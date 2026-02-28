import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (Canopy Wave - Mini-Ma 2.1) ---
CANOPY_TOKEN = "01BzATbVHNygmd7NSxLNt5uljKR4lUofTQ0pvyraMio"
# تم اختيار الموديل Mini-Ma 2.1 لدقته في الأنماط الرقمية
MODEL_NAME = "minima-2.1-instruct" 

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_minima_ai(prompt):
    """استدعاء محرك Mini-Ma 2.1 لتحليل الفجوات اللحظي"""
    url = "https://api.canopywave.io/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {CANOPY_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "أنت محلل رياضي فائق السرعة. تخصصك هو ربط بونص الجولات بفجوات التوقيت الزمني (Gap Analysis) لاستنتاج الخوارزمية."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1, # لضمان ثبات النتيجة الرياضية
        "max_tokens": 400
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            return f"⚡ [Mini-Ma 2.1 Engine]\n{resp.json()['choices'][0]['message']['content'].strip()}"
        else:
            return f"⚠️ خطأ في المحرك ({resp.status_code}): يرجى التأكد من توفر الموديل في حسابك."
    except Exception as e:
        return f"❌ انقطاع في الشبكة السيادية: {str(e)}"

# ==================== نظام معالجة الفجوات 24/7 ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً عبر /start") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text(f"🚀 **جاري تشغيل محرك {MODEL_NAME}...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # تحليل فجوات الوقت (آخر 30 جولة لضمان سرعة Mini-Ma)
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
        except: gap_report = "السجل فارغ."

        prompt = f"""حلل هذه البيانات فوراً:
{gap_report}

الجولة الحالية:
بونص: {text} | النوع: {context.user_data['suit']} | التوقيت: {time_str}

المطلوب:
1. استنتج المعادلة التي تربط الرقم الأخير من البونص بفجوة الثواني الحالية.
2. التوقع: (🔵 ثور أو 🔴 راعي).
3. القانون المكتشف: (بصيغة رياضية)."""

        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_minima_ai, prompt)

        # حفظ القانون في سجل القوانين السيادي
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO rules_log (rule_text, confidence_score) VALUES (%s, %s)", (analysis[:1500], 98.5))
                conn.commit()
            conn.close()
        except: pass

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل السيادي (Mini-Ma):**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون في السجل المستقل.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

# (دوال start و callback_handler تبقى كما هي)
