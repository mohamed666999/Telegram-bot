import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية المحدثة ---
# تم إزالة المفاتيح القديمة ووضع مفتاح Groq الخاص بك
GROQ_API_KEY = "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"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_groq(model_name, prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2, # تقليل الحرارة لزيادة الدقة الرياضية
                "max_tokens": 150
            },
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip()
        else:
            return f"خطأ في Groq: {resp.status_code}"
    except Exception as e:
        return f"فشل الاتصال: {str(e)}"

# ==================== المعالجات ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان V75.0 (محرك Groq الرياضي)**\nاختر نوع الورقة لبدء الاستنباط:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ النوع المختار: {data[2:]}\n📥 أرسل رقم البونص الآن:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم حفظ النتيجة كـ ({winner}) لتغذية القاعدة القادمة.")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data: return
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔬 **جاري تحليل الفجوات الزمنية واستنباط القاعدة...**")
        
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
                    raw_data += f"[{t_str}] B:{r[0]}, S:{r[1]} -> Win:{r[2]}\n"
            conn.close()
        except: raw_data = "بيانات الذاكرة غير كافية حالياً."

        prompt = f"""أنت محرك رياضي فائق السرعة. حلل البيانات الزمنية التالية وابتكر قاعدة رياضية فورية:
{raw_data}

المعطيات الجديدة: بونص {text}، ورقة {context.user_data['suit']}
الوقت الحالي: {current_time_str}

حلل الفجوات بالملي ثانية وابتكر قانوناً يفسر النتيجة القادمة.
المطلوب:
التوقع: 🔵 ثور (أو 🔴 راعي)
الثقة: %
القاعدة المبتكرة: (اشرح القانون الرياضي المستنبط في 10 كلمات)"""

        # تنفيذ الطلب عبر نموذج Llama 3.3 70B من خلال Groq
        loop = asyncio.get_event_loop()
        prediction = await loop.run_in_executor(None, ask_groq, "llama-3.3-70b-versatile", prompt)

        report = (f"⏰ **توقيت العملية:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"⚡ **تحليل Groq Quantum:**\n\n{prediction}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة الفعلية لتحديث المحرك:")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
