import os
import datetime
import psycopg2
import pandas as pd
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

# ==================== 2. دوال تحليل الوقت ====================
def get_time_period(hour):
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

def period_translate(period):
    return {"morning": "🌅 الصباح", "afternoon": "☀️ الظهر", "evening": "🌇 المساء", "night": "🌙 الليل"}.get(period, period)

# ==================== 3. المحرك الرياضي الأساسي ====================
def sovereign_math_engine(b_num: str, suit: str, last_timestamp, current_timestamp):
    last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
    B = sum(int(d) for d in last_3 if d.isdigit())
    S = 1 if suit in ['♦️', '♥️'] else 2
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    R = (B * S) + delta_t
    prediction_code = 1 if (R % 2 == 0) else 0  # 1=ثور, 0=راعي
    prediction_text = WINNER_NAMES[prediction_code]
    return prediction_text, prediction_code, delta_t

# ==================== 4. دوال التأكد من وجود الأعمدة ====================
def ensure_columns():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    # إضافة عمود prediction إذا لم يكن موجوداً
    cur.execute("""
        DO $$
        BEGIN
            BEGIN
                ALTER TABLE history ADD COLUMN prediction INTEGER;
            EXCEPTION
                WHEN duplicate_column THEN NULL;
            END;
        END $$;
    """)
    # إضافة عمود user_id إذا لم يكن موجوداً
    cur.execute("""
        DO $$
        BEGIN
            BEGIN
                ALTER TABLE history ADD COLUMN user_id BIGINT;
            EXCEPTION
                WHEN duplicate_column THEN NULL;
            END;
        END $$;
    """)
    conn.commit()
    conn.close()

# ==================== 5. أوامر البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️ ديناري (أحمر)", callback_data="s_♦️"),
         InlineKeyboardButton("♥️ قلب (أحمر)", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد (أسود)", callback_data="s_♠️"),
         InlineKeyboardButton("♣️ كلبة (أسود)", callback_data="s_♣️")]
    ]
    await update.message.reply_text(
        "🏛️ **HADES V100.0**\n"
        "محرك تنبؤي رياضي مع تحليل زمني\n\n"
        "🎴 اختر نوع البذلة:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحليل أداء التوقعات حسب الفترات والساعات"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL", conn)
        conn.close()

        if len(df) < 10:
            await update.message.reply_text("⚠️ البيانات غير كافية (نحتاج 10 جولات على الأقل).")
            return

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

        # الدقة حسب الفترات
        period_order = ["morning", "afternoon", "evening", "night"]
        period_acc = df.groupby('period')['correct'].mean().reindex(period_order) * 100

        # الدقة حسب الساعات (بحد أدنى 10 جولات)
        hour_stats = df.groupby('hour').agg(accuracy=('correct', 'mean'), count=('correct', 'count'))
        hour_stats = hour_stats[hour_stats['count'] >= 10]
        hour_acc = hour_stats['accuracy'] * 100

        report = "📊 **تقرير أداء HADES**\n━━━━━━━━━━━━━━\n"
        for p in period_order:
            if p in period_acc and not pd.isna(period_acc[p]):
                report += f"{period_translate(p)}: {period_acc[p]:.1f}%\n"

        if not hour_acc.empty:
            report += "\n✅ **أفضل 3 ساعات:**\n"
            for h, acc in hour_acc.nlargest(3).items():
                report += f"🟢 {h:02d}:00 → {acc:.1f}%\n"
            report += "\n⚠️ **أسوأ 3 ساعات:**\n"
            for h, acc in hour_acc.nsmallest(3).items():
                report += f"🔴 {h:02d}:00 → {acc:.1f}%\n"

        report += f"\n📈 إجمالي الجولات: {len(df)}"
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def model_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض حالة النموذج (آخر 50 و200 جولة)"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL ORDER BY id DESC LIMIT 200", conn)
        conn.close()

        if len(df) < 10:
            await update.message.reply_text("⚠️ بيانات غير كافية.")
            return

        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

        acc_50 = df.head(50)['correct'].mean() * 100 if len(df) >= 50 else None
        acc_200 = df['correct'].mean() * 100

        report = "🧠 **حالة محرك HADES**\n━━━━━━━━━━━━━━\n"
        if acc_50:
            report += f"📉 آخر 50 جولة: {acc_50:.1f}%\n"
        report += f"📊 آخر 200 جولة: {acc_200:.1f}%\n"

        if acc_200 >= 65:
            status = "✅ ممتاز"
        elif acc_200 >= 58:
            status = "⚖️ مقبول"
        else:
            status = "🔻 ضعيف"
        report += f"\n**التقييم:** {status}"

        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def delete_last_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف آخر إدخال للمستخدم"""
    user_id = update.effective_user.id
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT id FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("⚠️ لا يوجد إدخال سابق لك.")
        return
    cur.execute("DELETE FROM history WHERE id = %s", (row[0],))
    conn.commit()
    conn.close()
    await update.message.reply_text("🗑️ تم حذف آخر إدخال لك.")

async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحميل قاعدة البيانات (للمسؤول فقط)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمسؤول فقط.")
        return
    status = await update.message.reply_text("📊 جاري التصدير...")
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT * FROM history ORDER BY id ASC", conn)
        conn.close()
        filename = f"Observer_Log_{datetime.date.today()}.xlsx"
        df.to_excel(filename, index=False)
        with open(filename, "rb") as f:
            await update.message.reply_document(document=f, filename=filename, caption=f"📊 {len(df)} جولة.")
        os.remove(filename)
        await status.delete()
    except Exception as e:
        await status.edit_text(f"❌ فشل: {e}")

# ==================== 6. المعالجات الأساسية ====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start.")
            return

        current_time = datetime.datetime.now()
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        last_time = row[0] if row else None
        conn.close()

        pred_text, pred_code, gap = sovereign_math_engine(text, context.user_data['suit'], last_time, current_time)

        context.user_data['bonus'] = text
        context.user_data['prediction_code'] = pred_code
        context.user_data['current_time'] = current_time

        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
        ]
        await update.message.reply_text(
            f"🎯 **التوقع:** {pred_text}\n"
            f"⏱️ الفجوة الزمنية: {gap} ثانية\n"
            f"━━━━━━━━━━━━━━\n"
            f"اختر النتيجة الحقيقية:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ أرسل رقماً صحيحاً (7 أرقام على الأقل).")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("s_"):
        suit = query.data[2:]
        context.user_data['suit'] = suit
        color = "🔴 حمراء" if suit in ['♦️', '♥️'] else "⚫ سوداء"
        await query.edit_message_text(f"✅ تم اختيار {suit} ({color})\n📥 أرسل رقم البونص:")

    elif query.data.startswith("save_"):
        winner_db = query.data[5:]
        pred_code = context.user_data.get('prediction_code')
        if pred_code is None:
            await query.edit_message_text("❌ خطأ: لا يوجد توقع. ابدأ من جديد.")
            return

        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO history (b_num, suit, winner, timestamp, prediction, user_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                context.user_data['bonus'],
                context.user_data['suit'],
                winner_db,
                context.user_data['current_time'],
                pred_code,
                update.effective_user.id
            ))
            conn.commit()
            conn.close()

            pred_winner = WINNER_NAMES[pred_code]
            is_correct = "✅" if winner_db == pred_winner else "❌"

            # أزرار بعد الحفظ
            keyboard = [
                [InlineKeyboardButton("🔄 بدء جولة جديدة", callback_data="new_round"),
                 InlineKeyboardButton("🗑️ حذف آخر إدخال", callback_data="delete_last")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"{is_correct} **تم التسجيل**\n\n"
                f"🎯 توقعنا: {pred_winner}\n"
                f"🏆 النتيجة: {winner_db}\n"
                f"━━━━━━━━━━━━━━\n"
                f"/performance - تحليل\n"
                f"/status - حالة النموذج\n"
                f"/delete - حذف آخر إدخال",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {e}")

    elif query.data == "new_round":
        await start(update, context)

    elif query.data == "delete_last":
        user_id = update.effective_user.id
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT id FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM history WHERE id = %s", (row[0],))
            conn.commit()
            await query.edit_message_text("🗑️ تم حذف آخر إدخال لك.\nأرسل /start لبدء جولة جديدة.")
        else:
            await query.edit_message_text("⚠️ لا يوجد إدخال سابق لك.")
        conn.close()

# ==================== 7. التشغيل الرئيسي ====================
if __name__ == "__main__":
    # التأكد من وجود الأعمدة المطلوبة
    ensure_columns()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("status", model_status))
    app.add_handler(CommandHandler("delete", delete_last_entry))
    app.add_handler(CommandHandler("download", download_database))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🚀 HADES V100.0 يعمل... (إصدار مستقر)")
    app.run_polling()
