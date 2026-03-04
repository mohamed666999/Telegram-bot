"""
HADES V109 - Deep Dynamic Learning AI
إصلاح مشكلة تحجر القوانين، تنظيف البيانات المعطوبة، ومسح القوانين الفاشلة تلقائياً.
"""

import os, sys, datetime, psycopg2, pandas as pd, numpy as np
import json, re, logging, asyncio
from typing import Dict, Tuple, Optional
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, JobQueue
)
from openai import AsyncOpenAI

# ==================== 🛡️ الإعدادات الأساسية ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2,
    0: 0, 1: 1, 2: 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

DYNAMIC_CONFIG = {'S_RED': 1.0, 'S_BLACK': 1.0}

# ==================== 🗄️ إدارة قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def ensure_columns():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            DO $$ BEGIN ALTER TABLE history ADD COLUMN user_id BIGINT; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
        """)
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_laws (
            law_name VARCHAR(100) PRIMARY KEY, law_pattern JSONB,
            success_count INT DEFAULT 0, fail_count INT DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        
        alter_queries = [
            "ALTER TABLE ai_laws ADD COLUMN success_count INT DEFAULT 0;",
            "ALTER TABLE ai_laws ADD COLUMN fail_count INT DEFAULT 0;",
            "ALTER TABLE ai_laws ADD COLUMN is_active BOOLEAN DEFAULT TRUE;",
            "ALTER TABLE ai_laws ADD COLUMN last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
        ]
        for q in alter_queries:
            cur.execute(f"DO $$ BEGIN {q} EXCEPTION WHEN duplicate_column THEN NULL; END $$;")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Init Error: {e}")

# ==================== 🤖 محرك الذكاء الاصطناعي ====================
class AsyncAIEngine:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL, timeout=15.0)

    async def ask_json(self, prompt: str) -> Optional[Dict]:
        try:
            response = await self.client.chat.completions.create(
                model=NVIDIA_MODEL,
                messages=[{"role": "system", "content": "Respond strictly in JSON format."},
                          {"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=800
            )
            content = response.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match: return json.loads(match.group())
        except Exception:
            return None

ai_engine = AsyncAIEngine()

# ==================== ⚙️ المهام الذاتية والخلفية ====================
def update_law_stats(b_num: str, suit: str, actual_winner: int, revert: bool = False):
    last_digit = b_num[-1] if b_num[-1].isdigit() else '0'
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT law_name, law_pattern FROM ai_laws WHERE is_active = TRUE")
        for law_name, pattern in cur.fetchall():
            if pattern.get('suit') == suit and str(pattern.get('last_digit')) == str(last_digit):
                if pattern.get('winner') == actual_winner:
                    if revert: cur.execute("UPDATE ai_laws SET success_count = GREATEST(success_count - 1, 0) WHERE law_name = %s", (law_name,))
                    else: cur.execute("UPDATE ai_laws SET success_count = success_count + 1 WHERE law_name = %s", (law_name,))
                else:
                    if revert: cur.execute("UPDATE ai_laws SET fail_count = GREATEST(fail_count - 1, 0) WHERE law_name = %s", (law_name,))
                    else: cur.execute("UPDATE ai_laws SET fail_count = fail_count + 1 WHERE law_name = %s", (law_name,))
        conn.commit()
        conn.close()
    except: pass

def fast_hybrid_predict(b_num: str, suit: str) -> Tuple[int, str]:
    last_digit = b_num[-1] if b_num[-1].isdigit() else '0'
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # جلب القوانين مرتبة حسب فارق النجاح، وتجاهل القوانين التي فشلها أكبر من نجاحها!
        cur.execute("""
            SELECT law_name, law_pattern, success_count, fail_count 
            FROM ai_laws 
            WHERE is_active = TRUE 
            ORDER BY (success_count - fail_count) DESC, success_count DESC
        """)
        laws = cur.fetchall()
        conn.close()
        
        for law_name, pattern, succ, fail in laws:
            # إذا كان الفشل أكبر من النجاح، تجاهل القانون تماماً (الذكاء الاصطناعي لا يثبت على قانون فاشل)
            if fail > succ and fail > 2:
                continue
                
            if pattern.get('suit') == suit and str(pattern.get('last_digit')) == str(last_digit):
                return pattern.get('winner', 2), f"📜 {law_name} (✅{succ} | ❌{fail})"
    except: pass
    
    # المحرك الرياضي (في حال عدم وجود قانون قوي)
    last3 = sum(int(d) for d in b_num[-3:] if d.isdigit())
    S = 1.2 if suit in ['♦️', '♥️'] else 0.8
    math_result = int((last3 * S) + (int(last_digit) * 3)) % 2
    return math_result, "🧮 تحليل رياضي ديناميكي"

# ==================== 🛠️ أوامر الإدارة ====================
async def download_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("⏳ جاري استخراج قاعدة البيانات...")
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM history ORDER BY id DESC", conn)
        conn.close()
        filename = f"DB_Backup_{datetime.datetime.now().strftime('%Y%m%d')}.csv"
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        with open(filename, 'rb') as doc:
            await update.message.reply_document(document=doc, caption=f"📊 تم السحب بنجاح!\nإجمالي الجولات: {len(df)}")
        os.remove(filename)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")

async def force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🧠 جاري التنظيف والتعلم العميق من قاعدة البيانات...")
    try:
        conn = get_db_connection()
        # تحميل البيانات
        df = pd.read_sql("SELECT * FROM history WHERE winner IS NOT NULL", conn)
        
        # 1. تنظيف البيانات (استخراج الأرقام فقط وتجاهل النصوص الخاطئة)
        df['b_num_str'] = df['b_num'].astype(str)
        # الاحتفاظ فقط بالصفوف التي تحتوي على أرقام في عمود البونص
        df = df[df['b_num_str'].str.contains(r'\d', regex=True)]
        # استخراج آخر رقم فعلي
        df['last_digit'] = df['b_num_str'].apply(lambda x: re.sub(r'\D', '', x)[-1] if re.search(r'\d', x) else None)
        
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'last_digit', 'suit'])
        
        # 2. تحليل الأنماط القوية (نسبة النجاح)
        grouped = df.groupby(['suit', 'last_digit'])['winner_code'].value_counts().unstack(fill_value=0)
        
        cur = conn.cursor()
        added, updated = 0, 0
        
        for (suit, digit), row in grouped.iterrows():
            total = row.sum()
            if total >= 5: # يجب أن يكون تكرر النمط 5 مرات على الأقل
                best_winner = row.idxmax()
                best_count = row.max()
                fail_count = total - best_count
                win_rate = best_count / total
                
                # إذا كانت نسبة نجاح هذا النمط أعلى من 60%
                if win_rate >= 0.60:
                    law_name = f"DB_{suit}_{digit}"
                    pattern = {"suit": suit, "last_digit": str(digit), "winner": int(best_winner)}
                    
                    # DO UPDATE لتحديث الأرقام بدلاً من تجاهلها!
                    cur.execute("""
                        INSERT INTO ai_laws (law_name, law_pattern, success_count, fail_count, is_active) 
                        VALUES (%s, %s, %s, %s, TRUE) 
                        ON CONFLICT (law_name) DO UPDATE 
                        SET success_count = EXCLUDED.success_count, 
                            fail_count = EXCLUDED.fail_count,
                            law_pattern = EXCLUDED.law_pattern
                    """, (law_name, json.dumps(pattern), int(best_count), int(fail_count)))
                    added += 1

        # 3. مسح القوانين الفاشلة تماماً من الذاكرة
        cur.execute("DELETE FROM ai_laws WHERE fail_count > success_count OR (success_count = 0 AND fail_count > 2)")
        deleted_bad_laws = cur.rowcount
        
        conn.commit()
        conn.close()
        
        report = (f"✅ **تمت عملية التعلم العميق بنجاح!**\n"
                  f"📥 تم تحليل: {len(df)} جولة صالحة.\n"
                  f"➕ قوانين قوية تمت إضافتها/تحديثها: {added}\n"
                  f"🗑️ قوانين ضعيفة تم تدميرها: {deleted_bad_laws}")
        await msg.edit_text(report, parse_mode='Markdown')
    except Exception as e:
        await msg.edit_text(f"❌ فشل التعلم: {e}")

# ==================== 🎮 واجهة التليجرام الأساسية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🎴 بدء جولة جديدة", callback_data="choose_suit")],
        [InlineKeyboardButton("📜 القوانين النشطة", callback_data="view_laws")]
    ]
    text = "🏛️ **HADES V109 - Deep AI Engine**\n\nأوامر الأدمن:\n`/download` - سحب قاعدة البيانات\n`/force_learn` - تنظيف وتدريب الذكاء الاصطناعي\n\nاختر للبدء:"
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    
    if data == "choose_suit":
        kb = [[InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[:2]],
              [InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[2:]]]
        await query.edit_message_text("🎴 اختر البذلة للجولة الحالية:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("s_"):
        suit = data[2:]
        context.user_data['suit'] = suit
        await query.edit_message_text(f"✅ البذلة محفوظة: {suit}\n\n📥 **أرسل أرقام البونص الآن (يمكنك إرسال أرقام متتالية):**")
    
    elif data == "view_laws":
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT law_name, success_count, fail_count FROM ai_laws ORDER BY (success_count - fail_count) DESC LIMIT 10")
            laws = cur.fetchall()
            conn.close()
            text = "📜 **أقوى 10 قوانين للذكاء الاصطناعي:**\n\n" + "".join([f"🔹 {n} (✅ {s} | ❌ {f})\n" for n, s, f in laws])
            kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="start_back")]]
            await query.edit_message_text(text if laws else "لم يتم بناء قوانين قوية بعد.", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        except: pass

    elif data == "start_back":
        await start(update, context)

    elif data == "delete_last":
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, b_num, suit, winner FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
            row = cur.fetchone()
            if row:
                entry_id, b_num, suit, winner_str = row
                winner_code = WINNER_MAP.get(winner_str.split()[0], 2)
                update_law_stats(b_num, suit, winner_code, revert=True)
                cur.execute("DELETE FROM history WHERE id = %s", (entry_id,))
                conn.commit()
                msg = "🗑️ **تم مسح الجولة الخاطئة وتنظيف ذاكرة الـ AI.**"
            else:
                msg = "⚠️ لا يوجد جولة سابقة لحذفها."
            conn.close()
            kb = [[InlineKeyboardButton("🔄 تغيير البذلة", callback_data="choose_suit")]]
            await query.edit_message_text(f"{msg}\n\nالبذلة المحفوظة: {context.user_data.get('suit', 'غير محدد')}\nأرسل الرقم الصحيح للاستمرار.", reply_markup=InlineKeyboardMarkup(kb))
        except: pass
    
    elif data.startswith("save_"):
        try:
            winner_code = int(data.split("_")[1])
            winner_name = WINNER_NAMES.get(winner_code, "تعادل ⚪")
            
            b_num = context.user_data.get('last_b_num')
            suit = context.user_data.get('last_suit')
            
            if not b_num or not suit:
                await query.edit_message_text("⚠️ بيانات الجولة مفقودة. أرسل الرقم من جديد.")
                return
            
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO history (b_num, suit, winner, timestamp, user_id) VALUES (%s, %s, %s, %s, %s)",
                        (b_num, suit, winner_name, datetime.datetime.now(), user_id))
            conn.commit()
            conn.close()
            
            update_law_stats(b_num, suit, winner_code)
            
            kb = [
                [InlineKeyboardButton("🗑️ تصحيح الجولة", callback_data="delete_last")],
                [InlineKeyboardButton("🔄 تغيير البذلة", callback_data="choose_suit")]
            ]
            await query.edit_message_text(
                f"✅ **تم التسجيل والتدريب:** {winner_name}\n\n"
                f"📥 البذلة الحالية: **{suit}**\nأرسل الرقم التالي للمتابعة:", 
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
            )
        except Exception as e:
            await query.edit_message_text(f"❌ حدث خطأ داخلي. أرسل الرقم مجدداً.\nالخطأ: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text.isdigit() and len(text) >= 5:
        suit = context.user_data.get('suit')
        if not suit:
            await update.message.reply_text("⚠️ الرجاء اختيار البذلة أولاً عبر /start")
            return
        
        pred_code, reason = fast_hybrid_predict(text, suit)
        
        context.user_data['last_b_num'] = text
        context.user_data['last_suit'] = suit
        
        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data="save_0"),
             InlineKeyboardButton("🔵 ثور", callback_data="save_1")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_2")]
        ]
        
        report = f"""🎯 **التوقع اللحظي (V109)**
━━━━━━━━━━━━━━━
🏆 **النتيجة:** {WINNER_NAMES[pred_code]}
⚙️ **الأساس:** {reason}
━━━━━━━━━━━━━━━
اختر الفائز لتسجيل النتيجة وتدريب الـ AI:"""
        
        await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# ==================== 🚀 التشغيل ====================
if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_db))
    app.add_handler(CommandHandler("force_learn", force_learn))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ النظام جاهز - تم تحديث الهيكل بنجاح.")
    app.run_polling(drop_pending_updates=True)
