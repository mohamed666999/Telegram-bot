import os
import sys
import datetime
import requests
import asyncio
import psycopg2
from psycopg2.extras import DictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== المتغيرات البيئية (مهم جداً) ====================
TOKEN = os.environ.get("TOKEN", "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s")
HF_TOKEN = os.environ.get("HF_TOKEN", "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")  # مفتاح Hugging Face
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway")

# قائمة النماذج الاحتياطية (إذا فشل الأول، نجرب الثاني)
MODELS = [
    "meta-llama/Meta-Llama-3-8B-Instruct",   # نموذج قوي من Meta
    "google/gemma-1.1-7b-it",                 # نموذج Gemma من Google
    "mistralai/Mistral-7B-Instruct-v0.2"      # احتياطي إضافي
]

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

# ==================== دالة الاستدعاء الذكية ====================
def ask_huggingface(prompt, max_retries=2):
    """
    يحاول استدعاء نماذج Hugging Face بالتتابع حتى يعمل أحدها.
    """
    for model_id in MODELS:
        for attempt in range(max_retries):
            try:
                url = f"https://api-inference.huggingface.co/models/{model_id}"
                headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
                payload = {
                    "inputs": prompt,
                    "parameters": {
                        "max_new_tokens": 300,
                        "temperature": 0.3,
                        "return_full_text": False
                    }
                }
                response = requests.post(url, headers=headers, json=payload, timeout=25)
                
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0:
                        return data[0].get('generated_text', '❌ لا يوجد رد')
                    elif isinstance(data, dict) and 'generated_text' in data:
                        return data['generated_text']
                    else:
                        return str(data)
                elif response.status_code == 410:
                    # النموذج غير متاح، نجرب التالي
                    break  # خروج من محاولات هذا النموذج
                elif response.status_code == 503:
                    # النموذج قيد التحميل، ننتظر قليلاً
                    time.sleep(2)
                    continue
                else:
                    # خطأ آخر، نجرب النموذج التالي
                    break
            except Exception as e:
                print(f"خطأ مع {model_id}: {e}")
                continue
    return "⚠️ جميع النماذج غير متاحة حالياً، حاول لاحقاً."

# ==================== دوال البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]
    ]
    await update.message.reply_text(
        "🎯 **بوت تحليل البوكر V73.3**\n\nاختر نوع الورقة المكشوفة:",
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

    # حفظ النتيجة
    if data.startswith("save_"):
        winner = data.split("_")[1]
        actual_winner = {"راعي": "الراعي 🔴", "ثور": "الثور 🔵", "تعادل": "تعادل ⚪"}[winner]

        db_execute(
            "INSERT INTO history (b_num, suit, hand, winner, timestamp) VALUES (%s, %s, %s, %s, %s)",
            (context.user_data.get('bonus'), context.user_data.get('suit'), "متنوع", actual_winner, datetime.datetime.now())
        )
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
        loading = await update.message.reply_text("🧠 جاري تحليل البيانات...")

        # جلب آخر 15 جولة للسياق
        rows = db_fetch_all("SELECT b_num, suit, winner FROM history ORDER BY id DESC LIMIT 15")
        history_text = "\n".join([f"بونص {r['b_num']} {r['suit']} -> {r['winner']}" for r in rows]) or "لا توجد جولات سابقة."

        prompt = f"""هذه جولات سابقة:
{history_text}

الجولة الحالية: بونص {text}، ورقة {context.user_data['suit']}

بناءً على التحليل الإحصائي، هل تتوقع أن الفائز سيكون (الراعي) أم (الثور)؟ ولماذا؟"""

        # استدعاء Hugging Face
        ai_response = ask_huggingface(prompt)

        report = f"📊 **تحليل الذكاء الاصطناعي:**\n{ai_response}\n\n✅ اختر النتيجة الصحيحة:"
        kb = [
            [InlineKeyboardButton("🐂 ثور", callback_data="save_ثور")],
            [InlineKeyboardButton("🐑 راعي", callback_data="save_راعي")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")],
            [InlineKeyboardButton("🆕 جديد", callback_data="new")]
        ]
        await loading.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

    else:
        await update.message.reply_text("⚠️ الرقم غير صالح. يجب أن يكون 7-8 أرقام.")

# ==================== التشغيل ====================
if __name__ == "__main__":
    if not TOKEN or not HF_TOKEN or not DATABASE_URL:
        print("❌ تأكد من وجود جميع المتغيرات البيئية: TOKEN, HF_TOKEN, DATABASE_URL")
        sys.exit(1)

    init_database()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("🚀 البوت V73.3 يعمل مع نظام احتياطي متعدد النماذج...")
    app.run_polling()
