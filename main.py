import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
import secrets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084  # معرف المسؤول

# خطط الاشتراك (بالأيام)
PLANS = {
    'day': 1,
    'two_days': 2,
    'week': 7,
    'month': 30
}

# خريطة تحويل أسماء الفائزين إلى أرقام
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}

WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

# ==================== 2. دوال تحليل الوقت ====================
def get_time_period(hour: int) -> str:
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

def period_translate(period: str) -> str:
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
        cur.execute("SELECT COUNT(*) FROM subscription_keys WHERE plan = %s AND is_used = FALSE", (plan,))
        count = cur.fetchone()[0]
        if count == 0:
            for _ in range(5):
                key = secrets.token_urlsafe(16)
                cur.execute("INSERT INTO subscription_keys (key_code, plan) VALUES (%s, %s)", (key, plan))
    
    conn.commit()
    conn.close()

def is_user_subscribed(user_id: int) -> tuple:
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
        plan = row[0]
        expires = row[1]
        remaining = (expires - datetime.datetime.now()).days
        return True, plan, remaining
    return False, None, 0

def activate_subscription(user_id: int, key_code: str) -> bool:
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

# ==================== 4. المحرك الرياضي الأساسي ====================
def sovereign_math_engine(b_num: str, suit: str, last_timestamp, current_timestamp):
    last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
    B = sum(int(d) for d in last_3 if d.isdigit())
    S = 1 if suit in ['♦️', '♥️'] else 2
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    R = (B * S) + delta_t
    prediction_code = 1 if (R % 2 == 0) else 0
    prediction_text = WINNER_NAMES[prediction_code]
    return prediction_text, prediction_code, R, delta_t, B, S

# ==================== 5. Bayesian Adaptive Layer ====================
def bayesian_adjustment(prediction_code: int, current_hour: int, conn, min_samples: int = 15):
    try:
        period = get_time_period(current_hour)
        
        df = pd.read_sql("""
            SELECT winner, prediction, timestamp 
            FROM history 
            WHERE prediction IS NOT NULL 
            ORDER BY id DESC 
            LIMIT 200
        """, conn)
        
        if len(df) < min_samples:
            return prediction_code, None, None
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        
        period_data = df[df['period'] == period]
        if len(period_data) < min_samples:
            return prediction_code, None, None
        
        period_data['winner_code'] = period_data['winner'].map(WINNER_MAP)
        period_data = period_data.dropna(subset=['winner_code'])
        
        if len(period_data) < min_samples:
            return prediction_code, None, None
        
        total = len(period_data)
        p_rai = (period_data['winner_code'] == 0).sum() / total
        p_thawr = (period_data['winner_code'] == 1).sum() / total
        
        if prediction_code == 0:
            prior_rai, prior_thawr = 0.85, 0.15
        else:
            prior_rai, prior_thawr = 0.15, 0.85
        
        norm_rai = prior_rai * p_rai
        norm_thawr = prior_thawr * p_thawr
        
        if (norm_rai + norm_thawr) == 0:
            return prediction_code, None, None
        
        posterior_rai = norm_rai / (norm_rai + norm_thawr)
        posterior_thawr = norm_thawr / (norm_rai + norm_thawr)
        
        adjusted_code = 0 if posterior_rai > posterior_thawr else 1
        confidence_diff = abs(posterior_rai - posterior_thawr)
        
        return adjusted_code, (posterior_rai, posterior_thawr), confidence_diff
        
    except Exception as e:
        print(f"Bayesian Error: {e}")
        return prediction_code, None, None

# ==================== 6. أوامر البوت ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribed, plan, remaining = is_user_subscribed(user_id)
    
    if not subscribed:
        await update.message.reply_text(
            "🔐 **مرحبًا بك في HADES V100.2**\n"
            "للاستخدام، يجب عليك إدخال مفتاح اشتراك صالح.\n"
            "أرسل المفتاح الآن، أو تواصل مع المسؤول للحصول على مفتاح."
        )
        return
    
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️ ديناري (أحمر)", callback_data="s_♦️"), 
         InlineKeyboardButton("♥️ قلب (أحمر)", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد (أسود)", callback_data="s_♠️"), 
         InlineKeyboardButton("♣️ كلبة (أسود)", callback_data="s_♣️")]
    ]
    remaining_text = f"اشتراكك ({plan}) متبقي {remaining} يوم." if remaining > 0 else ""
    await update.message.reply_text(
        f"🏛️ **الكيان السيادي HADES V100.2**\n"
        f"محرك تنبؤي بايزي متطور مع تحليل زمني.\n"
        f"{remaining_text}\n\n"
        "🎴 اختر نوع البذلة:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if activate_subscription(user_id, text):
        await update.message.reply_text("✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن استخدام /start للبدء.")
    else:
        await update.message.reply_text("❌ المفتاح غير صالح أو مستخدم مسبقًا.")

async def generate_keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر متاح للمسؤول فقط.")
        return
    
    generate_keys()
    
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    df = pd.read_sql("SELECT key_code, plan FROM subscription_keys WHERE is_used = FALSE", conn)
    conn.close()
    
    if df.empty:
        await update.message.reply_text("لا توجد مفاتيح غير مستخدمة حاليًا.")
        return
    
    result = "🔑 **المفاتيح المتاحة:**\n\n"
    for plan in PLANS.keys():
        keys = df[df['plan'] == plan]['key_code'].tolist()
        plan_name = {
            'day': '📆 يوم',
            'two_days': '📆📆 يومين',
            'week': '📅 أسبوع',
            'month': '📅 شهر'
        }.get(plan, plan)
        result += f"**{plan_name}**:\n"
        if keys:
            for k in keys:
                result += f"`{k}`\n"
        else:
            result += "لا توجد مفاتيح.\n"
        result += "\n"
    
    await update.message.reply_text(result, parse_mode='Markdown')

async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribed, plan, remaining = is_user_subscribed(user_id)
    
    if subscribed:
        plan_name = {'day': 'يوم', 'two_days': 'يومين', 'week': 'أسبوع', 'month': 'شهر'}.get(plan, plan)
        await update.message.reply_text(f"✅ أنت مشترك في خطة **{plan_name}**.\n⏳ متبقي: {remaining} يوم.")
    else:
        await update.message.reply_text("❌ لا يوجد اشتراك نشط. استخدم /start وأدخل مفتاحًا صالحًا.")

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribed, _, _ = is_user_subscribed(user_id)
    if not subscribed:
        await update.message.reply_text("🔐 يجب أن يكون لديك اشتراك صالح لاستخدام هذا الأمر.")
        return
    
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, prediction, timestamp, suit FROM history WHERE prediction IS NOT NULL", conn)
        conn.close()

        if len(df) < 10:
            await update.message.reply_text("⚠️ البيانات غير كافية.")
            return

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

        if len(df) < 10:
            await update.message.reply_text("⚠️ بيانات غير صالحة بعد التنظيف.")
            return

        period_order = ["morning", "afternoon", "evening", "night"]
        period_accuracy = df.groupby('period')['correct'].mean().reindex(period_order) * 100

        hour_stats = df.groupby('hour').agg(accuracy=('correct', 'mean'), count=('correct', 'count'))
        hour_stats = hour_stats[hour_stats['count'] >= 10]
        hour_accuracy = hour_stats['accuracy'] * 100

        suit_stats = df.groupby('suit').agg(accuracy=('correct', 'mean'), count=('correct', 'count'))
        suit_stats['accuracy'] *= 100

        report = "📊 **تقرير أداء HADES**\n━━━━━━━━━━━━━━\n"
        
        report += "**🕐 الدقة حسب الفترة:**\n"
        for p in period_order:
            if p in period_accuracy and not pd.isna(period_accuracy[p]):
                emoji = "🟢" if period_accuracy[p] >= 60 else "🟡" if period_accuracy[p] >= 50 else "🔴"
                report += f"{emoji} {period_translate(p)}: {period_accuracy[p]:.1f}%\n"
        
        report += f"\n📈 **الدقة العامة:** {df['correct'].mean()*100:.1f}% ({len(df)} جولة)\n"

        if not hour_accuracy.empty:
            report += "\n🏆 **أفضل 3 ساعات:**\n"
            for h, acc in hour_accuracy.nlargest(3).items():
                report += f"🟢 {h:02d}:00 → {acc:.1f}%\n"
            
            report += "\n⚠️ **أسوأ 3 ساعات:**\n"
            for h, acc in hour_accuracy.nsmallest(3).items():
                report += f"🔴 {h:02d}:00 → {acc:.1f}%\n"

        if not suit_stats.empty:
            report += "\n🎴 **الدقة حسب البذلة:**\n"
            for suit, row in suit_stats.iterrows():
                emoji = "🟢" if row['accuracy'] >= 60 else "🟡" if row['accuracy'] >= 50 else "🔴"
                report += f"{emoji} {suit}: {row['accuracy']:.1f}% ({int(row['count'])} جولة)\n"

        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في التحليل: {e}")

async def model_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribed, _, _ = is_user_subscribed(user_id)
    if not subscribed:
        await update.message.reply_text("🔐 يجب أن يكون لديك اشتراك صالح.")
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
        hour_stats = df.groupby('hour').agg(acc=('correct', 'mean'), cnt=('correct', 'count'))
        hour_stats = hour_stats[hour_stats['cnt'] >= 10]
        
        best_hour = worst_hour = None
        if not hour_stats.empty:
            best_hour = hour_stats['acc'].idxmax()
            worst_hour = hour_stats['acc'].idxmin()

        status = "🔻 ضعيف"
        if acc_200 >= 65: status = "✅ ممتاز"
        elif acc_200 >= 58: status = "⚖️ مقبول"

        report = "🧠 **حالة محرك HADES**\n━━━━━━━━━━━━━━\n"
        if acc_50: report += f"📉 آخر 50 جولة: {acc_50:.1f}%\n"
        report += f"📊 آخر 200 جولة: {acc_200:.1f}%\n"
        
        if best_hour is not None:
            report += f"\n🏆 أفضل ساعة: {best_hour:02d}:00\n"
            report += f"⚠️ أسوأ ساعة: {worst_hour:02d}:00\n"
        
        report += f"\n**التقييم:** {status}"
        
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 7. المعالجات الأساسية ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    subscribed, _, _ = is_user_subscribed(user_id)
    if not subscribed:
        await subscribe(update, context)
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

        pred_text, pred_code, R, gap, B, S = sovereign_math_engine(text, context.user_data['suit'], last_time, current_time)

        adjusted_code, posteriors, confidence = bayesian_adjustment(pred_code, current_time.hour, conn)
        
        cur.close()
        conn.close()

        warning_text = ""
        if adjusted_code is not None and adjusted_code != pred_code and posteriors is not None:
            pred_code = adjusted_code
            pred_text = WINNER_NAMES[pred_code]
            p_rai, p_thawr = posteriors
            warning_text = (
                f"⚠️ **تعديل بايزي:**\n"
                f"المعادلة: {WINNER_NAMES[1 if (R % 2 == 0) else 0]} | "
                f"البيانات: راعي {p_rai*100:.0f}% vs ثور {p_thawr*100:.0f}%\n"
                f"→ التوقع المعدل: {pred_text}\n\n"
            )
        elif posteriors is not None:
            p_rai, p_thawr = posteriors
            warning_text = (
                f"ℹ️ **دعم بايزي:** "
                f"التاريخ يفضل {WINNER_NAMES[0] if p_rai > p_thawr else WINNER_NAMES[1]} "
                f"({max(p_rai, p_thawr)*100:.0f}%)\n\n"
            )

        context.user_data['bonus'] = text
        context.user_data['prediction_code'] = pred_code
        context.user_data['current_time'] = current_time

        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
        ]

        suit_color = "🔴" if context.user_data['suit'] in ['♦️', '♥️'] else "⚫"
        
        await update.message.reply_text(
            f"{warning_text}"
            f"🎯 **التوقع النهائي:** {pred_text}\n"
            f"🎴 البذلة: {context.user_data['suit']} {suit_color}\n"
            f"🔢 المعادلة: B={B} × S={S} + ΔT={gap} → R={R}\n"
            f"━━━━━━━━━━━━━━\n"
            f"اختر النتيجة الحقيقية:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )

    else:
        await update.message.reply_text("❌ أدخل رقم صحيح (7 أرقام على الأقل).")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("s_"):
        suit = query.data[2:]
        context.user_data['suit'] = suit
        color = "🔴 حمراء" if suit in ['♦️', '♥️'] else "⚫ سوداء"
        await query.edit_message_text(f"✅ تم اختيار: {suit} ({color})\n📥 أرسل رقم البونص:")

    elif query.data.startswith("save_"):
        winner_db = query.data[5:]
        pred_code = context.user_data.get('prediction_code')
        
        if pred_code is None:
            await query.edit_message_text("❌ خطأ: لا يوجد توقع مخزن.")
            return

        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO history (b_num, suit, winner, timestamp, prediction) 
                VALUES (%s, %s, %s, %s, %s)
            """, (
                context.user_data['bonus'],
                context.user_data['suit'],
                winner_db,
                context.user_data['current_time'],
                pred_code
            ))
            conn.commit()
            conn.close()

            pred_winner = WINNER_NAMES[pred_code]
            is_correct = "✅" if winner_db == pred_winner else "❌"
            
            await query.edit_message_text(
                f"{is_correct} **تم التسجيل**\n\n"
                f"🎯 توقعنا: {pred_winner}\n"
                f"🏆 النتيجة: {winner_db}\n"
                f"━━━━━━━━━━━━━━\n"
                f"/performance - التحليل\n"
                f"/status - حالة النموذج",
                parse_mode='Markdown'
            )
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {e}")

# ==================== 8. التشغيل الرئيسي ====================
if __name__ == "__main__":
    init_subscription_table()
    generate_keys()
    
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("
