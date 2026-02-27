import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية ---
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
API_KEY_PRIMARY = "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"
API_KEY_NVIDIA = "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"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# --- دالة الذكاء الاصطناعي (مؤمنة بالكامل) ---
def ask_ai(model_name, api_key, prompt):
    print(f"🔄 جاري إرسال الطلب إلى: {model_name}...")
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://railway.app", # ضروري لـ OpenRouter
                "X-Title": "Poker Analysis Bot",       # ضروري لـ OpenRouter
                "Content-Type": "application/json"
            },
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 50
            },
            timeout=10 # أقصى مدة انتظار 10 ثواني
        )
        print(f"✅ تم استلام الرد من {model_name}: الكود {resp.status_code}")
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip()
        return f"خطأ سيرفر {resp.status_code}"
    except Exception as e:
        print(f"❌ فشل الاتصال مع {model_name}: {e}")
        return "فشل الاتصال"

# ==================== معالجات البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("👑 رويال", callback_data="h_رويال"), InlineKeyboardButton("✌️ زوجين", callback_data="h_زوجين")],
          [InlineKeyboardButton("🏠 فل هاوس", callback_data="h_فل_هاوس"), InlineKeyboardButton("🃏 الأكبر", callback_data="h_أكبر")]]
    await update.message.reply_text("🏛️ **الكيان V64.0 (النسخة المستقرة)**\nاختر اليد:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("h_"):
        context.user_data['hand'] = data[2:]
        kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️"),
               InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
        await query.edit_message_text(f"اليد: {data[2:]}\nاختر النوع:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text("📥 أرسل رقم البونص:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        print(f"💾 جاري حفظ النتيجة في قاعدة البيانات: {winner}")
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, hand, winner, timestamp) VALUES (%s, %s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], context.user_data['hand'], winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم الحفظ: {winner}")
            print("✅ تم الحفظ بنجاح!")
        except Exception as e:
            print(f"❌ خطأ في قاعدة البيانات عند الحفظ: {e}")
            await query.edit_message_text("⚠️ خطأ في الحفظ.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ ابدأ بـ /start أولاً")
            return
            
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("📡 **جاري التحليل...**")
        
        # 1. جلب التاريخ
        print("\n--- دورة تحليل جديدة ---")
        print("🗄️ جاري الاتصال بقاعدة البيانات لجلب التاريخ...")
        history = "فارغ"
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history ORDER BY id DESC LIMIT 5")
                rows = cur.fetchall()
                if rows: history = ", ".join([r[0] for r in rows])
            conn.close()
            print("✅ تم جلب التاريخ بنجاح.")
        except Exception as e:
            print(f"⚠️ فشل جلب التاريخ (القاعدة فارغة أو غير متصلة): {e}")

        prompt = f"التاريخ: {history}\nبونص: {text}, ورقة: {context.user_data['suit']}, يد: {context.user_data['hand']}. توقع (ثور/راعي) وثقة %"

        # 2. تشغيل النماذج (باستخدام Executor لتفادي تعليق البوت)
        loop = asyncio.get_event_loop()
        
        # نطلب من جيميناي
        g_task = loop.run_in_executor(None, ask_ai, "google/gemini-2.0-flash-001", API_KEY_PRIMARY, prompt)
        g_res = await g_task
        
        # نطلب من انفيديا
        n_task = loop.run_in_executor(None, ask_ai, "nvidia/llama-3.1-nemotron-70b-instruct", API_KEY_NVIDIA, prompt)
        n_res = await n_task

        print("🎉 انتهى التحليل، جاري إرسال الرد للمستخدم.")
        report = f"🎯 **نتائج التحليل:**\n\n🧠 Gemini: {g_res}\n🤖 Nvidia: {n_res}"
        kb = [[InlineKeyboardButton("🐂 ثور", callback_data="save_ثور"), InlineKeyboardButton("🐑 راعي", callback_data="save_راعي")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    print("🚀 بدء تشغيل البوت V64.0...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
