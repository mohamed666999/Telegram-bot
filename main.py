"""
HADES V111 - The Quantum Update (Rank Analytics & DB Indexing)
الميزات: فصل الورقة (Rank)، فهرسة آخر رقم، لوحة إدخال ثلاثية، وتحديث رياضي عميق.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging
from typing import Dict, Tuple, Optional
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

# قيم الأوراق للتحليل الرياضي (كما اقترحت)
RANK_VALUE = {"A":14, "K":13, "Q":12, "J":11, "10":10, "9":9, "8":8, "7":7, "6":6, "5":5, "4":4, "3":3, "2":2}
RANKS_LAYOUT = [
    ["A", "K", "Q", "J"],
    ["10", "9", "8", "7"],
    ["6", "5", "4", "3", "2"]
]

# ==================== 🗄️ إدارة وتحديث قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def ensure_columns():
    """تحديث قاعدة البيانات بذكاء وإضافة الأعمدة الجديدة دون مسح القديم"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # إضافة الأعمدة الجديدة لجدول history (للتوافق مع اقتراحك)
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
        conn.close()
        logger.info("✅ تم تحديث هندسة قاعدة البيانات لـ V111 بنجاح.")
    except Exception as e:
        logger.error(f"DB Error: {e}")

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

# ==================== 🧠 المحرك الرياضي والتحليلي الجديد ====================
def predict_quantum(b_num: str, suit: str, rank: str) -> Tuple[int, str]:
    """توقع باستخدام البذلة، الورقة، والرقم الأخير"""
    clean_b = clean_digits(b_num)
    if len(clean_b) < 1: return 2, "❌ رقم غير صالح"
    
    last_digit = int(clean_b[-1])
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1️⃣ البحث عن قانون معقد (بذلة + ورقة + آخر رقم) - أقوى مستوى دقة
    cur.execute("""
        SELECT law_name, success_count, fail_count, law_pattern->>'winner' 
        FROM ai_laws 
        WHERE law_name = %s AND is_active = TRUE
    """, (f"DB_{suit}_{rank}_{last_digit}",))
    row = cur.fetchone()
    
    if not row:
        # 2️⃣ البحث عن قانون (بذلة + آخر رقم فقط) - في حال لم يتوفر قانون للورقة
        cur.execute("""
            SELECT law_name, success_count, fail_count, law_pattern->>'winner' 
            FROM ai_laws 
            WHERE law_name = %s AND is_active = TRUE
        """, (f"DB_{suit}_ALL_{last_digit}",))
        row = cur.fetchone()
        
    conn.close()
    
    if row:
        name, succ, fail, win_code = row
        if succ > fail:
            return int(win_code), f"📜 قانون {name} (✅{succ}|❌{fail})"
            
    # 3️⃣ المحرك الرياضي المعزز بقيمة الورقة (Rank Value)
    last3_sum = sum(int(d) for d in clean_b[-3:])
    card_val = RANK_VALUE.get(rank, 0)
    
    # المعادلة الجديدة: (مجموع آخر 3 أرقام * قيمة الورقة) + الرقم الأخير
    math_result = ((last3_sum * card_val) + last_digit) % 2
    return math_result, f"🧮 تحليل رياضي (الورقة: {card_val})"

def update_law_stats(law_name: str, is_success: bool):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if is_success:
            cur.execute("UPDATE ai_laws SET success_count = success_count + 1 WHERE law_name = %s", (law_name,))
        else:
            cur.execute("UPDATE ai_laws SET fail_count = fail_count + 1 WHERE law_name = %s", (law_name,))
        conn.commit()
        conn.close()
    except: pass

# ==================== 🛠️ أوامر الأدمن للتعلم ====================
async def force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """قراءة التاريخ وبناء قوانين (بذلة + ورقة + رقم)"""
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🧠 جاري معالجة البيانات وبناء القوانين الكمية...")
    
    conn = get_db_connection()
    df = pd.read_sql("SELECT suit, rank, bonus_last_digit, b_num, winner FROM history WHERE winner IS NOT NULL", conn)
    
    # استخراج البيانات المفقودة للبيانات القديمة
    df['clean_b'] = df['b_num'].astype(str).apply(clean_digits)
    df['calc_last_digit'] = df['clean_b'].str[-1]
    df['final_digit'] = df['bonus_last_digit'].fillna(df['calc_last_digit'])
    
    df['winner_code'] = df['winner'].map(WINNER_MAP)
    df = df.dropna(subset=['winner_code', 'final_digit', 'suit'])
    
    cur = conn.cursor()
    laws_added = 0
    
    # 1. بناء قوانين شاملة (بذلة + رقم) - للبيانات القديمة التي لا تملك Rank
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

    # 2. بناء قوانين دقيقة (بذلة + ورقة + رقم) - للبيانات الجديدة
    df_rank = df.dropna(subset=['rank'])
    if not df_rank.empty:
        grp_rank = df_rank.groupby(['suit', 'rank', 'final_digit'])['winner_code'].value_counts().unstack(fill_value=0)
        for (suit, rank, digit), row in grp_rank.iterrows():
            best_winner = row.idxmax()
            succ, fail = row[best_winner], row.drop(best_winner).sum()
            if succ >= 3 and succ > fail: # نحتاج 3 تكرارات فقط للقوانين الدقيقة
                l_name = f"DB_{suit}_{rank}_{digit}"
                pat = {"suit": suit, "rank": rank, "last_digit": str(digit), "winner": int(best_winner)}
                cur.execute("""INSERT INTO ai_laws (law_name, law_pattern, success_count, fail_count) 
                               VALUES (%s, %s, %s, %s) ON CONFLICT (law_name) DO UPDATE 
                               SET success_count=EXCLUDED.success_count, fail_count=EXCLUDED.fail_count""",
                               (l_name, json.dumps(pat), int(succ), int(fail)))
                laws_added += 1

    cur.execute("DELETE FROM ai_laws WHERE fail_count > success_count")
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    
    await msg.edit_text(f"✅ **تم التدريب (V111)**\n➕ قوانين مبنية: {laws_added}\n🗑️ قوانين محذوفة: {deleted}")

# ==================== 🎮 واجهة المستخدم ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("🏛️ **HADES V111 - The Quantum Engine**\n\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

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
        # بناء لوحة الأوراق بناءً على الترتيب
        kb = []
        for row in RANKS_LAYOUT:
            kb.append([InlineKeyboardButton(r, callback_data=f"rank_{r}") for r in row])
        kb.append([InlineKeyboardButton("🔙 رجوع للبذلات", callback_data="choose_suit")])
        
        await query.edit_message_text(f"✅ البذلة: **{suit}**\n🃏 **اختر الورقة المسحوبة:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith("rank_"):
        rank = data.split("_")[1]
        context.user_data['rank'] = rank
        suit = context.user_data.get('suit', 'غير معروف')
        
        kb = [[InlineKeyboardButton("🔄 تغيير الورقة/البذلة", callback_data="choose_suit")]]
        await query.edit_message_text(f"✅ تم الاختيار: **{suit} {rank}**\n\n📥 **أرسل الآن رقم البونص:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith("save_"):
        w_code = int(data.split("_")[1])
        b_num = context.user_data.get('last_b_num')
        suit = context.user_data.get('last_suit')
        rank = context.user_data.get('last_rank')
        law_used = context.user_data.get('last_law')
        pred_code = context.user_data.get('last_pred_code')
        
        if b_num and suit and rank:
            last_digit = int(clean_digits(b_num)[-1])
            conn = get_db_connection()
            cur = conn.cursor()
            # الحفظ الشامل (مع Rank و Bonus_last_digit)
            cur.execute("""INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id) 
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (b_num, suit, rank, last_digit, WINNER_NAMES[w_code], update.effective_user.id))
            conn.commit()
            conn.close()
            
            # تدريب القانون إذا تم استخدامه
            if law_used and "قانون" in law_used:
                law_name = law_used.split(" ")[1] # استخراج اسم القانون من النص
                update_law_stats(law_name, w_code == pred_code)

        # تجهيز الأزرار للجولة القادمة
        kb = [[InlineKeyboardButton("🃏 تغيير الورقة", callback_data=f"suit_{suit}"), 
               InlineKeyboardButton("🎴 تغيير البذلة", callback_data="choose_suit")]]
               
        await query.edit_message_text(f"✅ تم تسجيل: {WINNER_NAMES[w_code]}\n\n📥 لـ ({suit} {rank}) أرسل الرقم التالي، أو غير الاختيار:", reply_markup=InlineKeyboardMarkup(kb))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    clean_text = clean_digits(text)
    
    if len(clean_text) >= 3:
        suit = context.user_data.get('suit')
        rank = context.user_data.get('rank')
        
        if not suit or not rank:
            await update.message.reply_text("⚠️ **يجب اختيار البذلة والورقة أولاً من القائمة!**")
            return
            
        pred_code, reason = predict_quantum(clean_text, suit, rank)
        
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
            f"🎯 **التوقع (V111)**\n"
            f"🃏 الورقة: {suit} {rank} | 📥 البونص: `{clean_text}`\n\n"
            f"🏆 النتيجة: **{WINNER_NAMES[pred_code]}**\n"
            f"⚙️ {reason}", 
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )

# ==================== 🎬 التشغيل ====================
if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("force_learn", force_learn))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 HADES V111 Quantum Engine Is Online!")
    app.run_polling()
