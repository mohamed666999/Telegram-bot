import os
import sys
import datetime
import requests
import asyncio
import psycopg2
from psycopg2.extras import DictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- جلب الإعدادات من Variables (Railway) ---
TOKEN = os.getenv("TOKEN")
API_KEY_PRIMARY = os.getenv("API_KEY_PRIMARY")
API_KEY_NVIDIA = os.getenv("API_KEY_NVIDIA")
DATABASE_URL = os.getenv("DATABASE_URL")

MODEL_GEMINI = "google/gemini-2.0-flash-001"
MODEL_NVIDIA = "nvidia/llama-3.1-nemotron-70b-instruct"

# ==================== إدارة قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id SERIAL PRIMARY KEY,
                        b_num TEXT, suit TEXT, hand TEXT, winner TEXT, timestamp TIMESTAMP
                    )
                """)
                conn.commit()
    except Exception as e:
        print(f"⚠️ خطأ في قاعدة البيانات: {e}")

# ==================== محرك التوقع ====================
async def fetch_prediction(model, api_key, bonus, suit, hand, history):
    prompt = f"التاريخ: {history}\nالحالي: ب {bonus}, و {suit}, ي {hand}\nأجب حصراً بـ: النتيجة: (ثور/راعي) | الثقة: %"
    try:
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
            timeout=10)
        return resp.json()['choices'][0]['message']['content'].lower()
    except:
        return "غير متاح حالياً"

# ==================== المعالجات ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    kb = [[InlineKeyboardButton("👑 رويال", callback_data="h_رويال"), InlineKeyboardButton("🌈 ستريت فلاش", callback_data="h_ستريت_فلاش")],
          [InlineKeyboardButton("✌️ زوجين", callback_data="h_زوجين"), InlineKeyboardButton("🃏 الأكبر", callback_data="h_أكبر")]]
    await update.message.reply_text("🏛️ **الكيان V60.1 السحابي**\nاختر اليد الحالية:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    
    if data.startswith("h_"):
        context.user_data['hand'] = data[2:]
        kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️"),
               InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
        await query.edit_message_text(f"اليد: {data[2:]}\nاختر النوع:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text("📥 أرسل رقم البونص (7-8 أرقام):")

    elif data.startswith("save_"):
        winner = data.split("_")[1]
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, hand, winner, timestamp) VALUES (%s, %s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], context.user_data['hand'], winner, datetime.datetime.now()))
                conn.commit()
        await query.edit_message_text(f"✅ تم الحفظ: {winner}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        context.user_data['bonus'] = text
        load = await update.message.reply_text("📡 جاري التحليل...")
        
        # جلب تاريخ مختصر
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT b_num, winner FROM history ORDER BY id DESC LIMIT 10")
                rows = cur.fetchall()
        history = " | ".join([f"{r['b_num']}:{r['winner']}" for r in rows]) if rows else "فارغ"

        g_pred = await fetch_prediction(MODEL_GEMINI, API_KEY_PRIMARY, text, context.user_data['suit'], context.user_data['hand'], history)
        n_pred = await fetch_prediction(MODEL_NVIDIA, API_KEY_NVIDIA, text, context.user_data['suit'], context.user_data['hand'], history)

        kb = [[InlineKeyboardButton("🐂 ثور", callback_data="save_ثور"), InlineKeyboardButton("🐑 راعي", callback_data="save_راعي")]]
        await load.edit_text(f"🎯 **توقع مزدوج:**\n\n🧠 Gemini: {g_pred}\n🤖 Nvidia: {n_pred}", reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    if not TOKEN:
        print("❌ خطأ: التوكن مفقود! أضف TOKEN في Variables")
        sys.exit(1)
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
