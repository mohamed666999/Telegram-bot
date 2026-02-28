import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== الإعدادات السيادية (محرك Groq) ====================

# مفتاح جروق الخاص بك
GROQ_API_KEY = "ضغ_مفتاح_جروق_هنا" 
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# ==================== محرك الاستدلال (Llama 3 via Groq) ====================

def ask_groq_engine(prompt):
    """استدعاء محرك Llama 3 للتحليل فائق السرعة"""
    headers = {
        'Authorization': f'Bearer {GROQ_API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = {
        "model": "llama3-70b-8192", 
        "messages": [
            {"role": "system", "content": "أنت محلل بيانات رياضي خبير في استخراج الأنماط من فجوات الوقت وبونص الجولات. توقع النتيجة بدقة رياضية."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 1000
    }
    try:
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=15)
        data = resp.json()
        if resp.status_code == 200:
            return f"⚡ [Llama-3 via Groq]\n{data['choices'][0]['message']['content'].strip()}"
        else:
            error_info = data.get('error', {}).get('message', 'خطأ في المفتاح أو الخدمة')
            return f"⚠️ تنبيه Groq: {error_info} (كود {resp.status_code})"
    except Exception as e:
        return f"❌ انقطاع في مصفوفة جروق: {str(e)}"

# ==================== إدارة البيانات والعمليات ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V92.0 (Groq Edition)**\n"
        "تم تفعيل محرك Llama 3 70B للتحليل اللحظي.\n"
        "الرادار جاهز، اختر النوع:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ رادار {data[2:]} نشط.\n📥 أرسل رقم البونص:")
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
            await query.edit_message_text(f"✅ تم حفظ: {winner}. النمط تم تحديثه.")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً.") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔎 **جاري استنتاج النمط عبر محرك Groq...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # جلب التاريخ لتعزيز دقة Llama 3
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 25")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"ب:{rows[i][0]}|ف:{rows[i][1]}|ج:{gap}ث\n"
            conn.close()
        except: gap_report = "السجل قيد التكوين."

        prompt = (f"Analyze these time gaps and numbers:\n{gap_report}\n"
                  f"Input: Bonus {text}, Suit {context.user_data['suit']}, Time {time_str}\n"
                  f"Predict (Bull/Bear) and explain the math logic briefly.")
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_groq_engine, prompt)

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **تحليل الكيان (Llama 3):**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 المصفوفة مستقرة بنسبة 100%.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("🚀 الرادار يعمل بمحرك Groq الفائق...")
    app.run_polling()
