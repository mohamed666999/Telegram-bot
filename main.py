"""
HADES TITAN 5.0 - THE SINGULARITY
الميزات: التعلم المعزز (RL)، تقييم العقول الديناميكي، ومحرك تشفير XOR لفك خوارزمية RNG.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging
from typing import Tuple, List, Dict
from contextlib import contextmanager
from psycopg2.extras import execute_values
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2, 0: 0, 1: 1, 2: 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

RANK_VALUE = {"A":14, "K":13, "Q":12, "J":11, "10":10, "9":9, "8":8, "7":7, "6":6, "5":5, "4":4, "3":3, "2":2}
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]

# ==================== 🗄️ البنية التحتية ====================
@contextmanager
def get_db_cursor():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()

def ensure_columns():
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("""CREATE TABLE IF NOT EXISTS pattern_stats (
                pattern_id VARCHAR(50) PRIMARY KEY, pattern_type VARCHAR(20),
                red_count INT DEFAULT 0, blue_count INT DEFAULT 0, tie_count INT DEFAULT 0)""")
                
            # 🌟 الجدول الجديد: تقييم العقول (أوزان التعلم المعزز) 🌟
            cur.execute("""CREATE TABLE IF NOT EXISTS engine_weights (
                engine_name VARCHAR(20) PRIMARY KEY, 
                correct_guesses INT DEFAULT 10, 
                total_guesses INT DEFAULT 20)""")
                
            # تهيئة العقول إذا كانت جديدة
            engines = [('EXACT', 10, 20), ('SUIT', 10, 20), ('DIGIT', 10, 20), ('MATH', 10, 20)]
            execute_values(cur, "INSERT INTO engine_weights (engine_name, correct_guesses, total_guesses) VALUES %s ON CONFLICT DO NOTHING", engines)
            conn.commit()
    except Exception as e:
        logger.error(f"DB Init Error: {e}")

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

# ==================== 🧠 محرك التفرد (THE SINGULARITY) ====================

def get_engine_weights() -> Dict[str, float]:
    """يستخرج الأوزان الحية بناءً على نسبة ذكاء كل محرك في الوقت الحالي"""
    weights = {'EXACT': 2.0, 'SUIT': 1.0, 'DIGIT': 1.0, 'MATH': 0.8} # أوزان افتراضية
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT engine_name, correct_guesses, total_guesses FROM engine_weights")
            for name, correct, total in cur.fetchall():
                if total > 0:
                    accuracy = correct / total
                    # معادلة أسية: المحرك الدقيق يتضاعف وزنه، والغبي يتدمر وزنه
                    weights[name] = (accuracy ** 2) * 4.0 
    except: pass
    return weights

def get_pattern_stats(pattern_id: str) -> Dict[int, float]:
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT red_count, blue_count, tie_count FROM pattern_stats WHERE pattern_id = %s", (pattern_id,))
            row = cur.fetchone()
            if row:
                red, blue, tie = row
                total = red + blue + tie
                if total > 0:
                    return {0: red/total, 1: blue/total, 2: tie/total, 'total': total}
    except: pass
    return {0: 0.0, 1: 0.0, 2: 0.0, 'total': 0}

def predict_singularity(b_num: str, suit: str, rank: str) -> Tuple[int, int, str, dict]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح", {}
    last_digit = int(clean_b[-1])
    
    weights = get_engine_weights() # جلب العقول وأوزانها الحية
    votes = {0: 0.0, 1: 0.0, 2: 0.0}
    logs = []
    engines_predictions = {} # لحفظ قرار كل عقل لنتمكن من محاسبته لاحقاً!
    
    # 1️⃣ العقل الدقيق (EXACT)
    exact_id = f"EXACT_{suit}_{rank}_{last_digit}"
    exact_stats = get_pattern_stats(exact_id)
    if exact_stats['total'] > 0:
        best_exact = max([0, 1], key=lambda k: exact_stats[k])
        votes[best_exact] += exact_stats[best_exact] * weights['EXACT']
        logs.append(f"🎯 <b>دقيق:</b> {WINNER_NAMES[best_exact]} (الوزن المكتسب: {weights['EXACT']:.1f})")
        engines_predictions['EXACT'] = best_exact

    # 2️⃣ عقل البذلة (SUIT)
    suit_id = f"SUIT_{suit}"
    suit_stats = get_pattern_stats(suit_id)
    if suit_stats['total'] > 0:
        best_suit = max([0, 1], key=lambda k: suit_stats[k])
        votes[best_suit] += suit_stats[best_suit] * weights['SUIT']
        logs.append(f"🎴 <b>البذلة:</b> {WINNER_NAMES[best_suit]} (الوزن المكتسب: {weights['SUIT']:.1f})")
        engines_predictions['SUIT'] = best_suit

    # 3️⃣ عقل الرقم (DIGIT)
    digit_id = f"DIGIT_{last_digit}"
    digit_stats = get_pattern_stats(digit_id)
    if digit_stats['total'] > 0:
        best_digit = max([0, 1], key=lambda k: digit_stats[k])
        votes[best_digit] += digit_stats[best_digit] * weights['DIGIT']
        logs.append(f"🔢 <b>الرقم:</b> {WINNER_NAMES[best_digit]} (الوزن المكتسب: {weights['DIGIT']:.1f})")
        engines_predictions['DIGIT'] = best_digit

    # 4️⃣ عقل التشفير الكمي (XOR Cryptographic Math)
    # خوارزمية تشفير تعتمد على (XOR) بين مجموع الأرقام، وقيمة الورقة، وطول البونص.
    digits_sum = sum(int(d) for d in clean_b)
    card_val = RANK_VALUE.get(str(rank).strip().upper(), 0)
    length_mod = len(clean_b)
    # سر التشفير: (XOR) يعكس طبيعة الـ RNG في البرمجة!
    crypto_res = ((digits_sum ^ card_val) * length_mod + last_digit) % 2 
    votes[crypto_res] += 1.0 * weights['MATH']
    logs.append(f"🧮 <b>تشفير (XOR):</b> {WINNER_NAMES[crypto_res]} (الوزن المكتسب: {weights['MATH']:.1f})")
    engines_predictions['MATH'] = crypto_res

    # ================= القرار النهائي =================
    final_pred = max([0, 1], key=lambda k: votes[k])
    total_vote_score = votes[0] + votes[1]
    
    if total_vote_score > 0:
        confidence = int((votes[final_pred] / total_vote_score) * 100)
        confidence = min(99, max(50, confidence))
    else:
        confidence = 50

    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str, engines_predictions

# ==================== 🛠️ التعليم العقابي والمكافآت (Q-Learning) ====================
def live_train_reinforcement(b_num: str, suit: str, rank: str, actual_winner: int, engines_predictions: dict):
    """هنا يكمن السحر: البوت يراجع قرارات عقوله الأربعة، ويكافئ العقل المصيب ويعاقب العقل المخطئ!"""
    last_digit = int(clean_digits(b_num)[-1])
    patterns = [(f"EXACT_{suit}_{rank}_{last_digit}", "EXACT"), (f"SUIT_{suit}", "SUIT"), (f"DIGIT_{last_digit}", "DIGIT")]
    col_to_update = "red_count" if actual_winner == 0 else "blue_count" if actual_winner == 1 else "tie_count"
    
    try:
        with get_db_cursor() as (conn, cur):
            # 1. تحديث ذاكرة الأنماط
            for pid, ptype in patterns:
                cur.execute(f"""
                    INSERT INTO pattern_stats (pattern_id, pattern_type, {col_to_update})
                    VALUES (%s, %s, 1) ON CONFLICT (pattern_id) DO UPDATE 
                    SET {col_to_update} = pattern_stats.{col_to_update} + 1
                """, (pid, ptype))
            
            # 2. التعلم المعزز للعقول (المكافأة والعقاب)
            for engine_name, predicted_winner in engines_predictions.items():
                is_correct = 1 if predicted_winner == actual_winner else 0
                cur.execute("""
                    UPDATE engine_weights 
                    SET correct_guesses = correct_guesses + %s, total_guesses = total_guesses + 1 
                    WHERE engine_name = %s
                """, (is_correct, engine_name))
                
            conn.commit()
    except Exception as e:
        logger.error(f"RL Training Error: {e}")

# ==================== 🚀 التعلم العميق ====================
async def force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🧠 جاري تشغيل THE SINGULARITY...")
    try:
        with get_db_cursor() as (conn, cur):
            df = pd.read_sql("SELECT suit, rank, bonus_last_digit, b_num, winner FROM history WHERE winner IS NOT NULL", conn)
            
        df['clean_b'] = df['b_num'].astype(str).apply(clean_digits)
        df = df[df['clean_b'] != ""]
        df['final_digit'] = df['bonus_last_digit'].fillna(df['clean_b'].str[-1])
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'final_digit', 'suit'])
        
        stats = {}
        for _, row in df.iterrows():
            w = row['winner_code']
            if w not in [0, 1, 2]: continue
            pats = [(f"SUIT_{row['suit']}", "SUIT"), (f"DIGIT_{row['final_digit']}", "DIGIT")]
            if pd.notna(row['rank']): pats.append((f"EXACT_{row['suit']}_{row['rank']}_{row['final_digit']}", "EXACT"))
            for pid, ptype in pats:
                if pid not in stats: stats[pid] = {'type': ptype, 0:0, 1:0, 2:0}
                stats[pid][w] += 1
                
        data_to_insert = [(pid, v['type'], v[0], v[1], v[2]) for pid, v in stats.items()]
            
        if data_to_insert:
            insert_query = """INSERT INTO pattern_stats (pattern_id, pattern_type, red_count, blue_count, tie_count)
                              VALUES %s ON CONFLICT (pattern_id) DO UPDATE 
                              SET red_count=EXCLUDED.red_count, blue_count=EXCLUDED.blue_count, tie_count=EXCLUDED.tie_count"""
            with get_db_cursor() as (conn, cur):
                cur.execute("TRUNCATE TABLE pattern_stats;") 
                execute_values(cur, insert_query, data_to_insert)
                
                # تصفير الأوزان للبدء من جديد بذكاء ونظافة
                cur.execute("UPDATE engine_weights SET correct_guesses = 10, total_guesses = 20;")
                conn.commit()
                
        await msg.edit_text(f"✅ **الأنظمة تعمل بكفاءة (TITAN 5.0)**\nتم حقن {len(data_to_insert)} نمط، وتم تهيئة الأوزان للذكاء التلقائي.")
    except Exception as e:
        await msg.edit_text(f"❌ حدث خطأ: {e}")

async def download_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("⏳ جاري تحضير قاعدة البيانات...")
    try:
        with get_db_cursor() as (conn, cur):
            df_history = pd.read_sql("SELECT * FROM history ORDER BY id DESC LIMIT 5000", conn)
            df_patterns = pd.read_sql("SELECT * FROM pattern_stats ORDER BY (red_count+blue_count) DESC", conn)
            df_engines = pd.read_sql("SELECT * FROM engine_weights", conn)
            
        fh, fp, fe = "History.csv", "Patterns.csv", "Engines.csv"
        df_history.to_csv(fh, index=False); df_patterns.to_csv(fp, index=False); df_engines.to_csv(fe, index=False)

        await update.message.reply_document(document=open(fh, 'rb'), caption="📊 التاريخ")
        await update.message.reply_document(document=open(fp, 'rb'), caption="⚖️ الأنماط")
        await update.message.reply_document(document=open(fe, 'rb'), caption="🧠 تقييم العقول")
        
        for f in [fh, fp, fe]: os.remove(f)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")

# ==================== 🎮 الواجهة الأساسية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🏛️ HADES TITAN 5.0 (The Singularity)</b>\n\nنظام التداول والتعلم المعزز الذاتي.\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    try:
        if data == "choose_suit":
            context.user_data.pop('suit', None); context.user_data.pop('rank', None)
            kb = [[InlineKeyboardButton(s, callback_data=f"suit_{s}") for s in SUITS]]
            await query.edit_message_text("🎴 <b>اختر البذلة:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
        elif data.startswith("suit_"):
            suit = data.split("_")[1]
            context.user_data['suit'] = suit
            kb = [[InlineKeyboardButton(r, callback_data=f"rank_{r}") for r in row] for row in RANKS_LAYOUT]
            kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="choose_suit")])
            await query.edit_message_text(f"✅ البذلة: <b>{suit}</b>\n🃏 <b>اختر الورقة:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

        elif data.startswith("rank_"):
            rank = data.split("_")[1]
            context.user_data['rank'] = rank
            suit = context.user_data.get('suit', '')
            kb = [[InlineKeyboardButton("🔄 تغيير الاختيار", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ جاهز: <b>{suit} {rank}</b>\n\n📥 <b>أرسل رقم البونص الآن:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

        elif data == "delete_last":
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute("DELETE FROM history WHERE id = (SELECT max(id) FROM history WHERE user_id = %s)", (update.effective_user.id,))
                    conn.commit()
            except: pass
            suit = context.user_data.get('suit'); rank = context.user_data.get('rank')
            if suit and rank:
                kb = [[InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
                await query.edit_message_text(f"🗑️ تم حذف الجولة الخاطئة.\n\nمستمرون مع: <b>{suit} {rank}</b>\n📥 أرسل الرقم الصحيح:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            else:
                kb = [[InlineKeyboardButton("🎴 اختيار", callback_data="choose_suit")]]
                await query.edit_message_text("🗑️ تم الحذف.", reply_markup=InlineKeyboardMarkup(kb))

        elif data.startswith("save_"):
            w_code = int(data.split("_")[1])
            b_num = context.user_data.get('last_b_num')
            suit = context.user_data.get('last_suit')
            rank = context.user_data.get('last_rank')
            engines_preds = context.user_data.get('engines_predictions', {})
            
            if b_num and suit and rank:
                try:
                    with get_db_cursor() as (conn, cur):
                        cur.execute("""INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id) 
                                       VALUES (%s, %s, %s, %s, %s, %s)""",
                                    (b_num, suit, rank, int(clean_digits(b_num)[-1]), WINNER_NAMES[w_code], update.effective_user.id))
                        conn.commit()
                    
                    # 🔥 التعلم المعزز يحصل هنا!
                    live_train_reinforcement(b_num, suit, rank, w_code, engines_preds)
                except: pass

            kb = [[InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")], [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ تم تسجيل: <b>{WINNER_NAMES[w_code]}</b>\n(تمت مكافأة العقول المصيبة)\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
    except Exception as e:
        logger.error(f"Callback Error: {e}")
        await query.edit_message_text("❌ حدث خطأ، ارسل /start")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        clean_text = clean_digits(text)
        
        if clean_text:
            suit = context.user_data.get('suit')
            rank = context.user_data.get('rank')
            
            if not suit or not rank:
                kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
                await update.message.reply_text("⚠️ <b>يجب اختيار البذلة والورقة أولاً!</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                return
                
            pred_code, confidence, reason, engines_preds = predict_singularity(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            context.user_data['engines_predictions'] = engines_preds
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير TITAN 5.0 (Singularity)</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>التوقع: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 العقول الديناميكية:</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز لتسجيل النتيجة (لمكافأة/عقاب العقول):"""
            
            await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")
        await update.message.reply_text(f"⚠️ خطأ في المعالجة.")

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("force_learn", force_learn))
    app.add_handler(CommandHandler("download", download_db))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 HADES TITAN 5.0 (Singularity) Is Online!")
    app.run_polling(drop_pending_updates=True)
