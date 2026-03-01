import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
import secrets
import uuid
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084  # معرف المسؤول (مستثنى من القيود)

# خطط الاشتراك (بالأيام)
PLANS = {
    'day': 1,
    'two_days': 2,
    'week': 7,
    'month': 30
}

# إعدادات التباعد الزمني
PLAY_SESSION_MINUTES = 30  # مدة جلسة اللعب المستمر بالدقائق
COOL_DOWN_1_MIN = (5, 10)  # فترة التبريد الأولى بين 5-10 دقائق
COOL_DOWN_2_MIN = 15        # فترة التبريد الثانية 15 دقيقة
MAX_CORRECT_STREAK = 10     # عدد الجولات الصحيحة المتتالية قبل إدخال جولة خاطئة

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

# ==================== 3. دوال إدارة الاشتراكات ====================
def init_subscription_table():
    """إنشاء جدول الاشتراكات إذا لم يكن موجودًا"""
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
    """
    توليد 5 مفاتيح جديدة لكل خطة في كل مرة يتم استدعاء هذه الدالة.
    (بدون التحقق من وجود مفاتيح سابقة)
    """
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    for plan in PLANS.keys():
        for _ in range(5):
            key = secrets.token_urlsafe(16)  # مفتاح عشوائي آمن
            try:
                cur.execute(
                    "INSERT INTO subscription_keys (key_code, plan) VALUES (%s, %s)",
                    (key, plan)
                )
            except psycopg2.IntegrityError:
                # في حالة وجود مفتاح مكرر (نادر جداً)، نتجاهل ونستمر
                conn.rollback()
                continue
    conn.commit()
    conn.close()

def is_user_subscribed(user_id: int) -> tuple:
    """
    التحقق مما إذا كان المستخدم لديه اشتراك صالح
    تُرجع (True/False, الخطة, الأيام المتبقية)
    """
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
        plan = row[0]
        expires = row[1]
        remaining = (expires - datetime.datetime.now()).days
        return True, plan, remaining
    return False, None, 0

def activate_subscription(user_id: int, key_code: str) -> bool:
    """تفعيل الاشتراك بمفتاح معين لمستخدم"""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    
    # البحث عن المفتاح
    cur.execute("SELECT id, plan, is_used FROM subscription_keys WHERE key_code = %s", (key_code,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False  # مفتاح غير موجود
    
    key_id, plan, is_used = row
    if is_used:
        conn.close()
        return False  # مفتاح مستخدم مسبقًا
    
    # حساب تاريخ الانتهاء
    days = PLANS.get(plan)
    if not days:
        conn.close()
        return False
    
    expires_at = datetime.datetime.now() + datetime.timedelta(days=days)
    
    # تحديث المفتاح
    cur.execute("""
        UPDATE subscription_keys 
        SET is_used = TRUE, used_by = %s, used_at = NOW(), expires_at = %s
        WHERE id = %s
    """, (user_id, expires_at, key_id))
    
    conn.commit()
    conn.close()
    return True

# ==================== 4. دوال إدارة التباعد الزمني ====================
def init_user_session(context: ContextTypes.DEFAULT_TYPE):
    """تهيئة بيانات جلسة المستخدم"""
    if 'session_start' not in context.user_data:
        context.user_data['session_start'] = None
        context.user_data['session_play_minutes'] = 0
        context.user_data['cool_until'] = None
        context.user_data['cool_stage'] = 0  # 0 = لا تبريد, 1 = بعد أول 30 دقيقة, 2 = بعد ثاني 30 دقيقة
        context.user_data['correct_streak'] = 0

def can_user_play(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> tuple:
    """
    التحقق مما إذا كان المستخدم مسموحاً له باللعب الآن.
    تُرجع (مسموح, رسالة_الرفض)
    """
    # الأدمن دائماً مسموح
    if user_id == ADMIN_ID:
        return True, ""

    init_user_session(context)
    now = datetime.datetime.now()

    # إذا كان في فترة تبريد
    cool_until = context.user_data.get('cool_until')
    if cool_until and now < cool_until:
        remaining = (cool_until - now).seconds // 60
        remaining_seconds = (cool_until - now).seconds % 60
        msg = f"⏳ النظام في فترة تبريد. يرجى الانتظار {remaining} دقيقة و{remaining_seconds} ثانية."
        return False, msg

    # إذا لم تبدأ الجلسة بعد، نبدأها الآن
    if context.user_data['session_start'] is None:
        context.user_data['session_start'] = now
        context.user_data['session_play_minutes'] = 0
        return True, ""

    # حساب مدة الجلسة الحالية
    session_duration = (now - context.user_data['session_start']).total_seconds() / 60
    played = context.user_data['session_play_minutes'] + session_duration

    # إذا تجاوزنا الحد المسموح
    if played >= PLAY_SESSION_MINUTES:
        # نبدأ فترة تبريد
        if context.user_data['cool_stage'] == 0:
            # أول تبريد: عشوائي بين 5-10 دقائق
            cool_minutes = random.randint(COOL_DOWN_1_MIN[0], COOL_DOWN_1_MIN[1])
            context.user_data['cool_stage'] = 1
        else:
            # التبريد الثاني أو أكثر: 15 دقيقة
            cool_minutes = COOL_DOWN_2_MIN
            # إعادة تعيين المرحلة بعد التبريد الثاني للدورة (اختياري)
            # يمكن أن تبقى 2 أو تعود لـ0. سنبقيها 2 للتبريدات اللاحقة.
        
        context.user_data['cool_until'] = now + datetime.timedelta(minutes=cool_minutes)
        context.user_data['session_start'] = None  # إنهاء الجلسة الحالية
        context.user_data['session_play_minutes'] = 0

        msg = f"⏸️ انتهت جلسة اللعب. يرجى الانتظار {cool_minutes} دقيقة قبل المحاولة مرة أخرى."
        return False, msg

    # مسموح باللعب
    return True, ""

def update_session_after_play(context: ContextTypes.DEFAULT_TYPE):
    """تحديث وقت الجلسة بعد كل لعبة (تخزين الوقت المنقضي)"""
    if context.user_data.get('session_start') is None:
        return
    now = datetime.datetime.now()
    session_duration = (now - context.user_data['session_start']).total_seconds() / 60
    context.user_data['session_play_minutes'] += session_duration
    context.user_data['session_start'] = now  # إعادة ضبط بداية الجلسة بعد احتساب المدة

def inject_fake_prediction(pred_code: int) -> int:
    """
    إدخال جولة خاطئة: قلب التوقع (إذا كان 0 يصبح 1، إذا كان 1 يصبح 0)
    لا نستخدم التعادل (2) لأنه نادر.
    """
    return 1 if pred_code == 0 else 0

# ==================== 5. المحرك الرياضي الأساسي ====================
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

# ==================== 6. Bayesian Adaptive Layer (مُحسّن) ====================
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

# ==================== 7. أوامر البوت ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء التفاعل مع التحقق من الاشتراك"""
    user_id = update.effective_user.id
    
    # التحقق من الاشتراك
    subscribed, plan, remaining = is_user_subscribed(user_id)
    
    if not subscribed and user_id != ADMIN_ID:  # حتى الأدمن يحتاج اشتراك؟ لا، الأدمن مستثنى، لكن نسمح له بالدخول بدون اشتراك؟
        # إذا لم يكن مشتركًا وليس أدمن، نطلب إدخال مفتاح
        await update.message.reply_text(
            "🔐 **مرحبًا بك في HADES V100.2**\n"
            "للاستخدام، يجب عليك إدخال مفتاح اشتراك صالح.\n"
            "أرسل المفتاح الآن، أو تواصل مع المسؤول للحصول على مفتاح.\n\n"
            "إذا كان لديك مفتاح، أرسله كرسالة مباشرة."
        )
        return
    
    # إذا كان مشتركًا أو أدمن، نكمل
    context.user_data.clear()
    init_user_session(context)  # تهيئة بيانات الجلسة
    kb = [
        [InlineKeyboardButton("♦️ ديناري (أحمر)", callback_data="s_♦️"), 
         InlineKeyboardButton("♥️ قلب (أحمر)", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد (أسود)", callback_data="s_♠️"), 
         InlineKeyboardButton("♣️ كلبة (أسود)", callback_data="s_♣️")]
    ]
    remaining_text = f"اشتراكك ({plan}) متبقي {remaining} يوم." if subscribed else ""
    await update.message.reply_text(
        f"🏛️ **الكيان السيادي HADES V100.2**\n"
        f"محرك تنبؤي بايزي متطور مع تحليل زمني.\n"
        f"{remaining_text}\n\n"
        "🎴 اختر نوع البذلة:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إدخال مفتاح الاشتراك"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # محاولة تفعيل الاشتراك
    if activate_subscription(user_id, text):
        await update.message.reply_text("✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن استخدام /start للبدء.")
    else:
        await update.message.reply_text("❌ المفتاح غير صالح أو مستخدم مسبقًا. تأكد من المفتاح وحاول مرة أخرى.")

async def generate_keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر للمسؤول لتوليد مفاتيح جديدة وعرضها"""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر متاح للمسؤول فقط.")
        return

    # توليد 5 مفاتيح جديدة لكل خطة
    generate_keys()

    # جلب المفاتيح غير المستخدمة من قاعدة البيانات
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT key_code, plan FROM subscription_keys WHERE is_used = FALSE ORDER BY plan, id")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("⚠️ لا توجد مفاتيح غير مستخدمة حالياً (حدث خطأ غير متوقع).")
        return

    # تجميع المفاتيح حسب الخطة
    result = "🔑 **المفاتيح المتاحة:**\n\n"
    plans_keys = {plan: [] for plan in PLANS.keys()}
    for key, plan in rows:
        plans_keys[plan].append(key)

    for plan in PLANS.keys():
        plan_name = {
            'day': '📆 يوم',
            'two_days': '📆📆 يومين',
            'week': '📅 أسبوع',
            'month': '📅 شهر'
        }.get(plan, plan)
        keys = plans_keys[plan]
        result += f"**{plan_name}** ({len(keys)} مفتاح):\n"
        if keys:
            for k in keys:
                result += f"`{k}`\n"
        else:
            result += "لا توجد مفاتيح.\n"
        result += "\n"

    await update.message.reply_text(result, parse_mode='Markdown')

async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض حالة الاشتراك الحالية للمستخدم"""
    user_id = update.effective_user.id
    subscribed, plan, remaining = is_user_subscribed(user_id)
    
    if subscribed or user_id == ADMIN_ID:
        plan_name = {
            'day': 'يوم',
            'two_days': 'يومين',
            'week': 'أسبوع',
            'month': 'شهر'
        }.get(plan, plan) if subscribed else "مشرف"
        await update.message.reply_text(
            f"✅ أنت مشترك حاليًا في خطة **{plan_name}**.\n"
            f"⏳ متبقي: {remaining if subscribed else 'غير محدود'} يوم."
        )
    else:
        await update.message.reply_text("❌ لا يوجد اشتراك نشط. استخدم /start وأدخل مفتاحًا صالحًا.")

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحليل شامل للأداء (يتطلب اشتراكًا)"""
    user_id = update.effective_user.id
    subscribed, _, _ = is_user_subscribed(user_id)
    if not subscribed and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 يجب أن يكون لديك اشتراك صالح لاستخدام هذا الأمر.")
        return
    
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
    """حالة صحة النموذج (يتطلب اشتراكًا)"""
    user_id = update.effective_user.id
    subscribed, _, _ = is_user_subscribed(user_id)
    if not subscribed and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 يجب أن يكون لديك اشتراك صالح لاستخدام هذا الأمر.")
        return
    
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

# ==================== 8. المعالجات الأساسية ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إدخال رقم البونص مع Bayesian Adjustment وقيود التباعد"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # التحقق من الاشتراك أولاً
    subscribed, _, _ = is_user_subscribed(user_id)
    if not subscribed and user_id != ADMIN_ID:
        # إذا لم يكن مشتركًا وليس أدمن، نتعامل مع الرسالة كمحاولة اشتراك
        await subscribe(update, context)
        return
    
    # التحقق من التباعد الزمني (للمستخدمين العاديين فقط)
    allowed, msg = can_user_play(user_id, context)
    if not allowed:
        await update.message.reply_text(msg)
        return
    
    # إذا كان مشتركًا أو أدمن، نكمل معالجة البونص
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
        
        cur.close()
        conn.close()

        # إذا وصل streak إلى 10، نقوم بإدخال جولة خاطئة (للمستخدمين العاديين فقط)
        if user_id != ADMIN_ID and context.user_data.get('correct_streak', 0) >= MAX_CORRECT_STREAK:
            # قلب التوقع
            adjusted_code = inject_fake_prediction(adjusted_code if adjusted_code is not None else pred_code)
            pred_text = WINNER_NAMES[adjusted_code]
            # إعادة تعيين streak
            context.user_data['correct_streak'] = 0
            fake_warning = "\n⚠️ **تنبيه:** بناءً على تحليل الأرباح، تم تعديل التوقع بشكل مؤقت.\n\n"
        else:
            fake_warning = ""

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
            f"{fake_warning}{warning_text}"
            f"🎯 **التوقع النهائي:** {pred_text}\n"
            f"🎴 البذلة: {context.user_data['suit']} {suit_color}\n"
            f"🔢 المعادلة: B={B} × S={S} + ΔT={gap} → R={R}\n"
            f"━━━━━━━━━━━━━━\n"
            f"اختر النتيجة الحقيقية:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )

        # تحديث وقت الجلسة بعد اللعب
        update_session_after_play(context)

    else:
        await update.message.reply_text("❌ أدخل رقم صحيح (7 أرقام على الأقل).")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار مع التحقق من البيانات وتحديث streak"""
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
            
            # تحديث streak للمستخدمين العاديين
            user_id = update.effective_user.id
            if user_id != ADMIN_ID:
                if is_correct == "✅":
                    context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
                else:
                    context.user_data['correct_streak'] = 0
            
            await query.edit_message_text(
                f"{is_correct} **تم التسجيل**\n\n"
                f"🎯 توقعنا: {pred_winner}\n"
                f"🏆 النتيجة: {winner_db}\n"
                f"━━━━━━━━━━━━━━\n"
                f"/performance - التحليل\n"
                f"/status - حالة النموذج\n"
                f"/mysub - اشتراكي",
                parse_mode='Markdown'
            )
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {e}")

# ==================== 9. التشغيل الرئيسي ====================
if __name__ == "__main__":
    # تهيئة جدول الاشتراكات
    init_subscription_table()
    
    # التحقق من وجود أي مفاتيح، إذا لم يكن هناك أي مفاتيح، قم بتوليد مفاتيح أولية
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM subscription_keys")
    count = cur.fetchone()[0]
    conn.close()
    if count == 0:
        generate_keys()  # توليد المفاتيح الأولية
    
    app = ApplicationBuilder().token(TOKEN).build()

    # الأوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("status", model_status))
    app.add_handler(CommandHandler("generate_keys", generate_keys_command))
    app.add_handler(CommandHandler("mysub", my_subscription))

    # معالج النصوص (للبونص والمفاتيح)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # معالج الأزرار
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🚀 HADES V100.2 يعمل... (مع نظام اشتراك وتباعد زمني)")
    print("🏛️ محرك بايزي تكيفي")
    app.run_polling()
