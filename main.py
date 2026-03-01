import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
import secrets
import random
from collections import deque
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

PLANS = {'day': 1, 'two_days': 2, 'week': 7, 'month': 30}

PLAY_SESSION_MINUTES = 30
COOL_DOWN_1_MIN = (5, 10)
COOL_DOWN_2_MIN = 15
MAX_CORRECT_STREAK = 10

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

# ==================== 3. دوال إدارة الاشتراكات ====================
def init_subscription_table():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscription_keys (
            id SERIAL PRIMARY KEY,
            key_code VARCHAR(50) UNIQUE NOT NULL,
            plan VARCHAR(20) NOT NULL,
            is_used BOOLEAN DEFAULT FALSE,
            used_by BIGINT,
            used_at TIMESTAMP,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def generate_keys():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    for plan in PLANS.keys():
        for _ in range(5):
            key = secrets.token_urlsafe(16)
            try:
                cur.execute("INSERT INTO subscription_keys (key_code, plan) VALUES (%s, %s)", (key, plan))
            except psycopg2.IntegrityError:
                conn.rollback()
                continue
    conn.commit()
    conn.close()

def is_user_subscribed(user_id):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("""
        SELECT plan, expires_at FROM subscription_keys 
        WHERE used_by = %s AND expires_at > NOW() 
        ORDER BY expires_at DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        plan, expires = row
        remaining = (expires - datetime.datetime.now()).days
        return True, plan, remaining
    return False, None, 0

def activate_subscription(user_id, key_code):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT id, plan, is_used FROM subscription_keys WHERE key_code = %s", (key_code,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    key_id, plan, is_used = row
    if is_used:
        conn.close()
        return False
    days = PLANS.get(plan)
    if not days:
        conn.close()
        return False
    expires_at = datetime.datetime.now() + datetime.timedelta(days=days)
    cur.execute("""
        UPDATE subscription_keys 
        SET is_used = TRUE, used_by = %s, used_at = NOW(), expires_at = %s
        WHERE id = %s
    """, (user_id, expires_at, key_id))
    conn.commit()
    conn.close()
    return True

# ==================== 4. دوال إدارة التباعد الزمني ====================
def init_user_session(context):
    if 'session_start' not in context.user_data:
        context.user_data['session_start'] = None
        context.user_data['session_play_minutes'] = 0
        context.user_data['cool_until'] = None
        context.user_data['cool_stage'] = 0
        context.user_data['correct_streak'] = 0

def can_user_play(user_id, context):
    if user_id == ADMIN_ID:
        return True, ""
    init_user_session(context)
    now = datetime.datetime.now()
    cool_until = context.user_data.get('cool_until')
    if cool_until and now < cool_until:
        remaining = (cool_until - now).seconds // 60
        remaining_seconds = (cool_until - now).seconds % 60
        return False, f"⏳ تبريد {remaining} د و{remaining_seconds} ث."
    if context.user_data['session_start'] is None:
        context.user_data['session_start'] = now
        context.user_data['session_play_minutes'] = 0
        return True, ""
    session_duration = (now - context.user_data['session_start']).total_seconds() / 60
    played = context.user_data['session_play_minutes'] + session_duration
    if played >= PLAY_SESSION_MINUTES:
        if context.user_data['cool_stage'] == 0:
            cool_minutes = random.randint(COOL_DOWN_1_MIN[0], COOL_DOWN_1_MIN[1])
            context.user_data['cool_stage'] = 1
        else:
            cool_minutes = COOL_DOWN_2_MIN
        context.user_data['cool_until'] = now + datetime.timedelta(minutes=cool_minutes)
        context.user_data['session_start'] = None
        context.user_data['session_play_minutes'] = 0
        return False, f"⏸️ انتهت الجلسة. انتظر {cool_minutes} د."
    return True, ""

def update_session_after_play(context):
    if context.user_data.get('session_start') is None:
        return
    now = datetime.datetime.now()
    session_duration = (now - context.user_data['session_start']).total_seconds() / 60
    context.user_data['session_play_minutes'] += session_duration
    context.user_data['session_start'] = now

def inject_fake_prediction(pred_code):
    return 1 if pred_code == 0 else 0

# ==================== 5. إدارة الأوزان والنموذج الخطي ====================
def init_weights_table():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS model_weights (
            class INTEGER NOT NULL,
            feature VARCHAR(50) NOT NULL,
            weight FLOAT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (class, feature)
        )
    """)
    conn.commit()
    conn.close()

def load_weights(conn):
    weights = [{}, {}, {}]  # 0=راعي, 1=ثور, 2=تعادل
    cur = conn.cursor()
    cur.execute("SELECT class, feature, weight FROM model_weights")
    rows = cur.fetchall()
    if rows:
        for class_idx, feat, w in rows:
            weights[class_idx][feat] = w
    else:
        # أوزان افتراضية (تميل للمعادلة الأصلية)
        default_weights = [
            {'sum_digits': 1.0, 'last_digit': 0.0, 'parity': 0.0, 'even_count': 0.0,
             'mean_digit': 0.0, 'span_digit': 0.0, 'suit': 0.5, 'delta_t_log': 0.1,
             'time_bucket': 0.0, 'last_winner': 0.0},
            {'sum_digits': 1.0, 'last_digit': 0.0, 'parity': 0.0, 'even_count': 0.0,
             'mean_digit': 0.0, 'span_digit': 0.0, 'suit': 0.5, 'delta_t_log': 0.1,
             'time_bucket': 0.0, 'last_winner': 0.0},
            {'sum_digits': 0.0, 'last_digit': 0.0, 'parity': 0.0, 'even_count': 0.0,
             'mean_digit': 0.0, 'span_digit': 0.0, 'suit': 0.0, 'delta_t_log': 0.0,
             'time_bucket': 0.0, 'last_winner': 0.0}
        ]
        for i in range(3):
            for feat, w in default_weights[i].items():
                weights[i][feat] = w
    return weights

def save_weights(conn, weights):
    cur = conn.cursor()
    # حذف القديم
    cur.execute("DELETE FROM model_weights")
    # إدراج الجديد
    for class_idx, feat_dict in enumerate(weights):
        for feat, w in feat_dict.items():
            cur.execute(
                "INSERT INTO model_weights (class, feature, weight) VALUES (%s, %s, %s)",
                (class_idx, feat, w)
            )
    conn.commit()

def extract_math_features(b_num: str, suit: str, delta_t: int, last_winner: int = None):
    """
    استخراج الميزات من الرقم والبذلة والفجوة الزمنية.
    last_winner: 0,1,2 أو None.
    """
    digits = [int(d) for d in b_num if d.isdigit()]
    if not digits:
        return None
    # ميزات أساسية
    sum_digits = sum(digits[-3:])            # مجموع آخر 3 أرقام
    last_digit = digits[-1]                   # آخر رقم
    parity = last_digit % 2                    # 0 زوجي, 1 فردي
    even_count = sum(1 for d in digits if d % 2 == 0)  # عدد الأرقام الزوجية
    mean_digit = sum(digits) / len(digits)     # متوسط الأرقام
    span_digit = max(digits) - min(digits)     # المدى
    suit_code = 1 if suit in ['♦️', '♥️'] else 2  # لون البذلة
    delta_t_log = np.log1p(delta_t)            # ln(ΔT+1)

    # تقسيم الفجوة الزمنية إلى فئات (time bucket)
    if delta_t < 30:
        time_bucket = 0
    elif delta_t < 300:
        time_bucket = 1
    elif delta_t < 1800:
        time_bucket = 2
    else:
        time_bucket = 3

    # تجميع الميزات (بدون تطبيع بعد)
    raw = {
        'sum_digits': sum_digits,
        'last_digit': last_digit,
        'parity': parity,
        'even_count': even_count,
        'mean_digit': mean_digit,
        'span_digit': span_digit,
        'suit': suit_code,
        'delta_t_log': delta_t_log,
        'time_bucket': time_bucket,
    }
    if last_winner is not None:
        raw['last_winner'] = last_winner

    # تطبيع الميزات (جعلها في نطاق 0-1 تقريباً)
    normalized = {
        'sum_digits': raw['sum_digits'] / 27.0,
        'last_digit': raw['last_digit'] / 9.0,
        'parity': float(raw['parity']),          # 0 أو 1
        'even_count': raw['even_count'] / 6.0,
        'mean_digit': raw['mean_digit'] / 9.0,
        'span_digit': raw['span_digit'] / 9.0,
        'suit': raw['suit'] / 2.0,
        'delta_t_log': raw['delta_t_log'] / 10.0,
        'time_bucket': raw['time_bucket'] / 3.0,
    }
    if last_winner is not None:
        normalized['last_winner'] = raw['last_winner'] / 2.0

    return normalized

def predict_linear(features, weights):
    """
    حساب الدرجات لكل فئة باستخدام الأوزان الخطية.
    تُرجع (الفئة المتوقعة, مصفوفة الاحتمالات).
    """
    scores = []
    for i in range(3):
        score = 0.0
        for feat, val in features.items():
            score += weights[i].get(feat, 0.0) * val
        scores.append(score)
    # تحويل إلى احتمالات عبر softmax
    exp_scores = np.exp(scores - np.max(scores))  # للاستقرار العددي
    probs = exp_scores / np.sum(exp_scores)
    return int(np.argmax(probs)), probs

def update_weights(weights, features, predicted_class, actual_class, lr=0.005, reg=0.0001):
    """
    تحديث الأوزان بطريقة perceptron مع L2 regularization.
    """
    if predicted_class == actual_class:
        return weights  # لا تحديث إذا كان صحيحاً (اختياري، يمكنك دائماً التحديث بقوة أقل)

    for key, val in features.items():
        # زيادة وزن الفئة الصحيحة
        weights[actual_class][key] += lr * val
        # تقليل وزن الفئة المتوقعة الخاطئة
        weights[predicted_class][key] -= lr * val

        # تطبيق regularization (L2 بسيط)
        weights[actual_class][key] *= (1 - reg)
        weights[predicted_class][key] *= (1 - reg)

    return weights

# ==================== 6. التحليل البايزي (مع استبعاد غير الرقمي) ====================
def bayesian_analysis(conn, current_hour, min_samples=30):
    try:
        df = pd.read_sql("""
            SELECT winner, timestamp 
            FROM history 
            WHERE winner IS NOT NULL AND b_num ~ '^[0-9]+$'
        """, conn)
        if len(df) < min_samples:
            return None
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code'])
        periods = ['morning', 'afternoon', 'evening', 'night']
        bayesian_probs = {}
        for period in periods:
            period_data = df[df['period'] == period]
            if len(period_data) >= min_samples:
                total = len(period_data)
                p_rai = (period_data['winner_code'] == 0).sum() / total
                p_thawr = (period_data['winner_code'] == 1).sum() / total
                p_tie = (period_data['winner_code'] == 2).sum() / total
                bayesian_probs[period] = (p_rai, p_thawr, p_tie)
            else:
                bayesian_probs[period] = None
        return bayesian_probs
    except Exception as e:
        print(f"Bayesian Error: {e}")
        return None

# ==================== 7. دمج بايزي مع النموذج الخطي ====================
def hybrid_prediction(b_num, suit, last_timestamp, current_timestamp, bayesian_probs, math_weights, last_winner=None):
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    features = extract_math_features(b_num, suit, delta_t, last_winner)
    if features is None:
        return "تعادل ⚪", 2, 0, delta_t, 0, 0, "خطأ في استخراج الميزات"

    # التنبؤ بالنموذج الخطي
    linear_class, linear_probs = predict_linear(features, math_weights)
    linear_confidence = max(linear_probs)

    # التنبؤ البايزي
    if bayesian_probs:
        current_period = get_time_period(current_timestamp.hour)
        period_probs = bayesian_probs.get(current_period)
        if period_probs:
            p_rai, p_thawr, p_tie = period_probs
            bayes_probs = np.array([p_rai, p_thawr, p_tie])
            bayes_class = int(np.argmax(bayes_probs))
            bayes_confidence = max(bayes_probs)
        else:
            bayes_class, bayes_probs, bayes_confidence = None, None, 0.0
    else:
        bayes_class, bayes_probs, bayes_confidence = None, None, 0.0

    # دمج القرارات (نظام تصويت مرجح)
    if bayes_confidence > 0.6:
        # بايزي واثق
        final_class = bayes_class
        reason = f"بايزي (ثقة {bayes_confidence:.2f})"
    elif linear_confidence > 0.7:
        # النموذج الخطي واثق
        final_class = linear_class
        reason = f"نموذج خطي (ثقة {linear_confidence:.2f})"
    else:
        # مزج بسيط
        if bayes_probs is not None:
            mixed_probs = 0.6 * linear_probs + 0.4 * bayes_probs
        else:
            mixed_probs = linear_probs
        final_class = int(np.argmax(mixed_probs))
        reason = "مزج (60% خطي + 40% بايزي)" if bayes_probs is not None else "نموذج خطي فقط"

    final_text = WINNER_NAMES[final_class]
    return final_text, final_class, delta_t, delta_t, 0, 0, reason

# ==================== 8. أوامر البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribed, plan, remaining = is_user_subscribed(user_id)
    if not subscribed and user_id != ADMIN_ID:
        await update.message.reply_text(
            "🔐 **مرحبًا بك في HADES**\n"
            "للاستخدام، أدخل مفتاح اشتراك صالح.\n"
            "أرسل المفتاح الآن."
        )
        return
    context.user_data.clear()
    init_user_session(context)
    kb = [
        [InlineKeyboardButton("♦️ ديناري (أحمر)", callback_data="s_♦️"),
         InlineKeyboardButton("♥️ قلب (أحمر)", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد (أسود)", callback_data="s_♠️"),
         InlineKeyboardButton("♣️ كلبة (أسود)", callback_data="s_♣️")]
    ]
    remaining_text = f"اشتراكك ({plan}) متبقي {remaining} يوم." if subscribed else ""
    await update.message.reply_text(
        f"🏛️ **HADES V101**\n"
        f"محرك خطي متكيف + بايزي\n"
        f"{remaining_text}\n\n"
        "🎴 اختر نوع البذلة:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if activate_subscription(user_id, text):
        await update.message.reply_text("✅ تم تفعيل الاشتراك! أرسل /start للبدء.")
    else:
        await update.message.reply_text("❌ مفتاح غير صالح أو مستخدم.")

async def generate_keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمسؤول فقط.")
        return
    generate_keys()
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT key_code, plan FROM subscription_keys WHERE is_used = FALSE ORDER BY plan, id")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("⚠️ لا توجد مفاتيح.")
        return
    result = "🔑 **المفاتيح المتاحة:**\n\n"
    plans_keys = {plan: [] for plan in PLANS}
    for key, plan in rows:
        plans_keys[plan].append(key)
    for plan in PLANS:
        plan_name = {'day': '📆 يوم', 'two_days': '📆📆 يومين', 'week': '📅 أسبوع', 'month': '📅 شهر'}.get(plan, plan)
        keys = plans_keys[plan]
        result += f"**{plan_name}** ({len(keys)}):\n"
        for k in keys:
            result += f"`{k}`\n"
        result += "\n"
    await update.message.reply_text(result, parse_mode='Markdown')

async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub, plan, rem = is_user_subscribed(user_id)
    if sub or user_id == ADMIN_ID:
        name = {'day': 'يوم', 'two_days': 'يومين', 'week': 'أسبوع', 'month': 'شهر'}.get(plan, plan) if sub else "مشرف"
        await update.message.reply_text(f"✅ مشترك في {name}، متبقي {rem if sub else 'غير محدود'} يوم.")
    else:
        await update.message.reply_text("❌ لا يوجد اشتراك.")

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub, _, _ = is_user_subscribed(user_id)
    if not sub and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 تحتاج اشتراك.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, prediction, timestamp, suit FROM history WHERE prediction IS NOT NULL", conn)
        conn.close()
        if len(df) < 10:
            await update.message.reply_text("⚠️ بيانات غير كافية.")
            return
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)
        period_order = ["morning", "afternoon", "evening", "night"]
        period_acc = df.groupby('period')['correct'].mean().reindex(period_order) * 100
        hour_stats = df.groupby('hour').agg(accuracy=('correct','mean'), count=('correct','count'))
        hour_stats = hour_stats[hour_stats['count'] >= 10]
        hour_acc = hour_stats['accuracy'] * 100
        suit_stats = df.groupby('suit').agg(accuracy=('correct','mean'), count=('correct','count')) * 100
        report = "📊 **تقرير الأداء**\n━━━━━━━━━━\n"
        for p in period_order:
            if p in period_acc and not pd.isna(period_acc[p]):
                emoji = "🟢" if period_acc[p] >= 60 else "🟡" if period_acc[p] >= 50 else "🔴"
                report += f"{emoji} {period_translate(p)}: {period_acc[p]:.1f}%\n"
        report += f"\n📈 الإجمالي: {df['correct'].mean()*100:.1f}% ({len(df)} جولة)\n"
        if not hour_acc.empty:
            report += "\n🏆 أفضل 3 ساعات:\n"
            for h, acc in hour_acc.nlargest(3).items():
                report += f"🟢 {h:02d}:00 → {acc:.1f}%\n"
            report += "\n⚠️ أسوأ 3 ساعات:\n"
            for h, acc in hour_acc.nsmallest(3).items():
                report += f"🔴 {h:02d}:00 → {acc:.1f}%\n"
        if not suit_stats.empty:
            report += "\n🎴 الدقة حسب البذلة:\n"
            for suit, row in suit_stats.iterrows():
                emoji = "🟢" if row['accuracy'] >= 60 else "🟡" if row['accuracy'] >= 50 else "🔴"
                report += f"{emoji} {suit}: {row['accuracy']:.1f}% ({int(row['count'])} جولة)\n"
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def model_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub, _, _ = is_user_subscribed(user_id)
    if not sub and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 تحتاج اشتراك.")
        return
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
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        hour_stats = df.groupby('hour').agg(acc=('correct','mean'), cnt=('correct','count'))
        hour_stats = hour_stats[hour_stats['cnt'] >= 10]
        best_hour = hour_stats['acc'].idxmax() if not hour_stats.empty else None
        worst_hour = hour_stats['acc'].idxmin() if not hour_stats.empty else None
        status = "🔻 ضعيف"
        if acc_200 >= 65: status = "✅ ممتاز"
        elif acc_200 >= 58: status = "⚖️ مقبول"
        report = "🧠 **حالة المحرك**\n━━━━━━━━━━\n"
        if acc_50: report += f"📉 آخر 50 جولة: {acc_50:.1f}%\n"
        report += f"📊 آخر 200 جولة: {acc_200:.1f}%\n"
        if best_hour: report += f"\n🏆 أفضل ساعة: {best_hour:02d}:00\n"
        if worst_hour: report += f"⚠️ أسوأ ساعة: {worst_hour:02d}:00\n"
        report += f"\n**التقييم:** {status}"
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 9. أمر الحذف ====================
async def delete_last_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub, _, _ = is_user_subscribed(user_id)
    if not sub and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 تحتاج اشتراك.")
        return
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT id FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("⚠️ لا يوجد إدخال سابق لك.")
        return
    last_id = row[0]
    cur.execute("DELETE FROM history WHERE id = %s", (last_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("🗑️ تم حذف آخر إدخال لك.")

# ==================== 10. أمر التحميل للأدمن ====================
async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ==================== 11. المعالجات الأساسية ====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    sub, _, _ = is_user_subscribed(user_id)
    if not sub and user_id != ADMIN_ID:
        await subscribe(update, context)
        return

    allowed, msg = can_user_play(user_id, context)
    if not allowed:
        await update.message.reply_text(msg)
        return

    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start.")
            return

        current_time = datetime.datetime.now()
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()

        # آخر توقيت
        cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        last_time = row[0] if row else None

        # آخر فائز لهذا المستخدم (للذاكرة القصيرة)
        cur.execute("SELECT winner FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        last_winner_code = WINNER_MAP.get(row[0]) if row and row[0] in WINNER_MAP else None

        # تحميل الأوزان
        math_weights = load_weights(conn)

        # تحميل بايزي
        bayesian_probs = bayesian_analysis(conn, current_time.hour)

        # التنبؤ الهجين
        pred_text, pred_code, gap, _, _, _, reason = hybrid_prediction(
            text, context.user_data['suit'], last_time, current_time,
            bayesian_probs, math_weights, last_winner_code
        )

        cur.close()
        conn.close()

        # حقن خطأ إذا كان streak كبير
        if user_id != ADMIN_ID and context.user_data.get('correct_streak', 0) >= MAX_CORRECT_STREAK:
            pred_code = inject_fake_prediction(pred_code)
            pred_text = WINNER_NAMES[pred_code]
            context.user_data['correct_streak'] = 0
            fake_warning = "\n⚠️ تم تعديل التوقع مؤقتاً.\n"
        else:
            fake_warning = ""

        context.user_data['bonus'] = text
        context.user_data['prediction_code'] = pred_code
        context.user_data['current_time'] = current_time

        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
        ]

        suit_color = "🔴" if context.user_data['suit'] in ['♦️', '♥️'] else "⚫"
        await update.message.reply_text(
            f"{fake_warning}"
            f"🎯 **التوقع:** {pred_text}\n"
            f"📊 **المنهج:** {reason}\n"
            f"🎴 البذلة: {context.user_data['suit']} {suit_color}\n"
            f"⏱️ الفجوة: {gap} ثانية\n"
            f"━━━━━━━━━━━━━━\n"
            f"اختر النتيجة الحقيقية:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )

        update_session_after_play(context)
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

            # إدراج الجولة
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

            # تحديث الأوزان
            # نستخرج الميزات مرة أخرى (نحتاج last_winner للجولة الجديدة؟ لا، لأننا نستخدم ما قبلها)
            # آخر فائز لهذا المستخدم (قبل هذه الجولة)
            cur.execute("SELECT winner FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1 OFFSET 1", (update.effective_user.id,))
            row = cur.fetchone()
            last_winner_code = WINNER_MAP.get(row[0]) if row and row[0] in WINNER_MAP else None

            # حساب delta_t
            cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1 OFFSET 1")
            row = cur.fetchone()
            prev_time = row[0] if row else None
            if prev_time:
                delta_t = int((context.user_data['current_time'] - prev_time).total_seconds())
            else:
                delta_t = 0

            features = extract_math_features(
                context.user_data['bonus'],
                context.user_data['suit'],
                delta_t,
                last_winner_code
            )
            if features is not None:
                math_weights = load_weights(conn)
                predicted_class = pred_code
                actual_class = WINNER_MAP.get(winner_db, 2)  # 2 تعادل افتراضي
                math_weights = update_weights(math_weights, features, predicted_class, actual_class)
                save_weights(conn, math_weights)

            conn.close()

            pred_winner = WINNER_NAMES[pred_code]
            is_correct = "✅" if winner_db == pred_winner else "❌"

            # تحديث streak
            user_id = update.effective_user.id
            if user_id != ADMIN_ID:
                if is_correct == "✅":
                    context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
                else:
                    context.user_data['correct_streak'] = 0

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
                f"/mysub - اشتراكي",
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

# ==================== 12. التشغيل الرئيسي ====================
if __name__ == "__main__":
    init_subscription_table()
    init_weights_table()
    # التأكد من وجود عمود user_id
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("ALTER TABLE history ADD COLUMN IF NOT EXISTS user_id BIGINT")
        conn.commit()
        conn.close()
    except:
        pass
    # توليد مفاتيح أولية إذا لم توجد
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM subscription_keys")
    if cur.fetchone()[0] == 0:
        generate_keys()
    conn.close()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("status", model_status))
    app.add_handler(CommandHandler("generate_keys", generate_keys_command))
    app.add_handler(CommandHandler("mysub", my_subscription))
    app.add_handler(CommandHandler("delete", delete_last_entry))
    app.add_handler(CommandHandler("download", download_database))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🚀 HADES V101 يعمل... (نموذج خطي متكيف + بايزي)")
    app.run_polling()
