"""
HADES V11 - THE AI ORACLE
دمج نموذج NVIDIA الحي مع التحليل الإحصائي لتوقع مسار الروليت/الـ RNG لحظياً.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging, asyncio
from typing import Tuple, Dict, Optional
from contextlib import contextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s" 
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

# مفاتيح NVIDIA AI
NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

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

# ==================== 🤖 العقل الاصطناعي الحي (Live AI) ====================
class LiveAIEngine:
    def __init__(self):
        # مهلة 4 ثوانٍ فقط حتى لا يتأخر البوت عليك
        self.client = AsyncOpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL, timeout=4.0)

    async def get_ai_prediction(self, recent_history: list, current_b_num: str, suit: str, rank: str) -> Tuple[Optional[int], int, str]:
        try:
            prompt = f"""
            أنت خبير احتمالات في لعبة كازينو (الراعي 0 vs الثور 1).
            آخر 15 نتيجة للعبة هي: {recent_history} (حيث 0=راعي، 1=ثور، 2=تعادل).
            الجولة الحالية: الورقة [{suit} {rank}] ورقم البونص [{current_b_num}].
            المطلوب: هل يوجد نمط (Streak) يجب استمراره؟ أم أن اللعبة سترتد (Mean Reversion)؟
            حلل التسلسل وأعطني توقعك.
            أجب حصرياً بصيغة JSON:
            {{"winner": 0 or 1, "confidence": number between 50 and 95, "reason": "short explanation"}}
            """
            
            response = await self.client.chat.completions.create(
                model=NVIDIA_MODEL,
                messages=[
                    {"role": "system", "content": "You are a Casino AI reading patterns. Return ONLY strict JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2, max_tokens=150
            )
            content = response.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return int(data.get("winner", 2)), int(data.get("confidence", 50)), data.get("reason", "تحليل ذكي")
        except Exception as e:
            logger.error(f"AI API Error: {e}")
        return None, 0, "فشل الاتصال بالذكاء الاصطناعي"

ai_oracle = LiveAIEngine()

# ==================== 🧠 العقل الإحصائي (Stats Engine) ====================
def get_stats_prediction(suit: str, last_digit: int) -> Tuple[Optional[int], float, str]:
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT winner FROM history 
                WHERE suit = %s AND bonus_last_digit = %s AND winner IS NOT NULL 
                ORDER BY id DESC LIMIT 150
            """, (suit, last_digit))
            rows = cur.fetchall()
            
            if not rows or len(rows) < 3: return None, 0.0, "لا توجد بيانات كافية"
                
            recent_winners = [WINNER_MAP.get(r[0], 2) for r in rows]
            red_count = recent_winners.count(0)
            blue_count = recent_winners.count(1)
            total = red_count + blue_count
            
            if total == 0: return None, 0.0, ""
            
            p_red = red_count / total
            if p_red > 0.65:
                return 1, (p_red * 100), f"تصحيح إحصائي (لصالح الثور)"
            elif (blue_count / total) > 0.65:
                return 0, ((blue_count / total) * 100), f"تصحيح إحصائي (لصالح الراعي)"
                
            best_winner = 0 if red_count > blue_count else 1
            conf = (max(red_count, blue_count) / total) * 100
            return best_winner, conf, f"تاريخ حديث ({red_count}R:{blue_count}B)"
    except: pass
    return None, 0.0, ""

# ==================== ⚖️ V11 Integration (الدمج) ====================
async def predict_v11_oracle(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])
    
    scores = {0: 0.0, 1: 0.0}
    logs = []
    
    # 1. جلب آخر 15 جولة لتغذية الذكاء الاصطناعي
    recent_history = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 15")
            recent_history = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
            recent_history.reverse()
    except: pass

    # 2. استشارة الذكاء الاصطناعي الحي (NVIDIA AI)
    ai_pred, ai_conf, ai_log = await ai_oracle.get_ai_prediction(recent_history, clean_b, suit, rank)
    if ai_pred in [0, 1]:
        scores[ai_pred] += ai_conf * 1.5 # نعطي رأي الـ AI وزناً محترماً
        logs.append(f"🤖 **الذكاء الاصطناعي:** {WINNER_NAMES[ai_pred]} ({ai_log})")

    # 3. استشارة الإحصائيات (Stats Engine)
    stat_pred, stat_conf, stat_log = get_stats_prediction(suit, last_digit)
    if stat_pred is not None:
        scores[stat_pred] += stat_conf * 1.2
        logs.append(f"📊 **الإحصاء الحي:** {WINNER_NAMES[stat_pred]} ({stat_log})")

    # 4. الحساب النهائي
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    if total_score == 0:
        return 2, 50, "🧮 **بيانات غير كافية للتوقع**"
        
    raw_conf = (scores[final_pred] / total_score) * 100
    confidence = int(min(99, max(50, raw_conf)))
    
    # إذا اتفق العقلان، نعطي المستخدم إشارة ثقة عمياء
    if ai_pred == stat_pred:
        logs.append("\n🔥 **إجماع كلي (AI + STATS) - فرصة قوية!**")
        confidence = max(85, confidence)
    elif ai_pred is not None and stat_pred is not None:
        logs.append("\n⚠️ **اختلاف بين الـ AI والإحصاء - العب بحذر!**")
        confidence = min(65, confidence)

    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

# ==================== 🎮 الواجهة والتفاعل ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🏛️ HADES V11 (The AI Oracle)</b>\n\nيعمل الآن باستخدام <b>NVIDIA Live AI</b>.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

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
            
            # 🌟 رسالة الانتظار التفاعلية لأن الـ AI يحتاج ثانية للتفكير
            processing_msg = await update.message.reply_text("⏳ <b>يتم الآن استشارة الذكاء الاصطناعي (NVIDIA)...</b>", parse_mode='HTML')
            
            # استدعاء العقل الاصطناعي الحي
            pred_code, confidence, reason = await predict_v11_oracle(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير AI ORACLE (V11)</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>التوقع المرجح: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 مجريات التحليل:</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز الفعلي للتسجيل:"""
            
            # تحديث رسالة الانتظار لتصبح هي التوقع
            await processing_msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 HADES V11 (AI Oracle) RUNNING...")
    app.run_polling(drop_pending_updates=True)
