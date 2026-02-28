import os, datetime, psycopg2, pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات (Database & Config) ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# قاموس الخرائط الموحد (Mapping) لمنع تضارب النصوص
WINNER_MAP = {'الراعي 🔴': 0, 'ثور': 1, 'تعادل': 2, 'راعي': 0, 'ثور 🔵': 1, 'تعادل ⚪': 2}
PERIOD_ORDER = ["morning", "afternoon", "evening", "night"]

# ==================== 2. طبقة التحليل (Analytics Layer) ====================

def get_time_period(hour):
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

async def model_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🧠 أمر /model_status: يعطي نظرة شاملة عن صحة المحرك"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, prediction, timestamp, suit FROM history WHERE prediction IS NOT NULL", conn)
        conn.close()

        if len(df) < 20:
            await update.message.reply_text("⚠️ البيانات غير كافية لتحليل الحالة.") ; return

        # تنظيف البيانات (نصيحتك رقم 1)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # تحليل آخر 50 و 200 جولة (نصيحتك رقم 6)
        acc_50 = df.tail(50)['correct'].mean() * 100
        acc_200 = df.tail(200)['correct'].mean() * 100

        # تحليل الفترات بترتيب ثابت (نصيحتك رقم 2)
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        period_stats = df.groupby('period')['correct'].mean().reindex(PERIOD_ORDER) * 100

        # تحليل البذلة مع عدد العينات (نصيحتك رقم 4)
        suit_stats = df.groupby('suit').agg(accuracy=('correct', 'mean'), count=('correct', 'count'))
        suit_stats['accuracy'] *= 100

        report = "🧠 **حالة محرك HADES السيادي**\n━━━━━━━━━━━━━━\n"
        report += f"📈 آخر 50 جولة: {acc_50:.1f}%\n"
        report += f"📊 آخر 200 جولة: {acc_200:.1f}%\n\n"
        
        report += "🕒 **أداء الفترات:**\n"
        for p in PERIOD_ORDER:
            if p in period_stats:
                report += f"{p.capitalize()}: {period_stats[p]:.1f}%\n"

        report += "\n🃏 **أداء البذلات:**\n"
        for suit, row in suit_stats.iterrows():
            report += f"{suit}: {row['accuracy']:.1f}% ({int(row['count'])} جولة)\n"

        status = "🟢 مستقرة" if acc_50 > 60 else "🟡 تحتاج مراقبة"
        report += f"\n🏁 **حالة النموذج:** {status}"

        await update.message.reply_text(report)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في تقرير الحالة: {e}")

# ==================== 3. المحرك المحدث (Hades Pattern Engine) ====================

def hades_math_engine(b_num, suit, last_timestamp, current_timestamp):
    # استخدام منطق المعادلة السيادية R = (B * S) + ΔT
    last_3 = b_num[-3:]
    B = sum(int(d) for d in last_3 if d.isdigit())
    S = 1 if suit in ['♦️', '♥️'] else 2
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    R = (B * S) + delta_t
    
    pred_code = 1 if (R % 2 == 0) else 0
    return pred_code, R, delta_t

# ==================== 4. معالجة الرسائل (Operational Layer) ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً.") ; return

        now = datetime.datetime.now()
        
        # جلب آخر توقيت لحساب الفجوة
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone() ; last_time = row[0] if row else None
        conn.close()

        # التنبؤ وحفظ الكود في الذاكرة المؤقتة
        pred_code, R, gap = hades_math_engine(text, context.user_data['suit'], last_time, now)
        pred_text = "ثور 🔵" if pred_code == 1 else "راعي 🔴"
        
        context.user_data.update({'bonus': text, 'pred_code': pred_code, 'now': now})

        # رسالة التوقع مع أزرار النتيجة الحقيقية
        kb = [[InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_راعي"), 
               InlineKeyboardButton("🔵 فاز الثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        
        await update.message.reply_text(
            f"🎯 **توقع HADES:** {pred_text}\n"
            f"🔢 الفجوة: {gap}s | مؤشر R: {R}\n"
            f"━━━━━━━━━━━━━━\n"
            f"يرجى تسجيل النتيجة الحقيقية:",
            reply_markup=InlineKeyboardMarkup(kb)
        )

# ==================== 5. التشغيل (Main Loop) ====================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("🏛️ HADES V101.0 جاهز.\nاستخدم /model_status للمراقبة.")))
    app.add_handler(CommandHandler("model_status", model_status))
    app.add_handler(CommandHandler("download", lambda u, c: u.message.reply_text("استخدم كود التصدير السابق هنا."))) # دالة التحميل السابقة
    app.add_handler(CallbackQueryHandler(lambda u, c: None)) # دالة الحفظ السابقة (تأكد من تعديلها لحفظ pred_code)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    print("🚀 محرك HADES المحصن إحصائياً يعمل الآن...")
    app.run_polling()
