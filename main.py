import os
import datetime
import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np
import secrets
import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes
)

# ==================== الإعدادات الثابتة ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {'الراعي 🔴': 0, 'الثور 🔵': 1, 'تعادل ⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

# ==================== إدارة قواعد البيانات ====================
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscription_keys (
            id SERIAL PRIMARY KEY, key_code VARCHAR(50) UNIQUE, 
            is_used BOOLEAN DEFAULT FALSE, used_by BIGINT, expires_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY, b_num VARCHAR(20), suit VARCHAR(10), 
            winner VARCHAR(20), timestamp TIMESTAMP, prediction INTEGER, user_id BIGINT
        );
    """)
    conn.commit()
    conn.close()

# ==================== المحرك الهجين (سرعة فائقة) ====================
def get_hybrid_prediction(b_num, suit, conn):
    # حساب رياضي سريع
    last3 = "".join(filter(str.isdigit, b_num[-3:]))
    b_sum = sum(int(d) for d in last3) if last3 else 10
    s_val = 1.1 if suit in ['♦️', '♥️'] else 0.9
    
    # جلب آخر توقيت لحساب الفجوة
    cur = conn.cursor()
    cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
    last_row = cur.fetchone()
    gap = int((datetime.datetime.now() - last_row[0]).total_seconds()) if last_row else 30
    
    # معادلة HADES الأساسية
    r_val = (b_sum * s_val) + (gap % 7) + (int(b_num[-1]) if b_num[-1].isdigit() else 5)
    math_code = int(r_val % 2)
    
    return math_code, f"R:{int(r_val)} | G:{gap}s"

# ==================== معالجات الأوامر والرسائل ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # فحص الاشتراك
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT expires_at FROM subscription_keys WHERE used_by=%s AND expires_at > NOW()", (user_id,))
    is_sub = cur.fetchone()
    conn.close()

    if not is_sub and user_id != ADMIN_ID:
        await update.message.reply_text("🔐 **نظام HADES V101.5**\nيرجى إرسال كود التفعيل للاستمرار:")
        return

    context.user_data.clear()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🎯 **مرحباً بك في المحرك السيادي**\nاختر البذلة للبدء:", 
                                   reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("s_"):
        context.user_data['suit'] = query.data[2:]
        await query.edit_message_text(f"✅ المود: {query.data[2:]}\n📥 أرسل رقم البونص (7 أرقام):")

    elif query.data.startswith("res_"):
        # حفظ النتيجة في التاريخ
        res_winner = query.data[4:]
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""INSERT INTO history (b_num, suit, winner, timestamp, prediction, user_id) 
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (context.user_data['last_b'], context.user_data['suit'], res_winner, 
                     datetime.datetime.now(), context.user_data['last_p'], update.effective_user.id))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ تم تسجيل {res_winner}\nأرسل البونص التالي مباشرة:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    # 1. منطق التفعيل
    if len(text) > 15:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("UPDATE subscription_keys SET is_used=True, used_by=%s, expires_at=NOW() + interval '30 days' WHERE key_code=%s AND is_used=False RETURNING id", (user_id, text))
        activated = cur.fetchone()
        conn.commit()
        conn.close()
        if activated:
            await update.message.reply_text("✅ تم تفعيل الاشتراك! اضغط /start")
        return

    # 2. منطق التنبؤ (يجب أن يكون الرقم 7 خانات فأكثر)
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start")
            return

        conn = psycopg2.connect(DATABASE_URL)
        p_code, debug_info = get_hybrid_prediction(text, context.user_data['suit'], conn)
        conn.close()

        context.user_data['last_b'] = text
        context.user_data['last_p'] = p_code

        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="res_الراعي 🔴"), 
               InlineKeyboardButton("🔵 ثور", callback_data="res_الثور 🔵")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="res_تعادل ⚪")]]

        await update.message.reply_text(
            f"🎯 التوقع: **{WINNER_NAMES[p_code]}**\n⚙️ `{debug_info}`",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )

# ==================== التشغيل ====================
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 HADES SYSTEM START...")
    app.run_polling()
