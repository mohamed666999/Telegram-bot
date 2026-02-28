import os, sys, datetime, asyncio, psycopg2, requests, json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== الإعدادات السيادية (تم دمج المفتاح) ====================

GROQ_API_KEY = "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" 
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# ==================== محرك الاستدلال (Llama 3 70B via Groq) ====================

def ask_groq_engine(prompt):
    """محرك فائق السرعة مع معالجة التشفير لرموز الرموز العربي والإيموجي"""
    headers = {
        'Authorization': f'Bearer {GROQ_API_KEY}',
        'Content-Type': 'application/json; charset=utf-8'
    }
    payload = {
        "model": "llama3-70b-8192", 
        "messages": [
            {"role": "system", "content": "أنت محلل بيانات محترف. حلل فجوات الوقت وبونص الجولات لاستنتاج الخوارزمية. اجب بالعربية فقط."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 800
    }
    
    try:
        # ضمان تشفير البيانات بشكل صحيح لتجنب خطأ latin-1
        json_payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        resp = requests.post(GROQ_URL, headers=headers, data=json_payload, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            return f"⚡ [Groq LPU Engine]\n{data['choices'][0]['message']['content'].strip()}"
        else:
            return f"⚠️ تنبيه المحرك: (كود {resp.status_code}) - تأكد من صلاحية المفتاح."
    except Exception as e:
        return f"❌ خطأ في المصفوفة التقنية: {str(e)}"

# ==================== إدارة العمليات والبيانات ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V94.0 (Groq Activated)**\n"
        "تم ربط المصفوفة بمفتاح GSK بنجاح. السرعة الآن في أقصى حدودها.\n"
        "اختر النوع لبدء الرصد اللحظي:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ رادار {data[2:]} نشط.\n📥 أرسل بونص الجولة (7-8 أرقام):")
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
            await query.edit_message_text(f"✅ تم حفظ: {winner}. المصفوفة يتم تحديثها...")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً.") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔎 **جاري استنتاج النمط عبر محرك Llama 3 (Groq)...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # جلب سجل الفجوات لتعزيز دقة الاستنتاج
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 25")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"B:{rows[i][0]}|W:{rows[i][1]}|Gap:{gap}s\n"
            conn.close()
        except: gap_report = "السجل قيد البناء."

        prompt = (f"حلل الأنماط التالية:\n{gap_report}\n"
                  f"البيانات الحالية: بونص {text}، النوع {context.user_data['suit']}، التوقيت {time_str}\n"
                  f"توقع النتيجة (ثور/راعي) واشرح القانون الرياضي للفجوات باختصار.")
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_groq_engine, prompt)

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل السيادي (Groq):**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون وتحديث المصفوفة.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("🚀 الكيان السيادي يعمل بمحرك Groq الفائق...")
    app.run_polling()
