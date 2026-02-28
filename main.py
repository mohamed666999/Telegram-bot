import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات السيادية (Gemini 1.5 Flash API) ---
# ضع مفتاح Gemini الخاص بك هنا (الذي يدعم النصوص والوسائط)
GEMINI_API_KEY = "ضغ_مفتاح_جيمناي_هنا" 
MODEL_NAME = "gemini-1.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_gemini_sovereign(prompt):
    """استدعاء محرك Gemini لتحليل الأنماط الرقمية والفجوات الزمنية"""
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{
            "parts": [{
                "text": f"أنت محلل خوارزميات سيادي. حلل فجوات الوقت (Gaps) والأرقام التالية بدقة لاستنتاج النتيجة القادمة: {prompt}"
            }]
        }],
        "generationConfig": {
            "temperature": 0.1,  # دقة رياضية عالية
            "topP": 0.95,
            "maxOutputTokens": 600,
        }
    }
    try:
        resp = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            result = resp.json()
            # استخراج النص من استجابة Gemini
            return f"💎 [Gemini 1.5 Flash]\n{result['candidates'][0]['content']['parts'][0]['text'].strip()}"
        else:
            return f"⚠️ استجابة Gemini غير طبيعية (كود {resp.status_code})"
    except Exception as e:
        return f"❌ خطأ في الاتصال بمصفوفة Gemini: {str(e)}"

# ==================== نظام معالجة البيانات اللحظي ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V85.0 (Gemini Edition)**\n"
        "تم دمج المحرك متعدد الوسائط لتحليل النصوص والفجوات 24/7.\n"
        "اختر النوع لبدء الرصد:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ رادار {data[2:]} نشط.\n📥 أرسل بونص الجولة الآن:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data.get('bonus'), context.user_data.get('suit'), winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم حفظ الفوز لـ ({winner}). مصفوفة البيانات تتحدث.")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً.") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🧬 **جاري المعالجة عبر Gemini 1.5 Flash...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # تحليل سجل الفجوات (آخر 30 جولة لضمان دقة Gemini)
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 30")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"بونص:{rows[i][0]}|فوز:{rows[i][1]}|فجوة:{gap}ث\n"
            conn.close()
        except: gap_report = "السجل الأولي فارغ."

        prompt = f"""تحليل أنماط:\n{gap_report}\nالحالي: بونص {text}، نوع {context.user_data['suit']}، توقيت {time_str}.\nالتوقع: (ثور/راعي) مع ذكر المعادلة الرياضية للفجوات المستخدمة."""
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_gemini_sovereign, prompt)

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **تحليل Gemini السيادي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون وتحديث المصفوفة.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
