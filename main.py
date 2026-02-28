import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (Cloudflare AI) ---
# ملاحظة: Cloudflare يتطلب Account ID في الرابط والمفتاح في الهيدر
CLOUDFLARE_API_KEY = "skzW8mLqnWq9eqz2-D_kHZLUxZDf2azX_A3MkaPU"
ACCOUNT_ID = "087c2937528a4aa5b8b8c5e6d6f7a8b9" # تأكد من وضع Account ID الخاص بك هنا من لوحة تحكم Cloudflare

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_cloudflare_ai(prompt):
    """استدعاء محرك الذكاء الاصطناعي من Cloudflare"""
    # الرابط الافتراضي لنماذج Llama على Cloudflare
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-3-8b-instruct"
    headers = {"Authorization": f"Bearer {CLOUDFLARE_API_KEY}"}
    
    try:
        resp = requests.post(url, headers=headers, json={"prompt": prompt}, timeout=15)
        if resp.status_code == 200:
            result = resp.json()
            return result.get('result', {}).get('response', "⚠️ لم يتم استلام استجابة واضحة").strip()
        return f"⚠️ خطأ Cloudflare: {resp.status_code}"
    except:
        return "❌ فشل الاتصال بخادم الحافة (Edge Server)"

# ==================== المعالجات السيادية ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً عبر /start")
            return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("📡 **جاري الاتصال بمحرك Cloudflare وتحليل الفجوات...**")
        
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # تحليل فجوات الوقت (آخر 25 جولة) لربط القوانين
        all_data = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 25")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    all_data += f"B:{rows[i][0]} | W:{rows[i][1]} | Gap:{gap}s\n"
            conn.close()
        except: all_data = "سجل جديد."

        # بناء البرومبت الرياضي
        prompt = f"""[System: Analyze gaps and numbers]
History:
{all_data}

Current Task:
Bonus: {text} | Time: {current_time_str}
Target: Predict Bull/Bear and extract the formula based on the last 2 digits of bonus and the millisecond gap."""

        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_cloudflare_ai, prompt)

        # أرشفة القانون في سجل القوانين المستقل (Independent Rules Log)
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO rules_log (rule_text, confidence_score) VALUES (%s, %s)", (analysis[:1000], 92.5))
                conn.commit()
            conn.close()
        except: pass

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **تحليل Cloudflare السيادي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم تحديث السجل التاريخي والقوانين 24/7.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

# (بقية الدوال start و callback_handler تبقى كما هي لضمان عمل الأزرار)
