"""
HADES V-OMEGA - The Digital Brain Architecture
الميزات: حدس اصطناعي لحظي، إجماع هرمي (تصويت 3 عقول)، تحليل الزخم، ومؤشر ثقة بشري.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging, asyncio
from typing import Tuple, Dict, Optional
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

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2, 0: 0, 1: 1, 2: 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

RANK_VALUE = {"A":14, "K":13, "Q":12, "J":11, "10":10, "9":9, "8":8, "7":7, "6":6, "5":5, "4":4, "3":3, "2":2}
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]

# ==================== 🗄️ إدارة الذاكرة العميقة (Database) ====================
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
            history_updates = ["ALTER TABLE history ADD COLUMN rank VARCHAR(5);", "ALTER TABLE history ADD COLUMN bonus_last_digit INT;", "ALTER TABLE history ADD COLUMN user_id BIGINT;"]
            for q in history_updates:
                cur.execute(f"DO $$ BEGIN {q} EXCEPTION WHEN duplicate_column THEN NULL; END $$;")
            cur.execute("""CREATE TABLE IF NOT EXISTS ai_laws (law_name VARCHAR(100) PRIMARY KEY, law_pattern JSONB, success_count INT DEFAULT 0, fail_count INT DEFAULT 0, is_active BOOLEAN DEFAULT TRUE)""")
            conn.commit()
    except: pass

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    empty = 10 - filled
    return "█" * filled + "░" * empty

# ==================== 🧠 العقول الثلاثة (The 3 Brains) ====================

class OmegaAI:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL, timeout=3.0) # مهلة قصيرة جداً لسرعة الرد

    async def get_human_intuition(self, recent_history: list, current_b_num: str, suit: str, rank: str) -> Tuple[int, int]:
        """العقل 1: يحلل الزخم وتسلسل الفوز كإنسان محترف"""
        try:
            prompt = f"""
            أنت مقامر محترف تعتمد على الحدس والزخم.
            آخر 10 نتائج (0=راعي, 1=ثور, 2=تعادل): {recent_history}
            الجولة الحالية: ورقة {suit}{rank} ورقم البونص {current_b_num}.
            حلل هل يوجد سلسلة فوز (Streak) يجب ركوبها، أم أن النمط سينكسر؟
            أعطني النتيجة بصيغة JSON فقط: {{"winner": 0 أو 1, "confidence": من 50 إلى 95}}
            """
            response = await self.client.chat.completions.create(
                model=NVIDIA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=100
            )
            content = response.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return int(data.get("winner", 2)), int(data.get("confidence", 50))
        except: pass
        return 2, 0 # في حال فشل الاتصال بالسيرفر

async def get_db_experience(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    """العقل 2: خبرة التاريخ المتراكمة (القوانين)"""
    last_digit = int(b_num[-1])
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("""SELECT law_name, success_count, fail_count, law_pattern->>'winner' 
                           FROM ai_laws WHERE law_name = %s AND is_active = TRUE""", (f"DB_{suit}_{rank}_{last_digit}",))
            row = cur.fetchone()
            if row and row[1] > row[2]:
                confidence = min(95, 50 + int((row[1] / (row[1] + row[2])) * 40))
                return int(row[3]), confidence, f"تطابق من الذاكرة العميقة ({row[0]})"
    except: pass
    return 2, 0, ""

def get_math_logic(b_num: str, rank: str) -> Tuple[int, int, str]:
    """العقل 3: المنطق الرياضي الكمي (Dynamic Math)"""
    try:
        last_digits_sum = sum(int(d) for d in b_num[-3:])
        card_val = RANK_VALUE.get(str(rank).strip().upper(), 0)
        hour_modifier = datetime.datetime.now().hour % 3 + 1 # عامل زمني يتغير كل 3 ساعات
        math_result = ((last_digits_sum * card_val * hour_modifier) + int(b_num[-1])) % 2
        return math_result, 60, "معادلة كمية (تفاعل الورقة مع الزمن)" # ثقة متوسطة للرياضيات
    except:
        return 2, 0, ""

# ==================== ⚖️ مجلس الحكماء (Neural Consensus) ====================
async def predict_omega(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    """يجمع قرارات العقول الثلاثة ويستخرج القرار النهائي كإنسان"""
    
    # جلب آخر 10 جولات للـ AI
    recent_history = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 10")
            recent_history = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
            recent_history.reverse()
    except: pass

    # تشغيل العقول الثلاثة في نفس اللحظة (لضمان السرعة)
    ai_engine = OmegaAI()
    ai_task = asyncio.create_task(ai_engine.get_human_intuition(recent_history, b_num, suit, rank))
    db_task = asyncio.create_task(get_db_experience(b_num, suit, rank))
    
    # انتظار النتائج
    ai_pred, ai_conf = await ai_task
    db_pred, db_conf, db_reason = await db_task
    math_pred, math_conf, math_reason = get_math_logic(b_num, rank)

    # 🗳️ نظام التصويت (Voting System)
    votes = {0: 0, 1: 0, 2: 0}
    reasons_list = []

    if db_conf > 0:
        votes[db_pred] += db_conf * 1.5 # الذاكرة لها وزن أعلى
        reasons_list.append(f"🧠 <b>الخبرة السابقة:</b> اختارت {WINNER_NAMES[db_pred]} ({db_reason})")
    
    if ai_conf > 0 and ai_pred in [0, 1]:
        votes[ai_pred] += ai_conf
        reasons_list.append(f"👁️ <b>حدس الذكاء الاصطناعي:</b> اختار {WINNER_NAMES[ai_pred]} (بناءً على زخم الطاولة)")
        
    votes[math_pred] += math_conf
    reasons_list.append(f"🧮 <b>المنطق الرياضي:</b> رجّح {WINNER_NAMES[math_pred]} ({math_reason})")

    # تحديد الفائز بالنقاط
    final_pred = max(votes, key=votes.get)
    
    # حساب الثقة النهائية
    total_votes = sum(votes.values())
    if total_votes == 0: return 2, 50, "تحليل عشوائي"
    
    final_confidence = min(99, int((votes[final_pred] / total_votes) * 100))
    
    # إذا اتفقت العقول
    if db_pred == ai_pred == math_pred:
        final_confidence = 99
        consensus_text = "🔥 <b>إجماع كامل (إشارة ذهبية)!</b> جميع الأنظمة متفقة."
    elif final_confidence < 60:
        consensus_text = "⚠️ <b>حالة تشتت:</b> الأنظمة مختلفة، العب بحذر."
    else:
        consensus_text = "✅ <b>قرار الأغلبية:</b> تم الترجيح بناءً على الأوزان."

    final_reason = "\n".join(reasons_list) + f"\n\n{consensus_text}"
    return final_pred, final_confidence, final_reason

# ==================== 🛠️ تحديث القوانين ====================
def update_law_stats(law_name: str, is_success: bool):
    try:
        with get_db_cursor() as (conn, cur):
            if is_success:
                cur.execute("UPDATE ai_laws SET success_count = success_count + 1 WHERE law_name = %s", (law_name,))
            else:
                cur.execute("UPDATE ai_laws SET fail_count = fail_count + 1 WHERE law_name = %s", (law_name,))
            conn.commit()
    except: pass

# ==================== 🎮 واجهة المستخدم الاستثنائية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 بدء تحليل V-OMEGA", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🏛️ HADES V-OMEGA (The Brain)</b>\n\nيستخدم تقنية الإجماع الهرمي وحدس الذكاء الاصطناعي اللحظي.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

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
            suit = context.user_data.get('suit'); rank = context.user_data.get('rank')
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
            pred_code = context.user_data.get('last_pred_code')
            
            if b_num and suit and rank:
                last_digit = int(b_num[-1])
                try:
                    with get_db_cursor() as (conn, cur):
                        cur.execute("""INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id) VALUES (%s, %s, %s, %s, %s, %s)""",
                                    (b_num, suit, rank, last_digit, WINNER_NAMES[w_code], update.effective_user.id))
                        conn.commit()
                    update_law_stats(f"DB_{suit}_{rank}_{last_digit}", w_code == pred_code)
                except: pass

            kb = [[InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")], [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ تم تسجيل وتعليم النظام: <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
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
            
            # رسالة انتظار احترافية لأن الذكاء الاصطناعي قد يستغرق ثانية
            processing_msg = await update.message.reply_text("⏳ <b>يتم الآن استشارة العقول الثلاثة (O.M.E.G.A)...</b>", parse_mode='HTML')
            
            pred_code, confidence, reason = await predict_omega(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            context.user_data['last_pred_code'] = pred_code
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            
            report = f"""🎯 <b>تقرير HADES V-OMEGA</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>الفائز المتوقع: {WINNER_NAMES[pred_code]}</b>
📊 <b>نسبة الثقة:</b> [{bar}] {confidence}%

{reason}
━━━━━━━━━━━━━━━
اضغط لتأكيد النتيجة وتدريب العقول:"""
            
            await processing_msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"⚠️ خطأ: `{str(e)}`", parse_mode='Markdown')

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 HADES V-OMEGA (The Brain) Is Online!")
    app.run_polling(drop_pending_updates=True)
