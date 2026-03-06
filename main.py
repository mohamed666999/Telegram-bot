"""
HADES V12 - THE AUTONOMOUS AGENT
عميل ذكاء اصطناعي مستقل يعمل في الخلفية، يحلل الفجوات الزمنية (Time Gaps)،
ويكتب قوانين اللعبة ويحدثها تلقائياً.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging, asyncio
from typing import Tuple, Dict, Optional, List
from contextlib import contextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
            
            # جدول جديد خاص بالقوانين التي يكتبها الـ AI Agent بناءً على الفجوة الزمنية
            cur.execute("""CREATE TABLE IF NOT EXISTS agent_laws (
                id SERIAL PRIMARY KEY,
                suit TEXT,
                min_gap INT,
                max_gap INT,
                predicted_winner INT,
                confidence INT,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            conn.commit()
    except Exception as e:
        logger.error(f"DB Init Error: {e}")

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

# ==================== 🤖 العميل المستقل (The AI Agent) ====================
class AutonomousAgent:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL, timeout=15.0)

    async def analyze_and_create_laws(self, limit=200) -> str:
        """يقوم العميل بسحب البيانات، تحليل الفجوات، وكتابة قوانين جديدة في DB"""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(f"SELECT suit, timestamp, winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT {limit}")
                rows = cur.fetchall()
            
            if len(rows) < 10: return "بيانات غير كافية لتدريب العميل."

            # تجهيز البيانات للعميل (حساب الفجوات الزمنية بين الجولات المتتالية)
            agent_data = []
            rows.reverse() # من الأقدم للأحدث
            for i in range(1, len(rows)):
                suit = rows[i][0]
                time_gap = int((rows[i][1] - rows[i-1][1]).total_seconds())
                winner = WINNER_MAP.get(rows[i][2], 2)
                
                # تجاهل الانقطاعات الطويلة جداً (أكثر من 5 دقائق)
                if time_gap < 300: 
                    agent_data.append(f"[{suit}, Gap:{time_gap}s -> Winner:{winner}]")

            prompt = f"""
            You are a Casino Quant AI Agent. 
            Dataset format: [Suit, Time Gap in seconds, Winner (0=Red, 1=Blue)].
            Data: {', '.join(agent_data[-100:])}
            
            Find the correlation between the 'Time Gap' and the 'Winner' for each suit.
            Example: Does playing fast (30s) favor Blue? Does waiting (60s) favor Red?
            
            Return ONLY a valid JSON array of 3 rules in this EXACT format:
            [
              {{"suit": "♦️", "min_gap": 25, "max_gap": 40, "predicted_winner": 1, "confidence": 85, "reason": "Fast diamonds favor blue"}},
              {{"suit": "♠️", "min_gap": 45, "max_gap": 90, "predicted_winner": 0, "confidence": 75, "reason": "Slow spades favor red"}}
            ]
            """
            
            response = await self.client.chat.completions.create(
                model=NVIDIA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=300
            )
            
            content = response.choices[0].message.content
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                laws = json.loads(match.group())
                
                # مسح القوانين القديمة وحقن القوانين الجديدة التي كتبها العميل
                with get_db_cursor() as (conn, cur):
                    cur.execute("TRUNCATE TABLE agent_laws")
                    for law in laws:
                        cur.execute("""INSERT INTO agent_laws (suit, min_gap, max_gap, predicted_winner, confidence, reason) 
                                       VALUES (%s, %s, %s, %s, %s, %s)""",
                                    (law['suit'], law['min_gap'], law['max_gap'], law['predicted_winner'], law['confidence'], law['reason']))
                    conn.commit()
                return f"✅ تم بنجاح! العميل زرع {len(laws)} قوانين زمنية جديدة."
            return "⚠️ لم يستطع العميل إيجاد أنماط زمنية واضحة."
        except Exception as e:
            logger.error(f"Agent Error: {e}")
            return f"❌ خطأ في العميل: {str(e)}"

ai_agent = AutonomousAgent()

# ⏱️ وظيفة تعمل في الخلفية كل 15 دقيقة (يستيقظ العميل ليتعلم)
async def background_agent_task(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🤖 [AI AGENT] Waking up to analyze recent time gaps...")
    result = await ai_agent.analyze_and_create_laws(limit=50) # يحلل آخر 50 جولة فقط ليكون سريعاً
    logger.info(f"🤖 [AI AGENT] Task Result: {result}")

# ==================== 🧠 محرك التوقع المدمج (V12) ====================
def calculate_current_gap() -> int:
    """يحسب الثواني منذ آخر جولة ليعرف الإيقاع الحالي"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                gap = (datetime.datetime.utcnow() - row[0]).total_seconds()
                return int(gap)
    except: pass
    return 0

def get_agent_prediction(suit: str, gap: int) -> Tuple[Optional[int], int, str]:
    """يبحث هل كتب العميل الذكي قانوناً يناسب هذه الفجوة الزمنية؟"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("""SELECT predicted_winner, confidence, reason 
                           FROM agent_laws 
                           WHERE suit = %s AND %s BETWEEN min_gap AND max_gap
                           ORDER BY confidence DESC LIMIT 1""", (suit, gap))
            row = cur.fetchone()
            if row:
                return row[0], row[1], f"🤖 قانون العميل الذكي ({row[2]})"
    except: pass
    return None, 0, ""

async def predict_v12(b_num: str, suit: str, rank: str) -> Tuple[int, int, str, int]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح", 0
    last_digit = int(clean_b[-1])
    
    # ⏱ حساب الفجوة الزمنية
    current_gap = calculate_current_gap()
    
    logs = []
    scores = {0: 0.0, 1: 0.0}
    
    # 1️⃣ العقل الأول: قوانين العميل الذكي (مبنية على الفجوة الزمنية)
    agent_w, agent_c, agent_log = get_agent_prediction(suit, current_gap)
    if agent_w is not None:
        scores[agent_w] += agent_c * 2.0  # وزن ثقيل جداً لأنها قوانين الـ AI الحية
        logs.append(f"⏱️ **الفجوة ({current_gap} ثانية):** {WINNER_NAMES[agent_w]} [{agent_log}]")
    else:
        logs.append(f"⏱️ الفجوة الحالية: {current_gap} ثانية (لا يوجد قانون زمني لها).")

    # 2️⃣ العقل الثاني: الإحصاء التقليدي المبني على (Suit + Digit)
    try:
        with get_db_cursor() as (conn, cur):
            # محاكاة للمحرك البايزي من الجولات السابقة
            cur.execute("SELECT winner FROM history WHERE suit=%s AND bonus_last_digit=%s ORDER BY id DESC LIMIT 50", (suit, last_digit))
            rows = cur.fetchall()
            if len(rows) > 3:
                recent = [WINNER_MAP.get(r[0], 2) for r in rows]
                red, blue = recent.count(0), recent.count(1)
                if red != blue:
                    best = 0 if red > blue else 1
                    conf = (max(red, blue) / (red + blue)) * 100
                    scores[best] += conf * 1.5
                    logs.append(f"📊 **الذاكرة الإحصائية:** {WINNER_NAMES[best]}")
    except: pass

    # ================= الحساب النهائي =================
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    if total_score == 0:
        # المحرك الرياضي في حال غياب أي بيانات
        math_res = (sum(int(d) for d in clean_b[-3:]) + last_digit) % 2
        return math_res, 60, "🧮 **المحرك الرياضي الاحتياطي**", current_gap
        
    raw_conf = (scores[final_pred] / total_score) * 100
    confidence = int(min(99, max(50, raw_conf)))
    
    return final_pred, confidence, "\n".join(logs), current_gap

# ==================== 🛠️ أوامر التدخل الإداري ====================
async def trigger_agent_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """زر/أمر يجبر العميل على قراءة كل التاريخ وتوليد قوانين الفجوة الزمنية"""
    if update.effective_user.id != ADMIN_ID: return
    
    query = update.callback_query
    msg = update.message if update.message else query.message
    
    wait_msg = await msg.reply_text("🤖 <b>جاري إيقاظ العميل الذكي...</b>\nيتم الآن تحليل آلاف الجولات وربطها بالفجوة الزمنية (Time Gap).", parse_mode='HTML')
    
    # نجبر العميل على قراءة آخر 500 جولة لاستخراج القوانين العميقة
    result = await ai_agent.analyze_and_create_laws(limit=500)
    
    await wait_msg.edit_text(f"🤖 <b>تقرير العميل الذكي:</b>\n{result}", parse_mode='HTML')

# ==================== 🎮 الواجهة ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🎴 بدء التوقع اللحظي", callback_data="choose_suit")],
        [InlineKeyboardButton("🤖 تدخّل الذكاء الاصطناعي (Agent)", callback_data="force_agent")]
    ]
    await update.message.reply_text("<b>🏛️ HADES V12 (Autonomous Agent)</b>\n\nنظام تحليل الفجوة الزمنية مفعل.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

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
                        conn.commit()
                except Exception as e: logger.error(f"Save Error: {e}")

            kb = [[InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")], [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ تم التسجيل بنجاح: <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
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
                
            pred_code, confidence, reason, gap = await predict_v12(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير V12 (Agent Mode)</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>التوقع: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 مجريات التحليل:</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز لتسجيل النتيجة:"""
            
            await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    
    # ⏱️ تشغيل العميل في الخلفية كل 15 دقيقة (900 ثانية)
    app.job_queue.run_repeating(background_agent_task, interval=900, first=60)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("agent", trigger_agent_manual))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 HADES V12 (Autonomous Agent) RUNNING...")
    app.run_polling(drop_pending_updates=True)
