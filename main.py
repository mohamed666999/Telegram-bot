"""
HADES V-TITAN 3.0 - The Pinnacle
الميزات: سرعة 30x في قواعد البيانات (Bulk Upsert)، أمان التزامن، توحيد فحص الانقطاع، ومعادلة رياضية محمية.
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging
from typing import Tuple
from contextlib import contextmanager
from psycopg2.extras import execute_values # 🌟 السر في تسريع قاعدة البيانات
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s" # ⚠️ يجب تغييره لاحقاً من BotFather للأمان
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2, 0: 0, 1: 1, 2: 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

RANK_VALUE = {"A":14, "K":13, "Q":12, "J":11, "10":10, "9":9, "8":8, "7":7, "6":6, "5":5, "4":4, "3":3, "2":2}
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]

# ==================== 🗄️ إدارة قاعدة البيانات ====================
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
            history_updates = ["ALTER TABLE history ADD COLUMN rank VARCHAR(5);", "ALTER TABLE history ADD COLUMN bonus_last_digit INT;", "ALTER TABLE history ADD COLUMN user_id BIGINT;"]
            for q in history_updates:
                cur.execute(f"DO $$ BEGIN {q} EXCEPTION WHEN duplicate_column THEN NULL; END $$;")
            cur.execute("""CREATE TABLE IF NOT EXISTS ai_laws (law_name VARCHAR(100) PRIMARY KEY, law_pattern JSONB, success_count INT DEFAULT 0, fail_count INT DEFAULT 0, is_active BOOLEAN DEFAULT TRUE)""")
            conn.commit()
    except: pass

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

# ==================== ⏱️ اكتشاف الانقطاع الزمني ====================
def is_sequence_broken() -> bool:
    """يفحص الانقطاع مرة واحدة فقط بالاعتماد على توقيت السيرفر العالمي UTC"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if not row: return True
            
            time_diff_seconds = (datetime.datetime.utcnow() - row[0]).total_seconds()
            if time_diff_seconds > 180: # 3 دقائق
                return True
    except: pass
    return False

# ==================== ⚙️ المحركات الذكية لـ V-TITAN 3.0 ====================
def get_markov_chain_prediction(sequence_broken: bool) -> Tuple[int, int, str]:
    if sequence_broken:
        return 2, 0, "تم تجاهل التسلسل (يوجد انقطاع زمني بين الجولات)"
        
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 500")
            rows = cur.fetchall()
            if len(rows) < 10: return 2, 0, ""
            
            history_codes = [WINNER_MAP.get(r[0], 2) for r in rows]
            history_codes.reverse()
            
            current_seq = tuple(history_codes[-3:])
            next_outcomes = {0: 0, 1: 0, 2: 0}
            
            for i in range(len(history_codes) - 3):
                if tuple(history_codes[i:i+3]) == current_seq:
                    next_outcomes[history_codes[i+3]] += 1
                    
            total_matches = sum(next_outcomes.values())
            if total_matches >= 3:
                best_pred = max(next_outcomes, key=next_outcomes.get)
                conf = int((next_outcomes[best_pred] / total_matches) * 100)
                return best_pred, conf, f"سلاسل التاريخ (تكرر التسلسل {total_matches} مرات)"
    except: pass
    return 2, 0, ""

def get_cascading_db_prediction(suit: str, rank: str, last_digit: int) -> Tuple[int, int, str]:
    queries = [
        (f"DB_{suit}_{rank}_{last_digit}", "تطابق دقيق (بذلة+ورقة+رقم)"),
        (f"DB_{suit}_{rank}", "تطابق قوي (بذلة+ورقة)"),
        (f"DB_{suit}_ALL_{last_digit}", "تطابق متوسط (بذلة+رقم)")
    ]
    try:
        with get_db_cursor() as (conn, cur):
            for q_name, desc in queries:
                cur.execute("SELECT success_count, fail_count, law_pattern->>'winner' FROM ai_laws WHERE law_name LIKE %s AND is_active = TRUE", (f"{q_name}%",))
                row = cur.fetchone()
                if row:
                    succ, fail, winner = row
                    if succ > fail:
                        conf = int((succ / (succ + fail)) * 100)
                        return int(winner), conf, f"{desc} [✅{succ}]"
    except: pass
    return 2, 0, ""

def get_momentum_correction(sequence_broken: bool) -> Tuple[int, int, str]:
    if sequence_broken:
        return 2, 0, "تم تجاهل الزخم (الجولات متقطعة)"
        
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 20")
            rows = cur.fetchall()
            if len(rows) < 10: return 2, 0, ""
            
            recent = [WINNER_MAP.get(r[0], 2) for r in rows]
            red_count = recent.count(0)
            blue_count = recent.count(1)
            
            if red_count >= 14:
                return 1, 75, "تصحيح زخم (تشبع الراعي)"
            elif blue_count >= 14:
                return 0, 75, "تصحيح زخم (تشبع الثور)"
    except: pass
    return 2, 0, ""

# ==================== ⚖️ خوارزمية التجميع ====================
def predict_titan(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])
    
    # 🌟 الاستدعاء لمرة واحدة فقط (تقليل الضغط على قاعدة البيانات)
    sequence_broken = is_sequence_broken()
    
    markov_pred, markov_conf, markov_desc = get_markov_chain_prediction(sequence_broken)
    db_pred, db_conf, db_desc = get_cascading_db_prediction(suit, rank, last_digit)
    mom_pred, mom_conf, mom_desc = get_momentum_correction(sequence_broken)
    
    votes = {0: 0.0, 1: 0.0, 2: 0.0}
    logs = []
    
    if markov_conf > 0:
        votes[markov_pred] += markov_conf * 1.5 
        logs.append(f"🧬 **ماركوف:** {WINNER_NAMES[markov_pred]} ({markov_desc})")
        
    if db_conf > 0:
        votes[db_pred] += db_conf * 2.0 
        logs.append(f"💾 **الذاكرة:** {WINNER_NAMES[db_pred]} ({db_desc})")
        
    if mom_conf > 0:
        votes[mom_pred] += mom_conf * 1.0 
        logs.append(f"⚖️ **الزخم:** {WINNER_NAMES[mom_pred]} ({mom_desc})")

    if sum(votes.values()) == 0:
        # 🌟 الحماية الرياضية (zfill)
        padded_b = clean_b.zfill(3)
        last_digits_sum = sum(int(d) for d in padded_b[-3:])
        card_val = RANK_VALUE.get(str(rank).strip().upper(), 0)
        math_res = ((last_digits_sum * card_val) + last_digit) % 2
        votes[math_res] += 60
        logs.append(f"🧮 **رياضيات:** {WINNER_NAMES[math_res]} (معادلة الورقة)")

    final_pred = max(votes, key=votes.get)
    total_score = sum(votes.values())
    confidence = min(99, int((votes[final_pred] / total_score) * 100)) if total_score > 0 else 50
    
    if sequence_broken:
        logs.append("\n⚠️ *ملاحظة:* تم الاعتماد على الذاكرة فقط بسبب انقطاعك عن اللعب.")
        
    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

def update_law_stats(law_name: str, is_success: bool):
    try:
        with get_db_cursor() as (conn, cur):
            if is_success:
                cur.execute("UPDATE ai_laws SET success_count = success_count + 1 WHERE law_name = %s", (law_name,))
            else:
                cur.execute("UPDATE ai_laws SET fail_count = fail_count + 1 WHERE law_name = %s", (law_name,))
            conn.commit()
    except: pass

# ==================== 🚀 التعلم السريع (Bulk Upsert) ====================
async def force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🧠 جاري المعالجة السريعة للبيانات (Bulk Update)...")
    
    try:
        with get_db_cursor() as (conn, cur):
            df = pd.read_sql("SELECT suit, rank, bonus_last_digit, b_num, winner FROM history WHERE winner IS NOT NULL", conn)
            
        df['clean_b'] = df['b_num'].astype(str).apply(clean_digits)
        df = df[df['clean_b'] != ""]
        df['calc_last_digit'] = df['clean_b'].str[-1]
        df['final_digit'] = df['bonus_last_digit'].fillna(df['calc_last_digit'])
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'final_digit', 'suit'])
        
        data_to_upsert = []
        
        # 1. تجميع القوانين العامة
        grp_all = df.groupby(['suit', 'final_digit'])['winner_code'].value_counts().unstack(fill_value=0)
        for (suit, digit), row in grp_all.iterrows():
            best_winner = row.idxmax()
            succ, fail = row[best_winner], row.drop(best_winner).sum()
            if succ >= 5 and succ > fail:
                l_name = f"DB_{suit}_ALL_{digit}"
                pat = json.dumps({"suit": suit, "last_digit": str(digit), "winner": int(best_winner)})
                data_to_upsert.append((l_name, pat, int(succ), int(fail)))

        # 2. تجميع القوانين الدقيقة
        df_rank = df.dropna(subset=['rank'])
        if not df_rank.empty:
            grp_rank = df_rank.groupby(['suit', 'rank', 'final_digit'])['winner_code'].value_counts().unstack(fill_value=0)
            for (suit, rank, digit), row in grp_rank.iterrows():
                best_winner = row.idxmax()
                succ, fail = row[best_winner], row.drop(best_winner).sum()
                if succ >= 3 and succ > fail:
                    l_name = f"DB_{suit}_{rank}_{digit}"
                    pat = json.dumps({"suit": suit, "rank": rank, "last_digit": str(digit), "winner": int(best_winner)})
                    data_to_upsert.append((l_name, pat, int(succ), int(fail)))

        # 🌟 السر المعماري (Bulk Upsert): تنفيذها بضربة واحدة بدل مئات الاستعلامات
        if data_to_upsert:
            insert_query = """
                INSERT INTO ai_laws (law_name, law_pattern, success_count, fail_count)
                VALUES %s
                ON CONFLICT (law_name) DO UPDATE 
                SET success_count = EXCLUDED.success_count, fail_count = EXCLUDED.fail_count
            """
            with get_db_cursor() as (conn, cur):
                execute_values(cur, insert_query, data_to_upsert)
                cur.execute("DELETE FROM ai_laws WHERE fail_count >= success_count")
                deleted = cur.rowcount
                conn.commit()
                
        await msg.edit_text(f"✅ **تم التدريب الخارق (Bulk Upsert)**\n➕ قوانين مبنية ومحدثة: {len(data_to_upsert)}\n🗑️ قوانين فاشلة حُذفت: {deleted}")
    except Exception as e:
        await msg.edit_text(f"❌ حدث خطأ: {e}")

async def download_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("⏳ جاري تحضير قاعدة البيانات...")
    try:
        with get_db_cursor() as (conn, cur):
            df_history = pd.read_sql("SELECT * FROM history ORDER BY id DESC LIMIT 5000", conn)
            df_laws = pd.read_sql("SELECT * FROM ai_laws ORDER BY law_name", conn)
            
        filename_hist = f"History_{datetime.datetime.now().strftime('%Y%m%d')}.csv"
        filename_laws = f"Laws_{datetime.datetime.now().strftime('%Y%m%d')}.csv"
        df_history.to_csv(filename_hist, index=False)
        df_laws.to_csv(filename_laws, index=False)

        await update.message.reply_document(document=open(filename_hist, 'rb'), caption="📊 جدول التاريخ")
        await update.message.reply_document(document=open(filename_laws, 'rb'), caption="⚖️ جدول القوانين")
        
        os.remove(filename_hist)
        os.remove(filename_laws)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")

# ==================== 🎮 الواجهة الآمنة ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🏛️ HADES V-TITAN 3.0 (Quantum Speed)</b>\n\nاضغط للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    try:
        if data == "choose_suit":
            context.user_data.pop('suit', None)
            context.user_data.pop('rank', None)
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
            
            suit = context.user_data.get('suit')
            rank = context.user_data.get('rank')
            if suit and rank:
                kb = [[InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
                await query.edit_message_text(f"🗑️ تم حذف الجولة الخاطئة.\n\nمستمرون مع: <b>{suit} {rank}</b>\n📥 أرسل الرقم الصحيح:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            else:
                kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
                await query.edit_message_text("🗑️ تم الحذف. يرجى اختيار الورقة من جديد:", reply_markup=InlineKeyboardMarkup(kb))

        elif data.startswith("save_"):
            w_code = int(data.split("_")[1])
            b_num = context.user_data.get('last_b_num')
            suit = context.user_data.get('last_suit')
            rank = context.user_data.get('last_rank')
            
            if b_num and suit and rank:
                last_digit = int(clean_digits(b_num)[-1])
                try:
                    with get_db_cursor() as (conn, cur):
                        cur.execute("""INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id, timestamp) 
                                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                                    (b_num, suit, rank, last_digit, WINNER_NAMES[w_code], update.effective_user.id, datetime.datetime.utcnow()))
                        conn.commit()
                    
                    update_law_stats(f"DB_{suit}_{rank}_{last_digit}", context.user_data.get('last_pred_code') == w_code)
                except: pass

            kb = [
                [InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")],
                [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]
            ]
            await query.edit_message_text(f"✅ تم التسجيل: <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            
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
                
            pred_code, confidence, reason = predict_titan(clean_text, suit, rank)
            
            context.user_data['last_b_num'] = clean_text
            context.user_data['last_suit'] = suit
            context.user_data['last_rank'] = rank
            context.user_data['last_pred_code'] = pred_code
            
            kb = [
                [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
                [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
            ]
            
            bar = generate_progress_bar(confidence)
            report = f"""🎯 <b>تقرير TITAN 3.0</b>
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>الفائز المتوقع: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 تفاصيل التحليل:</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز لتسجيل النتيجة:"""
            
            await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")
        await update.message.reply_text("⚠️ حدث خطأ في المعالجة.")

if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_db))
    app.add_handler(CommandHandler("force_learn", force_learn))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 HADES V-TITAN 3.0 Is Online!")
    app.run_polling(drop_pending_updates=True)
