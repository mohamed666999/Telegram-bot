"""
HADES V101.6 - Self-Monitoring AI Prediction Bot
نظام تنبؤ هجين مع مراقب ذكاء اصطناعي مستقل
يعمل على Railway مع PostgreSQL
"""

import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
import secrets
import json
import re
import time
import logging
import random
import asyncio
from typing import Dict, Any, Tuple, Optional, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, JobQueue
)
from openai import OpenAI

# ==================== إعدادات التسجيل ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ==================== الثوابت والإعدادات ====================
TOKEN = os.getenv("TELEGRAM_TOKEN", "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway")
ADMIN_ID = 6033203084

# تم التحديث إلى minimax-m2.5 مع المفتاح الجديد
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "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")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

PLANS = {'day': 1, 'two_days': 2, 'week': 7, 'month': 30}

WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

DYNAMIC_CONFIG = {
    'CONFIDENCE_THRESHOLD': 0.65,
    'MATH_WEIGHT': 0.55,
    'BAYES_WEIGHT': 0.45,
    'MATH_CONFIDENCE': 0.7,
    'S_RED': 1.0,
    'S_BLACK': 1.0,
    'RANDOM_NOISE': 0.02,
}

PLAY_SESSION_MINUTES = 30
COOL_DOWN_1_MIN = (5, 10)
COOL_DOWN_2_MIN = 15

# ==================== دوال الوقت ====================
def get_time_period(hour: int) -> str:
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

# ==================== إدارة قاعدة البيانات ====================
def get_db_connection():
    """إنشاء اتصال آمن بقاعدة البيانات"""
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_database():
    """إنشاء جميع الجداول المطلوبة"""
    conn = get_db_connection()
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

    # جدول الإعدادات الديناميكية
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_settings (
            id SERIAL PRIMARY KEY,
            config_name VARCHAR(50) UNIQUE NOT NULL,
            config_value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # جدول التاريخ
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

    # 🆕 جدول قوانين الذكاء الاصطناعي (جديد)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_laws (
            id SERIAL PRIMARY KEY,
            law_name VARCHAR(100) UNIQUE NOT NULL,
            law_description TEXT,
            law_pattern JSONB,
            confidence_score FLOAT DEFAULT 0.0,
            activation_count INTEGER DEFAULT 0,
            success_rate FLOAT DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            created_by VARCHAR(50) DEFAULT 'AI_OBSERVER'
        )
    """)

    # 🆕 جدول سجل مراقبة الذكاء الاصطناعي
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_observer_log (
            id SERIAL PRIMARY KEY,
            observer_cycle VARCHAR(20),
            action_type VARCHAR(50),
            details JSONB,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    logger.info("✅ تم تهيئة قاعدة البيانات مع جداول المراقبة الذاتية")

def load_dynamic_config():
    """تحميل الإعدادات من قاعدة البيانات"""
    global DYNAMIC_CONFIG
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT config_name, config_value FROM ai_settings")
        for name, value in cur.fetchall():
            if name in DYNAMIC_CONFIG:
                try:
                    DYNAMIC_CONFIG[name] = json.loads(value)
                except:
                    DYNAMIC_CONFIG[name] = value
        conn.close()
    except Exception as e:
        logger.warning(f"⚠️ فشل تحميل الإعدادات: {e}")

def save_dynamic_config(config_updates: Dict[str, Any]):
    """حفظ تحديثات الإعدادات"""
    global DYNAMIC_CONFIG
    conn = get_db_connection()
    cur = conn.cursor()
    for name, value in config_updates.items():
        json_value = json.dumps(value)
        cur.execute("""
            INSERT INTO ai_settings (config_name, config_value)
            VALUES (%s, %s)
            ON CONFLICT (config_name) DO UPDATE 
            SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP
        """, (name, json_value))
        DYNAMIC_CONFIG[name] = value
    conn.commit()
    conn.close()
    logger.info(f"🔄 تم تحديث الإعدادات: {list(config_updates.keys())}")

# ==================== الاشتراكات ====================
def is_user_subscribed(user_id: int) -> Tuple[bool, Optional[str], int]:
    if user_id == ADMIN_ID:
        return True, "Admin", 999
    try:
        conn = get_db_connection()
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
            return True, plan, max(0, remaining)
    except Exception as e:
        logger.error(f"❌ خطأ في التحقق من الاشتراك: {e}")
    return False, None, 0

def activate_subscription(user_id: int, key_code: str) -> Tuple[bool, str]:
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, plan, is_used FROM subscription_keys WHERE key_code = %s", (key_code,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False, "مفتاح غير موجود"
        key_id, plan, is_used = row
        if is_used:
            conn.close()
            return False, "مفتاح مستخدم مسبقاً"
        days = PLANS.get(plan)
        if not days:
            conn.close()
            return False, "خطة غير صالحة"
        expires_at = datetime.datetime.now() + datetime.timedelta(days=days)
        cur.execute("""
            UPDATE subscription_keys
            SET is_used = TRUE, used_by = %s, used_at = NOW(), expires_at = %s
            WHERE id = %s
        """, (user_id, expires_at, key_id))
        conn.commit()
        conn.close()
        return True, f"تم تفعيل اشتراك {plan} بنجاح"
    except Exception as e:
        logger.error(f"❌ خطأ في تفعيل الاشتراك: {e}")
        return False, "خطأ في الخادم"

# ==================== إدارة الجلسات ====================
def init_user_session(context: ContextTypes.DEFAULT_TYPE):
    if 'session_start' not in context.user_data:
        context.user_data.update({
            'session_start': None,
            'session_play_minutes': 0,
            'cool_until': None,
            'cool_stage': 0,
            'correct_streak': 0,
            'last_predictions': []
        })

def can_user_play(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, str]:
    if user_id == ADMIN_ID:
        return True, ""
    init_user_session(context)
    now = datetime.datetime.now()
    cool_until = context.user_data.get('cool_until')
    if cool_until and now < cool_until:
        remaining = (cool_until - now).seconds
        mins, secs = divmod(remaining, 60)
        return False, f"⏳ فترة تبريد: {mins}د {secs}ث"
    if context.user_data['session_start'] is None:
        context.user_data['session_start'] = now
        return True, ""
    session_duration = (now - context.user_data['session_start']).total_seconds() / 60
    played = context.user_data['session_play_minutes'] + session_duration
    if played >= PLAY_SESSION_MINUTES:
        cool_minutes = COOL_DOWN_2_MIN if context.user_data['cool_stage'] else random.randint(*COOL_DOWN_1_MIN)
        context.user_data.update({
            'cool_stage': 1,
            'cool_until': now + datetime.timedelta(minutes=cool_minutes),
            'session_start': None,
            'session_play_minutes': 0
        })
        return False, f"⏸️ انتهت الجلسة. انتظر {cool_minutes} دقيقة"
    return True, ""

def update_session_after_play(context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('session_start') is None:
        return
    now = datetime.datetime.now()
    duration = (now - context.user_data['session_start']).total_seconds() / 60
    context.user_data['session_play_minutes'] += duration
    context.user_data['session_start'] = now

# ==================== المحرك الرياضي ====================
def sovereign_math_engine(b_num: str, suit: str, last_ts, current_ts) -> Tuple[str, int, int, int, int, float]:
    last3 = b_num[-3:]
    B = sum(int(d) for d in last3 if d.isdigit())
    last_digit = int(b_num[-1])
    S = DYNAMIC_CONFIG['S_RED'] if suit in ['♦️', '♥️'] else DYNAMIC_CONFIG['S_BLACK']
    delta_t = int((current_ts - last_ts).total_seconds()) if last_ts else 0
    R = (B * S) + (delta_t % 7) + (last_digit * 3)
    prediction_code = int(R % 2)
    return WINNER_NAMES[prediction_code], prediction_code, R, delta_t, B, S

# ==================== التحليل البايزي ====================
def bayesian_analysis(conn, current_hour: int, min_samples: int = 20) -> Optional[Dict]:
    try:
        df = pd.read_sql("SELECT winner, timestamp FROM history WHERE winner IS NOT NULL", conn)
        if len(df) < min_samples:
            return None
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code'])
        bayesian_probs = {}
        for period in ['morning', 'afternoon', 'evening', 'night']:
            period_data = df[df['period'] == period]
            if len(period_data) >= min_samples:
                total = len(period_data)
                bayesian_probs[period] = (
                    (period_data['winner_code'] == 0).sum() / total,
                    (period_data['winner_code'] == 1).sum() / total,
                    (period_data['winner_code'] == 2).sum() / total,
                )
            else:
                bayesian_probs[period] = None
        return bayesian_probs
    except Exception as e:
        logger.error(f"❌ خطأ في التحليل البايزي: {e}")
        return None

# ==================== التنبؤ الهجين ====================
def hybrid_prediction(b_num: str, suit: str, last_ts, current_ts, bayesian_probs) -> Tuple[str, int, int, int, int, float, str]:
    math_text, math_code, R, gap, B, S = sovereign_math_engine(b_num, suit, last_ts, current_ts)
    if bayesian_probs is None:
        return math_text, math_code, R, gap, B, S, "Math Only"
    current_period = get_time_period(current_ts.hour)
    period_probs = bayesian_probs.get(current_period)
    if period_probs is None:
        return math_text, math_code, R, gap, B, S, "Math Only"
    p_rai, p_thawr, p_tie = period_probs
    bayes_code = int(np.argmax([p_rai, p_thawr, p_tie]))
    noise = DYNAMIC_CONFIG['RANDOM_NOISE']
    weights = [
        DYNAMIC_CONFIG['MATH_WEIGHT'] * (1 if math_code == 0 else 0) + DYNAMIC_CONFIG['BAYES_WEIGHT'] * p_rai + random.uniform(0, noise),
        DYNAMIC_CONFIG['MATH_WEIGHT'] * (1 if math_code == 1 else 0) + DYNAMIC_CONFIG['BAYES_WEIGHT'] * p_thawr + random.uniform(0, noise),
        DYNAMIC_CONFIG['MATH_WEIGHT'] * (1 if math_code == 2 else 0) + DYNAMIC_CONFIG['BAYES_WEIGHT'] * p_tie + random.uniform(0, noise),
    ]
    final_code = int(np.argmax(weights))
    sorted_w = sorted(weights, reverse=True)
    if sorted_w[0] - sorted_w[1] < 0.02:
        final_code = bayes_code
    reason = f"Hybrid | M:{WINNER_NAMES[math_code]} | B:R:{p_rai:.2f} T:{p_thawr:.2f}"
    return WINNER_NAMES[final_code], final_code, R, gap, B, S, reason

# ==================== خدمة NVIDIA AI ====================
class NVIDIAService:
    def __init__(self):
        self.client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
        self.model = NVIDIA_MODEL

    def ask(self, prompt: str, temperature: float = 0.7, max_tokens: int = 2048) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"❌ خطأ NVIDIA AI: {e}")
            return f"⚠️ خطأ في الاتصال: {str(e)[:100]}"

    def ask_json(self, prompt: str, temperature: float = 0.3) -> Optional[Dict]:
        """إرسال طلب والحصول على رد بصيغة JSON"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "أجب فقط بصيغة JSON صالحة. لا تضيف أي نص إضافي."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=1500
            )
            content = response.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل JSON من AI: {e}")
        return None

nvidia_ai = NVIDIAService()

# ==================== 🆕 مراقب الذكاء الاصطناعي المستقل ====================
class AIObserver:
    """
    طرف ثالث يراقب قاعدة البيانات بشكل مستقل
    - مراجعة سريعة كل 10 دقائق
    - مراجعة عميقة كل 30 دقيقة
    - اكتشاف وتخزين القوانين والأنماط
    - تحديث الإعدادات ديناميكياً
    """
    def __init__(self, app):
        self.app = app
        self.client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
        self.model = NVIDIA_MODEL
        self.is_running = False

    def _log_action(self, cycle: str, action: str, details: Dict):
        """تسجيل إجراء المراقب في قاعدة البيانات"""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_observer_log (observer_cycle, action_type, details)
                VALUES (%s, %s, %s)
            """, (cycle, action, json.dumps(details)))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"❌ خطأ في تسجيل سجل المراقب: {e}")

    def _get_recent_history(self, limit: int = 100) -> pd.DataFrame:
        """جلب آخر جولات من التاريخ للتحليل"""
        try:
            conn = get_db_connection()
            df = pd.read_sql(f"""
                SELECT * FROM history 
                WHERE winner IS NOT NULL AND prediction IS NOT NULL
                ORDER BY id DESC LIMIT {limit}
            """, conn)
            conn.close()
            return df
        except Exception as e:
            logger.error(f"❌ خطأ في جلب التاريخ: {e}")
            return pd.DataFrame()

    def _get_existing_laws(self) -> List[Dict]:
        """جلب القوانين المخزنة حالياً"""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT law_name, law_pattern, confidence_score, success_rate, is_active
                FROM ai_laws WHERE is_active = TRUE
            """)
            laws = []
            for row in cur.fetchall():
                laws.append({
                    'name': row[0],
                    'pattern': row[1],
                    'confidence': row[2],
                    'success_rate': row[3],
                    'is_active': row[4]
                })
            conn.close()
            return laws
        except Exception as e:
            logger.error(f"❌ خطأ في جلب القوانين: {e}")
            return []

    def _save_new_law(self, law_name: str, description: str, pattern: Dict, confidence: float):
        """حفظ قانون جديد اكتشفه الذكاء الاصطناعي"""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_laws (law_name, law_description, law_pattern, confidence_score)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (law_name) DO UPDATE 
                SET confidence_score = EXCLUDED.confidence_score, 
                    last_updated = CURRENT_TIMESTAMP
            """, (law_name, description, json.dumps(pattern), confidence))
            conn.commit()
            conn.close()
            logger.info(f"💡 قانون جديد محفوظ: {law_name}")
        except Exception as e:
            logger.error(f"❌ خطأ في حفظ القانون: {e}")

    def _update_law_stats(self, law_name: str, success: bool):
        """تحديث إحصائيات قانون موجود"""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            if success:
                cur.execute("""
                    UPDATE ai_laws 
                    SET activation_count = activation_count + 1,
                        success_rate = (success_rate * activation_count + 1) / (activation_count + 1)
                    WHERE law_name = %s
                """, (law_name,))
            else:
                cur.execute("""
                    UPDATE ai_laws 
                    SET activation_count = activation_count + 1,
                        success_rate = (success_rate * activation_count) / (activation_count + 1)
                    WHERE law_name = %s
                """, (law_name,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"❌ خطأ في تحديث إحصائيات القانون: {e}")

    def _analyze_patterns_quick(self, df: pd.DataFrame) -> List[Dict]:
        """تحليل سريع للأنماط (كل 10 دقائق)"""
        if len(df) < 20:
            return []

        patterns = []

        # نمط 1: تكرار الفائز بعد نتيجة معينة
        for winner in ['الراعي 🔴', 'الثور 🔵', 'تعادل ⚪']:
            subset = df[df['winner'] == winner]
            if len(subset) >= 5:
                last_digit_freq = subset['b_num'].str[-1].value_counts()
                most_common = last_digit_freq.idxmax() if not last_digit_freq.empty else None
                if most_common and last_digit_freq[most_common] >= 3:
                    patterns.append({
                        'type': 'last_digit_after_winner',
                        'winner': winner,
                        'digit': most_common,
                        'frequency': int(last_digit_freq[most_common]),
                        'confidence': min(0.95, last_digit_freq[most_common] / len(subset) + 0.3)
                    })

        # نمط 2: العلاقة بين البذلة والنتيجة
        for suit in ['♦️', '♥️', '♠️', '♣️']:
            subset = df[df['suit'] == suit]
            if len(subset) >= 5:
                winner_freq = subset['winner'].value_counts()
                if not winner_freq.empty:
                    top_winner = winner_freq.idxmax()
                    if winner_freq[top_winner] >= 3:
                        patterns.append({
                            'type': 'suit_winner_correlation',
                            'suit': suit,
                            'winner': top_winner,
                            'frequency': int(winner_freq[top_winner]),
                            'confidence': min(0.95, winner_freq[top_winner] / len(subset) + 0.25)
                        })

        return patterns

    def _analyze_patterns_deep(self, df: pd.DataFrame, existing_laws: List[Dict]) -> Tuple[List[Dict], Optional[Dict]]:
        """تحليل عميق للأنماط واقتراح تحديثات (كل 30 دقيقة)"""
        if len(df) < 50:
            return [], None

        new_laws = []
        config_updates = None

        # تحليل إحصائي متقدم
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code'])

        # 1: تحليل دقة التنبؤ حسب الفترة الزمنية
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        df['period'] = df['hour'].apply(get_time_period)

        period_accuracy = {}
        for period in df['period'].unique():
            period_data = df[df['period'] == period]
            if len(period_data) >= 10:
                acc = (period_data['winner_code'] == period_data['prediction']).mean()
                period_accuracy[period] = float(acc)

        # 2: تحليل تأثير المعاملات الرياضية
        if len(df) >= 30:
            # حساب الارتباط بين R والنتيجة
            def calc_R(row):
                try:
                    last3 = str(row['b_num'])[-3:]
                    B = sum(int(d) for d in last3 if d.isdigit())
                    S = 1.0 if row['suit'] in ['♦️', '♥️'] else 1.0
                    return (B * S) + (int(str(row['b_num'])[-1]) * 3)
                except:
                    return 0

            df['calc_R'] = df.apply(calc_R, axis=1)
            df['R_mod2'] = df['calc_R'] % 2

            correlation = df['R_mod2'].corr(df['winner_code'])
            if abs(correlation) > 0.15:
                # اقتراح تعديل الأوزان
                if correlation > 0:
                    config_updates = {'MATH_WEIGHT': min(0.7, DYNAMIC_CONFIG['MATH_WEIGHT'] + 0.03)}
                else:
                    config_updates = {'MATH_WEIGHT': max(0.3, DYNAMIC_CONFIG['MATH_WEIGHT'] - 0.03)}

        # 3: استخدام AI لاكتشاف قوانين معقدة
        if len(df) >= 80:
            prompt = f"""
أنت خبير في اكتشاف الأنماط في بيانات الألعاب.

بيانات آخر {len(df)} جولة (مجهولة الهوية):
- البذور المستخدمة: {df['suit'].unique().tolist()}
- النتائج: {df['winner'].value_counts().to_dict()}
- دقة التنبؤ العامة: {(df['winner_code'] == df['prediction']).mean():.2%}
- دقة آخر 20 جولة: {(df['winner_code'] == df['prediction']).tail(20).mean():.2%}

المهمة:
1. اقترح 1-2 قانون/نمط جديد محتمل بناءً على البيانات
2. لكل قانون: اسم، وصف، شروط التطبيق، مستوى الثقة (0.0-1.0)
3. إذا وجدت سبباً لتعديل الإعدادات الحالية، اقترح التعديل

أجب بصيغة JSON فقط بهذا الهيكل:
{{
    "new_laws": [
        {{"name": "اسم_القانون", "description": "وصف", "pattern": {{"condition": "...", "action": "..."}}, "confidence": 0.XX}}
    ],
    "config_suggestions": {{"SETTING_NAME": new_value}}
}}
"""
            result = nvidia_ai.ask_json(prompt, temperature=0.2)

            if result:
                # معالجة القوانين الجديدة
                for law in result.get('new_laws', []):
                    if law.get('confidence', 0) >= 0.6:
                        new_laws.append(law)

                # معالجة اقتراحات الإعدادات
                if result.get('config_suggestions'):
                    config_updates = config_updates or {}
                    config_updates.update(result['config_suggestions'])

        return new_laws, config_updates

    async def quick_review_job(self, context: ContextTypes.DEFAULT_TYPE):
        """مهمة المراجعة السريعة - كل 10 دقائق"""
        if not self.is_running:
            return

        logger.info("🔍 [AI Observer] بدء المراجعة السريعة...")

        df = self._get_recent_history(limit=50)
        if df.empty:
            return

        patterns = self._analyze_patterns_quick(df)

        for pattern in patterns:
            law_name = f"{pattern['type']}_{pattern.get('winner', pattern.get('suit', 'unknown'))}"
            existing = [l for l in self._get_existing_laws() if l['name'] == law_name]

            if not existing:
                self._save_new_law(
                    law_name=law_name,
                    description=f"نمط مكتشف: {pattern['type']}",
                    pattern=pattern,
                    confidence=pattern['confidence']
                )
                self._log_action("quick", "new_law", {'law': law_name, 'pattern': pattern})
                logger.info(f"💡 [Quick] قانون جديد: {law_name}")
            else:
                # تحديث الثقة للقانون الموجود
                self._update_law_stats(law_name, True)

        self._log_action("quick", "review_complete", {'patterns_found': len(patterns)})
        logger.info(f"✅ [AI Observer] انتهت المراجعة السريعة - أنماط مكتشفة: {len(patterns)}")

    async def deep_review_job(self, context: ContextTypes.DEFAULT_TYPE):
        """مهمة المراجعة العميقة - كل 30 دقيقة"""
        if not self.is_running:
            return

        logger.info("🔬 [AI Observer] بدء المراجعة العميقة...")

        df = self._get_recent_history(limit=200)
        if df.empty:
            return

        existing_laws = self._get_existing_laws()
        new_laws, config_updates = self._analyze_patterns_deep(df, existing_laws)

        # حفظ القوانين الجديدة
        for law in new_laws:
            self._save_new_law(
                law_name=law['name'],
                description=law['description'],
                pattern=law['pattern'],
                confidence=law['confidence']
            )
            self._log_action("deep", "new_law", law)
            logger.info(f"💡 [Deep] قانون جديد: {law['name']} (ثقة: {law['confidence']})")

        # تطبيق تحديثات الإعدادات
        if config_updates:
            # تصفية القيم غير المنطقية
            safe_updates = {}
            for key, value in config_updates.items():
                if key in DYNAMIC_CONFIG:
                    if isinstance(DYNAMIC_CONFIG[key], (int, float)):
                        if isinstance(value, (int, float)):
                            # حدود آمنة للأوزان
                            if key in ['MATH_WEIGHT', 'BAYES_WEIGHT']:
                                value = max(0.2, min(0.8, value))
                            elif key == 'RANDOM_NOISE':
                                value = max(0.001, min(0.1, value))
                    safe_updates[key] = value

            if safe_updates:
                save_dynamic_config(safe_updates)
                self._log_action("deep", "config_update", safe_updates)
                logger.info(f"⚙️ [Deep] تم تحديث الإعدادات: {safe_updates}")

        # تقييم أداء القوانين الحالية
        for law in existing_laws:
            # هنا يمكن إضافة منطق لتقييم فعالية كل قانون
            pass

        self._log_action("deep", "review_complete", {
            'new_laws': len(new_laws),
            'config_updates': config_updates is not None
        })
        logger.info(f"✅ [AI Observer] انتهت المراجعة العميقة")

    def start(self, job_queue: JobQueue):
        """بدء تشغيل مراقب الذكاء الاصطناعي مع الجدولة"""
        self.is_running = True

        # جدولة المراجعة السريعة كل 10 دقائق
        job_queue.run_repeating(
            self.quick_review_job,
            interval=600,  # 10 دقائق بالثواني
            first=60,  # البدء بعد دقيقة واحدة
            name="ai_observer_quick"
        )
        logger.info("⏰ [AI Observer] تم جدولة المراجعة السريعة كل 10 دقائق")

        # جدولة المراجعة العميقة كل 30 دقيقة
        job_queue.run_repeating(
            self.deep_review_job,
            interval=1800,  # 30 دقيقة بالثواني
            first=120,  # البدء بعد دقيقتين
            name="ai_observer_deep"
        )
        logger.info("⏰ [AI Observer] تم جدولة المراجعة العميقة كل 30 دقائق")

    def stop(self, job_queue: JobQueue):
        """إيقاف مراقب الذكاء الاصطناعي"""
        self.is_running = False
        job_queue.stop()
        logger.info("🛑 [AI Observer] تم إيقاف المراقب")

# ==================== 🆕 أوامر إدارة التاريخ ====================
async def delete_rounds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /delete_rounds N - للأدمن فقط: حذف N جولة من التاريخ
    """
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ هذا الأمر متاح للأدمن فقط.")
        return

    try:
        args = context.args
        if not args or not args[0].isdigit():
            await update.message.reply_text("⚠️ الاستخدام: /delete_rounds <عدد>\nمثال: /delete_rounds 10")
            return

        count = int(args[0])
        if count < 1 or count > 1000:
            await update.message.reply_text("⚠️ العدد يجب أن يكون بين 1 و 1000")
            return

        conn = get_db_connection()
        cur = conn.cursor()

        # جلب IDs للجولات المراد حذفها
        cur.execute("SELECT id FROM history ORDER BY id DESC LIMIT %s", (count,))
        ids_to_delete = [row[0] for row in cur.fetchall()]

        if not ids_to_delete:
            await update.message.reply_text("ℹ️ لا توجد جولات لحذفها.")
            conn.close()
            return

        # الحذف
        cur.execute("DELETE FROM history WHERE id = ANY(%s)", (ids_to_delete,))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"✅ تم حذف {len(ids_to_delete)} جولة من التاريخ.")
        logger.info(f"🗑️ الأدمن {user_id} حذف {len(ids_to_delete)} جولة")

    except Exception as e:
        logger.error(f"❌ خطأ في حذف الجولات: {e}")
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")

async def delete_last_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /delete_last - للمستخدمين: حذف آخر جولة لهم فقط
    """
    user_id = update.effective_user.id

    conn = get_db_connection()
    cur = conn.cursor()

    # البحث عن آخر جولة لهذا المستخدم
    cur.execute("""
        SELECT id, b_num, suit, winner, timestamp 
        FROM history 
        WHERE user_id = %s 
        ORDER BY id DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        await update.message.reply_text("ℹ️ لا توجد جولات سابقة لك لحذفها.")
        return

    entry_id, b_num, suit, winner, timestamp = row

    # الحذف
    cur.execute("DELETE FROM history WHERE id = %s AND user_id = %s", (entry_id, user_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ تم حذف آخر جولة لك:\n"
        f"🎴 {suit} | 🔢 {b_num} | 🏆 {winner}\n"
        f"🕐 {timestamp.strftime('%Y-%m-%d %H:%M')}"
    )
    logger.info(f"🗑️ المستخدم {user_id} حذف آخر جولة له")

# ==================== معالجات البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_sub, plan, rem = is_user_subscribed(user_id)

    if not is_sub and user_id != ADMIN_ID:
        await update.message.reply_text(
            "🔐 **HADES V101.6**\n\n"
            "نظام التنبؤ مغلق للمشتركين فقط.\n"
            "📥 أرسل مفتاح الاشتراك للتفعيل، أو تواصل مع @المسؤول."
        )
        return

    context.user_data.clear()
    init_user_session(context)

    kb = [
        [InlineKeyboardButton("♦️ ديناري", callback_data="s_♦️"), InlineKeyboardButton("♥️ قلب", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد", callback_data="s_♠️"), InlineKeyboardButton("♣️ كلبة", callback_data="s_♣️")],
        [InlineKeyboardButton("🤖 دردشة AI", callback_data="ai_chat")]
    ]

    # إضافة أزرار الإدارة للأدمن
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("🗑️ حذف جولات", callback_data="admin_delete")])

    status = f"📊 الخطة: {plan} | ⏳ المتبقي: {rem} يوم" if is_sub else ""
    await update.message.reply_text(
        f"🏛️ **الكيان السيادي HADES V101.6**\n\n"
        f"{status}\n\n"
        f"🎴 اختر البذلة للبدء، أو دردشة مع AI:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("s_"):
        suit = query.data[2:]
        context.user_data['suit'] = suit
        await query.edit_message_text(
            f"✅ البذلة: {suit}\n\n📥 أرسل رقم البونص (7 أرقام على الأقل):"
        )

    elif query.data == "ai_chat":
        context.user_data['mode'] = "AI"
        await query.edit_message_text(
            "🤖 **وضع AI نشط**\n\nاكتب سؤالك، أو أرسل 'خروج' للعودة:"
        )

    elif query.data == "admin_delete":
        if update.effective_user.id != ADMIN_ID:
            await query.answer("❌ غير مصرح", show_alert=True)
            return
        await query.edit_message_text(
            "🗑️ **حذف الجولات**\n\n"
            "• للأدمن: `/delete_rounds 10` لحذف 10 جولات\n"
            "• للمستخدم: `/delete_last` لحذف آخر جولة لك"
        )

    elif query.data.startswith("save_"):
        winner = query.data[5:]
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO history (b_num, suit, winner, timestamp, prediction, user_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                context.user_data.get('last_b'),
                context.user_data.get('suit'),
                winner,
                datetime.datetime.now(),
                context.user_data.get('last_p'),
                update.effective_user.id
            ))
            conn.commit()
            conn.close()

            context.user_data['last_b'] = None
            context.user_data['last_p'] = None

            await query.edit_message_text(
                f"✅ سُجّل: {winner}\n\n🔄 أرسل البونص القادم:"
            )
        except Exception as e:
            logger.error(f"❌ خطأ في الحفظ: {e}")
            await query.edit_message_text("⚠️ خطأ في حفظ النتيجة. حاول مرة أخرى.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    # 1: محاولة تفعيل الاشتراك
    is_sub, _, _ = is_user_subscribed(user_id)
    if not is_sub and user_id != ADMIN_ID:
        success, msg = activate_subscription(user_id, text)
        if success:
            await update.message.reply_text(f"✅ {msg}\n\nاضغط /start للبدء")
        else:
            await update.message.reply_text(f"❌ {msg}")
        return

    # 2: وضع الدردشة مع AI
    if context.user_data.get('mode') == "AI":
        if text.lower() in ['exit', 'خروج', 'رجوع', 'back', '/start']:
            context.user_data['mode'] = None
            await update.message.reply_text("🔙 تم الخروج. اضغط /start للعودة.")
            return

        response = nvidia_ai.ask(text)
        await update.message.reply_text(f"🤖 **HADES AI:**\n\n{response}", parse_mode='Markdown')
        return

    # 3: معالجة رقم البونص
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start")
            return

        can_play, msg = can_user_play(user_id, context)
        if not can_play:
            await update.message.reply_text(msg)
            return

        now = datetime.datetime.now()
        suit = context.user_data['suit']

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            last_ts = row[0] if row else now
            conn.close()
        except:
            last_ts = now

        try:
            conn = get_db_connection()
            bayesian_probs = bayesian_analysis(conn, now.hour)
            conn.close()
        except:
            bayesian_probs = None

        pred_text, pred_code, R, gap, B, S, reason = hybrid_prediction(
            text, suit, last_ts, now, bayesian_probs
        )

        context.user_data.update({'last_b': text, 'last_p': pred_code})
        update_session_after_play(context)

        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 ثور", callback_data="save_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
        ]

        await update.message.reply_text(
            f"🎯 **توقع HADES V101.6**\n\n"
            f"🏆 **{pred_text}**\n"
            f"⚙️ R={R} | Gap={gap}s | B={B} | S={S}\n"
            f"🎴 {suit}\n"
            f"📊 {reason}\n\n"
            f"سجل النتيجة الحقيقية:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("⚠️ أدخل رقم بونص صحيح (7+ أرقام).")

# ==================== التشغيل الرئيسي ====================
if __name__ == "__main__":
    logger.info("🚀 بدء تشغيل HADES V101.6 مع المراقب الذاتي...")

    # تهيئة القاعدة
    init_database()
    load_dynamic_config()

    # توليد مفاتيح تجريبية إذا فارغة
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM subscription_keys")
        if cur.fetchone()[0] == 0:
            for _ in range(10):
                cur.execute(
                    "INSERT INTO subscription_keys (key_code, plan) VALUES (%s, %s)",
                    (secrets.token_urlsafe(16), 'month')
                )
            conn.commit()
            logger.info("✅ تم توليد مفاتيح تجريبية")
        conn.close()
    except Exception as e:
        logger.warning(f"⚠️ لم يتم توليد المفاتيح: {e}")

    # بناء التطبيق
    app = ApplicationBuilder().token(TOKEN).build()

    # تسجيل المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("delete_rounds", delete_rounds_command))  # 🆕 للأدمن
    app.add_handler(CommandHandler("delete_last", delete_last_command))      # 🆕 للمستخدمين
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 🆕 بدء مراقب الذكاء الاصطناعي المستقل
    ai_observer = AIObserver(app)
    ai_observer.start(app.job_queue)

    logger.info("✅ البوت جاهز. المراقب الذاتي يعمل في الخلفية.")
    logger.info("📊 الجدولة: مراجعة سريعة كل 10 دقائق | مراجعة عميقة كل 30 دقيقة")

    app.run_polling(drop_pending_updates=True)
