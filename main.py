import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (Hugging Face / Gemini) ---
HF_TOKEN = "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"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_gemini(prompt):
    # استخدام نموذج Gemini 1.5 Flash المجاني عبر Hugging Face Inference API
    API_URL = "https://api-inference.huggingface.co/models/google/gemma-2-9b-it"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    
    try:
        # صياغة البرومبت ليكون صارماً رياضياً
        payload = {
            "inputs": f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n",
            "parameters": {"max_new_tokens": 250, "temperature": 0.1}
        }
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=15)
        
        if resp.status_code == 200:
            result = resp.json()
            # تنظيف الرد من علامات الـ Markdown الخاصة بالموديل
            text = result[0]['generated_text'].split("model\n")[-1].strip()
            return text
        else:
            return f"⚠️ عذراً، المحرك مشغول حالياً ({resp.status_code})"
    except:
        return "❌ فشل الاتصال بالذكاء الاصطناعي"

# ==================== المعالجات الأساسية ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان V73.0 (Gemini Flash Engine)**\nالمحرك المجاني نشط. اختر النوع لبدء الاستنباط:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ النوع المختار: {data[2:]}\n📥 أرسل بونص الجولة:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                # حفظ الجولة (Data Persistence)
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم حفظ النتيجة: {winner}. تم تحديث الذاكرة.")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data: return
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔭 **جاري قراءة الأنماط الزمنية عبر Gemini...**")
        
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # سحب آخر 15 جولة للتحليل (قراءة فقط - لا حذف)
        raw_data = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, suit, winner, timestamp FROM history ORDER BY id DESC LIMIT 15")
                rows = cur.fetchall()
                for r in rows:
                    raw_data += f"• {r[0]} | {r[1]} | {r[2]} | {r[3].strftime('%M:%S.%f')[:-3]}\n"
            conn.close()
        except: raw_data = "لا توجد بيانات سابقة."

        prompt = f"""أنت خبير رياضيات وإحصاء. حلل هذه البيانات التاريخية واستنبط القاعدة القادمة:
{raw_data}

المعطيات الجديدة:
البونص: {text} | النوع: {context.user_data['suit']} | التوقيت: {current_time_str}

المطلوب بدقة:
1. ابحث عن نمط يربط بين آخر رقمين في البونص وبين أجزاء الثانية (Milliseconds).
2. التوقع: (🔵 ثور أو 🔴 راعي)
3. الثقة: %
4. القاعدة المبتكرة: (اشرح المعادلة الرياضية باختصار)"""

        loop = asyncio.get_event_loop()
        prediction = await loop.run_in_executor(None, ask_gemini, prompt)

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **تحليل Gemini:**\n{prediction}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة الفعلية لتطوير الخوارزمية:")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
