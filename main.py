import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات السيادية (Canopy Wave + OpenAI Hybrid) ---
CANOPY_TOKEN = "01BzATbVHNygmd7NSxLNt5uljKR4lUofTQ0pvyraMio"
OPENAI_KEY = "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"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_canopy_ai(prompt):
    """استدعاء محرك Canopy Wave للتحليل المعمق"""
    url = "https://api.canopywave.io/v1/chat/completions" # رابط الـ API الخاص بهم
    headers = {
        "Authorization": f"Bearer {CANOPY_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-reasoner", # أو الموديل الذي تفضله لديهم
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code == 200:
            return f"🔵 [Canopy Engine]\n{resp.json()['choices'][0]['message']['content'].strip()}"
    except: pass
    return None

def ask_backup_ai(prompt):
    """المحرك الاحتياطي (OpenAI) في حال فشل Canopy"""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
    try:
        resp = requests.post(url, headers=headers, json={"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}]}, timeout=15)
        if resp.status_code == 200:
            return f"🟢 [OpenAI Backup]\n{resp.json()['choices'][0]['message']['content'].strip()}"
    except: return "❌ تعذر الاتصال بكافة المحركات."

# ==================== نظام معالجة البيانات ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("📡 **جاري استخدام محرك Canopy Wave للتحليل...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # تحليل فجوات الوقت (آخر 35 جولة)
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 35")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"ب:{rows[i][0]}|ف:{rows[i][1]}|ج:{gap}ث\n"
            conn.close()
        except: gap_report = "السجل فارغ."

        prompt = f"Data Analysis:\n{gap_report}\nCurrent: Bonus {text}, Time {time_str}\nTask: Find numeric pattern & Predict Bull/Bear with Math Rule."

        # التنفيذ بنظام الأولوية
        analysis = ask_canopy_ai(prompt)
        if not analysis:
            analysis = ask_backup_ai(prompt)

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل السيادي (V80):**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم تحديث سجل القوانين 24/7.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# (دوال التشغيل start و callback تبقى كما هي)
