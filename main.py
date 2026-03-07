"""
HADES V16 - THE NEURAL HYBRID (GPT-5.2 + Bayesian Engine)
تم تعديل الموديل إلى gpt-5.2 وفقاً للصورة المرفوعة.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging
from typing import Tuple, Dict, Optional, List
from contextlib import contextmanager
from psycopg2.extras import execute_values
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== 🛡️ الإعدادات ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s" 
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

# 🌟 إعدادات الذكاء الاصطناعي (تم تصحيحها بناءً على الكود الخاص بك) 🌟
AI_API_KEY = "acv-d8351cddde4fbd194ee91aa7442600cd54b961bd1fe39fcf898831db50b3892b"
AI_BASE_URL = "https://www.aichixia.xyz/api/v1"  # تم التصحيح
AI_MODEL = "gpt-5.2"  # تم التعديل حسب الصورة

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2, 0: 0, 1: 1, 2: 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]
RANK_VALUE = {"A":14, "K":13, "Q":12, "J":11, "10":10, "9":9, "8":8, "7":7, "6":6, "5":5, "4":4, "3":3, "2":2}

# أوزان الدمج
WEIGHTS = {'GPT': 2.5, 'SD': 2.8, 'SUIT': 1.8, 'DIGIT': 1.2, 'MOMENTUM': 1.5}

# ==================== 🗄️ إدارة قاعدة البيانات ====================
@contextmanager
def get_db_cursor():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
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

# ==================== 🤖 محرك GPT-5.2 ====================
class CustomAIEngine:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL, timeout=5.0)

    async def get_prediction(self, recent_history: list) -> Tuple[Optional[int], float, str]:
        if len(recent_history) < 3: return None, 0.0, "بيانات غير كافية"
        
        prompt = f"""
        Analyze casino sequence (0=Red, 1=Blue): {recent_history}.
        Will the trend continue or revert to mean?
        Reply ONLY in pure JSON: {{"winner": 0 or 1, "confidence": 50-95, "reason": "Arabic short reason"}}
        """
        try:
            response = await self.client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=100
            )
            content = response.choices[0].message.content.replace('```json', '').replace('```', '').strip()
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return int(data.get("winner", 2)), float(data.get("confidence", 50)), data.get("reason", "تحليل السلسلة")
        except Exception as e:
            logger.error(f"AI API Error: {e}")
            return None, 0.0, f"فشل الاتصال: {str(e)[:30]}"
        return None, 0.0, "خطأ في قراءة الرد"

gpt_engine = CustomAIEngine()

# ==================== 📊 محرك الإحصائيات (Bayesian V16) ====================
def fetch_all_patterns(pattern_ids: List[str]) -> Dict[str, dict]:
    results = {pid: {'w': 2, 'c': 0.0, 'log': '[No Data]'} for pid in pattern_ids}
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT pattern_id, red_count, blue_count FROM pattern_stats WHERE pattern_id = ANY(%s)", (pattern_ids,))
            rows = cur.fetchall()
            for pid, red, blue in rows:
                total = red + blue
                if total == 0: continue
                smoothed_red, smoothed_blue = red + 2, blue + 2
                smoothed_total = smoothed_red + smoothed_blue
                p_red, p_blue = smoothed_red / smoothed_total, smoothed_blue / smoothed_total
                
                winner = 0 if p_red > p_blue else 1
                conf_penalty = 1.0 if total >= 5 else (total / 5.0)
                confidence = max(p_red, p_blue) * conf_penalty
                results[pid] = {'w': winner, 'c': confidence, 'log': f"[{int(red)}🔴:{int(blue)}🔵]"}
    except: pass
    return results

def detect_streak_breaker() -> Tuple[Optional[int], float, str]:
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner, timestamp FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 4")
            rows = cur.fetchall()
            if len(rows) < 3: return None, 0.0, ""
            
            time_diff = (rows[0][1] - rows[2][1]).total_seconds()
            if time_diff > 300: return None, 0.0, "" 
            
            recent = [WINNER_MAP.get(r[0], 2) for r in rows[:3]]
            if recent == [0, 0, 0]: return 1, 0.90, "⚠️ كسر السلسلة (توقع الثور)"
            elif recent == [1, 1, 1]: return 0, 0.90, "⚠️ كسر السلسلة (توقع الراعي)"
    except: pass
    return None, 0.0, ""

# ==================== 🧠 دمج العقول (The Neural Hybrid) ====================
async def predict_hybrid_v16(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])
    
    logs = []
    scores = {0: 0.0, 1: 0.0}
    
    # 1. الذكاء الاصطناعي (GPT-5.2)
    recent_history = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 15")
            recent_history = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
            recent_history.reverse()
    except: pass

    gpt_pred, gpt_conf, gpt_log = await gpt_engine.get_prediction(recent_history)
    if gpt_pred in [0, 1]:
        scores[gpt_pred] += (gpt_conf / 100) * WEIGHTS['GPT']
        logs.append(f"🤖 **GPT-5.2:** {WINNER_NAMES[gpt_pred]} ({gpt_log})")
    else:
        logs.append(f"⚠️ **حالة GPT:** {gpt_log}")

    # 2. الزخم (Momentum)
    streak_pred, streak_conf, streak_log = detect_streak_breaker()
    if streak_pred is not None:
        scores[streak_pred] += streak_conf * WEIGHTS['MOMENTUM']
        logs.append(f"⏱️ **الزخم:** {WINNER_NAMES[streak_pred]} ({streak_log})")

    # 3. الأنماط الإحصائية (DB Patterns)
    p_sd, p_suit, p_digit = f"SD_{suit}_{last_digit}", f"SUIT_{suit}", f"DIGIT_{last_digit}"
    patterns = fetch_all_patterns([p_sd, p_suit, p_digit])
    
    logic_map = [('SD', p_sd, '✨ نمط (بذلة+رقم)'), ('SUIT', p_suit, '🎴 نمط البذلة'), ('DIGIT', p_digit, '🔢 نمط الرقم')]
    
    for weight_key, pid, desc in logic_map:
        res = patterns[pid]
        if res['w'] != 2 and res['c'] > 0.0: 
            scores[res['w']] += res['c'] * WEIGHTS[weight_key]
            logs.append(f"{desc}: {WINNER_NAMES[res['w']]} {res['log']}")

    # ================= החישוב הסופי =================
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    if total_score == 0:
        padded_b = clean_b.zfill(3) 
        math_res = ((sum(int(d) for d in padded_b[-3:]) * RANK_VALUE.get(str(rank).strip().upper(), 0)) + last_digit) % 2
        return math_res, 60, "🧮 **تحليل رياضي احتياطي**\n" + "\n".join(logs)
        
    raw_conf = (scores[final_pred] / total_score) * 100
    confidence = int(min(99, max(50, raw_conf)))
    
    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

# ==================== 🎮 الواجهة والتحديث الحي ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🏛️ HADES V16 (Neural Hybrid)</b>\nدمج GPT-5.2 مع الإحصائيات.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

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
            b_num = context.user_data.get('last_b_num', '00000')
            suit = context.user_data.get('last_suit', '♦️')
            rank = context.user_data.get('last_rank', 'A')
            
            if b_num and suit and rank:
                last_digit = int(clean_digits(b_num)[-1]) 
                try:
                    with get_db_cursor() as (conn, cur):
                        cur.execute("""INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id) 
                                       VALUES (%s, %s, %s, %s, %s, %s)""",
                                    (b_num, suit, rank, last_digit, WINNER_NAMES[w_code], update.effective_user.id))
                        
                        col = "red_count" if w_code == 0 else "blue_count" if w_code == 1 else "tie_count"
                        for pid in [f"SD_{suit}_{last_digit}", f"SUIT_{suit}", f"DIGIT_{last_digit}"]:
                            cur.execute(f"""INSERT INTO pattern_stats (pattern_id, {col}) VALUES (%s, 1) 
                                            ON CONFLICT (pattern_id) DO UPDATE SET {col} = pattern_stats.{col} + 1""", (pid,))
                        conn.commit()
                except Exception as e: logger.error(f"Live Save Error: {e}")

            kb = [[InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")], [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ تم التسجيل: <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
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
            
            processing_msg = await update.message.reply_text("⏳ <b>يتم استشارة الإحصائيات و GPT-5.2...</b>", parse_mode='HTML')
            
            pred_code, confidence, reason = await predict_hybrid_v16(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير V16 (الدمج العصبي)</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>التوقع: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 محركات التحليل:</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز الفعلي لتسجيل النتيجة:"""
            
            await processing_msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 HADES V16 RUNNING...")
    app.run_polling(drop_pending_updates=True)
