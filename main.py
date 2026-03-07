import os
import re
import json
import math
import psycopg2
import datetime
from contextlib import contextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, CommandHandler, filters, ContextTypes
from openai import AsyncOpenAI

# ==================== معلومات المستخدم (مضافة مباشرة) ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
AI_API_KEY = "acv-d8351cddde4fbd194ee91aa7442600cd54b961bd1fe39fcf898831db50b3892b"

AI_MODEL = "gpt-5-mini"

ai_client = AsyncOpenAI(api_key=AI_API_KEY)

WINNER_MAP = {
"الراعي 🔴":0,
"الثور 🔵":1,
"تعادل ⚪":2
}

WINNER_NAMES = {
0:"الراعي 🔴",
1:"الثور 🔵",
2:"تعادل ⚪"
}

SUITS = ['♦️','♥️','♠️','♣️']

# ================= DATABASE =================

@contextmanager
def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()

def init_db():

    with get_db() as (conn,cur):

        cur.execute("""
        CREATE TABLE IF NOT EXISTS history(
        id SERIAL PRIMARY KEY,
        b_num TEXT,
        suit TEXT,
        rank TEXT,
        bonus_last_digit INT,
        winner TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_laws(
        id SERIAL PRIMARY KEY,
        formula TEXT,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.commit()

# ================= DATA =================

def clean_digits(t):

    if not t:
        return ""

    return re.sub(r"\D","",str(t))

def get_last_digit(b):

    c = clean_digits(b)

    if not c:
        return 0

    return int(c[-1])

# ================= AI LEARN =================

def read_all_rounds():

    with get_db() as (conn,cur):

        cur.execute("""
        SELECT bonus_last_digit,suit,winner,timestamp
        FROM history
        ORDER BY id
        """)

        rows = cur.fetchall()

    return rows

def build_dataset(rows):

    data=[]

    for i in range(len(rows)-1):

        digit = rows[i][0]
        suit = rows[i][1]
        winner = rows[i][2]

        t1 = rows[i][3]
        t2 = rows[i+1][3]

        gap = (t1 - t2).total_seconds()

        data.append({
        "digit":digit,
        "suit":suit,
        "gap":gap,
        "winner":winner
        })

    return data

async def ai_generate_formula(dataset):

    prompt=f"""
Create a mathematical formula predicting winner.

Variables:
digit
gap

Use:
sin
cos
log
sqrt
mod

Return JSON only:

{{
"formula":"...",
"description":"..."
}}

dataset:
{dataset[:200]}
"""

    r = await ai_client.chat.completions.create(
        model=AI_MODEL,
        messages=[{"role":"user","content":prompt}],
        temperature=0.2
    )

    txt = r.choices[0].message.content

    j = re.search(r"\{.*\}",txt,re.S)

    if j:
        return json.loads(j.group())

    return None

def save_formula(formula,desc):

    with get_db() as (conn,cur):

        cur.execute("""
        INSERT INTO ai_laws(formula,description)
        VALUES(%s,%s)
        """,(formula,desc))

        conn.commit()

# ================= EXECUTE LAW =================

def run_formula(digit,gap):

    score = (math.sin(digit)+math.sqrt(digit))*math.cos(gap/20)

    if score>0:
        return 1
    else:
        return 0

# ================= PREDICT =================

def predict(bonus):

    digit=get_last_digit(bonus)

    gap=18

    return run_formula(digit,gap)

# ================= BOT =================

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):

    kb=[
    [InlineKeyboardButton("AI Learn",callback_data="learn")]
    ]

    await update.message.reply_text(
    "HADES AI ENGINE",
    reply_markup=InlineKeyboardMarkup(kb)
    )

async def callback(update:Update,context:ContextTypes.DEFAULT_TYPE):

    q=update.callback_query
    await q.answer()

    if q.data=="learn":

        await q.edit_message_text("AI reading database...")

        rows=read_all_rounds()

        dataset=build_dataset(rows)

        law=await ai_generate_formula(dataset)

        if law:

            save_formula(law["formula"],law["description"])

            await q.edit_message_text(
            f"AI created new law\n\n{law['formula']}"
            )

        else:

            await q.edit_message_text("AI failed")

async def message(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text=update.message.text

    digit=clean_digits(text)

    if digit:

        p=predict(digit)

        await update.message.reply_text(
        f"Prediction: {WINNER_NAMES[p]}"
        )

# ================= RUN =================

if __name__=="__main__":

    init_db()

    app=ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))

    app.add_handler(CallbackQueryHandler(callback))

    app.add_handler(MessageHandler(filters.TEXT,message))

    print("BOT RUNNING")

    app.run_polling()
