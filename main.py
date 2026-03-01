import os
import datetime
import psycopg2
import pandas as pd
import secrets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084  # معرف المسؤول

PLANS = {
    'day': 1,
    'two_days': 2,
    'week': 7,
    'month': 30
}

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

# ==================== 4. المحرك الرياضي ====================
def sovereign_math_engine(b_num: str, suit: str, last_timestamp, current_timestamp):
    last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
    B = sum(int(d) for d in last_3 if d.isdigit())
    S = 1 if suit in ['♦️', '♥️'] else 2
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    R = (B * S) + delta_t
    prediction_code = 1 if (R % 2 == 0) else 0
    prediction_text = WINNER_NAMES[prediction_code]
    return prediction_text, prediction_code, R, delta_t, B, S

# ==================== 5. Bayesian Adaptive ====================
def bayesian_adjustment(prediction_code: int, current_hour: int, conn, min_samples: int = 15):
    try:
        period = get_time_period(current_hour)
        df = pd.read_sql("SELECT winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL ORDER BY id DESC LIMIT 200", conn)
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
        await update.message.reply_text("🔐 مرحبًا، أرسل مفتاح الاشتراك.")
        return
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️ ديناري", callback_data="s_♦️"), InlineKeyboardButton("♥️ قلب", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد", callback_data="s_♠️"), InlineKeyboardButton("♣️ كلبة", callback_data="s_♣️")]
    ]
    await update.message.reply_text(f"🏛️ مرحبًا! اشتراكك ({plan}) متبقي {remaining} يوم.", reply_markup=InlineKeyboardMarkup(kb))

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if activate_subscription(user_id, text):
        await update.message.reply_text("✅ تم تفعيل اشتراكك!")
    else:
        await update.message.reply_text("❌ المفتاح غير صالح أو مستخدم مسبقًا.")

async def generate_keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ مسؤول فقط")
        return
    generate_keys()
    await update.message.reply_text("🔑 تم إنشاء المفاتيح بنجاح.")

async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribed, plan, remaining = is_user_subscribed(user_id)
    if subscribed:
        await update.message.reply_text(f"✅ اشتراكك: {plan}, متبقي: {remaining} يوم.")
    else:
        await update.message.reply_text("❌ لا يوجد اشتراك نشط.")

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ أمر التحليل مؤقتًا غير مفعل.")  # يمكنك إعادة المنطق السابق هنا

async def model_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ أمر حالة النموذج مؤقتًا غير مفعل.")  # يمكنك إعادة المنطق السابق هنا

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ المعالجة النصية مؤقتًا غير مفعل.")  # يمكنك إعادة المنطق السابق هنا

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("⚠️ المعالجة الاختيارية مؤقتًا غير مفعلة.")  # يمكنك إعادة المنطق السابق هنا

# ==================== 7. التشغيل الرئيسي ====================
if __name__ == "__main__":
    init_subscription_table()
    generate_keys()
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("status", model_status))
    app.add_handler(CommandHandler("my_subscription", my_subscription))
    app.add_handler(CommandHandler("generate_keys", generate_keys_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("🚀 HADES V100.2 يعمل...")
    app.run_polling()
