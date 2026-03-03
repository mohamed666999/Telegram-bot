"""
HADES V106 - Ultimate Hybrid AI System
النظام المتكامل: ذكاء اصطناعي بخلفية ذاتية التطور + ميزة تصحيح الجولات الخاطئة (Undo)
"""

import os, sys, datetime, psycopg2, pandas as pd, numpy as np
import json, re, logging, asyncio
from typing import Dict, List, Tuple, Optional, Any
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, JobQueue
)
from openai import AsyncOpenAI

# ==================== 🛡️ الإعدادات الأساسية ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

WARMUP_ROUNDS = 700
WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

DYNAMIC_CONFIG = {'S_RED': 1.0, 'S_BLACK': 1.0}

# ==================== 🗄️ إدارة قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def ensure_columns():
    """التأكد من وجود الأعمدة من الكود القديم (مثل user_id) وجداول الـ AI الجديدة"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # إضافة user_id لو لم يكن موجوداً
        cur.execute("""
            DO $$ BEGIN
                ALTER TABLE history ADD COLUMN user_id BIGINT;
            EXCEPTION WHEN duplicate_column THEN NULL; END $$;
        """)
        
        # جداول الـ AI
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_laws (
            law_name VARCHAR(100) PRIMARY KEY,
            law_pattern JSONB,
            success_count INT DEFAULT 0,
            fail_count INT DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Init Error: {e}")

def load_history(limit: int = 1000) -> pd.DataFrame:
    try:
        conn = get_db_connection()
        df = pd.read_sql(f"SELECT * FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT {limit}", conn)
        conn.close()
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        return df.dropna(subset=['winner_code'])
    except:
        return pd.DataFrame()

# ==================== 🤖 محرك الذكاء الاصطناعي (Async) ====================
class AsyncAIEngine:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL, timeout=10.0)
        self.model = NVIDIA_MODEL

    async def ask_json(self, prompt: str) -> Optional[Dict]:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Respond strictly in JSON format. No explanations."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3, max_tokens=800
            )
            content = response.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match: return json.loads(match.group())
        except Exception as e:
            logger.error(f"❌ AI API Error: {e}")
        return None

ai_engine = AsyncAIEngine()

# ==================== ⚙️ مهام الخلفية الذاتية (Background Jobs) ====================
async def task_5m_quick_sync(context: ContextTypes.DEFAULT_TYPE):
    df = load_history(50)
    if len(df) < 20: return
    red_ratio = df['winner_code'].value_counts(normalize=True).to_dict().get(0, 0.5)
    
    global DYNAMIC_CONFIG
    if red_ratio > 0.6: DYNAMIC_CONFIG['S_RED'], DYNAMIC_CONFIG['S_BLACK'] = 1.2, 0.8
    elif red_ratio < 0.4: DYNAMIC_CONFIG['S_RED'], DYNAMIC_CONFIG['S_BLACK'] = 0.8, 1.2
    else: DYNAMIC_CONFIG['S_RED'], DYNAMIC_CONFIG['S_BLACK'] = 1.0, 1.0

async def task_15m_pattern_discovery(context: ContextTypes.DEFAULT_TYPE):
    df = load_history(200)
    if len(df) < 50: return
    df['last_digit'] = df['b_num'].astype(str).str[-1]
    grouped = df.groupby(['suit', 'last_digit'])['winner_code'].agg(lambda x: x.value_counts().index[0] if x.value_counts().max() >= 4 else None).dropna()
    
    conn = get_db_connection()
    cur = conn.cursor()
    for (suit, digit), winner_code in grouped.items():
        law_name = f"Auto_{suit}_{digit}"
        pattern = {"suit": suit, "last_digit": digit, "winner": int(winner_code)}
        cur.execute("""INSERT INTO ai_laws (law_name, law_pattern) VALUES (%s, %s) ON CONFLICT (law_name) DO NOTHING""", (law_name, json.dumps(pattern)))
    conn.commit()
    conn.close()

async def task_60m_ai_master_audit(context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT law_name, law_pattern, success_count, fail_count FROM ai_laws")
    current_laws = [{"name": r[0], "pattern": r[1], "success": r[2], "fails": r[3]} for r in cur.fetchall()]
    
    df = load_history(300)
    recent_winners = df['winner_code'].tolist()[:50] if not df.empty else []
    
    prompt = f"""
    You are the Master AI. Recent 50 outcomes (0=Red, 1=Blue, 2=Tie): {recent_winners}
    Current Laws: {json.dumps(current_laws)}
    Respond in JSON:
    {{"delete_laws": ["bad_law_1"], "new_laws": [{{"law_name": "AI_Law_1", "pattern": {{"suit": "♥️", "last_digit": "5", "winner": 0}}}}]}}
    """
    decision = await ai_engine.ask_json(prompt)
    if decision:
        for bad_law in decision.get("delete_laws", []):
            cur.execute("DELETE FROM ai_laws WHERE law_name = %s", (bad_law,))
        for new_law in decision.get("new_laws", []):
            if new_law.get("law_name") and new_law.get("pattern"):
                cur.execute("""INSERT INTO ai_laws (law_name, law_pattern, success_count, fail_count) VALUES (%s, %s, 0, 0) ON CONFLICT (law_name) DO UPDATE SET law_pattern = EXCLUDED.law_pattern""", (new_law["law_name"], json.dumps(new_law["pattern"])))
        conn.commit()
    conn.close()

# ==================== ⚡ محرك التوقع الفوري السريع ====================
def fast_hybrid_predict(b_num: str, suit: str) -> Tuple[int, str]:
    last_digit = b_num[-1] if b_num[-1].isdigit() else '0'
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT law_name, law_pattern FROM ai_laws WHERE is_active = TRUE")
    for law_name, pattern in cur.fetchall():
        if pattern.get('suit') == suit and str(pattern.get('last_digit')) == str(last_digit):
            conn.close()
            return pattern.get('winner', 2), f"📜 قانون AI: {law_name}"
    conn.close()
    
    last3 = sum(int(d) for d in b_num[-3:] if d.isdigit())
    S = DYNAMIC_CONFIG['S_RED'] if suit in ['♦️', '♥️'] else DYNAMIC_CONFIG['S_BLACK']
    math_result = int((last3 * S) + (int(last_digit) * 3)) % 2
    return math_result, "🧮 تحليل رياضي ديناميكي"

def update_law_stats(b_num: str, suit: str, actual_winner: int, revert: bool = False):
    """تحديث ذاكرة الـ AI (إضافة نجاح/فشل، أو خصمها في حالة تصحيح الجولة)"""
    last_digit = b_num[-1] if b_num[-1].isdigit() else '0'
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

# ==================== 🎮 واجهة التليجرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🎴 بدء جولة جديدة", callback_data="choose_suit")],
        [InlineKeyboardButton("📜 القوانين النشطة", callback_data="view_laws")]
    ]
    await update.message.reply_text("🏛️ **HADES V106 - AI Engine**\n\nاختر للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def delete_last_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    """ميزة حذف الجولة الخاطئة وتنظيف ذاكرة الـ AI (مقتبسة من الكود القديم ومطورة)"""
    user_id = update.effective_user.id
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, b_num, suit, winner FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        
        if row:
            entry_id, b_num, suit, winner_str = row
            winner_code = WINNER_MAP.get(winner_str.split()[0], 2)
            
            # مسح النتيجة من ذاكرة الـ AI لكي لا يتعلم بالخطأ
            update_law_stats(b_num, suit, winner_code, revert=True)
            
            # مسح النتيجة من قاعدة البيانات
            cur.execute("DELETE FROM history WHERE id = %s", (entry_id,))
            conn.commit()
            msg = "🗑️ **تم الحذف بنجاح!**\nتم مسح الجولة الخاطئة وتنظيف ذاكرة الذكاء الاصطناعي منها."
        else:
            msg = "⚠️ لا يوجد إدخال سابق لك لحذفه."
        conn.close()
        
        if is_callback:
            kb = [[InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")]]
            await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        else:
            await update.message.reply_text(msg, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Delete Error: {e}")

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
        await query.edit_message_text(f"✅ البذلة: {suit}\n\n📥 **أرسل رقم البونص الآن (7 أرقام):**")
    
    elif data == "view_laws":
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT law_name, success_count, fail_count FROM ai_laws ORDER BY success_count DESC LIMIT 10")
        laws = cur.fetchall()
        conn.close()
        text = "📜 **أفضل القوانين الحالية:**\n\n" + "".join([f"🔹 {n} (نجاح: {s} | فشل: {f})\n" for n, s, f in laws])
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="start_back")]]
        await query.edit_message_text(text if laws else "لم تبنَ القوانين بعد.", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == "start_back":
        await start(update, context)

    elif data == "delete_last":
        await delete_last_entry(update, context, is_callback=True)

    elif data.startswith("save_"):
        parts = data.split("_")
        b_num, suit, winner_name = parts[1], parts[2], "_".join(parts[3:])
        winner_code = WINNER_MAP.get(winner_name.split()[0], 2)
        
        # حفظ النتيجة لتعليم الـ AI
        update_law_stats(b_num, suit, winner_code)
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO history (b_num, suit, winner, timestamp, user_id) VALUES (%s, %s, %s, %s, %s)",
                        (b_num, suit, winner_name, datetime.datetime.now(), user_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Save error: {e}")
        
        # الأزرار الهجينة (تكملة + تصحيح)
        kb = [
            [InlineKeyboardButton("🔄 بدء جولة جديدة", callback_data="choose_suit")],
            [InlineKeyboardButton("🗑️ تصحيح (حذف الجولة المضافة)", callback_data="delete_last")]
        ]
        await query.edit_message_text(f"✅ تم التدريب والتسجيل: ({winner_name})\nماذا تريد أن تفعل الآن؟", reply_markup=InlineKeyboardMarkup(kb))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text.isdigit() and len(text) >= 5:
        suit = context.user_data.get('suit')
        if not suit:
            await update.message.reply_text("⚠️ **اختر البذلة أولاً عبر /start**")
            return
            
        pred_code, reason = fast_hybrid_predict(text, suit)
        prediction = WINNER_NAMES[pred_code]
        
        report = f"""🎯 **التوقع اللحظي (V106)**
━━━━━━━━━━━━━━━
🏆 **النتيجة:** {prediction}
⚙️ **الأساس:** {reason}
━━━━━━━━━━━━━━━
اختر الفائز الفعلي لتسجيل النتيجة:"""
        
        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data=f"save_{text}_{suit}_الراعي 🔴"),
             InlineKeyboardButton("🔵 ثور", callback_data=f"save_{text}_{suit}_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data=f"save_{text}_{suit}_تعادل ⚪")]
        ]
        
        await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        context.user_data.pop('suit', None) 
        return

# ==================== 🚀 التشغيل الأساسي ====================
if __name__ == "__main__":
    logger.info("🚀 تشغيل HADES V106...")
    ensure_columns()

    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("delete", delete_last_entry))  # أمر الحذف القديم موجود أيضاً
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    jq = app.job_queue
    jq.run_repeating(task_5m_quick_sync, interval=300, first=10)
    jq.run_repeating(task_15m_pattern_discovery, interval=900, first=20)
    jq.run_repeating(task_60m_ai_master_audit, interval=3600, first=30)
    
    logger.info("✅ النظام جاهز.")
    app.run_polling(drop_pending_updates=True)
