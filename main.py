"""
HADES V105 - Fully Autonomous Hybrid Prediction System
نظام تنبؤ هجين متكامل وذاتي التطور يعمل في الخلفية بشكل دائم
التحليل الدوري: 5 دقائق (أوزان) - 15 دقيقة (أنماط) - 60 دقيقة (تحكم AI بالقوانين)
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
# استخدام النسخة غير المتزامنة لضمان سرعة البوت وعدم تجمده
from openai import AsyncOpenAI

# ==================== 🛡️ الإعدادات الأساسية ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ✅ المفاتيح 
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

# أوزان النظام (يتم تعديلها تلقائياً بواسطة AI)
DYNAMIC_CONFIG = {
    'MATH_WEIGHT': 0.30, 'LAW_WEIGHT': 0.60, 'LIVE_AI_WEIGHT': 0.10,
    'S_RED': 1.0, 'S_BLACK': 1.0
}

# ==================== 🗄️ إدارة قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # إضافة أعمدة للتقييم لكي يتمكن الـ AI من معرفة القوانين الفاشلة
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
        query = f"SELECT * FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT {limit}"
        df = pd.read_sql(query, conn)
        conn.close()
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        return df.dropna(subset=['winner_code'])
    except:
        return pd.DataFrame()

# ==================== 🤖 محرك الذكاء الاصطناعي (Async) ====================
class AsyncAIEngine:
    def __init__(self):
        # استخدام مهلة (timeout) لمنع البوت من التعليق
        self.client = AsyncOpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL, timeout=10.0)
        self.model = NVIDIA_MODEL

    async def ask_json(self, prompt: str) -> Optional[Dict]:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Respond strictly in JSON format. No explanations. Keys and values must be valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            content = response.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            logger.error(f"❌ AI API Error: {e}")
        return None

ai_engine = AsyncAIEngine()

# ==================== ⚙️ مهام الخلفية الذاتية (Background Jobs) ====================

async def task_5m_quick_sync(context: ContextTypes.DEFAULT_TYPE):
    """كل 5 دقائق: ضبط سريع للأوزان بناءً على آخر 50 جولة"""
    logger.info("⏱️ [5m Task] جاري المزامنة السريعة وتعديل الأوزان...")
    df = load_history(50)
    if len(df) < 20: return
    
    counts = df['winner_code'].value_counts(normalize=True).to_dict()
    red_ratio = counts.get(0, 0.5)
    
    # تعديل رياضي ديناميكي
    global DYNAMIC_CONFIG
    if red_ratio > 0.6:
        DYNAMIC_CONFIG['S_RED'] = 1.2
        DYNAMIC_CONFIG['S_BLACK'] = 0.8
    elif red_ratio < 0.4:
        DYNAMIC_CONFIG['S_RED'] = 0.8
        DYNAMIC_CONFIG['S_BLACK'] = 1.2
    else:
        DYNAMIC_CONFIG['S_RED'] = 1.0
        DYNAMIC_CONFIG['S_BLACK'] = 1.0

async def task_15m_pattern_discovery(context: ContextTypes.DEFAULT_TYPE):
    """كل 15 دقيقة: اكتشاف الأنماط الرياضية وإضافتها كقوانين مبدئية"""
    logger.info("⏱️ [15m Task] البحث عن أنماط جديدة في قاعدة البيانات...")
    df = load_history(200)
    if len(df) < 50: return
    
    df['last_digit'] = df['b_num'].astype(str).str[-1]
    grouped = df.groupby(['suit', 'last_digit'])['winner_code'].agg(lambda x: x.value_counts().index[0] if x.value_counts().max() >= 4 else None).dropna()
    
    conn = get_db_connection()
    cur = conn.cursor()
    for (suit, digit), winner_code in grouped.items():
        law_name = f"Auto_{suit}_{digit}"
        pattern = {"suit": suit, "last_digit": digit, "winner": int(winner_code)}
        cur.execute("""
            INSERT INTO ai_laws (law_name, law_pattern)
            VALUES (%s, %s) ON CONFLICT (law_name) DO NOTHING
        """, (law_name, json.dumps(pattern)))
    conn.commit()
    conn.close()

async def task_60m_ai_master_audit(context: ContextTypes.DEFAULT_TYPE):
    """كل 60 دقيقة: يتحكم الـ AI بالكامل بالقوانين (يحذف الفاشل ويصنع الجديد)"""
    logger.info("👑 [60m Task] الـ AI يقوم الآن بالمراجعة الشاملة للقوانين...")
    
    # جلب القوانين الحالية
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT law_name, law_pattern, success_count, fail_count FROM ai_laws")
    current_laws = [{"name": r[0], "pattern": r[1], "success": r[2], "fails": r[3]} for r in cur.fetchall()]
    
    # جلب آخر الإحصائيات
    df = load_history(300)
    recent_winners = df['winner_code'].tolist()[:50] if not df.empty else []
    
    prompt = f"""
    You are the Master AI of a prediction game.
    Recent 50 game outcomes (0=Red, 1=Blue, 2=Tie): {recent_winners}
    Current Laws in Database: {json.dumps(current_laws)}
    
    Task:
    1. Identify bad laws (high fails compared to success) to DELETE.
    2. Create strictly 2 NEW logical laws based on recent outcomes.
    
    Respond ONLY with this JSON structure:
    {{
        "delete_laws": ["law_name_1", "law_name_2"],
        "new_laws": [
            {{"law_name": "AI_Law_1", "pattern": {{"suit": "♥️", "last_digit": "5", "winner": 0}}}}
        ]
    }}
    """
    
    decision = await ai_engine.ask_json(prompt)
    if decision:
        deleted = 0
        added = 0
        # تنفيذ أوامر الـ AI
        for bad_law in decision.get("delete_laws", []):
            cur.execute("DELETE FROM ai_laws WHERE law_name = %s", (bad_law,))
            deleted += cur.rowcount
            
        for new_law in decision.get("new_laws", []):
            name = new_law.get("law_name")
            pattern = new_law.get("pattern")
            if name and pattern:
                cur.execute("""
                    INSERT INTO ai_laws (law_name, law_pattern, success_count, fail_count)
                    VALUES (%s, %s, 0, 0) ON CONFLICT (law_name) DO UPDATE SET law_pattern = EXCLUDED.law_pattern
                """, (name, json.dumps(pattern)))
                added += 1
                
        conn.commit()
        logger.info(f"✅ [Master AI] قام بحذف {deleted} قانون وصناعة {added} قانون جديد.")
    conn.close()

# ==================== ⚡ محرك التوقع الفوري السريع ====================
def fast_hybrid_predict(b_num: str, suit: str) -> Tuple[int, str]:
    """يستخدم القوانين المجهزة مسبقاً والرياضيات للرد في جزء من الثانية"""
    last_digit = b_num[-1] if b_num[-1].isdigit() else '0'
    
    # 1. البحث في قوانين الـ AI الجاهزة
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT law_name, law_pattern FROM ai_laws WHERE is_active = TRUE")
    laws = cur.fetchall()
    conn.close()
    
    for law_name, pattern in laws:
        if pattern.get('suit') == suit and str(pattern.get('last_digit')) == str(last_digit):
            return pattern.get('winner', 2), f"📜 تم تطبيق قانون الـ AI: {law_name}"
    
    # 2. إذا لم يوجد قانون، استخدم المعادلة الرياضية الديناميكية
    last3 = sum(int(d) for d in b_num[-3:] if d.isdigit())
    S = DYNAMIC_CONFIG['S_RED'] if suit in ['♦️', '♥️'] else DYNAMIC_CONFIG['S_BLACK']
    math_result = int((last3 * S) + (int(last_digit) * 3)) % 2
    
    return math_result, "🧮 تحليل رياضي ديناميكي"

def update_law_stats(b_num: str, suit: str, actual_winner: int):
    """تحديث نجاح أو فشل القانون بعد معرفة النتيجة الحقيقية للتعلم المستمر"""
    last_digit = b_num[-1] if b_num[-1].isdigit() else '0'
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT law_name, law_pattern FROM ai_laws WHERE is_active = TRUE")
    for law_name, pattern in cur.fetchall():
        if pattern.get('suit') == suit and str(pattern.get('last_digit')) == str(last_digit):
            if pattern.get('winner') == actual_winner:
                cur.execute("UPDATE ai_laws SET success_count = success_count + 1 WHERE law_name = %s", (law_name,))
            else:
                cur.execute("UPDATE ai_laws SET fail_count = fail_count + 1 WHERE law_name = %s", (law_name,))
    conn.commit()
    conn.close()

# ==================== 🎮 واجهة التليجرام (الأزرار) ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🎴 اختيار البذلة للبدء", callback_data="choose_suit")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="view_stats"),
         InlineKeyboardButton("📜 القوانين النشطة", callback_data="view_laws")]
    ]
    await update.message.reply_text(
        "🏛️ **HADES V105 - Autonomous AI**\n\n"
        "النظام يحلل ويتطور في الخلفية (5، 15، 60 دقيقة).\n"
        "اختر البذلة وسأعطيك توقعاً لحظياً:", 
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "choose_suit":
        kb = [[InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[:2]],
              [InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[2:]]]
        await query.edit_message_text("🎴 اختر البذلة للجولة الحالية:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("s_"):
        suit = data[2:]
        context.user_data['suit'] = suit
        await query.edit_message_text(f"✅ البذلة: {suit}\n\n📥 **أرسل رقم البونص الآن في رسالة للحصول على التوقع:**")
    
    elif data == "view_laws":
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT law_name, success_count, fail_count FROM ai_laws ORDER BY success_count DESC LIMIT 10")
        laws = cur.fetchall()
        conn.close()
        text = "📜 **أفضل القوانين التي يتحكم بها AI:**\n\n"
        for name, succ, fail in laws:
            text += f"🔹 {name} (نجاح: {succ} | فشل: {fail})\n"
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="start_back")]]
        await query.edit_message_text(text if laws else "لم يقم الـ AI ببناء قوانين بعد.", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == "start_back":
        await start(update, context)

    elif data.startswith("save_"):
        parts = data.split("_")
        b_num, suit, winner_name = parts[1], parts[2], "_".join(parts[3:])
        winner_code = WINNER_MAP.get(winner_name.split()[0], 2)
        
        # حفظ النتيجة لتعليم القوانين وتطوير الـ AI
        update_law_stats(b_num, suit, winner_code)
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                        (b_num, suit, winner_name, datetime.datetime.now()))
            conn.commit()
            conn.close()
        except: pass
        
        kb = [[InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")]]
        await query.edit_message_text(f"✅ تم تعليم النظام بأن الفائز كان ({winner_name}).\nاستمر باللعب:", reply_markup=InlineKeyboardMarkup(kb))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text.isdigit() and len(text) >= 5:
        suit = context.user_data.get('suit')
        if not suit:
            await update.message.reply_text("⚠️ **الرجاء اختيار البذلة أولاً عبر /start**")
            return
            
        # توقع فوري لحظي (لا يوجد انتظار)
        pred_code, reason = fast_hybrid_predict(text, suit)
        prediction = WINNER_NAMES[pred_code]
        
        report = f"""🎯 **التوقع اللحظي (HADES V105)**
━━━━━━━━━━━━━━━
🏆 **النتيجة المتوقعة:** {prediction}
⚙️ **سبب التوقع:** {reason}
━━━━━━━━━━━━━━━
اختر الفائز الحقيقي لتحديث وتدريب قوانين الـ AI فوراً:"""
        
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
    logger.info("🚀 جاري تهيئة HADES V105...")
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()
    
    # إضافة Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # ⚙️ تفعيل المهام الذاتية الدورية في الخلفية (Jobs)
    jq = app.job_queue
    jq.run_repeating(task_5m_quick_sync, interval=300, first=10)        # كل 5 دقائق
    jq.run_repeating(task_15m_pattern_discovery, interval=900, first=20) # كل 15 دقيقة
    jq.run_repeating(task_60m_ai_master_audit, interval=3600, first=30)  # كل 60 دقيقة
    
    logger.info("✅ البوت يعمل والذكاء الاصطناعي يقوم بالتحليل في الخلفية.")
    app.run_polling(drop_pending_updates=True)
