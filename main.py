import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (الرصيد المفتوح) ---
AIML_KEY = "a4ef4823e990496fa7166844a9e3eea0"
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai_ultra(prompt):
    try:
        resp = requests.post(
            "https://api.aimlapi.com/chat/completions",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "meta-llama/Llama-3.1-405B-Instruct-Turbo", 
                "messages": [{"role": "system", "content": "أنت نظام رادار رياضي يعمل 24/7 لتحليل فجوات الوقت والأنماط الرقمية."}, {"role": "user", "content": prompt}],
                "temperature": 0.0, "max_tokens": 1000
            }, timeout=40
        )
        return resp.json()['choices'][0]['message']['content'].strip() if resp.status_code == 200 else "ERR"
    except: return "CONNECTION_ERR"

async def initialize_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    with conn.cursor() as cur:
        # إنشاء جدول القوانين المستقل
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

# --- دالة المعالجة التي سببت الخطأ (تمت إضافتها بالكامل) ---
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ النوع المختار: {data[2:]}\n📥 أرسل بونص الجولة:")
    
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                # حفظ النتيجة لتغذية خوارزمية الفجوات
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم حفظ النتيجة ({winner}) وتحديث السجل التاريخي بنجاح.")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في قاعدة البيانات: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await initialize_db()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان السيادي V75.1**\nنظام التحليل المستمر 24/7 مفعل.\nاختر النوع:", reply_markup=InlineKeyboardMarkup(kb))

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data: return
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🛰️ **جاري استنباط القوانين عبر تحليل الفجوات الزمنية...**")
        
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        all_data = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 50")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    all_data += f"الجولة: {rows[i][0]} -> فوز: {rows[i][1]} | الفجوة: {gap} ثانية\n"
            conn.close()
        except: all_data = "لا توجد بيانات سابقة."

        prompt = f"""حلل الفجوات والأنماط الرياضية:\n{all_data}\n\nالحالي: بونص {text}, توقيت {current_time_str}\nالتوقع والقانون:"""
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_ai_ultra, prompt)

        # حفظ القانون في السجل المستقل
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO rules_log (rule_text, confidence_score) VALUES (%s, %s)", (analysis, 95.0))
                conn.commit()
            conn.close()
        except: pass

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل السيادي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون في سجل القوانين المستقل.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler)) # تم تعريفها الآن
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
