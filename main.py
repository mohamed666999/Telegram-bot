"""
HADES V13.2 - THE ANTI-SHIFT ENGINE (JSON Armor)
إصلاح مشكلة معالجة الـ JSON القادم من الذكاء الاصطناعي وتجريده من الشوائب.
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

# ==================== 🤖 العميل المستقل (Safeguarded AI Agent) ====================
class AutonomousAgent:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL, timeout=20.0)

    async def analyze_and_create_laws(self, limit=100) -> str:
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(f"SELECT suit, timestamp, winner FROM history WHERE winner IS NOT NULL AND timestamp IS NOT NULL ORDER BY id DESC LIMIT {limit}")
                rows = cur.fetchall()
            
            if len(rows) < 10: return "بيانات غير كافية لتدريب العميل."

            agent_data = []
            rows.reverse()
            for i in range(1, len(rows)):
                suit = rows[i][0]
                t_current = rows[i][1]
                t_prev = rows[i-1][1]
                
                if t_current is None or t_prev is None: continue
                    
                time_gap = int((t_current - t_prev).total_seconds())
                winner = WINNER_MAP.get(rows[i][2], 2)
                
                if time_gap > 0 and time_gap < 180: 
                    agent_data.append(f"({suit},{time_gap}s,{winner})")

            if not agent_data: return "⚠️ لا توجد جولات متتالية صحيحة التوقيت لبناء قوانين."

            prompt = f"""
            Analyze this Casino data format: (Suit, TimeGap_seconds, Winner[0=Red, 1=Blue]).
            Data: {', '.join(agent_data[-60:])}
            
            Task: Give me 2 or 3 rules based on TimeGap.
            OUTPUT STRICTLY AS A RAW JSON ARRAY. NO MARKDOWN. NO CODE BLOCKS.
            Example:
            [
              {{"suit": "♦️", "min_gap": 25, "max_gap": 40, "predicted_winner": 1, "confidence": 85, "reason": "Fast gaps favor Blue"}}
            ]
            """
            
            response = await self.client.chat.completions.create(
                model=NVIDIA_MODEL,
                messages=[
                    {"role": "system", "content": "You are a JSON stringifier. Do not use markdown like ```json. Return pure JSON array."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1, max_tokens=300
            )
            
            content = response.choices[0].message.content
            
            # 🛡️ الدرع الواقي (JSON Armor) لتنظيف النص من الماركداون والشوائب
            content = content.replace('```json', '').replace('```', '').strip()
            match = re.search(r'\[.*\]', content, re.DOTALL)
            
            if match:
                clean_json_str = match.group()
                try:
                    laws = json.loads(clean_json_str)
                    if isinstance(laws, list) and len(laws) > 0:
                        with get_db_cursor() as (conn, cur):
                            cur.execute("TRUNCATE TABLE agent_laws")
                            for law in laws:
                                cur.execute("""INSERT INTO agent_laws (suit, min_gap, max_gap, predicted_winner, confidence, reason) 
                                               VALUES (%s, %s, %s, %s, %s, %s)""",
                                            (law.get('suit'), law.get('min_gap'), law.get('max_gap'), law.get('predicted_winner'), law.get('confidence'), law.get('reason')))
                            conn.commit()
                        return f"✅ تم بنجاح! العميل زرع {len(laws)} قوانين زمنية جديدة."
                    else:
                        return "⚠️ العميل لم ينتج أي قانون مفيد."
                except json.JSONDecodeError as e:
                    logger.error(f"JSON Decode Error. Raw string: {clean_json_str}")
                    return "❌ فشل الذكاء الاصطناعي في صياغة القوانين بشكل صحيح. حاول مجدداً."
            return "⚠️ الذكاء الاصطناعي أرجع رداً غير مفهوم."
        except Exception as e:
            return f"❌ خطأ في الاتصال بالعميل الذكي."

ai_agent = AutonomousAgent()

# ==================== 🔄 كاشف الانعكاس الحي (Auto-Inversion) ====================
def detect_regime_shift() -> Tuple[bool, str]:
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

# ==================== 🧠 محرك التوقع (V13.2) ====================
def calculate_current_gap() -> int:
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT timestamp FROM history WHERE timestamp IS NOT NULL ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row and row[0]: 
                return int((datetime.datetime.utcnow() - row[0]).total_seconds())
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
    
    is_shifted, shift_msg = detect_regime_shift()
    if is_shifted:
        logs.append(shift_msg)
    
    agent_w, agent_c, agent_log = get_agent_prediction(suit, current_gap)
    if agent_w is not None:
        if is_shifted: agent_w = 1 if agent_w == 0 else 0
        scores[agent_w] += agent_c * 2.0  
        logs.append(f"⏱️ **الفجوة ({current_gap} ث):** {WINNER_NAMES[agent_w]} [{agent_log}]")
    else:
        logs.append(f"⏱️ الفجوة الحالية: {current_gap} ث (لا يوجد قانون لها).")

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE suit=%s AND bonus_last_digit=%s AND winner IS NOT NULL ORDER BY id DESC LIMIT 50", (suit, last_digit))
            rows = cur.fetchall()
            if len(rows) > 2:
                recent = [WINNER_MAP.get(r[0], 2) for r in rows]
                red, blue = recent.count(0), recent.count(1)
                if red != blue:
                    best = 0 if red > blue else 1
                    if is_shifted: best = 1 if best == 0 else 0
                    
                    conf = (max(red, blue) / (red + blue)) * 100
                    scores[best] += conf * 1.5
                    logs.append(f"📊 **الذاكرة المباشرة:** {WINNER_NAMES[best]}")
    except: pass

    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    if total_score == 0:
        math_res = (sum(int(d) for d in clean_b[-3:]) + last_digit) % 2
        if is_shifted: math_res = 1 if math_res == 0 else 0
        return math_res, 60, "🧮 **المحرك الرياضي الاحتياطي**"
        
    raw_conf = (scores[final_pred] / total_score) * 100
    confidence = int(min(99, max(50, raw_conf)))
    
    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

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
    await update.message.reply_text("<b>🏛️ HADES V13.2 (Anti-Shift Mode)</b>\n\nنظام كشف الانعكاس والعميل الزمني مفعل.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

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
            
            suit = context.user_data.get('suit')
            rank = context.user_data.get('rank')
            if suit and rank:
                kb = [[InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
                await query.edit_message_text(f"🗑️ تم حذف الجولة الخاطئة.\n\nمستمرون مع: <b>{suit} {rank}</b>\n📥 أرسل الرقم الصحيح:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            else:
                kb = [[InlineKeyboardButton("🎴 اختيار", callback_data="choose_suit")]]
                await query.edit_message_text("🗑️ تم الحذف. يرجى اختيار الورقة من جديد:", reply_markup=InlineKeyboardMarkup(kb))

        elif data.startswith("save_"):
            w_code = int(data.split("_")[1])
            b_num = context.user_data.get('last_b_num')
            suit = context.user_data.get('last_suit')
            rank = context.user_data.get('last_rank')
            
            if b_num and suit and rank:
                last_digit = int(clean_digits(b_num)[-1]) 
                try:
                    with get_db_cursor() as (conn, cur):
                        cur.execute("""INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id, timestamp) 
                                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                                    (b_num, suit, rank, last_digit, WINNER_NAMES[w_code], update.effective_user.id, datetime.datetime.utcnow()))
                        conn.commit()
                except Exception as e: logger.error(f"Live Save Error: {e}")

            kb = [[InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")], [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ تم التسجيل: <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
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
                
            pred_code, confidence, reason = await predict_v13(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            context.user_data['last_pred_code'] = pred_code
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير V13.2</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>التوقع المرجح: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 مجريات التحليل:</b>\n{reason}
━━━━━━━━━━━━━━━
اختر الفائز الفعلي:"""
            
            await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 HADES V13.2 RUNNING...")
    app.run_polling(drop_pending_updates=True)
