import re
import logging
import psycopg2
from contextlib import contextmanager
from typing import Tuple
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
logging.basicConfig(level=logging.INFO)
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
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()

def ensure_tables():
    with db_cursor() as (conn, cur):
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

# ---------------------------
# وظائف مساعدة
# ---------------------------
def clean_digits(text: str):
    return re.sub(r"\D", "", text)

def digit_engine(digit: int) -> Tuple[int, int]:
    with db_cursor() as (conn, cur):
        cur.execute("SELECT winner FROM history WHERE digit=%s ORDER BY id DESC LIMIT 200", (digit,))
        rows = cur.fetchall()
    if len(rows) < 10: return 2, 0
    red = sum(1 for r in rows if WINNER_MAP.get(r[0]) == 0)
    blue = sum(1 for r in rows if WINNER_MAP.get(r[0]) == 1)
    return (0, int(red/len(rows)*100)) if red>blue else (1, int(blue/len(rows)*100))

def suit_engine(suit: str) -> Tuple[int, int]:
    with db_cursor() as (conn, cur):
        cur.execute("SELECT winner FROM history WHERE suit=%s ORDER BY id DESC LIMIT 300", (suit,))
        rows = cur.fetchall()
    if len(rows) < 20: return 2,0
    red = sum(1 for r in rows if WINNER_MAP.get(r[0]) == 0)
    blue = sum(1 for r in rows if WINNER_MAP.get(r[0]) == 1)
    return (0,int(red/len(rows)*100)) if red>blue else (1,int(blue/len(rows)*100))

def pattern_engine(suit: str, rank: str, digit: int) -> Tuple[int,int]:
    with db_cursor() as (conn, cur):
        cur.execute("SELECT winner FROM history WHERE suit=%s AND rank=%s AND digit=%s ORDER BY id DESC LIMIT 100", (suit, rank, digit))
        rows = cur.fetchall()
    if len(rows)<5: return 2,0
    red=sum(1 for r in rows if WINNER_MAP.get(r[0])==0)
    blue=sum(1 for r in rows if WINNER_MAP.get(r[0])==1)
    return (0,int(red/len(rows)*100)) if red>blue else (1,int(blue/len(rows)*100))

def math_engine(bonus:str, rank:str):
    padded=bonus.zfill(3)
    s=sum(int(d) for d in padded[-3:])
    val=CARD_VALUES.get(rank,5)
    result=((s*val)+int(padded[-1]))%2
    return result,50

def predict(suit:str, rank:str, bonus:str):
    digits=clean_digits(bonus)
    digit=int(digits[-1])
    p1,c1=pattern_engine(suit,rank,digit)
    p2,c2=suit_engine(suit)
    p3,c3=digit_engine(digit)
    p4,c4=math_engine(digits,rank)
    votes={0:0,1:0,2:0}
    votes[p1]+=c1*2.2
    votes[p2]+=c2*1.2
    votes[p3]+=c3*1.1
    votes[p4]+=c4*0.7
    final=max(votes,key=votes.get)
    conf=int(votes[final]/sum(votes.values())*100)
    return final,conf

# ---------------------------
# دالة AI
# ---------------------------
async def ai_predict(suit:str, rank:str, bonus:str) -> dict:
    prompt=f"توقع نتيجة اللعبة للبذلة {suit}, الورقة {rank}, البونص {bonus} مع شرح سبب الاختيار"
    response = ai_client.chat.completions.create(
        model="moonshotai/kimi-k2-instruct-0905",
        messages=[{"role":"user","content":prompt}],
        temperature=0.6,
        top_p=0.9,
        max_tokens=300
    )
    result_text=response.choices[0].message.content
    return {"text":result_text}

# ---------------------------
# أوامر تيليجرام
# ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb=[[InlineKeyboardButton("اختيار البذلة", callback_data="suit")]]
    await update.message.reply_text("HADES TITAN\nابدأ التحليل", reply_markup=InlineKeyboardMarkup(kb))

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer(cache_time=0)  # مهم لتجنب تعليق الزر
        data = q.data

        if data == "suit":
            kb = [[InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS]]
            await q.edit_message_text("اختر البذلة", reply_markup=InlineKeyboardMarkup(kb))

        elif data.startswith("s_"):
            suit = data.split("_")[1]
            context.user_data["suit"] = suit
            kb = [[InlineKeyboardButton(r, callback_data=f"r_{r}") for r in row] for row in RANK_LAYOUT]
            await q.edit_message_text(f"{suit} اختر الورقة", reply_markup=InlineKeyboardMarkup(kb))

        elif data.startswith("r_"):
            rank = data.split("_")[1]
            context.user_data["rank"] = rank
            await q.edit_message_text("ارسل رقم البونص")

    except Exception as e:
        logger.error(f"Callback error: {e}")
        await q.edit_message_text("حدث خطأ، حاول مرة أخرى.")

async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=update.message.text
    digits=clean_digits(text)
    if not digits: return
    suit=context.user_data.get("suit")
    rank=context.user_data.get("rank")
    if not suit or not rank:
        await update.message.reply_text("اختر الورقة أولاً")
        return
    pred,conf=predict(suit,rank,digits)
    ai_result=await ai_predict(suit,rank,digits)
    await update.message.reply_text(
        f"""
النتيجة المتوقعة (تقليدية)
{WINNER_NAMES[pred]}
الثقة: {conf}%

الذكاء الاصطناعي يقول:
{ai_result['text']}
"""
    )

# ---------------------------
# التشغيل
# ---------------------------
if __name__=="__main__":
    ensure_tables()
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling()
