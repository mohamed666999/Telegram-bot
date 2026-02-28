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
                "temperature": 0.0, 
                "max_tokens": 400 # تم زيادته لمنع انقطاع التحليل
            },
            timeout=20
        )
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip()
        else:
            return f"⚠️ تنبيه: المحرك واجه استجابة غير مكتملة ({resp.status_code})"
    except: return "❌ فشل في معالجة البيانات"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان V70.2 (المعالج الرياضي المستقر)**\nاختر نوع الورقة:", reply_markup=InlineKeyboardMarkup(kb))

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
            await query.edit_message_text(f"✅ تم الحفظ. الجولة القادمة ستكون أدق.")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data: return
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔄 **جاري تشغيل خوارزمية التحليل الرقمي...**")
        
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
                    # تنسيق البيانات بشكل أنظف لتجنب خطأ 400
                    raw_data += f"Data: {r[0]} | {r[1]} | {r[2]} | Time: {t_str}\n"
            conn.close()
        except: raw_data = "بيانات غير كافية."

        prompt = f"""حلل الأنماط الرياضية التالية بدقة متناهية:
{raw_data}

المعطيات الجديدة للتنبؤ:
البونص: {text} | الورقة: {context.user_data['suit']} | التوقيت: {current_time_str}

المطلوب:
1. استخراج علاقة بين (آخر رقمين من البونص + أرقام الملي ثانية).
2. تحديد ما إذا كانت النتيجة تميل لـ (راعي) أو (ثور) بناءً على التكرار الإحصائي.
3. التنسيق الإلزامي:
التوقع: (🔵 ثور أو 🔴 راعي)
الثقة: %
القاعدة: (معادلة رياضية مختصرة جداً)"""

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, ask_ai, "llama-3.3-70b-versatile", GROQ_KEY, prompt),
            loop.run_in_executor(None, ask_ai, "mixtral-8x7b-32768", GROQ_KEY, prompt)
        ]
        results = await asyncio.gather(*tasks)
        r1, r2 = results

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل العميق:**\n{r1}\n\n"
                  f"🤖 **التدقيق المنطقي:**\n{r2}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة الفعلية:")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
