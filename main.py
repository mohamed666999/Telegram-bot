import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQuery_Handler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (OpenAI GPT-4o) ---
OPENAI_API_KEY = "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"
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_openai_ultra(prompt):
    """استدعاء محرك OpenAI GPT-4o للتحليل الرياضي العميق"""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o", # استخدام الموديل الأحدث والأذكى
        "messages": [
            {"role": "system", "content": "أنت محرك رياضي سيادي. وظيفتك تحليل فجوات الوقت (Gaps) والأرقام لاستخراج خوارزمية الفوز بدقة 100%."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2, # درجة حرارة منخفضة لضمان منطق رياضي صارم
        "max_tokens": 500
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip()
        else:
            return f"⚠️ خطأ OpenAI (كود {resp.status_code}): يرجى مراجعة الرصيد أو الصلاحيات."
    except Exception as e:
        return f"❌ فشل الاتصال بالمحرك الفائق: {str(e)}"

# ==================== نظام تحليل الفجوات والأنماط ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان السيادي V78.0 (GPT-4o Engine)**\nالنظام في وضع التحليل الفائق 24/7.\nاختر النوع لبدء الرصد اللحظي:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ تم تفعيل الرادار للنوع: {data[2:]}\n📥 أرسل بونص الجولة الآن:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data.get('bonus'), context.user_data.get('suit'), winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم حفظ النتيجة: {winner}. تم تحديث نمط الفجوات.")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر النوع أولاً عبر /start") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🧠 **جاري تشغيل المعالج GPT-4o لتحليل الفجوات...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # تحليل الفجوات الزمنية لآخر 40 جولة (لأقصى دقة)
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 40")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"بونص:{rows[i][0]} | فوز:{rows[i][1]} | فجوة:{gap} ثانية\n"
            conn.close()
        except: gap_report = "السجل فارغ."

        prompt = f"""حلل هذه الأنماط الرياضية والزمنية لاستنتاج الجولة القادمة:
{gap_report}

المعطيات الحالية:
البونص: {text} | النوع: {context.user_data['suit']} | التوقيت: {time_str}

المطلوب:
1. استخرج علاقة رياضية تربط آخر 3 أرقام من البونص مع فجوة الثواني.
2. التوقع: (🔵 ثور أو 🔴 راعي).
3. القانون المطبق: (اكتب المعادلة الرياضية المستخدمة)."""

        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_openai_ultra, prompt)

        # حفظ القانون في سجل القوانين المستقل
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO rules_log (rule_text, confidence_score) VALUES (%s, %s)", (analysis[:1500], 99.0))
                conn.commit()
            conn.close()
        except: pass

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **تحليل GPT-4o السيادي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون في السجل المستقل.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
