"""
HADES V110 - Ultimate Deep Learning AI
الميزات: تنظيف ذكي للأرقام، تحليل الأنماط الثلاثية، صيانة تلقائية للقوانين.
"""

import os, re, datetime, psycopg2, pandas as pd, logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# ==================== 🛠️ معالج البيانات الذكي ====================
def clean_digits(text: str) -> str:
    """استخراج الأرقام فقط من أي نص"""
    return re.sub(r"\D", "", text)

# ==================== 🧠 محرك التوقع المتقدم ====================
def predict_hybrid(b_num: str, suit: str) -> Tuple[int, str]:
    digits = clean_digits(b_num)
    if len(digits) < 1: return 2, "❌ رقم غير صالح"
    
    last_digit = digits[-1]
    # محرك الأنماط الثلاثية (Sequence Pattern)
    seq = digits[-3:] 
    
    conn = get_db_connection()
    cur = conn.cursor()
    # البحث عن القوانين الأقوى
    cur.execute("""
        SELECT law_name, law_pattern, success_count, fail_count 
        FROM ai_laws 
        WHERE law_pattern->>'suit' = %s AND law_pattern->>'last_digit' = %s 
        AND is_active = TRUE
        ORDER BY (success_count - fail_count) DESC LIMIT 1
    """, (suit, last_digit))
    
    law = cur.fetchone()
    conn.close()
    
    if law:
        name, pattern, succ, fail = law
        return pattern.get('winner', 2), f"📜 {name} (✅{succ}|❌{fail})"
        
    # الرياضي الاحتياطي
    last3_sum = sum(int(d) for d in digits[-3:])
    res = (last3_sum + int(last_digit)) % 2
    return res, "🧮 تحليل رياضي"

# ==================== 🚀 الأوامر ====================
async def force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🧠 جاري التحليل العميق...")
    
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM history", conn)
    df['clean_b'] = df['b_num'].apply(clean_digits)
    df = df[df['clean_b'].str.len() >= 3]
    df['last_digit'] = df['clean_b'].str[-1]
    df['winner_code'] = df['winner'].map(WINNER_MAP)
    
    grouped = df.groupby(['suit', 'last_digit'])['winner_code'].value_counts().unstack(fill_value=0)
    
    cur = conn.cursor()
    for (suit, digit), row in grouped.iterrows():
        best_winner = row.idxmax()
        succ, fail = row[best_winner], row.drop(best_winner).sum()
        if succ > fail:
            cur.execute("""INSERT INTO ai_laws (law_name, law_pattern, success_count, fail_count)
                VALUES (%s, %s, %s, %s) ON CONFLICT (law_name) DO UPDATE SET success_count=EXCLUDED.success_count, fail_count=EXCLUDED.fail_count""",
                (f"DB_{suit}_{digit}", json.dumps({"suit": suit, "last_digit": digit, "winner": int(best_winner)}), int(succ), int(fail)))
    
    cur.execute("DELETE FROM ai_laws WHERE fail_count > success_count")
    conn.commit()
    conn.close()
    await msg.edit_text("✅ تم التحديث والتعلم العميق.")

async def sql_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    conn = get_db_connection()
    df = pd.read_sql("SELECT law_name, success_count, fail_count FROM ai_laws ORDER BY success_count DESC LIMIT 10", conn)
    conn.close()
    await update.message.reply_text(f"📊 القوانين:\n{df.to_string()}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = clean_digits(update.message.text)
    if len(text) >= 5:
        suit = context.user_data.get('suit', '♦️')
        context.user_data['last_b_num'] = text
        context.user_data['last_suit'] = suit
        
        pred, reason = predict_hybrid(text, suit)
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data="save_0"), InlineKeyboardButton("🔵 ثور", callback_data="save_1")],
              [InlineKeyboardButton("⚪ تعادل", callback_data="save_2")]]
        
        await update.message.reply_text(f"🏆 {WINNER_NAMES[pred]}\n⚙️ {reason}", reply_markup=InlineKeyboardMarkup(kb))

# ==================== 🎬 التشغيل ====================
if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("force_learn", force_learn))
    app.add_handler(CommandHandler("sql", sql_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
