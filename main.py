import os
import sys
import datetime
import requests
import asyncio
import psycopg2
from psycopg2.extras import DictCursor
from collections import Counter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== المتغيرات البيئية (مكتوبة مباشرة) ====================
# أنا وضعت التوكن والـ API Keys هنا نيابة عنك
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
API_KEY_PRIMARY = "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"
API_KEY_NVIDIA = "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"
DATABASE_URL = os.getenv("DATABASE_URL")  # هذا يأتي من Railway تلقائياً

# التحقق من وجود DATABASE_URL فقط
if not DATABASE_URL:
    print("❌ خطأ: DATABASE_URL غير موجود. تأكد من إضافة PostgreSQL في Railway")
    sys.exit(1)

# ==================== إعدادات النماذج ====================
MODEL_GEMINI = "google/gemini-2.0-flash-001"
MODEL_NVIDIA = "nvidia/llama-3.1-nemotron-70b-instruct"

# ==================== دوال قاعدة البيانات PostgreSQL ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_database():
    """إنشاء الجداول إذا لم تكن موجودة"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id SERIAL PRIMARY KEY,
                    b_num TEXT,
                    suit TEXT,
                    hand TEXT,
                    winner TEXT,
                    timestamp TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS model_performance (
                    id SERIAL PRIMARY KEY,
                    model_name TEXT,
                    hand_type TEXT,
                    suit_type TEXT,
                    bonus_pattern TEXT,
                    total_predictions INTEGER DEFAULT 0,
                    correct_predictions INTEGER DEFAULT 0,
                    accuracy REAL DEFAULT 0,
                    last_updated TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS prediction_history (
                    id SERIAL PRIMARY KEY,
                    b_num TEXT,
                    suit TEXT,
                    hand TEXT,
                    actual_winner TEXT,
                    gemini_pred TEXT,
                    nvidia_pred TEXT,
                    correct_model TEXT,
                    timestamp TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gemini_memory (
                    id SERIAL PRIMARY KEY,
                    b_num TEXT,
                    suit TEXT,
                    hand TEXT,
                    winner TEXT,
                    timestamp TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS nvidia_memory (
                    id SERIAL PRIMARY KEY,
                    b_num TEXT,
                    suit TEXT,
                    hand TEXT,
                    winner TEXT,
                    timestamp TIMESTAMP
                )
            """)
            conn.commit()

def db_execute(query, params=()):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()

def db_fetch_all(query, params=()):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()

def db_fetch_one(query, params=()):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()

# ==================== دوال تحديث الأداء ====================
def update_model_performance(model_name, hand_type, suit_type, bonus, was_correct):
    bonus_pattern = bonus[-3:] if bonus and len(bonus) >= 3 else "000"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, total_predictions, correct_predictions
                FROM model_performance
                WHERE model_name = %s AND hand_type = %s AND suit_type = %s AND bonus_pattern = %s
            """, (model_name, hand_type, suit_type, bonus_pattern))
            row = cur.fetchone()
            if row:
                pid, total, correct = row
                new_total = total + 1
                new_correct = correct + (1 if was_correct else 0)
                new_acc = (new_correct / new_total) * 100
                cur.execute("""
                    UPDATE model_performance
                    SET total_predictions = %s, correct_predictions = %s, accuracy = %s, last_updated = %s
                    WHERE id = %s
                """, (new_total, new_correct, new_acc, datetime.datetime.now(), pid))
            else:
                acc = 100 if was_correct else 0
                cur.execute("""
                    INSERT INTO model_performance
                    (model_name, hand_type, suit_type, bonus_pattern, total_predictions, correct_predictions, accuracy, last_updated)
                    VALUES (%s, %s, %s, %s, 1, %s, %s, %s)
                """, (model_name, hand_type, suit_type, bonus_pattern, 1 if was_correct else 0, acc, datetime.datetime.now()))
            conn.commit()

def get_best_model_for_current(hand_type, suit_type, bonus):
    bonus_pattern = bonus[-3:] if bonus and len(bonus) >= 3 else "000"
    row = db_fetch_one("""
        SELECT model_name, accuracy, total_predictions
        FROM model_performance
        WHERE hand_type = %s AND suit_type = %s AND bonus_pattern = %s
        ORDER BY accuracy DESC, total_predictions DESC
        LIMIT 1
    """, (hand_type, suit_type, bonus_pattern))
    if row and row['total_predictions'] >= 5:
        return row['model_name'], row['accuracy']
    return None, 0

def save_prediction_result(b_num, suit, hand, actual_winner, gemini_pred, nvidia_pred, correct_model):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO prediction_history
                (b_num, suit, hand, actual_winner, gemini_pred, nvidia_pred, correct_model, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (b_num, suit, hand, actual_winner, gemini_pred, nvidia_pred, correct_model, datetime.datetime.now()))
            cur.execute("""
                INSERT INTO gemini_memory (b_num, suit, hand, winner, timestamp)
                VALUES (%s, %s, %s, %s, %s)
            """, (b_num, suit, hand, actual_winner, datetime.datetime.now()))
            cur.execute("""
                INSERT INTO nvidia_memory (b_num, suit, hand, winner, timestamp)
                VALUES (%s, %s, %s, %s, %s)
            """, (b_num, suit, hand, actual_winner, datetime.datetime.now()))
            conn.commit()

def read_public_history(limit=150):
    rows = db_fetch_all("SELECT b_num, suit, hand, winner FROM history ORDER BY id DESC LIMIT %s", (limit,))
    if not rows:
        return "لا توجد بيانات كافية."
    text = f"قاعدة البيانات العامة (آخر {len(rows)} جولة):\n" + "="*50 + "\n"
    for i, r in enumerate(rows, 1):
        text += f"جولة {i}: بونص={r['b_num']}, اليد={r['hand']}, الورقة={r['suit']}, النتيجة={r['winner']}\n"
    text += "="*50
    return text

def read_model_memory(model_name, limit=50):
    table = "gemini_memory" if model_name == "Gemini" else "nvidia_memory"
    rows = db_fetch_all(f"SELECT b_num, suit, hand, winner FROM {table} ORDER BY id DESC LIMIT %s", (limit,))
    if not rows:
        return f"لا توجد ذاكرة سابقة لـ {model_name}."
    text = f"ذاكرة {model_name} (آخر {len(rows)} جولة):\n" + "="*40 + "\n"
    for i, r in enumerate(rows, 1):
        text += f"جولة {i}: بونص={r['b_num']}, الورقة={r['suit']}, اليد={r['hand']}, النتيجة={r['winner']}\n"
    text += "="*40
    return text

# ==================== دوال التوقع عبر OpenRouter ====================
async def get_nvidia_prediction(bonus, suit, hand):
    public = read_public_history(100)
    memory = read_model_memory("Nvidia", 50)
    prompt = f"""أنت خبير في تحليل البوكر. إليك البيانات:

[البيانات العامة]
{public}

[ذاكرتك الخاصة]
{memory}

الجولة الحالية:
- بونص: {bonus}
- نوع الورقة: {suit}
- اليد: {hand}

أجب فقط بالتنسيق:
النتيجة: (ثور أو راعي)
الثقة: (رقم 0-100)
"""
    try:
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY_NVIDIA}", "Content-Type": "application/json"},
            json={"model": MODEL_NVIDIA, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
            timeout=15)
        if resp.status_code == 200:
            content = resp.json()['choices'][0]['message']['content']
            lines = content.lower().split('\n')
            result = "راعي"
            conf = 50
            for line in lines:
                if 'النتيجة:' in line:
                    result = "ثور" if 'ثور' in line else "راعي"
                elif 'الثقة:' in line:
                    try:
                        conf = int(''.join(filter(str.isdigit, line)))
                    except:
                        pass
            return result, conf
    except Exception as e:
        print("Nvidia error:", e)
    return "راعي", 50

async def get_gemini_prediction(bonus, hand):
    public = read_public_history(100)
    memory = read_model_memory("Gemini", 50)
    prompt = f"""أنت خبير ذكاء اصطناعي أول في البوكر. إليك البيانات:

[البيانات العامة]
{public}

[ذاكرتك الخاصة]
{memory}

الجولة الحالية:
- بونص: {bonus}
- اليد: {hand}
(الورقة المكشوفة غير متوفرة)

أجب فقط بالتنسيق:
النتيجة: (ثور أو راعي)
الثقة: (رقم 0-100)
"""
    try:
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY_PRIMARY}", "Content-Type": "application/json"},
            json={"model": MODEL_GEMINI, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
            timeout=15)
        if resp.status_code == 200:
            content = resp.json()['choices'][0]['message']['content']
            lines = content.lower().split('\n')
            result = "راعي"
            conf = 50
            for line in lines:
                if 'النتيجة:' in line:
                    result = "ثور" if 'ثور' in line else "راعي"
                elif 'الثقة:' in line:
                    try:
                        conf = int(''.join(filter(str.isdigit, line)))
                    except:
                        pass
            return result, conf
    except Exception as e:
        print("Gemini error:", e)
    return "راعي", 50

def get_observer_recommendation(hand, suit, bonus, gemini_conf, nvidia_conf):
    best_model, acc = get_best_model_for_current(hand, suit, bonus)
    if best_model:
        return best_model, f"🔍 المراقب يوصي باستخدام **{best_model}** (دقة {acc:.1f}% في هذا النوع)"
    if gemini_conf > nvidia_conf + 10:
        return "Gemini", f"🔍 المراقب يوصي باستخدام **Gemini** (ثقة {gemini_conf}%)"
    if nvidia_conf > gemini_conf + 10:
        return "Nvidia", f"🔍 المراقب يوصي باستخدام **Nvidia** (ثقة {nvidia_conf}%)"
    return None, "🔍 المراقب: لا توجد توصية واضحة."

async def analyze(bonus, suit, hand):
    nvidia_task = get_nvidia_prediction(bonus, suit, hand)
    gemini_task = get_gemini_prediction(bonus, hand)
    (nvidia_res, nvidia_conf), (gemini_res, gemini_conf) = await asyncio.gather(nvidia_task, gemini_task)
    rec_model, rec_text = get_observer_recommendation(hand, suit, bonus, gemini_conf, nvidia_conf)
    report = (
        f"📊 **تحليل النماذج:**\n"
        f"━━━━━━━━━━━━\n"
        f"🧠 **Gemini** (بدون ورقة): {gemini_res} (ثقة {gemini_conf}%)\n"
        f"🤖 **Nvidia** (مع ورقة): {nvidia_res} (ثقة {nvidia_conf}%)\n"
        f"━━━━━━━━━━━━\n"
        f"{rec_text}\n"
        f"━━━━━━━━━━━━\n"
        f"✅ اختر النتيجة الصحيحة:"
    )
    return report, gemini_res, nvidia_res

# ==================== أوامر البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    count_row = db_fetch_one("SELECT COUNT(*) as c FROM history")
    count = count_row['c'] if count_row else 0
    kb = [
        [InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]
    ]
    await update.message.reply_text(
        f"🎯 **بوت تحليل البوكر**\n📊 قاعدة البيانات: {count} جولة\n\nاختر نوع الورقة المكشوفة:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_row = db_fetch_one("SELECT COUNT(*) as c FROM history")
    total = total_row['c'] if total_row else 0
    rows = db_fetch_all("SELECT model_name, SUM(correct_predictions) as corr, SUM(total_predictions) as tot FROM model_performance GROUP BY model_name")
    msg = f"📊 **إحصائيات الأداء:**\nإجمالي الجولات: {total}\n\n"
    for r in rows:
        acc = (r['corr']/r['tot']*100) if r['tot'] else 0
        msg += f"• {r['model_name']}: {r['corr']}/{r['tot']} ({acc:.1f}%)\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "new":
        context.user_data.clear()
        kb = [
            [InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
            [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]
        ]
        await query.edit_message_text("اختر نوع الورقة المكشوفة:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("s_"):
        context.user_data['last_suit'] = data[2:]
        context.user_data['suit_selected'] = True
        await query.edit_message_text(f"الورقة: {context.user_data['last_suit']}\n\nأرسل رقم البونص (7-8 أرقام):")
        return

    if data.startswith("result_"):
        actual = {"result_bull": "ثور", "result_bear": "راعي", "result_tie": "تعادل"}[data]
        gemini_pred = context.user_data.get('gemini_pred', '')
        nvidia_pred = context.user_data.get('nvidia_pred', '')
        gemini_correct = (gemini_pred == actual)
        nvidia_correct = (nvidia_pred == actual)

        # حفظ في history
        db_execute("INSERT INTO history (b_num, suit, hand, winner, timestamp) VALUES (%s,%s,%s,%s,%s)",
                   (context.user_data['last_bonus'], context.user_data['last_suit'], "متنوع", actual, datetime.datetime.now()))

        # تحديث أداء كل نموذج
        update_model_performance("Gemini", "متنوع", context.user_data['last_suit'], context.user_data['last_bonus'], gemini_correct)
        update_model_performance("Nvidia", "متنوع", context.user_data['last_suit'], context.user_data['last_bonus'], nvidia_correct)

        # تحديد النموذج الصحيح
        if gemini_correct and nvidia_correct:
            correct = "كلاهما"
        elif gemini_correct:
            correct = "Gemini"
        elif nvidia_correct:
            correct = "Nvidia"
        else:
            correct = "لا أحد"

        save_prediction_result(context.user_data['last_bonus'], context.user_data['last_suit'], "متنوع",
                               actual, gemini_pred, nvidia_pred, correct)

        await query.edit_message_text(
            f"{query.message.text}\n\n✅ تم الحفظ. النتيجة الفعلية: {actual}\n"
            f"🧠 Gemini: {'✅' if gemini_correct else '❌'} | 🤖 Nvidia: {'✅' if nvidia_correct else '❌'}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🆕 جولة جديدة", callback_data="new")]])
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in (7,8):
        if not context.user_data.get('suit_selected'):
            await update.message.reply_text("⚠️ اختر الورقة أولاً.")
            return
        loading = await update.message.reply_text("📊 جاري التحليل...")
        report, gemini_pred, nvidia_pred = await analyze(text, context.user_data['last_suit'], "متنوع")
        context.user_data.update({'last_bonus': text, 'gemini_pred': gemini_pred, 'nvidia_pred': nvidia_pred})
        kb = [
            [InlineKeyboardButton("🐂 ثور", callback_data="result_bull")],
            [InlineKeyboardButton("🐑 راعي", callback_data="result_bear")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="result_tie")],
            [InlineKeyboardButton("🆕 جديد", callback_data="new")]
        ]
        await loading.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text("⚠️ البونص يجب أن يكون 7-8 أرقام.")

# ==================== تشغيل البوت ====================
if __name__ == "__main__":
    print("🚀 بدء تشغيل البوت...")
    init_database()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("✅ البوت يعمل بنجاح!")
    app.run_polling()