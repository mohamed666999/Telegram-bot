import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية ---
AIML_KEY = "a4ef4823e990496fa7166844a9e3eea0"
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai_ultra(prompt):
    try:
        resp = requests.post(
            "https://api.aimlapi.com/chat/completions",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                "messages": [{"role": "system", "content": "أنت نظام رادار لتحليل الفجوات الرقمية."}, {"role": "user", "content": prompt}],
                "temperature": 0.0, "max_tokens": 400
            }, timeout=25
        )
        return resp.json()['choices'][0]['message']['content'].strip() if resp.status_code == 200 else "ERR"
    except: return "CONNECTION_ERR"

# --- دالة البداية المحدثة ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان السيادي V75.3**\nيجب اختيار النوع أولاً لتفعيل الرادار:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ تم تفعيل رادار النوع: {data[2:]}\n📥 أرسل رقم البونص الآن (7 أو 8 أرقام):")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data.get('bonus'), context.user_data.get('suit', 'Unknown'), winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم الحفظ بنجاح: {winner}")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    # تحسين شرط التحقق ليقبل الأرقام التي أرسلتها (مثل 11249345)
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ **خطأ:** يرجى اختيار النوع (♦️, ♥️, ♠️, ♣️) عبر أمر /start أولاً.")
            return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🛰️ **جاري استدعاء السجل التاريخي وتحليل الفجوات...**")
        
        #         
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
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
        except: all_data = "لا يوجد سجل كافٍ."

        prompt = f"تحليل فجوات 24/7:\n{all_data}\n\nالمعطى الجديد: بونص {text}, وقت {current_time_str}\nاستنتج التوقع والقاعدة:"
        
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_ai_ultra, prompt)

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل السيادي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم تسجيل القانون في الأرشيف المستقل.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
