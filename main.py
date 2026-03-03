"""
HADES V104.5 - Fast AI Prediction Bot
تم تحديث الكود للسرعة والكفاءة بدون تعقيدات زائدة، ومعالجة صحيحة لرسائل البونص.
"""

import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
import secrets
import json
import re
import random
import logging
from typing import Dict, Any, Tuple, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes
)
from openai import OpenAI

# ==================== الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

# مفتاح NVIDIA
NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

WINNER_MAP = {'الراعي 🔴': 0, 'الثور 🔵': 1, 'تعادل ⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

DYNAMIC_CONFIG = {
    'MATH_WEIGHT': 0.55, 'BAYES_WEIGHT': 0.45, 'S_RED': 1.0, 'S_BLACK': 1.0, 'RANDOM_NOISE': 0.02
}

# ==================== إدارة قاعدة البيانات ====================
def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"❌ Database connection error: {e}")
        return None

def init_database():
    conn = get_db_connection()
    if not conn: return
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscription_keys (
            id SERIAL PRIMARY KEY, key_code VARCHAR(50) UNIQUE, plan VARCHAR(20),
            is_used BOOLEAN DEFAULT FALSE, used_by BIGINT, expires_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY, b_num VARCHAR(20), suit VARCHAR(10), 
            winner VARCHAR(20), timestamp TIMESTAMP, prediction INTEGER, user_id BIGINT
        );
        CREATE TABLE IF NOT EXISTS ai_settings (
            config_name VARCHAR(50) PRIMARY KEY, config_value TEXT
        );
    """)
    conn.commit()
    conn.close()

def is_user_subscribed(user_id: int):
    if user_id == ADMIN_ID: return True, "Admin", 999
    conn = get_db_connection()
    if not conn: return False, None, 0
    cur = conn.cursor()
    cur.execute("SELECT plan, expires_at FROM subscription_keys WHERE used_by = %s AND expires_at > NOW()", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        rem = (row[1] - datetime.datetime.now()).days
        return True, row[0], rem
    return False, None, 0

# ==================== المحرك الرياضي والذكاء الاصطناعي ====================
def sovereign_math_engine(b_num: str, suit: str, last_ts, current_ts):
    last3 = b_num[-3:]
    B = sum(int(d) for d in last3 if d.isdigit())
    S = DYNAMIC_CONFIG['S_RED'] if suit in ['♦️', '♥️'] else DYNAMIC_CONFIG['S_BLACK']
    delta_t = int((current_ts - last_ts).total_seconds()) if last_ts else 0
    
    last_digit = int(b_num[-1]) if b_num[-1].isdigit() else 0
    R = (B * S) + (delta_t % 7) + (last_digit * 3)
    code = int(R % 2)
    return WINNER_NAMES[code], code, R, delta_t

def bayesian_analysis(current_hour: int):
    try:
        conn = get_db_connection()
        if not conn: return None
        cur = conn.cursor()
        # نستخدم آخر 100 جولة فقط للسرعة
        cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 100")
        rows = cur.fetchall()
        conn.close()
        
        if not rows: return None
        
        total = len(rows)
        counts = {0: 0, 1: 0, 2: 0}
        for r in rows:
            code = WINNER_MAP.get(r[0])
            if code is not None:
                counts[code] += 1
                
        probs = {k: v/total for k, v in counts.items()}
        return probs
    except Exception as e:
        logger.error(f"Bayesian Analysis Error: {e}")
        return None

def hybrid_prediction(b_num: str, suit: str, last_ts, current_ts):
    math_text, math_code, R, gap = sovereign_math_engine(b_num, suit, last_ts, current_ts)
    probs = bayesian_analysis(current_ts.hour)
    
    if not probs:
        return math_text, math_code, R, gap, "Math Only"
        
    p_rai, p_thawr, p_tie = probs.get(0, 0), probs.get(1, 0), probs.get(2, 0)
    bayes_code = np.argmax([p_rai, p_thawr, p_tie])
    
    w_rai = DYNAMIC_CONFIG['MATH_WEIGHT'] * (1 if math_code == 0 else 0) + DYNAMIC_CONFIG['BAYES_WEIGHT'] * p_rai + random.uniform(0, DYNAMIC_CONFIG['RANDOM_NOISE'])
    w_thawr = DYNAMIC_CONFIG['MATH_WEIGHT'] * (1 if math_code == 1 else 0) + DYNAMIC_CONFIG['BAYES_WEIGHT'] * p_thawr + random.uniform(0, DYNAMIC_CONFIG['RANDOM_NOISE'])
    w_tie = DYNAMIC_CONFIG['MATH_WEIGHT'] * (1 if math_code == 2 else 0) + DYNAMIC_CONFIG['BAYES_WEIGHT'] * p_tie + random.uniform(0, DYNAMIC_CONFIG['RANDOM_NOISE'])
    
    scores = [w_rai, w_thawr, w_tie]
    final_code = int(np.argmax(scores))
    
    sorted_scores = sorted(scores, reverse=True)
    if sorted_scores[0] - sorted_scores[1] < 0.02:
        final_code = bayes_code
        
    reason = f"Hybrid | Math:{WINNER_NAMES[math_code]} | Bayes R:{p_rai:.2f} T:{p_thawr:.2f}"
    return WINNER_NAMES[final_code], final_code, R, gap, reason

# ==================== معالجات البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_sub, plan, rem = is_user_subscribed(user_id)
    
    if not is_sub:
        await update.message.reply_text("🔐 **HADES V104.5**\nالنظام مغلق. يرجى إرسال مفتاح الاشتراك للتفعيل.")
        return

    kb = [
        [InlineKeyboardButton("♦️ ديناري", callback_data="s_♦️"), InlineKeyboardButton("♥️ قلب", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد", callback_data="s_♠️"), InlineKeyboardButton("♣️ كلبة", callback_data="s_♣️")],
        [InlineKeyboardButton("🤖 دردشة AI", callback_data="ai_chat")]
    ]
    await update.message.reply_text(
        f"🏛️ **الكيان السيادي HADES**\nالخطة: {plan} | المتبقي: {rem} يوم\n\nاختر نوع البذلة للبدء:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("s_"):
        context.user_data['suit'] = query.data[2:]
        context.user_data['mode'] = "PREDICT"
        await query.edit_message_text(f"✅ تم اختيار {query.data[2:]}\n📥 أرسل رقم البونص (7 أرقام على الأقل):")
    
    elif query.data == "ai_chat":
        context.user_data['mode'] = "AI"
        await query.edit_message_text("🤖 **وضع الذكاء الاصطناعي نشط**\nتفضل بطرح سؤالك:")

    elif query.data.startswith("save_"):
        winner_name = query.data[5:]
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO history (b_num, suit, winner, timestamp, prediction, user_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (context.user_data.get('last_b'), context.user_data.get('suit'), winner_name, 
                  datetime.datetime.now(), context.user_data.get('last_p'), update.effective_user.id))
            conn.commit()
            conn.close()
        await query.edit_message_text(f"✅ تم تسجيل النتيجة: {winner_name}\nأرسل البونص القادم مباشرة:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # 1. تفعيل المفاتيح (إذا كان نص طويل ولا يبدو كبونص)
    is_sub, _, _ = is_user_subscribed(user_id)
    if not is_sub:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("UPDATE subscription_keys SET is_used=TRUE, used_by=%s, used_at=NOW(), expires_at=NOW()+INTERVAL '30 days' WHERE key_code=%s AND is_used=FALSE RETURNING plan", (user_id, text))
            res = cur.fetchone()
            conn.commit()
            conn.close()
            if res:
                await update.message.reply_text(f"✅ تم تفعيل اشتراك {res[0]} بنجاح! اضغط /start")
            else:
                await update.message.reply_text("❌ مفتاح خاطئ أو مستخدم مسبقاً.")
        return

    # 2. وضع الدردشة
    if context.user_data.get('mode') == "AI":
        try:
            client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
            resp = client.chat.completions.create(model=NVIDIA_MODEL, messages=[{"role":"user", "content":text}])
            await update.message.reply_text(f"🤖 **HADES AI:**\n\n{resp.choices[0].message.content}")
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ في الاتصال بالذكاء الاصطناعي: {e}")
        return

    # 3. معالجة البونص والتوقع
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start")
            return

        now = datetime.datetime.now()
        # جلب آخر توقيت من القاعدة
        conn = get_db_connection()
        last_ts = now
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            last_ts = row[0] if row else now
            conn.close()

        # حساب التوقع
        p_text, p_code, r_val, gap, reason = hybrid_prediction(text, context.user_data['suit'], last_ts, now)
        
        # تخزين البيانات للجولة القادمة
        context.user_data['last_b'] = text
        context.user_data['last_p'] = p_code

        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 ثور", callback_data="save_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
        ]

        await update.message.reply_text(
            f"🎯 **توقع HADES V104.5:**\n\n"
            f"🏆 النتيجة: **{p_text}**\n"
            f"⚙️ الاستدلال: `{reason}`\n"
            f"⏱️ Gap: {gap}s | R: {r_val}\n"
            f"🎴 البذلة: {context.user_data['suit']}\n\n"
            f"سجل النتيجة الحقيقية لتحديث الأوزان:",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )
    else:
        if context.user_data.get('mode') == "PREDICT":
             await update.message.reply_text("⚠️ يرجى إدخال رقم البونص بشكل صحيح (أرقام فقط، 7 أرقام على الأقل).")

# ==================== التشغيل الرئيسي ====================
if __name__ == "__main__":
    init_database()
    # توليد مفاتيح إذا كانت القاعدة فارغة
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM subscription_keys")
        if cur.fetchone()[0] == 0:
            for _ in range(10):
                cur.execute("INSERT INTO subscription_keys (key_code, plan) VALUES (%s, %s)", (secrets.token_urlsafe(16), 'month'))
            conn.commit()
            logger.info("Generated initial subscription keys.")
        conn.close()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 HADES V104.5 is running...")
    app.run_polling()
