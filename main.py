import os, sys, datetime, asyncio, psycopg2, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# --- الإعدادات الفنية ---
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
            json={"model": model_name, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 60},
            timeout=12
        )
        return resp.json()['choices'][0]['message']['content'].strip() if resp.status_code == 200 else f"خطأ {resp.status_code}"
    except: return "فشل الاتصال"

# ==================== المعالجات المحدثة V69.0 ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
          [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]]
    await update.message.reply_text("🏛️ **الكيان V69.0 (تحليل السلاسل الزمنية)**\nاختر نوع الورقة المكشوفة:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ النوع: {data[2:]}\n📥 أرسل رقم البونص:")
    elif data.startswith("save_"):
        winner = data.split("_")[1]
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                           (context.user_data['bonus'], context.user_data['suit'], winner, datetime.datetime.now()))
                conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ تم الحفظ: {winner}")
        except: pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) in [7, 8]:
        if 'suit' not in context.user_data: return
        context.user_data['bonus'] = text
        msg = await update.message.reply_text("🕵️ **جاري فحص الاتصال الزمني للبيانات...**")
        
        # --- نظام RAG المطور للتعامل مع الفجوات ---
        total_rounds = 0; bulls = 0; shepherds = 0
        recent_chain = "لا يوجد (بداية سلسلة جديدة)"
        time_diff_msg = ""

        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            with conn.cursor() as cur:
                # 1. إحصاء شامل (الذاكرة الكبرى)
                cur.execute("SELECT winner, COUNT(*) FROM history GROUP BY winner")
                stats = dict(cur.fetchall())
                bulls = stats.get('ثور', 0); shepherds = stats.get('راعي', 0)
                total_rounds = bulls + shepherds
                
                # 2. جلب آخر جولة لمعرفة الفجوة الزمنية
                cur.execute("SELECT winner, timestamp FROM history ORDER BY id DESC LIMIT 1")
                last_row = cur.fetchone()
                
                if last_row:
                    last_winner, last_time = last_row
                    diff = datetime.datetime.now() - last_time
                    minutes_ago = int(diff.total_seconds() / 60)
                    
                    # إذا كانت آخر جولة قبل أقل من 15 دقيقة، نعتبرها سلسلة متصلة
                    if minutes_ago < 15:
                        cur.execute("SELECT winner FROM history WHERE timestamp > %s ORDER BY id ASC", 
                                   (datetime.datetime.now() - datetime.timedelta(minutes=15),))
                        recent_chain = " -> ".join([r[0] for r in cur.fetchall()])
                        time_diff_msg = f"الجولات متصلة (آخر جولة منذ {minutes_ago} دقيقة)"
                    else:
                        time_diff_msg = f"سلسلة جديدة (آخر جولة كانت منذ {minutes_ago} دقيقة - النمط قد تغير)"

            conn.close()
        except: pass

        prompt = f"""أنت خبير إحصائي. حلل هذه البيانات مع مراعاة الفجوات الزمنية:
- إجمالي الخبرة: {total_rounds} جولة (ثور:{bulls}, راعي:{shepherds}).
- الحالة الزمنية: {time_diff_msg}
- السلسلة المتصلة حالياً: {recent_chain}
- المعطيات: بونص {text}, ورقة {context.user_data['suit']}.

المطلوب (تنسيق صارم):
التوقع: 🔵 ثور (أو 🔴 راعي)
الثقة: %
التحليل: (هل النمط مستمر أم انقطع؟ بـ 5 كلمات)"""

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, ask_ai, "google/gemini-2.0-flash-001", KEY_1, prompt),
            loop.run_in_executor(None, ask_ai, "nvidia/llama-3.1-nemotron-70b-instruct", KEY_2, prompt),
            loop.run_in_executor(None, ask_ai, "anthropic/claude-3-haiku", KEY_3, prompt)
        ]
        r1, r2, r3 = await asyncio.gather(*tasks)

        report = (f"📊 **تحليل السلسلة:** {time_diff_msg}\n"
                  f"🔢 **الجولات الكلية:** {total_rounds}\n━━━━━━━━━━━━\n"
                  f"🧠 **Gemini:**\n{r1}\n\n"
                  f"🤖 **Nvidia:**\n{r2}\n\n"
                  f"🔍 **Claude:**\n{r3}\n━━━━━━━━━━━━\n"
                  f"✅ سجل النتيجة الفعلية:")
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_راعي"), InlineKeyboardButton("🔵 ثور", callback_data="save_ثور")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]]
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()
