"""
HADES V-TITAN 2.1 - Gap-Aware Adaptive Algorithm
"""

import os
import re
import datetime
import psycopg2
import logging

from typing import Tuple
from contextlib import contextmanager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"

DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

ADMIN_ID = 6033203084

WINNER_MAP = {
'الراعي 🔴':0,'راعي':0,'🔴':0,
'الثور 🔵':1,'ثور':1,'🔵':1,
'تعادل ⚪':2,'تعادل':2,'⚪':2,
0:0,1:1,2:2
}

WINNER_NAMES = {
0:'الراعي 🔴',
1:'الثور 🔵',
2:'تعادل ⚪'
}

SUITS = ['♦️','♥️','♠️','♣️']

RANK_VALUE = {
"A":14,"K":13,"Q":12,"J":11,
"10":10,"9":9,"8":8,"7":7,
"6":6,"5":5,"4":4,"3":3,"2":2
}

RANKS_LAYOUT = [
["A","K","Q","J"],
["10","9","8","7"],
["6","5","4","3","2"]
]

# ================= DATABASE =================

@contextmanager
def get_db_cursor():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()

def ensure_columns():

    try:

        with get_db_cursor() as (conn,cur):

            cur.execute("""
            CREATE TABLE IF NOT EXISTS history(
            id SERIAL PRIMARY KEY,
            b_num VARCHAR(30),
            suit VARCHAR(5),
            rank VARCHAR(5),
            bonus_last_digit INT,
            winner VARCHAR(20),
            user_id BIGINT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_laws(
            law_name VARCHAR(120) PRIMARY KEY,
            law_pattern JSONB,
            success_count INT DEFAULT 0,
            fail_count INT DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE
            )
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_history_winner ON history(winner)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_history_time ON history(timestamp)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_laws_name ON ai_laws(law_name)")

            conn.commit()

    except Exception as e:
        logger.error(e)

# ================= TOOLS =================

def clean_digits(text:str)->str:

    if not text:
        return ""

    return re.sub(r"\D","",str(text))


def generate_progress_bar(p):

    filled=int(p/10)

    return "█"*filled+"░"*(10-filled)

# ================= GAP DETECTOR =================

def is_sequence_broken():

    try:

        with get_db_cursor() as (conn,cur):

            cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 3")

            rows=cur.fetchall()

            if len(rows)<3:
                return True

            diff=(datetime.datetime.utcnow()-rows[2][0]).total_seconds()/60

            if diff>15:
                return True

    except:

        return True

    return False

# ================= MARKOV =================

def get_markov_chain_prediction(sequence_broken):

    if sequence_broken:
        return 2,0,""

    try:

        with get_db_cursor() as (conn,cur):

            cur.execute("SELECT winner FROM history ORDER BY id DESC LIMIT 500")

            rows=cur.fetchall()

            if len(rows)<10:
                return 2,0,""

            hist=[WINNER_MAP.get(r[0],2) for r in rows]

            hist.reverse()

            seq=tuple(hist[-3:])

            counter={0:0,1:0,2:0}

            for i in range(len(hist)-3):

                if tuple(hist[i:i+3])==seq:

                    counter[hist[i+3]]+=1

            total=sum(counter.values())

            if total>=3:

                pred=max(counter,key=counter.get)

                conf=int(counter[pred]/total*100)

                return pred,conf,f"تكرار تسلسل {total}"

    except:

        pass

    return 2,0,""

# ================= MOMENTUM =================

def get_momentum(sequence_broken):

    if sequence_broken:
        return 2,0,""

    try:

        with get_db_cursor() as (conn,cur):

            cur.execute("SELECT winner FROM history ORDER BY id DESC LIMIT 20")

            rows=cur.fetchall()

            if len(rows)<10:
                return 2,0,""

            hist=[WINNER_MAP.get(r[0],2) for r in rows]

            red=hist.count(0)
            blue=hist.count(1)

            if red>=14:
                return 1,75,"تشبع الراعي"

            if blue>=14:
                return 0,75,"تشبع الثور"

    except:

        pass

    return 2,0,""

# ================= MEMORY =================

def get_memory_prediction(suit,rank,last_digit):

    queries=[
    (f"DB_{suit}_{rank}_{last_digit}","تطابق كامل"),
    (f"DB_{suit}_{rank}","تطابق قوي"),
    (f"DB_{suit}_ALL_{last_digit}","تطابق متوسط")
    ]

    try:

        with get_db_cursor() as (conn,cur):

            for name,desc in queries:

                cur.execute("SELECT success_count,fail_count,law_pattern->>'winner' FROM ai_laws WHERE law_name LIKE %s",(f"{name}%",))

                row=cur.fetchone()

                if row:

                    s,f,w=row

                    if s>f:

                        conf=int(s/(s+f)*100)

                        return int(w),conf,f"{desc} [{s}]"

    except:

        pass

    return 2,0,""

# ================= PREDICT =================

def predict_titan(b_num,suit,rank):

    clean_b=clean_digits(b_num)

    if not clean_b:
        return 2,0,"رقم غير صالح"

    digits=clean_b.zfill(3)

    last_digit=int(digits[-1])

    sequence_broken=is_sequence_broken()

    markov_pred,markov_conf,markov_desc=get_markov_chain_prediction(sequence_broken)

    mem_pred,mem_conf,mem_desc=get_memory_prediction(suit,rank,last_digit)

    mom_pred,mom_conf,mom_desc=get_momentum(sequence_broken)

    votes={0:0,1:0,2:0}

    logs=[]

    if markov_conf>0:
        votes[markov_pred]+=markov_conf*1.5
        logs.append(f"🧬 ماركوف {WINNER_NAMES[markov_pred]}")

    if mem_conf>0:
        votes[mem_pred]+=mem_conf*2
        logs.append(f"💾 ذاكرة {WINNER_NAMES[mem_pred]}")

    if mom_conf>0:
        votes[mom_pred]+=mom_conf
        logs.append(f"⚖️ زخم {WINNER_NAMES[mom_pred]}")

    if sum(votes.values())==0:

        s=sum(int(d) for d in digits[-3:])

        card_val=RANK_VALUE.get(rank,0)

        math_res=((s*card_val)+last_digit)%2

        votes[math_res]+=60

        logs.append("🧮 معادلة الورقة")

    pred=max(votes,key=votes.get)

    total=sum(votes.values())

    conf=int((votes[pred]/total)*100) if total else 50

    if sequence_broken:
        logs.append("⚠️ تم تجاهل التسلسل بسبب الانقطاع")

    return pred,conf,"\n".join(logs)

# ================= BOT =================

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):

    context.user_data.clear()

    kb=[[InlineKeyboardButton("🎴 اختيار البذلة",callback_data="choose_suit")]]

    await update.message.reply_text("🏛️ HADES V-TITAN جاهز للعمل",reply_markup=InlineKeyboardMarkup(kb))

# ================= MESSAGE =================

async def handle_message(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text=update.message.text

    num=clean_digits(text)

    if not num:
        return

    suit=context.user_data.get("suit")
    rank=context.user_data.get("rank")

    if not suit or not rank:
        return

    pred,conf,reason=predict_titan(num,suit,rank)

    bar=generate_progress_bar(conf)

    msg=f"""
🎯 تقرير TITAN

🃏 {suit} {rank}
📥 {num}

🏆 {WINNER_NAMES[pred]}
📊 {bar} {conf}%

{reason}
"""

    kb=[
    [InlineKeyboardButton("راعي 🔴",callback_data="save_0"),
     InlineKeyboardButton("ثور 🔵",callback_data="save_1")],
    [InlineKeyboardButton("تعادل ⚪",callback_data="save_2")]
    ]

    await update.message.reply_text(msg,reply_markup=InlineKeyboardMarkup(kb))

# ================= MAIN =================

if __name__=="__main__":

    ensure_columns()

    app=ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_message))

    logger.info("🚀 HADES TITAN ONLINE")

    app.run_polling()
