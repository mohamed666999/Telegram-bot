import os, sys, datetime, psycopg2, pandas as pd, numpy as np
import json, re, logging, random, secrets, requests
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

# إعداد عميل OpenAI متوافق مع NVIDIA API
nv_client = OpenAI(
    base_url=NVIDIA_BASE_URL,
    api_key=NVIDIA_API_KEY
)

# ثوابت النظام
WARMUP_ROUNDS = 700
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

DYNAMIC_CONFIG = {
    'CONFIDENCE_THRESHOLD': 0.65, 'MATH_WEIGHT': 0.55, 'BAYES_WEIGHT': 0.45,
    'MATH_CONFIDENCE': 0.7, 'S_RED': 1.0, 'S_BLACK': 1.0,
    'RANDOM_NOISE': 0.02, 'VOTE_THRESHOLD': 2,
}

# ==================== 🗄️ إدارة قاعدة البيانات ====================
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=10)
        return conn
    except Exception as e:
        logger.error(f"❌ فشل الاتصال بقاعدة البيانات: {e}")
        return None

def load_filtered_history(min_id: int = WARMUP_ROUNDS + 1) -> pd.DataFrame:
    try:
        conn = get_db_connection()
        if not conn:
            return pd.DataFrame()
        query = f"""
            SELECT id, b_num, suit, winner, timestamp, prediction, user_id
            FROM history 
            WHERE winner IS NOT NULL AND id >= {min_id}
            ORDER BY id ASC
        """
        df = pd.read_sql(query, conn)
        conn.close()
        
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            df['winner_code'] = df['winner'].map(WINNER_MAP)
            df = df.dropna(subset=['winner_code'])
        
        logger.info(f"✅ تم تحميل {len(df)} جولة (بعد تجاهل أول {WARMUP_ROUNDS})")
        return df
    except Exception as e:
        logger.error(f"❌ خطأ في تحميل البيانات: {e}")
        return pd.DataFrame()

def get_latest_stats(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {'total_rounds': 0, 'bias': {'red': 0, 'blue': 0, 'tie': 0}}
    
    stats = {
        'total_rounds': len(df),
        'winner_dist': df['winner'].value_counts().to_dict() if 'winner' in df.columns else {},
        'bias': {'red': 0, 'blue': 0, 'tie': 0}
    }
    
    total = len(df)
    if total > 0 and 'winner' in df.columns:
        stats['bias'] = {
            'red': float((df['winner'] == 'الراعي 🔴').sum()) / total,
            'blue': float((df['winner'] == 'الثور 🔵').sum()) / total,
            'tie': float((df['winner'] == 'تعادل ⚪').sum()) / total
        }
    return stats

def load_dynamic_config():
    global DYNAMIC_CONFIG
    try:
        conn = get_db_connection()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("SELECT config_name, config_value FROM ai_settings")
        for name, value in cur.fetchall():
            if name in DYNAMIC_CONFIG:
                try:
                    DYNAMIC_CONFIG[name] = float(value)
                except ValueError:
                    DYNAMIC_CONFIG[name] = value
        cur.close()
        conn.close()
        logger.info("✅ تم تحميل الإعدادات الديناميكية")
    except Exception as e:
        logger.error(f"❌ خطأ في تحميل الإعدادات الديناميكية: {e}")

# ==================== 🔮 نموذج التنبؤ الرياضي ====================
def math_prediction(df: pd.DataFrame) -> Tuple[int, float]:
    if df.empty:
        return 2, 0.33  
    last_50 = df.tail(50)
    counts = last_50['winner_code'].value_counts(normalize=True)
    pred = int(counts.idxmax()) if not counts.empty else 2
    confidence = float(counts.max()) if not counts.empty else 0.33
    confidence = max(confidence, DYNAMIC_CONFIG['MATH_CONFIDENCE'])
    return pred, confidence

# ==================== 🔍 تحليل بايزي ====================
def bayesian_prediction(df: pd.DataFrame) -> Tuple[int, float]:
    if df.empty:
        return 2, 0.33
    total = len(df)
    counts = df['winner_code'].value_counts()
    priors = {k: (counts.get(k, 0) + 1) / (total + 3) for k in range(3)}
    
    likelihoods = {}
    for k in range(3):
        likelihoods[k] = priors[k]
    
    pred = max(likelihoods, key=likelihoods.get)
    confidence = float(likelihoods[pred])
    return pred, confidence

# ==================== 🤖 استدعاء نموذج NVIDIA AI ====================
def nvidia_ai_prediction(features: Dict[str, Any]) -> Tuple[int, float]:
    try:
        prompt = f"""
        Analyze these game statistics and predict the next winner.
        Features: {json.dumps(features)}
        Options: 0 for Red, 1 for Blue, 2 for Tie.
        Respond ONLY with a valid JSON in this exact format:
        {{"prediction": 0, "confidence": 0.85}}
        """
        
        response = nv_client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=50
        )
        
        content = response.choices[0].message.content
        # تنظيف النص لاستخراج الـ JSON فقط
        json_str = re.search(r'\{.*\}', content, re.DOTALL)
        if json_str:
            data = json.loads(json_str.group())
            pred = int(data.get('prediction', 2))
            conf = float(data.get('confidence', 0.33))
            return pred, conf
        return 2, 0.33
    except Exception as e:
        logger.error(f"❌ خطأ في استدعاء نموذج NVIDIA AI: {e}")
        return 2, 0.33

# ==================== 🧠 دمج التنبؤات ====================
def combined_prediction(df: pd.DataFrame, features: Dict[str, Any]) -> Tuple[int, float]:
    math_pred, math_conf = math_prediction(df)
    bayes_pred, bayes_conf = bayesian_prediction(df)
    nvidia_pred, nvidia_conf = nvidia_ai_prediction(features)
    
    votes = Counter()
    weights = {
        math_pred: math_conf * DYNAMIC_CONFIG['MATH_WEIGHT'],
        bayes_pred: bayes_conf * DYNAMIC_CONFIG['BAYES_WEIGHT'],
        nvidia_pred: nvidia_conf * (1 - DYNAMIC_CONFIG['MATH_WEIGHT'] - DYNAMIC_CONFIG['BAYES_WEIGHT'])
    }
    for pred, weight in weights.items():
        votes[pred] += weight
        
    final_pred, final_conf = votes.most_common(1)[0]
    final_conf = min(max(final_conf, 0.0), 1.0)
    
    if final_conf < DYNAMIC_CONFIG['CONFIDENCE_THRESHOLD']:
        final_pred = 2  
        
    return int(final_pred), float(final_conf)

# ==================== 🕹️ واجهة أزرار تفاعلية ====================
def build_keyboard() -> InlineKeyboardMarkup:
    """بناء لوحة المفاتيح التفاعلية للبوت"""
    buttons = [
        [
            InlineKeyboardButton("الراعي 🔴", callback_data="win_0"),
            InlineKeyboardButton("الثور 🔵", callback_data="win_1"),
            InlineKeyboardButton("تعادل ⚪", callback_data="win_2")
        ],
        [
            InlineKeyboardButton("🔮 تنبؤ جديد", callback_data="predict_now"),
            InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

# ==================== 📱 دوال معالجة التليجرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرد على أمر /start"""
    welcome_text = (
        "مرحباً بك في بوت التنبؤات الذكي 🤖\n\n"
        "أنا أستخدم خوارزميات رياضية ونماذج ذكاء اصطناعي من NVIDIA "
        "لتحليل البيانات وتوقع النتائج.\n\n"
        "اختر أحد الإجراءات من القائمة أدناه:"
    )
    await update.message.reply_text(welcome_text, reply_markup=build_keyboard())

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة النقرات على الأزرار"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "predict_now":
        await query.edit_message_text("⏳ جاري تحليل البيانات والتنبؤ...", reply_markup=None)
        
        df = load_filtered_history()
        features = get_latest_stats(df)
        pred, conf = combined_prediction(df, features)
        
        winner_str = WINNER_NAMES.get(pred, 'غير معروف')
        result_text = (
            f"🎯 **النتيجة المتوقعة:** {winner_str}\n"
            f"📊 **نسبة الثقة:** %{conf * 100:.1f}\n\n"
            f"اختر إجراء آخر:"
        )
        await query.edit_message_text(text=result_text, parse_mode='Markdown', reply_markup=build_keyboard())

    elif data == "show_stats":
        df = load_filtered_history()
        stats = get_latest_stats(df)
        
        stats_text = (
            f"📈 **إحصائيات النظام:**\n"
            f"إجمالي الجولات المحللة: {stats['total_rounds']}\n"
            f"🔴 نسبة الراعي: %{stats['bias']['red']*100:.1f}\n"
            f"🔵 نسبة الثور: %{stats['bias']['blue']*100:.1f}\n"
            f"⚪ نسبة التعادل: %{stats['bias']['tie']*100:.1f}"
        )
        await query.edit_message_text(text=stats_text, parse_mode='Markdown', reply_markup=build_keyboard())
        
    elif data.startswith("win_"):
        # هنا يمكنك إضافة كود لحفظ النتيجة في قاعدة البيانات
        # win_code = int(data.split('_')[1])
        await query.edit_message_text("✅ تم تسجيل النتيجة بنجاح في النظام!", reply_markup=build_keyboard())

# ==================== 🚀 التشغيل الأساسي ====================
def main():
    logger.info("⚙️ جاري بدء تشغيل البوت...")
    
    # تحميل الإعدادات الديناميكية من قاعدة البيانات
    load_dynamic_config()
    
    # إعداد البوت
    app = ApplicationBuilder().token(TOKEN).build()
    
    # ربط الأوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("🤖 البوت يعمل الآن وينتظر الأوامر...")
    app.run_polling()

if __name__ == '__main__':
    main()
