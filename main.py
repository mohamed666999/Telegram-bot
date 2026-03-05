د"""
HADES V10 - THE QUANTUM FLIP (Adaptive Trend Reversal)
إصلاح مشكلة الدقة السلبية عبر الاعتماد على الذاكرة قصيرة المدى ونظام "عكس الإشارة" للأنماط المشبعة.
"""

import os, re, datetime, psycopg2, pandas as pd, logging
from typing import Tuple, Dict, Optional
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
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]

# ==================== 🗄️ إدارة قاعدة البيانات ====================
@contextmanager
def get_db_cursor():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

# ==================== 🧠 المحرك المباشر (Live Memory Engine) ====================
def get_live_memory_prediction(suit: str, last_digit: int) -> Tuple[Optional[int], float, str]:
    """ 
    هذا هو العقل الجديد: يقرأ آخر 150 جولة فقط لتجاهل الماضي الميت.
    """
    try:
        with get_db_cursor() as (conn, cur):
            # نبحث في آخر 150 جولة عن نفس البذلة والرقم
            cur.execute("""
                SELECT winner 
                FROM history 
                WHERE suit = %s AND bonus_last_digit = %s AND winner IS NOT NULL 
                ORDER BY id DESC LIMIT 150
            """, (suit, last_digit))
            rows = cur.fetchall()
            
            if not rows or len(rows) < 3: 
                return None, 0.0, "بيانات حديثة غير كافية"
                
            recent_winners = [WINNER_MAP.get(r[0], 2) for r in rows]
            red_count = recent_winners.count(0)
            blue_count = recent_winners.count(1)
            total = red_count + blue_count
            
            if total == 0: return None, 0.0, ""
            
            # إذا كان النمط منحازاً بقوة في الماضي القريب، نتوقع العكس (Trend Reversal)
            # لأن اللعبة تكسر الأنماط الواضحة
            p_red = red_count / total
            if p_red > 0.65:
                return 1, (p_red * 100), f"موجة الراعي مشبعة (عكس الإشارة للثور 🔵)"
            elif (blue_count / total) > 0.65:
                return 0, ((blue_count / total) * 100), f"موجة الثور مشبعة (عكس الإشارة للراعي 🔴)"
                
            # إذا كانت النسب طبيعية، نتبع الترجيح البسيط
            best_winner = 0 if red_count > blue_count else 1
            conf = (max(red_count, blue_count) / total) * 100
            return best_winner, conf, f"مسار حديث ({red_count}🔴:{blue_count}🔵)"
    except Exception as e:
        logger.error(f"Live Engine Error: {e}")
    return None, 0.0, ""

def detect_streak_breaker() -> Tuple[Optional[int], float, str]:
    """مراقبة السلاسل اللحظية (آخر 4 جولات)"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 4")
            rows = cur.fetchall()
            if len(rows) < 3: return None, 0.0, ""
            
            recent = [WINNER_MAP.get(r[0], 2) for r in rows[:3]]
            
            if recent == [0, 0, 0]:
                return 1, 85.0, "⚠️ كسر السلسلة (توقع الثور 🔵)"
            elif recent == [1, 1, 1]:
                return 0, 85.0, "⚠️ كسر السلسلة (توقع الراعي 🔴)"
    except: pass
    return None, 0.0, ""

# ==================== ⚖️ V10 Core Engine ====================
def predict_v10(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])
    
    scores = {0: 0.0, 1: 0.0}
    logs = []
    
    # 1. الذاكرة الحية (Short-Term Memory & Inversion) - وزن ضخم جداً
    live_w, live_c, live_log = get_live_memory_prediction(suit, last_digit)
    if live_w is not None:
        scores[live_w] += live_c * 3.0
        logs.append(f"⏱️ **الذاكرة الحية:** {WINNER_NAMES[live_w]} [{live_log}]")
    
    # 2. كاسر السلاسل
    streak_w, streak_c, streak_log = detect_streak_breaker()
    if streak_w is not None:
        scores[streak_w] += streak_c * 2.0
        logs.append(f"🛡️ **الزخم:** {WINNER_NAMES[streak_w]} [{streak_log}]")

    # 3. الاعتماد الاحتياطي على البذلة (بشكل عام)
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT red_count, blue_count FROM pattern_stats WHERE pattern_id = %s", (f"SUIT_{suit}",))
            row = cur.fetchone()
            if row:
                red, blue = row
                if red != blue:
                    suit_w = 0 if red > blue else 1
                    suit_c = (max(red, blue) / (red + blue)) * 100
                    scores[suit_w] += suit_c * 1.0
                    logs.append(f"🎴 **التاريخ العام:** {WINNER_NAMES[suit_w]}")
    except: pass

    # ==================== الحساب النهائي ====================
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    if total_score == 0:
        return 2, 50, "🧮 **بيانات غير كافية للتوقع**"
        
    raw_conf = (scores[final_pred] / total_score) * 100
    confidence = int(min(99, max(50, raw_conf)))
    
    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

# ==================== 🎮 الواجهة ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🏛️ HADES V10 (The Quantum Flip)</b>\n\nتم تفعيل الذاكرة قصيرة المدى ونظام عكس الإشارة.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

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
                
            pred_code, confidence, reason = predict_v10(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير V10 (الذاكرة الحية)</b>
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
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 HADES V10 RUNNING...")
    app.run_polling(drop_pending_updates=True)
