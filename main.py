"""
HADES V110 - Ultimate Deep Learning AI (Fixed)
"""

import os, re, datetime, psycopg2, pandas as pd, logging
from typing import Dict, List, Tuple, Optional, Any # تم إضافة Tuple هنا
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes
)
from openai import AsyncOpenAI

# ==================== 🛡️ الإعدادات الأساسية ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2,
    0: 0, 1: 1, 2: 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

# ==================== 🗄️ إدارة قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def ensure_columns():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_laws (
            law_name VARCHAR(100) PRIMARY KEY, law_pattern JSONB,
            success_count INT DEFAULT 0, fail_count INT DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Init Error: {e}")

# ==================== 🛠️ معالج البيانات ====================
def clean_digits(text: str) -> str:
    return re.sub(r"\D", "", text)

# ==================== 🧠 محرك التوقع ====================
def predict_hybrid(b_num: str, suit: str) -> Tuple[int, str]:
    digits = clean_digits(b_num)
    if len(digits) < 1: return 2, "❌ رقم غير صالح"
    last_digit = digits[-1]
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT law_name, law_pattern, success_count, fail_count 
            FROM ai_laws 
            WHERE law_pattern->>'suit' = %s AND law_pattern->>'last_digit' = %s 
            AND is_active = TRUE
            ORDER BY (success_count - fail_count) DESC LIMIT 1
        """, (suit, last_digit))
        law = cur.fetchone()
        conn.close()
        
        if law:
            name, pattern, succ, fail = law
            return pattern.get('winner', 2), f"📜 {name} (✅{succ}|❌{fail})"
    except: pass
    
    # احتياطي رياضي
    last3_sum = sum(int(d) for d in digits[-3:])
    res = (last3_sum + int(last_digit)) % 2
    return res, "🧮 تحليل رياضي"

# ==================== 🚀 الأوامر ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("🏛️ HADES V110\nأرسل البونص للتحليل.", reply_markup=InlineKeyboardMarkup(kb))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "choose_suit":
        kb = [[InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS]]
        await query.edit_message_text("🎴 اختر البذلة:", reply_markup=InlineKeyboardMarkup(kb))
    elif query.data.startswith("s_"):
        context.user_data['suit'] = query.data[2:]
        await query.edit_message_text(f"✅ تم حفظ البذلة: {context.user_data['suit']}\n📥 أرسل الرقم:")
    elif query.data.startswith("save_"):
        winner_code = int(query.data.split("_")[1])
        b_num = context.user_data.get('last_b_num')
        suit = context.user_data.get('last_suit')
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO history (b_num, suit, winner, user_id) VALUES (%s, %s, %s, %s)",
                    (b_num, suit, WINNER_NAMES[winner_code], update.effective_user.id))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ تم تسجيل {WINNER_NAMES[winner_code]}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = clean_digits(update.message.text)
    if len(text) >= 5:
        suit = context.user_data.get('suit', '♦️')
        context.user_data['last_b_num'] = text
        context.user_data['last_suit'] = suit
        pred, reason = predict_hybrid(text, suit)
        kb = [[InlineKeyboardButton("🔴", callback_data="save_0"), InlineKeyboardButton("🔵", callback_data="save_1")]]
        await update.message.reply_text(f"🏆 {WINNER_NAMES[pred]}\n⚙️ {reason}", reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
