import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات السيادية (Gemini 3 Flash - الروابط المحدثة) ---
# تأكد من وضع المفتاح هنا
GEMINI_API_KEY = "AIzaSyAU3jS-GbbxMvNSjUlrqbau_vw5M14x-fc"
# تحديث اسم الموديل ليتوافق مع Gemini 3 Flash
MODEL_NAME = "gemini-3-flash" 
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_gemini_v3(prompt):
    """استدعاء محرك Gemini 3 Flash المحدث"""
    headers = {'Content-Type': 'application/json'}
    # هيكل الطلب المحدث لتجنب خطأ 400
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 800
        }
    }
    try:
        resp = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=20)
        data = resp.json()
        
        if resp.status_code == 200:
            # استخراج النص بمرونة أكبر
            return f"🌀 [Gemini 3 Flash Engine]\n{data['candidates'][0]['content']['parts'][0]['text'].strip()}"
        elif resp.status_code == 400:
            return f"⚠️ خطأ 400: يرجى التأكد من تفعيل موديل {MODEL_NAME} في Google AI Studio."
        else:
            return f"⚠️ استجابة غير متوقعة: كود {resp.status_code}\n{data.get('error', {}).get('message', '')}"
    except Exception as e:
        return f"❌ انقطاع في مصفوفة Gemini: {str(e)}"

# ==================== معالجة البيانات والأنماط ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً عبر /start") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🧠 **جاري تحليل الفجوات عبر Gemini 3 Flash...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # جلب السجل لتعزيز ذكاء Gemini 3
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 30")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"B:{rows[i][0]} | W:{rows[i][1]} | G:{gap}s\n"
            conn.close()
        except: gap_report = "السجل فارغ."

        # صياغة Prompt احترافي لـ Gemini 3
        full_prompt = (
            f"You are a mathematical pattern recognition engine. Analyze these gaps:\n{gap_report}\n"
            f"Current Input: Bonus {text}, Suit {context.user_data['suit']}, Time {time_str}.\n"
            f"Task: Predict Bull/Bear and provide the predictive mathematical formula based on time gaps."
        )
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_gemini_v3, full_prompt)

        report = (f"⏰ **رصد التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **تحليل الكيان السيادي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون وتحديث المصفوفة.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

# (دوال start و callback_handler تبقى كما هي لضمان استقرار الواجهة)
