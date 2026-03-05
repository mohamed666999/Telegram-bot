import re
import logging
import psycopg2
import asyncio
from contextlib import contextmanager
from typing import Tuple, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
from openai import OpenAI
from telegram.error import BadRequest

# ---------------------------
# بياناتك
# ---------------------------
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084
OPENAI_API_KEY = "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"
OPENAI_BASE_URL = "https://integrate.api.nvidia.com/v1"

# ---------------------------
# إعدادات البوت و AI
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ai_client = OpenAI(
    base_url=OPENAI_BASE_URL,
    api_key=OPENAI_API_KEY
)

# ---------------------------
# الثوابت
# ---------------------------
WINNER_MAP = {"راعي": 0, "الراعي 🔴": 0, "ثور": 1, "الثور 🔵": 1, "تعادل": 2, "تعادل ⚪": 2}
WINNER_NAMES = {0: "الراعي 🔴", 1: "الثور 🔵", 2: "تعادل ⚪"}
SUITS = ["♦️", "♥️", "♠️", "♣️"]
CARD_VALUES = {"A": 14, "K": 13, "Q": 12, "J": 11, "10": 10, "9": 9, "8": 8, "7": 7, "6": 6, "5": 5, "4": 4, "3": 3, "2": 2}
RANK_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]
# ---------------------------
# قاعدة البيانات
# ---------------------------
@contextmanager
def db_cursor():
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=10)
        yield conn, conn.cursor()
    except Exception as e:
        logger.error(f"❌ خطأ قاعدة البيانات: {e}")
        if conn:
            conn.rollback()
        yield None, None
    finally:
        if conn:
            conn.close()

def ensure_tables():
    try:
        with db_cursor() as (conn, cur):
            if cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS history(
                        id SERIAL PRIMARY KEY,
                        suit TEXT,
                        rank TEXT,
                        bonus TEXT,
                        digit INT,
                        winner TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
                logger.info("✅ الجداول جاهزة")
    except Exception as e:
        logger.error(f"❌ خطأ في تهيئة الجداول: {e}")

# ---------------------------
# وظائف مساعدة
# ---------------------------
def clean_digits(text: str) -> str:
    return re.sub(r"\D", "", text)

def digit_engine(digit: int) -> Tuple[int, int]:
    try:
        with db_cursor() as (conn, cur):
            if not cur:
                return 2, 0
            cur.execute("SELECT winner FROM history WHERE digit=%s ORDER BY id DESC LIMIT 200", (digit,))            rows = cur.fetchall()
        if len(rows) < 10:
            return 2, 0
        red = sum(1 for r in rows if WINNER_MAP.get(r[0]) == 0)
        blue = sum(1 for r in rows if WINNER_MAP.get(r[0]) == 1)
        total = red + blue
        if total == 0:
            return 2, 0
        return (0, int(red/total*100)) if red > blue else (1, int(blue/total*100))
    except Exception as e:
        logger.error(f"❌ خطأ في digit_engine: {e}")
        return 2, 0

def suit_engine(suit: str) -> Tuple[int, int]:
    try:
        with db_cursor() as (conn, cur):
            if not cur:
                return 2, 0
            cur.execute("SELECT winner FROM history WHERE suit=%s ORDER BY id DESC LIMIT 300", (suit,))
            rows = cur.fetchall()
        if len(rows) < 20:
            return 2, 0
        red = sum(1 for r in rows if WINNER_MAP.get(r[0]) == 0)
        blue = sum(1 for r in rows if WINNER_MAP.get(r[0]) == 1)
        total = red + blue
        if total == 0:
            return 2, 0
        return (0, int(red/total*100)) if red > blue else (1, int(blue/total*100))
    except Exception as e:
        logger.error(f"❌ خطأ في suit_engine: {e}")
        return 2, 0

def pattern_engine(suit: str, rank: str, digit: int) -> Tuple[int, int]:
    try:
        with db_cursor() as (conn, cur):
            if not cur:
                return 2, 0
            cur.execute(
                "SELECT winner FROM history WHERE suit=%s AND rank=%s AND digit=%s ORDER BY id DESC LIMIT 100",
                (suit, rank, digit)
            )
            rows = cur.fetchall()
        if len(rows) < 5:
            return 2, 0
        red = sum(1 for r in rows if WINNER_MAP.get(r[0]) == 0)
        blue = sum(1 for r in rows if WINNER_MAP.get(r[0]) == 1)
        total = red + blue
        if total == 0:
            return 2, 0
        return (0, int(red/total*100)) if red > blue else (1, int(blue/total*100))    except Exception as e:
        logger.error(f"❌ خطأ في pattern_engine: {e}")
        return 2, 0

def math_engine(bonus: str, rank: str) -> Tuple[int, int]:
    try:
        padded = bonus.zfill(3)
        s = sum(int(d) for d in padded[-3:])
        val = CARD_VALUES.get(rank, 5)
        result = ((s * val) + int(padded[-1])) % 2
        return result, 50
    except:
        return 2, 0

def predict(suit: str, rank: str, bonus: str) -> Tuple[int, int]:
    try:
        digits = clean_digits(bonus)
        if not digits:
            return 2, 0
        digit = int(digits[-1])
        
        p1, c1 = pattern_engine(suit, rank, digit)
        p2, c2 = suit_engine(suit)
        p3, c3 = digit_engine(digit)
        p4, c4 = math_engine(digits, rank)
        
        votes = {0: 0, 1: 0, 2: 0}
        votes[p1] += c1 * 2.2
        votes[p2] += c2 * 1.2
        votes[p3] += c3 * 1.1
        votes[p4] += c4 * 0.7
        
        total_votes = sum(votes.values())
        if total_votes == 0:
            return 2, 0
            
        final = max(votes, key=votes.get)
        conf = int(votes[final] / total_votes * 100)
        return final, conf
    except Exception as e:
        logger.error(f"❌ خطأ في predict: {e}")
        return 2, 0

# ---------------------------
# دالة AI مع مهلة زمنية
# ---------------------------
async def ai_predict(suit: str, rank: str, bonus: str) -> dict:
    try:
        prompt = f"توقع نتيجة اللعبة للبذلة {suit}, الورقة {rank}, البونص {bonus} مع شرح سبب الاختيار في جملة واحدة مختصرة"
                # إضافة مهلة زمنية للطلب
        response = await asyncio.wait_for(
            asyncio.to_thread(
                ai_client.chat.completions.create,
                model="moonshotai/kimi-k2-instruct-0905",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                top_p=0.9,
                max_tokens=200
            ),
            timeout=15  # 15 ثانية مهلة
        )
        result_text = response.choices[0].message.content
        return {"text": result_text}
    except asyncio.TimeoutError:
        logger.warning("⏰ مهلة AI انتهت")
        return {"text": "⏳ جاري التحليل... (حاول مرة أخرى)"}
    except Exception as e:
        logger.error(f"❌ خطأ في AI: {e}")
        return {"text": "⚠️ تعذر الاتصال بالذكاء الاصطناعي"}

# ---------------------------
# دالة آمنة لتعديل الرسائل
# ---------------------------
async def safe_edit_message(query, text: str, reply_markup=None):
    try:
        if reply_markup:
            await query.edit_message_text(text, reply_markup=reply_markup)
        else:
            await query.edit_message_text(text)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass  # لا شيء نفعله، الرسالة نفسها
        elif "Message to edit not found" in str(e):
            # الرسالة اختفت، نرسل رسالة جديدة
            await query.message.reply_text(text, reply_markup=reply_markup)
        else:
            logger.error(f"❌ خطأ في edit_message: {e}")
    except Exception as e:
        logger.error(f"❌ خطأ غير متوقع في edit_message: {e}")

# ---------------------------
# أوامر تيليجرام
# ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # مسح حالة المستخدم السابقة
        context.user_data.clear()
        context.user_data["step"] = "start"
                kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="suit")]]
        await update.message.reply_text(
            "🏛️ **HADES TITAN**\n\nاختر البذلة للبدء:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
        logger.info(f"✅ /start من المستخدم {update.effective_user.id}")
    except Exception as e:
        logger.error(f"❌ خطأ في start: {e}")
        await update.message.reply_text("⚠️ حدث خطأ، حاول /start مرة أخرى")

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    
    try:
        # ✅ الإصلاح الرئيسي: answer() بدون cache_time
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        logger.info(f"🔘 زر {data} من المستخدم {user_id}")
        
        # === اختيار البذلة ===
        if data == "suit":
            kb = [[InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS]]
            kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_start")])
            await safe_edit_message(query, "🎴 اختر البذلة:", InlineKeyboardMarkup(kb))
            context.user_data["step"] = "choosing_suit"
        
        # === بعد اختيار البذلة ===
        elif data.startswith("s_"):
            suit = data.split("_")[1]
            context.user_data["suit"] = suit
            context.user_data["step"] = "choosing_rank"
            
            kb = [[InlineKeyboardButton(r, callback_data=f"r_{r}") for r in row] for row in RANK_LAYOUT]
            kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="suit")])
            await safe_edit_message(query, f"{suit} اختر الورقة:", InlineKeyboardMarkup(kb))
        
        # === بعد اختيار الورقة ===
        elif data.startswith("r_"):
            rank = data.split("_")[1]
            context.user_data["rank"] = rank
            context.user_data["step"] = "waiting_bonus"
            
            kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="suit")]]
            await safe_edit_message(
                query,                f"✅ الورقة: {context.user_data.get('suit')} {rank}\n\n📥 أرسل رقم البونص الآن:",
                InlineKeyboardMarkup(kb)
            )
        
        # === زر الرجوع ===
        elif data == "back_start":
            context.user_data.clear()
            context.user_data["step"] = "start"
            kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="suit")]]
            await safe_edit_message(query, "🏛️ **HADES TITAN**\n\nاختر البذلة للبدء:", InlineKeyboardMarkup(kb))
        
    except Exception as e:
        logger.error(f"❌ خطأ في callback: {e}")
        try:
            await query.answer("⚠️ حدث خطأ", show_alert=True)
        except:
            pass

async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        user_id = update.effective_user.id
        
        # التحقق من أن المستخدم في مرحلة انتظار البونص
        if context.user_data.get("step") != "waiting_bonus":
            kb = [[InlineKeyboardButton("🎴 البدء", callback_data="suit")]]
            await update.message.reply_text(
                "🏛️ **HADES TITAN**\nاختر البذلة أولاً:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='Markdown'
            )
            return
        
        digits = clean_digits(text)
        if len(digits) < 3:
            await update.message.reply_text("⚠️ أدخل رقم بونص صحيح (3 أرقام على الأقل)")
            return
        
        suit = context.user_data.get("suit")
        rank = context.user_data.get("rank")
        
        if not suit or not rank:
            await update.message.reply_text("⚠️ اختر الورقة أولاً عبر الأزرار")
            return
        
        # إرسال رسالة "جاري التحليل"
        analyzing_msg = await update.message.reply_text("🔄 جاري التحليل...")
        
        # الحساب التقليدي
        pred, conf = predict(suit, rank, digits)        
        # الذكاء الاصطناعي (مع التعامل مع الأخطاء)
        ai_result = await ai_predict(suit, rank, digits)
        
        # تحديث رسالة التحليل بالنتيجة
        await analyzing_msg.edit_text(
            f"""🎯 **نتيجة HADES TITAN**

📊 التحليل التقليدي:
{WINNER_NAMES[pred]}
الثقة: {conf}%

🤖 تحليل الذكاء الاصطناعي:
{ai_result['text']}

🔄 للتحليل مرة أخرى: اختر بذلة جديدة""",
            parse_mode='Markdown'
        )
        
        # إعادة تعيين الحالة
        context.user_data.clear()
        context.user_data["step"] = "start"
        
        logger.info(f"✅ تحليل مكتمل للمستخدم {user_id}")
        
    except Exception as e:
        logger.error(f"❌ خطأ في message: {e}")
        try:
            await update.message.reply_text("⚠️ حدث خطأ أثناء التحليل، حاول مرة أخرى")
        except:
            pass

# ---------------------------
# التشغيل
# ---------------------------
if __name__ == "__main__":
    logger.info("🚀 بدء HADES TITAN...")
    ensure_tables()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    
    logger.info("✅ البوت جاهز!")
    app.run_polling(drop_pending_updates=True)
