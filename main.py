"""
HADES V112 - The Oracle (3-Layer Architecture & Safe DB Pool)
تم إصلاح مشكلة طول الرقم، وتطبيق نظام التوقع الهرمي، وحل مشكلة تجميد قاعدة البيانات.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging, io
from typing import Tuple
from contextlib import contextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2, 0: 0, 1: 1, 2: 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

RANK_VALUE = {"A":14, "K":13, "Q":12, "J":11, "10":10, "9":9, "8":8, "7":7, "6":6, "5":5, "4":4, "3":3, "2":2}
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]

# ==================== 🗄️ إدارة قاعدة البيانات (الآمنة جداً) ====================
@contextmanager
def get_db_cursor():
    """هذا الحل المعماري يمنع تجميد السيرفر تماماً ويغلق الاتصال تلقائياً"""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()

def ensure_columns():
    with get_db_cursor() as (conn, cur):
        history_updates = [
            "ALTER TABLE history ADD COLUMN rank VARCHAR(5);",
            "ALTER TABLE history ADD COLUMN bonus_last_digit INT;",
            "ALTER TABLE history ADD COLUMN user_id BIGINT;"
        ]
        for q in history_updates:
            cur.execute(f"DO $$ BEGIN {q} EXCEPTION WHEN duplicate_column THEN NULL; END $$;")
            
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_laws (
            law_name VARCHAR(100) PRIMARY KEY, law_pattern JSONB,
            success_count INT DEFAULT 0, fail_count INT DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE)""")
        conn.commit()

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

# ==================== 🧠 محرك التوقع الهرمي (3 طبقات) ====================
def predict_3_layer(b_num: str, suit: str, rank: str) -> Tuple[int, str]:
    digits = clean_digits(b_num)
    last_digit = int(digits[-1])
    
    with get_db_cursor() as (conn, cur):
        # 🟢 الطبقة الأولى: قانون دقيق (بذلة + ورقة + رقم)
        cur.execute("""
            SELECT law_name, success_count, fail_count, law_pattern->>'winner' 
            FROM ai_laws WHERE law_name = %s AND is_active = TRUE
        """, (f"DB_{suit}_{rank}_{last_digit}",))
        row = cur.fetchone()
        if row and row[1] > row[2]:
            return int(row[3]), f"🎯 تطابق دقيق: {row[0]} (✅{row[1]}|❌{row[2]})"

        # 🟡 الطبقة الثانية: قانون عام (بذلة + رقم) - في حال غياب الورقة
        cur.execute("""
            SELECT law_name, success_count, fail_count, law_pattern->>'winner' 
            FROM ai_laws WHERE law_name = %s AND is_active = TRUE
        """, (f"DB_{suit}_ALL_{last_digit}",))
        row = cur.fetchone()
        if row and row[1] > row[2]:
            return int(row[3]), f"📜 تطابق البذلة: {row[0]} (✅{row[1]}|❌{row[2]})"

    # 🔴 الطبقة الثالثة: المعادلة الرياضية المعززة بقيمة الورقة (إذا فشلت القوانين)
    last_digits_sum = sum(int(d) for d in digits[-3:]) # يجمع آخر 3 أرقام (أو أقل إن كان الرقم صغيراً)
    card_val = RANK_VALUE.get(rank, 0)
    math_result = ((last_digits_sum * card_val) + last_digit) % 2
    return math_result, f"🧮 المحرك الرياضي (قيمة الورقة: {card_val})"

def update_law_stats(law_name: str, is_success: bool):
    with get_db_cursor() as (conn, cur):
        if is_success:
            cur.execute("UPDATE ai_laws SET success_count = success_count + 1 WHERE law_name = %s", (law_name,))
        else:
            cur.execute("UPDATE ai_laws SET fail_count = fail_count + 1 WHERE law_name = %s", (law_name,))
        conn.commit()

# ==================== 🛠️ أوامر الإدارة ====================
async def force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🧠 جاري بناء الطبقات التحليلية...")
    
    with get_db_cursor() as (conn, cur):
        df = pd.read_sql("SELECT suit, rank, bonus_last_digit, b_num, winner FROM history WHERE winner IS NOT NULL", conn)
        
    df['clean_b'] = df['b_num'].astype(str).apply(clean_digits)
    df = df[df['clean_b'] != ""]
    df['calc_last_digit'] = df['clean_b'].str[-1]
    df['final_digit'] = df['bonus_last_digit'].fillna(df['calc_last_digit'])
    df['winner_code'] = df['winner'].map(WINNER_MAP)
    df = df.dropna(subset=['winner_code', 'final_digit', 'suit'])
    
    laws_added = 0
    with get_db_cursor() as (conn, cur):
        # 1. بناء قوانين الطبقة الثانية (بذلة + رقم)
        grp_all = df.groupby(['suit', 'final_digit'])['winner_code'].value_counts().unstack(fill_value=0)
        for (suit, digit), row in grp_all.iterrows():
            best_winner = row.idxmax()
            succ, fail = row[best_winner], row.drop(best_winner).sum()
            if succ >= 5 and succ > fail:
                l_name = f"DB_{suit}_ALL_{digit}"
                pat = {"suit": suit, "last_digit": str(digit), "winner": int(best_winner)}
                cur.execute("""INSERT INTO ai_laws (law_name, law_pattern, success_count, fail_count) 
                               VALUES (%s, %s, %s, %s) ON CONFLICT (law_name) DO UPDATE 
                               SET success_count=EXCLUDED.success_count, fail_count=EXCLUDED.fail_count""",
                               (l_name, json.dumps(pat), int(succ), int(fail)))
                laws_added += 1

        # 2. بناء قوانين الطبقة الأولى (بذلة + ورقة + رقم)
        df_rank = df.dropna(subset=['rank'])
        if not df_rank.empty:
            grp_rank = df_rank.groupby(['suit', 'rank', 'final_digit'])['winner_code'].value_counts().unstack(fill_value=0)
            for (suit, rank, digit), row in grp_rank.iterrows():
                best_winner = row.idxmax()
                succ, fail = row[best_winner], row.drop(best_winner).sum()
                if succ >= 3 and succ > fail:
                    l_name = f"DB_{suit}_{rank}_{digit}"
                    pat = {"suit": suit, "rank": rank, "last_digit": str(digit), "winner": int(best_winner)}
                    cur.execute("""INSERT INTO ai_laws (law_name, law_pattern, success_count, fail_count) 
                                   VALUES (%s, %s, %s, %s) ON CONFLICT (law_name) DO UPDATE 
                                   SET success_count=EXCLUDED.success_count, fail_count=EXCLUDED.fail_count""",
                                   (l_name, json.dumps(pat), int(succ), int(fail)))
                    laws_added += 1

        cur.execute("DELETE FROM ai_laws WHERE fail_count >= success_count")
        deleted = cur.rowcount
        conn.commit()
    
    await msg.edit_text(f"✅ **تم التدريب (V112 - 3 Layers)**\n➕ قوانين مبنية: {laws_added}\n🗑️ قوانين فاشلة حُذفت: {deleted}")

# ==================== 📥 أمر تحميل قاعدة البيانات ====================
async def download_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """سحب قاعدة البيانات كملف Excel (للأدمن فقط)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمسؤول فقط.")
        return
    msg = await update.message.reply_text("⏳ جاري تحضير نسخة احتياطية...")
    try:
        with get_db_cursor() as (conn, cur):
            # جلب جميع الجداول المهمة
            df_history = pd.read_sql("SELECT * FROM history ORDER BY id", conn)
            df_laws = pd.read_sql("SELECT * FROM ai_laws ORDER BY law_name", conn)
        # إنشاء ملف Excel في الذاكرة
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_history.to_excel(writer, sheet_name='history', index=False)
            df_laws.to_excel(writer, sheet_name='ai_laws', index=False)
        output.seek(0)
        filename = f"hades_db_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        await update.message.reply_document(document=output, filename=filename, caption="📥 نسخة احتياطية من قاعدة بيانات HADES")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")

# ==================== 🎮 واجهة التليجرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("🏛️ **HADES V112 - The Oracle**\n\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "choose_suit":
        kb = [[InlineKeyboardButton(s, callback_data=f"suit_{s}") for s in SUITS]]
        await query.edit_message_text("🎴 **اختر البذلة:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        
    elif data.startswith("suit_"):
        suit = data.split("_")[1]
        context.user_data['suit'] = suit
        kb = [[InlineKeyboardButton(r, callback_data=f"rank_{r}") for r in row] for row in RANKS_LAYOUT]
        kb.append([InlineKeyboardButton("🔙 رجوع للبذلات", callback_data="choose_suit")])
        await query.edit_message_text(f"✅ البذلة: **{suit}**\n🃏 **اختر الورقة:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith("rank_"):
        rank = data.split("_")[1]
        context.user_data['rank'] = rank
        suit = context.user_data.get('suit', '')
        kb = [[InlineKeyboardButton("🔄 تغيير الاختيار", callback_data="choose_suit")]]
        await query.edit_message_text(f"✅ جاهز: **{suit} {rank}**\n\n📥 **أرسل رقم البونص الآن:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == "delete_last":
        with get_db_cursor() as (conn, cur):
            cur.execute("DELETE FROM history WHERE id = (SELECT max(id) FROM history WHERE user_id = %s)", (update.effective_user.id,))
            conn.commit()
        kb = [[InlineKeyboardButton("🔄 استمرار", callback_data=f"rank_{context.user_data.get('rank')}")]]
        await query.edit_message_text("🗑️ تم حذف الجولة الخاطئة.", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("save_"):
        w_code = int(data.split("_")[1])
        b_num = context.user_data.get('last_b_num')
        suit = context.user_data.get('last_suit')
        rank = context.user_data.get('last_rank')
        law_used = context.user_data.get('last_law')
        pred_code = context.user_data.get('last_pred_code')
        
        if b_num and suit and rank:
            last_digit = int(b_num[-1])
            with get_db_cursor() as (conn, cur):
                cur.execute("""INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id) 
                               VALUES (%s, %s, %s, %s, %s, %s)""",
                            (b_num, suit, rank, last_digit, WINNER_NAMES[w_code], update.effective_user.id))
                conn.commit()
            
            if law_used and ("تطابق" in law_used or "قانون" in law_used):
                law_name = law_used.split(":")[1].split("(")[0].strip()
                update_law_stats(law_name, w_code == pred_code)

        kb = [[InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last"), InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
        await query.edit_message_text(f"✅ تم التسجيل: {WINNER_NAMES[w_code]}\n📥 أرسل الرقم التالي لـ ({suit} {rank}):", reply_markup=InlineKeyboardMarkup(kb))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # 🌟 الإصلاح السحري: يقبل أي شيء ويستخرج الأرقام فقط!
    clean_text = clean_digits(text)
    
    if clean_text:
        suit = context.user_data.get('suit')
        rank = context.user_data.get('rank')
        
        if not suit or not rank:
            await update.message.reply_text("⚠️ **يجب اختيار البذلة والورقة أولاً من القائمة!**")
            return
            
        pred_code, reason = predict_3_layer(clean_text, suit, rank)
        
        context.user_data['last_b_num'] = clean_text
        context.user_data['last_suit'] = suit
        context.user_data['last_rank'] = rank
        context.user_data['last_pred_code'] = pred_code
        context.user_data['last_law'] = reason
        
        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data="save_0"), InlineKeyboardButton("🔵 ثور", callback_data="save_1")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_2")]
        ]
        
        await update.message.reply_text(
            f"🎯 **التوقع (V112)**\n"
            f"🃏 {suit} {rank} | 📥 `{clean_text}`\n\n"
            f"🏆 النتيجة: **{WINNER_NAMES[pred_code]}**\n"
            f"{reason}", 
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("force_learn", force_learn))
    app.add_handler(CommandHandler("download", download_db))  # الأمر الجديد
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 HADES V112 Is Online!")
    app.run_polling()
