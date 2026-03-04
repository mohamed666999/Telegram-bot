"""
HADES V-TITAN 2.0 - Gap-Aware Trading Algorithm
الميزات: اكتشاف الانقطاع الزمني (مبني على 35 ثانية)، تجاهل السلاسل الكاذبة، الذاكرة الصافية.
"""
import os, re, datetime, psycopg2, logging
from typing import Tuple, List
from contextlib import contextmanager
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
            # استخدام IF NOT EXISTS المدعومة في النسخ الحديثة من PostgreSQL لتجنب الأخطاء
            cur.execute("ALTER TABLE history ADD COLUMN IF NOT EXISTS rank VARCHAR(5);")
            cur.execute("ALTER TABLE history ADD COLUMN IF NOT EXISTS bonus_last_digit INT;")
            cur.execute("ALTER TABLE history ADD COLUMN IF NOT EXISTS user_id BIGINT;")
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ai_laws (
                    law_name VARCHAR(100) PRIMARY KEY, 
                    law_pattern JSONB, 
                    success_count INT DEFAULT 0, 
                    fail_count INT DEFAULT 0, 
                    is_active BOOLEAN DEFAULT TRUE
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

# ==================== ⏱️ أداة اكتشاف الانقطاع (Gap Detector) ====================
def is_sequence_broken() -> bool:
    """يتحقق هل تم إدخال الجولات بشكل متتالٍ (بناءً على 30-35 ثانية لكل جولة)"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 3")
            rows = cur.fetchall()
            
            if len(rows) < 3: 
                return True # لا يوجد جولات كافية
            
            now = datetime.datetime.now()
            last_round_time = rows[0][0]
            third_last_round_time = rows[2][0]
            
            # 1. إذا مر أكثر من 90 ثانية منذ آخر جولة تم إدخالها، فهناك انقطاع
            time_since_last = (now - last_round_time).total_seconds()
            if time_since_last > 90:
                return True
                
            # 2. 3 جولات تأخذ حوالي 105 ثواني. إذا كان الفرق بين الجولة الأولى والثالثة أكبر من 130 ثانية، فهناك جولة مفقودة في المنتصف
            time_span_3_rounds = (last_round_time - third_last_round_time).total_seconds()
            if time_span_3_rounds > 130:
                return True
                
    except Exception as e:
        logger.error(f"Gap Detector Error: {e}")
        return True
        
    return False

# ==================== ⚙️ المحركات الذكية لـ V-TITAN ====================
def get_markov_chain_prediction() -> Tuple[int, int, str]:
    if is_sequence_broken():
        return 2, 0, "تم تجاهل ماركوف (توقف زمني > 90 ثانية)"
        
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 500")
            rows = cur.fetchall()
            if len(rows) < 10: return 2, 0, ""
            
            history_codes = [WINNER_MAP.get(r[0], 2) for r in rows]
            history_codes.reverse()
            
            current_seq = tuple(history_codes[-3:])
            
            next_outcomes = {0: 0, 1: 0, 2: 0}
            for i in range(len(history_codes) - 3):
                if tuple(history_codes[i:i+3]) == current_seq:
                    next_outcomes[history_codes[i+3]] += 1
                    
            total_matches = sum(next_outcomes.values())
            if total_matches >= 3:
                best_pred = max(next_outcomes, key=next_outcomes.get)
                conf = int((next_outcomes[best_pred] / total_matches) * 100)
                return best_pred, conf, f"سلاسل التاريخ (تكرر {total_matches} مرات)"
    except: pass
    return 2, 0, ""

def get_cascading_db_prediction(suit: str, rank: str, last_digit: int) -> Tuple[int, int, str]:
    """العقل المستقر: يعمل دائماً ولا يتأثر بالانقطاع لأنه يعتمد على الورقة فقط"""
    queries = [
        (f"DB_{suit}{rank}{last_digit}", "تطابق دقيق (بذلة+ورقة+رقم)"),
        (f"DB_{suit}{rank}", "تطابق قوي (بذلة+ورقة)"),
        (f"DB{suit}ALL{last_digit}", "تطابق متوسط (بذلة+رقم)")
    ]
    try:
        with get_db_cursor() as (conn, cur):
            for q_name, desc in queries:
                cur.execute("SELECT success_count, fail_count, law_pattern->>'winner' FROM ai_laws WHERE law_name LIKE %s AND is_active = TRUE", (f"{q_name}%",))
                row = cur.fetchone()
                if row:
                    succ, fail, winner = row
                    if succ > fail:
                        conf = int((succ / (succ + fail)) * 100)
                        return int(winner), conf, f"{desc} [✅{succ}]"
    except: pass
    return 2, 0, ""

def get_momentum_correction() -> Tuple[int, int, str]:
    if is_sequence_broken():
        return 2, 0, "تم تجاهل الزخم (الجولات متقطعة)"
        
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 20")
            rows = cur.fetchall()
            if len(rows) < 10: return 2, 0, ""
            
            recent = [WINNER_MAP.get(r[0], 2) for r in rows]
            red_count = recent.count(0)
            blue_count = recent.count(1)
            
            if red_count >= 14:
                return 1, 75, "تصحيح زخم (تشبع الراعي)"
            elif blue_count >= 14:
                return 0, 75, "تصحيح زخم (تشبع الثور)"
    except: pass
    return 2, 0, ""

# ==================== ⚖️ خوارزمية V-TITAN المجمعة ====================
def predict_titan(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])
    
    # استدعاء العقول
    markov_pred, markov_conf, markov_desc = get_markov_chain_prediction()
    db_pred, db_conf, db_desc = get_cascading_db_prediction(suit, rank, last_digit)
    mom_pred, mom_conf, mom_desc = get_momentum_correction()

    votes = {0: 0.0, 1: 0.0, 2: 0.0}
    logs = []
    
    if markov_conf > 0:
        votes[markov_pred] += markov_conf * 1.5 
        logs.append(f"🧬 **ماركوف:** {WINNER_NAMES[markov_pred]} ({markov_desc})")
        
    if db_conf > 0:
        votes[db_pred] += db_conf * 2.0 
        logs.append(f"💾 **الذاكرة:** {WINNER_NAMES[db_pred]} ({db_desc})")
        
    if mom_conf > 0:
        votes[mom_pred] += mom_conf * 1.0 
        logs.append(f"⚖️ **الزخم:** {WINNER_NAMES[mom_pred]} ({mom_desc})")

    # المعادلة الرياضية كمنقذ أخير
    if sum(votes.values()) == 0:
        last_digits_sum = sum(int(d) for d in clean_b[-3:])
        card_val = RANK_VALUE.get(str(rank).strip().upper(), 0)
        math_res = ((last_digits_sum * card_val) + last_digit) % 2
        votes[math_res] += 60
        logs.append(f"🧮 **رياضيات:** {WINNER_NAMES[math_res]} (معادلة الورقة)")

    final_pred = max(votes, key=votes.get)
    total_score = sum(votes.values())
    confidence = min(99, int((votes[final_pred] / total_score) * 100)) if total_score > 0 else 50
    
    if is_sequence_broken():
        logs.append("\n⚠️ *ملاحظة:* تم الاعتماد على خصائص الورقة/الرياضيات فقط بسبب الانقطاع الزمني.")
        
    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

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

# ==================== 🎮 الواجهة الآمنة ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🏛️ HADES V-TITAN 2.0 (Gap-Aware)</b>\n\nنظام حساس للوقت (35s) ومقاوم للانقطاعات.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

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
                kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
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
                        cur.execute("""INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id) 
                                       VALUES (%s, %s, %s, %s, %s, %s)""",
                                    (b_num, suit, rank, last_digit, WINNER_NAMES[w_code], update.effective_user.id))
                        conn.commit()
                    
                    update_law_stats(f"DB_{suit}_{rank}_{last_digit}", context.user_data.get('last_pred_code') == w_code)
                except: pass

            kb = [
                [InlineKeyboardButton("🗑️ تصحيح الخطأ", callback_data="delete_last")],
                [InlineKeyboardButton("🔄 تغيير البذلة/الورقة", callback_data="choose_suit")]
            ]
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
                
            pred_code, confidence, reason = predict_titan(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            context.user_data['last_pred_code'] = pred_code
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير TITAN 2.0</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>
🏆 <b>الفائز المتوقع: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 تفاصيل التحليل:</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز لتسجيل النتيجة:"""
            
            await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")
        await update.message.reply_text("⚠️ حدث خطأ في المعالجة.")

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 HADES V-TITAN 2.0 Is Online!")
    app.run_polling(drop_pending_updates=True)
