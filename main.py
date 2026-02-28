import os, datetime, psycopg2, pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات السيادية ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# ==================== 2. المحرك الرياضي القطعي ====================
def sovereign_math_engine(b_num, suit, last_timestamp, current_timestamp):
    """محرك حساب القانون السيادي بدون تدخل الذكاء الاصطناعي"""
    
    # 1. حساب عامل البونص (B): مجموع آخر 3 أرقام
    last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
    B = sum(int(digit) for digit in last_3 if digit.isdigit())
    
    # 2. حساب عامل البذلة (S)
    S = 1 if suit in ['♦️', '♥️'] else 2
    
    # 3. حساب الفجوة الزمنية (ΔT) بالثواني
    if last_timestamp:
        delta_t = int((current_timestamp - last_timestamp).total_seconds())
    else:
        delta_t = 0 # في حال كانت هذه أول جولة في السجل
        
    # 4. المعادلة السيادية: R = (B * S) + ΔT
    R = (B * S) + delta_t
    
    # 5. الاستنتاج
    is_even = (R % 2 == 0)
    prediction = "ثور 🔵" if is_even else "راعي 🔴"
    
    report = (
        f"🧮 **المحرك الرياضي النشط**\n"
        f"━━━━━━━━━━━━\n"
        f"▪️ البونص ($B$): مجموع {last_3} = {B}\n"
        f"▪️ البذلة ($S$): {suit} = {S}\n"
        f"▪️ الفجوة الزمنية ($\Delta T$): {delta_t} ثانية\n"
        f"▪️ الحسبة ($R$): ({B} × {S}) + {delta_t} = {R}\n"
        f"━━━━━━━━━━━━\n"
        f"🎯 **التوقع:** {prediction} (لأن {R} رقم {'زوجي' if is_even else 'فردي'})"
    )
    return report

# ==================== 3. معالجات التليجرام (Handlers) ====================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ رادار {data[2:]} نشط.\n📥 أرسل بونص الجولة:")
        
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        timestamp = context.user_data.get('current_time', datetime.datetime.now())
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data.get('bonus'), context.user_data.get('suit'), winner, timestamp))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم أرشفة الجولة ({winner}) في السجل بنجاح.\nالمراقب يسجل البيانات...")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V99.0 (الوضع الرياضي)**\n"
        "تم إيقاف المحرك اللفظي، والاعتماد الآن على خوارزمية الفجوات الزمنية.\n"
        "اختر النوع للبدء:", reply_markup=InlineKeyboardMarkup(kb)
    )

async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("📊 جاري تصدير السجل السيادي للمراقبة...")
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT * FROM history ORDER BY id ASC", conn)
        conn.close()
        
        filename = f"Observer_Log_{datetime.date.today()}.xlsx"
        df.to_excel(filename, index=False)
        
        with open(filename, "rb") as f:
            await update.message.reply_document(document=f, filename=filename, caption=f"📊 السجل يحتوي على {len(df)} جولة.")
        os.remove(filename)
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ فشل الاستخراج: {str(e)}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً.")
            return

        context.user_data['bonus'] = text
        current_timestamp = datetime.datetime.now()
        context.user_data['current_time'] = current_timestamp # لحفظها لاحقاً
        
        # جلب توقيت آخر جولة مسجلة لحساب الفجوة
        last_timestamp = None
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                if row:
                    last_timestamp = row[0]
            conn.close()
        except Exception as e:
            print(f"Database read error: {e}")

        # تطبيق القانون الرياضي اللحظي
        analysis_report = sovereign_math_engine(text, context.user_data['suit'], last_timestamp, current_timestamp)

        time_str = current_timestamp.strftime("%H:%M:%S")
        final_message = f"⏰ **توقيت الإدخال:** `{time_str}`\n\n{analysis_report}"
        
        kb = [[InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 فاز الثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        
        await update.message.reply_text(final_message, reply_markup=InlineKeyboardMarkup(kb))

# ==================== 4. التشغيل ====================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_database))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    print("🚀 البوت يعمل الآن بنظام المحرك الرياضي (V99.0)...")
    app.run_polling()
