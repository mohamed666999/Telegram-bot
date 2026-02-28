import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية ---
GROQ_KEY = "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"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai(model_name, api_key, prompt):
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_name, 
                "messages": [{"role": "user", "content": prompt}], 
                "temperature": 0.0, # تم خفض الحرارة للصفر لزيادة الدقة الرياضية ومنع الهلوسة
                "max_tokens": 200    # زيادة التوكنز ليتسع للتحليل العميق
            },
            timeout=15
        )
        return resp.json()['choices'][0]['message']['content'].strip() if resp.status_code == 200 else f"خطأ {resp.status_code}"
    except: return "فشل الاتصال"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان V70.1 (المحرك الرياضي العميق)**\nاختر نوع الورقة:", reply_markup=InlineKeyboardMarkup(kb))

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
        msg = await update.message.reply_text("🔬 **جاري إجراء تحليل رياضي عميق (نمط OpenRouter)...**")
        
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

        # تم تحديث البرومبت ليكون "تحليلياً" وليس مجرد توقع سريع
        prompt = f"""حلل هذه البيانات كخبير رياضيات واحصاء.
البيانات السابقة:
{raw_data}

المعطيات الحالية: بونص {text}، ورقة {context.user_data['suit']}، وقت الطلب {current_time_str}

مهمتك:
1. ابحث عن علاقة رقمية بين آخر رقمين في البونص وبين وقت الملي ثانية.
2. استنبط النمط المتكرر في النتائج السابقة بناءً على "فجوة الوقت".
3. قدم توقعاً مبنياً على معادلة رياضية واضحة.

التنسيق:
التوقع: 🔵 ثور (أو 🔴 راعي)
الثقة: %
القاعدة المبتكرة: (اكتب المعادلة الرياضية التي استنتجتها بدقة)"""

        loop = asyncio.get_event_loop()
        # استخدام الموديلات الأقوى في Groq لمحاكاة دقة OpenRouter
        tasks = [
            loop.run_in_executor(None, ask_ai, "llama-3.3-70b-versatile", GROQ_KEY, prompt),
            loop.run_in_executor(None, ask_ai, "mixtral-8x7b-32768", GROQ_KEY, prompt),
            loop.run_in_executor(None, ask_ai, "llama-3.1-8b-instant", GROQ_KEY, prompt)
        ]
        r1, r2, r3 = await asyncio.gather(*tasks)

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل العميق (1):**\n{r1}\n\n"
                  f"🤖 **التحليل المنطقي (2):**\n{r2}\n\n"
                  f"🔍 **مقارنة الأنماط (3):**\n{r3}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة الفعلية لتغذية النظام:")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
