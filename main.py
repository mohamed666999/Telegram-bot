import os, sys, datetime, asyncio, psycopg2, requests, json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== الإعدادات السيادية ====================

GROQ_API_KEY = "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" 
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
MODEL_NAME = "llama-3.3-70b-versatile"

# ==================== وظيفة تحميل السجل (جديد) ====================

async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استخراج بيانات جدول التاريخ وإرسالها كملف"""
    msg = await update.message.reply_text("📂 جاري استخراج السجل السيادي...")
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM history ORDER BY id ASC")
            rows = cur.fetchall()
            
            # صناعة محتوى الملف
            content = "ID | Bonus Num | Suit | Winner | Timestamp\n"
            content += "-" * 50 + "\n"
            for row in rows:
                content += f"{row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]}\n"
        conn.close()

        # حفظ الملف مؤقتاً
        filename = f"history_backup_{datetime.date.today()}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)

        # إرسال الملف للمستخدم
        with open(filename, "rb") as f:
            await update.message.reply_document(document=f, filename=filename, caption="📊 سجل الجولات المكتمل.")
        
        # حذف الملف من السيرفر بعد الإرسال
        os.remove(filename)
        await msg.delete()

    except Exception as e:
        await update.message.reply_text(f"❌ فشل استخراج البيانات: {str(e)}")

# ==================== المحرك والوظائف المعتادة ====================

def ask_groq_sovereign(prompt):
    headers = {'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'}
    payload = {"model": MODEL_NAME, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
    try:
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=15)
        return f"⚡ [Groq Analysis]\n{resp.json()['choices'][0]['message']['content'].strip()}"
    except: return "⚠️ خطأ في المحرك."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان السيادي V96.0**\nاستخدم /download لتحميل سجل الجولات.", reply_markup=InlineKeyboardMarkup(kb))

# (أضف دوال callback_handler و message_handler من النسخة السابقة هنا)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_database)) # تفعيل أمر التحميل
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
