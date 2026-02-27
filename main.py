import os
import sys
import datetime
import requests
import asyncio
import psycopg2
from psycopg2.extras import DictCursor

# --- جلب الإعدادات من Railway Variables ---
TOKEN = os.getenv("TOKEN")
API_KEY_PRIMARY = os.getenv("API_KEY_PRIMARY")
API_KEY_NVIDIA = os.getenv("API_KEY_NVIDIA")
DATABASE_URL = os.getenv("DATABASE_URL")

MODEL_GEMINI = "google/gemini-2.0-flash-001"
MODEL_NVIDIA = "nvidia/llama-3.1-nemotron-70b-instruct"

# --- التأكد من استيراد المكتبات بنجاح ---
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes
except ImportError:
    print("❌ خطأ: المكتبات غير مثبتة. تأكد من ملف requirements.txt")
    sys.exit(1)

# ==================== إدارة قاعدة البيانات PostgreSQL ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id SERIAL PRIMARY KEY,
                    b_num TEXT, suit TEXT, hand TEXT, winner TEXT, timestamp TIMESTAMP
                )
            """)
            conn.commit()

# ==================== محرك الذكاء الاصطناعي الهجين ====================
async def fetch_prediction(model, api_key, bonus, suit, hand, history):
    prompt = f"""تحليل تاريخي لآخر الجولات: {history}
الجولة الحالية: بونص {bonus}، ورقة {suit}، يد {hand}.
بناءً على الأنماط، هل النتيجة القادمة (ثور) أم (راعي)؟ 
أجب بصيغة: النتيجة: (ثور/راعي) | الثقة: %"""
    
    try:
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
            timeout=15)
        return resp.json()['choices'][0]['message']['content'].lower()
    except:
        return "فشل الاتصال"

# ==================== معالجات البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    # حساب الجولات من PostgreSQL
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM history")
            count = cur.fetchone()[0]
            
    kb = [[InlineKeyboardButton("👑 رويال", callback_data="h_رويال"), InlineKeyboardButton("🌈 ستريت فلاش", callback_data="h_ستريت_فلاش")],
          [InlineKeyboardButton("🏠 فل هاوس", callback_data="h_فل_هاوس"), InlineKeyboardButton("📏 ستريت", callback_data="h_ستريت")],
          [InlineKeyboardButton("✌️ زوجين", callback_data="h_زوجين"), InlineKeyboardButton("🃏 الأكبر", callback_data="h_أكبر")]]
    
    await update.message.reply_text(
        f"🏛️ **الكيان الموحد V60.0** ✅\n📊 متصل بـ PostgreSQL ({count} جولة مخزنة)\n\nاختر اليد الحالية:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    
    if data.startswith("h_"):
        context.user_data['hand'] = data[2:]
        kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️"),
               InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
        await query.edit_message_text(f"اليد المختار: {data[2:]}\nاختر نوع الورقة:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ تم تحديد {context.user_data['hand']} - {data[2:]}\n📥 أرسل رقم البونص (7-8 أرقام):")

    elif data.startswith("save_"):
        winner = data.split("_")[1]
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, hand, winner, timestamp) VALUES (%s, %s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], context.user_data['hand'], winner, datetime.datetime.now()))
                conn.commit()
        await query.edit_message_text(f"✅ تم حفظ النتيجة: {winner}\nاضغط /start لجولة جديدة.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        context.user_data['bonus'] = text
        load = await update.message.reply_text("🧬 جاري التحليل المزدوج ومطابقة الأنماط...")
        
        # جلب تاريخ حقيقي من قاعدة البيانات للسياق
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT b_num, winner FROM history ORDER BY id DESC LIMIT 20")
                rows = cur.fetchall()
        history = " | ".join([f"{r['b_num']}:{r['winner']}" for r in rows]) if rows else "قاعدة البيانات جديدة"

        # طلب التوقعات
        g_pred = await fetch_prediction(MODEL_GEMINI, API_KEY_PRIMARY, text, context.user_data['suit'], context.user_data['hand'], history)
        n_pred = await fetch_prediction(MODEL_NVIDIA, API_KEY_NVIDIA, text, context.user_data['suit'], context.user_data['hand'], history)

        report = (f"🎯 **نتائج التحليل:**\n━━━━━━━━━━━━\n"
                  f"🧠 **Gemini:** {g_pred}\n"
                  f"🤖 **Nvidia:** {n_pred}\n━━━━━━━━━━━━\n"
                  f"✅ اختر ما حدث فعلياً للتخزين:")
        
        kb = [[InlineKeyboardButton("🐂 ثور", callback_data="save_ثور"), InlineKeyboardButton("🐑 راعي", callback_data="save_راعي")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await load.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("🚀 V60.0 جاهز للعمل على Railway")
    app.run_polling()
