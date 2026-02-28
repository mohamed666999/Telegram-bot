import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# خريطة تحويل أسماء الفائزين إلى أرقام (مع جميع المتغيرات الممكنة)
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
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
    المعادلة الرياضية السيادية:
    R = (B × S) + ΔT
    """
    last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
    B = sum(int(d) for d in last_3 if d.isdigit())
    S = 1 if suit in ['♦️', '♥️'] else 2
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    R = (B * S) + delta_t
    prediction_code = 1 if (R % 2 == 0) else 0  # 1=ثور, 0=راعي
    prediction_text = WINNER_NAMES[prediction_code]
    return prediction_text, prediction_code, R, delta_t, B, S

# ==================== 4. Bayesian Adaptive Layer (مُحسّن) ====================
def bayesian_adjustment(prediction_code: int, current_hour: int, conn, min_samples: int = 15):
    """
    تعديل التوقع باستخدام Bayes Theorem مع الاحتمالات الشرطية للفترة الزمنية
    """
    try:
        period = get_time_period(current_hour)
        
        # جلب البيانات التاريخية للفترة الحالية فقط (أحدث 200 جولة)
        df = pd.read_sql("""
            SELECT winner, prediction, timestamp 
            FROM history 
            WHERE prediction IS NOT NULL 
            ORDER BY id DESC 
            LIMIT 200
        """, conn)
        
        if len(df) < min_samples:
            return prediction_code, None, None  # بيانات غير كافية
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        
        # فلترة الفترة الحالية
        period_data = df[df['period'] == period]
        if len(period_data) < min_samples:
            return prediction_code, None, None
        
        # تحويل النصوص إلى أكواد رقمية للمقارنة الصحيحة
        period_data['winner_code'] = period_data['winner'].map(WINNER_MAP)
        period_data = period_data.dropna(subset=['winner_code'])
        
        if len(period_data) < min_samples:
            return prediction_code, None, None
        
        # حساب الاحتمالات الشرطية P(Winner|Period)
        total = len(period_data)
        p_rai = (period_data['winner_code'] == 0).sum() / total
        p_thawr = (period_data['winner_code'] == 1).sum() / total
        p_tie = (period_data['winner_code'] == 2).sum() / total
        
        # Prior probabilities (من المعادلة الرياضية)
        # نعطي 0.85 للفئة المختارة و0.15 للأخرى (ثقة عالية في المعادلة)
        if prediction_code == 0:  # راعي
            prior_rai, prior_thawr = 0.85, 0.15
        else:  # ثور
            prior_rai, prior_thawr = 0.15, 0.85
        
        # Bayesian Update: Posterior ∝ Prior × Likelihood
        # Normalization
        norm_rai = prior_rai * p_rai
        norm_thawr = prior_thawr * p_thawr
        
        if (norm_rai + norm_thawr) == 0:
            return prediction_code, None, None
        
        posterior_rai = norm_rai / (norm_rai + norm_thawr)
        posterior_thawr = norm_thawr / (norm_rai + norm_thawr)
        
        # القرار النهائي
        adjusted_code = 0 if posterior_rai > posterior_thawr else 1
        
        # حساب "قوة التعديل" (confidence في التعديل)
        confidence_diff = abs(posterior_rai - posterior_thawr)
        
        return adjusted_code, (posterior_rai, posterior_thawr), confidence_diff
        
    except Exception as e:
        print(f"Bayesian Error: {e}")
        return prediction_code, None, None

# ==================== 5. أوامر البوت ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء التفاعل مع اختيار البذلة"""
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️ ديناري (أحمر)", callback_data="s_♦️"), 
         InlineKeyboardButton("♥️ قلب (أحمر)", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد (أسود)", callback_data="s_♠️"), 
         InlineKeyboardButton("♣️ كلبة (أسود)", callback_data="s_♣️")]
    ]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي HADES V100.2**\n"
        "محرك تنبؤي بايزي متطور مع تحليل زمني.\n\n"
        "🎴 اختر نوع البذلة:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحليل شامل للأداء"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        
        # جلب البيانات مع فلترة القيم الناقصة
        df = pd.read_sql("""
            SELECT winner, prediction, timestamp, suit 
            FROM history 
            WHERE prediction IS NOT NULL
        """, conn)
        conn.close()

        if len(df) < 10:
            await update.message.reply_text("⚠️ البيانات غير كافية (نحتاج 10 جولات على الأقل).")
            return

        # تحضير البيانات
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

        if len(df) < 10:
            await update.message.reply_text("⚠️ بيانات غير صالحة بعد التنظيف.")
            return

        # تحليل الفترات (مع ترتيب ثابت)
        period_order = ["morning", "afternoon", "evening", "night"]
        period_accuracy = df.groupby('period')['correct'].mean().reindex(period_order) * 100

        # تحليل الساعات (مع حد أدنى 10 جولات)
        hour_stats = df.groupby('hour').agg(
            accuracy=('correct', 'mean'),
            count=('correct', 'count')
        )
        hour_stats = hour_stats[hour_stats['count'] >= 10]
        hour_accuracy = hour_stats['accuracy'] * 100

        # تحليل البذلة
        suit_stats = df.groupby('suit').agg(
            accuracy=('correct', 'mean'),
            count=('correct', 'count')
        ) * 100
        suit_stats['accuracy'] = suit_stats['accuracy']

        # بناء التقرير
        report = "📊 **تقرير أداء HADES**\n━━━━━━━━━━━━━━\n"
        
        report += "**🕐 الدقة حسب الفترة:**\n"
        for p in period_order:
            if p in period_accuracy and not pd.isna(period_accuracy[p]):
                emoji = "🟢" if period_accuracy[p] >= 60 else "🟡" if period_accuracy[p] >= 50 else "🔴"
                report += f"{emoji} {period_translate(p)}: {period_accuracy[p]:.1f}%\n"
        
        report += f"\n📈 **الدقة العامة:** {df['correct'].mean()*100:.1f}% ({len(df)} جولة)\n"

        if not hour_accuracy.empty:
            report += "\n🏆 **أفضل 3 ساعات:**\n"
            for h, acc in hour_accuracy.nlargest(3).items():
                report += f"🟢 {h:02d}:00 → {acc:.1f}%\n"
            
            report += "\n⚠️ **أسوأ 3 ساعات:**\n"
            for h, acc in hour_accuracy.nsmallest(3).items():
                report += f"🔴 {h:02d}:00 → {acc:.1f}%\n"

        if not suit_stats.empty:
            report += "\n🎴 **الدقة حسب البذلة:**\n"
            for suit, row in suit_stats.iterrows():
                emoji = "🟢" if row['accuracy'] >= 60 else "🟡" if row['accuracy'] >= 50 else "🔴"
                report += f"{emoji} {suit}: {row['accuracy']:.1f}% ({int(row['count'])} جولة)\n"

        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في التحليل: {e}")

async def model_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حالة صحة النموذج"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        
        df = pd.read_sql("""
            SELECT winner, prediction, timestamp 
            FROM history 
            WHERE prediction IS NOT NULL 
            ORDER BY id DESC 
            LIMIT 200
        """, conn)
        conn.close()

        if len(df) < 10:
            await update.message.reply_text("⚠️ بيانات غير كافية.")
            return

        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

        # آخر 50 و200 جولة
        acc_50 = df.head(50)['correct'].mean() * 100 if len(df) >= 50 else None
        acc_200 = df['correct'].mean() * 100

        # أفضل/أسوأ ساعة
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        hour_stats = df.groupby('hour').agg(
            acc=('correct', 'mean'),
            cnt=('correct', 'count')
        )
        hour_stats = hour_stats[hour_stats['cnt'] >= 10]
        
        best_hour = worst_hour = None
        if not hour_stats.empty:
            best_hour = hour_stats['acc'].idxmax()
            worst_hour = hour_stats['acc'].idxmin()

        # التقييم
        status = "🔻 ضعيف"
        if acc_200 >= 65:
            status = "✅ ممتاز"
        elif acc_200 >= 58:
            status = "⚖️ مقبول"

        report = "🧠 **حالة محرك HADES**\n━━━━━━━━━━━━━━\n"
        if acc_50:
            report += f"📉 آخر 50 جولة: {acc_50:.1f}%\n"
        report += f"📊 آخر 200 جولة: {acc_200:.1f}%\n"
        
        if best_hour is not None:
            report += f"\n🏆 أفضل ساعة: {best_hour:02d}:00\n"
            report += f"⚠️ أسوأ ساعة: {worst_hour:02d}:00\n"
        
        report += f"\n**التقييم:** {status}"
        
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 6. المعالجات الأساسية ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إدخال رقم البونص مع Bayesian Adjustment"""
    text = update.message.text.strip()
    
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start.")
            return

        current_time = datetime.datetime.now()

        # جلب آخر جولة
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        last_time = row[0] if row else None

        # التنبؤ الأصلي
        pred_text, pred_code, R, gap, B, S = sovereign_math_engine(
            text, context.user_data['suit'], last_time, current_time
        )

        # Bayesian Adjustment
        adjusted_code, posteriors, confidence = bayesian_adjustment(
            pred_code, current_time.hour, conn
        )
        
        # إغلاق الاتصال مؤقتاً (سنفتحه لاحقاً إذا لزم الأمر)
        cur.close()
        conn.close()

        # بناء رسالة التوقع
        warning_text = ""
        if adjusted_code is not None and adjusted_code != pred_code and posteriors is not None:
            pred_code = adjusted_code
            pred_text = WINNER_NAMES[pred_code]
            p_rai, p_thawr = posteriors
            warning_text = (
                f"⚠️ **تعديل بايزي:**\n"
                f"المعادلة: {WINNER_NAMES[1 if (R % 2 == 0) else 0]} | "
                f"البيانات: راعي {p_rai*100:.0f}% vs ثور {p_thawr*100:.0f}%\n"
                f"→ التوقع المعدل: {pred_text}\n\n"
            )
        elif posteriors is not None:
            p_rai, p_thawr = posteriors
            warning_text = (
                f"ℹ️ **دعم بايزي:** "
                f"التاريخ يفضل {WINNER_NAMES[0] if p_rai > p_thawr else WINNER_NAMES[1]} "
                f"({max(p_rai, p_thawr)*100:.0f}%)\n\n"
            )

        # تخزين البيانات
        context.user_data['bonus'] = text
        context.user_data['prediction_code'] = pred_code
        context.user_data['current_time'] = current_time

        # أزرار النتيجة
        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
        ]

        suit_color = "🔴" if context.user_data['suit'] in ['♦️', '♥️'] else "⚫"
        
        await update.message.reply_text(
            f"{warning_text}"
            f"🎯 **التوقع النهائي:** {pred_text}\n"
            f"🎴 البذلة: {context.user_data['suit']} {suit_color}\n"
            f"🔢 المعادلة: B={B} × S={S} + ΔT={gap} → R={R}\n"
            f"━━━━━━━━━━━━━━\n"
            f"اختر النتيجة الحقيقية:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )

    else:
        await update.message.reply_text("❌ أدخل رقم صحيح (7 أرقام على الأقل).")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار مع التحقق من البيانات"""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("s_"):
        suit = query.data[2:]
        context.user_data['suit'] = suit
        color = "🔴 حمراء" if suit in ['♦️', '♥️'] else "⚫ سوداء"
        await query.edit_message_text(
            f"✅ تم اختيار: {suit} ({color})\n"
            f"📥 أرسل رقم البونص:"
        )

    elif query.data.startswith("save_"):
        winner_db = query.data[5:]  # استخراج الاسم الكامل مع الإيموجي
        pred_code = context.user_data.get('prediction_code')
        
        if pred_code is None:
            await query.edit_message_text("❌ خطأ: لا يوجد توقع مخزن. ابدأ من جديد.")
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

            pred_winner = WINNER_NAMES[pred_code]
            is_correct = "✅" if winner_db == pred_winner else "❌"
            
            await query.edit_message_text(
                f"{is_correct} **تم التسجيل**\n\n"
                f"🎯 توقعنا: {pred_winner}\n"
                f"🏆 النتيجة: {winner_db}\n"
                f"━━━━━━━━━━━━━━\n"
                f"/performance - التحليل\n"
                f"/status - حالة النموذج",
                parse_mode='Markdown'
            )
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {e}")

# ==================== 7. التشغيل الرئيسي ====================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    # الأوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("status", model_status))

    # المعالجات
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("🚀 HADES V100.2 يعمل...")
    print("🏛️ محرك بايزي تكيفي")
    app.run_polling()
