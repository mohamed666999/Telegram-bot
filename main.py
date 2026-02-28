import os, sys, datetime, asyncio, psycopg2, requests, json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== الإعدادات السيادية (محرك Groq) ====================

GROQ_API_KEY = "ضع_مفتاح_جروق_هنا" 
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# ==================== محرك الاستدلال (Llama 3 المصحح) ====================

def ask_groq_engine(prompt):
    """استدعاء محرك Llama 3 مع معالجة التشفير UTF-8"""
    headers = {
        'Authorization': f'Bearer {GROQ_API_KEY}',
        'Content-Type': 'application/json; charset=utf-8' # تحديد التشفير هنا
    }
    payload = {
        "model": "llama3-70b-8192", 
        "messages": [
            {"role": "system", "content": "You are a mathematical analyst. Analyze patterns in numbers and time gaps. Respond in Arabic."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    
    try:
        # تحويل البيانات إلى JSON مع التأكد من تشفيرها بـ UTF-8 قبل الإرسال
        json_payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        resp = requests.post(GROQ_URL, headers=headers, data=json_payload, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            return f"⚡ [Llama-3 via Groq]\n{data['choices'][0]['message']['content'].strip()}"
        else:
            return f"⚠️ تنبيه Groq: (كود {resp.status_code})"
    except Exception as e:
        return f"❌ خطأ تقني في التشفير: {str(e)}"

# ==================== إدارة البيانات والعمليات ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً.") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔎 **جاري معالجة البيانات وتأمين التشفير...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # جلب التاريخ
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 25")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    # تحويل الرموز لنصوص لتجنب مشاكل التشفير في السجلات القديمة
                    gap_report += f"B:{rows[i][0]}|W:{rows[i][1]}|G:{gap}s\n"
            conn.close()
        except: gap_report = "السجل قيد التحديث."

        # صياغة الـ Prompt بلغة نظيفة (English Keys + Arabic Request)
        prompt = (f"Analyze patterns:\n{gap_report}\n"
                  f"Input: Bonus {text}, Type {context.user_data['suit']}, Time {time_str}\n"
                  f"Predict (Bull/Bear) and show the formula.")
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_groq_engine, prompt)

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **تحليل الكيان (UTF-8 Optimized):**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم تصحيح مصفوفة التشفير.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

# (دوال start و callback_handler المعتادة)
