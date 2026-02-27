import os, sys, datetime, requests, asyncio, psycopg2
from psycopg2.extras import DictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية الثابتة ---
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
API_KEY_PRIMARY = "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"
API_KEY_NVIDIA = "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"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# --- محرك التحليل السريع جداً ---
async def quick_predict(model, api_key, bonus, suit, hand, history):
    # تقليل التوقعات إلى كلمات مفتاحية لزيادة السرعة
    prompt = f"التاريخ: {history}\nبونص {bonus}، {suit}، {hand}. توقع النتيجة (ثور/راعي) ونسبة الثقة فقط."
    try:
        # استخدام معالجة سريعة (Stream = False)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 40},
            timeout=8 # تقليل المهلة لسرعة الاستجابة
        ))
        return response.json()['choices'][0]['message']['content'].strip()
    except:
        return "فشل التحليل السريع"

# ==================== المعالجات الأساسية (Turbo Mode) ====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً بالضغط على /start")
            return
            
        context.user_data['bonus'] = text
        load = await update.message.reply_text("📡 **تحليل فوري...**")
        
        # جلب التاريخ بسرعة فائقة
        history = "فارغ"
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner FROM history ORDER BY id DESC LIMIT 5")
                rows = cur.fetchall()
                history = " | ".join([f"{r[0]}:{r[1]}" for r in rows])
            conn.close()
        except: pass

        # تشغيل Gemini و Nvidia في وقت واحد (Parallel)
        tasks = [
            quick_predict("google/gemini-2.0-flash-001", API_KEY_PRIMARY, text, context.user_data['suit'], context.user_data['hand'], history),
            quick_predict("nvidia/llama-3.1-nemotron-70b-instruct", API_KEY_NVIDIA, text, context.user_data['suit'], context.user_data['hand'], history)
        ]
        
        g_res, n_res = await asyncio.gather(*tasks)

        report = (f"🎯 **النتيجة الذكية:**\n\n🧠 Gemini: {g_res}\n🤖 Nvidia: {n_res}")
        kb = [[InlineKeyboardButton("🐂 ثور", callback_data="save_ثور"), InlineKeyboardButton("🐑 راعي", callback_data="save_راعي")]]
        await load.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

# (بقية الدوال: start و callback_handler تبقى كما هي في V60.2)
