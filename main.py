import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
import secrets
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

PLANS = {'day': 1, 'two_days': 2, 'week': 7, 'month': 30}

PLAY_SESSION_MINUTES = 30
COOL_DOWN_1_MIN = (5, 10)
COOL_DOWN_2_MIN = 15
MAX_CORRECT_STREAK = 10

WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

CONFIDENCE_THRESHOLD = 0.65

# ==================== 2. دوال تحليل الوقت ====================
def get_time_period(hour):
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

def period_translate(period):
    return {"morning": "🌅 الصباح", "afternoon": "☀️ الظهر", "evening": "🌇 المساء", "night": "🌙 الليل"}.get(period, period)

# ==================== 3. دوال إدارة الاشتراكات ====================
def init_subscription_table():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscription_keys (
            id SERIAL PRIMARY KEY,
            key_code VARCHAR(50) UNIQUE NOT NULL,
            plan VARCHAR(20) NOT NULL,
            is_used BOOLEAN DEFAULT FALSE,
            used_by BIGINT,
            used_at TIMESTAMP,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def generate_keys():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    for plan in PLANS.keys():
        for _ in range(5):
            key = secrets.token_urlsafe(16)
            try:
                cur.execute("INSERT INTO subscription_keys (key_code, plan) VALUES (%s, %s)", (key, plan))
            except psycopg2.IntegrityError:
                conn.rollback()
                continue
    conn.commit()
    conn.close()

def is_user_subscribed(user_id):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("""
        SELECT plan, expires_at FROM subscription_keys 
        WHERE used_by = %s AND expires_at > NOW() 
        ORDER BY expires_at DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        plan, expires = row
        remaining = (expires - datetime.datetime.now()).days
        return True, plan, remaining
    return False, None, 0

def activate_subscription(user_id, key_code):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT id, plan, is_used FROM subscription_keys WHERE key_code = %s", (key_code,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    key_id, plan, is_used = row
    if is_used:
        conn.close()
        return False
    days = PLANS.get(plan)
    if not days:
        conn.close()
        return False
    expires_at = datetime.datetime.now() + datetime.timedelta(days=days)
    cur.execute("""
        UPDATE subscription_keys 
        SET is_used = TRUE, used_by = %s, used_at = NOW(), expires_at = %s
        WHERE id = %s
    """, (user_id, expires_at, key_id))
    conn.commit()
    conn.close()
    return True

# ==================== 4. دوال إدارة التباعد الزمني ====================
def init_user_session(context):
    if 'session_start' not in context.user_data:
        context.user_data['session_start'] = None
        context.user_data['session_play_minutes'] = 0
        context.user_data['cool_until'] = None
        context.user_data['cool_stage'] = 0
        context.user_data['correct_streak'] = 0

def can_user_play(user_id, context):
    if user_id == ADMIN_ID:
        return True, ""
    init_user_session(context)
    now = datetime.datetime.now()
    cool_until = context.user_data.get('cool_until')
    if cool_until and now < cool_until:
        remaining = (cool_until - now).seconds // 60
        remaining_seconds = (cool_until - now).seconds % 60
        return False, f"⏳ تبريد {remaining} د و{remaining_seconds} ث."
    if context.user_data['session_start'] is None:
        context.user_data['session_start'] = now
        context.user_data['session_play_minutes'] = 0
        return True, ""
    session_duration = (now - context.user_data['session_start']).total_seconds() / 60
    played = context.user_data['session_play_minutes'] + session_duration
    if played >= PLAY_SESSION_MINUTES:
        if context.user_data['cool_stage'] == 0:
            cool_minutes = random.randint(COOL_DOWN_1_MIN[0], COOL_DOWN_1_MIN[1])
            context.user_data['cool_stage'] = 1
        else:
            cool_minutes = COOL_DOWN_2_MIN
        context.user_data['cool_until'] = now + datetime.timedelta(minutes=cool_minutes)
        context.user_data['session_start'] = None
        context.user_data['session_play_minutes'] = 0
        return False, f"⏸️ انتهت الجلسة. انتظر {cool_minutes} د."
    return True, ""

def update_session_after_play(context):
    if context.user_data.get('session_start') is None:
        return
    now = datetime.datetime.now()
    session_duration = (now - context.user_data['session_start']).total_seconds() / 60
    context.user_data['session_play_minutes'] += session_duration
    context.user_data['session_start'] = now

def inject_fake_prediction(pred_code):
    return 1 if pred_code == 0 else 0

# ==================== 5. المحرك الرياضي الأساسي ====================
def sovereign_math_engine(b_num, suit, last_timestamp, current_timestamp):
    last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
    B = sum(int(d) for d in last_3 if d.isdigit())
    S = 1 if suit in ['♦️', '♥️'] else 2
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    R = (B * S) + delta_t
    pred_code = 1 if (R % 2 == 0) else 0
    return WINNER_NAMES[pred_code], pred_code, R, delta_t, B, S

# ==================== 6. التحليل البايزي (مع استبعاد غير الرقمي) ====================
def bayesian_analysis(conn, current_hour, min_samples=30):
    try:
        df = pd.read_sql("""
            SELECT winner, timestamp 
            FROM history 
            WHERE winner IS NOT NULL AND b_num ~ '^[0-9]+$'
        """, conn)
        if len(df) < min_samples:
            return None
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code'])
        periods = ['morning', 'afternoon', 'evening', 'night']
        bayesian_probs = {}
        for period in periods:
            period_data = df[df['period'] == period]
            if len(period_data) >= min_samples:
                total = len(period_data)
                p_rai = (period_data['winner_code'] == 0).sum() / total
                p_thawr = (period_data['winner_code'] == 1).sum() / total
                p_tie = (period_data['winner_code'] == 2).sum() / total
                bayesian_probs[period] = (p_rai, p_thawr, p_tie)
            else:
                bayesian_probs[period] = None
        return bayesian_probs
    except Exception as e:
        print(f"Bayesian Error: {e}")
        return None

# ==================== 7. القرار الهجين ====================
def hybrid_prediction(b_num, suit, last_timestamp, current_timestamp, bayesian_probs):
    math_text, math_code, R, gap, B, S = sovereign_math_engine(b_num, suit, last_timestamp, current_timestamp)
    if bayesian_probs is None:
        return math_text, math_code, R, gap, B, S, "معادلة فقط"
    current_period = get_time_period(current_timestamp.hour)
    period_probs = bayesian_probs.get(current_period)
    if period_probs is None:
        return math_text, math_code, R, gap, B, S, "معادلة فقط (لا بيانات كافية للفترة)"
    p_rai, p_thawr, p_tie = period_probs
    math_confidence = 0.7
    probs = [p_rai, p_thawr, p_tie]
    probs_sorted = sorted(probs, reverse=True)
    bayes_confidence = probs_sorted[0] - probs_sorted[1]
    if bayes_confidence > CONFIDENCE_THRESHOLD:
        if probs_sorted[0] == p_rai:
            final_code = 0
        elif probs_sorted[0] == p_thawr:
            final_code = 1
        else:
            final_code = 2
        final_text = WINNER_NAMES[final_code]
        return final_text, final_code, R, gap, B, S, f"بايزي (ثقة {bayes_confidence:.2f})"
    elif math_confidence > CONFIDENCE_THRESHOLD:
        return math_text, math_code, R, gap, B, S, "معادلة (ثقة افتراضية)"
    else:
        weighted_rai = 0.7 * (1 if math_code == 0 else 0) + 0.3 * p_rai
        weighted_thawr = 0.7 * (1 if math_code == 1 else 0) + 0.3 * p_thawr
        weighted_tie = 0.7 * (1 if math_code == 2 else 0) + 0.3 * p_tie
        if weighted_rai > weighted_thawr and weighted_rai > weighted_tie:
            final_code = 0
        elif weighted_thawr > weighted_rai and weighted_thawr > weighted_tie:
            final_code = 1
        else:
            final_code = 2
        final_text = WINNER_NAMES[final_code]
        return final_text, final_code, R, gap, B, S, f"مزج: معادلة {math_text}, بايزي راعي {p_rai:.2f} ثور {p_thawr:.2f}"

# ==================== 8. أوامر البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribed, plan, remaining = is_user_subscribed(user_id)
    if not subscribed and user_id != ADMIN_ID:
        await update.message.reply_text(
            "🔐 **مرحبًا بك في HADES**\n"
            "للاستخدام، أدخل مفتاح اشتراك صالح.\n"
            "أرسل المفتاح الآن."
        )
        return
    context.user_data.clear()
    init_user_session(context)
    kb = [
        [InlineKeyboardButton("♦️ ديناري (أحمر)", callback_data="s_♦️"),
         InlineKeyboardButton("♥️ قلب (أحمر)", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد (أسود)", callback_data="s_♠️"),
         InlineKeyboardButton("♣️ كلبة (أسود)", callback_data="s_♣️")]
    ]
    remaining_text = f"اشتراكك ({plan}) متبقي {remaining} يوم." if subscribed else ""
    await update.message.reply_text(
        f"🏛️ **HADES V100.2**\n"
        f"محرك هجين (معادلة + بايزي)\n"
        f"{remaining_text}\n\n"
        "🎴 اختر نوع البذلة:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if activate_subscription(user_id, text):
        await update.message.reply_text("✅ تم تفعيل الاشتراك! أرسل /start للبدء.")
    else:
        await update.message.reply_text("❌ مفتاح غير صالح أو مستخدم.")

async def generate_keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمسؤول فقط.")
        return
    generate_keys()
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT key_code, plan FROM subscription_keys WHERE is_used = FALSE ORDER BY plan, id")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("⚠️ لا توجد مفاتيح.")
        return
    result = "🔑 **المفاتيح المتاحة:**\n\n"
    plans_keys = {plan: [] for plan in PLANS}
    for key, plan in rows:
        plans_keys[plan].append(key)
    for plan in PLANS:
        plan_name = {'day': '📆 يوم', 'two_days': '📆📆 يومين', 'week': '📅 أسبوع', 'month': '📅 شهر'}.get(plan, plan)
        keys = plans_keys[plan]
        result += f"**{plan_name}** ({len(keys)}):\n"
        for k in keys:
            result += f"`{k}`\n"
        result += "\n"
    await update.message.reply_text(result, parse_mode='Markdown')

async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub, plan, rem = is_user_subscribed(user_id)
    if sub or user_id == ADMIN_ID:
        name = {'day': 'يوم', 'two_days': 'يومين', 'week': 'أسبوع', 'month': 'شهر'}.get(plan, plan) if sub else "مشرف"
        await update.message.reply_text(f"✅ مشترك في {name}، متبقي {rem if sub else 'غير محدود'} يوم.")
    else:
        await update.message.reply_text("❌ لا يوجد اشتراك.")

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub, _, _ = is_user_subscribed(user_id)
    if not sub and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 تحتاج اشتراك.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, prediction, timestamp, suit FROM history WHERE prediction IS NOT NULL", conn)
        conn.close()
        if len(df) < 10:
            await update.message.reply_text("⚠️ بيانات غير كافية.")
            return
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)
        period_order = ["morning", "afternoon", "evening", "night"]
        period_acc = df.groupby('period')['correct'].mean().reindex(period_order) * 100
        hour_stats = df.groupby('hour').agg(accuracy=('correct','mean'), count=('correct','count'))
        hour_stats = hour_stats[hour_stats['count'] >= 10]
        hour_acc = hour_stats['accuracy'] * 100
        suit_stats = df.groupby('suit').agg(accuracy=('correct','mean'), count=('correct','count')) * 100
        report = "📊 **تقرير الأداء**\n━━━━━━━━━━\n"
        for p in period_order:
            if p in period_acc and not pd.isna(period_acc[p]):
                emoji = "🟢" if period_acc[p] >= 60 else "🟡" if period_acc[p] >= 50 else "🔴"
                report += f"{emoji} {period_translate(p)}: {period_acc[p]:.1f}%\n"
        report += f"\n📈 الإجمالي: {df['correct'].mean()*100:.1f}% ({len(df)} جولة)\n"
        if not hour_acc.empty:
            report += "\n🏆 أفضل 3 ساعات:\n"
            for h, acc in hour_acc.nlargest(3).items():
                report += f"🟢 {h:02d}:00 → {acc:.1f}%\n"
            report += "\n⚠️ أسوأ 3 ساعات:\n"
            for h, acc in hour_acc.nsmallest(3).items():
                report += f"🔴 {h:02d}:00 → {acc:.1f}%\n"
        if not suit_stats.empty:
            report += "\n🎴 الدقة حسب البذلة:\n"
            for suit, row in suit_stats.iterrows():
                emoji = "🟢" if row['accuracy'] >= 60 else "🟡" if row['accuracy'] >= 50 else "🔴"
                report += f"{emoji} {suit}: {row['accuracy']:.1f}% ({int(row['count'])} جولة)\n"
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def model_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub, _, _ = is_user_subscribed(user_id)
    if not sub and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 تحتاج اشتراك.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL ORDER BY id DESC LIMIT 200", conn)
        conn.close()
        if len(df) < 10:
            await update.message.reply_text("⚠️ بيانات غير كافية.")
            return
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)
        acc_50 = df.head(50)['correct'].mean() * 100 if len(df) >= 50 else None
        acc_200 = df['correct'].mean() * 100
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        hour_stats = df.groupby('hour').agg(acc=('correct','mean'), cnt=('correct','count'))
        hour_stats = hour_stats[hour_stats['cnt'] >= 10]
        best_hour = hour_stats['acc'].idxmax() if not hour_stats.empty else None
        worst_hour = hour_stats['acc'].idxmin() if not hour_stats.empty else None
        status = "🔻 ضعيف"
        if acc_200 >= 65: status = "✅ ممتاز"
        elif acc_200 >= 58: status = "⚖️ مقبول"
        report = "🧠 **حالة المحرك**\n━━━━━━━━━━\n"
        if acc_50: report += f"📉 آخر 50 جولة: {acc_50:.1f}%\n"
        report += f"📊 آخر 200 جولة: {acc_200:.1f}%\n"
        if best_hour: report += f"\n🏆 أفضل ساعة: {best_hour:02d}:00\n"
        if worst_hour: report += f"⚠️ أسوأ ساعة: {worst_hour:02d}:00\n"
        report += f"\n**التقييم:** {status}"
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 9. أمر الحذف للمستخدم العادي ====================
async def delete_last_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف آخر إدخال للمستخدم الحالي."""
    user_id = update.effective_user.id
    # التحقق من الاشتراك (الأدمن غير مشمول)
    sub, _, _ = is_user_subscribed(user_id)
    if not sub and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 تحتاج اشتراك.")
        return
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    # البحث عن آخر إدخال للمستخدم
    cur.execute("SELECT id FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("⚠️ لا يوجد إدخال سابق لك.")
        return
    last_id = row[0]
    cur.execute("DELETE FROM history WHERE id = %s", (last_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("🗑️ تم حذف آخر إدخال لك.")

# ==================== 10. أمر التحميل للأدمن فقط ====================
async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمسؤول فقط.")
        return
    status = await update.message.reply_text("📊 جاري التصدير...")
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT * FROM history ORDER BY id ASC", conn)
        conn.close()
        filename = f"Observer_Log_{datetime.date.today()}.xlsx"
        df.to_excel(filename, index=False)
        with open(filename, "rb") as f:
            await update.message.reply_document(document=f, filename=filename, caption=f"📊 {len(df)} جولة.")
        os.remove(filename)
        await status.delete()
    except Exception as e:
        await status.edit_text(f"❌ فشل: {e}")

# ==================== 11. المعالجات الأساسية ====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    # إذا كان المستخدم غير مشترك، نعتبر الرسالة محاولة اشتراك
    sub, _, _ = is_user_subscribed(user_id)
    if not sub and user_id != ADMIN_ID:
        await subscribe(update, context)
        return
    # التحقق من التباعد الزمني للمستخدمين العاديين
    allowed, msg = can_user_play(user_id, context)
    if not allowed:
        await update.message.reply_text(msg)
        return
    # م
