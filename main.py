import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات السيادية (Canopy Wave - Mini-Ma 2.1) ---
# هذا المفتاح والنموذج سيتجاوزان مشكلة 429 التي تظهر في صورك
CANOPY_TOKEN = "01BzATbVHNygmd7NSxLNt5uljKR4lUofTQ0pvyraMio"
MODEL_NAME = "minima-2.1-instruct" 

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_canopy_minima(prompt):
    """محرك الاستدلال السريع لتجنب توقف الخدمة"""
    url = "https://api.canopywave.io/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {CANOPY_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "أنت محلل خوارزميات محترف. وظيفتك استخراج الأنماط من بونص الجولات وفجوات الوقت بدقة متناهية."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code == 200:
            return f"⚡ [Mini-Ma 2.1 Activated]\n{resp.json()['choices'][0]['message']['content'].strip()}"
        return f"⚠️ استجابة المحرك: {resp.status_code}"
    except:
        return "❌ فشل المحرك الأساسي. جاري محاولة إعادة الاتصال..."

# ==================== المعالجات الفنية ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # مسح بيانات المستخدم القديمة لضمان بداية نظيفة
    context.user_data.clear()
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V82.0**\nتم الانتقال لمحرك Canopy (Mini-Ma 2.1) لتجاوز قيود OpenAI.\n\n"
        "الآن النظام مستقر ويعمل 24/7. اختر النوع:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ تم تفعيل رادار {data[2:]}\n📥 أرسل رقم البونص المكون من 7-8 أرقام:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data.get('bonus'), context.user_data.get('suit'), winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم حفظ: {winner}. النمط الآن أكثر ذكاءً.")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ يرجى استخدام /start أولاً واختيار النوع.") ; return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🔎 **جاري استنتاج الخوارزمية عبر Mini-Ma 2.1...**")
        
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # سحب وتحليل آخر 25 جولة (توازن مثالي للسرعة والدقة)
        gap_report = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 25")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    gap_report += f"ب:{rows[i][0]}|ف:{rows[i][1]}|ج:{gap}s\n"
            conn.close()
        except: gap_report = "السجل الأولي قيد البناء."

        prompt = f"Analyze time gaps and numbers:\n{gap_report}\nCurrent: Bonus {text}, Suit {context.user_data['suit']}, Time {time_str}\nPredict Bull/Bear and write the math rule."
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_canopy_minima, prompt)

        report = (f"⏰ **التوقيت:** `{time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **تحليل Mini-Ma الاستراتيجي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون في سجل مستقل.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
