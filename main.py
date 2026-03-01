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
    return WINNER_NAMES[pred_code], pred_code, delta_t

# ==================== 6. دوال التأكد من وجود الأعمدة ====================
def ensure_columns():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS prediction INTEGER;")
    cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS user_id BIGINT;")
    conn.commit()
    conn.close()

# ==================== 7. أوامر البوت ====================
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
        [InlineKeyboardButton("♦️", callback_data="s_♦️"),
         InlineKeyboardButton("♥️", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️", callback_data="s_♠️"),
         InlineKeyboardButton("♣️", callback_data="s_♣️")]
    ]
    remaining_text = f"اشتراكك ({plan}) متبقي {remaining} يوم." if subscribed else ""
    await update.message.reply_text(
        f"🏛️ **HADES V100.2**\n"
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
    """تحليل أداء التوقعات حسب الوقت"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL", conn)
        conn.close()

        if len(df) < 10:
            await update.message.reply_text("⚠️ البيانات غير كافية (نحتاج 10 جولات على الأقل).")
            return

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

        # تحليل الفترات
        period_order = ["morning", "afternoon", "evening", "night"]
        period_acc = df.groupby('period')['correct'].mean().reindex(period_order) * 100

        # تحليل الساعات (بحد أدنى 10 جولات)
        hour_stats = df.groupby('hour').agg(accuracy=('correct', 'mean'), count=('correct', 'count'))
        hour_stats = hour_stats[hour_stats['count'] >= 10]
        hour_acc = hour_stats['accuracy'] * 100

        report = "📊 **تحليل أداء HADES حسب الوقت**\n━━━━━━━━━━━━━━\n"
        for p in period_order:
            if p in period_acc and not pd.isna(period_acc[p]):
                emoji = {"morning": "🌅", "afternoon": "☀️", "evening": "🌇", "night": "🌙"}.get(p, "⏰")
                report += f"{emoji} {period_translate(p)}: {period_acc[p]:.1f}%\n"

        if not hour_acc.empty:
            report += "\n✅ **أفضل 3 ساعات:**\n"
            for h, acc in hour_acc.nlargest(3).items():
                report += f"🟢 {h:02d}:00 → {acc:.1f}%\n"
            report += "\n⚠️ **أسوأ 3 ساعات:**\n"
            for h, acc in hour_acc.nsmallest(3).items():
                report += f"🔴 {h:02d}:00 → {acc:.1f}%\n"

        report += f"\n📈 إجمالي الجولات: {len(df)}"
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def advanced_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحليل متقدم حسب آخر رقم والفترة"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT b_num, suit, winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL", conn)
        conn.close()

        if df.empty:
            await update.message.reply_text("❌ لا توجد بيانات.")
            return

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['last_digit'] = df['b_num'].astype(str).str[-1].astype(int)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

        # جدول محوري لكل last_digit وفترة
        pivot = df.pivot_table(index='last_digit', columns='period', values='correct', aggfunc='mean') * 100
        pivot = pivot.round(1).reindex(columns=["morning", "afternoon", "evening", "night"])

        report = "🔬 **تحليل متقدم (last_digit + فترة)**\n━━━━━━━━━━━━━━━\n"
        report += pivot.to_string()
        await update.message.reply_text(f"```\n{report}\n```")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def model_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض حالة النموذج (آخر 50 و200 جولة)"""
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

        report = "🧠 **حالة محرك HADES**\n━━━━━━━━━━━━━━\n"
        if acc_50:
            report += f"📉 آخر 50 جولة: {acc_50:.1f}%\n"
        report += f"📊 آخر 200 جولة: {acc_200:.1f}%\n"

        if acc_200 >= 65:
            status = "✅ ممتاز"
        elif acc_200 >= 58:
            status = "⚖️ مقبول"
        else:
            status = "🔻 ضعيف"
        report += f"\n**التقييم:** {status}"
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def delete_last_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف آخر إدخال للمستخدم"""
    user_id = update.effective_user.id
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT id FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("⚠️ لا يوجد إدخال سابق لك.")
        return
    cur.execute("DELETE FROM history WHERE id = %s", (row[0],))
    conn.commit()
    conn.close()
    await update.message.reply_text("🗑️ تم حذف آخر إدخال لك.")

async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحميل قاعدة البيانات (للمسؤول فقط)"""
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

# ==================== 8. المعالجات الأساسية ====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # إذا كان المستخدم غير مشترك، نتعامل مع الرسالة كمحاولة اشتراك
    sub, _, _ = is_user_subscribed(user_id)
    if not sub and user_id != ADMIN_ID:
        await subscribe(update, context)
        return

    # التحقق من التباعد الزمني للمستخدمين العاديين
    allowed, msg = can_user_play(user_id, context)
    if not allowed:
        await update.message.reply_text(msg)
        return

    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start.")
            return

        current_time = datetime.datetime.now()
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        last_time = row[0] if row else None
        conn.close()

        pred_text, pred_code, gap = sovereign_math_engine(text, context.user_data['suit'], last_time, current_time)

        # تخزين التوقع في user_data
        context.user_data['bonus'] = text
        context.user_data['prediction'] = pred_code
        context.user_data['current_time'] = current_time

        # حقن خطأ إذا كان streak كبير
        if user_id != ADMIN_ID and context.user_data.get('correct_streak', 0) >= MAX_CORRECT_STREAK:
            pred_code = inject_fake_prediction(pred_code)
            pred_text = WINNER_NAMES[pred_code]
            context.user_data['correct_streak'] = 0
            fake_warning = "\n⚠️ تم تعديل التوقع مؤقتاً.\n"
        else:
            fake_warning = ""

        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
        ]
        suit_color = "🔴" if context.user_data['suit'] in ['♦️', '♥️'] else "⚫"
        await update.message.reply_text(
            f"{fake_warning}"
            f"🎯 **التوقع:** {pred_text}\n"
            f"🎴 البذلة: {context.user_data['suit']} {suit_color}\n"
            f"⏱️ الفجوة: {gap} ثانية\n"
            f"━━━━━━━━━━━━━━\n"
            f"اختر النتيجة الحقيقية:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
        update_session_after_play(context)
    else:
        await update.message.reply_text("❌ أرسل رقماً صحيحاً (7 أرقام على الأقل).")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("s_"):
        suit = query.data[2:]
        context.user_data['suit'] = suit
        await query.edit_message_text(f"✅ تم اختيار {suit}.\n📥 أرسل رقم البونص:")

    elif query.data.startswith("save_"):
        winner_db = query.data[5:]
        pred_code = context.user_data.get('prediction')
        if pred_code is None:
            await query.edit_message_text("❌ خطأ: لا يوجد توقع. ابدأ من جديد /start.")
            return

        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO history (b_num, suit, winner, timestamp, prediction, user_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    context.user_data['bonus'],
                    context.user_data['suit'],
                    winner_db,
                    context.user_data['current_time'],
                    pred_code,
                    update.effective_user.id
                )
            )
            conn.commit()
            conn.close()

            pred_winner = WINNER_NAMES[pred_code]
            is_correct = "✅" if winner_db == pred_winner else "❌"

            # تحديث streak للمستخدمين العاديين
            user_id = update.effective_user.id
            if user_id != ADMIN_ID:
                if is_correct == "✅":
                    context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
                else:
                    context.user_data['correct_streak'] = 0

            # أزرار بعد الحفظ
            keyboard = [
                [InlineKeyboardButton("🔄 بدء جولة جديدة", callback_data="new_round"),
                 InlineKeyboardButton("🗑️ حذف آخر إدخال", callback_data="delete_last")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"{is_correct} **تم التسجيل**\n\n"
                f"🎯 توقعنا: {pred_winner}\n"
                f"🏆 النتيجة: {winner_db}\n"
                f"━━━━━━━━━━━━━━\n"
                f"/performance - تحليل\n"
                f"/advanced - تحليل متقدم\n"
                f"/status - حالة النموذج\n"
                f"/delete - حذف آخر إدخال",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {e}")

    elif query.data == "new_round":
        await start(update, context)

    elif query.data == "delete_last":
        user_id = update.effective_user.id
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT id FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM history WHERE id = %s", (row[0],))
            conn.commit()
            await query.edit_message_text("🗑️ تم حذف آخر إدخال لك.\nأرسل /start لبدء جولة جديدة.")
        else:
            await query.edit_message_text("⚠️ لا يوجد إدخال سابق لك.")
        conn.close()

# ==================== 9. التشغيل الرئيسي ====================
if __name__ == "__main__":
    ensure_columns()
    init_subscription_table()
    # توليد مفاتيح أولية إذا لم توجد
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM subscription_keys")
    if cur.fetchone()[0] == 0:
        generate_keys()
    conn.close()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("advanced", advanced_analysis))
    app.add_handler(CommandHandler("status", model_status))
    app.add_handler(CommandHandler("generate_keys", generate_keys_command))
    app.add_handler(CommandHandler("mysub", my_subscription))
    app.add_handler(CommandHandler("delete", delete_last_entry))
    app.add_handler(CommandHandler("download", download_database))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🚀 HADES V100.2 يعمل... (مع تحليل زمني)")
    app.run_polling()
