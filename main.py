import os, sys, datetime, asyncio, psycopg2, requests, json
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات السيادية ====================
GROQ_API_KEY = "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"
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
MODEL_NAME = "llama-3.3-70b-versatile"

# ==================== 2. محرك الاستدلال (Groq) ====================
def ask_groq_sovereign(prompt):
    headers = {
        'Authorization': f'Bearer {GROQ_API_KEY}',
        'Content-Type': 'application/json; charset=utf-8'
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "أنت محلل بيانات رياضي خبير. حلل الأنماط بدقة."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    try:
        json_payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, data=json_payload, timeout=15)
        if resp.status_code == 200:
            return f"⚡ [Groq Analysis]\n{resp.json()['choices'][0]['message']['content'].strip()}"
        return f"⚠️ خطأ في المحرك (كود {resp.status_code})"
    except Exception as e:
        return f"❌ عطل تقني: {str(e)}"

# ==================== 3. معالجات الأوامر (Handlers) ====================

# تم تعريف callback_handler هنا قبل استدعائها في الأسفل
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ رادار {data[2:]} نشط.\n📥 أرسل بونص الجولة (7-8 أرقام):")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data.get('bonus'), context.user_data.get('suit'), winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم حفظ النتيجة: {winner}.")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V98.0**\nأهلاً بك يا مهندس. النظام جاهز.\n"
        "استخدم /download لسحب السجل بصيغة Excel.",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("📊 جاري تصدير البيانات...")
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT * FROM history ORDER BY id DESC", conn)
        conn.close()
        
        filename = f"History_{datetime.date.today()}.xlsx"
        df.to_excel(filename, index=False)
        
        with open(filename, "rb") as f:
            await update.message.reply_document(document=f, filename=filename, caption="📊 سجل الجولات المكتمل.")
        os.remove(filename)
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ فشل الاستخراج: {str(e)}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً.")
            return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔎 **جاري استنتاج النمط عبر مصفوفة Groq...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 20")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"B:{rows[i][0]}|W:{rows[i][1]}|G:{gap}s\n"
            conn.close()
        except: gap_report = "السجل قيد المزامنة."

        prompt = f"Analyze:\n{gap_report}\nCurrent: Bonus {text}, Time {time_str}\nPredict Bull/Bear:"
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_groq_sovereign, prompt)

        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(f"⏰ `{time_str}`\n\n{analysis}", reply_markup=InlineKeyboardMarkup(kb))

# ==================== 4. تشغيل التطبيق (Application) ====================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    # إضافة المعالجات بالترتيب الصحيح
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_database))
    app.add_handler(CallbackQueryHandler(callback_handler)) # تم حل مشكلة الـ NameError
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    print("🚀 البوت يعمل الآن بنجاح على Railway...")
    app.run_polling()
