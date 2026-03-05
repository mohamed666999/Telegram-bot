"""
HADES TITAN 4.0 - Feature Pattern Mining Architecture
تصميم هندسي متقدم: 4 محركات تحليل، أوزان دقيقة، وتعلم فوري متزامن.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging
from typing import Tuple, List, Dict
from contextlib import contextmanager
from psycopg2.extras import execute_values
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

# أوزان المحركات كما صممتها أنت
WEIGHTS = {'DB': 2.2, 'SUIT': 1.2, 'DIGIT': 1.1, 'MATH': 0.7}

# ==================== 🗄️ إدارة قاعدة البيانات ====================
@contextmanager
def get_db_cursor():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()

def ensure_columns():
    try:
        with get_db_cursor() as (conn, cur):
            # التأكد من جدول التاريخ
            history_updates = ["ALTER TABLE history ADD COLUMN rank VARCHAR(5);", "ALTER TABLE history ADD COLUMN bonus_last_digit INT;", "ALTER TABLE history ADD COLUMN user_id BIGINT;"]
            for q in history_updates:
                cur.execute(f"DO $$ BEGIN {q} EXCEPTION WHEN duplicate_column THEN NULL; END $$;")
            
            # 🌟 الجدول الجديد الاحترافي للإحصائيات 🌟
            cur.execute("""CREATE TABLE IF NOT EXISTS pattern_stats (
                pattern_id VARCHAR(50) PRIMARY KEY,
                pattern_type VARCHAR(20),
                red_count INT DEFAULT 0,
                blue_count INT DEFAULT 0,
                tie_count INT DEFAULT 0
            )""")
            conn.commit()
    except: pass

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

# ==================== 🧠 محرك التوقع المعماري TITAN 4.0 ====================
def get_pattern_stats(pattern_id: str) -> Dict[int, float]:
    """يجلب نسبة فوز كل طرف لهذا النمط المحدد"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT red_count, blue_count, tie_count FROM pattern_stats WHERE pattern_id = %s", (pattern_id,))
            row = cur.fetchone()
            if row:
                red, blue, tie = row
                total = red + blue + tie
                if total > 0:
                    return {0: red/total, 1: blue/total, 2: tie/total, 'total': total}
    except: pass
    return {0: 0.0, 1: 0.0, 2: 0.0, 'total': 0}

def predict_titan_4(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])
    
    votes = {0: 0.0, 1: 0.0, 2: 0.0}
    logs = []
    
    # 1️⃣ DB Pattern Engine (بذلة + ورقة + رقم)
    exact_id = f"EXACT_{suit}_{rank}_{last_digit}"
    exact_stats = get_pattern_stats(exact_id)
    if exact_stats['total'] > 0:
        for w in [0, 1]: votes[w] += exact_stats[w] * WEIGHTS['DB']
        best_exact = max([0, 1], key=lambda k: exact_stats[k])
        logs.append(f"🎯 <b>نمط دقيق:</b> {WINNER_NAMES[best_exact]} ({exact_stats[best_exact]*100:.0f}%)")

    # 2️⃣ Suit Engine (بذلة فقط)
    suit_id = f"SUIT_{suit}"
    suit_stats = get_pattern_stats(suit_id)
    if suit_stats['total'] > 0:
        for w in [0, 1]: votes[w] += suit_stats[w] * WEIGHTS['SUIT']
        best_suit = max([0, 1], key=lambda k: suit_stats[k])
        logs.append(f"🎴 <b>نمط البذلة:</b> {WINNER_NAMES[best_suit]} ({suit_stats[best_suit]*100:.0f}%)")

    # 3️⃣ Digit Engine (الرقم الأخير فقط)
    digit_id = f"DIGIT_{last_digit}"
    digit_stats = get_pattern_stats(digit_id)
    if digit_stats['total'] > 0:
        for w in [0, 1]: votes[w] += digit_stats[w] * WEIGHTS['DIGIT']
        best_digit = max([0, 1], key=lambda k: digit_stats[k])
        logs.append(f"🔢 <b>نمط الرقم:</b> {WINNER_NAMES[best_digit]} ({digit_stats[best_digit]*100:.0f}%)")

    # 4️⃣ Math Engine (المعادلة الرياضية للورقة)
    padded_b = clean_b.zfill(3)
    last_digits_sum = sum(int(d) for d in padded_b[-3:])
    card_val = RANK_VALUE.get(str(rank).strip().upper(), 0)
    math_res = ((last_digits_sum * card_val) + last_digit) % 2
    votes[math_res] += 1.0 * WEIGHTS['MATH']
    logs.append(f"🧮 <b>المحرك الرياضي:</b> {WINNER_NAMES[math_res]}")

    # ================= حساب النتيجة النهائية =================
    final_pred = max([0, 1], key=lambda k: votes[k])
    
    # حساب نسبة الثقة بناءً على مجموع النقاط المحتملة
    total_vote_score = votes[0] + votes[1]
    if total_vote_score > 0:
        confidence = int((votes[final_pred] / total_vote_score) * 100)
        # رفع الثقة قليلاً لتبدو منطقية (لأنها نسب مئوية مضروبة في أوزان)
        confidence = min(99, max(50, confidence))
    else:
        confidence = 50

    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

# ==================== 🛠️ التعليم الفوري والمستمر ====================
def live_train_pattern(b_num: str, suit: str, rank: str, winner_code: int):
    """هذه الدالة تعمل فوراً بعد ضغطك على الزر ليتعلم البوت خصائص الجولة"""
    last_digit = int(clean_digits(b_num)[-1])
    
    patterns = [
        (f"EXACT_{suit}_{rank}_{last_digit}", "EXACT"),
        (f"SUIT_{suit}", "SUIT"),
        (f"DIGIT_{last_digit}", "DIGIT")
    ]
    
    col_to_update = "red_count" if winner_code == 0 else "blue_count" if winner_code == 1 else "tie_count"
    
    try:
        with get_db_cursor() as (conn, cur):
            for pid, ptype in patterns:
                cur.execute(f"""
                    INSERT INTO pattern_stats (pattern_id, pattern_type, {col_to_update})
                    VALUES (%s, %s, 1)
                    ON CONFLICT (pattern_id) DO UPDATE 
                    SET {col_to_update} = pattern_stats.{col_to_update} + 1
                """, (pid, ptype))
            conn.commit()
    except Exception as e:
        logger.error(f"Live Train Error: {e}")

# ==================== 🚀 التعلم العميق لقاعدة البيانات (Force Learn) ====================
async def force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يسحب الـ 1800 جولة، ويفككها إلى Features ويحفظها بالجدول الجديد بضربة واحدة"""
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🧠 جاري تشغيل خوارزمية Feature Pattern Mining...")
    
    try:
        with get_db_cursor() as (conn, cur):
            df = pd.read_sql("SELECT suit, rank, bonus_last_digit, b_num, winner FROM history WHERE winner IS NOT NULL", conn)
            
        df['clean_b'] = df['b_num'].astype(str).apply(clean_digits)
        df = df[df['clean_b'] != ""]
        df['calc_last_digit'] = df['clean_b'].str[-1]
        df['final_digit'] = df['bonus_last_digit'].fillna(df['calc_last_digit'])
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'final_digit', 'suit'])
        
        # تجميع الإحصائيات في قاموس في الذاكرة أولاً للسرعة
        stats = {}
        
        for _, row in df.iterrows():
            w = row['winner_code']
            if w not in [0, 1, 2]: continue
            
            pats = [
                (f"SUIT_{row['suit']}", "SUIT"),
                (f"DIGIT_{row['final_digit']}", "DIGIT")
            ]
            if pd.notna(row['rank']):
                pats.append((f"EXACT_{row['suit']}_{row['rank']}_{row['final_digit']}", "EXACT"))
                
            for pid, ptype in pats:
                if pid not in stats:
                    stats[pid] = {'type': ptype, 0:0, 1:0, 2:0}
                stats[pid][w] += 1
                
        # تحويل القاموس إلى قائمة للـ Bulk Upsert
        data_to_insert = []
        for pid, v in stats.items():
            data_to_insert.append((pid, v['type'], v[0], v[1], v[2]))
            
        if data_to_insert:
            insert_query = """
                INSERT INTO pattern_stats (pattern_id, pattern_type, red_count, blue_count, tie_count)
                VALUES %s
                ON CONFLICT (pattern_id) DO UPDATE 
                SET red_count = EXCLUDED.red_count, blue_count = EXCLUDED.blue_count, tie_count = EXCLUDED.tie_count
            """
            with get_db_cursor() as (conn, cur):
                cur.execute("TRUNCATE TABLE pattern_stats;") # مسح الجدول القديم للبدء بنظافة
                execute_values(cur, insert_query, data_to_insert)
                conn.commit()
                
        await msg.edit_text(f"✅ **اكتمل بناء العقول! (TITAN 4.0)**\nتم استخراج ومعالجة {len(data_to_insert)} نمط مستقل (Features).")
    except Exception as e:
        await msg.edit_text(f"❌ حدث خطأ: {e}")

# ==================== 🎮 الواجهة الأساسية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🏛️ HADES TITAN 4.0</b>\n\nنظام (Feature Pattern Mining) جاهز.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    try:
        if data == "choose_suit":
            context.user_data.pop('suit', None)
            context.user_data.pop('rank', None)
            kb = [[InlineKeyboardButton(s, callback_data=f"suit_{s}") for s in SUITS]]
            await query.edit_message_text("🎴 <b>اختر البذلة:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
        elif data.startswith("suit_"):
            suit = data.split("_")[1]
            context.user_data['suit'] = suit
            kb = [[InlineKeyboardButton(r, callback_data=f"rank_{r}") for r in row] for row in RANKS_LAYOUT]
            kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="choose_suit")])
            await query.edit_message_text(f"✅ البذلة: <b>{suit}</b>\n🃏 <b>اختر الورقة:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

        elif data.startswith("rank_"):
            rank = data.split("_")[1]
            context.user_data['rank'] = rank
            suit = context.user_data.get('suit', '')
            kb = [[InlineKeyboardButton("🔄 تغيير الاختيار", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ جاهز: <b>{suit} {rank}</b>\n\n📥 <b>أرسل رقم البونص الآن:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

        elif data == "delete_last":
            # في حال الحذف، نحذف من التاريخ فقط (تبسيطاً للعمليات)
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute("DELETE FROM history WHERE id = (SELECT max(id) FROM history WHERE user_id = %s)", (update.effective_user.id,))
                    conn.commit()
            except: pass
            
            suit = context.user_data.get('suit')
            rank = context.user_data.get('rank')
            if suit and rank:
                kb = [[InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
                await query.edit_message_text(f"🗑️ تم حذف الجولة الخاطئة.\n\nمستمرون مع: <b>{suit} {rank}</b>\n📥 أرسل الرقم الصحيح:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            else:
                kb = [[InlineKeyboardButton("🎴 اختيار", callback_data="choose_suit")]]
                await query.edit_message_text("🗑️ تم الحذف.", reply_markup=InlineKeyboardMarkup(kb))

        elif data.startswith("save_"):
            w_code = int(data.split("_")[1])
            b_num = context.user_data.get('last_b_num')
            suit = context.user_data.get('last_suit')
            rank = context.user_data.get('last_rank')
            
            if b_num and suit and rank:
                last_digit = int(clean_digits(b_num)[-1])
                try:
                    with get_db_cursor() as (conn, cur):
                        cur.execute("""INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id) 
                                       VALUES (%s, %s, %s, %s, %s, %s)""",
                                    (b_num, suit, rank, last_digit, WINNER_NAMES[w_code], update.effective_user.id))
                        conn.commit()
                    
                    # 🔥 التعليم اللحظي لمحركات البوت
                    live_train_pattern(b_num, suit, rank, w_code)
                except: pass

            kb = [
                [InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")],
                [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]
            ]
            await query.edit_message_text(f"✅ تم التسجيل وتعليم الميزات: <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
    except Exception as e:
        logger.error(f"Callback Error: {e}")
        await query.edit_message_text("❌ حدث خطأ، ارسل /start")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        clean_text = clean_digits(text)
        
        if clean_text:
            suit = context.user_data.get('suit')
            rank = context.user_data.get('rank')
            
            if not suit or not rank:
                kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
                await update.message.reply_text("⚠️ <b>يجب اختيار البذلة والورقة أولاً!</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                return
                
            pred_code, confidence, reason = predict_titan_4(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            context.user_data['last_pred_code'] = pred_code
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير TITAN 4.0</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>التوقع: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 محركات التحليل:</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز لتسجيل النتيجة:"""
            
            await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")
        await update.message.reply_text(f"⚠️ خطأ في المعالجة: {str(e)}")

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("force_learn", force_learn))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 HADES TITAN 4.0 Is Online!")
    app.run_polling(drop_pending_updates=True)
