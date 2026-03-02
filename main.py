"""
HADES V101.5 - Anti-Bias Self-Optimizing AI Prediction Bot
جميع المفاتيح مضمنة، يعمل فوراً على Railway مع PostgreSQL.
تم تحديث النموذج إلى GLM-5 مع تفعيل التفكير الظاهر.
"""

import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
import secrets
import uuid
import random
import asyncio
import io
import json
import re
from typing import Dict, Any, Tuple, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, ConversationHandler
)
from openai import OpenAI

# ==================== الإعدادات والثوابت (مضمنة) ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@postgres.railway.internal:5432/railway"
ADMIN_ID = 6033203084

# تحديث إلى GLM-5 مع المفتاح الجديد
NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "z-ai/glm5"

# خطط الاشتراك (بالأيام)
PLANS = {
    'day': 1,
    'two_days': 2,
    'week': 7,
    'month': 30
}

# إعدادات التباعد الزمني (سيتم تحديثها عبر AI)
PLAY_SESSION_MINUTES = 30
COOL_DOWN_1_MIN = (5, 10)
COOL_DOWN_2_MIN = 15
MAX_CORRECT_STREAK = 10

# خريطة تحويل أسماء الفائزين
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

# الإعدادات الديناميكية (سيتم تحميلها من قاعدة البيانات)
DYNAMIC_CONFIG = {
    'CONFIDENCE_THRESHOLD': 0.65,
    'MATH_WEIGHT': 0.55,
    'BAYES_WEIGHT': 0.45,
    'MATH_CONFIDENCE': 0.7,
    'S_RED': 1,
    'S_BLACK': 1,
    'RANDOM_NOISE': 0.02,
}

# حالات المحادثة
(AI_MODE, PREDICTION_MODE) = range(2)

# ==================== دوال تحليل الوقت ====================
def get_time_period(hour: int) -> str:
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 24:
        return "evening"
    else:
        return "night"

def period_translate(period: str) -> str:
    return {
        "morning": "🌅 الصباح",
        "afternoon": "☀️ الظهر",
        "evening": "🌇 المساء",
        "night": "🌙 الليل"
    }.get(period, period)

# ==================== دوال إدارة قاعدة البيانات والإعدادات ====================
def init_database():
    """إنشاء الجداول المطلوبة إذا لم تكن موجودة."""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()

    # جدول الاشتراكات
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

    # جدول الإعدادات الديناميكية (ai_settings)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_settings (
            id SERIAL PRIMARY KEY,
            config_name VARCHAR(50) UNIQUE NOT NULL,
            config_value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # جدول history
    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY,
            b_num VARCHAR(20),
            suit VARCHAR(10),
            winner VARCHAR(20),
            timestamp TIMESTAMP,
            prediction INTEGER,
            user_id BIGINT
        )
    """)

    conn.commit()
    conn.close()

def load_dynamic_config():
    """تحميل الإعدادات الديناميكية من قاعدة البيانات وتحديث المتغيرات العامة."""
    global DYNAMIC_CONFIG, CONFIDENCE_THRESHOLD, MATH_WEIGHT, BAYES_WEIGHT, MATH_CONFIDENCE, S_RED, S_BLACK, RANDOM_NOISE
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT config_name, config_value FROM ai_settings")
    rows = cur.fetchall()
    conn.close()

    for name, value in rows:
        if name in DYNAMIC_CONFIG:
            try:
                DYNAMIC_CONFIG[name] = json.loads(value)
            except:
                DYNAMIC_CONFIG[name] = value

    CONFIDENCE_THRESHOLD = DYNAMIC_CONFIG.get('CONFIDENCE_THRESHOLD', 0.65)
    MATH_WEIGHT = DYNAMIC_CONFIG.get('MATH_WEIGHT', 0.55)
    BAYES_WEIGHT = DYNAMIC_CONFIG.get('BAYES_WEIGHT', 0.45)
    MATH_CONFIDENCE = DYNAMIC_CONFIG.get('MATH_CONFIDENCE', 0.7)
    S_RED = DYNAMIC_CONFIG.get('S_RED', 1)
    S_BLACK = DYNAMIC_CONFIG.get('S_BLACK', 1)
    RANDOM_NOISE = DYNAMIC_CONFIG.get('RANDOM_NOISE', 0.02)

def save_dynamic_config(config_updates: Dict[str, Any]):
    """حفظ تحديثات الإعدادات في قاعدة البيانات وتحديث الذاكرة."""
    global DYNAMIC_CONFIG
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    for name, value in config_updates.items():
        json_value = json.dumps(value)
        cur.execute("""
            INSERT INTO ai_settings (config_name, config_value)
            VALUES (%s, %s)
            ON CONFLICT (config_name) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP
        """, (name, json_value))
        DYNAMIC_CONFIG[name] = value
    conn.commit()
    conn.close()
    load_dynamic_config()

# ==================== دوال إدارة الاشتراكات ====================
def generate_keys():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    for plan in PLANS.keys():
        for _ in range(5):
            key = secrets.token_urlsafe(16)
            try:
                cur.execute(
                    "INSERT INTO subscription_keys (key_code, plan) VALUES (%s, %s)",
                    (key, plan)
                )
            except psycopg2.IntegrityError:
                conn.rollback()
                continue
    conn.commit()
    conn.close()

def is_user_subscribed(user_id: int) -> tuple:
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

# ==================== دوال إدارة التباعد الزمني ====================
def init_user_session(context: ContextTypes.DEFAULT_TYPE):
    if 'session_start' not in context.user_data:
        context.user_data['session_start'] = None
        context.user_data['session_play_minutes'] = 0
        context.user_data['cool_until'] = None
        context.user_data['cool_stage'] = 0
        context.user_data['correct_streak'] = 0
        context.user_data['last_predictions'] = []  # لمكافحة الانحياز

def can_user_play(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> tuple:
    if user_id == ADMIN_ID:
        return True, ""
    init_user_session(context)
    now = datetime.datetime.now()
    cool_until = context.user_data.get('cool_until')
    if cool_until and now < cool_until:
        remaining = (cool_until - now).seconds // 60
        remaining_seconds = (cool_until - now).seconds % 60
        msg = f"⏳ النظام في فترة تبريد. يرجى الانتظار {remaining} دقيقة و{remaining_seconds} ثانية."
        return False, msg
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
        msg = f"⏸️ انتهت جلسة اللعب. يرجى الانتظار {cool_minutes} دقيقة قبل المحاولة مرة أخرى."
        return False, msg
    return True, ""

def update_session_after_play(context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('session_start') is None:
        return
    now = datetime.datetime.now()
    session_duration = (now - context.user_data['session_start']).total_seconds() / 60
    context.user_data['session_play_minutes'] += session_duration
    context.user_data['session_start'] = now

def inject_fake_prediction(pred_code: int) -> int:
    return 1 if pred_code == 0 else 0

# ==================== المحرك الرياضي الأساسي (معدل بالكامل) ====================
def sovereign_math_engine(b_num: str, suit: str, last_timestamp, current_timestamp):
    last3 = b_num[-3:]
    B = sum(int(d) for d in last3 if d.isdigit())          # مجموع آخر 3 أرقام
    last_digit = int(b_num[-1])                            # آخر رقم من البونص
    S = S_RED if suit in ['♦️', '♥️'] else S_BLACK        # معامل البذلة
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    # معادلة جديدة: R = (B * S) + (delta_t % 7) + (last_digit * 3)
    R = (B * S) + (delta_t % 7) + (last_digit * 3)
    prediction_code = R % 2                                # 0 للراعي، 1 للثور
    prediction_text = WINNER_NAMES[prediction_code]
    return prediction_text, prediction_code, R, delta_t, B, S

# ==================== تحليل بايزي ====================
def bayesian_analysis(conn, current_hour: int, min_samples: int = 30):
    try:
        df = pd.read_sql("""
            SELECT winner, timestamp 
            FROM history 
            WHERE winner IS NOT NULL
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
        print(f"Bayesian Analysis Error: {e}")
        return None

# ==================== دالة التنبؤ الهجين (مع عشوائية لكسر الانحياز) ====================
def hybrid_prediction(b_num: str, suit: str, last_timestamp, current_timestamp, bayesian_probs):
    math_pred_text, math_pred_code, R, gap, B, S = sovereign_math_engine(
        b_num, suit, last_timestamp, current_timestamp
    )

    if bayesian_probs is None:
        return math_pred_text, math_pred_code, R, gap, B, S, "Math Only"

    current_period = get_time_period(current_timestamp.hour)
    period_probs = bayesian_probs.get(current_period)

    if period_probs is None:
        return math_pred_text, math_pred_code, R, gap, B, S, "Math Only"

    p_rai, p_thawr, p_tie = period_probs

    # Bayesian prediction
    bayes_code = np.argmax([p_rai, p_thawr, p_tie])

    # دمج الاحتمالات مع عشوائية طفيفة لكسر الانحياز
    weighted_rai = MATH_WEIGHT * (1 if math_pred_code == 0 else 0) + BAYES_WEIGHT * p_rai + random.uniform(0, RANDOM_NOISE)
    weighted_thawr = MATH_WEIGHT * (1 if math_pred_code == 1 else 0) + BAYES_WEIGHT * p_thawr + random.uniform(0, RANDOM_NOISE)
    weighted_tie = MATH_WEIGHT * (1 if math_pred_code == 2 else 0) + BAYES_WEIGHT * p_tie + random.uniform(0, RANDOM_NOISE)

    scores = [weighted_rai, weighted_thawr, weighted_tie]
    final_code = int(np.argmax(scores))

    # إذا كان الفرق بين أعلى نتيجتين صغيراً جداً، نأخذ بقرار Bayesian
    sorted_scores = sorted(scores, reverse=True)
    if sorted_scores[0] - sorted_scores[1] < 0.02:
        final_code = bayes_code

    final_text = WINNER_NAMES[final_code]
    reason = f"Hybrid Mix | Math:{math_pred_text} | Bayes R:{p_rai:.2f} T:{p_thawr:.2f}"

    return final_text, final_code, R, gap, B, S, reason

# ==================== AI ENGINEER AGENT (يعمل كل 30 دقيقة) ====================
class HADESAIEngineer:
    def __init__(self):
        self.client = OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=NVIDIA_API_KEY
        )
        self.model = NVIDIA_MODEL

    def load_rounds(self):
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("""
        SELECT *
        FROM history
        ORDER BY id
        """, conn)
        conn.close()
        if len(df) < 800:
            return None
        # تجاهل أول 700 جولة (إذا كانت كلها تعادل أو غير موثوقة)
        df = df.iloc[700:]
        return df

    def compute_metrics(self, df):
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        if len(df) < 50:
            return None
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)
        metrics = {}
        metrics["total_accuracy"] = float(df['correct'].mean())
        metrics["last50"] = float(df.tail(50)['correct'].mean())
        metrics["last100"] = float(df.tail(100)['correct'].mean())
        metrics["last300"] = float(df.tail(300)['correct'].mean())
        metrics["rounds"] = len(df)
        return metrics

    def ai_optimize(self, metrics):
        prompt = f"""
أنت مهندس ذكاء اصطناعي مسؤول عن تحسين نظام تنبؤ.

بيانات النظام (بعد تجاهل أول 700 جولة غير موثوقة):
عدد الجولات: {metrics['rounds']}
الدقة العامة: {metrics['total_accuracy']}
آخر 50 جولة: {metrics['last50']}
آخر 100 جولة: {metrics['last100']}
آخر 300 جولة: {metrics['last300']}

الإعدادات الحالية:
CONFIDENCE_THRESHOLD={CONFIDENCE_THRESHOLD}
MATH_WEIGHT={MATH_WEIGHT}
BAYES_WEIGHT={BAYES_WEIGHT}
S_RED={S_RED}
S_BLACK={S_BLACK}
MATH_CONFIDENCE={MATH_CONFIDENCE}
RANDOM_NOISE={RANDOM_NOISE}

المعادلة الجديدة:
R = (B * S) + (delta_t % 7) + (last_digit * 3)
prediction_code = R % 2

المطلوب: تحسين القيم التالية لرفع الدقة:
CONFIDENCE_THRESHOLD, MATH_WEIGHT, BAYES_WEIGHT, S_RED, S_BLACK, MATH_CONFIDENCE, RANDOM_NOISE

أعد فقط JSON.
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=1,
                top_p=1,
                max_tokens=16384,
                extra_body={"chat_template_kwargs": {"enable_thinking": True, "clear_thinking": False}},
                stream=False
            )
            content = response.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                # منع القيم المتطرفة
                if "MATH_WEIGHT" in data and "BAYES_WEIGHT" in data:
                    if data["MATH_WEIGHT"] < 0.3:
                        data["MATH_WEIGHT"] = 0.4
                    if data["BAYES_WEIGHT"] > 0.7:
                        data["BAYES_WEIGHT"] = 0.6
                if "RANDOM_NOISE" in data:
                    data["RANDOM_NOISE"] = min(0.05, max(0.005, data["RANDOM_NOISE"]))
                return data
        except Exception as e:
            print("AI OPT ERROR:", e)
        return None

    def run_cycle(self):
        try:
            df = self.load_rounds()
            if df is None:
                print("AI waiting for more rounds...")
                return
            metrics = self.compute_metrics(df)
            if metrics is None:
                return
            print("AI METRICS:", metrics)
            if metrics["last100"] < 0.55 or metrics["last50"] < 0.50:
                print("AI detected performance drop")
                suggestions = self.ai_optimize(metrics)
                if suggestions:
                    save_dynamic_config(suggestions)
                    print("AI updated configuration:", suggestions)
        except Exception as e:
            print("AI ENGINE ERROR:", e)

ai_engineer = HADESAIEngineer()

# ==================== خدمة الذكاء الاصطناعي للمحادثة (GLM-5) ====================
class NVIDIAService:
    def __init__(self):
        self.client = OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=NVIDIA_API_KEY
        )
        self.model = NVIDIA_MODEL

    def ask(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=1,
                top_p=1,
                max_tokens=16384,
                extra_body={"chat_template_kwargs": {"enable_thinking": True, "clear_thinking": False}},
                stream=False
            )
            # نستطيع هنا معالجة التفكير إذا أردنا فصله، لكن سنعيد المحتوى الكامل
            return response.choices[0].message.content
        except Exception as e:
            return f"⚠️ خطأ في الاتصال بالذكاء الاصطناعي: {str(e)}"

nvidia_ai = NVIDIAService()

# ==================== أوامر البوت ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribed, plan, remaining = is_user_subscribed(user_id)
    if not subscribed and user_id != ADMIN_ID:
        await update.message.reply_text(
            "🔐 **مرحبًا بك في HADES V101.5**\n"
            "للاستخدام، يجب عليك إدخال مفتاح اشتراك صالح.\n"
            "أرسل المفتاح الآن، أو تواصل مع المسؤول للحصول على مفتاح.\n\n"
            "إذا كان لديك مفتاح، أرسله كرسالة مباشرة."
        )
        return
    context.user_data.clear()
    init_user_session(context)
    kb = [
        [InlineKeyboardButton("♦️ ديناري (أحمر)", callback_data="s_♦️"),
         InlineKeyboardButton("♥️ قلب (أحمر)", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد (أسود)", callback_data="s_♠️"),
         InlineKeyboardButton("♣️ كلبة (أسود)", callback_data="s_♣️")],
        [InlineKeyboardButton("🤖 دردشة مع AI", callback_data="ai_chat")]
    ]
    remaining_text = f"اشتراكك ({plan}) متبقي {remaining} يوم." if subscribed else ""
    await update.message.reply_text(
        f"🏛️ **الكيان السيادي HADES V101.5**\n"
        f"محرك تنبؤي هجين (معادلة + بايزي) مع تحليل زمني ومكافحة انحياز.\n"
        f"{remaining_text}\n\n"
        "🎴 اختر نوع البذلة للتنبؤ، أو اختر دردشة AI:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def suit_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج اختيار البذلة من الأزرار."""
    query = update.callback_query
    await query.answer()
    suit = query.data[2:]  # إزالة "s_"
    context.user_data['suit'] = suit
    # حفظ آخر توقيت للجولة القادمة
    context.user_data['last_timestamp'] = None
    await query.message.reply_text(
        f"✅ تم اختيار البذلة: {suit}\n"
        "📥 أرسل الآن رقم البونص (7 أرقام على الأقل):"
    )

async def handle_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إدخال رقم البونص بعد اختيار البذلة."""
    if 'suit' not in context.user_data:
        await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start.")
        return

    text = update.message.text.strip()
    if not text.isdigit() or len(text) < 7:
        await update.message.reply_text("❌ أدخل رقم صحيح (7 أرقام على الأقل).")
        return

    b_num = text
    suit = context.user_data['suit']
    now = datetime.datetime.now()
    last_timestamp = context.user_data.get('last_timestamp')

    # جلب بيانات بايزي من قاعدة البيانات
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    bayesian_probs = bayesian_analysis(conn, now.hour)
    conn.close()

    # التنبؤ الهجين
    pred_text, pred_code, R, gap, B, S, reason = hybrid_prediction(
        b_num, suit, last_timestamp, now, bayesian_probs
    )

    # تحديث البيانات في الذاكرة المؤقتة
    context.user_data['bonus'] = b_num
    context.user_data['prediction_code'] = pred_code
    context.user_data['current_time'] = now
    context.user_data['last_timestamp'] = now  # تحديث التوقيت للجولة القادمة

    # أزرار لتسجيل النتيجة
    kb = [
        [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_الراعي 🔴"),
         InlineKeyboardButton("🔵 فاز الثور", callback_data="save_الثور 🔵")],
        [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
    ]

    await update.message.reply_text(
        f"🧠 **تحليل HADES V101.5**\n"
        f"⚙️ `الاستدلال:` {reason}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🎯 **التوقع النهائي:** {pred_text}\n"
        f"🎴 **البذلة:** {suit}\n"
        f"🔢 **الفجوة الزمنية:** {gap} ثانية | R={R}\n\n"
        f"يرجى تسجيل النتيجة الحقيقية لحماية وتحديث الأوزان:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def ai_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الدخول في وضع الدردشة مع الذكاء الاصطناعي."""
    context.user_data['mode'] = AI_MODE
    await update.message.reply_text(
        "🤖 **وضع الذكاء الاصطناعي نشط.**\n"
        "تفضل بطرح أي سؤال أو تحليل تريده. (للخروج أرسل /start)"
    )

async def end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الخروج من وضع الدردشة مع الذكاء الاصطناعي."""
    if 'mode' in context.user_data:
        del context.user_data['mode']
    await update.message.reply_text("✅ تم الخروج من وضع الدردشة. استخدم /start للعودة.")

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إدخال مفتاح الاشتراك."""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if activate_subscription(user_id, text):
        await update.message.reply_text("✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن استخدام /start للبدء.")
    else:
        await update.message.reply_text("❌ المفتاح غير صالح أو مستخدم مسبقًا. تأكد من المفتاح وحاول مرة أخرى.")

async def generate_keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر للمسؤول لتوليد مفاتيح جديدة وعرضها."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر متاح للمسؤول فقط.")
        return
    generate_keys()
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT key_code, plan FROM subscription_keys WHERE is_used = FALSE ORDER BY plan, id")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("⚠️ لا توجد مفاتيح غير مستخدمة حالياً.")
        return
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
    """عرض حالة الاشتراك الحالية للمستخدم."""
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
    """تحليل شامل للأداء (يتطلب اشتراكًا)."""
    user_id = update.effective_user.id
    subscribed, _, _ = is_user_subscribed(user_id)
    if not subscribed and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 يجب أن يكون لديك اشتراك صالح لاستخدام هذا الأمر.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("""
            SELECT winner, prediction, timestamp, suit 
            FROM history 
            WHERE prediction IS NOT NULL
        """, conn)
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
        if len(df) < 10:
            await update.message.reply_text("⚠️ بيانات غير صالحة بعد التنظيف.")
            return
        period_order = ["morning", "afternoon", "evening", "night"]
        period_accuracy = df.groupby('period')['correct'].mean().reindex(period_order) * 100
        hour_stats = df.groupby('hour').agg(
            accuracy=('correct', 'mean'),
            count=('correct', 'count')
        )
        hour_stats = hour_stats[hour_stats['count'] >= 10]
        hour_accuracy = hour_stats['accuracy'] * 100
        suit_stats = df.groupby('suit').agg(
            accuracy=('correct', 'mean'),
            count=('correct', 'count')
        ) * 100
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
    """حالة صحة النموذج (يتطلب اشتراكًا)."""
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
        acc_50 = df.head(50)['correct'].mean() * 100 if len(df) >= 50 else None
        acc_200 = df['correct'].mean() * 100
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        hour_stats = df.groupby('hour').agg(
            acc=('correct', 'mean'),
            cnt=('correct', 'count')
        )
        hour_stats = hour_stats[hour_stats['cnt'] >= 10]
        best_hour = hour_stats['acc'].idxmax() if not hour_stats.empty else None
        worst_hour = hour_stats['acc'].idxmin() if not hour_stats.empty else None
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

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف آخر إدخال للمستخدم (إذا كان خاطئاً)."""
    user_id = update.effective_user.id
    subscribed, _, _ = is_user_subscribed(user_id)
    if not subscribed and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 يجب أن يكون لديك اشتراك صالح لاستخدام هذا الأمر.")
        return
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    if user_id == ADMIN_ID:
        cur.execute("SELECT id FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM history WHERE id = %s", (row[0],))
            conn.commit()
            await update.message.reply_text("🗑️ تم حذف آخر إدخال في السجل.")
        else:
            await update.message.reply_text("⚠️ لا توجد إدخالات للحذف.")
    else:
        cur.execute("""
            SELECT id FROM history 
            WHERE user_id = %s 
            ORDER BY id DESC LIMIT 1
        """, (user_id,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM history WHERE id = %s", (row[0],))
            conn.commit()
            await update.message.reply_text("🗑️ تم حذف آخر إدخال لك.")
        else:
            await update.message.reply_text("⚠️ لا توجد إدخالات سابقة لك.")
    conn.close()

async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحميل جميع جداول قاعدة البيانات كملف Excel (للأدمن فقط)."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر متاح للمسؤول فقط.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        history_df = pd.read_sql("SELECT * FROM history ORDER BY id", conn)
        keys_df = pd.read_sql("SELECT * FROM subscription_keys ORDER BY id", conn)
        settings_df = pd.read_sql("SELECT * FROM ai_settings ORDER BY id", conn)
        conn.close()
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            history_df.to_excel(writer, sheet_name='history', index=False)
            keys_df.to_excel(writer, sheet_name='subscription_keys', index=False)
            settings_df.to_excel(writer, sheet_name='ai_settings', index=False)
        output.seek(0)
        await update.message.reply_document(
            document=output,
            filename=f"database_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            caption="📥 نسخة احتياطية من قاعدة البيانات"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في تحميل قاعدة البيانات: {e}")

# ==================== معالج الأزرار (Callback) ====================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data.startswith("s_"):
        await suit_selected(update, context)
    elif query.data == "ai_chat":
        context.user_data['mode'] = AI_MODE
        await query.edit_message_text(
            "🤖 **وضع الذكاء الاصطناعي نشط.**\n"
            "تفضل بطرح أي سؤال أو تحليل تريده. (للخروج أرسل /start)"
        )
    elif query.data.startswith("save_"):
        winner_db = query.data[5:]  # استخراج الاسم الكامل مع الإيموجي
        pred_code = context.user_data.get('prediction_code')
        if pred_code is None:
            await query.edit_message_text("❌ خطأ: لا يوجد توقع مخزن. ابدأ من جديد /start.")
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
                user_id
            ))
            conn.commit()
            conn.close()

            pred_winner = WINNER_NAMES[pred_code]
            is_correct = "✅" if winner_db == pred_winner else "❌"

            # إنشاء زر لبدء جولة جديدة
            keyboard = [[InlineKeyboardButton("🔄 بدء جولة جديدة", callback_data="new_round")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"{is_correct} **تم تسجيل النتيجة**\n\n"
                f"🎯 توقعنا: {pred_winner}\n"
                f"🏆 النتيجة: {winner_db}\n"
                f"━━━━━━━━━━━━━━\n"
                f"أرسل البونص القادم مباشرة للاستمرار بنفس البذلة.",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {e}")
    elif query.data == "new_round":
        await start(update, context)

# ==================== معالج الرسائل النصية العام ====================
async def general_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    # 1. فحص الاشتراك
    subscribed, _, _ = is_user_subscribed(user_id)
    if not subscribed and user_id != ADMIN_ID:
        if activate_subscription(user_id, text):
            await update.message.reply_text("✅ تم تفعيل اشتراكك بنجاح! استخدم /start للبدء.")
        else:
            await update.message.reply_text("❌ المفتاح غير صالح. يرجى إرسال مفتاح صحيح.")
        return

    # 2. فحص وضع الدردشة مع AI
    if context.user_data.get('mode') == AI_MODE:
        wait_msg = await update.message.reply_text("⏳ جاري تحليل سؤالك عبر مصفوفة NVIDIA...")
        ai_response = nvidia_ai.ask(text)
        await wait_msg.edit_text(f"🤖 **HADES AI:**\n\n{ai_response}")
        return

    # 3. إذا لم يكن اشتراكاً ولا دردشة، فهو رقم بونص
    await handle_bonus(update, context)

# ==================== التشغيل الرئيسي ====================
def main():
    print("⏳ جاري تهيئة قواعد البيانات والإعدادات الديناميكية...")
    init_database()
    load_dynamic_config()

    # فحص مفاتيح الاشتراك وتوليدها إذا كانت فارغة
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM subscription_keys")
        if cur.fetchone()[0] == 0:
            generate_keys()
            print("🔑 تم توليد مفاتيح الاشتراك الأولية.")
        conn.close()
    except Exception as e:
        print(f"⚠️ خطأ أثناء فحص المفاتيح: {e}")

    # بناء وتشغيل البوت
    app = ApplicationBuilder().token(TOKEN).build()

    # جدولة AI Engineer كل 30 دقيقة
    app.job_queue.run_repeating(
        lambda ctx: ai_engineer.run_cycle(),
        interval=1800,
        first=10
    )

    # تسجيل الأوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("status", model_status))
    app.add_handler(CommandHandler("generate_keys", generate_keys_command))
    app.add_handler(CommandHandler("mysub", my_subscription))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("download", download_database))
    app.add_handler(CommandHandler("ai", ai_chat_command))
    app.add_handler(CommandHandler("end", end_chat))

    # معالج الأزرار
    app.add_handler(CallbackQueryHandler(callback_handler))

    # معالج النصوص (للبونص والمفاتيح والدردشة)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, general_message_handler))

    print("🚀 محرك HADES V101.5 يعمل الآن بكامل طاقته (مع GLM-5)...")
    app.run_polling()

if __name__ == "__main__":
    main()
