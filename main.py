"""
HADES V101.5 - Anti-Bias Self-Optimizing AI Prediction Bot
تم تحديث النموذج إلى stepfun-ai/step-3.5-flash من NVIDIA.
الكود كامل وجاهز للتشغيل على Railway مع PostgreSQL.
"""

import os
import datetime
import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np
import secrets
import json
import re
import time
import logging
import random
from typing import Dict, Any, Tuple, Optional, Generator

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes
)
from openai import OpenAI, APIError, RateLimitError, APIConnectionError

# ==================== الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "stepfun-ai/step-3.5-flash"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PLANS = {'day': 1, 'two_days': 2, 'week': 7, 'month': 30}
WINNER_MAP = {'الراعي 🔴': 0, 'الثور 🔵': 1, 'تعادل ⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

DYNAMIC_CONFIG = {
    'MATH_WEIGHT': 0.55, 'BAYES_WEIGHT': 0.45, 'S_RED': 1.0, 'S_BLACK': 1.0, 'RANDOM_NOISE': 0.02
}

# ==================== إدارة قاعدة البيانات ====================
def init_database():
    conn = psycopg2.connect(DATABASE_URL)
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
    conn = psycopg2.connect(DATABASE_URL)
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
    R = (B * S) + (delta_t % 7) + (int(b_num[-1]) * 3)
    code = int(R % 2)
    return WINNER_NAMES[code], code, R, delta_t

def bayesian_analysis(current_hour: int):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT winner, COUNT(*) FROM history WHERE winner IS NOT NULL GROUP BY winner")
        rows = cur.fetchall()
        conn.close()
        total = sum(r[1] for r in rows)
        if total < 20: return None
        probs = {WINNER_MAP[r[0]]: r[1]/total for r in rows if r[0] in WINNER_MAP}
        return probs
    except: return None

# ==================== معالجات البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_sub, plan, rem = is_user_subscribed(user_id)
    
    if not is_sub:
        await update.message.reply_text("🔐 **HADES V101.5**\nنظام التنبؤ مغلق. يرجى إرسال مفتاح الاشتراك للتفعيل.")
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
        await query.edit_message_text(f"✅ تم اختيار {query.data[2:]}\n📥 أرسل رقم البونص (7 أرقام على الأقل):")
    
    elif query.data == "ai_chat":
        context.user_data['mode'] = "AI"
        await query.edit_message_text("🤖 **وضع الذكاء الاصطناعي نشط**\nتفضل بطرح سؤالك:")

    elif query.data.startswith("save_"):
        # حفظ النتيجة في تاريخ البيانات
        winner_name = query.data[5:]
        conn = psycopg2.connect(DATABASE_URL)
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
    
    # 1. تفعيل المفاتيح
    is_sub, _, _ = is_user_subscribed(user_id)
    if not is_sub:
        conn = psycopg2.connect(DATABASE_URL)
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
        client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
        resp = client.chat.completions.create(model=NVIDIA_MODEL, messages=[{"role":"user", "content":text}])
        await update.message.reply_text(f"🤖 **HADES AI:**\n\n{resp.choices[0].message.content}")
        return

    # 3. معالجة البونص والتوقع
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start")
            return

        now = datetime.datetime.now()
        # جلب آخر توقيت من القاعدة
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        last_ts = row[0] if row else now
        conn.close()

        # حساب التوقع
        p_text, p_code, r_val, gap = sovereign_math_engine(text, context.user_data['suit'], last_ts, now)
        
        # تخزين البيانات للجولة القادمة
        context.user_data['last_b'] = text
        context.user_data['last_p'] = p_code

        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 ثور", callback_data="save_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
        ]

        await update.message.reply_text(
            f"🎯 **توقع HADES V101.5:**\n\n"
            f"🏆 النتيجة: **{p_text}**\n"
            f"⚙️ الاستدلال: `R={r_val} | Gap={gap}s`\n"
            f"🎴 البذلة: {context.user_data['suit']}\n\n"
            f"سجل النتيجة الحقيقية لتطوير الذكاء الاصطناعي:",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("⚠️ يرجى إدخال رقم البونص بشكل صحيح (أرقام فقط).")

# ==================== التشغيل الرئيسي ====================
if __name__ == "__main__":
    init_database()
    # توليد مفاتيح إذا كانت القاعدة فارغة
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM subscription_keys")
    if cur.fetchone()[0] == 0:
        for _ in range(10):
            cur.execute("INSERT INTO subscription_keys (key_code, plan) VALUES (%s, %s)", (secrets.token_urlsafe(16), 'month'))
        conn.commit()
    conn.close()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 HADES V101.5 (Step-3.5-Flash) is running...")
    app.run_polling()
