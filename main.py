import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
from collections import deque
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# خريطة تحويل أسماء الفائزين إلى أرقام (للمقارنة)
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0,
    'الثور 🔵': 1, 'ثور': 1,
    'تعادل ⚪': 2, 'تعادل': 2
}

# أسماء الفائزين بالعربية مع الرموز (للعرض)
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

# ==================== 2. دوال تحليل الوقت ====================
def get_time_period(hour: int) -> str:
    """تحديد الفترة الزمنية بناءً على الساعة"""
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 24:
        return "evening"
    else:
        return "night"

def period_translate(period: str) -> str:
    """ترجمة الفترة إلى العربية مع رمز"""
    return {
        "morning": "🌅 الصباح",
        "afternoon": "☀️ الظهر",
        "evening": "🌇 المساء",
        "night": "🌙 الليل"
    }.get(period, period)

# ==================== 3. المحرك الرياضي الأساسي ====================
def sovereign_math_engine(b_num: str, suit: str, last_timestamp, current_timestamp):
    """
    المعادلة الرياضية الأساسية:
    - B = مجموع آخر 3 أرقام من b_num
    - S = 1 إذا كانت البذلة حمراء (♦️,♥️) ، 2 إذا سوداء (♠️,♣️)
    - ΔT = الفجوة الزمنية بالثواني عن آخر جولة
    - R = (B * S) + ΔT
    - النتيجة: زوجي → ثور (1) ، فردي → راعي (0)
    """
    last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
    B = sum(int(d) for d in last_3 if d.isdigit())
    S = 1 if suit in ['♦️', '♥️'] else 2
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    R = (B * S) + delta_t
    prediction_code = 1 if (R % 2 == 0) else 0  # 1=ثور, 0=راعي
    prediction_text = WINNER_NAMES[prediction_code]
    return prediction_text, prediction_code, R, delta_t

# ==================== 4. دوال التحليل المتقدم ====================
def analyze_performance(conn):
    """
    تحليل أداء التوقعات حسب الفترات والساعات.
    تعيد قاموساً يحتوي على:
    - period_accuracy: دقة كل فترة
    - hour_accuracy: دقة كل ساعة (مع شرط الحد الأدنى 10 جولات)
    - best_hours, worst_hours: أفضل وأسوأ 3 ساعات
    - total_rounds: عدد الجولات المحللة
    """
    df = pd.read_sql(
        "SELECT winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL",
        conn
    )
    if len(df) < 10:
        return None

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['period'] = df['hour'].apply(get_time_period)

    # تحويل winner إلى كود رقمي
    df['winner_code'] = df['winner'].map(WINNER_MAP)
    # حذف الصفوف التي فشل فيها التحويل (winner غير معروف) أو prediction فارغ
    df = df.dropna(subset=['winner_code', 'prediction'])
    df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

    # تحليل الفترات
    period_order = ["morning", "afternoon", "evening", "night"]
    period_accuracy = df.groupby('period')['correct'].mean().reindex(period_order) * 100

    # تحليل الساعات مع شرط الحد الأدنى 10 جولات
    hour_stats = df.groupby('hour').agg(
        accuracy=('correct', 'mean'),
        count=('correct', 'count')
    ).reset_index()
    hour_stats['accuracy'] *= 100
    hour_stats = hour_stats[hour_stats['count'] >= 10]
    hour_accuracy = hour_stats.set_index('hour')['accuracy']

    # أفضل وأسوأ 3 ساعات
    best_hours = hour_accuracy.nlargest(3)
    worst_hours = hour_accuracy.nsmallest(3)

    return {
        'period_accuracy': period_accuracy,
        'hour_accuracy': hour_accuracy,
        'best_hours': best_hours,
        'worst_hours': worst_hours,
        'total_rounds': len(df)
    }

def analyze_by_suit(conn):
    """تحليل الدقة حسب نوع البذلة مع عدد الجولات"""
    df = pd.read_sql(
        "SELECT suit, winner, prediction FROM history WHERE prediction IS NOT NULL",
        conn
    )
    if df.empty:
        return None
    df['winner_code'] = df['winner'].map(WINNER_MAP)
    df = df.dropna(subset=['winner_code', 'prediction'])
    df['correct'] = (df['winner_code'] == df['prediction']).astype(int)
    suit_stats = df.groupby('suit').agg(
        accuracy=('correct', 'mean'),
        count=('correct', 'count')
    )
    suit_stats['accuracy'] *= 100
    return suit_stats

def analyze_by_last_digit(conn):
    """تحليل الدقة حسب آخر رقم مع الفترة الزمنية"""
    df = pd.read_sql(
        "SELECT b_num, winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL",
        conn
    )
    if df.empty:
        return None
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['period'] = df['hour'].apply(get_time_period)
    df['last_digit'] = df['b_num'].astype(str).str[-1].astype(int)

    df['winner_code'] = df['winner'].map(WINNER_MAP)
    df = df.dropna(subset=['winner_code', 'prediction'])
    df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

    # فلترة الأرقام التي لديها على الأقل 10 جولات
    digit_counts = df['last_digit'].value_counts()
    valid_digits = digit_counts[digit_counts >= 10].index
    df = df[df['last_digit'].isin(valid_digits)]

    if df.empty:
        return None

    pivot = df.pivot_table(
        index='last_digit',
        columns='period',
        values='correct',
        aggfunc='mean'
    ) * 100
    # ترتيب الفترات
    pivot = pivot.reindex(columns=["morning", "afternoon", "evening", "night"])
    return pivot.round(1)

def model_health_check(conn):
    """فحص صحة النموذج: آخر 50 و200 جولة، أفضل وأسوأ ساعة"""
    df = pd.read_sql(
        "SELECT winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL ORDER BY id DESC",
        conn
    )
    if len(df) < 10:
        return None

    df['winner_code'] = df['winner'].map(WINNER_MAP)
    df = df.dropna(subset=['winner_code', 'prediction'])
    df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

    # آخر 50 جولة
    last_50 = df.head(50)
    acc_50 = last_50['correct'].mean() * 100 if len(last_50) >= 10 else None

    # آخر 200 جولة
    last_200 = df.head(200)
    acc_200 = last_200['correct'].mean() * 100 if len(last_200) >= 10 else None

    # أفضل وأسوأ ساعة من كل التاريخ (مع حد 10 جولات)
    df_all = df.copy()
    df_all['hour'] = pd.to_datetime(df_all['timestamp']).dt.hour
    hour_stats = df_all.groupby('hour').agg(
        acc=('correct', 'mean'),
        cnt=('correct', 'count')
    )
    hour_stats = hour_stats[hour_stats['cnt'] >= 10]
    if not hour_stats.empty:
        best_hour = hour_stats['acc'].idxmax()
        best_acc = hour_stats.loc[best_hour, 'acc'] * 100
        worst_hour = hour_stats['acc'].idxmin()
        worst_acc = hour_stats.loc[worst_hour, 'acc'] * 100
    else:
        best_hour = worst_hour = None
        best_acc = worst_acc = None

    return {
        'acc_50': acc_50,
        'acc_200': acc_200,
        'best_hour': best_hour,
        'best_acc': best_acc,
        'worst_hour': worst_hour,
        'worst_acc': worst_acc
    }

def get_current_period_accuracy(conn, current_hour):
    """الحصول على دقة الفترة الحالية (للاستخدام في التحذيرات)"""
    df = pd.read_sql(
        "SELECT winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL",
        conn
    )
    if len(df) < 10:
        return None
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['period'] = df['hour'].apply(get_time_period)
    df['winner_code'] = df['winner'].map(WINNER_MAP)
    df = df.dropna(subset=['winner_code', 'prediction'])
    df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

    current_period = get_time_period(current_hour)
    period_data = df[df['period'] == current_period]
    if len(period_data) < 10:
        return None
    acc = period_data['correct'].mean() * 100
    return acc

# ==================== 5. أوامر البوت ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]
    ]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي HADES V100.0**\n"
        "محرك تنبؤي متطور مع تحليل زمني ومراقبة الأداء.\n"
        "اختر البذلة للبدء:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("📊 جاري تصدير السجل السيادي...")
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

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض أداء التوقعات حسب الفترات والساعات"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        perf = analyze_performance(conn)
        conn.close()

        if perf is None:
            await update.message.reply_text("⚠️ البيانات غير كافية (نحتاج 10 جولات على الأقل مع توقعات).")
            return

        report = "📊 **تقرير أداء HADES**\n━━━━━━━━━━━━━━\n"
        report += "**الفترات:**\n"
        for period, acc in perf['period_accuracy'].items():
            if not pd.isna(acc):
                report += f"{period_translate(period)}: {acc:.1f}%\n"

        report += "\n**أفضل 3 ساعات:**\n"
        for hour, acc in perf['best_hours'].items():
            report += f"🟢 {hour:02d}:00 → {acc:.1f}%\n"

        report += "\n**أسوأ 3 ساعات:**\n"
        for hour, acc in perf['worst_hours'].items():
            report += f"🔴 {hour:02d}:00 → {acc:.1f}%\n"

        report += f"\n📈 إجمالي الجولات المحللة: {perf['total_rounds']}"
        await update.message.reply_text(report)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في التحليل: {e}")

async def advanced_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحليل متقدم حسب آخر رقم والفترة"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        pivot = analyze_by_last_digit(conn)
        suit_stats = analyze_by_suit(conn)
        conn.close()

        report = "🔬 **تحليل متقدم**\n━━━━━━━━━━━━━━━\n"

        if suit_stats is not None and not suit_stats.empty:
            report += "**الدقة حسب البذلة:**\n"
            for suit, row in suit_stats.iterrows():
                report += f"{suit} : {row['accuracy']:.1f}% ({int(row['count'])} جولة)\n"
        else:
            report += "لا توجد بيانات كافية لتحليل البذلة.\n"

        if pivot is not None and not pivot.empty:
            report += "\n**الدقة حسب آخر رقم والفترة (نسبة مئوية):**\n"
            # تحويل pivot إلى نص منسق
            report += "```\n" + pivot.to_string() + "\n```"
        else:
            report += "\nلا توجد بيانات كافية لتحليل آخر رقم (يحتاج 10 جولات على الأقل لكل رقم)."

        await update.message.reply_text(report)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في التحليل: {e}")

async def model_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حالة صحة النموذج"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        health = model_health_check(conn)
        conn.close()

        if health is None:
            await update.message.reply_text("⚠️ البيانات غير كافية (نحتاج 10 جولات على الأقل).")
            return

        report = "🧠 **حالة محرك HADES**\n━━━━━━━━━━━━━━━\n"
        if health['acc_50'] is not None:
            report += f"📉 آخر 50 جولة: {health['acc_50']:.1f}%\n"
        if health['acc_200'] is not None:
            report += f"📊 آخر 200 جولة: {health['acc_200']:.1f}%\n"

        if health['best_hour'] is not None:
            report += f"🏆 أفضل ساعة: {health['best_hour']:02d}:00 ({health['best_acc']:.1f}%)\n"
        if health['worst_hour'] is not None:
            report += f"⚠️ أسوأ ساعة: {health['worst_hour']:02d}:00 ({health['worst_acc']:.1f}%)\n"

        # تقييم عام
        if health['acc_200'] is not None:
            if health['acc_200'] >= 65:
                status = "✅ ممتاز"
            elif health['acc_200'] >= 58:
                status = "⚖️ مقبول"
            else:
                status = "🔻 ضعيف (ينصح بإعادة تقييم البيانات)"
            report += f"\n**التقييم العام:** {status}"

        await update.message.reply_text(report)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 6. المعالجات الأساسية ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start.")
            return

        current_time = datetime.datetime.now()

        # جلب توقيت آخر جولة مسجلة في قاعدة البيانات
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                last_time = row[0] if row else None
            conn.close()
        except Exception as e:
            print(f"Database read error: {e}")
            last_time = None

        # التنبؤ
        pred_text, pred_code, R, gap = sovereign_math_engine(
            text, context.user_data['suit'], last_time, current_time
        )

        # تخزين البيانات في context
        context.user_data['bonus'] = text
        context.user_data['prediction_code'] = pred_code
        context.user_data['current_time'] = current_time

        # تحذير زمني (اختياري)
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            period_acc = get_current_period_accuracy(conn, current_time.hour)
            conn.close()
            if period_acc is not None and period_acc < 58:
                warning = f"⚠️ تحذير: دقة النموذج في هذه الفترة ({period_translate(get_time_period(current_time.hour))}) منخفضة ({period_acc:.1f}%).\n"
            else:
                warning = ""
        except:
            warning = ""

        # أزرار الاختيار
        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_راعي"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_ثور")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]
        ]

        await update.message.reply_text(
            f"{warning}"
            f"🎯 **التوقع:** {pred_text}\n"
            f"⏱️ الفجوة: {gap} ثانية | المعادلة: {R}\n"
            f"━━━━━━━━━━━━━━\n"
            f"سجل النتيجة الحقيقية:",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    else:
        await update.message.reply_text("❌ الرقم يجب أن يتكون من 7 أرقام على الأقل ولا يحتوي على أحرف.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("s_"):
        # اختيار البذلة
        context.user_data['suit'] = query.data[2:]
        await query.edit_message_text(f"✅ رادار {context.user_data['suit']} نشط.\n📥 أرسل رقم البونص (b_num):")

    elif query.data.startswith("save_"):
        # حفظ النتيجة الفعلية
        winner_text = query.data.split("_", 1)[1]  # مثلاً "راعي" أو "ثور" أو "تعادل"
        # تحويل النص إلى الصيغة المخزنة (مطابقة لـ WINNER_MAP)
        # نحتاج للتأكد من أنها تطابق المفاتيح في WINNER_MAP
        if winner_text == "راعي":
            winner_db = "الراعي 🔴"
        elif winner_text == "ثور":
            winner_db = "الثور 🔵"
        elif winner_text == "تعادل":
            winner_db = "تعادل ⚪"
        else:
            winner_db = winner_text  # افتراضي

        pred_code = context.user_data.get('prediction_code')
        if pred_code is None:
            await query.edit_message_text("❌ لا يوجد توقع مخزن. أعد إدخال الرقم.")
            return

        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO history (b_num, suit, winner, timestamp, prediction)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                context.user_data['bonus'],
                context.user_data['suit'],
                winner_db,
                context.user_data['current_time'],
                pred_code
            ))
            conn.commit()
            conn.close()

            await query.edit_message_text(
                f"✅ تم الحفظ.\n"
                f"النتيجة الفعلية: {winner_db}\n"
                f"توقع النموذج: {WINNER_NAMES[pred_code]}\n"
                f"━━━━━━━━━━━━━━\n"
                f"يمكنك متابعة التحليلات بـ /performance"
            )
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {e}")

# ==================== 7. التشغيل الرئيسي ====================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    # أوامر التحليل
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("advanced", advanced_analysis))
    app.add_handler(CommandHandler("status", model_status))
    app.add_handler(CommandHandler("download", download_database))
    app.add_handler(CommandHandler("start", start))

    # معالج الأزرار
    app.add_handler(CallbackQueryHandler(callback_handler))

    # معالج الرسائل النصية
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("🚀 بوت HADES V100.0 يعمل الآن...")
    app.run_polling()
