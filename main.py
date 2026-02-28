import os, sys, datetime, asyncio, psycopg2, requests, pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== الإعدادات السيادية ====================

GROQ_API_KEY = "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" 
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# ==================== ميزة تحميل البيانات بصيغة Excel ====================

async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحويل جدول التاريخ إلى ملف Excel وإرساله"""
    status_msg = await update.message.reply_text("📊 جاري استخراج البيانات وتحويلها إلى Excel...")
    try:
        # الاتصال وجلب البيانات باستخدام Pandas
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        query = "SELECT * FROM history ORDER BY id DESC"
        df = pd.read_sql(query, conn)
        conn.close()

        if df.empty:
            await status_msg.edit_text("⚠️ السجل فارغ حالياً، لا توجد بيانات للتصدير.")
            return

        # حفظ الملف بصيغة Excel
        filename = f"Sovereign_Log_{datetime.date.today()}.xlsx"
        df.to_excel(filename, index=False)

        # إرسال الملف
        with open(filename, "rb") as f:
            await update.message.reply_document(
                document=f, 
                filename=filename, 
                caption=f"✅ تم استخراج {len(df)} جولة بنجاح."
            )
        
        os.remove(filename) # تنظيف السيرفر
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ فشل الاستخراج: {str(e)}")

# ==================== المحرك والوظائف الأساسية ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V97.0**\nاستخدم الأمر /download للحصول على سجل الجولات بصيغة Excel.",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ... (أضف دوال callback_handler و message_handler و ask_groq_sovereign من النسخ السابقة)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_database)) # تفعيل الأمر
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
