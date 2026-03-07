"""
HADES V14 - DIRECT AI LINK (No Libraries)
إصلاح جذري لاتصال GPT-5.2 عبر التخلص من مكتبة OpenAI والاتصال المباشر عبر HTTP.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging, asyncio, aiohttp
from typing import Tuple, Dict, Optional, List
from contextlib import contextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== 🛡️ الإعدادات والمفاتيح ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s" 
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

# 🌟 مفتاح الـ API واسم המوديل 🌟
AI_API_KEY = "acv-d8351cddde4fbd194ee91aa7442600cd54b961bd1fe39fcf898831db50b3892b"
AI_MODEL = "gpt-5.2"
AI_BASE_URL = "https://api.openai.com/v1/chat/completions" # عدل هذا الرابط إذا كان مزودك يعطيك رابطاً مختلفاً

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]

# ==================== 🗄️ إدارة قاعدة البيانات ====================
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

# ==================== 🤖 محرك GPT المباشر (Direct HTTP Call) ====================
async def call_gpt_direct(recent_history: list, current_b_num: str, suit: str, rank: str) -> Tuple[Optional[int], int, str]:
    """ 
    دالة تتصل مباشرة بمزود الـ API بدون مكتبات وسيطة لضمان الحصول على الرد أو الخطأ الحقيقي.
    """
    if len(recent_history) < 3: 
        return None, 0, "بيانات تاريخية غير كافية"

    prompt = f"""
    You are a Casino Data Scientist AI. Predict the next winner (0=Red, 1=Blue).
    Live Trend (last 20 rounds): {recent_history}
    Current Round: Card {suit} {rank}, Bonus {current_b_num}.
    Reply ONLY with a raw JSON object like this:
    {{"winner": 0 or 1, "confidence": 50-95, "reason": "Arabic sentence explaining the trend logic"}}
    """

    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": "You output only pure JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }

    # سنستخدم aiohttp لتنفيذ الطلب بشكل غير متزامن وعدم تجميد البوت
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_BASE_URL, headers=headers, json=payload, timeout=8.0) as response:
                # إذا كان الرد ليس 200 (أي أنه يوجد خطأ من السيرفر)
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"GPT Server Error: {response.status} - {error_text}")
                    return None, 0, f"خطأ سيرفر GPT [{response.status}]: {error_text[:30]}"
                
                # إذا كان الرد سليماً
                data = await response.json()
                content = data['choices'][0]['message']['content']
                content = content.replace('```json', '').replace('```', '').strip()
                
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    json_data = json.loads(match.group())
                    winner = int(json_data.get("winner", 2))
                    conf = int(json_data.get("confidence", 50))
                    reason = json_data.get("reason", "تحليل ذكي")
                    return winner, conf, reason
                else:
                    return None, 0, "GPT أعاد نصاً ليس JSON"
    
    except asyncio.TimeoutError:
        return None, 0, "انتهى وقت انتظار GPT (Timeout)"
    except Exception as e:
        logger.error(f"GPT Request Error: {e}")
        return None, 0, f"خطأ في الاتصال: {str(e)[:30]}"

# ==================== 🌌 محرك الإحصائيات (DB Pattern) ====================
def fetch_db_patterns(suit: str, last_digit: int) -> Tuple[Dict[int, float], List[str]]:
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

# ==================== 🧠 الدمج الشامل (V14) ====================
async def predict_infinity_gpt(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])
    
    logs = []
    scores = {0: 0.0, 1: 0.0}
    
    # 1. جلب آخر 20 جولة لـ GPT
    recent_history = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 20")
            recent_history = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
            recent_history.reverse()
    except: pass

    # 2. استشارة GPT (مباشرة وبدون مكتبات وسيطة)
    gpt_pred, gpt_conf, gpt_log = await call_gpt_direct(recent_history, clean_b, suit, rank)
    
    if gpt_pred in [0, 1]:
        scores[gpt_pred] += (gpt_conf / 100) * 3.0 
        logs.append(f"🤖 **GPT-5.2:** {WINNER_NAMES[gpt_pred]} ({gpt_log})")
    else:
        # هنا سنرى السبب الحقيقي الذي يمنع GPT من العمل
        logs.append(f"⚠️ **حالة GPT:** {gpt_log}")

    # 3. الإحصائيات
    db_scores, db_logs = fetch_db_patterns(suit, last_digit)
    logs.extend(db_logs)
    scores[0] += db_scores[0]
    scores[1] += db_scores[1]
    
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    if total_score == 0:
        padded_b = clean_b.zfill(3)
        math_res = (sum(int(d) for d in padded_b[-3:]) + last_digit) % 2
        return math_res, 60, "🧮 **تحليل رياضي احتياطي**\n" + "\n".join(logs)
        
    raw_conf = (scores[final_pred] / total_score) * 100
    confidence = int(min(99, max(50, raw_conf)))
    
    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

# ==================== 🎮 واجهة التليجرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 بدء التوقع", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🌌 HADES V14 (Direct AI Link)</b>\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("يتم التنفيذ...") 
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
                    
                    col = "red_count" if w_code == 0 else "blue_count" if w_code == 1 else "tie_count"
                    pid = f"SD_{suit}_{int(clean_digits(b_num)[-1])}"
                    cur.execute(f"INSERT INTO pattern_stats (pattern_id, {col}) VALUES (%s, 1) ON CONFLICT (pattern_id) DO UPDATE SET {col} = pattern_stats.{col} + 1", (pid,))
                    conn.commit()
            except Exception as db_e: pass

            kb = [
                [InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")], 
                [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]
            ]
            await query.edit_message_text(f"✅ تم حفظ: <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
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
            
            processing_msg = await update.message.reply_text("⏳ <b>جاري الاتصال بـ GPT-5.2...</b>", parse_mode='HTML')
            
            pred_code, confidence, reason = await predict_infinity_gpt(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🌌 <b>تقرير V14 (AI Link)</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>التوقع المرجح: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 مجريات التحليل:</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز الفعلي للتسجيل:"""
            
            await processing_msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🌌 HADES V14 (Direct AI Link) RUNNING...")
    app.run_polling(drop_pending_updates=True)
