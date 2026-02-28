import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== الإعدادات السيادية المحدثة ====================

# المفتاح الصحيح الذي يبدأ بـ AIza
GEMINI_API_KEY = "AIzaSyDytcR8_Lz_LWBRJrwXXYQAsmPNtLGy434" 
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# الاعتماد على الجيل الثاني Gemini 2.0 و v1beta بناءً على تحليلك
MODEL_NAME = "gemini-2.0-flash" 
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"

# ==================== محرك الاستدلال Gemini 2.0 ====================

def ask_gemini_v2(prompt):
    """استدعاء محرك الجيل الثاني لفك شفرات الأنماط"""
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1, # دقة رياضية مطلقة
            "maxOutputTokens": 1000
        }
    }
    try:
        resp = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=20)
        data = resp.json()
        if resp.status_code == 200:
            return f"🌀 [Gemini 2.0 Flash Engine]\n{data['candidates'][0]['content']['parts'][0]['text'].strip()}"
        else:
            error_msg = data.get('error', {}).get('message', 'Unknown Error')
            return f"⚠️ تنبيه Gemini 2.0: {error_msg} (كود {resp.status_code})"
    except Exception as e:
        return f"❌ عطل في الاتصال بالمصفوفة: {str(e)}"

# ==================== نظام معالجة البيانات الذكي ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V90.0**\nتم تفعيل محرك **Gemini 2.0 Flash** عبر v1beta.\n\n"
        "النظام الآن في قمة استقراره. اختر النوع لبدء الرصد:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ رادار {data[2:]} نشط.\n📥 أرسل بونص الجولة (7-8 أرقام):")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        # حفظ البيانات في خيط منفصل لتجنب تجميد البوت
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
            await query.edit_message_text(f"✅ تم حفظ النتيجة: {winner}. المصفوفة تزداد ذكاءً.")
        except Exception as e:
            print(f"❌ خطأ قاعدة البيانات: {e}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً.") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🧠 **جاري تحليل الأنماط عبر جيل 2.0 الفائق...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # جلب البيانات التاريخية
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 30")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"ب:{rows[i][0]}|ف:{rows[i][1]}|ج:{gap}ث\n"
            conn.close()
        except Exception as e:
            print(f"❌ خطأ جلب البيانات: {e}")
            gap_report = "السجل الأولي فارغ."

        prompt = (f"أنت محرك تحليل احتمالات سيادي. حلل هذه البيانات التاريخية:\n{gap_report}\n"
                  f"المدخل الحالي: بونص {text}، النوع {context.user_data['suit']}، الوقت {time_str}.\n"
                  f"المطلوب: توقع النتيجة (ثور/راعي) مع شرح الخوارزمية الرياضية للفجوات الزمنية بدقة.")
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_gemini_v2, prompt)

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل السيادي (Gemini 2.0):**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون وتحديث المصفوفة.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("🚀 الكيان السيادي V90.0 يعمل الآن بنجاح...")
    app.run_polling()
