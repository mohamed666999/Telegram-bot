import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية ---
HF_TOKEN = "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"
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai_hub(model_id, prompt):
    """دالة استدعاء الموديلات مع معالجة الأخطاء الذكية"""
    url = f"https://api-inference.huggingface.co/models/{model_id}"
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "inputs": f"System: Analyze mathematical patterns. User: {prompt}",
        "parameters": {"max_new_tokens": 200, "temperature": 0.1}
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code == 200:
            res = resp.json()
            # استخراج النص الصافي
            return res[0]['generated_text'].split("User:")[-1].strip() if isinstance(res, list) else res.get('generated_text', "خطأ في التنسيق")
        return f"ERR_{resp.status_code}"
    except:
        return "ERR_TIMEOUT"

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data: return
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("📡 **جاري الاتصال بمصفوفة Nvidia & Gemini...**")
        
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        raw_data = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                # قراءة آخر 15 جولة (بدون أي حذف)
                cur.execute("SELECT b_num, suit, winner, timestamp FROM history ORDER BY id DESC LIMIT 15")
                rows = cur.fetchall()
                for r in rows:
                    raw_data += f"B:{r[0]} | S:{r[1]} -> Win:{r[2]} | T:{r[3].strftime('%M:%S.%f')[:-3]}\n"
            conn.close()
        except: raw_data = "لا يوجد سجل."

        prompt = f"Data:\n{raw_data}\nCurrent: B:{text}, S:{context.user_data['suit']}, T:{current_time_str}\nPredict Win (Bull/Bear) and Formula:"

        # محاولة المحرك الأول (Nvidia Llama)
        prediction = ask_ai_hub("meta-llama/Meta-Llama-3-8B-Instruct", prompt)
        
        # إذا فشل الأول، جرب المحرك الثاني (Gemini/Gemma) تلقائياً
        if "ERR" in prediction:
            prediction = ask_ai_hub("google/gemma-1.1-7b-it", prompt)

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل الرقمي:**\n{prediction}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة الفعلية:")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

# (بقية دوال start و callback_handler تبقى كما هي تماماً)
