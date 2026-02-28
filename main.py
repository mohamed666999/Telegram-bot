import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (Hugging Face - Stable Engine) ---
HF_TOKEN = "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"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai_free(prompt):
    # استخدام نموذج Llama-3-70B المجاني (بديل Gemini المستقر حالياً على HF)
    API_URL = "https://api-inference.huggingface.co/models/meta-llama/Meta-Llama-3-70B-Instruct"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    
    try:
        payload = {
            "inputs": prompt,
            "parameters": {"max_new_tokens": 200, "temperature": 0.1, "return_full_text": False}
        }
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=15)
        
        if resp.status_code == 200:
            result = resp.json()
            # استخراج النص النظيف
            return result[0]['generated_text'].strip() if isinstance(result, list) else result['generated_text'].strip()
        elif resp.status_code == 503:
            return "⏳ المحرك قيد التحميل.. أرسل البونص مرة أخرى بعد ثوانٍ."
        else:
            return f"⚠️ تنبيه فني ({resp.status_code})"
    except:
        return "❌ فشل الاتصال بالذكاء الاصطناعي"

# ==================== المعالجات ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان V73.1 (Stable Free Engine)**\nالمحرك جاهز. اختر النوع:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ النوع: {data[2:]}\n📥 أرسل بونص الجولة:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                # حفظ فقط دون مسح (Data Safety)
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم الحفظ: {winner}")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data: return
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔬 **جاري استنباط القاعدة الرياضية...**")
        
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        raw_data = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, suit, winner, timestamp FROM history ORDER BY id DESC LIMIT 15")
                rows = cur.fetchall()
                for r in rows:
                    raw_data += f"• B:{r[0]} | S:{r[1]} -> {r[2]} | T:{r[3].strftime('%M:%S.%f')[:-3]}\n"
            conn.close()
        except: raw_data = "السجل فارغ."

        # برومبت مُحسن للموديلات المجانية
        prompt = f"""تحليل رياضي فوريكس/احتمالات:
البيانات السابقة:
{raw_data}

المعطيات الجديدة: بونص {text}، ورقة {context.user_data['suit']}، توقيت {current_time_str}

المطلوب:
التوقع: (🔵 ثور أو 🔴 راعي)
الثقة: %
القاعدة المبتكرة: (معادلة تربط آخر رقمين في البونص مع الملي ثانية)"""

        loop = asyncio.get_event_loop()
        prediction = await loop.run_in_executor(None, ask_ai_free, prompt)

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **تحليل المحرك:**\n{prediction}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة الفعلية:")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
