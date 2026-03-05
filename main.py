"""
HADES TITAN 9.0 - The Singularity Node (Data Science Masterpiece)
تم إعداده بناءً على التحليل الإحصائي العميق (2500+ جولة).
الاعتماد الكلي على نمط (Suit + Digit) الذهبي، والتنعيم البايزي ضد الأنماط النادرة.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging
from typing import Tuple, Dict, List, Optional
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

# ⚡ الأوزان المعمارية المهندسة بناءً على تقرير البيانات ⚡
WEIGHTS = {
    'SD': 2.8,       # 🌟 النمط الأسطوري (Suit + Digit) - الأعلى وزناً
    'SUIT': 1.8,     # انحياز حقيقي وموثوق
    'DIGIT': 1.2,    # انحياز حقيقي
    'MOMENTUM': 1.1, # كاسر السلاسل (يعمل بقوة عند التكرار)
    'RANK': 0.4,     # ضعيف جداً إحصائياً
    'EXACT': 0.2     # شبه ملغي (وهم إحصائي بسبب قلة التكرار)
}

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
            cur.execute("""CREATE TABLE IF NOT EXISTS history(
                id SERIAL PRIMARY KEY, b_num TEXT, suit TEXT, rank TEXT,
                bonus_last_digit INT, winner TEXT, user_id BIGINT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            
            cur.execute("""CREATE TABLE IF NOT EXISTS pattern_stats (
                pattern_id VARCHAR(50) PRIMARY KEY, pattern_type VARCHAR(20),
                red_count FLOAT DEFAULT 0, blue_count FLOAT DEFAULT 0, tie_count FLOAT DEFAULT 0)""")
            conn.commit()
    except Exception as e:
        logger.error(f"DB Init Error: {e}")

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

# ==================== 📊 Smart Bayesian Engine (V9.0) ====================
def fetch_all_patterns(pattern_ids: List[str]) -> Dict[str, dict]:
    """ 🚀 استعلام فائق السرعة مع التنعيم البايزي لمعالجة الأنماط النادرة """
    results = {pid: {'w': 2, 'c': 0.0, 'log': '[No Data]'} for pid in pattern_ids}
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT pattern_id, red_count, blue_count FROM pattern_stats WHERE pattern_id = ANY(%s)", (pattern_ids,))
            rows = cur.fetchall()
            
            for pid, red, blue in rows:
                total = red + blue
                # Laplace Smoothing الذكي: 
                # إذا كان العدد أقل من 4، لا نثق به كثيراً فنعطيه ثقة تقترب من 50%
                if total == 0: continue
                
                smoothed_red = red + 2
                smoothed_blue = blue + 2
                smoothed_total = smoothed_red + smoothed_blue
                
                p_red = smoothed_red / smoothed_total
                p_blue = smoothed_blue / smoothed_total
                
                winner = 0 if p_red > p_blue else 1
                
                # تخفيض الثقة للأنماط التي لم تتكرر كثيراً (مثل EXACT)
                confidence_penalty = 1.0 if total >= 5 else (total / 5.0)
                confidence = max(p_red, p_blue) * confidence_penalty
                
                results[pid] = {'w': winner, 'c': confidence, 'log': f"[{int(red)}🔴:{int(blue)}🔵]"}
    except Exception as e:
        logger.error(f"Fast Query Error: {e}")
    return results

# ==================== 🔐 Momentum & Drift Detection ====================
def detect_streak_breaker() -> Tuple[Optional[int], float, str]:
    """ يعمل ككاسر أمواج (Anti-Streak) بناءً على المتوسط الإحصائي 2.1 للعبة """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner, timestamp FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 4")
            rows = cur.fetchall()
            if len(rows) < 3: return None, 0.0, ""
            
            time_diff = (rows[0][1] - rows[2][1]).total_seconds()
            if time_diff > 180: return None, 0.0, "" # جولات متقطعة = لا تحسب التسلسل
            
            recent = [WINNER_MAP.get(r[0], 2) for r in rows[:3]]
            
            if recent == [0, 0, 0]:
                return 1, 0.90, "⚠️ كسر السلسلة (3 راعي متتالية)"
            elif recent == [1, 1, 1]:
                return 0, 0.90, "⚠️ كسر السلسلة (3 ثور متتالية)"
    except: pass
    return None, 0.0, ""

# ==================== 🧠 TITAN 9.0 Core Engine ====================
def predict_titan_9(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    
    last_digit = int(clean_b[-1])
    
    # تعريف الـ 5 أنماط الرئيسية
    p_sd    = f"SD_{suit}_{last_digit}" 
    p_suit  = f"SUIT_{suit}"
    p_digit = f"DIGIT_{last_digit}"
    p_rank  = f"RANK_{rank}"
    p_exact = f"EXACT_{suit}_{rank}_{last_digit}"
    
    patterns = fetch_all_patterns([p_sd, p_suit, p_digit, p_rank, p_exact])
    
    scores = {0: 0.0, 1: 0.0}
    logs = []
    
    streak_pred, streak_conf, streak_log = detect_streak_breaker()
    if streak_pred is not None:
        scores[streak_pred] += streak_conf * WEIGHTS['MOMENTUM']
        logs.append(f"⏱️ **الزخم:** {WINNER_NAMES[streak_pred]} ({streak_log})")

    # الترتيب حسب قوة الوزن لطباعتها بشكل جميل للمستخدم
    logic_map = [
        ('SD', p_sd, '✨ بذلة+رقم (الذهبي)'),
        ('SUIT', p_suit, '🎴 البذلة'),
        ('DIGIT', p_digit, '🔢 الرقم'),
        ('RANK', p_rank, '🃏 الورقة')
    ]
    
    for weight_key, pid, desc in logic_map:
        res = patterns[pid]
        if res['w'] != 2 and res['c'] > 0.0: 
            # نضرب احتمال النمط في الوزن الخاص به المعرف في الأعلى
            scores[res['w']] += res['c'] * WEIGHTS[weight_key]
            logs.append(f"{desc}: {WINNER_NAMES[res['w']]} {res['log']}")

    # ==================== حساب القرار النهائي ====================
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    if total_score == 0:
        # المحرك الرياضي (Fallback) في حالة نادرة جداً
        padded_b = clean_b.zfill(3) 
        last_digits_sum = sum(int(d) for d in padded_b[-3:])
        card_val = RANK_VALUE.get(str(rank).strip().upper(), 0)
        math_res = ((last_digits_sum * card_val) + last_digit) % 2
        return math_res, 60, f"🧮 **تحليل رياضي احتياطي**"
        
    raw_conf = (scores[final_pred] / total_score) * 100
    confidence = int(min(99, max(50, raw_conf)))
    
    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

# ==================== 🚀 Fast Bulk Learning (Pandas Fix) ====================
async def force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🧠 جاري تشغيل خوارزميات TITAN 9.0...")
    try:
        with get_db_cursor() as (conn, cur):
            df = pd.read_sql("SELECT suit, rank, bonus_last_digit, b_num, winner FROM history WHERE winner IS NOT NULL", conn)
            
        df['clean_b'] = df['b_num'].astype(str).apply(clean_digits)
        df = df[df['clean_b'] != ""]
        
        # 🌟 إصلاح الـ Float (7.0 vs 7) 🌟
        df['final_digit'] = df['bonus_last_digit'].fillna(df['clean_b'].str[-1])
        df['final_digit'] = pd.to_numeric(df['final_digit'], errors='coerce').fillna(0).astype(int)
        
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'final_digit', 'suit'])
        
        stats = {}
        for _, row in df.iterrows():
            w = row['winner_code']
            if w not in [0, 1, 2]: continue
            
            s = row['suit']
            d = row['final_digit'] 
            r = row['rank'] if pd.notna(row['rank']) else ""
            
            pats = [
                (f"SUIT_{s}", "SUIT"),
                (f"DIGIT_{d}", "DIGIT"),
                (f"SD_{s}_{d}", "SD") 
            ]
            if r:
                pats.append((f"RANK_{r}", "RANK"))
                pats.append((f"EXACT_{s}_{r}_{d}", "EXACT"))
                
            for pid, ptype in pats:
                if pid not in stats: stats[pid] = {'type': ptype, 0:0, 1:0, 2:0}
                stats[pid][w] += 1
                
        data_to_insert = [(pid, v['type'], v[0], v[1], v[2]) for pid, v in stats.items()]
            
        if data_to_insert:
            insert_query = """INSERT INTO pattern_stats (pattern_id, pattern_type, red_count, blue_count, tie_count)
                              VALUES %s ON CONFLICT (pattern_id) DO UPDATE 
                              SET red_count=EXCLUDED.red_count, blue_count=EXCLUDED.blue_count, tie_count=EXCLUDED.tie_count"""
            with get_db_cursor() as (conn, cur):
                cur.execute("TRUNCATE TABLE pattern_stats;") 
                execute_values(cur, insert_query, data_to_insert)
                conn.commit()
                
        await msg.edit_text(f"✅ **اكتمل التدريب (TITAN 9.0)**\nتم ضخ {len(data_to_insert)} نمط. (التركيز على النمط الذهبي SD).")
    except Exception as e:
        await msg.edit_text(f"❌ حدث خطأ: {e}")

async def download_db_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    message = update.message if update.message else update.callback_query.message
    msg = await message.reply_text("⏳ جاري سحب قاعدة البيانات...")
    
    try:
        with get_db_cursor() as (conn, cur):
            df_history = pd.read_sql("SELECT * FROM history ORDER BY id DESC LIMIT 5000", conn)
            df_patterns = pd.read_sql("SELECT * FROM pattern_stats ORDER BY (red_count + blue_count) DESC", conn)
            
        filename = f"hades_db_v9_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write("=== HADES TITAN 9.0 DB BACKUP ===\n\n--- PATTERN STATS ---\n")
            df_patterns.to_csv(f, sep='\t', index=False)
            f.write("\n\n--- HISTORY ---\n")
            df_history.to_csv(f, sep='\t', index=False)

        with open(filename, "rb") as f:
            await message.reply_document(document=f, caption="📥 نسخة V9 (Apex Architecture)")
        os.remove(filename)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")

# ==================== 🎮 الواجهة والمراقبة الحية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")],
        [InlineKeyboardButton("📥 تحميل قاعدة البيانات (TXT)", callback_data="download_txt")]
    ]
    await update.message.reply_text("<b>🏛️ HADES TITAN 9.0 (Singularity Node)</b>\n\nنظام التداول المبني على Bayesian Smoothing.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    try:
        if data == "download_txt":
            await download_db_txt(update, context)
            
        elif data == "choose_suit":
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
                        
                        # 🚀 Live Training - Single Fast Query
                        col = "red_count" if w_code == 0 else "blue_count" if w_code == 1 else "tie_count"
                        pats_to_update = [
                            (f"EXACT_{suit}_{rank}_{last_digit}", "EXACT"),
                            (f"SD_{suit}_{last_digit}", "SD"),
                            (f"SUIT_{suit}", "SUIT"),
                            (f"DIGIT_{last_digit}", "DIGIT"),
                            (f"RANK_{rank}", "RANK")
                        ]
                        
                        query_insert = f"""INSERT INTO pattern_stats (pattern_id, pattern_type, {col}) 
                                           VALUES %s ON CONFLICT (pattern_id) DO UPDATE SET {col} = pattern_stats.{col} + 1"""
                        execute_values(cur, query_insert, [(p[0], p[1], 1) for p in pats_to_update])
                        conn.commit()
                except Exception as e: logger.error(f"Live Train Error: {e}")

            kb = [[InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")], [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ تم التسجيل (Live Sync): <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
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
                
            pred_code, confidence, reason = predict_titan_9(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير TITAN 9.0</b>
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

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_db_txt))
    app.add_handler(CommandHandler("force_learn", force_learn))
    
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 HADES TITAN 9.0 RUNNING...")
    app.run_polling(drop_pending_updates=True)
