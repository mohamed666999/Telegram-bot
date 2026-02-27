import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية المحدثة ---
KEY_1 = "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"
KEY_2 = "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"
KEY_3 = "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"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai(model_name, api_key, prompt):
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model_name, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 40},
            timeout=12
        )
        return resp.json()['choices'][0]['message']['content'].strip() if resp.status_code == 200 else f"خطأ {resp.status_code}"
    except: return "فشل الاتصال"

# ==================== المعالجات المحدثة (بدون نوع اليد) ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # البدء مباشرة باختيار نوع الورقة المكشوفة
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان V66.0 السريع**\nاختر نوع الورقة المكشوفة الآن:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ تم اختيار النوع: {data[2:]}\n📥 أرسل الآن رقم البونص (7-8 أرقام):")
    
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم الحفظ: {winner}\nاضغط /start لجولة جديدة.")
        except: await query.edit_message_text("⚠️ خطأ في الحفظ.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر نوع الورقة أولاً عبر /start")
            return
            
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🧬 **جاري التحليل الثلاثي السريع...**")
        
        history = "جديد"
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history ORDER BY id DESC LIMIT 5")
                rows = cur.fetchall()
                if rows: history = ", ".join([r[0] for r in rows])
            conn.close()
        except: pass

        # البرومبت الآن يركز فقط على البونص والنوع المكشوف
        prompt = f"التاريخ: {history}\nبونص الحالي: {text}, الورقة المكشوفة: {context.user_data['suit']}. توقع (ثور/راعي) وثقة %"

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, ask_ai, "google/gemini-2.0-flash-001", KEY_1, prompt),
            loop.run_in_executor(None, ask_ai, "nvidia/llama-3.1-nemotron-70b-instruct", KEY_2, prompt),
            loop.run_in_executor(None, ask_ai, "anthropic/claude-3-haiku", KEY_3, prompt)
        ]
        
        r1, r2, r3 = await asyncio.gather(*tasks)

        report = (f"🎯 **نتائج التحليل:**\n━━━━━━━━━━━━\n"
                  f"🧠 **Gemini:** {r1}\n"
                  f"🤖 **Nvidia:** {r2}\n"
                  f"🔍 **Claude:** {r3}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة الفعلية:")
        
        kb = [[InlineKeyboardButton("🐂 ثور", callback_data="save_ثور"), InlineKeyboardButton("🐑 راعي", callback_data="save_راعي")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
