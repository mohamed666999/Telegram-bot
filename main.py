import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية (Cloudflare AI) ---
CLOUDFLARE_API_KEY = "skzW8mLqnWq9eqz2-D_kHZLUxZDf2azX_A3MkaPU"
# ⚠️ ملاحظة: إذا لم تضع الـ Account ID هنا، سيخبرك البوت بذلك فوراً عند التجربة
ACCOUNT_ID = "ضع_هنا_رقم_الحساب_من_لوحة_تحكم_كلاود_فلير" 

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_cloudflare_ai(prompt):
    if "ضع_هنا" in ACCOUNT_ID:
        return "⚠️ خطأ: يرجى وضع Account ID في الكود لكي أتمكن من التحليل."
    
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-3-8b-instruct"
    headers = {"Authorization": f"Bearer {CLOUDFLARE_API_KEY}"}
    
    try:
        resp = requests.post(url, headers=headers, json={"prompt": prompt}, timeout=15)
        if resp.status_code == 200:
            return resp.json().get('result', {}).get('response', "لا يوجد رد رقمي").strip()
        else:
            return f"❌ خطأ من Cloudflare (كود {resp.status_code}): تأكد من الـ Account ID وصلاحية الـ AI في حسابك."
    except Exception as e:
        return f"❌ فشل الاتصال بخادم الحافة: {str(e)}"

# ==================== المعالجات المصلحة ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # التأكد من عمل البوت فوراً عند الضغط على Start
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي V76.1 (محرك Cloudflare)**\n\n"
        "النظام جاهز للعمل 24/7.\n"
        "يرجى اختيار النوع لبدء التحليل:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ تم تفعيل النوع: {data[2:]}\n📥 أرسل بونص الجولة الآن:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data.get('bonus'), context.user_data.get('suit'), winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم الحفظ بنجاح: {winner}")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ يرجى اختيار النوع أولاً عبر الضغط على الرموز أعلاه.")
            return

        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🧬 **جاري معالجة الفجوات الزمنية عبر Cloudflare...**")
        
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # تحليل آخر 20 جولة للفجوات
        all_data = ""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("SELECT b_num, winner, timestamp FROM history ORDER BY id DESC LIMIT 20")
                rows = cur.fetchall()
                for i in range(len(rows)-1):
                    gap = (rows[i][2] - rows[i+1][2]).total_seconds()
                    all_data += f"B:{rows[i][0]}|W:{rows[i][1]}|G:{gap}s\n"
            conn.close()
        except: all_data = "سجل فارغ."

        prompt = f"Analyze patterns:\n{all_data}\nCurrent: B:{text}, T:{current_time_str}\nPredict Bull/Bear and Rule:"
        
        # استدعاء المحرك مع معالجة الأخطاء
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, ask_cloudflare_ai, prompt)

        report = (f"⏰ **التوقيت:** `{current_time_str}`\n━━━━━━━━━━━━\n"
                  f"🧠 **التحليل السيادي:**\n{analysis}\n━━━━━━━━━━━━\n"
                  f"📂 تم أرشفة القانون في سجل القوانين المستقل.")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
