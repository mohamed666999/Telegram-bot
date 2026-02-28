import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية المحدثة ---
KEY_1 = "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"
KEY_2 = "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"
KEY_3 = "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"

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

def ask_ai(model_name, api_key, prompt):
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model_name, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 50},
            timeout=12
        )
        return resp.json()['choices'][0]['message']['content'].strip() if resp.status_code == 200 else f"خطأ {resp.status_code}"
    except: return "فشل الاتصال"

# ==================== المعالجات المحدثة ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # البدء مباشرة باختيار نوع الورقة المكشوفة
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان V68.0 السريع (نظام RAG)**\nاختر نوع الورقة المكشوفة الآن:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ تم اختيار النوع: {data[2:]}\n📥 أرسل الآن رقم البونص (7-8 أرقام):")
    
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم الحفظ: {winner}\nاضغط /start لجولة جديدة.")
        except: await query.edit_message_text("⚠️ خطأ في الحفظ.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر نوع الورقة أولاً عبر /start")
            return
            
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🧬 **جاري التحليل وتفعيل نظام RAG لاسترجاع البيانات...**")
        
        # --- نظام RAG: استخراج وتحليل كامل قاعدة البيانات ---
        history_seq = "جديد"
        total_rounds = 0
        bulls = 0
        shepherds = 0
        
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                # 1. إحصائيات التعلم العميق (جميع الجولات)
                cur.execute("SELECT winner, COUNT(*) FROM history GROUP BY winner")
                stats = dict(cur.fetchall())
                bulls = stats.get('ثور', 0)
                shepherds = stats.get('راعي', 0)
                total_rounds = bulls + shepherds + stats.get('تعادل', 0)
                
                # 2. الأنماط اللحظية (آخر 10 جولات)
                cur.execute("SELECT winner FROM history ORDER BY id DESC LIMIT 10")
                rows = cur.fetchall()
                if rows: history_seq = ", ".join([r[0] for r in reversed(rows)]) # الترتيب الزمني الصحيح
            conn.close()
        except: pass

        # البرومبت الصارم الجديد (التعلم المستمر، التوقع أولاً)
        prompt = f"""أنت خبير إحصائي تستخدم نظام RAG. بياناتك التدريبية محدثة من قاعدة البيانات الفعلية.
إجمالي الجولات المسجلة: {total_rounds} جولة.
الإحصاء الشامل: ثور ({bulls} مرة)، راعي ({shepherds} مرة).
تسلسل النمط الأخير: {history_seq}

المعطيات الحالية -> بونص: {text}, الورقة المكشوفة: {context.user_data['suit']}.

المطلوب إجابة صارمة بهذا التنسيق الحرفي وفقط:
التوقع: 🔵 ثور (أو 🔴 راعي)
الثقة: %
السبب: (كلمتين أو ثلاث للإحصاء)"""

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, ask_ai, "google/gemini-2.0-flash-001", KEY_1, prompt),
            loop.run_in_executor(None, ask_ai, "nvidia/llama-3.1-nemotron-70b-instruct", KEY_2, prompt),
            loop.run_in_executor(None, ask_ai, "anthropic/claude-3-haiku", KEY_3, prompt)
        ]
        
        r1, r2, r3 = await asyncio.gather(*tasks)

        report = (f"📊 **إحصائيات RAG:** (تم تحليل {total_rounds} جولة)\n"
                  f"🎯 **نتائج التحليل:**\n━━━━━━━━━━━━\n"
                  f"🧠 **Gemini:**\n{r1}\n\n"
                  f"🤖 **Nvidia:**\n{r2}\n\n"
                  f"🔍 **Claude:**\n{r3}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة الفعلية:")
        
        # التليجرام يرتب الأزرار من اليسار لليمين حسب القائمة
        # العنصر الأول (راعي) سيكون على اليسار، والثاني (ثور) سيكون على اليمين
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
