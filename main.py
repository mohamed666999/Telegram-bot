"""
HADES V104 - Fully Autonomous Hybrid Prediction System
نظام تنبؤ هجين متكامل: معادلة رياضية + بايزي + NVIDIA AI + قوانين ذاتية التطور
"""

import os, sys, datetime, psycopg2, pandas as pd, numpy as np
import json, re, logging, random, secrets, asyncio
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, JobQueue
)
from openai import OpenAI

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
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

DYNAMIC_CONFIG = {
    'CONFIDENCE_THRESHOLD': 0.65, 'MATH_WEIGHT': 0.35, 'AI_WEIGHT': 0.40, 'LAW_WEIGHT': 0.25,
    'S_RED': 1.0, 'S_BLACK': 1.0, 'VOTE_THRESHOLD': 2,
}

# ==================== 🗄️ إدارة قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def load_filtered_history(min_id: int = WARMUP_ROUNDS + 1) -> pd.DataFrame:
    try:
        conn = get_db_connection()
        query = f"SELECT * FROM history WHERE winner IS NOT NULL AND id >= {min_id} ORDER BY id ASC"
        df = pd.read_sql(query, conn)
        conn.close()
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        return df.dropna(subset=['winner_code'])
    except:
        return pd.DataFrame()

def get_latest_stats(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty: return {}
    stats = {'total_rounds': len(df), 'bias': {'red': 0, 'blue': 0, 'tie': 0}}
    total = len(df)
    stats['bias'] = {
        'red': float((df['winner'] == 'الراعي 🔴').sum() / total) if total > 0 else 0,
        'blue': float((df['winner'] == 'الثور 🔵').sum() / total) if total > 0 else 0,
        'tie': float((df['winner'] == 'تعادل ⚪').sum() / total) if total > 0 else 0
    }
    return stats

# ==================== 🤖 محرك الذكاء الاصطناعي المتطور ====================
class AdvancedAIEngine:
    def __init__(self):
        self.client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
        self.model = NVIDIA_MODEL

    def ask_json(self, prompt: str) -> Optional[Dict]:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You must respond with valid JSON only. No markdown, no explanations."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=500
            )
            content = response.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            logger.error(f"❌ خطأ في استدعاء AI: {e}")
        return None
    
    def direct_predict(self, df: pd.DataFrame, b_num: str, suit: str) -> Tuple[int, float]:
        """توقع الـ AI المباشر للجولة الحالية"""
        recent = df.tail(15)['winner'].tolist() if not df.empty else []
        prompt = f"""
        Game history (last 15 winners): {recent}
        Current Round -> Bonus Number: {b_num}, Suit: {suit}
        Based on patterns, predict the next winner.
        Respond ONLY with JSON: {{"prediction": 0, "confidence": 0.85}} 
        (0=Red, 1=Blue, 2=Tie).
        """
        res = self.ask_json(prompt)
        if res and 'prediction' in res:
            return int(res['prediction']), float(res.get('confidence', 0.5))
        return 2, 0.33

# ==================== ⚙️ المحرك الرياضي والقوانين ====================
def get_active_laws() -> List[Dict]:
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT law_name, law_pattern FROM ai_laws WHERE is_active=TRUE")
        laws = [{'name': r[0], 'pattern': r[1]} for r in cur.fetchall()]
        conn.close()
        return laws
    except:
        return []

def math_engine(b_num: str, suit: str) -> int:
    """معادلة رياضية أساسية لتوليد توقع رياضي"""
    last3 = sum(int(d) for d in b_num[-3:] if d.isdigit())
    last_digit = int(b_num[-1]) if b_num[-1].isdigit() else 0
    S = DYNAMIC_CONFIG['S_RED'] if suit in ['♦️', '♥️'] else DYNAMIC_CONFIG['S_BLACK']
    result = (last3 * S) + (last_digit * 3)
    return int(result) % 2

def apply_laws(b_num: str, suit: str) -> Optional[int]:
    """تطبيق القوانين المستخرجة من قاعدة البيانات"""
    laws = get_active_laws()
    last_digit = b_num[-1] if b_num[-1].isdigit() else '0'
    for law in laws:
        pat = law['pattern']
        if isinstance(pat, dict):
            # إذا تطابقت البذلة والرقم الأخير مع قانون مسجل
            if pat.get('suit') == suit and str(pat.get('last_digit')) == str(last_digit):
                winner_str = pat.get('winner', '')
                return WINNER_MAP.get(winner_str)
    return None

# ==================== 🧠 العقل المدبر (النظام الهجين) ====================
def hybrid_prediction_system(b_num: str, suit: str) -> Tuple[str, str, float]:
    """
    يجمع بين: (1) الذكاء الاصطناعي (2) المحرك الرياضي (3) القوانين الذكية
    """
    df = load_filtered_history()
    ai_engine = AdvancedAIEngine()
    
    # 1. توقع الذكاء الاصطناعي المباشر
    ai_pred, ai_conf = ai_engine.direct_predict(df, b_num, suit)
    
    # 2. توقع المحرك الرياضي
    math_pred = math_engine(b_num, suit)
    
    # 3. توقع القوانين (إن وجدت)
    law_pred = apply_laws(b_num, suit)
    
    # --- نظام التصويت المرجح ---
    votes = {0: 0.0, 1: 0.0, 2: 0.0}
    
    # وزن الـ AI
    votes[ai_pred] += DYNAMIC_CONFIG['AI_WEIGHT'] * ai_conf
    
    # وزن الرياضيات
    votes[math_pred] += DYNAMIC_CONFIG['MATH_WEIGHT']
    
    # وزن القوانين المستنتجة
    if law_pred is not None:
        votes[law_pred] += DYNAMIC_CONFIG['LAW_WEIGHT']
    
    # تحديد الفائز النهائي
    final_pred = max(votes, key=votes.get)
    total_weight = sum(votes.values())
    confidence = (votes[final_pred] / total_weight) if total_weight > 0 else 0.5
    
    # توليد التقرير
    reasons = []
    if ai_pred == final_pred: reasons.append("🤖 توافق ذكاء اصطناعي")
    if math_pred == final_pred: reasons.append("🧮 معادلة رياضية")
    if law_pred == final_pred: reasons.append("📜 قانون تاريخي مطابق")
    
    reason_str = " + ".join(reasons) if reasons else "تحليل إحصائي عام"
    
    return WINNER_NAMES[final_pred], reason_str, confidence

# ==================== 👁️ مراقب الذكاء الاصطناعي الخلفي ====================
async def ai_observer_task(context: ContextTypes.DEFAULT_TYPE):
    """يعمل كل فترة للبحث عن قوانين جديدة في قاعدة البيانات"""
    logger.info("🔍 [AI Observer] بدء تحليل قاعدة البيانات لاكتشاف قوانين...")
    df = load_filtered_history(WARMUP_ROUNDS)
    if len(df) < 50: return
    
    # البحث عن أنماط قوية متكررة
    df_copy = df.tail(100).copy()
    if 'suit' in df_copy.columns and 'b_num' in df_copy.columns:
        df_copy['last_digit'] = df_copy['b_num'].astype(str).str[-1]
        
        # تجميع حسب البذلة والرقم الأخير
        grouped = df_copy.groupby(['suit', 'last_digit'])['winner'].agg(lambda x: x.value_counts().index[0] if x.value_counts().max() >= 3 else None).dropna()
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        for (suit, digit), winner in grouped.items():
            law_name = f"Law_{suit}_{digit}"
            pattern = {"suit": suit, "last_digit": digit, "winner": winner}
            
            cur.execute("""
                INSERT INTO ai_laws (law_name, law_pattern, is_active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (law_name) DO NOTHING
            """, (law_name, json.dumps(pattern)))
            
        conn.commit()
        conn.close()
        logger.info("✅ [AI Observer] تم تحديث القوانين بنجاح.")

# ==================== 🎮 واجهة التليجرام التفاعلية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="view_stats")],
        [InlineKeyboardButton("📜 القوانين النشطة", callback_data="view_laws")]
    ]
    await update.message.reply_text("🏛️ **HADES V104 - Hybrid AI Engine**\n\nأهلاً بك، اختر الإجراء للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

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
        await query.edit_message_text(f"✅ تم اختيار البذلة: {suit}\n\n📥 **الآن قم بإرسال رقم البونص (مثال: 1045621) في رسالة عادية وسأقوم بتوقع النتيجة فوراً.**")
    
    elif data == "view_stats":
        df = load_filtered_history()
        stats = get_latest_stats(df)
        report = f"📊 إجمالي الجولات: {stats.get('total_rounds', 0)}\n🔴 راعي: %{stats.get('bias',{}).get('red',0)*100:.1f}\n🔵 ثور: %{stats.get('bias',{}).get('blue',0)*100:.1f}"
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="start_back")]]
        await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "view_laws":
        laws = get_active_laws()
        report = "📜 **القوانين المستنتجة ذاتياً:**\n" + "\n".join([f"• {l['name']}" for l in laws[:10]]) if laws else "لم يتم استنتاج قوانين كافية بعد."
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="start_back")]]
        await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == "start_back":
        await start(update, context)

    elif data.startswith("save_"):
        parts = data.split("_")
        b_num, suit, winner = parts[1], parts[2], "_".join(parts[3:])
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                        (b_num, suit, winner, datetime.datetime.now()))
            conn.commit()
            conn.close()
            kb = [[InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ تم حفظ الفائز ({winner}) للجولة.\nاختر لبدء جولة جديدة:", reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            await query.edit_message_text("❌ حدث خطأ أثناء الحفظ.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    # إذا كان المستخدم أرسل أرقاماً (يعتبرها البوت رقم بونص)
    if text.isdigit() and len(text) >= 5:
        suit = context.user_data.get('suit')
        if not suit:
            await update.message.reply_text("⚠️ **يجب اختيار البذلة أولاً!**\nاضغط على /start ثم اختر البذلة.")
            return
            
        processing_msg = await update.message.reply_text(f"🔄 جاري التحليل الهجين...\nالرقم: {text} | البذلة: {suit}\n(يتم دمج AI + القوانين + الرياضيات)...")
        
        # توليد التوقع عبر المحرك الهجين
        prediction, reason, confidence = hybrid_prediction_system(text, suit)
        
        report = f"""🎯 **التوقع النهائي (HADES V104)**
━━━━━━━━━━━━━━━
🏆 **النتيجة:** {prediction}
📊 **الثقة:** %{confidence*100:.1f}
⚙️ **أساس التوقع:** {reason}
━━━━━━━━━━━━━━━
اختر الفائز الفعلي لحفظه وتدريب الذكاء الاصطناعي:"""
        
        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data=f"save_{text}_{suit}_الراعي 🔴"),
             InlineKeyboardButton("🔵 ثور", callback_data=f"save_{text}_{suit}_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data=f"save_{text}_{suit}_تعادل ⚪")]
        ]
        
        await processing_msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        # مسح البذلة بعد التوقع لإجبار المستخدم على اختيارها للجولة القادمة
        context.user_data.pop('suit', None) 
        return
        
    await update.message.reply_text("أرسل أرقام البونص فقط بعد اختيار البذلة، أو اضغط /start للقائمة.")

# ==================== 🚀 التشغيل الرئيسي ====================
if __name__ == "__main__":
    logger.info("🚀 بدء تشغيل HADES V104...")
    
    # إعداد قاعدة البيانات
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_laws (
            id SERIAL PRIMARY KEY, law_name VARCHAR(100) UNIQUE NOT NULL,
            law_pattern JSONB, is_active BOOLEAN DEFAULT TRUE)""")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Error: {e}")

    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # تشغيل مراقب AI كل 15 دقيقة ليحدث القوانين
    app.job_queue.run_repeating(ai_observer_task, interval=900, first=30)
    
    logger.info("✅ البوت يعمل الآن وينتظر الأوامر.")
    app.run_polling(drop_pending_updates=True)
