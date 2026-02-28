import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (تم التحديث للمفتاح الجديد فقط) ---
GROQ_KEY = "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"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai(model_name, api_key, prompt):
    try:
        # تم تعديل الرابط ليتوافق مع Groq API الرسمي
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model_name, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 120},
            timeout=15
        )
        return resp.json()['choices'][0]['message']['content'].strip() if resp.status_code == 200 else f"خطأ {resp.status_code}"
    except: return "فشل الاتصال"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان V70.0 (المحرك الرياضي المبتكر)**\nاختر نوع الورقة:", reply_markup=InlineKeyboardMarkup(kb))

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
            await query.edit_message_text(f"✅ تم حفظ النتيجة: {winner}")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data: return
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔬 **جاري استنباط القواعد الرياضية من الذاكرة الزمنية...**")
        
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        raw_data = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, suit, winner, timestamp FROM history ORDER BY id DESC LIMIT 15")
                rows = cur.fetchall()
                for r in rows:
                    t_str = r[3].strftime("%H:%M:%S.%f")[:-3]
                    raw_data += f"[{t_str}] Bonus:{r[0]}, Suit:{r[1]} -> Win:{r[2]}\n"
            conn.close()
        except: raw_data = "لا توجد بيانات سابقة كافية."

        prompt = f"""أنت محرك رياضي فائق الذكاء. مهمتك ابتكار قاعدة رياضية (Formula) تربط بين رقم البونص، نوع الورقة، والوقت بدقة الأجزاء من الثانية.
البيانات الخام الحالية:
{raw_data}

الوقت الحالي للجولة: {current_time_str}
المعطيات الجديدة: بونص {text}، ورقة {context.user_data['suit']}

حلل الفجوات الزمنية وابتكر قانوناً يفسر النتيجة القادمة.
المطلوب (تنسيق إلزامي):
التوقع: 🔵 ثور (أو 🔴 راعي)
الثقة: %
القاعدة المبتكرة: (اشرح القانون الرياضي الذي استنبطته في 10 كلمات)"""

        # تشغيل النماذج الثلاثة باستخدام مفتاح Groq واحد وموديلات مختلفة
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, ask_ai, "llama-3.3-70b-versatile", GROQ_KEY, prompt),
            loop.run_in_executor(None, ask_ai, "llama-3.1-8b-instant", GROQ_KEY, prompt),
            loop.run_in_executor(None, ask_ai, "mixtral-8x7b-32768", GROQ_KEY, prompt)
        ]
        r1, r2, r3 = await asyncio.gather(*tasks)

        report = (f"⏰ **توقيت الطلب:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **Llama 70B:**\n{r1}\n\n"
                  f"🤖 **Llama 8B:**\n{r2}\n\n"
                  f"🔍 **Mixtral:**\n{r3}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة الفعلية لتطوير القاعدة:")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
