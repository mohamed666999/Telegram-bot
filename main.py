import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== الإعدادات السيادية (تم إدخال الـ APIs) ====================

# مفتاح Gemini الخاص بك (تم دمجه بناءً على طلبك)
GEMINI_API_KEY = "01BzATbVHNygmd7NSxLNt5uljKR4lUofTQ0pvyraMio" 
MODEL_NAME = "gemini-1.5-flash" 
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"

# إعدادات التليجرام وقاعدة البيانات
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# ==================== محرك الاستدلال والتحليل ====================

def ask_gemini_sovereign(prompt):
    """استدعاء محرك Gemini 1.5 Flash للتحليل الرقمي"""
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.1,  # لضمان ثبات النتيجة الرياضية
            "maxOutputTokens": 800
        }
    }
    try:
        resp = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=20)
        data = resp.json()
        if resp.status_code == 200:
            # استخراج النص من هيكل Google API الصحيح
            return f"🌀 [Gemini Sovereign Engine]\n{data['candidates'][0]['content']['parts'][0]['text'].strip()}"
        else:
            error_msg = data.get('error', {}).get('message', 'Unknown Error')
            return f"⚠️ تنبيه المحرك: {error_msg} (كود {resp.status_code})"
    except Exception as e:
        return f"❌ انقطاع في المصفوفة: {str(e)}"

# ==================== المعالجات الفنية للبوت ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V87.0**\nتم دمج محرك Gemini بنجاح. النظام يعمل 24/7.\nاختر النوع لبدء التحليل:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ رادار {data[2:]} نشط.\n📥 أرسل بونص الجولة (7-8 أرقام):")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data.get('bonus'), context.user_data.get('suit'), winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم حفظ الفوز لـ ({winner}). المصفوفة تتطور.")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ يرجى اختيار النوع أولاً عبر /start") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🧠 **جاري تحليل الفجوات الرقمية عبر Gemini...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # جلب السجل لبناء سياق التحليل
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 30")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"بونص:{rows[i][0]} | فوز:{rows[i][1]} | فجوة:{gap}ث\n"
            conn.close()
        except: gap_report = "السجل فارغ."

        prompt = (f"أنت محلل بيانات رياضي. حلل هذه الفجوات الزمنية:\n{gap_report}\n"
                  f"الحالي: بونص {text}، النوع {context.user_data['suit']}، الوقت {time_str}.\n"
                  f"المطلوب: توقع النتيجة القادمة (ثور/راعي) واكتب المعادلة الرياضية المستخدمة بناءً على فجوات الملي ثانية.")
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_gemini_sovereign, prompt)

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل السيادي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون في السجل المستقل.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

# ==================== التشغيل النهائي ====================

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
