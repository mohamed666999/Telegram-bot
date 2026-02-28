import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (تحسين الاستقرار) ---
AIML_KEY = "a4ef4823e990496fa7166844a9e3eea0"
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai_fast_ultra(prompt):
    """محرك سريع الاستجابة لتجنب الـ ERR"""
    try:
        resp = requests.post(
            "https://api.aimlapi.com/chat/completions",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", # تبديل للنسخة الأسرع والأكثر استقراراً
                "messages": [
                    {"role": "system", "content": "أنت نظام رادار لتحليل الثغرات الرقمية والوقتية."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.0, 
                "max_tokens": 400
            }, timeout=25 # تقليل وقت الانتظار لضمان عدم تعليق البوت
        )
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip()
        return f"⚠️ استجابة المنصة: {resp.status_code}"
    except: return "❌ فشل في معالجة المصفوفة اللحظية"

# --- المعالجات ---

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ النوع: {data[2:]}\n📥 أرسل البونص الجديد:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم الحفظ وتغذية الذاكرة بـ: {winner}")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data: return
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("⚡ **جاري استنباط النمط الرقمي (تحليل الفجوات)...**")
        
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # تحليل آخر 25 جولة (توازن مثالي بين الدقة والسرعة)
        all_data = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 25")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    all_data += f"B:{rows[i][0]} | W:{rows[i][1]} | Gap:{gap}s\n"
            conn.close()
        except: all_data = "السجل الأولي."

        prompt = f"حلل فجوات الوقت والأنماط:\n{all_data}\nالحالي: بونص {text}, وقت {current_time_str}\nأعطني التوقع والقانون الرياضي:"

        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_ai_fast_ultra, prompt)

        # حفظ القانون في سجل القوانين (Rules Log)
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO rules_log (rule_text, confidence_score) VALUES (%s, %s)", (analysis, 98.0))
                conn.commit()
            conn.close()
        except: pass

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل السيادي (V75.2):**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون رقم ({datetime.datetime.now().strftime('%H%M%S')})")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("🏛️ نظام V75.2 نشط.")))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
