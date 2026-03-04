"""
HADES V110 - The Architect (Triple Pattern & Smart Cleaning)
"""

import os, sys, datetime, psycopg2, pandas as pd, numpy as np
import json, re, logging, asyncio
from typing import Dict, Tuple, Optional, List, Any
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, JobQueue
)
from openai import AsyncOpenAI

# ==================== 🛡️ الإعدادات ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

# تم تحديث المفتاح والنموذج إلى Mixtral-8x22B
NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "mistralai/mixtral-8x22b-instruct-v0.1"

WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2,
    0: 0, 1: 1, 2: 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

# ==================== 🛠️ أدوات المعالجة الذكية ====================
def clean_digits(text: str) -> str:
    """استخراج الأرقام فقط وحذف أي إيموجي أو نص"""
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def ensure_columns():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # التأكد من جدول التاريخ
        cur.execute("""
            DO $$ BEGIN 
                ALTER TABLE history ADD COLUMN user_id BIGINT; 
            EXCEPTION WHEN duplicate_column THEN NULL; END $$;
        """)
        # التأكد من جدول القوانين مع الأعمدة الجديدة
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_laws (
            law_name VARCHAR(100) PRIMARY KEY, law_pattern JSONB)""")
        
        cols = [
            "ALTER TABLE ai_laws ADD COLUMN success_count INT DEFAULT 0;",
            "ALTER TABLE ai_laws ADD COLUMN fail_count INT DEFAULT 0;",
            "ALTER TABLE ai_laws ADD COLUMN is_active BOOLEAN DEFAULT TRUE;",
            "ALTER TABLE ai_laws ADD COLUMN last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
        ]
        for q in cols:
            cur.execute(f"DO $$ BEGIN {q} EXCEPTION WHEN duplicate_column THEN NULL; END $$;")
            
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Error: {e}")

# ==================== 🧠 المحرك التحليلي (V110) ====================
def update_law_stats(law_name: str, actual_winner: int, expected_winner: int):
    """تحديث دقيق للقانون"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if actual_winner == expected_winner:
            cur.execute("UPDATE ai_laws SET success_count = success_count + 1 WHERE law_name = %s", (law_name,))
        else:
            cur.execute("UPDATE ai_laws SET fail_count = fail_count + 1 WHERE law_name = %s", (law_name,))
        conn.commit()
        conn.close()
    except: pass

def predict_hybrid(b_num: str, suit: str) -> Tuple[int, str, str]:
    """التنبؤ باستخدام الأنماط الثلاثية + أنماط البذلة"""
    clean_b = clean_digits(b_num)
    if len(clean_b) < 1: return 2, "❌ رقم غير صالح", ""
    
    last_digit = clean_b[-1]
    predicted_winner = 2
    reason = "🧮 تحليل رياضي (احتياطي)"
    used_law = ""

    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1️⃣ البحث عن قانون ثلاثي (Sequence) - هذا هو الأقوى
    # نحتاج آخر نتيجتين من قاعدة البيانات لنعرف التسلسل
    cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 2")
    rows = cur.fetchall()
    if len(rows) == 2:
        last_w1 = WINNER_MAP.get(rows[0][0], 2)
        last_w2 = WINNER_MAP.get(rows[1][0], 2)
        seq_key = f"{last_w2}-{last_w1}" # تسلسل: قبل الأخير -> الأخير
        
        cur.execute("""
            SELECT law_name, law_pattern, success_count, fail_count 
            FROM ai_laws 
            WHERE law_name LIKE %s AND is_active = TRUE 
            ORDER BY (success_count - fail_count) DESC LIMIT 1
        """, (f"SEQ_{seq_key}%",))
        row = cur.fetchone()
        if row:
            name, pat, s, f = row
            if s > f + 2: # شرط الثقة
                return pat['winner'], f"🔗 نمط تسلسلي {seq_key} (✅{s}|❌{f})", name

    # 2️⃣ البحث عن قانون البذلة والرقم (Standard DB Pattern)
    cur.execute("""
        SELECT law_name, law_pattern, success_count, fail_count 
        FROM ai_laws 
        WHERE law_name = %s AND is_active = TRUE
    """, (f"DB_{suit}_{last_digit}",))
    row = cur.fetchone()
    if row:
        name, pat, s, f = row
        if s > f:
            return pat['winner'], f"📜 قانون {name} (✅{s}|❌{f})", name

    conn.close()
    
    # 3️⃣ رياضي بحت إذا لم نجد قوانين
    last3_val = sum(int(d) for d in clean_b[-3:])
    res = (last3_val + int(last_digit)) % 2
    return res, reason, ""

# ==================== 🛠️ أوامر التحكم ====================
async def force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعلم العميق: يستخرج الأرقام وينشئ قوانين ثلاثية"""
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🧠 جاري تحليل 1800+ جولة واستخراج الأنماط الثلاثية...")
    
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM history WHERE winner IS NOT NULL ORDER BY id ASC", conn)
    
    # تنظيف البيانات (السر في V110)
    df['clean_b'] = df['b_num'].astype(str).apply(clean_digits)
    df = df[df['clean_b'] != ""] # حذف الفارغ
    df['last_digit'] = df['clean_b'].str[-1]
    df['winner_code'] = df['winner'].map(WINNER_MAP)
    df = df.dropna(subset=['winner_code', 'last_digit', 'suit'])
    
    cur = conn.cursor()
    laws_added = 0
    
    # 1. تعلم أنماط (بذلة + رقم)
    grouped = df.groupby(['suit', 'last_digit'])['winner_code'].agg(lambda x: x.value_counts().index[0]).to_dict()
    counts = df.groupby(['suit', 'last_digit'])['winner_code'].value_counts().unstack(fill_value=0)
    
    for (suit, digit), best_winner in grouped.items():
        if (suit, digit) in counts.index:
            s = counts.loc[(suit, digit), best_winner]
            f = counts.loc[(suit, digit)].sum() - s
            if s >= 4 and s > f:
                law_name = f"DB_{suit}_{digit}"
                pat = {"suit": suit, "last_digit": digit, "winner": int(best_winner)}
                cur.execute("""INSERT INTO ai_laws (law_name, law_pattern, success_count, fail_count) 
                               VALUES (%s, %s, %s, %s) ON CONFLICT (law_name) DO UPDATE 
                               SET success_count=EXCLUDED.success_count, fail_count=EXCLUDED.fail_count""",
                               (law_name, json.dumps(pat), int(s), int(f)))
                laws_added += 1

    # 2. تعلم الأنماط الثلاثية (Sequence Learning)
    # نحتاج معرفة: إذا جاء (فائز A) ثم (فائز B) -> ماذا يأتي غالباً؟
    df['prev_1'] = df['winner_code'].shift(1)
    df['prev_2'] = df['winner_code'].shift(2)
    df_seq = df.dropna()
    
    seq_groups = df_seq.groupby(['prev_2', 'prev_1'])['winner_code'].agg(lambda x: x.value_counts().index[0]).to_dict()
    seq_counts = df_seq.groupby(['prev_2', 'prev_1'])['winner_code'].value_counts().unstack(fill_value=0)
    
    for (p2, p1), next_w in seq_groups.items():
        s = seq_counts.loc[(p2, p1), next_w]
        f = seq_counts.loc[(p2, p1)].sum() - s
        if s >= 5 and s > f: # ثقة عالية
            law_name = f"SEQ_{int(p2)}-{int(p1)}"
            pat = {"prev_2": int(p2), "prev_1": int(p1), "winner": int(next_w)}
            cur.execute("""INSERT INTO ai_laws (law_name, law_pattern, success_count, fail_count) 
                           VALUES (%s, %s, %s, %s) ON CONFLICT (law_name) DO UPDATE 
                           SET success_count=EXCLUDED.success_count, fail_count=EXCLUDED.fail_count""",
                           (law_name, json.dumps(pat), int(s), int(f)))
            laws_added += 1

    # تنظيف القوانين الفاشلة
    cur.execute("DELETE FROM ai_laws WHERE fail_count > success_count")
    deleted = cur.rowcount
    
    conn.commit()
    conn.close()
    await msg.edit_text(f"✅ **تم تحديث الذكاء (V110)**\n➕ قوانين جديدة/محدثة: {laws_added}\n🗑️ قوانين فاشلة حُذفت: {deleted}\nالآن جرب اللعب!")

async def sql_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القوانين الموجودة للتأكد"""
    if update.effective_user.id != ADMIN_ID: return
    conn = get_db_connection()
    df = pd.read_sql("SELECT law_name, success_count, fail_count FROM ai_laws ORDER BY success_count DESC LIMIT 15", conn)
    conn.close()
    await update.message.reply_text(f"📊 **أقوى القوانين في V110:**\n```\n{df.to_string(index=False)}\n```", parse_mode='Markdown')

# ==================== 🎮 الواجهة ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 بدء اللعب", callback_data="choose_suit")]]
    await update.message.reply_text("🏛️ **HADES V110 - The Architect**\n\n- تعلم الأنماط الثلاثية\n- تنظيف ذكي للأرقام\n\nأوامر الأدمن:\n`/force_learn` - تدريب\n`/sql` - عرض القوانين", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "choose_suit":
        kb = [[InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS]]
        await query.edit_message_text("🎴 اختر البذلة:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("s_"):
        suit = data[2:]
        context.user_data['suit'] = suit
        await query.edit_message_text(f"✅ البذلة: {suit}\n📥 أرسل الأرقام (أي تنسيق مقبول):")
    
    elif data.startswith("save_"):
        w_code = int(data.split("_")[1])
        b_num = context.user_data.get('last_b_num')
        suit = context.user_data.get('last_suit')
        law_used = context.user_data.get('last_law')
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO history (b_num, suit, winner, user_id) VALUES (%s, %s, %s, %s)",
                    (b_num, suit, WINNER_NAMES[w_code], update.effective_user.id))
        conn.commit()
        conn.close()
        
        # تحديث القانون المستخدم (Reinforcement Learning)
        if law_used:
            # نتوقع أن هذا القانون توقع الفائز
            # لكن علينا معرفة ماذا توقع القانون؟ (تم تخزينه في last_pred_code)
            pred_code = context.user_data.get('last_pred_code')
            update_law_stats(law_used, w_code, pred_code)
        
        kb = [[InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last"), InlineKeyboardButton("🔄 بذلة", callback_data="choose_suit")]]
        await query.edit_message_text(f"✅ تم تسجيل: {WINNER_NAMES[w_code]}\n(تم تحديث ذكاء القانون)", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "delete_last":
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM history WHERE id = (SELECT max(id) FROM history WHERE user_id = %s)", (update.effective_user.id,))
        conn.commit()
        conn.close()
        await query.edit_message_text("🗑️ تم الحذف.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    # التنظيف الذكي (الجوهر في V110)
    clean_text = clean_digits(raw_text)
    
    if len(clean_text) >= 3:
        suit = context.user_data.get('suit', '♦️') # افتراضي
        
        pred_code, reason, law_name = predict_hybrid(clean_text, suit)
        
        context.user_data['last_b_num'] = clean_text
        context.user_data['last_suit'] = suit
        context.user_data['last_law'] = law_name
        context.user_data['last_pred_code'] = pred_code
        
        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data="save_0"),
             InlineKeyboardButton("🔵 ثور", callback_data="save_1")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_2")]
        ]
        
        await update.message.reply_text(
            f"🎯 **HADES V110**\n"
            f"📥 الرقم: `{clean_text}`\n"
            f"🏆 التوقع: **{WINNER_NAMES[pred_code]}**\n"
            f"{reason}", 
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("force_learn", force_learn))
    app.add_handler(CommandHandler("sql", sql_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
