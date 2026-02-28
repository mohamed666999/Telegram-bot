import os, sys, datetime, asyncio, psycopg2, requests, json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== الإعدادات السيادية (المفتاح المحدث) ====================

# المفتاح الجديد الذي أرسلته
GROQ_API_KEY = "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" 
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# ==================== محرك الاستدلال الذكي (نظام التبديل) ====================

def ask_groq_failover(prompt):
    """محرك مزدوج: يحاول تشغيل Llama 3.3، وإذا فشل ينتقل لـ Mixtral فوراً"""
    models = ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "llama3-8b-8192"]
    
    headers = {
        'Authorization': f'Bearer {GROQ_API_KEY}',
        'Content-Type': 'application/json; charset=utf-8'
    }

    for model in models:
        payload = {
            "model": model, 
            "messages": [
                {"role": "system", "content": "أنت محلل بيانات محترف. حلل فجوات الوقت والأنماط الرقمية بدقة. أجب بالعربية."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }
        try:
            json_payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            resp = requests.post(GROQ_URL, headers=headers, data=json_payload, timeout=12)
            
            if resp.status_code == 200:
                data = resp.json()
                return f"⚡ [Groq Engine: {model}]\n{data['choices'][0]['message']['content'].strip()}"
            else:
                print(f"DEBUG: Model {model} failed with code {resp.status_code}")
                continue # جرب النموذج التالي في القائمة
        except Exception as e:
            print(f"DEBUG: Connection error with {model}: {e}")
            continue

    return "❌ فشل كامل في مصفوفة النماذج. تأكد من تفعيل الحساب في Groq Console."

# ==================== إدارة العمليات والبيانات ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V96.0 (Fail-Safe)**\n"
        "تم دمج المفتاح الجديد مع نظام التبديل التلقائي.\n"
        "الرادار جاهز للعمل 24/7. اختر النوع:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ رادار {data[2:]} نشط.\n📥 أرسل بونص الجولة:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        loop = asyncio.get_event_loop()
        try:
            def save_to_db():
                conn = psycopg2.connect(DATABASE_URL, sslmode='require')
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                               (context.user_data.get('bonus'), context.user_data.get('suit'), winner, datetime.datetime.now()))
                    conn.commit()
                conn.close()
            await loop.run_in_executor(None, save_to_db)
            await query.edit_message_text(f"✅ تم حفظ: {winner}. المصفوفة تتدرب.")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ استخدم /start أولاً.") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔎 **جاري استكشاف النمط عبر مصفوفة النماذج...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 25")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"B:{rows[i][0]}|W:{rows[i][1]}|G:{gap}s\n"
            conn.close()
        except: gap_report = "السجل قيد المزامنة."

        prompt = (f"Analyze time gaps:\n{gap_report}\n"
                  f"Input: Bonus {text}, Suit {context.user_data['suit']}, Time {time_str}\n"
                  f"Predict (Bull/Bear) and provide the math law.")
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_groq_failover, prompt)

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **تحليل الكيان السيادي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 المصفوفة مستقرة وتعمل بنظام التبادل.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("🚀 الرادار V96.0 يعمل الآن بمفتاح GSK المحدث...")
    app.run_polling()
