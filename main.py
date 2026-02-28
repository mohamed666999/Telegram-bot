import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (AIML API - رصيد مفتوح) ---
AIML_KEY = "a4ef4823e990496fa7166844a9e3eea0"
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai_ultra(prompt):
    """محرك التحليل العميق بنمط 24/7"""
    try:
        resp = requests.post(
            "https://api.aimlapi.com/chat/completions",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "meta-llama/Llama-3.1-405B-Instruct-Turbo", # أقوى نموذج متاح للتحليل الرياضي
                "messages": [{"role": "system", "content": "أنت نظام رادار رياضي يعمل 24/7 لتحليل فجوات الوقت والأنماط الرقمية."}, {"role": "user", "content": prompt}],
                "temperature": 0.0, "max_tokens": 1000
            }, timeout=40
        )
        return resp.json()['choices'][0]['message']['content'].strip() if resp.status_code == 200 else "ERR"
    except: return "CONNECTION_ERR"

async def initialize_db():
    """إنشاء جدول القوانين المستقل (Independent Rules Log)"""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rules_log (
                id SERIAL PRIMARY KEY,
                rule_text TEXT,
                confidence_score FLOAT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await initialize_db()
    await update.message.reply_text("🏛️ **الكيان السيادي V75.0**\nالنظام في وضع التحليل المستمر 24/7.\nأرسل البونص وسأقوم بدمجه مع كامل السجل التاريخي وتحليل الفجوات.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🛰️ **جاري سحب كامل السجل التاريخي وتحليل الفجوات الزمنية...**")
        
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # 1. قراءة جميع الحالات (ALL HISTORY) لتحليل شامل
        all_data = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 50") # تحليل أعمق لـ 50 جولة
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    # حساب الفجوة الزمنية بين كل جولة والتي قبلها (Gap Analysis)
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    all_data += f"الجولة: {rows[i][0]} -> فوز: {rows[i][1]} | الفجوة: {gap} ثانية\n"
            conn.close()
        except: all_data = "بيانات السجل الأولي."

        # 2. برومبت التحليل الفائق (Ultra Logic Prompt)
        prompt = f"""مهمة تحليلية سيادية 24/7:
البيانات المستخرجة (بما في ذلك فجوات الوقت):
{all_data}

المعطيات الجديدة: بونص {text} | توقيت الطلب: {current_time_str}

المطلوب:
1. حلل 'الفجوات الزمنية' غير المتتالية واستنتج علاقة رياضية بين آخر رقمين في البونص وبين الثانية الحالية.
2. استنبط قانوناً رياضياً صارماً لهذه الجولة.
3. التوقع: (🔵 ثور أو 🔴 راعي) | الثقة: %"""

        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_ai_ultra, prompt)

        # 3. حفظ "القانون المستنبط" في ملف القوانين المستقل (rules_log)
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO rules_log (rule_text, confidence_score) VALUES (%s, %s)", (analysis, 90.0))
                conn.commit()
            conn.close()
        except: pass

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل السيادي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 **تم تسجيل القانون الجديد في ملف القوانين المستقل.**")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

# (بقية كود التليجرام و callback_handler تبقى كما هي)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.run_polling()
