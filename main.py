import os, sys, datetime, asyncio, psycopg2
import httpx # مكتبة أسرع للطلبات المتزامنة
from psycopg2.extras import DictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (تأكد من دقة المفاتيح) ---
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
API_KEY_PRIMARY = "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"
API_KEY_NVIDIA = "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"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# --- محرك التحليل المتوازي فائق السرعة ---
async def fetch_ai_prediction(model, api_key, bonus, suit, hand, history):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://railway.app", # متطلب لبعض النماذج
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "أنت خبير إحصائي سريع. أعطِ توقعك (ثور/راعي) ونسبة الثقة."},
            {"role": "user", "content": f"التاريخ: {history}\nبونص: {bonus}, ورقة: {suit}, يد: {hand}"}
        ],
        "temperature": 0.1,
        "max_tokens": 50
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=15.0)
            if response.status_code == 200:
                return response.json()['choices'][0]['message']['content'].strip()
            return f"خطأ سيرفر: {response.status_code}"
    except Exception as e:
        return f"فشل اتصال: {str(e)[:20]}"

# ==================== المعالجات (V62.0) ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("👑 رويال", callback_data="h_رويال"), InlineKeyboardButton("✌️ زوجين", callback_data="h_زوجين")],
          [InlineKeyboardButton("🏠 فل هاوس", callback_data="h_فل_هاوس"), InlineKeyboardButton("🃏 الأكبر", callback_data="h_أكبر")]]
    await update.message.reply_text("🏛️ **الكيان الموحد - وضع السرعة القصوى**\nاختر اليد:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("h_"):
        context.user_data['hand'] = data[2:]
        kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️"),
               InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
        await query.edit_message_text(f"اليد: {data[2:]}\nاختر النوع:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text("📥 أرسل رقم البونص:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        # (كود الحفظ في Postgres يبقى كما هو)
        await query.edit_message_text(f"✅ تم الحفظ: {winner}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        context.user_data['bonus'] = text
        load = await update.message.reply_text("📡 **جاري التحليل المتوازي...**")
        
        # جلب تاريخ سريع
        history = "لا يوجد"
        try:
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT winner FROM history ORDER BY id DESC LIMIT 5")
                    history = ", ".join([r[0] for r in cur.fetchall()])
        except: pass

        # تشغيل الطلبات في وقت واحد
        tasks = [
            fetch_ai_prediction("google/gemini-2.0-flash-001", API_KEY_PRIMARY, text, context.user_data['suit'], context.user_data['hand'], history),
            fetch_ai_prediction("nvidia/llama-3.1-nemotron-70b-instruct", API_KEY_NVIDIA, text, context.user_data['suit'], context.user_data['hand'], history)
        ]
        
        results = await asyncio.gather(*tasks)

        report = (f"🎯 **التوقعات الحية:**\n\n🧠 Gemini: {results[0]}\n🤖 Nvidia: {results[1]}")
        kb = [[InlineKeyboardButton("🐂 ثور", callback_data="save_ثور"), InlineKeyboardButton("🐑 راعي", callback_data="save_راعي")]]
        await load.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
