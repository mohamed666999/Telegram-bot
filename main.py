"""
HADES V101.5 - Anti-Bias Self-Optimizing AI Prediction Bot
نظام تنبؤ هجين: معادلة رياضية + تحليل بايزي + NVIDIA AI
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
from typing import Dict, Any, Tuple, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes
)
from openai import OpenAI

# ==================== إعدادات التسجيل ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== الثوابت والإعدادات ====================
# ⚠️ استبدل هذه القيم بمتغيرات بيئة في الإنتاج
TOKEN = os.getenv("TELEGRAM_TOKEN", "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway")
ADMIN_ID = 6033203084

# تم التحديث إلى المفتاح والنموذج الجديدين
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "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")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

# خطط الاشتراك
PLANS = {'day': 1, 'two_days': 2, 'week': 7, 'month': 30}

# خريطة الفائزين
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

# الإعدادات الديناميكية
DYNAMIC_CONFIG = {
    'CONFIDENCE_THRESHOLD': 0.65,
    'MATH_WEIGHT': 0.55,
    'BAYES_WEIGHT': 0.45,
    'MATH_CONFIDENCE': 0.7,
    'S_RED': 1.0,
    'S_BLACK': 1.0,
    'RANDOM_NOISE': 0.02,
}

# إعدادات الجلسات
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
def init_database():
    """إنشاء الجداول إذا لم تكن موجودة"""
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
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_settings (
            id SERIAL PRIMARY KEY,
            config_name VARCHAR(50) UNIQUE NOT NULL,
            config_value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
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
    logger.info("✅ تم تهيئة قاعدة البيانات")

def load_dynamic_config():
    """تحميل الإعدادات من قاعدة البيانات"""
    global DYNAMIC_CONFIG
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
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
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
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

# ==================== الاشتراكات ====================
def is_user_subscribed(user_id: int) -> Tuple[bool, Optional[str], int]:
    """التحقق من اشتراك المستخدم"""
    if user_id == ADMIN_ID:
        return True, "Admin", 999
    
    try:
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
            return True, plan, max(0, remaining)
    except Exception as e:
        logger.error(f"❌ خطأ في التحقق من الاشتراك: {e}")
    
    return False, None, 0

def activate_subscription(user_id: int, key_code: str) -> Tuple[bool, str]:
    """تفعيل مفتاح الاشتراك"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, plan, is_used FROM subscription_keys 
            WHERE key_code = %s
        """, (key_code,))
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
    """تهيئة بيانات جلسة المستخدم"""
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
    """التحقق من إمكانية لعب المستخدم"""
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
    """تحديث الجلسة بعد كل جولة"""
    if context.user_data.get('session_start') is None:
        return
    now = datetime.datetime.now()
    duration = (now - context.user_data['session_start']).total_seconds() / 60
    context.user_data['session_play_minutes'] += duration
    context.user_data['session_start'] = now

# ==================== المحرك الرياضي ====================
def sovereign_math_engine(b_num: str, suit: str, last_ts, current_ts) -> Tuple[str, int, int, int, int, float]:
    """المحرك الرياضي الأساسي للتنبؤ"""
    last3 = b_num[-3:]
    B = sum(int(d) for d in last3 if d.isdigit())
    last_digit = int(b_num[-1])
    S = DYNAMIC_CONFIG['S_RED'] if suit in ['♦️', '♥️'] else DYNAMIC_CONFIG['S_BLACK']
    delta_t = int((current_ts - last_ts).total_seconds()) if last_ts else 0
    
    # المعادلة الجديدة المقاومة للانحياز
    R = (B * S) + (delta_t % 7) + (last_digit * 3)
    prediction_code = int(R % 2)
    
    return WINNER_NAMES[prediction_code], prediction_code, R, delta_t, B, S

# ==================== التحليل البايزي ====================
def bayesian_analysis(conn, current_hour: int, min_samples: int = 20) -> Optional[Dict]:
    """تحليل بايزي بناءً على البيانات التاريخية"""
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
    """دمج التنبؤ الرياضي مع البايزي"""
    math_text, math_code, R, gap, B, S = sovereign_math_engine(b_num, suit, last_ts, current_ts)
    
    if bayesian_probs is None:
        return math_text, math_code, R, gap, B, S, "Math Only"
    
    current_period = get_time_period(current_ts.hour)
    period_probs = bayesian_probs.get(current_period)
    
    if period_probs is None:
        return math_text, math_code, R, gap, B, S, "Math Only"
    
    p_rai, p_thawr, p_tie = period_probs
    bayes_code = int(np.argmax([p_rai, p_thawr, p_tie]))
    
    # دمج مرجح مع ضوضاء عشوائية صغيرة
    noise = DYNAMIC_CONFIG['RANDOM_NOISE']
    weights = [
        DYNAMIC_CONFIG['MATH_WEIGHT'] * (1 if math_code == 0 else 0) + DYNAMIC_CONFIG['BAYES_WEIGHT'] * p_rai + random.uniform(0, noise),
        DYNAMIC_CONFIG['MATH_WEIGHT'] * (1 if math_code == 1 else 0) + DYNAMIC_CONFIG['BAYES_WEIGHT'] * p_thawr + random.uniform(0, noise),
        DYNAMIC_CONFIG['MATH_WEIGHT'] * (1 if math_code == 2 else 0) + DYNAMIC_CONFIG['BAYES_WEIGHT'] * p_tie + random.uniform(0, noise),
    ]
    
    final_code = int(np.argmax(weights))
    # إذا كانت النتائج متقاربة جداً، نعتمد على البايزي
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
    
    def ask(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=1,
                top_p=0.95,
                max_tokens=8192
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"❌ خطأ NVIDIA AI: {e}")
            return f"⚠️ خطأ في الاتصال: {str(e)[:100]}"

nvidia_ai = NVIDIAService()

# ==================== معالجات البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر البداية"""
    user_id = update.effective_user.id
    is_sub, plan, rem = is_user_subscribed(user_id)
    
    if not is_sub and user_id != ADMIN_ID:
        await update.message.reply_text(
            "🔐 **HADES V101.5**\n\n"
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
    
    status = f"📊 الخطة: {plan} | ⏳ المتبقي: {rem} يوم" if is_sub else ""
    await update.message.reply_text(
        f"🏛️ **الكيان السيادي HADES V101.5**\n\n"
        f"{status}\n\n"
        f"🎴 اختر البذلة للبدء، أو دردشة مع AI:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار التفاعلية"""
    query = update.callback_query
    await query.answer()
    
    # اختيار البذلة
    if query.data.startswith("s_"):
        suit = query.data[2:]
        context.user_data['suit'] = suit
        await query.edit_message_text(
            f"✅ البذلة: {suit}\n\n📥 أرسل رقم البونص (7 أرقام على الأقل):"
        )
    
    # وضع الدردشة
    elif query.data == "ai_chat":
        context.user_data['mode'] = "AI"
        await query.edit_message_text(
            "🤖 **وضع AI نشط**\n\nاكتب سؤالك، أو أرسل 'خروج' للعودة:"
        )
    
    # حفظ النتيجة
    elif query.data.startswith("save_"):
        winner = query.data[5:]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
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
            
            # إعادة التهيئة للجولة التالية
            context.user_data['last_b'] = None
            context.user_data['last_p'] = None
            
            await query.edit_message_text(
                f"✅ سُجّل: {winner}\n\n🔄 أرسل البونص القادم:"
            )
        except Exception as e:
            logger.error(f"❌ خطأ في الحفظ: {e}")
            await query.edit_message_text("⚠️ خطأ في حفظ النتيجة. حاول مرة أخرى.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل النصية الرئيسي"""
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
        
        # جلب آخر توقيت
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            last_ts = row[0] if row else now
            conn.close()
        except:
            last_ts = now
        
        # تحليل بايزي
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            bayesian_probs = bayesian_analysis(conn, now.hour)
            conn.close()
        except:
            bayesian_probs = None
        
        # حساب التنبؤ
        pred_text, pred_code, R, gap, B, S, reason = hybrid_prediction(
            text, suit, last_ts, now, bayesian_probs
        )
        
        # حفظ للجلسة التالية
        context.user_data.update({'last_b': text, 'last_p': pred_code})
        update_session_after_play(context)
        
        # أزرار النتيجة
        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 ثور", callback_data="save_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
        ]
        
        await update.message.reply_text(
            f"🎯 **توقع HADES V101.5**\n\n"
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
    logger.info("🚀 بدء تشغيل HADES V101.5...")
    
    # تهيئة القاعدة
    init_database()
    load_dynamic_config()
    
    # توليد مفاتيح تجريبية إذا فارغة
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
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
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ البوت جاهز. ينتظر الرسائل...")
    app.run_polling(drop_pending_updates=True)
