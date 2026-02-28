import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (النماذج المجانية) ---
# ملاحظة: هذه المفاتيح ستعمل مع النماذج المجانية حتى لو كان الرصيد 0
KEY_1 = "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"
KEY_2 = "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"
KEY_3 = "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"
KEY_4 = "xai-625BykGM1tRwraxJTXDnN8WEXyzQCGZbay8iA8JTPfqVzjaUQEVdD5oVcvSxoIXAuMC7rffEvAUUxTex"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai(model_name, api_key, prompt):
    is_xai = api_key.startswith("xai-")
    url = "https://api.x.ai/v1/chat/completions" if is_xai else "https://openrouter.ai/api/v1/chat/completions"
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        resp = requests.post(
            url,
            headers=headers,
            json={"model": model_name, "messages": [{"role": "user", "content": prompt}], "temperature": 0.4, "max_tokens": 120},
            timeout=15
        )
        return resp.json()['choices'][0]['message']['content'].strip() if resp.status_code == 200 else f"تجاوز الحصة (رصيد 0)"
    except: return "فشل الاتصال"

# --- المعالجات ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان V74.0 (النسخة المجانية)**\nاختر نوع الورقة:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ النوع: {data[2:]}\n📥 أرسل رقم البونص:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم الحفظ: {winner}\nاضغط /start")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data: return
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🧬 **جاري التحليل الرياضي عبر النماذج المجانية...**")
        
        now = datetime.datetime.now()
        current_time_str = now.strftime("%H:%M:%S.%f")[:-3]
        
        raw_data = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, suit, winner, timestamp FROM history ORDER BY id DESC LIMIT 10")
                rows = cur.fetchall()
                for r in rows:
                    raw_data += f"[{r[3].strftime('%M:%S')}] B:{r[0]} S:{r[1]} -> {r[2]}\n"
            conn.close()
        except: raw_data = "لا يوجد بيانات."

        prompt = f"حلل رياضياً وابتكر قانوناً: {raw_data}\nالحالي: بونص {text}, {context.user_data['suit']}, وقت {current_time_str}\nأجب بـ: التوقع، الثقة، القاعدة."

        loop = asyncio.get_event_loop()
        tasks = [
            # استخدام نماذج مجانية تماماً لا تطلب رصيداً
            loop.run_in_executor(None, ask_ai, "google/gemini-2.0-flash-exp:free", KEY_1, prompt),
            loop.run_in_executor(None, ask_ai, "meta-llama/llama-3.1-8b-instruct:free", KEY_2, prompt),
            loop.run_in_executor(None, ask_ai, "mistralai/mistral-7b-instruct:free", KEY_3, prompt),
            loop.run_in_executor(None, ask_ai, "grok-beta", KEY_4, prompt) 
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        r1, r2, r3, r4 = [r if not isinstance(r, Exception) else "عطل مؤقت" for r in results]

        report = (f"📊 **تحليل مجاني (رصيد 0):**\n━━━━━━━━━━━━\n"
                  f"🧠 **Gemini (Free):**\n{r1}\n\n"
                  f"🤖 **Llama (Free):**\n{r2}\n\n"
                  f"🔍 **Mistral (Free):**\n{r3}\n\n"
                  f"🌌 **Grok (Official):**\n{r4}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة:")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
