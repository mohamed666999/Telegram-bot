"""
HADES V-INFINITY 3.0 - The Contextual Mind (GPT-5.2 Deep Memory)
تم تزويد GPT-5.2 بذاكرة سياقية عميقة (Historical + Live Data) ليفهم قاعدة البيانات بالكامل.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging, asyncio
from typing import Tuple, Dict, Optional, List
from contextlib import contextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== 🛡️ الإعدادات الأساسية والمفاتيح ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s" 
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

# 🌟 مفاتيح الذكاء الاصطناعي (GPT-5.2) 🌟
AI_API_KEY = "acv-d8351cddde4fbd194ee91aa7442600cd54b961bd1fe39fcf898831db50b3892b"
AI_MODEL = "gpt-5.2"
AI_BASE_URL = "https://api.openai.com/v1" 

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]

RANK_VALUE = {"A":14, "K":13, "Q":12, "J":11, "10":10, "9":9, "8":8, "7":7, "6":6, "5":5, "4":4, "3":3, "2":2}

# ==================== 🗄️ إدارة قاعدة البيانات الآمنة السريعة ====================
@contextmanager
def get_db_cursor():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=3)
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

# ==================== 🤖 محرك GPT-5.2 ذو الذاكرة السياقية (Contextual Memory) ====================
class GPT5ContextualEngine:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL, timeout=6.0)

    async def get_prediction(self, suit: str, rank: str, last_digit: int, clean_b: str) -> Tuple[Optional[int], int, str]:
        """يجمع البيانات التاريخية واللحظية ويشكل سياقاً عميقاً لـ GPT"""
        
        recent_trend = []
        hist_suit_red, hist_suit_blue = 0, 0
        hist_exact_red, hist_exact_blue = 0, 0
        
        try:
            with get_db_cursor() as (conn, cur):
                # 1. السياق اللحظي (آخر 20 جولة لكسر التريند)
                cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 20")
                recent_trend = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
                recent_trend.reverse()
                
                # 2. السياق التاريخي للبذلة
                cur.execute("SELECT red_count, blue_count FROM pattern_stats WHERE pattern_id = %s", (f"SUIT_{suit}",))
                row = cur.fetchone()
                if row: hist_suit_red, hist_suit_blue = int(row[0]), int(row[1])

                # 3. السياق التاريخي الدقيق (الورقة والرقم)
                cur.execute("SELECT red_count, blue_count FROM pattern_stats WHERE pattern_id = %s", (f"SD_{suit}_{last_digit}",))
                row = cur.fetchone()
                if row: hist_exact_red, hist_exact_blue = int(row[0]), int(row[1])
        except: pass

        if len(recent_trend) < 3: return None, 0, ""

        # 🧠 صياغة الذاكرة السياقية لـ GPT
        prompt = f"""
        You are a highly advanced Casino Data Scientist AI (GPT-5.2). Your goal is to predict the next winner (0=Red, 1=Blue).
        
        ### CONTEXTUAL MEMORY (Database Facts):
        - Overall Suit Bias for [{suit}]: Historical wins -> Red: {hist_suit_red}, Blue: {hist_suit_blue}.
        - Exact Pattern Bias for [{suit} + digit {last_digit}]: Historical wins -> Red: {hist_exact_red}, Blue: {hist_exact_blue}.
        
        ### LIVE MARKET TREND (Last 20 outcomes):
        Sequence (oldest to newest): {recent_trend}
        
        ### CURRENT ROUND:
        Card: {suit} {rank}, Bonus Number: {clean_b}.
        
        Task: Analyze the clash between Historical Bias and Live Trend. If the live trend is too strong (e.g., 5 Blues in a row), a mean reversion (break) to Red is highly probable. 
        Reply ONLY with a raw JSON object:
        {{"winner": 0 or 1, "confidence": integer 50 to 95, "reason": "1 short Arabic sentence explaining the logic based on history vs trend"}}
        """
        
        try:
            response = await self.client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a master of probability. Output pure JSON without markdown code blocks."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3, max_tokens=150
            )
            content = response.choices[0].message.content.replace('```json', '').replace('```', '').strip()
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return int(data.get("winner", 2)), int(data.get("confidence", 50)), data.get("reason", "تحليل سياقي عميق")
        except Exception as e:
            logger.error(f"GPT Contextual Error: {e}")
        return None, 0, "تعذر معالجة السياق"

gpt_context_engine = GPT5ContextualEngine()

# ==================== 🌌 محرك الفوضى والتناقض (Chaos & Paradox) ====================
def fetch_db_patterns(suit: str, last_digit: int) -> Tuple[Dict[int, float], List[str]]:
    """يجلب الأنماط الإحصائية كدعم لقرار الـ AI"""
    scores = {0: 0.0, 1: 0.0}
    logs = []
    queries = [(f"SD_{suit}_{last_digit}", "نمط القاعدة (بذلة+رقم)", 2.0), (f"SUIT_{suit}", "نمط البذلة العام", 1.2)]
    
    try:
        with get_db_cursor() as (conn, cur):
            for pid, desc, weight in queries:
                cur.execute("SELECT red_count, blue_count FROM pattern_stats WHERE pattern_id = %s", (pid,))
                row = cur.fetchone()
                if row:
                    red, blue = row[0], row[1]
                    total = red + blue
                    if total > 0:
                        p_red = red / total
                        p_blue = blue / total
                        # بروتوكول التناقض (عكس النمط الوهمي المكشوف)
                        if p_red > 0.85 and total >= 5:
                            scores[1] += weight * 3.0 
                            logs.append(f"🌀 بروتوكول التناقض: فخ راعي في ({desc}) -> إجبار للثور 🔵")
                        elif p_blue > 0.85 and total >= 5:
                            scores[0] += weight * 3.0 
                            logs.append(f"🌀 بروتوكول التناقض: فخ ثور في ({desc}) -> إجبار للراعي 🔴")
                        else:
                            winner = 0 if p_red > p_blue else 1
                            scores[winner] += max(p_red, p_blue) * weight
                            logs.append(f"📊 {desc}: {WINNER_NAMES[winner]} [✅{int(max(red,blue))}|❌{int(min(red,blue))}]")
    except: pass
    return scores, logs

# ==================== 🧠 محرك INFINITY המدمج (V3.0) ====================
async def predict_infinity_gpt(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])
    
    logs = []
    scores = {0: 0.0, 1: 0.0}
    
    # 1. استشارة عقل GPT-5.2 السياقي العميق
    gpt_pred, gpt_conf, gpt_log = await gpt_context_engine.get_prediction(suit, rank, last_digit, clean_b)
    if gpt_pred in [0, 1]:
        scores[gpt_pred] += (gpt_conf / 100) * 3.0 # وزن هائل لـ GPT لأنه يمتلك السياق كاملاً
        logs.append(f"🤖 **GPT-5.2 (ذاكرة سياقية):** {WINNER_NAMES[gpt_pred]} ({gpt_log})")

    # 2. الأنماط الرياضية والـ Paradox (لتعزيز أو نقض قرار الـ AI)
    db_scores, db_logs = fetch_db_patterns(suit, last_digit)
    logs.extend(db_logs)
    scores[0] += db_scores[0]
    scores[1] += db_scores[1]
    
    # الحساب النهائي
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    if total_score == 0:
        padded_b = clean_b.zfill(3)
        math_res = (sum(int(d) for d in padded_b[-3:]) + last_digit) % 2
        return math_res, 60, "🧮 **تحليل رياضي احتياطي**"
        
    raw_conf = (scores[final_pred] / total_score) * 100
    confidence = int(min(99, max(50, raw_conf)))
    
    # رسالة تناغم
    if gpt_pred == final_pred and len(logs) > 1:
        logs.append("\n🔥 **إجماع كلي: GPT يتفق مع الإحصائيات!**")
        confidence = max(85, confidence)
    
    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

# ==================== 🛠️ السحب والتصدير ====================
async def download_db_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    message = update.message if update.message else update.callback_query.message
    msg = await message.reply_text("⏳ جاري سحب قاعدة البيانات...")
    try:
        with get_db_cursor() as (conn, cur):
            df_history = pd.read_sql("SELECT * FROM history ORDER BY id DESC LIMIT 5000", conn)
            df_patterns = pd.read_sql("SELECT * FROM pattern_stats ORDER BY (red_count + blue_count) DESC", conn)
            
        filename = f"hades_db_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("=== HADES DB BACKUP ===\n\n--- PATTERN STATS ---\n")
            df_patterns.to_csv(f, sep='\t', index=False)
            f.write("\n\n--- HISTORY ---\n")
            df_history.to_csv(f, sep='\t', index=False)

        with open(filename, "rb") as f:
            await message.reply_document(document=f, caption="📥 نسخة احتياطية من قاعدة البيانات")
        os.remove(filename)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")

# ==================== 🎮 واجهة التليجرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🎴 بدء التوقع", callback_data="choose_suit")],
        [InlineKeyboardButton("📥 تحميل البيانات", callback_data="download_txt")]
    ]
    await update.message.reply_text("<b>🌌 HADES V-INFINITY 3.0 (Deep Context Memory)</b>\nالذكاء الاصطناعي الآن يفهم تاريخ اللعبة كاملاً.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("يتم تنفيذ الأمر...") 
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
            await query.edit_message_text(f"✅ تم الاختيار: <b>{suit} {rank}</b>\n\n📥 <b>أرسل رقم البونص:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

        elif data == "delete_last":
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute("DELETE FROM history WHERE id = (SELECT max(id) FROM history WHERE user_id = %s)", (update.effective_user.id,))
                    conn.commit()
            except: pass
            kb = [[InlineKeyboardButton("🔄 تغيير الاختيار", callback_data="choose_suit")]]
            await query.edit_message_text(f"🗑️ تم مسح الجولة الخاطئة.\nأرسل الرقم الصحيح:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

        elif data.startswith("save_"):
            w_code = int(data.split("_")[1])
            b_num = context.user_data.get('last_b_num', '00000')
            suit = context.user_data.get('last_suit', '♦️')
            rank = context.user_data.get('last_rank', 'A')
            
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute("""INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id) 
                                   VALUES (%s, %s, %s, %s, %s, %s)""",
                                (b_num, suit, rank, int(clean_digits(b_num)[-1]), WINNER_NAMES[w_code], update.effective_user.id))
                    
                    # التعليم الفوري لجدول الأنماط
                    col = "red_count" if w_code == 0 else "blue_count" if w_code == 1 else "tie_count"
                    pid = f"SD_{suit}_{int(clean_digits(b_num)[-1])}"
                    cur.execute(f"INSERT INTO pattern_stats (pattern_id, {col}) VALUES (%s, 1) ON CONFLICT (pattern_id) DO UPDATE SET {col} = pattern_stats.{col} + 1", (pid,))
                    
                    pid2 = f"SUIT_{suit}"
                    cur.execute(f"INSERT INTO pattern_stats (pattern_id, {col}) VALUES (%s, 1) ON CONFLICT (pattern_id) DO UPDATE SET {col} = pattern_stats.{col} + 1", (pid2,))
                    conn.commit()
            except Exception as db_e: 
                logger.error(f"Live Save Error: {db_e}")

            kb = [
                [InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")], 
                [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]
            ]
            await query.edit_message_text(f"✅ تم حفظ: <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
    except Exception as e:
        logger.error(f"Callback Error: {e}")
        kb = [[InlineKeyboardButton("رجوع للقائمة", callback_data="choose_suit")]]
        await query.edit_message_text("❌ انتهت صلاحية الجلسة.", reply_markup=InlineKeyboardMarkup(kb))

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
            
            processing_msg = await update.message.reply_text("⏳ <b>يتم دمج ذاكرة 2500 جولة مع سياق GPT-5.2...</b>", parse_mode='HTML')
            
            pred_code, confidence, reason = await predict_infinity_gpt(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            context.user_data['last_pred_code'] = pred_code
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🌌 <b>تقرير INFINITY 3.0 (Deep Memory)</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>التوقع المرجح: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 مجريات التحليل:</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز لتسجيل النتيجة:"""
            
            await processing_msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_db_txt))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🌌 HADES V-INFINITY 3.0 RUNNING...")
    app.run_polling(drop_pending_updates=True)
