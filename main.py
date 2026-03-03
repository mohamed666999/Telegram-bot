```python
import os, sys, datetime, psycopg2, pandas as pd, numpy as np
import json, re, logging, random, secrets
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

# ✅ المفاتيح - كما طلبت تبقى كما هي
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

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
        return 2, 0.33  # تعادل مع ثقة منخفضة
    
    last_50 = df.tail(50)
    counts = last_50['winner_code'].value_counts(normalize=True)
    pred = counts.idxmax() if not counts.empty else 2
    confidence = counts.max() if not counts.empty else 0.33
    confidence = max(confidence, DYNAMIC_CONFIG['MATH_CONFIDENCE'])
    return pred, confidence

# ==================== 🔍 تحليل بايزي ====================
def bayesian_prediction(df: pd.DataFrame) -> Tuple[int, float]:
    if df.empty:
        return 2, 0.33
    
    total = len(df)
    counts = df['winner_code'].value_counts()
    priors = {k: (counts.get(k, 0) + 1) / (total + 3) for k in range(3)}  # Laplace smoothing
    
    likelihoods = {}
    for k in range(3):
        likelihoods[k] = priors[k]
    
    pred = max(likelihoods, key=likelihoods.get)
    confidence = likelihoods[pred]
    return pred, confidence

# ==================== 🤖 استدعاء نموذج NVIDIA AI ====================
import requests

def nvidia_ai_prediction(features: Dict[str, Any]) -> Tuple[int, float]:
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": NVIDIA_MODEL,
        "inputs": features
    }
    try:
        response = requests.post(f"{NVIDIA_BASE_URL}/models/{NVIDIA_MODEL}/predict", headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        pred = data.get('prediction', 2)
        confidence = data.get('confidence', 0.33)
        if isinstance(pred, str):
            pred = WINNER_MAP.get(pred, 2)
        return pred, confidence
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
        final_pred = 2  # تعادل إذا الثقة منخفضة
    
    return final_pred, final_conf

# ==================== 🕹️ واجهة أزرار تفاعلية ====================
def build_keyboard() -> InlineKeyboardMarkup:
    buttons
