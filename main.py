import os
import sys
import datetime
import requests
import asyncio
import psycopg2
import joblib
import numpy as np
import pandas as pd
from psycopg2.extras import DictCursor
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== المتغيرات البيئية ====================
TOKEN = os.environ.get("TOKEN", "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "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")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway")

# نماذج OpenRouter المجانية (جربناها سابقاً)
OPENROUTER_MODELS = [
    "google/gemini-2.0-flash-exp",         # نموذج جوجل المجاني
    "nvidia/llama-3.1-nemotron-70b-instruct",  # نموذج Nvidia
    "meta-llama/llama-3.2-3b-instruct"     # احتياطي إضافي
]

# مسار حفظ النموذج المحلي (سيتم وضعه في مجلد مؤقت، Railway لا يحتفظ به بعد إعادة التشغيل)
# ولكن يمكننا تخزينه في قاعدة البيانات كـ bytea أو استخدام Bucket
LOCAL_MODEL_PATH = "/tmp/local_model.pkl"

# ==================== دوال قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_database():
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
            # جدول لتخزين النموذج المحلي (اختياري)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS model_store (
                    id SERIAL PRIMARY KEY,
                    model_name TEXT,
                    model_data BYTEA,
                    updated_at TIMESTAMP
                )
            """)
            conn.commit()

def db_fetch_all(query, params=()):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()

def db_execute(query, params=()):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()

# ==================== النموذج المحلي (RandomForest) ====================
def train_local_model():
    """تدريب نموذج غابة عشوائية على جميع البيانات التاريخية"""
    rows = db_fetch_all("SELECT b_num, suit, winner FROM history WHERE winner IN ('الثور 🔵', 'الراعي 🔴')")
    if len(rows) < 50:
        return None  # لا نبدأ قبل 50 جولة

    df = pd.DataFrame(rows)
    # تحويل الميزات
    df['bonus_last3'] = df['b_num'].astype(str).str[-3:].astype(int)
    df['suit_code'] = df['suit'].map({'♦️':0, '♥️':1, '♠️':2, '♣️':3}).fillna(0).astype(int)
    df['target'] = (df['winner'] == 'الثور 🔵').astype(int)

    X = df[['bonus_last3', 'suit_code']].values
    y = df['target'].values

    model = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42)
    model.fit(X, y)

    # حفظ النموذج (مؤقتاً)
    joblib.dump(model, LOCAL_MODEL_PATH)

    # اختيارياً: حفظ النموذج في قاعدة البيانات (للحفاظ عليه بعد إعادة التشغيل)
    with open(LOCAL_MODEL_PATH, 'rb') as f:
        model_data = f.read()
    db_execute("INSERT INTO model_store (model_name, model_data, updated_at) VALUES (%s, %s, %s) ON CONFLICT (model_name) DO UPDATE SET model_data = EXCLUDED.model_data, updated_at = EXCLUDED.updated_at",
               ('random_forest', model_data, datetime.datetime.now()))

    return model

def load_local_model():
    """تحميل النموذج المحلي من قاعدة البيانات إن وجد"""
    row = db_fetch_one("SELECT model_data FROM model_store WHERE model_name = 'random_forest' ORDER BY updated_at DESC LIMIT 1")
    if row:
        model_data = row['model_data']
        with open(LOCAL_MODEL_PATH, 'wb') as f:
            f.write(model_data)
        return joblib.load(LOCAL_MODEL_PATH)
    return None

def predict_local(bonus, suit):
    """توقع باستخدام النموذج المحلي"""
    model = load_local_model()
    if model is None:
        # حاول التدريب أولاً
        model = train_local_model()
        if model is None:
            return None, 0

    bonus_last3 = int(str(bonus)[-3:])
    suit_code = {'♦️':0, '♥️':1, '♠️':2, '♣️':3}.get(suit, 0)
    X = np.array([[bonus_last3, suit_code]])
    prob = model.predict_proba(X)[0]
    pred_class = model.predict(X)[0]
    result = "ثور" if pred_class == 1 else "راعي"
    confidence = int(prob[pred_class] * 100)
    return result, confidence

# ==================== دالة OpenRouter ====================
def ask_openrouter(prompt, model_index=0):
    """استدعاء OpenRouter مع التبديل التلقائي بين النماذج"""
    for i in range(len(OPENROUTER_MODELS)):
        model = OPENROUTER_MODELS[(model_index + i) % len(OPENROUTER_MODELS)]
        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 200
                },
                timeout=15
            )
            if response.status_code == 200:
                data = response.json()
                return data['choices'][0]['message']['content'], model
            else:
                print(f"OpenRouter error {response.status_code} with {model}")
        except Exception as e:
            print(f"Exception with {model}: {e}")
            continue
    return None, None

# ==================== دمج جميع المصادر ====================
async def get_hybrid_prediction(bonus, suit):
    """يجمع بين OpenRouter والنموذج المحلي"""
    # 1. جلب آخر 20 جولة للسياق
    rows = db_fetch_all("SELECT b_num, suit, winner FROM history ORDER BY id DESC LIMIT 20")
    history_text = "\n".join([f"{r['b_num']} {r['suit']} -> {r['winner']}" for r in rows]) or "لا توجد بيانات سابقة."

    prompt = f"""هذه جولات سابقة:
{history_text}

الجولة الحالية: بونص {bonus}، ورقة {suit}

قم بتحليل الأنماط وتوقع من سيفوز (راعي أم ثور) مع ذكر السبب ودرجة الثقة (0-100)."""

    # 2. استدعاء OpenRouter
    ai_response, used_model = ask_openrouter(prompt)

    # 3. توقع النموذج المحلي
    local_result, local_conf = predict_local(bonus, suit)

    # 4. بناء التقرير النهائي
    if ai_response:
        report = f"🧠 **تحليل OpenRouter ({used_model}):**\n{ai_response}\n\n"
    else:
        report = "⚠️ تعذر الاتصال بـ OpenRouter.\n"

    if local_result:
        report += f"📊 **النموذج المحلي:** يتوقع {local_result} (ثقة {local_conf}%)\n"

    report += "\n✅ اختر النتيجة الصحيحة:"
    return report

# ==================== دوال البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]
    ]
    await update.message.reply_text(
        "🎯 **بوت تحليل البوكر V73.4**\n\nاختر نوع الورقة المكشوفة:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )

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
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"الورقة: {context.user_data['suit']}\n\nأرسل رقم البونص (7-8 أرقام):")
        return

    if data.startswith("save_"):
        winner = data.split("_")[1]
        actual_winner = {"راعي": "الراعي 🔴", "ثور": "الثور 🔵", "تعادل": "تعادل ⚪"}[winner]

        db_execute(
            "INSERT INTO history (b_num, suit, hand, winner, timestamp) VALUES (%s, %s, %s, %s, %s)",
            (context.user_data.get('bonus'), context.user_data.get('suit'), "متنوع", actual_winner, datetime.datetime.now())
        )

        # بعد كل 10 جولات جديدة، نعيد تدريب النموذج المحلي
        count = db_fetch_one("SELECT COUNT(*) as c FROM history")['c']
        if count % 10 == 0:
            asyncio.create_task(asyncio.to_thread(train_local_model))  # تدريب غير متزامن

        await query.edit_message_text(
            f"{query.message.text}\n\n✅ تم الحفظ. النتيجة الفعلية: {actual_winner}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🆕 جولة جديدة", callback_data="new")]])
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر الورقة أولاً.")
            return

        context.user_data['bonus'] = text
        loading = await update.message.reply_text("🧠 جاري التحليل المتقدم...")

        report = await get_hybrid_prediction(text, context.user_data['suit'])

        kb = [
            [InlineKeyboardButton("🐂 ثور", callback_data="save_ثور")],
            [InlineKeyboardButton("🐑 راعي", callback_data="save_راعي")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")],
            [InlineKeyboardButton("🆕 جديد", callback_data="new")]
        ]
        await loading.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text("⚠️ الرقم غير صالح. يجب أن يكون 7-8 أرقام.")

def db_fetch_one(query, params=()):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()

# ==================== التشغيل ====================
if __name__ == "__main__":
    if not TOKEN or not OPENROUTER_API_KEY or not DATABASE_URL:
        print("❌ تأكد من وجود جميع المتغيرات البيئية")
        sys.exit(1)

    init_database()

    # محاولة تدريب النموذج المحلي عند بدء التشغيل
    try:
        train_local_model()
    except:
        pass

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("🚀 البوت V73.4 يعمل مع OpenRouter + نموذج محلي")
    app.run_polling()
