import os, sys, datetime, asyncio, psycopg2, requests
from psycopg2.extras import DictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية ---
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
API_KEY_PRIMARY = "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"
API_KEY_NVIDIA = "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"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# --- دالة جلب التوقعات (باستخدام requests داخل خيط منفصل لمنع التعليق) ---
def get_ai_sync(model, api_key, bonus, suit, hand, history):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": f"التاريخ: {history}\nبونص: {bonus}, ورقة: {suit}, يد: {hand}. توقع (ثور/راعي) وثقة %"}],
        "temperature": 0.3, "max_tokens": 50
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip()
        return f"خطأ {resp.status_code}"
    except Exception as e:
        return f"خطأ اتصال"

# ==================== المعالجات المحدثة ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ ابدأ بـ /start أولاً")
            return
            
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("📡 **جاري التحليل...**")
        
        # جلب التاريخ بسلاسة
        history = "فارغ"
        try:
            conn = psycopg2.connect(DATABASE_URL)
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history ORDER BY id DESC LIMIT 5")
                history = ", ".join([r[0] for r in cur.fetchall()])
            conn.close()
        except: pass

        # تنفيذ الطلبات بدون تعطيل البوت (Thread Pool)
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, get_ai_sync, "google/gemini-2.0-flash-001", API_KEY_PRIMARY, text, context.user_data['suit'], context.user_data['hand'], history),
            loop.run_in_executor(None, get_ai_sync, "nvidia/llama-3.1-nemotron-70b-instruct", API_KEY_NVIDIA, text, context.user_data['suit'], context.user_data['hand'], history)
        ]
        
        # انتظار النتائج مع مهلة زمنية قصوى
        try:
            results = await asyncio.gather(*tasks)
            report = f"🎯 **نتائج التحليل:**\n\n🧠 Gemini: {results[0]}\n🤖 Nvidia: {results[1]}"
        except:
            report = "⚠️ حدث تأخير كبير في الرد من السيرفرات."

        kb = [[InlineKeyboardButton("🐂 ثور", callback_data="save_ثور"), InlineKeyboardButton("🐑 راعي", callback_data="save_راعي")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

# (دوال start و callback_handler تبقى كما هي في الكود السابق)
