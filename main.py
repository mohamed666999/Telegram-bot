"""
HADES V13 - THE ANTI-SHIFT ENGINE
الميزات: كاشف انعكاس اللعبة التلقائي (Auto-Inversion)، تبسيط الـ AI Agent، وتحليل الفجوات الزمنية.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging, asyncio
from typing import Tuple, Dict, Optional, List
from contextlib import contextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s" 
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]

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
            
            cur.execute("""CREATE TABLE IF NOT EXISTS agent_laws (
                id SERIAL PRIMARY KEY, suit TEXT, min_gap INT, max_gap INT,
                predicted_winner INT, confidence INT, reason TEXT)""")
            conn.commit()
    except Exception as e:
        logger.error(f"DB Init Error: {e}")

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

# ==================== 🤖 العميل المستقل (Optimized AI Agent) ====================
class AutonomousAgent:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL, timeout=20.0)

    async def analyze_and_create_laws(self, limit=100) -> str:
        """نسخة مبسطة جداً لضمان استجابة نموذج الذكاء الاصطناعي"""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(f"SELECT suit, timestamp, winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT {limit}")
                rows = cur.fetchall()
            
            if len(rows) < 10: return "بيانات غير كافية لتدريب العميل."

            agent_data = []
            rows.reverse()
            for i in range(1, len(rows)):
                suit = rows[i][0]
                time_gap = int((rows[i][1] - rows[i-1][1]).total_seconds())
                winner = WINNER_MAP.get(rows[i][2], 2)
                if time_gap < 120: # نركز فقط على الجولات السريعة المتتالية (أقل من دقيقتين)
                    agent_data.append(f"({suit},{time_gap}s,{winner})")

            prompt = f"""
            Analyze this Casino data format: (Suit, TimeGap_seconds, Winner[0=Red, 1=Blue]).
            Data: {', '.join(agent_data[-60:])}
            
            Task: Give me 2 or 3 rules based on TimeGap. 
            Example: If Gap is between 30 and 40 for ♦️, who wins more?
            
            You MUST reply ONLY with a valid JSON array like this:
            [
              {{"suit": "♦️", "min_gap": 25, "max_gap": 40, "predicted_winner": 1, "confidence": 85, "reason": "Fast gaps favor Blue"}},
              {{"suit": "♠️", "min_gap": 41, "max_gap": 60, "predicted_winner": 0, "confidence": 75, "reason": "Medium gaps favor Red"}}
            ]
            """
            
            response = await self.client.chat.completions.create(
                model=NVIDIA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=300
            )
            
            content = response.choices[0].message.content
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                laws = json.loads(match.group())
                with get_db_cursor() as (conn, cur):
                    cur.execute("TRUNCATE TABLE agent_laws")
                    for law in laws:
                        cur.execute("""INSERT INTO agent_laws (suit, min_gap, max_gap, predicted_winner, confidence, reason) 
                                       VALUES (%s, %s, %s, %s, %s, %s)""",
                                    (law['suit'], law['min_gap'], law['max_gap'], law['predicted_winner'], law['confidence'], law['reason']))
                    conn.commit()
                return f"✅ تم بنجاح! العميل زرع {len(laws)} قوانين زمنية جديدة."
            return "⚠️ الذكاء الاصطناعي لم يجد نمطاً حاسماً."
        except Exception as e:
            return f"❌ خطأ في العميل."

ai_agent = AutonomousAgent()

# ==================== 🔄 كاشف الانعكاس الحي (Auto-Inversion) ====================
def detect_regime_shift() -> Tuple[bool, str]:
    """
    يقرأ آخر 6 جولات من قاعدة البيانات. إذا رأى أن اللعبة بدأت تتجه لطرف واحد 
    بقوة (مثلاً 5 ثور)، سيعرف أن اللعبة دخلت وضع "تفريغ/انعكاس".
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 6")
            rows = cur.fetchall()
            if len(rows) < 4: return False, ""
            
            recent = [WINNER_MAP.get(r[0], 2) for r in rows]
            red_count = recent.count(0)
            blue_count = recent.count(1)
            
            if red_count >= 5:
                return True, "⚠️ اللعبة في حالة انعكاس (تم قلب الإشارة للثور 🔵)"
            elif blue_count >= 5:
                return True, "⚠️ اللعبة في حالة انعكاس (تم قلب الإشارة للراعي 🔴)"
    except: pass
    return False, ""

# ==================== 🧠 محرك التوقع (V13) ====================
def calculate_current_gap() -> int:
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row: return int((datetime.datetime.utcnow() - row[0]).total_seconds())
    except: pass
    return 0

def get_agent_prediction(suit: str, gap: int) -> Tuple[Optional[int], int, str]:
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("""SELECT predicted_winner, confidence, reason 
                           FROM agent_laws 
                           WHERE suit = %s AND %s BETWEEN min_gap AND max_gap
                           ORDER BY confidence DESC LIMIT 1""", (suit, gap))
            row = cur.fetchone()
            if row: return row[0], row[1], f"🤖 قانون زمني ({row[2]})"
    except: pass
    return None, 0, ""

async def predict_v13(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])
    current_gap = calculate_current_gap()
    
    logs = []
    scores = {0: 0.0, 1: 0.0}
    
    # 1. كاشف الانعكاس (أهم شيء الآن)
    is_shifted, shift_msg = detect_regime_shift()
    if is_shifted:
        logs.append(shift_msg)
    
    # 2. قوانين العميل الزمني
    agent_w, agent_c, agent_log = get_agent_prediction(suit, current_gap)
    if agent_w is not None:
        # إذا كانت اللعبة في حالة انعكاس، نعكس قرار العميل
        if is_shifted: agent_w = 1 if agent_w == 0 else 0
        scores[agent_w] += agent_c * 2.0  
        logs.append(f"⏱️ **الفجوة ({current_gap} ث):** {WINNER_NAMES[agent_w]} [{agent_log}]")
    else:
        logs.append(f"⏱️ الفجوة الحالية: {current_gap} ث (لا يوجد قانون لها).")

    # 3. الإحصاء الرياضي السريع
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE suit=%s AND bonus_last_digit=%s ORDER BY id DESC LIMIT 50", (suit, last_digit))
            rows = cur.fetchall()
            if len(rows) > 2:
                recent = [WINNER_MAP.get(r[0], 2) for r in rows]
                red, blue = recent.count(0), recent.count(1)
                if red != blue:
                    best = 0 if red > blue else 1
                    # نعكس القرار الإحصائي إذا كانت اللعبة في وضع الانعكاس
                    if is_shifted: best = 1 if best == 0 else 0
                    
                    conf = (max(red, blue) / (red + blue)) * 100
                    scores[best] += conf * 1.5
                    logs.append(f"📊 **الذاكرة المباشرة:** {WINNER_NAMES[best]}")
    except: pass

    # ================= الحساب النهائي =================
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    if total_score == 0:
        math_res = (sum(int(d) for d in clean_b[-3:]) + last_digit) % 2
        if is_shifted: math_res = 1 if math_res == 0 else 0
        return math_res, 60, "🧮 **المحرك الرياضي الاحتياطي**"
        
    raw_conf = (scores[final_pred] / total_score) * 100
    confidence = int(min(99, max(50, raw_conf)))
    
    return final_pred, confidence, "\n".join(logs)

# ==================== 🛠️ أوامر التدخل الإداري ====================
async def trigger_agent_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    query = update.callback_query
    msg = update.message if update.message else query.message
    wait_msg = await msg.reply_text("🤖 <b>جاري إيقاظ العميل الذكي...</b>\nيتم الآن تحليل الجولات لمعرفة قوانين الزمن.", parse_mode='HTML')
    result = await ai_agent.analyze_and_create_laws(limit=300)
    await wait_msg.edit_text(f"🤖 <b>تقرير العميل الذكي:</b>\n{result}", parse_mode='HTML')

# ==================== 🎮 الواجهة ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🎴 بدء التوقع", callback_data="choose_suit")],
        [InlineKeyboardButton("🤖 تحديث قوانين العميل الزمني", callback_data="force_agent")]
    ]
    await update.message.reply_text("<b>🏛️ HADES V13 (Anti-Shift Mode)</b>\n\nنظام كشف الانعكاس والعميل الزمني مفعل.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    try:
        if data == "force_agent":
            await trigger_agent_manual(update, context)
            
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
            suit = context.user_data.get
