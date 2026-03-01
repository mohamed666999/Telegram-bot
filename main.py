import os
import datetime
import psycopg2
import pandas as pd
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

def get_time_period(hour):
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

def period_translate(period):
    return {"morning": "🌅 الصباح", "afternoon": "☀️ الظهر", "evening": "🌇 المساء", "night": "🌙 الليل"}.get(period, period)

def ensure_columns():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS prediction INTEGER;")
    cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS user_id BIGINT;")
    conn.commit()
    conn.close()

def sovereign_math_engine(b_num, suit, last_timestamp, current_timestamp):
    last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
    B = sum(int(d) for d in last_3 if d.isdigit())
    S = 1 if suit in ['♦️', '♥️'] else 2
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    R = (B * S) + delta_t
    pred_code = 1 if (R % 2 == 0) else 0
    return WINNER_NAMES[pred_code], pred_code, delta_t

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]
    ]
    await update.message.reply_text(
        "🎴 اختر نوع البذلة:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, prediction, timestamp FROM history WHERE prediction IS NOT NULL", conn)
        conn.close()
        if len(df) < 10:
            await update.message.reply_text("⚠️ البيانات غير كافية.")
            return
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)
        period_order = ["morning", "afternoon", "evening", "night"]
        period_acc = df.groupby('period')['correct'].mean().reindex(period_order) * 100
        hour_stats = df.groupby('hour').agg(accuracy=('correct', 'mean'), count=('correct', 'count'))
        hour_stats = hour_stats[hour_stats['count'] >= 10]
        hour_acc = hour_stats['accuracy'] * 100
        report = "📊 **تقرير الأداء**\n━━━━━━━━━━\n"
        for p in period_order:
            if p in period_acc and not pd.isna(period_acc[p]):
                report += f"{period_translate(p)}: {period_acc[p]:.1f}%\n"
        if not hour_acc.empty:
            report += "\n✅ أفضل 3 ساعات:\n"
            for h, acc in hour_acc.nlargest(3).items():
                report += f"🟢 {h:02d}:00 → {acc:.1f}%\n"
            report += "\n⚠️ أسوأ 3 ساعات:\n"
            for h, acc in hour_acc.nsmallest(3).items():
                report += f"🔴 {h:02d}:00 → {acc:.1f}%\n"
        report += f"\n📈 إجمالي: {len(df)}"
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً.")
            return
        current_time = datetime.datetime.now()
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        last_time = row[0] if row else None
        conn.close()
        pred_text, pred_code, gap = sovereign_math_engine(text, context.user_data['suit'], last_time, current_time)
        context.user_data['bonus'] = text
        context.user_data['prediction_code'] = pred_code
        context.user_data['current_time'] = current_time
        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_الثور 🔵")]
        ]
        await update.message.reply_text(
            f"🎯 التوقع: {pred_text}\n⏱️ الفجوة: {gap} ثانية\nاختر النتيجة:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        await update.message.reply_text("❌ أرسل رقماً صحيحاً (7 أرقام).")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("s_"):
        suit = query.data[2:]
        context.user_data['suit'] = suit
        await query.edit_message_text(f"✅ تم اختيار {suit}. أرسل رقم البونص:")
    elif query.data.startswith("save_"):
        winner_db = query.data[5:]
        pred_code = context.user_data.get('prediction_code')
        if pred_code is None:
            await query.edit_message_text("❌ خطأ.")
            return
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO history (b_num, suit, winner, timestamp, prediction, user_id) VALUES (%s, %s, %s, %s, %s, %s)",
            (context.user_data['bonus'], context.user_data['suit'], winner_db, context.user_data['current_time'], pred_code, update.effective_user.id)
        )
        conn.commit()
        conn.close()
        pred_winner = WINNER_NAMES[pred_code]
        is_correct = "✅" if winner_db == pred_winner else "❌"
        keyboard = [[InlineKeyboardButton("🔄 بدء جولة جديدة", callback_data="new_round")]]
        await query.edit_message_text(
            f"{is_correct} تم التسجيل\nتوقعنا: {pred_winner}\nالنتيجة: {winner_db}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif query.data == "new_round":
        await start(update, context)

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    print("🚀 البوت يعمل...")
    app.run_polling()
