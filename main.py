"""
HADES TITAN 6.0 - Advanced Bayesian & Caching Architecture
Real Data Science Implementation (No Marketing Jargon).
"""

import os, re, datetime, time, psycopg2, pandas as pd, json, logging
from typing import Tuple, Dict, Optional
from contextlib import contextmanager
from psycopg2.extras import execute_values
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s" # تأكد من تغييره لاحقاً
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2, 0: 0, 1: 1, 2: 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]

# ⚡ Ultra Fast Prediction Cache (In-Memory)
PREDICTION_CACHE = {}
CACHE_TTL = 60 # ثانية

# ==================== 🗄️ إدارة قاعدة البيانات ====================
@contextmanager
def get_db_cursor():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()

def ensure_columns():
    """تهيئة الجداول بشكل كامل وصحيح كما أشرت أنت"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                CREATE TABLE IF NOT EXISTS history(
                    id SERIAL PRIMARY KEY,
                    b_num TEXT,
                    suit TEXT,
                    rank TEXT,
                    bonus_last_digit INT,
                    winner TEXT,
                    user_id BIGINT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pattern_stats (
                    pattern_id VARCHAR(50) PRIMARY KEY, 
                    pattern_type VARCHAR(20),
                    red_count FLOAT DEFAULT 0, 
                    blue_count FLOAT DEFAULT 0, 
                    tie_count FLOAT DEFAULT 0
                )
            """)
            conn.commit()
    except Exception as e:
        logger.error(f"DB Init Error: {e}")

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

# ==================== 📊 Bayesian Probability Engine ====================
def get_bayesian_prob(pattern_id: str) -> Tuple[float, float, str]:
    """
    يحسب الاحتمال باستخدام Laplace Smoothing
    لضمان عدم الحصول على احتمالات صفرية أو القسمة على صفر.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT red_count, blue_count FROM pattern_stats WHERE pattern_id = %s", (pattern_id,))
            row = cur.fetchone()
            if row:
                red, blue = row[0], row[1]
                # Laplace Smoothing (Alpha = 1)
                total = red + blue + 2 
                p_red = (red + 1) / total
                p_blue = (blue + 1) / total
                
                confidence = max(p_red, p_blue) * 100
                winner = 0 if p_red > p_blue else 1
                return winner, confidence, f"[{int(red)}R:{int(blue)}B]"
    except: pass
    return 2, 50.0, "[No Data]"

# ==================== 🔐 Anti-Pattern Detection ====================
def detect_anti_pattern() -> Tuple[Optional[int], float, str]:
    """يكتشف التشبع باستخدام آخر 15 جولة (Mean Reversion)"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 15")
            rows = cur.fetchall()
            if len(rows) < 10: return None, 0.0, ""
            
            recent = [WINNER_MAP.get(r[0], 2) for r in rows]
            red_ratio = recent.count(0) / len(recent)
            blue_ratio = recent.count(1) / len(recent)
            
            if red_ratio > 0.75:
                return 1, 80.0, "⚠️ تشبع شرائي للراعي (Mean Reversion للثور)"
            elif blue_ratio > 0.75:
                return 0, 80.0, "⚠️ تشبع بيعي للثور (Mean Reversion للراعي)"
    except: pass
    return None, 0.0, ""

# ==================== 🧠 TITAN 6.0 Core Engine ====================
def predict_titan_6(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])
    
    # ⚡ نظام الكاش المسرّع (Ultra Fast Cache)
    cache_key = f"{suit}_{rank}_{clean_b}"
    if cache_key in PREDICTION_CACHE:
        cached_time, cached_result = PREDICTION_CACHE[cache_key]
        if time.time() - cached_time < CACHE_TTL:
            return cached_result[0], cached_result[1], cached_result[2] + "\n⚡ *(جُلب من الكاش السريع)*"

    logs = []
    
    # 1. مكافحة الأنماط المفرطة (Anti-pattern)
    anti_pred, anti_conf, anti_desc = detect_anti_pattern()
    if anti_pred is not None:
        logs.append(f"🛡️ **مراقب التشبع:** {WINNER_NAMES[anti_pred]} ({anti_desc})")
    
    # 2. الاحتمالات البايزية (Bayesian Engine)
    exact_w, exact_c, exact_log = get_bayesian_prob(f"EXACT_{suit}_{rank}_{last_digit}")
    suit_w, suit_c, suit_log = get_bayesian_prob(f"SUIT_{suit}")
    
    logs.append(f"📊 **بايز (دقيق):** {WINNER_NAMES[exact_w]} {exact_log} ({exact_c:.1f}%)")
    logs.append(f"📊 **بايز (بذلة):** {WINNER_NAMES[suit_w]} {suit_log} ({suit_c:.1f}%)")
    
    # 3. دمج الأوزان وحساب النتيجة
    scores = {0: 0.0, 1: 0.0}
    if anti_pred is not None: scores[anti_pred] += anti_conf * 1.5
    if exact_w != 2: scores[exact_w] += exact_c * 2.0
    if suit_w != 2: scores[suit_w] += suit_c * 1.0
    
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    if total_score == 0:
        final_pred = 2 # تعادل إحصائي
        confidence = 50
        logs.append("🧮 **لا توجد بيانات كافية (احتمال متساوٍ)**")
    else:
        raw_conf = (scores[final_pred] / total_score) * 100
        confidence = int(min(99, max(50, raw_conf)))
    
    reason_str = "\n".join(logs)
    
    # تحديث الكاش
    PREDICTION_CACHE[cache_key] = (time.time(), (final_pred, confidence, reason_str))
    
    return final_pred, confidence, reason_str

# ==================== 🧬 Adaptive Memory Decay ====================
async def apply_memory_decay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يضرب كل إحصائيات الأنماط في 0.9 لتقليل وزن الماضي البعيد 
    وجعل النظام يتكيف مع التغيرات الحالية للخوارزمية.
    """
    if update.effective_user.id != ADMIN_ID: return
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                UPDATE pattern_stats 
                SET red_count = red_count * 0.9, 
                    blue_count = blue_count * 0.9, 
                    tie_count = tie_count * 0.9
            """)
            conn.commit()
        await update.message.reply_text("🧬 **تم تطبيق Memory Decay!**\nتم تخفيض وزن التاريخ بنسبة 10% للتكيف مع الأنماط الحديثة.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 🚀 Bulk Learning (كما أوضحت أنت سابقاً) ====================
async def force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🧠 جاري التحليل الشامل (Bulk Upsert)...")
    try:
        with get_db_cursor() as (conn, cur):
            df = pd.read_sql("SELECT suit, rank, bonus_last_digit, b_num, winner FROM history WHERE winner IS NOT NULL", conn)
            
        df['clean_b'] = df['b_num'].astype(str).apply(clean_digits)
        df = df[df['clean_b'] != ""]
        df['final_digit'] = df['bonus_last_digit'].fillna(df['clean_b'].str[-1])
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'final_digit', 'suit'])
        
        stats = {}
        for _, row in df.iterrows():
            w = row['winner_code']
            if w not in [0, 1, 2]: continue
            
            pats = [f"SUIT_{row['suit']}", f"DIGIT_{row['final_digit']}"]
            if pd.notna(row['rank']):
                pats.append(f"EXACT_{row['suit']}_{row['rank']}_{row['final_digit']}")
                
            for pid in pats:
                if pid not in stats: stats[pid] = {0:0, 1:0, 2:0}
                stats[pid][w] += 1
                
        data_to_insert = [(pid, pid.split('_')[0], v[0], v[1], v[2]) for pid, v in stats.items()]
            
        if data_to_insert:
            insert_query = """INSERT INTO pattern_stats (pattern_id, pattern_type, red_count, blue_count, tie_count)
                              VALUES %s ON CONFLICT (pattern_id) DO UPDATE 
                              SET red_count=EXCLUDED.red_count, blue_count=EXCLUDED.blue_count, tie_count=EXCLUDED.tie_count"""
            with get_db_cursor() as (conn, cur):
                cur.execute("TRUNCATE TABLE pattern_stats;") 
                execute_values(cur, insert_query, data_to_insert)
                conn.commit()
                
        await msg.edit_text(f"✅ **اكتمل التدريب الشامل! (TITAN 6.0)**\nتم معالجة وضخ {len(data_to_insert)} نمط.")
    except Exception as e:
        await msg.edit_text(f"❌ حدث خطأ: {e}")

# ==================== 🎮 Telegram Interface ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🏛️ HADES TITAN 6.0</b>\n\n- Bayesian Engine\n- Ultra Fast Cache\n- Anti-pattern Detection\n\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    try:
        if data == "choose_suit":
            context.user_data.pop('suit', None); context.user_data.pop('rank', None)
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
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute("DELETE FROM history WHERE id = (SELECT max(id) FROM history WHERE user_id = %s)", (update.effective_user.id,))
                    conn.commit()
            except: pass
            kb = [[InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text(f"🗑️ تم حذف الجولة الخاطئة.\n📥 أرسل الرقم الصحيح:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

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
                        
                        # Live Update for Bayesian Stats
                        col = "red_count" if w_code == 0 else "blue_count" if w_code == 1 else "tie_count"
                        for pid in [f"EXACT_{suit}_{rank}_{last_digit}", f"SUIT_{suit}", f"DIGIT_{last_digit}"]:
                            cur.execute(f"""INSERT INTO pattern_stats (pattern_id, {col}) VALUES (%s, 1) 
                                            ON CONFLICT (pattern_id) DO UPDATE SET {col} = pattern_stats.{col} + 1""", (pid,))
                        conn.commit()
                except Exception as e: logger.error(e)

            kb = [[InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")], [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ تم تسجيل: <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
    except Exception as e:
        logger.error(f"Callback Error: {e}")

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
                
            pred_code, confidence, reason = predict_titan_6(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير TITAN 6.0</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>التوقع: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 محركات التحليل (Bayesian):</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز لتسجيل النتيجة:"""
            
            await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")

# ==================== 🚀 التشغيل الأساسي ====================
if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("force_learn", force_learn))
    app.add_handler(CommandHandler("decay_memory", apply_memory_decay)) # الأمر الجديد 🧬
    
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 HADES TITAN 6.0 RUNNING...")
    app.run_polling(drop_pending_updates=True)
