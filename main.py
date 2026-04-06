"""
HADES V19.0 - Neural Hybrid + Deep Learning Memory
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/force_learn : يُحلّل كل الجولات السابقة (+2700) ويستخرج قوانين ذكية
               تُخزَّن في DB وتُستخدم مباشرة في كل تنبؤ.

الذاكرة السياقية:
  - كل جلسة تعلم تبني فوق السابقة (تراكمية)
  - AI يكتشف أنماطاً لم تكن موجودة في الكود يدوياً
  - القوانين لها وزن وثقة، تتلاشى مع الزمن إن ثبت خطؤها
  - البوت يطبّق القوانين آلياً بجانب الأنماط الإحصائية
"""

import itertools
import re
import json
import logging
import math
import html
import random
import asyncio
import time
from typing import Tuple, Dict, Optional, List, Any
from datetime import datetime, timedelta
from collections import OrderedDict, defaultdict
from supabase import create_client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import threading
import aiohttp
from openai import OpenAI
from flask import Flask

# ==================== الإعدادات ====================
TOKEN        = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
SUPABASE_URL = "https://mamjpudfwhmvqdvrqojb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1hbWpwdWRmd2htdnFkdnJxb2piIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUyMTAwNjMsImV4cCI6MjA5MDc4NjA2M30.Y6tajMxbkCgcOx8tQIowg6LjxfjaRrnBAO9DwqZCVLI"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_ID     = 6033203084

AI_INVOKE_URL  = "https://integrate.api.nvidia.com/v1"
AI_API_KEY     = "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"
AI_MODEL       = "meta/llama-3.1-405b-instruct"   # ✅ أقوى نموذج — Llama 405B
AI_MODEL_SMALL = "meta/llama-3.1-8b-instruct"
AI_TIMEOUT    = 12.0
LEARN_TIMEOUT = 1800  # ✅ 30 دقيقة مهلة للتعلم العميق

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== خرائط ثابتة ====================
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0,
    'الثور 🔵':  1, 'ثور':  1,
    'تعادل ⚪':  2, 'تعادل': 2,
    '🔴': 0, '🔵': 1, '⚪': 2,
    0: 0, 1: 1, 2: 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS        = ['♦️', '♥️', '♠️', '♣️']
RANKS_LAYOUT = [
    ["A", "K", "Q", "J"],
    ["10", "9", "8", "7"],
    ["6", "5", "4", "3", "2"],
]
RANK_VALUE = {k: v for k, v in zip(
    ["A","K","Q","J","10","9","8","7","6","5","4","3","2"],
    [14, 13, 12, 11, 10,  9,  8,  7,  6,  5,  4,  3,  2]
)}
WEIGHTS = {
    'SD': 3.5, 'SUIT': 1.5, 'DIGIT': 0.8,  # ✅ تقليل DIGIT لكسر انحياز الأزرق
    'RANK': 1.0,   # ✅ تقليل RANK لمنع الانحياز
    'MOMENTUM': 3.2,  # ✅ رفع الزخم لاكتشاف التحولات
    'AI': 2.5,
    'LAW': 4.0,    # ✅ رفع وزن القوانين بعد تنظيفها
}
# ════════════════════════════════════════════════════════════════════
# 📊 قوانين مستخلصة من تحليل 1780 جولة حقيقية (v19)
# ════════════════════════════════════════════════════════════════════
DATA_LAWS: List[Dict] = [
    {"id": -1, "law_type": "data_gap_micro", "conditions": {"b_gap_gte": 100, "b_gap_lt": 500},
     "prediction": 0, "confidence": 62, "accuracy": 60.0, "times_used": 122,
     "description": "فجوة 100-500 → الراعي 🔴 (تحليل حقيقي)", "active": True},
    {"id": -2, "law_type": "data_gap_nano", "conditions": {"b_gap_lt": 100},
     "prediction": 1, "confidence": 60, "accuracy": 60.0, "times_used": 35,
     "description": "فجوة 0-100 → الثور 🔵 (تحليل حقيقي)", "active": True},
    {"id": -3, "law_type": "data_after_4x_red", "conditions": {"streak": {"length": 4, "value": 0}},
     "prediction": 1, "confidence": 64, "accuracy": 64.0, "times_used": 34,
     "description": "بعد 4 رواعٍ متتالية → الثور 🔵 (bias=0.29)", "active": True},
    {"id": -4, "law_type": "data_cycle8_pos1", "conditions": {"cycle_position": {"cycle": 8, "position": 1}},
     "prediction": 0, "confidence": 56, "accuracy": 55.5, "times_used": 223,
     "description": "دورة 8 موضع 1 → الراعي 🔴", "active": True},
    {"id": -5, "law_type": "data_cycle8_pos5", "conditions": {"cycle_position": {"cycle": 8, "position": 5}},
     "prediction": 1, "confidence": 56, "accuracy": 56.0, "times_used": 222,
     "description": "دورة 8 موضع 5 → الثور 🔵", "active": True},
    {"id": -6, "law_type": "data_digsum_mod9_r6", "conditions": {"digit_sum_mod": {"mod": 9, "remainder": 6}},
     "prediction": 0, "confidence": 56, "accuracy": 55.3, "times_used": 206,
     "description": "مجموع الأرقام mod9=6 → الراعي 🔴", "active": True},
    {"id": -7, "law_type": "data_digsum_mod7_r1", "conditions": {"digit_sum_mod": {"mod": 7, "remainder": 1}},
     "prediction": 1, "confidence": 55, "accuracy": 55.0, "times_used": 241,
     "description": "مجموع الأرقام mod7=1 → الثور 🔵", "active": True},
    {"id": -8, "law_type": "data_after_4x_blue", "conditions": {"streak": {"length": 4, "value": 1}},
     "prediction": 0, "confidence": 58, "accuracy": 58.5, "times_used": 41,
     "description": "بعد 4 ثيران متتالية → الراعي 🔴 (bias=0.17)", "active": True},
]
DATA_LAW_WEIGHT = 2.2

# ==================== 📦 بيانات الأنماط المدمجة ====================
EMBEDDED_PATTERNS: Dict[str, Dict] = {
    "SUIT_♦️": {"r": 315, "b": 347, "t": 27},
    "SUIT_♣️": {"r": 206, "b": 194, "t": 15},
    "SUIT_♥️": {"r": 190, "b": 194, "t": 11},
    "SUIT_♠️": {"r": 202, "b": 168, "t": 13},
    "DIGIT_0": {"r":  85, "b": 101, "t": 4},
    "DIGIT_1": {"r":  88, "b":  87, "t": 9},
    "DIGIT_2": {"r":  87, "b":  76, "t": 7},
    "DIGIT_3": {"r":  86, "b":  91, "t": 7},
    "DIGIT_4": {"r":  94, "b":  66, "t": 9},
    "DIGIT_5": {"r":  91, "b":  94, "t": 8},
    "DIGIT_6": {"r":  92, "b":  97, "t": 6},
    "DIGIT_7": {"r":  90, "b": 104, "t": 5},
    "DIGIT_8": {"r":  92, "b":  89, "t": 7},
    "DIGIT_9": {"r": 108, "b":  98, "t": 4},
    "RANK_A":  {"r": 19, "b": 16, "t": 4},
    "RANK_2":  {"r": 23, "b": 23, "t": 3},
    "RANK_3":  {"r": 17, "b": 24, "t": 0},
    "RANK_4":  {"r": 21, "b": 24, "t": 1},
    "RANK_5":  {"r": 23, "b": 28, "t": 0},
    "RANK_6":  {"r": 22, "b": 15, "t": 2},
    "RANK_7":  {"r": 24, "b": 20, "t": 4},
    "RANK_8":  {"r": 23, "b": 19, "t": 1},
    "RANK_9":  {"r": 26, "b": 18, "t": 5},
    "RANK_10": {"r": 16, "b": 20, "t": 2},
    "RANK_J":  {"r": 21, "b": 13, "t": 0},
    "RANK_Q":  {"r": 19, "b": 23, "t": 2},
    "RANK_K":  {"r": 19, "b": 14, "t": 1},
    "SD_♦️_0": {"r": 30, "b": 42, "t": 2},
    "SD_♦️_1": {"r": 25, "b": 30, "t": 4},
    "SD_♦️_2": {"r": 30, "b": 30, "t": 2},
    "SD_♦️_3": {"r": 30, "b": 31, "t": 3},
    "SD_♦️_4": {"r": 35, "b": 26, "t": 4},
    "SD_♦️_5": {"r": 34, "b": 43, "t": 4},
    "SD_♦️_6": {"r": 27, "b": 39, "t": 3},
    "SD_♦️_7": {"r": 32, "b": 35, "t": 1},
    "SD_♦️_8": {"r": 34, "b": 32, "t": 3},
    "SD_♦️_9": {"r": 38, "b": 39, "t": 1},
    "SD_♥️_0": {"r": 21, "b": 25, "t": 0},
    "SD_♥️_1": {"r": 24, "b": 18, "t": 3},
    "SD_♥️_2": {"r": 15, "b": 14, "t": 2},
    "SD_♥️_3": {"r": 21, "b": 20, "t": 1},
    "SD_♥️_4": {"r": 17, "b": 20, "t": 0},
    "SD_♥️_5": {"r": 17, "b": 20, "t": 1},
    "SD_♥️_6": {"r": 21, "b": 17, "t": 1},
    "SD_♥️_7": {"r": 15, "b": 25, "t": 0},
    "SD_♥️_8": {"r": 17, "b": 19, "t": 1},
    "SD_♥️_9": {"r": 22, "b": 18, "t": 2},
    "SD_♠️_0": {"r": 12, "b": 18, "t": 1},
    "SD_♠️_1": {"r": 16, "b": 19, "t": 1},
    "SD_♠️_2": {"r": 23, "b": 13, "t": 1},
    "SD_♠️_3": {"r": 17, "b": 16, "t": 2},
    "SD_♠️_4": {"r": 19, "b":  6, "t": 2},
    "SD_♠️_5": {"r": 22, "b": 21, "t": 1},
    "SD_♠️_6": {"r": 21, "b": 19, "t": 1},
    "SD_♠️_7": {"r": 23, "b": 23, "t": 2},
    "SD_♠️_8": {"r": 25, "b": 13, "t": 2},
    "SD_♠️_9": {"r": 24, "b": 21, "t": 0},
    "SD_♣️_0": {"r": 22, "b": 16, "t": 1},
    "SD_♣️_1": {"r": 23, "b": 20, "t": 1},
    "SD_♣️_2": {"r": 19, "b": 19, "t": 2},
    "SD_♣️_3": {"r": 18, "b": 24, "t": 1},
    "SD_♣️_4": {"r": 23, "b": 15, "t": 3},
    "SD_♣️_5": {"r": 18, "b": 11, "t": 2},
    "SD_♣️_6": {"r": 23, "b": 22, "t": 2},
    "SD_♣️_7": {"r": 20, "b": 21, "t": 2},
    "SD_♣️_8": {"r": 16, "b": 27, "t": 1},
    "SD_♣️_9": {"r": 24, "b": 20, "t": 1},
}

# ==================== TTL Cache ====================
class TTLCache:
    def __init__(self, ttl_seconds=60):
        self.cache = OrderedDict()
        self.ttl   = ttl_seconds

    def get(self, key):
        if key in self.cache:
            value, ts = self.cache[key]
            if time.time() - ts < self.ttl:
                return value
            del self.cache[key]
        return None

    def set(self, key, value):
        self.cache[key] = (value, time.time())
        if len(self.cache) > 500:
            self.cache.popitem(last=False)

live_cache = TTLCache(ttl_seconds=30)

# ==================== Database Connection Pool ====================
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

# رابط قاعدة بياناتك مع كلمة المرور
SUPABASE_DB_URL = "postgresql://postgres.mamjpudfwhmvqdvrqojb:Loploplop909090.@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"

class DatabasePool:
    _instance = None
    _pool     = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_pool()
        return cls._instance

    def _init_pool(self):
        try:
            self._pool = psycopg2.pool.ThreadedConnectionPool(1, 20, SUPABASE_DB_URL)
            logger.info("✅ تم الاتصال بقاعدة بيانات Supabase بنجاح!")
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بقاعدة بيانات Supabase: {e}")

    @contextmanager
    def get_conn(self):
        if self._pool is None:
            self._init_pool()
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

db_pool = DatabasePool()


# ==================== 🧠 الذاكرة السياقية ====================
_laws_cache: List[Dict] = []
_laws_loaded_at: float  = 0.0

def load_laws(force: bool = False) -> List[Dict]:
    global _laws_cache, _laws_loaded_at
    if not force and time.time() - _laws_loaded_at < 300:
        return _laws_cache
    try:
        proven_r = supabase.table("ai_laws").select(
            "id,law_type,conditions,prediction,confidence,accuracy,times_used,description,created_at"
        ).eq("active", True).gte("times_used", 5).gte("accuracy", 55).order(
            "accuracy", desc=True).limit(10).execute()
        proven = [(r["id"],r["law_type"],r["conditions"],r["prediction"],
                   r["confidence"],r["accuracy"],r["times_used"],r["description"],r["created_at"])
                  for r in proven_r.data]

        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(hours=48)).isoformat()
        prob_r = supabase.table("ai_laws").select(
            "id,law_type,conditions,prediction,confidence,accuracy,times_used,description,created_at"
        ).eq("active", True).lt("times_used", 5).gte("created_at", cutoff).order(
            "confidence", desc=True).limit(6).execute()
        probation = [(r["id"],r["law_type"],r["conditions"],r["prediction"],
                      r["confidence"],r["accuracy"],r["times_used"],r["description"],r["created_at"])
                     for r in prob_r.data]

        def _is_aliasing_law(cond_raw) -> bool:
            try:
                c = cond_raw if isinstance(cond_raw, dict) else json.loads(cond_raw or "{}")
                ts_m = c.get("ts_mod", {})
                return bool(ts_m) and int(ts_m.get("mod", 0)) in (11, 13, 16, 17)
            except Exception:
                return False

        laws = []
        for row in proven:
            if _is_aliasing_law(row[2]):
                continue
            laws.append({
                "id":          row[0],
                "law_type":    row[1],
                "conditions":  row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}"),
                "prediction":  row[3],
                "confidence":  float(row[4]),
                "accuracy":    float(row[5]),
                "times_used":  int(row[6]),
                "description": row[7],
                "created_at":  row[8],
                "tier":        "proven",
            })

        for row in probation:
            if _is_aliasing_law(row[2]):
                continue
            laws.append({
                "id":          row[0],
                "law_type":    row[1],
                "conditions":  row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}"),
                "prediction":  row[3],
                "confidence":  float(row[4]),
                "accuracy":    50.0,
                "times_used":  int(row[6]),
                "description": row[7],
                "created_at":  row[8],
                "tier":        "probation",
            })

        _laws_cache     = laws
        _laws_loaded_at = time.time()
        n_proven    = sum(1 for l in laws if l.get('tier') == 'proven')
        n_probation = sum(1 for l in laws if l.get('tier') == 'probation')
        logger.info(f"✅ Laws loaded: {n_proven} proven + {n_probation} probation")

        try:
            from datetime import timedelta
            cutoff48 = (datetime.utcnow() - timedelta(hours=48)).isoformat()
            supabase.table("ai_laws").update({"active": False}).eq("active", True).eq("times_used", 0).lt("created_at", cutoff48).execute()
            supabase.table("ai_laws").update({"active": False}).eq("active", True).gte("times_used", 5).lt("accuracy", 40).execute()
        except Exception as _e:
            logger.debug(f"load_laws cleanup: {_e}")

        return laws
    except Exception as e:
        logger.error(f"load_laws error: {e}")
        return _laws_cache

def match_law(law: Dict, suit: str, rank: str, last_digit: int,
              recent: List[int], b_num: str = "", b_gap: Optional[float] = None,
              gap_sec: Optional[float] = None, round_index: int = 0) -> float:
    cond  = law.get("conditions", {})
    score = 0.0
    total = 0

    def chk(condition: bool):
        nonlocal score, total
        total += 1
        if condition:
            score += 1

    if "suit"      in cond: chk(suit == cond["suit"])
    if "suits_in"  in cond: chk(suit in cond["suits_in"])
    if "digit"     in cond: chk(str(last_digit) == str(cond["digit"]))
    if "digits_in" in cond: chk(str(last_digit) in [str(d) for d in cond["digits_in"]])
    if "rank"      in cond: chk(rank == cond["rank"])
    if "digit_parity" in cond:
        chk(("even" if last_digit % 2 == 0 else "odd") == cond["digit_parity"])
    if "rank_family" in cond:
        families = {"face": ["J","Q","K"], "low": ["2","3","4","5"],
                    "high": ["9","10","A"], "middle": ["6","7","8"]}
        chk(rank in families.get(cond["rank_family"], []))

    if "streak" in cond:
        slen = cond["streak"]["length"]
        if len(recent) >= slen:
            chk(recent[-slen:] == [cond["streak"]["value"]] * slen)
    if "after_pattern" in cond:
        pat = cond["after_pattern"]
        if len(recent) >= len(pat):
            chk(recent[-len(pat):] == pat)

    if b_num and "digit_sum_mod" in cond:
        c    = cond["digit_sum_mod"]
        dsum = sum(int(d) for d in b_num if d.isdigit())
        chk(dsum % int(c["mod"]) == int(c["remainder"]))
    if b_num and "rank_value_mod" in cond:
        c  = cond["rank_value_mod"]
        rv = RANK_VALUE.get(rank.upper(), 0)
        chk(rv % int(c["mod"]) == int(c["remainder"]))
    if b_num and "digit_plus_rank_mod" in cond:
        c    = cond["digit_plus_rank_mod"]
        rv   = RANK_VALUE.get(rank.upper(), 0)
        dsum = sum(int(d) for d in b_num if d.isdigit())
        chk((dsum + rv) % int(c["mod"]) == int(c["remainder"]))

    if "cycle_position" in cond and round_index > 0:
        c = cond["cycle_position"]
        chk(round_index % int(c["cycle"]) == int(c["position"]))

    if b_gap is not None:
        if "b_gap_gt"      in cond: chk(b_gap > float(cond["b_gap_gt"]))
        if "b_gap_lt"      in cond: chk(b_gap < float(cond["b_gap_lt"]))
        if "b_gap_gte"     in cond: chk(b_gap >= float(cond["b_gap_gte"]))
        if "b_gap_lte"     in cond: chk(b_gap <= float(cond["b_gap_lte"]))
        if "after_big_gap" in cond: chk(b_gap > 2000)

    if gap_sec is not None:
        if "gap_sec_lt" in cond: chk(gap_sec < float(cond["gap_sec_lt"]))
        if "gap_sec_gt" in cond: chk(gap_sec > float(cond["gap_sec_gt"]))

    if "ts_mod" in cond:
        c = cond["ts_mod"]
        try:
            ts_val = int(time.time()) if round_index == 0 else round_index
            chk(ts_val % int(c["mod"]) == int(c["remainder"]))
        except Exception:
            pass

    if total == 0:
        return 0.5
    return score / total

MAX_LAW_CONTRIBUTION = 0.35  # حد أقصى لمساهمة قانون واحد (35% من total)
MIN_EDGE_THRESHOLD   = 0.55  # حد الثقة الأدنى للتنبؤ — تحته نتجاهل الجولة

def should_predict(score_0: float, score_1: float) -> bool:
    """Decision Gate: لا تتنبأ إذا كانت الإشارة ضعيفة (< 55% ثقة)."""
    total = score_0 + score_1
    if total == 0:
        return False
    edge = max(score_0, score_1) / total
    return edge >= MIN_EDGE_THRESHOLD

def classify_law(law: dict) -> str:
    """SEQUENTIAL = يعتمد على streak/cycle/gap | ABSOLUTE = مستقل."""
    conditions = str(law.get("conditions", {})).lower()
    if any(k in conditions for k in ["streak", "cycle", "gap"]):
        return "SEQUENTIAL"
    return "ABSOLUTE"


def apply_laws(suit: str, rank: str, last_digit: int,
               recent: List[int], b_num: str = "",
               b_gap: Optional[float] = None, gap_sec: Optional[float] = None,
               round_index: int = 0) -> Tuple[Dict[int, float], List[str]]:
    laws   = load_laws()
    scores = {0: 0.0, 1: 0.0}
    logs   = []

    # ── تصفية القوانين المتكررة بنفس الشروط (Correlation Prevention) ──
    seen_conditions = set()
    filtered_laws = []
    for law in (laws + list(DATA_LAWS)):
        key = str(law.get("conditions", {}))
        if key not in seen_conditions:
            seen_conditions.add(key)
            filtered_laws.append(law)

    # ── تطبيق القوانين مع seq_weight ──────────────────────────────────
    seq_w = seq_weight_from_gap(gap_sec)
    for law in filtered_laws:
        match = match_law(law, suit, rank, last_digit, recent,
                          b_num=b_num, b_gap=b_gap,
                          gap_sec=gap_sec, round_index=round_index)
        if match < 0.7:
            continue

        pred = law.get("prediction")
        if pred not in [0, 1]:
            continue
        if "conditions" not in law:
            continue

        used = law.get("times_used", 0)

        # تجاهل القوانين ذات العينة الصغيرة جداً (ضوضاء مؤكدة)
        if used < 15 and law.get('id', 0) > 0:
            continue

        acc_raw = law.get("accuracy", 50.0) / 100.0

        # معادلة Bayesian Logarithmic Score: Accuracy × log10(Used + 10)
        # تكافئ القوانين ذات الاستخدام العالي وتخسف بالوهم الإحصائي
        bayesian_score = acc_raw * math.log10(used + 10)

        law_weight = WEIGHTS['LAW'] * bayesian_score
        # القوانين التسلسلية تتأثر بانقطاع الجلسة
        if classify_law(law) == "SEQUENTIAL":
            law_weight *= seq_w
        conf_factor = law.get("confidence", 50.0) / 100.0
        weight = conf_factor * law_weight * match
        # منع سيطرة قانون واحد
        contribution = min(weight, (scores[0] + scores[1] + 0.01) * MAX_LAW_CONTRIBUTION)
        scores[pred] += contribution

        if match >= 0.8:
            tier_label = " 🔬" if law.get('tier') == 'probation' else ""
            logs.append(
                f"⚖️ قانون #{law['id']} ({law['law_type']}){tier_label}: "
                f"{WINNER_NAMES[pred]} — {law['description'][:60]}"
            )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.run_in_executor(None, _increment_law_usage, law["id"])
        except Exception:
            pass

    max_law_score = WEIGHTS['LAW'] * 3
    scores[0] = min(scores[0], max_law_score)
    scores[1] = min(scores[1], max_law_score)

    return scores, logs

def _increment_law_usage(law_id: int):
    try:
        # fetch current then increment
        r = supabase.table("ai_laws").select("times_used").eq("id", law_id).single().execute()
        if r.data:
            supabase.table("ai_laws").update({"times_used": r.data["times_used"] + 1}).eq("id", law_id).execute()
    except Exception:
        pass

def update_law_accuracy(law_id: int, correct: bool):
    try:
        new_val = 100.0 if correct else 0.0
        r = supabase.table("ai_laws").select("accuracy,accuracy_recent").eq("id", law_id).single().execute()
        if r.data:
            acc = float(r.data.get("accuracy") or 70)
            acc_r = float(r.data.get("accuracy_recent") or acc)
            new_acc = acc * 0.95 + new_val * 0.05
            new_acc_r = acc_r * 0.85 + new_val * 0.15
            supabase.table("ai_laws").update({
                "accuracy": round(new_acc, 2),
                "accuracy_recent": round(new_acc_r, 2),
                "active": new_acc >= 30
            }).eq("id", law_id).execute()
    except Exception as e:
        logger.error(f"update_law_accuracy error: {e}")

# ==================== DB Tables ====================
def ensure_tables():
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id               SERIAL PRIMARY KEY,
                        b_num            TEXT,
                        suit             TEXT,
                        hand             TEXT,
                        winner           TEXT,
                        timestamp        TIMESTAMP,
                        prediction       TEXT,
                        user_id          BIGINT,
                        final_prediction TEXT,
                        gap_pred         TEXT,
                        math_pred        TEXT,
                        file_pred        TEXT,
                        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        rank             TEXT,
                        bonus_last_digit INT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pattern_stats (
                        pattern_id   VARCHAR(60) PRIMARY KEY,
                        pattern_type VARCHAR(20),
                        red_count    FLOAT DEFAULT 0,
                        blue_count   FLOAT DEFAULT 0,
                        tie_count    FLOAT DEFAULT 0
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ai_laws (
                        id         SERIAL PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                migrate_cols = [
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS law_type    VARCHAR(50)",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS conditions  JSONB",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS prediction  INT",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS confidence  FLOAT DEFAULT 70",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS accuracy    FLOAT DEFAULT 70",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS accuracy_recent FLOAT DEFAULT NULL",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS times_used  INT DEFAULT 0",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS description TEXT",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS source      TEXT DEFAULT 'force_learn'",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS active      BOOLEAN DEFAULT TRUE",
                ]
                for sql in migrate_cols:
                    cur.execute(sql)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS learn_sessions (
                        id           SERIAL PRIMARY KEY,
                        rounds_used  INT,
                        laws_created INT,
                        laws_updated INT,
                        summary      TEXT,
                        context      TEXT,
                        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS signal_performance (
                        signal_name   VARCHAR(50) PRIMARY KEY,
                        correct_count FLOAT DEFAULT 0,
                        total_count   FLOAT DEFAULT 0,
                        updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # جدول مفاتيح API مع صلاحية
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        service     VARCHAR(20) PRIMARY KEY,
                        api_key     TEXT NOT NULL,
                        expiry      TIMESTAMP,
                        set_by      BIGINT,
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # جدول اشتراكات المستخدمين
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        user_id     BIGINT PRIMARY KEY,
                        username    TEXT,
                        plan        VARCHAR(20),
                        expiry      TIMESTAMP,
                        granted_by  BIGINT,
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        logger.info("✅ Tables ensured")
    except Exception as e:
        logger.error(f"DB init error: {e}")

# ==================== دوال مساعدة ====================
def clean_digits(text: str) -> str:
    return re.sub(r"\D", "", str(text))

def get_last_digit(b: str) -> int:
    c = clean_digits(b)
    return int(c[-1]) if c else 0

def generate_bar(pct: int, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)

# ==================== محرك الأنماط ====================
def _score_pattern(raw: Dict, pattern_id: str = "") -> Dict:
    r, b, t = raw.get("r", 0), raw.get("b", 0), raw.get("t", 0)
    total = r + b + t
    if total == 0:
        return {"w": 2, "c": 0.0, "log": "[No Data]", "tie_ratio": 0.0}
    if pattern_id.startswith("EXACT_") and total < 15:
        return {"w": 2, "c": 0.0, "log": f"[Noise:{total}<15]", "tie_ratio": 0.0}
    if pattern_id.startswith("SD_") and total < 10:
        return {"w": 2, "c": 0.0, "log": f"[Noise:{total}<10]", "tie_ratio": 0.0}
    if total < 5:
        return {"w": 2, "c": 0.0, "log": f"[Noise:{total}<5]", "tie_ratio": 0.0}
    sr = r + 2; sb = b + 2; st = t + 1
    sm = sr + sb + st
    p_r = sr / sm; p_b = sb / sm
    winner     = 0 if p_r > p_b else 1
    conf_raw   = max(p_r, p_b)
    conf_scale = min(1.0, total / 10.0)
    tie_ratio  = t / total
    confidence = conf_raw * conf_scale * (1 - tie_ratio * 0.5)
    return {"w": winner, "c": confidence,
            "log": f"[{int(r)}🔴:{int(b)}🔵:{int(t)}⚪]", "tie_ratio": tie_ratio}

def get_pattern(pattern_id: str) -> Dict:
    cached = live_cache.get(pattern_id)
    if cached:
        return cached
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT red_count, blue_count, tie_count FROM pattern_stats WHERE pattern_id = %s",
                    (pattern_id,)
                )
                row = cur.fetchone()
                if row:
                    result = _score_pattern({"r": row[0], "b": row[1], "t": row[2]}, pattern_id)
                    live_cache.set(pattern_id, result)
                    return result
    except Exception as e:
        logger.warning(f"DB pattern fetch ({pattern_id}): {e}")
    raw = EMBEDDED_PATTERNS.get(pattern_id)
    if raw:
        result = _score_pattern(raw, pattern_id)
        live_cache.set(pattern_id, result)
        return result
    return {"w": 2, "c": 0.0, "log": "[No Data]", "tie_ratio": 0.0}

def update_pattern_db(suit: str, rank: str, last_digit: int, winner: int):
    col = {0: "red_count", 1: "blue_count", 2: "tie_count"}.get(winner)
    if col is None:
        return
    items = [
        (f"SUIT_{suit}", "SUIT"),
        (f"DIGIT_{last_digit}", "DIGIT"),
        (f"RANK_{rank}", "RANK"),
        (f"SD_{suit}_{last_digit}", "SD"),
    ]
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                for pid, ptype in items:
                    cur.execute("""
                        INSERT INTO pattern_stats (pattern_id, pattern_type, red_count, blue_count, tie_count)
                        VALUES (%s, %s, 0, 0, 0) ON CONFLICT (pattern_id) DO NOTHING
                    """, (pid, ptype))
                    cur.execute(f"UPDATE pattern_stats SET {col} = {col} + 1 WHERE pattern_id = %s", (pid,))
                    live_cache.cache.pop(pid, None)
                conn.commit()
    except Exception as e:
        logger.error(f"Pattern update error: {e}")

# ==================== 🤖 AI Client ====================
async def _nvidia_chat_single(messages: list, model: str, max_tokens: int,
                               temperature: float, enable_thinking: bool,
                               timeout: int) -> str:
    loop = asyncio.get_event_loop()

    def _sync_call():
        import httpx
        client = OpenAI(
            base_url=AI_INVOKE_URL,
            api_key=AI_API_KEY,
            timeout=1200.0,
            http_client=httpx.Client(
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                timeout=1200.0,
            ),
        )
        extra = {}
        if "deepseek" in model.lower() and enable_thinking:
            extra["extra_body"] = {"chat_template_kwargs": {"thinking": True}}

        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=0.95,
            max_tokens=max_tokens,
            stream=True,
            **extra,
        )
        result = ""
        for chunk in completion:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                continue
            if delta.content:
                result += delta.content
        return result

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_call),
            timeout=float(timeout)
        )
    except asyncio.TimeoutError:
        raise
    except Exception as e:
        raise RuntimeError(f"OpenAI client error: {e}")

    logger.info(f"_nvidia_chat_single done: model={model} len={len(result)}")
    if not result:
        raise RuntimeError("استجابة فارغة")
    return result

async def _nvidia_chat(messages: list, max_tokens: int = 512,
                       temperature: float = 0.6, enable_thinking: bool = False,
                       timeout: int = 60) -> str:
    attempts = [
        (AI_MODEL,       max_tokens,           timeout),
        (AI_MODEL,       max(800, max_tokens//2), min(timeout, 120)),
        (AI_MODEL_SMALL, max(600, max_tokens//3), 90),
    ]
    last_err = None
    for i, (model, tok, tout) in enumerate(attempts):
        try:
            if i > 0:
                wait = 5 * i
                logger.info(f"_nvidia_chat retry {i+1}/3 — model={model} tokens={tok} (wait {wait}s)")
                await asyncio.sleep(wait)
            result = await _nvidia_chat_single(messages, model, tok, temperature,
                                               enable_thinking, tout)
            logger.info(f"_nvidia_chat success on attempt {i+1} — len={len(result)}")
            return result
        except RuntimeError as e:
            last_err = e
            err_str = str(e)
            if "504" in err_str or "500" in err_str or "timeout" in err_str.lower():
                logger.warning(f"_nvidia_chat attempt {i+1} failed: {err_str[:100]}")
                continue
            raise
        except asyncio.TimeoutError:
            last_err = RuntimeError("timeout")
            logger.warning(f"_nvidia_chat attempt {i+1} timeout")
            continue
    raise RuntimeError(f"فشل كل المحاولات: {last_err}")

def _scan_json_objects(text: str) -> List[Dict]:
    results = []
    i = 0
    while i < len(text):
        if text[i] != '{':
            i += 1
            continue
        depth = 0
        start = i
        in_str = False
        escape = False
        for j in range(i, len(text)):
            c = text[j]
            if escape:
                escape = False
                continue
            if c == '\\' and in_str:
                escape = True
                continue
            if c == '"' and not escape:
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:j+1])
                        if isinstance(obj, dict) and 'law_type' in obj and 'prediction' in obj:
                            results.append(obj)
                    except Exception:
                        pass
                    i = j
                    break
        i += 1
    return results

def extract_json_safe(text: str) -> Optional[Any]:
    if not text:
        return None
    text = re.sub(r'(?s)^\s*<think>.*?</think>\s*', '', text).strip()
    text = re.sub(r'(?s)\s*<think>.*?</think>\s*$', '', text).strip()
    cleaned = re.sub(r'```(?:json)?\s*', '', text).replace('```', '').strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, (list, dict)):
            return result
    except Exception:
        pass
    for src in [cleaned, text]:
        bracket_start = src.find('[')
        if bracket_start == -1:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(bracket_start, len(src)):
            c = src[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_str:
                escape = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    try:
                        r = json.loads(src[bracket_start:i+1])
                        if isinstance(r, list) and r:
                            return r
                    except Exception:
                        pass
                    break
    objects = _scan_json_objects(cleaned)
    if objects:
        return objects
    try:
        fixed = re.sub(r',\s*([}\]])', r'\1', cleaned)
        result = json.loads(fixed)
        if isinstance(result, (list, dict)):
            return result
    except Exception:
        pass
    brace_start = cleaned.find('{')
    if brace_start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(brace_start, len(cleaned)):
            c = cleaned[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_str:
                escape = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[brace_start:i+1])
                    except Exception:
                        break
    return None

# ==================== 🧬 /force_learn: التعلم الرياضي العميق ====================
SESSION_CONNECTED_SEC  = 45
SESSION_SOFT_BREAK_SEC = 180
SEQ_WEIGHT_CONNECTED   = 1.0
SEQ_WEIGHT_SOFT        = 0.3
SEQ_WEIGHT_HARD        = 0.0

def gap_classify(gap_sec: Optional[float]) -> str:
    if gap_sec is None:
        return 'hard_break'
    if gap_sec <= SESSION_CONNECTED_SEC:
        return 'connected'
    if gap_sec <= SESSION_SOFT_BREAK_SEC:
        return 'soft_break'
    return 'hard_break'

def seq_weight_from_gap(gap_sec: Optional[float], b_gap: Optional[float] = None) -> float:
    """يحسب وزن محركات التسلسل — يدمج الفجوة الزمنية والرقمية."""
    cls = gap_classify(gap_sec)
    base = {'connected': SEQ_WEIGHT_CONNECTED, 'soft_break': SEQ_WEIGHT_SOFT, 'hard_break': SEQ_WEIGHT_HARD}[cls]
    if b_gap is not None and base > 0:
        import math
        c = math.exp(-b_gap / 3000.0)
        base = base * c
    return max(0.0, base)

def _filter_valid_rounds(rows) -> List[Dict]:
    valid = []
    rows_list = list(rows)
    # ✅ استثناء أول 700 جولة (تطهير التعادلات والانحياز المبكر)
    working = rows_list[700:] if len(rows_list) > 700 else rows_list
    logger.info(f"_filter_valid_rounds: total={len(rows_list)}, after_skip700={len(working)}")
    for i, row in enumerate(working):
        # Supabase returns dicts — support both dict and tuple
        if isinstance(row, dict):
            b_num   = clean_digits(str(row.get("b_num") or ""))
            suit    = row.get("suit") or ""
            rank    = row.get("rank") or ""
            _dig    = row.get("bonus_last_digit")
            digit   = int(_dig) if _dig is not None else -1
            winner  = WINNER_MAP.get(row.get("winner"), 2)
            ts      = row.get("created_at")
        else:
            b_num   = clean_digits(str(row[1] or ""))
            suit    = row[2] or ""
            rank    = row[3] or ""
            digit   = int(row[4]) if row[4] is not None else -1
            winner  = WINNER_MAP.get(row[5], 2)
            ts      = row[6]
        if winner == 2 or not b_num or not suit:
            continue
        gap_sec = None
        prev = working[i-1] if i > 0 else None
        if prev is not None:
            prev_ts = prev.get("created_at") if isinstance(prev, dict) else prev[6]
            if prev_ts and ts:
                gap_sec = abs((ts - prev_ts).total_seconds())
        b_gap = None
        if prev is not None:
            prev_b_raw = prev.get("b_num") if isinstance(prev, dict) else prev[1]
            prev_b = clean_digits(str(prev_b_raw or ""))
            if b_num and prev_b:
                try:
                    b_gap = abs(int(b_num) - int(prev_b))
                except Exception:
                    pass
        valid.append({
            "idx": i, "b_num": b_num, "suit": suit, "rank": rank, "digit": digit,
            "winner": winner, "ts": ts, "gap_sec": gap_sec, "b_gap": b_gap,
            "connected": gap_sec is not None and gap_sec <= SESSION_CONNECTED_SEC,
        })
    return valid

def _run_law_on_rows(law_dict: Dict, rows: List) -> Tuple[int, int]:
    pred = law_dict.get("prediction")
    correct = 0
    total = 0
    for row in rows:
        b_num_r   = str(row[1] or "")
        suit_r    = str(row[2] or "")
        rank_r    = str(row[3] or "")
        digit_r   = int(row[4]) if row[4] is not None else 0
        winner_r  = WINNER_MAP.get(row[5], 2)
        created_r = row[6]
        b_gap_r   = row[7]
        gap_sec_r = float(row[8]) if row[8] is not None else None
        if winner_r not in [0, 1]:
            continue
        clean_b   = clean_digits(b_num_r)
        unix_ts_r = int(created_r.timestamp()) if created_r else int(time.time())
        match = match_law(law_dict, suit_r, rank_r, digit_r,
                          recent=[], b_num=clean_b,
                          b_gap=b_gap_r, gap_sec=gap_sec_r,
                          round_index=unix_ts_r)
        if match < 0.7:
            continue
        total += 1
        if winner_r == pred:
            correct += 1
    return correct, total

def backtest_law(law_dict: Dict, backtest_rows: List) -> Tuple[bool, float, int]:
    MIN_TOTAL_SAMPLE = 12
    MIN_TOTAL_ACC    = 0.52

    pred = law_dict.get("prediction")
    if pred not in [0, 1]:
        return False, 0.0, 0

    c_total, t_total = _run_law_on_rows(law_dict, backtest_rows)

    if t_total < MIN_TOTAL_SAMPLE:
        return False, 0.0, t_total

    acc_total = c_total / t_total
    if acc_total < MIN_TOTAL_ACC:
        return False, acc_total, t_total

    mid      = len(backtest_rows) // 2
    rows_new = backtest_rows[:mid]
    rows_old = backtest_rows[mid:]

    c_new, t_new = _run_law_on_rows(law_dict, rows_new)
    c_old, t_old = _run_law_on_rows(law_dict, rows_old)

    acc_new = (c_new / t_new) if t_new > 0 else 0.0
    acc_old = (c_old / t_old) if t_old > 0 else 0.0

    if t_new >= 6 and acc_new < 0.50:
        logger.info(
            f"Backtest REJECT (drifted): {law_dict.get('law_type')} "
            f"total={acc_total:.0%} new={acc_new:.0%}/{t_new}"
        )
        return False, acc_total, t_total

    logger.info(
        f"Backtest PASS: {law_dict.get('law_type')} "
        f"total={acc_total:.0%}/{t_total} (new={acc_new:.0%}/{t_new} old={acc_old:.0%}/{t_old})"
    )
    return True, acc_total, t_total

def _fetch_backtest_rows() -> List:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        h.id,
                        h.b_num,
                        h.suit,
                        h.rank,
                        h.bonus_last_digit,
                        h.winner,
                        h.created_at,
                        ABS(h.b_num::bigint - LAG(h.b_num::bigint) OVER (ORDER BY h.id)) AS b_gap,
                        EXTRACT(EPOCH FROM (h.created_at - LAG(h.created_at) OVER (ORDER BY h.id))) AS gap_sec
                    FROM history h
                    WHERE h.winner IS NOT NULL
                      AND h.rank IS NOT NULL AND h.rank NOT IN ('NULL','')
                      AND h.b_num ~ '^[0-9]+$'
                    ORDER BY h.id DESC LIMIT 600
                """)
                return cur.fetchall()
    except Exception as e:
        logger.warning(f"_fetch_backtest_rows: {e}")
        return []

def _build_math_memory(rounds: List[Dict]) -> Dict:
    total = len(rounds)
    connected = [r for r in rounds if r["connected"]]
    confirmed_patterns = []
    MIN_N    = 40
    MIN_BIAS = 0.10

    def add_if_significant(label, cond_dict, v, min_n=MIN_N, min_bias=MIN_BIAS):
        n = v[0] + v[1]
        if n < min_n:
            return
        bias = (v[1] - v[0]) / n
        if abs(bias) < min_bias:
            return
        pred = 1 if bias > 0 else 0
        confirmed_patterns.append({
            "pattern": label,
            "conditions": cond_dict,
            "prediction": pred,
            "n": n,
            "red": v[0], "blue": v[1],
            "bias_pct": round(abs(bias) * 100, 1),
            "accuracy_est": round(50 + abs(bias) * 50, 1),
        })

    for mod in range(2, 16):
        mod_stats = defaultdict(lambda: [0, 0])
        for r in rounds:
            if r["b_num"] and r["winner"] in [0, 1]:
                s = sum(int(d) for d in r["b_num"]) % mod
                mod_stats[s][r["winner"]] += 1
        for rem, v in mod_stats.items():
            add_if_significant(
                f"digit_sum mod {mod} == {rem}",
                {"digit_sum_mod": {"mod": mod, "remainder": rem}},
                v
            )

    for d in range(10):
        v = [0, 0]
        for r in rounds:
            if r["b_num"] and r["winner"] in [0, 1]:
                if r["b_num"][-1] == str(d):
                    v[r["winner"]] += 1
        add_if_significant(f"last_digit_bnum == {d}", {"digit": d}, v, min_n=50)

    gap_ranges = [("lt200", None, 200), ("200_500", 200, 500),
                  ("500_2000", 500, 2000), ("gt2000", 2000, None)]
    for label, lo, hi in gap_ranges:
        v = [0, 0]
        for r in rounds:
            if r["b_gap"] is None or r["winner"] not in [0, 1]:
                continue
            if lo is not None and r["b_gap"] < lo:
                continue
            if hi is not None and r["b_gap"] >= hi:
                continue
            v[r["winner"]] += 1
        cond = {}
        if lo: cond["b_gap_gte"] = lo
        if hi: cond["b_gap_lt"]  = hi
        add_if_significant(f"b_gap_{label}", cond, v)

    for cutoff in [10, 15, 20, 30]:
        v_lt = [0, 0]; v_gt = [0, 0]
        for r in rounds:
            if r["gap_sec"] is None or r["winner"] not in [0, 1]:
                continue
            if r["gap_sec"] < cutoff:
                v_lt[r["winner"]] += 1
            else:
                v_gt[r["winner"]] += 1
        add_if_significant(f"gap_sec_lt_{cutoff}", {"gap_sec_lt": cutoff}, v_lt)
        add_if_significant(f"gap_sec_gt_{cutoff}", {"gap_sec_gt": cutoff}, v_gt)

    for cycle in range(3, 10):
        for pos in range(cycle):
            v = [0, 0]
            for i, r in enumerate(connected):
                if r["winner"] in [0, 1] and i % cycle == pos:
                    v[r["winner"]] += 1
            add_if_significant(
                f"cycle{cycle}_pos{pos}",
                {"cycle_position": {"cycle": cycle, "position": pos}},
                v, min_n=25
            )

    for streak_len in [2, 3, 4]:
        for streak_val in [0, 1]:
            v = [0, 0]
            seq = [r["winner"] for r in connected if r["winner"] in [0, 1]]
            for i in range(streak_len, len(seq)):
                if seq[i-streak_len:i] == [streak_val]*streak_len and seq[i] in [0, 1]:
                    v[seq[i]] += 1
            add_if_significant(
                f"after_{streak_len}x_{'red' if streak_val==0 else 'blue'}",
                {"streak": {"length": streak_len, "value": streak_val}},
                v, min_n=20
            )

    ranked = [r for r in rounds if r["rank"] and r["rank"] not in ("", "NULL")]
    for mod in [3, 5, 7]:
        for rank in ["A","K","Q","J","10","9","8","7","6","5","4","3","2"]:
            mod_stats = defaultdict(lambda: [0, 0])
            for r in ranked:
                if r["rank"] == rank and r["winner"] in [0, 1]:
                    s = sum(int(d) for d in r["b_num"]) % mod
                    mod_stats[s][r["winner"]] += 1
            for rem, v in mod_stats.items():
                add_if_significant(
                    f"rank_{rank}_digsum_mod{mod}_{rem}",
                    {"rank": rank, "digit_sum_mod": {"mod": mod, "remainder": rem}},
                    v, min_n=8, min_bias=0.25
                )

    ts_has_data = any(r.get("ts") is not None for r in rounds)
    ts_mod_patterns = {}
    if ts_has_data:
        for mod in [5, 6, 7, 8, 9]:
            mod_stats = defaultdict(lambda: [0, 0])
            for r in rounds:
                if r.get("ts") and r["winner"] in [0, 1]:
                    try:
                        unix_ts = int(r["ts"].timestamp())
                        rem = unix_ts % mod
                        mod_stats[rem][r["winner"]] += 1
                    except Exception:
                        pass
            for rem, v in mod_stats.items():
                add_if_significant(
                    f"timestamp mod {mod} == {rem}",
                    {"ts_mod": {"mod": mod, "remainder": rem}},
                    v, min_n=30, min_bias=0.12
                )
            summary = {}
            for rem, v in mod_stats.items():
                n = v[0] + v[1]
                if n >= 20:
                    bias = round((v[1] - v[0]) / n * 100, 1)
                    summary[str(rem)] = {"n": n, "bias_pct": bias,
                                         "red": v[0], "blue": v[1]}
            if summary:
                ts_mod_patterns[f"ts_mod_{mod}"] = summary

    confirmed_patterns.sort(key=lambda x: -x["bias_pct"])
    top_patterns = confirmed_patterns[:20]

    sample = [
        {
            "b_num": r["b_num"],
            "digit_sum": sum(int(d) for d in r["b_num"]) if r["b_num"] else None,
            "suit": r["suit"], "rank": r["rank"], "digit": r["digit"],
            "winner": r["winner"],
            "b_gap": r["b_gap"],
            "gap_sec": round(r["gap_sec"], 1) if r["gap_sec"] else None,
            "connected": r["connected"],
        }
        for r in rounds[-40:]
    ]

    seq_all = [r["winner"] for r in rounds if r["winner"] in [0, 1]]
    streak_stats = {"after_red_next_red": 0, "after_red_next_blue": 0,
                    "after_blue_next_red": 0, "after_blue_next_blue": 0}
    for i in range(1, len(seq_all)):
        if seq_all[i-1] == 0:
            if seq_all[i] == 0: streak_stats["after_red_next_red"] += 1
            else: streak_stats["after_red_next_blue"] += 1
        else:
            if seq_all[i] == 0: streak_stats["after_blue_next_red"] += 1
            else: streak_stats["after_blue_next_blue"] += 1

    return {
        "overview": {
            "total_valid_rounds": total,
            "connected_rounds": len(connected),
            "ranked_rounds": len(ranked),
            "note": "winner=0 means Banker(red), winner=1 means Player(blue)"
        },
        "confirmed_patterns": top_patterns,
        "timestamp_mod_patterns": ts_mod_patterns,
        "transition_stats": streak_stats,
        "raw_sample_last40": sample,
    }

async def safe_ai_call(prompt: str, max_tokens: int = 8192, temperature: float = 0.1) -> str:
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            logger.info(f"safe_ai_call: attempt {attempt+1}/{max_attempts}")
            result = await _nvidia_chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens if attempt == 0 else max(4096, max_tokens // 2),
                temperature=temperature,
                enable_thinking=True,
                timeout=LEARN_TIMEOUT,
            )
            return result
        except Exception as e:
            if attempt == max_attempts - 1:
                raise e
            wait = 30 * (attempt + 1)
            logger.error(f"safe_ai_call attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
            await asyncio.sleep(wait)
    raise RuntimeError("فشلت كل محاولات الاتصال بـ AI")

async def force_learn_engine(status_callback) -> Dict:
    await status_callback("📥 <b>المرحلة 1/5</b> — جلب كل الجولات...")

    # ✅ تصفير القوانين القديمة قبل التعلم الجديد لكسر الانحياز
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE ai_laws SET active = FALSE")
                deactivated = cur.rowcount
                conn.commit()
        logger.info(f"force_learn: deactivated {deactivated} old laws before learning")
    except Exception as _e:
        logger.warning(f"force_learn: could not deactivate old laws: {_e}")

    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, b_num, suit, rank, bonus_last_digit,
                           winner, created_at
                    FROM history
                    WHERE winner IS NOT NULL AND suit IS NOT NULL
                    ORDER BY id ASC
                """)
                rows = cur.fetchall()
    except Exception as e:
        return {"error": str(e)}

    if len(rows) < 50:
        return {"error": "بيانات غير كافية"}

    raw_total    = len(rows)
    total_rounds = raw_total
    await status_callback(
        f"✅ <b>المرحلة 1/5</b> — {raw_total} جولة خام\n\n"
        f"🔬 <b>المرحلة 2/5</b> — تصفية + تحليل الفجوات..."
    )

    rounds = _filter_valid_rounds(rows)
    conn_cnt = sum(1 for r in rounds if r["connected"])
    memory = _build_math_memory(rounds)

    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT law_type, conditions, prediction, accuracy, description
                    FROM ai_laws WHERE active = TRUE
                    ORDER BY accuracy DESC LIMIT 15
                """)
                existing_laws = cur.fetchall()
    except Exception:
        existing_laws = []

    prev_laws_txt = ""
    if existing_laws:
        prev_laws_txt = "\n\nالقوانين الحالية (لا تكررها، طوّر عليها أو اكتشف جديدة):\n"
        for l in existing_laws:
            prev_laws_txt += f"- [{l[0]}] pred={l[2]} acc={l[3]:.0f}% — {l[4]}\n"

    await status_callback(
        f"✅ <b>المرحلة 2/5</b> — {len(rounds)} جولة صالحة ({conn_cnt} متصلة)\n\n"
        f"🤖 <b>المرحلة 3/5</b> — Qwen يحلل الأنماط الرياضية...\n"
        f"<i>لا مهلة زمنية — انتظر حتى الاكتمال</i>"
    )

    prompt = f"""
أنت محلل بيانات رياضي متخصص.

مهمتك: تحويل الأنماط الإحصائية المُثبتة إلى قوانين قابلة للتطبيق.

━━━ تعريف أساسي ━━━
prediction=0 = الراعي 🔴 (Banker/Red)
prediction=1 = الثور 🔵 (Player/Blue)

━━━ الأنماط المُثبتة إحصائياً من {len(rounds)} جولة حقيقية ━━━
هذه أنماط حقيقية من البيانات، ليست افتراضات:

{json.dumps(memory["confirmed_patterns"][:25], ensure_ascii=False, indent=1)}

━━━ أنماط Timestamp mod N (RNG seed detection) ━━━
{json.dumps(memory.get("timestamp_mod_patterns", {}), ensure_ascii=False, indent=1) if memory.get("timestamp_mod_patterns") else "لا بيانات timestamp كافية"}

━━━ إحصاءات الانتقال ━━━
{json.dumps(memory["transition_stats"], ensure_ascii=False)}

━━━ عينة من آخر 80 جولة (الأحدث في النهاية) ━━━
{json.dumps(memory["raw_sample_last40"][-30:], ensure_ascii=False)}

━━━ القوانين الحالية (لا تكررها) ━━━
{prev_laws_txt}

━━━ المطلوب ━━━
أنت مهندس خوارزميات كمّي. مهمتك: اكتشاف أنماط كسر السلاسل وتأثير الفجوات الزمنية.

القواعد الصارمة:
1. ممنوع تماماً: digit، digit_sum_mod، rank، ts_mod، b_gap، suit
2. الشروط المسموحة فقط:
   - {{"streak":{{"length":2أو3أو4أو5,"value":0أو1}}}}
   - {{"gap_sec_gt":N}} أو {{"gap_sec_lt":N}} (بين 15 و60)
   - {{"cycle_position":{{"cycle":N,"position":K}}}} (cycle بين 4 و10)
3. شرط واحد أو اثنان فقط لكل قانون
4. confidence بين 55-68 فقط
5. أنشئ 10-12 قانوناً

مثال ممتاز:
{{"law_type":"streak3_gap_break","conditions":{{"streak":{{"length":3,"value":0}},"gap_sec_gt":30}},"prediction":1,"confidence":63,"description":"بعد 3 رواعٍ + تأخير >30ث → الثور"}}

أعد JSON array فقط:
"""

    try:
        raw_text = await safe_ai_call(
            prompt=prompt,
            max_tokens=8192,
            temperature=0.1,
        )
        logger.info(f"Qwen raw_text length={len(raw_text)}, preview: {raw_text[:300]}")
    except asyncio.TimeoutError:
        return {"error": "انتهت المهلة الزمنية"}
    except Exception as e:
        return {"error": f"خطأ في AI: {e}"}

    await status_callback(
        "✅ <b>المرحلة 3/5</b> — Qwen أكمل التحليل\n\n"
        "🔬 <b>المرحلة 4/5</b> — Backtest على التاريخ الحقيقي..."
    )

    backtest_rows = _fetch_backtest_rows()
    logger.info(f"Backtest rows: {len(backtest_rows)}")

    laws_data = extract_json_safe(raw_text)
    if not laws_data or not isinstance(laws_data, list):
        logger.error(f"Qwen raw response (first 500):\n{raw_text[:500]}")
        recovered = _scan_json_objects(raw_text)
        if recovered:
            logger.info(f"Recovered {len(recovered)} laws from partial/truncated JSON")
            laws_data = recovered
        else:
            preview = raw_text[:400] if raw_text else "فارغ تماماً"
            return {"error": f"فشل استخراج JSON\nطول الرد: {len(raw_text)} حرف\nأول 400 حرف:\n<code>{html.escape(preview)}</code>"}

    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ai_laws SET active = TRUE
                    WHERE active = FALSE
                      AND accuracy >= 85
                      AND times_used < 5
                      AND created_at > NOW() - INTERVAL '24 hours'
                """)
                reactivated = cur.rowcount
                conn.commit()
                if reactivated:
                    logger.info(f"Reactivated {reactivated} high-accuracy laws")
    except Exception:
        pass

    saved = 0
    skipped = 0
    rejected_bt = 0
    sample_laws_saved = []

    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM learn_sessions")
                session_id = cur.fetchone()[0]

                cur.execute("SELECT conditions::text FROM ai_laws WHERE active = TRUE")
                existing_conds = set(r[0] for r in cur.fetchall())

                for law in laws_data:
                    if not isinstance(law, dict):
                        continue
                    pred = law.get("prediction")
                    if pred not in [0, 1]:
                        skipped += 1
                        continue
                    cond = law.get("conditions", {})
                    if not cond:
                        skipped += 1
                        continue

                    cond_str = json.dumps(cond, ensure_ascii=False, sort_keys=True)
                    if cond_str in existing_conds:
                        skipped += 1
                        logger.info(f"DUPLICATE REJECTED: {law.get('law_type')} conditions already exist")
                        continue

                    bt_passes, bt_acc, bt_n = backtest_law(law, backtest_rows)
                    if not bt_passes:
                        rejected_bt += 1
                        logger.info(
                            f"Backtest REJECTED: {law.get('law_type')} "
                            f"acc={bt_acc:.0%} n={bt_n} "
                            f"({'عينة صغيرة' if bt_n < 15 else 'دقة ضعيفة'})"
                        )
                        continue

                    initial_acc = round(bt_acc * 100, 1)
                    law_name = f"{law.get('law_type', 'COMBINED')}_{saved}_{int(time.time())}"
                    cur.execute("""
                        INSERT INTO ai_laws
                            (law_type, conditions, prediction, confidence,
                             accuracy, description, source)
                        VALUES (%s, %s, %s, %s, %s, %s, 'force_learn')
                    """, (
                        law.get("law_type", "COMBINED"),
                        cond_str,
                        int(pred),
                        float(law.get("confidence", 70)),
                        initial_acc,
                        f"{law.get('description', '')} [bt:{bt_acc:.0%}/{bt_n}]",
                    ))
                    existing_conds.add(cond_str)
                    saved += 1
                    if len(sample_laws_saved) < 3:
                        sample_laws_saved.append({**law, "bt_acc": bt_acc, "bt_n": bt_n})

                cur.execute("""
                    INSERT INTO learn_sessions
                        (rounds_used, laws_created, laws_updated, summary, context)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    total_rounds, saved, 0,
                    f"جلسة #{session_id}: {saved} قانون نجح backtest من أصل {len(laws_data)} ({rejected_bt} مرفوض)",
                    json.dumps({"memory_keys": list(memory.keys()),
                                "backtest_rows": len(backtest_rows)}, ensure_ascii=False)
                ))
                conn.commit()
    except Exception as e:
        return {"error": f"خطأ في حفظ القوانين: {e}"}

    await status_callback(
        f"✅ <b>المرحلة 4/5</b> — <b>{saved}</b> قانون نجح الـ backtest"
        f"  |  ❌ {rejected_bt} مرفوض\n\n"
        f"🔄 <b>المرحلة 5/5</b> — تحديث الذاكرة النشطة..."
    )

    load_laws(force=True)

    return {
        "total_rounds":   total_rounds,
        "laws_saved":     saved,
        "laws_skipped":   skipped,
        "laws_rejected":  rejected_bt,
        "session_id":     session_id,
        "sample_laws":    sample_laws_saved,
        "backtest_rows":  len(backtest_rows),
    }

def _build_statistical_memory(rows) -> Dict:
    rounds = []
    for row in rows:
        w = WINNER_MAP.get(row[5], 2)
        if w == 2:
            continue
        rounds.append({
            "suit":   row[2] or "",
            "rank":   row[3] or "",
            "digit":  int(row[4]) if row[4] is not None else -1,
            "winner": w,
        })
    if not rounds:
        return {}
    total = len(rounds)
    red   = sum(1 for r in rounds if r["winner"] == 0)
    blue  = sum(1 for r in rounds if r["winner"] == 1)

    suit_stats = defaultdict(lambda: [0, 0])
    for r in rounds:
        suit_stats[r["suit"]][r["winner"]] += 1

    digit_stats = defaultdict(lambda: [0, 0])
    for r in rounds:
        if r["digit"] >= 0:
            digit_stats[str(r["digit"])][r["winner"]] += 1

    rank_stats = defaultdict(lambda: [0, 0])
    for r in rounds:
        rank_stats[r["rank"]][r["winner"]] += 1

    sd_stats = defaultdict(lambda: [0, 0])
    for r in rounds:
        if r["digit"] >= 0:
            key = f"{r['suit']}_{r['digit']}"
            sd_stats[key][r["winner"]] += 1

    streak_analysis = _analyze_streaks([r["winner"] for r in rounds])
    triplet_analysis = _analyze_triplets([r["winner"] for r in rounds])
    suit_transition = _analyze_suit_transitions(rounds)
    best_patterns = _find_best_patterns(suit_stats, digit_stats, rank_stats, sd_stats)

    return {
        "overview": {
            "total": total,
            "red_pct": round(red / total * 100, 1),
            "blue_pct": round(blue / total * 100, 1),
        },
        "suit_win_rates": {
            s: {
                "red": v[0], "blue": v[1],
                "blue_dominance": round((v[1] - v[0]) / max(v[0] + v[1], 1) * 100, 1)
            }
            for s, v in suit_stats.items()
        },
        "digit_win_rates": {
            d: {
                "red": v[0], "blue": v[1],
                "blue_dominance": round((v[1] - v[0]) / max(v[0] + v[1], 1) * 100, 1)
            }
            for d, v in digit_stats.items()
        },
        "rank_win_rates": {
            r: {
                "red": v[0], "blue": v[1],
                "blue_dominance": round((v[1] - v[0]) / max(v[0] + v[1], 1) * 100, 1)
            }
            for r, v in rank_stats.items()
        },
        "top_sd_patterns": dict(sorted(
            {k: {"red": v[0], "blue": v[1]} for k, v in sd_stats.items()}.items(),
            key=lambda x: abs(x[1]["blue"] - x[1]["red"]), reverse=True
        )[:15]),
        "streak_analysis": streak_analysis,
        "triplet_analysis": triplet_analysis,
        "suit_transitions": suit_transition,
        "best_patterns":    best_patterns,
    }

def _analyze_streaks(winners: List[int]) -> Dict:
    results = {"after_red_streak": {}, "after_blue_streak": {}}
    i = 0
    while i < len(winners):
        j = i
        while j < len(winners) and winners[j] == winners[i]:
            j += 1
        streak_len = j - i
        val        = winners[i]
        if streak_len >= 2 and j < len(winners):
            key = f"len_{min(streak_len, 5)}"
            side = "after_red_streak" if val == 0 else "after_blue_streak"
            next_val = winners[j]
            if key not in results[side]:
                results[side][key] = {"continued": 0, "broke": 0}
            if next_val == val:
                results[side][key]["continued"] += 1
            else:
                results[side][key]["broke"] += 1
        i = j
    return results

def _analyze_triplets(winners: List[int]) -> Dict:
    triplets = defaultdict(lambda: [0, 0])
    for i in range(len(winners) - 3):
        key = f"{winners[i]}{winners[i+1]}{winners[i+2]}"
        triplets[key][winners[i+3]] += 1
    return {
        k: {"next_red": v[0], "next_blue": v[1],
            "likely": "red" if v[0] > v[1] else "blue"}
        for k, v in triplets.items()
        if v[0] + v[1] >= 5
    }

def _analyze_suit_transitions(rounds: List[Dict]) -> Dict:
    transitions = defaultdict(lambda: [0, 0])
    for i in range(1, len(rounds)):
        prev_suit = rounds[i-1]["suit"]
        curr_suit = rounds[i]["suit"]
        if prev_suit != curr_suit:
            key = f"{prev_suit}→{curr_suit}"
            transitions[key][rounds[i]["winner"]] += 1
    return {
        k: {"red": v[0], "blue": v[1]}
        for k, v in transitions.items()
        if v[0] + v[1] >= 3
    }

def _find_best_patterns(suit_s, digit_s, rank_s, sd_s) -> Dict:
    all_p = {}
    for k, v in suit_s.items():
        t = v[0] + v[1]
        if t >= 10:
            all_p[f"SUIT_{k}"] = (v[1] - v[0]) / t
    for k, v in digit_s.items():
        t = v[0] + v[1]
        if t >= 10:
            all_p[f"DIGIT_{k}"] = (v[1] - v[0]) / t
    for k, v in rank_s.items():
        t = v[0] + v[1]
        if t >= 5:
            all_p[f"RANK_{k}"] = (v[1] - v[0]) / t
    for k, v in sd_s.items():
        t = v[0] + v[1]
        if t >= 8:
            all_p[f"SD_{k}"] = (v[1] - v[0]) / t
    sorted_p = sorted(all_p.items(), key=lambda x: abs(x[1]), reverse=True)
    return {
        "strongest_blue": [(k, round(v*100, 1)) for k, v in sorted_p if v > 0][:5],
        "strongest_red":  [(k, round(-v*100, 1)) for k, v in sorted_p if v < 0][:5],
    }

# ==================== ⚡ تحليل الزخم الحقيقي (T1) ====================
def detect_real_streak(history: List[int]) -> Tuple[Optional[int], float]:
    if len(history) < 4:
        return None, 0.0
    last   = history[-1]
    streak = 1
    for i in range(len(history) - 2, -1, -1):
        if history[i] == last:
            streak += 1
        else:
            break
    if streak >= 4:
        opposite = 1 if last == 0 else 0
        conf = min(0.90, 0.75 + (streak - 4) * 0.03)
        return opposite, conf
    return None, 0.0

# ==================== 🧠 الذاكرة القصيرة (T2) ====================
def short_memory_bias(history: List[int]) -> Tuple[Optional[int], float]:
    if len(history) < 10:
        return None, 0.0
    last10 = history[-10:]
    r = last10.count(0)
    b = last10.count(1)
    if abs(r - b) >= 5:
        return (0, 0.65) if r > b else (1, 0.65)
    return None, 0.0

# ==================== 📊 انحياز البذلة الذكي (T3) ====================
def suit_bias_from_history(suit: str) -> Tuple[Optional[int], float]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL AND suit = %s ORDER BY id DESC LIMIT 80", (suit,))
                rows = cur.fetchall()
        if len(rows) < 10:
            return None, 0.0
        r = sum(1 for x in rows if WINNER_MAP.get(x[0], 2) == 0)
        b = sum(1 for x in rows if WINNER_MAP.get(x[0], 2) == 1)
        t = r + b
        if t == 0:
            return None, 0.0
        diff = (b - r) / t
        if abs(diff) > 0.20:
            pred = 1 if diff > 0 else 0
            conf = min(0.70, abs(diff))
            return pred, conf
    except Exception:
        pass
    return None, 0.0

# ==================== 🔢 فحص الأعداد الأولية (T7) ====================
def is_prime(n: int) -> bool:
    if n < 2:
        return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            return False
    return True

# ════════════════════════════════════════════════════════════════════
# 🧬 المحرك 1: أوزان تكيّفية ديناميكية
# ════════════════════════════════════════════════════════════════════
_signal_perf: Dict[str, List[int]] = {}

def get_adaptive_weight(signal: str, base_weight: float) -> float:
    perf = _signal_perf.get(signal)
    if not perf or perf[1] < 20:
        return base_weight
    acc = perf[0] / perf[1]
    if acc >= 0.65:   factor = 1.20
    elif acc >= 0.55: factor = 1.10
    elif acc >= 0.45: factor = 1.00
    elif acc >= 0.35: factor = 0.85
    else:             factor = 0.70
    return base_weight * factor

def update_signal_perf(signal: str, correct: bool, window: int = 60):
    if signal not in _signal_perf:
        _signal_perf[signal] = [0, 0]
    _signal_perf[signal][1] += 1
    if correct:
        _signal_perf[signal][0] += 1
    if _signal_perf[signal][1] > window:
        decay = 1 / window
        _signal_perf[signal][0] = max(0, _signal_perf[signal][0] - decay)
        _signal_perf[signal][1] = window

def load_signal_perf_from_db():
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT signal_name, correct_count, total_count FROM signal_performance WHERE total_count > 0")
                for row in cur.fetchall():
                    _signal_perf[row[0]] = [int(row[1]), int(row[2])]
        logger.info(f"✅ Loaded {len(_signal_perf)} signal performance records")
    except Exception:
        pass

def save_signal_perf_to_db():
    if not _signal_perf:
        return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                for sig, vals in _signal_perf.items():
                    cur.execute("""
                        INSERT INTO signal_performance (signal_name, correct_count, total_count)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (signal_name) DO UPDATE
                            SET correct_count = EXCLUDED.correct_count,
                                total_count   = EXCLUDED.total_count
                    """, (sig, vals[0], vals[1]))
                conn.commit()
    except Exception as e:
        logger.warning(f"save_signal_perf: {e}")

# ════════════════════════════════════════════════════════════════════
# 🔗 المحرك 2: سلسلة ماركوف (Markov Chain)
# ════════════════════════════════════════════════════════════════════
_markov_cache: Optional[Dict] = None
_markov_ts: float = 0.0
_session_markov_cache: Optional[Dict] = None
_session_markov_ts: float = 0.0

def build_markov_from_seq(seq: List[int]) -> Dict:
    matrix: Dict[str, Dict[int, int]] = defaultdict(lambda: {0: 0, 1: 0})
    for i in range(len(seq) - 3):
        key = f"{seq[i]}{seq[i+1]}{seq[i+2]}"
        matrix[key][seq[i+3]] += 1
    return dict(matrix)

def build_session_markov(connected_seq: List[int]) -> Dict:
    global _session_markov_cache, _session_markov_ts
    if _session_markov_cache is not None and time.time() - _session_markov_ts < 15:
        return _session_markov_cache
    clean = [x for x in connected_seq if x in [0, 1]]
    if len(clean) < 6:
        return {}
    result = build_markov_from_seq(clean)
    _session_markov_cache = result
    _session_markov_ts    = time.time()
    return result

def build_markov_matrix() -> Dict:
    global _markov_cache, _markov_ts
    if _markov_cache and time.time() - _markov_ts < 60:
        return _markov_cache
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner, created_at FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 600")
                rows = list(reversed(cur.fetchall()))
        connected_seq: List[int] = []
        for i, (w, ts) in enumerate(rows):
            val = WINNER_MAP.get(w, 2)
            if val not in [0, 1]:
                continue
            if i > 0 and rows[i-1][1] and ts:
                gap = (ts - rows[i-1][1]).total_seconds()
                if gap > SESSION_CONNECTED_SEC:
                    pass
            connected_seq.append(val)
        matrix: Dict[str, Dict[int, int]] = defaultdict(lambda: {0: 0, 1: 0})
        for i in range(len(connected_seq) - 3):
            key = f"{connected_seq[i]}{connected_seq[i+1]}{connected_seq[i+2]}"
            matrix[key][connected_seq[i+3]] += 1
        _markov_cache = dict(matrix)
        _markov_ts    = time.time()
        return _markov_cache
    except Exception:
        return {}

def markov_predict(history: List[int], session_history: Optional[List[int]] = None) -> Tuple[Optional[int], float, str]:
    clean = [x for x in history if x in [0, 1]]
    if len(clean) < 3:
        return None, 0.0, ""
    key = f"{clean[-3]}{clean[-2]}{clean[-1]}"

    if session_history and len([x for x in session_history if x in [0,1]]) >= 6:
        sess_matrix = build_session_markov(session_history)
        counts = sess_matrix.get(key)
        if counts:
            r, b = counts.get(0, 0), counts.get(1, 0)
            total = r + b
            if total >= 3:
                pred = 0 if r > b else 1
                conf = max(r, b) / total
                if conf >= 0.55:
                    return pred, conf, f"ماركوف-جلسة[{key}]→{r}🔴:{b}🔵 ({total} مشاهدة)"

    matrix = build_markov_matrix()
    counts = matrix.get(key)
    if not counts:
        return None, 0.0, ""
    r, b   = counts.get(0, 0), counts.get(1, 0)
    total  = r + b
    if total < 4:
        return None, 0.0, ""
    pred   = 0 if r > b else 1
    conf   = max(r, b) / total
    if conf < 0.55:
        return None, 0.0, ""
    return pred, conf, f"ماركوف[{key}]→{r}🔴:{b}🔵 ({total} مشاهدة)"

# ════════════════════════════════════════════════════════════════════
# 🔄 المحرك 3: كاشف الدورات (Cycle Detector)
# ════════════════════════════════════════════════════════════════════
def detect_cycle(history: List[int]) -> Tuple[Optional[int], float, str]:
    if len(history) < 6:
        return None, 0.0, ""
    for cycle_len in [2, 3, 4, 5, 6]:
        if len(history) < cycle_len * 2:
            continue
        recent   = history[-cycle_len * 2:]
        first    = recent[:cycle_len]
        second   = recent[cycle_len:]
        if first == second:
            next_pos = len(history) % cycle_len
            pred     = first[next_pos]
            if pred in [0, 1]:
                conf = 0.70 + (cycle_len - 2) * 0.03
                return pred, min(conf, 0.88), f"دورة طولها {cycle_len}"
    if len(history) >= 4:
        last4 = history[-4:]
        if last4 == [0, 1, 0, 1] or last4 == [1, 0, 1, 0]:
            pred = 1 - history[-1]
            return pred, 0.72, "نمط تبادلي"
    return None, 0.0, ""

# ════════════════════════════════════════════════════════════════════
# 📡 المحرك 4: مضخّم الإجماع (Consensus Amplifier)
# ════════════════════════════════════════════════════════════════════
def amplify_consensus(scores: Dict[int, float], signal_count: int) -> float:
    s0, s1    = scores[0], scores[1]
    total     = s0 + s1
    if total == 0:
        return 1.0
    dominance = abs(s0 - s1) / total
    sig_bonus = min(signal_count / 8, 1.0)
    amplifier = 1.0 + dominance * 0.6 * sig_bonus
    return min(amplifier, 1.8)

# ════════════════════════════════════════════════════════════════════
# 🧮 المحرك 5: بصمة b_num متعددة الأبعاد
# ════════════════════════════════════════════════════════════════════
def bnum_fingerprint(b_num: str, rank: str) -> List[Tuple[int, float, str]]:
    signals = []
    if not b_num:
        return signals
    digits   = [int(d) for d in b_num]
    d_sum    = sum(digits)
    d_prod   = 1
    for d in digits:
        d_prod = (d_prod * max(d, 1)) % 97
    rv       = RANK_VALUE.get(rank.upper(), 7)
    last_d   = digits[-1]
    first_d  = digits[0]

    r1 = d_sum % 3
    w1 = 0 if r1 in [0, 2] else 1
    signals.append((w1, 0.55, f"Σmod3={r1}"))

    r2 = (d_sum + rv) % 4
    w2 = 0 if r2 in [0, 3] else 1
    signals.append((w2, 0.58, f"(Σ+rank)mod4={r2}"))

    r3 = d_prod % 7
    w3 = 0 if r3 in [0, 1, 6] else 1
    signals.append((w3, 0.52, f"Πmod7={r3}"))

    r4 = (last_d * max(first_d, 1) + rv) % 2
    signals.append((r4, 0.54, f"(L×F+rv)mod2={r4}"))

    odd_count = sum(1 for d in digits if d % 2 == 1)
    r5 = odd_count % 2
    w5 = 0 if r5 == 0 else 1
    signals.append((w5, 0.53, f"odds_mod2={r5}"))
    return signals

# ════════════════════════════════════════════════════════════════════
# 🔮 المحرك 6: مدير القوانين الذاتي (Auto-Law Manager)
# ════════════════════════════════════════════════════════════════════
def prune_weak_patterns():
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM pattern_stats
                    WHERE (red_count + blue_count) > 50
                      AND ABS(blue_count - red_count) / NULLIF(red_count + blue_count, 0) < 0.02
                """)
                removed = cur.rowcount
                conn.commit()
            if removed:
                logger.info(f"prune_weak_patterns: removed {removed} weak patterns")
                live_cache.cache.clear()
    except Exception as e:
        logger.warning(f"prune_weak_patterns: {e}")

def auto_manage_laws():
    """
    Quant Filter: يحمي القوانين ذات العينة الكبيرة حتى لو دقتها 52%.
    Edge حقيقي على 400+ جولة أفضل من وهم 90% على 5 جولات.
    """
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                # 1. قتل الضوضاء الصريحة: عينة صغيرة + دقة ضعيفة
                cur.execute("""
                    UPDATE ai_laws SET active = FALSE
                    WHERE active = TRUE
                      AND times_used >= 5 AND times_used < 30
                      AND accuracy < 60
                """)
                d_noise = cur.rowcount

                # 2. العينة المتوسطة: تسقط عند < 53%
                cur.execute("""
                    UPDATE ai_laws SET active = FALSE
                    WHERE active = TRUE
                      AND times_used >= 30 AND times_used < 100
                      AND accuracy < 53
                """)
                d_mid = cur.rowcount

                # 3. حماية العمالقة (n≥100): يموت فقط إذا فقد الـ Edge كلياً (< 50.5%)
                cur.execute("""
                    UPDATE ai_laws SET active = FALSE
                    WHERE active = TRUE
                      AND times_used >= 100
                      AND accuracy < 50.5
                """)
                d_core = cur.rowcount

                # 4. drift detection: انهار حديثاً
                cur.execute("""
                    UPDATE ai_laws SET active = FALSE
                    WHERE active = TRUE
                      AND times_used >= 20
                      AND accuracy_recent IS NOT NULL
                      AND accuracy_recent < accuracy - 15
                      AND accuracy_recent < 45
                """)
                drifted = cur.rowcount

                # 5. تعزيز القوانين الممتازة
                cur.execute("""
                    UPDATE ai_laws
                    SET confidence = LEAST(97, confidence * 1.04)
                    WHERE active = TRUE
                      AND times_used >= 30
                      AND accuracy > 70
                """)
                boosted = cur.rowcount

                conn.commit()
                prune_weak_patterns()
                total = d_noise + d_mid + d_core + drifted
                if total or boosted:
                    load_laws(force=True)
                    logger.info(
                        f"QuantFilter: noise={d_noise} mid={d_mid} core={d_core} "
                        f"drift={drifted} boosted={boosted}"
                    )
    except Exception as e:
        logger.warning(f"auto_manage_laws: {e}")

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🧬 المحرك الخرافي 1: LOOKALIKE ENGINE                             ║
# ╚══════════════════════════════════════════════════════════════════════╝
_lookalike_history_cache: List[int] = []
_lookalike_cache_ts: float = 0.0

def _refresh_lookalike_cache():
    global _lookalike_history_cache, _lookalike_cache_ts
    if time.time() - _lookalike_cache_ts < 45:
        return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 800")
                raw = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
                _lookalike_history_cache = [x for x in reversed(raw) if x in [0, 1]]
                _lookalike_cache_ts = time.time()
    except Exception:
        pass

def lookalike_predict(recent: List[int], window: int = 8) -> Tuple[Optional[int], float, str]:
    _refresh_lookalike_cache()
    hist = _lookalike_history_cache
    if len(recent) < window or len(hist) < window + 1:
        return None, 0.0, ""
    query   = recent[-window:]
    matches = []
    for i in range(len(hist) - window - 1):
        segment = hist[i : i + window]
        sim = sum(1 for a, b in zip(query, segment) if a == b) / window
        if sim >= 0.70:
            nxt = hist[i + window]
            if nxt in [0, 1]:
                matches.append((sim, nxt))
    if len(matches) < 3:
        return None, 0.0, ""
    matches.sort(key=lambda x: -x[0])
    top   = matches[:8]
    votes = {0: 0.0, 1: 0.0}
    for sim, res in top:
        votes[res] += sim
    total_v = votes[0] + votes[1]
    if total_v == 0:
        return None, 0.0, ""
    pred = 0 if votes[0] >= votes[1] else 1
    conf = max(votes[0], votes[1]) / total_v
    if conf < 0.58:
        return None, 0.0, ""
    return pred, conf, f"lookalike: {len(matches)} موضع مشابه ({top[0][0]:.0%} أعلى)"

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🧠 المحرك الخرافي 2: REGIME DETECTOR                             ║
# ╚══════════════════════════════════════════════════════════════════════╝
_REGIME_BANKER     = "banker_streak"
_REGIME_PLAYER     = "player_streak"
_REGIME_ALTERNATING= "alternating"
_REGIME_CHAOTIC    = "chaotic"

def detect_regime(history: List[int]) -> Tuple[str, float]:
    last12 = [x for x in history[-12:] if x in [0, 1]]
    if len(last12) < 6:
        return _REGIME_CHAOTIC, 0.5
    r = last12.count(0); b = last12.count(1); n = len(last12)
    if r / n >= 0.70:
        return _REGIME_BANKER, r / n
    if b / n >= 0.70:
        return _REGIME_PLAYER, b / n
    alt = sum(1 for i in range(len(last12)-1) if last12[i] != last12[i+1])
    if alt / (len(last12)-1) >= 0.70:
        return _REGIME_ALTERNATING, alt / (len(last12)-1)
    return _REGIME_CHAOTIC, 0.5

def regime_vote(regime: str, conf: float, history: List[int]) -> Tuple[Optional[int], float, str]:
    def streak_of(val):
        n = 0
        for v in reversed(history):
            if v == val: n += 1
            else: break
        return n
    if regime == _REGIME_BANKER:
        sl = streak_of(0)
        if sl >= 5:
            return 1, 0.72, f"كسر سيطرة الراعي (سلسلة {sl})"
        return 0, conf * 0.85, "استمرار سيطرة الراعي"
    if regime == _REGIME_PLAYER:
        sl = streak_of(1)
        if sl >= 5:
            return 0, 0.72, f"كسر سيطرة الثور (سلسلة {sl})"
        return 1, conf * 0.85, "استمرار سيطرة الثور"
    if regime == _REGIME_ALTERNATING:
        last = next((v for v in reversed(history) if v in [0,1]), None)
        if last is not None:
            pred = 1 - last
            return pred, conf * 0.90, f"تبادل → {WINNER_NAMES[pred]}"
    return None, 0.0, ""

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  📉 المحرك الخرافي 3: ANTI-MODE                                   ║
# ╚══════════════════════════════════════════════════════════════════════╝
def check_anti_mode() -> Tuple[bool, float]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner, prediction FROM history WHERE winner IS NOT NULL AND prediction IS NOT NULL ORDER BY id DESC LIMIT 15")
                rows = cur.fetchall()
        if len(rows) < 8:
            return False, 0.5
        correct = sum(1 for r in rows if WINNER_MAP.get(r[0],-1) == WINNER_MAP.get(r[1],-2))
        acc = correct / len(rows)
        return acc < 0.38, round(acc, 3)
    except Exception:
        return False, 0.5

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  📊 المحرك الخرافي 4: BAYESIAN ENGINE                             ║
# ╚══════════════════════════════════════════════════════════════════════╝
def bayesian_predict(suit: str, rank: str, last_digit: int) -> Tuple[Optional[int], float, str]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        SUM(CASE WHEN winner IN ('الراعي 🔴','راعي') THEN 1 ELSE 0 END)::float,
                        SUM(CASE WHEN winner IN ('الثور 🔵','ثور')   THEN 1 ELSE 0 END)::float,
                        COUNT(*)::float
                    FROM history WHERE winner IS NOT NULL
                """)
                pr = cur.fetchone()
                if not pr or not pr[2] or pr[2] < 20:
                    return None, 0.0, ""
                prior_r = (float(pr[0] or 0) + 1) / (float(pr[2]) + 2)
                prior_b = (float(pr[1] or 0) + 1) / (float(pr[2]) + 2)

                cur.execute("""
                    SELECT
                        SUM(CASE WHEN winner IN ('الراعي 🔴','راعي') THEN 1 ELSE 0 END)::float,
                        SUM(CASE WHEN winner IN ('الثور 🔵','ثور')   THEN 1 ELSE 0 END)::float,
                        COUNT(*)::float
                    FROM history
                    WHERE suit = %s AND bonus_last_digit = %s AND winner IS NOT NULL
                """, (suit, last_digit))
                lk = cur.fetchone()
                if not lk or not lk[2] or lk[2] < 5:
                    return None, 0.0, ""

                lk_r = (float(lk[0] or 0) + 1) / (float(lk[2]) + 2)
                lk_b = (float(lk[1] or 0) + 1) / (float(lk[2]) + 2)

                post_r = prior_r * lk_r
                post_b = prior_b * lk_b
                total  = post_r + post_b
                if total == 0:
                    return None, 0.0, ""

                nr = post_r / total
                nb = post_b / total
                if abs(nr - nb) < 0.06:
                    return None, 0.0, ""

                pred = 0 if nr > nb else 1
                return pred, max(nr, nb), f"P(🔴)={nr:.2f} P(🔵)={nb:.2f} n={int(float(lk[2]))}"
    except Exception as e:
        logger.debug(f"bayesian: {e}")
        return None, 0.0, ""

# ==================== كاشف الزخم ====================
def detect_momentum() -> Tuple[Optional[int], float, str]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner, created_at FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 4")
                rows = cur.fetchall()
        if len(rows) < 3:
            return None, 0.0, ""
        if (datetime.now() - rows[0][1]).total_seconds() > 300:
            return None, 0.0, ""
        recent = [WINNER_MAP.get(r[0], 2) for r in rows[:3]]
        if recent == [0, 0, 0]:
            return 1, 0.85, "⚠️ كسر سلسلة الراعي"
        if recent == [1, 1, 1]:
            return 0, 0.85, "⚠️ كسر سلسلة الثور"
    except Exception as e:
        logger.error(f"Momentum error: {e}")
    return None, 0.0, ""

# ==================== AI للتنبؤ الآني ====================
async def ai_predict(recent_history: List[int]) -> Tuple[Optional[int], float, str]:
    if len(recent_history) < 3:
        return None, 0.0, "بيانات غير كافية"
    try:
        task = asyncio.create_task(_ai_fetch(recent_history))
        return await asyncio.wait_for(task, timeout=AI_TIMEOUT)
    except asyncio.TimeoutError:
        return None, 0.0, "تجاوز المهلة"
    except Exception as e:
        return None, 0.0, f"خطأ: {str(e)[:30]}"

async def _ai_fetch(recent_history: List[int]) -> Tuple[Optional[int], float, str]:
    prompt = (
        f"أنت محلل باكارات. 0=راعي، 1=ثور.\n"
        f"التسلسل: {recent_history}\n"
        f"توقّع الجولة التالية. أعد JSON فقط:\n"
        f'{{"winner":0أو1,"confidence":50-95,"reason":"سبب"}}'
    )
    full = await _nvidia_chat(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=256,
        temperature=0.3,
        enable_thinking=False,
        timeout=int(AI_TIMEOUT),
    )
    data = extract_json_safe(full)
    if data and isinstance(data, dict):
        return int(data.get("winner", 2)), float(data.get("confidence", 50)), data.get("reason", "")
    return None, 0.0, "خطأ في قراءة الرد"

# ════════════════════════════════════════════════════════════════════
# 🕰️ المحرك الأسطوري 1: الارتباط الزمني (Temporal Autocorrelation)
# ════════════════════════════════════════════════════════════════════
def temporal_autocorr(history: List[int]) -> Tuple[Optional[int], float, str]:
    seq = [x for x in history if x in [0, 1]]
    if len(seq) < 20:
        return None, 0.0, ""
    best_lag, best_score, best_match = None, 0.0, 0.5
    for lag in range(1, min(16, len(seq) - 5)):
        pairs = [(seq[i - lag], seq[i]) for i in range(lag, len(seq))]
        if len(pairs) < 8:
            continue
        match_rate = sum(1 for a, b in pairs if a == b) / len(pairs)
        score = abs(match_rate - 0.5) * 2
        if score > best_score:
            best_score, best_lag, best_match = score, lag, match_rate
    if best_lag is None or best_score < 0.12:
        return None, 0.0, ""
    lag_val = seq[-best_lag]
    pred = lag_val if best_match >= 0.5 else (1 - lag_val)
    conf = 0.54 + best_score * 0.35
    return pred, min(conf, 0.89), f"ارتباط زمني lag={best_lag} r={best_score:.2f}"

# ════════════════════════════════════════════════════════════════════
# 🔍 المحرك الأسطوري 2: بحث N-Gram في DB كاملة
# ════════════════════════════════════════════════════════════════════
_ngram_cache: Dict[str, Tuple] = {}
_ngram_ts: float = 0.0

def ngram_db_predict(history: List[int]) -> Tuple[Optional[int], float, str]:
    global _ngram_cache, _ngram_ts
    clean = [x for x in history if x in [0, 1]]
    if len(clean) < 5:
        return None, 0.0, ""
    for n in [5, 4, 3]:
        if len(clean) < n:
            continue
        key = "".join(map(str, clean[-n:]))
        cache_key = f"ngram_{key}"
        if cache_key in _ngram_cache and time.time() - _ngram_ts < 45:
            cached = _ngram_cache[cache_key]
            if cached[0] is not None:
                return cached
        counts = {0: 0, 1: 0}
        for i in range(len(clean) - n - 1):
            if tuple(clean[i:i+n]) == tuple(clean[-n:]):
                nxt = clean[i + n]
                if nxt in [0, 1]:
                    counts[nxt] += 1
        total = counts[0] + counts[1]
        if total >= 3:
            pred = 0 if counts[0] > counts[1] else 1
            conf = max(counts[0], counts[1]) / total
            if conf >= 0.58:
                result = (pred, conf, f"N-gram({n}): {counts[0]}🔴:{counts[1]}🔵 ({total} مرة)")
                _ngram_cache[cache_key] = result
                _ngram_ts = time.time()
                return result
    return None, 0.0, ""

# ════════════════════════════════════════════════════════════════════
# 📏 المحرك الأسطوري 3: ذاكرة الفجوة التاريخية
# ════════════════════════════════════════════════════════════════════
_gap_hist_cache: Dict[str, Tuple] = {}
_gap_hist_ts: float = 0.0

def gap_history_predict(b_gap: Optional[float]) -> Tuple[Optional[int], float, str]:
    global _gap_hist_cache, _gap_hist_ts
    if b_gap is None:
        return None, 0.0, ""
    if b_gap < 50:       gap_range, lo, hi = "nano",   0,    50
    elif b_gap < 200:    gap_range, lo, hi = "tiny",   50,   200
    elif b_gap < 800:    gap_range, lo, hi = "small",  200,  800
    elif b_gap < 3000:   gap_range, lo, hi = "medium", 800,  3000
    elif b_gap < 10000:  gap_range, lo, hi = "large",  3000, 10000
    else:                gap_range, lo, hi = "xlarge", 10000, 9999999
    ck = f"gap_{gap_range}"
    if ck in _gap_hist_cache and time.time() - _gap_hist_ts < 120:
        return _gap_hist_cache[ck]
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT h2.winner
                    FROM history h1
                    JOIN history h2 ON h2.id = h1.id + 1
                    WHERE h1.winner IS NOT NULL AND h2.winner IS NOT NULL
                      AND h1.b_num ~ '^[0-9]+$' AND h2.b_num ~ '^[0-9]+$'
                      AND ABS(h2.b_num::bigint - h1.b_num::bigint) BETWEEN %s AND %s
                    ORDER BY h2.id DESC LIMIT 80
                """, (lo, hi))
                rows = cur.fetchall()
        counts = {0: 0, 1: 0}
        for r in rows:
            w = WINNER_MAP.get(r[0], 2)
            if w in [0, 1]:
                counts[w] += 1
        total = counts[0] + counts[1]
        if total >= 6:
            pred = 0 if counts[0] > counts[1] else 1
            conf = max(counts[0], counts[1]) / total
            if conf >= 0.55:
                result = (pred, conf, f"فجوة-تاريخ {gap_range}({int(b_gap)}): {counts[0]}🔴:{counts[1]}🔵")
                _gap_hist_cache[ck] = result
                _gap_hist_ts = time.time()
                return result
    except Exception:
        pass
    return None, 0.0, ""

# ════════════════════════════════════════════════════════════════════
# ⏳ المحرك الأسطوري 4: كاشف النتيجة المتأخرة (Overdue Detector)
# ════════════════════════════════════════════════════════════════════
def overdue_detector(history: List[int]) -> Tuple[Optional[int], float, str]:
    clean = [x for x in history if x in [0, 1]]
    if len(clean) < 15:
        return None, 0.0, ""
    last_seen = {0: 0, 1: 0}
    for i, v in enumerate(reversed(clean)):
        if v in last_seen and last_seen[v] == 0:
            last_seen[v] = i + 1
        if all(last_seen.values()):
            break
    overdue_0 = last_seen[0]
    overdue_1 = last_seen[1]
    total = len(clean)
    avg_gap = total / max(clean.count(0) + clean.count(1), 1) * 2
    threshold = max(6, avg_gap * 1.5)
    if overdue_0 > threshold and overdue_0 > overdue_1 * 2:
        conf = min(0.80, 0.55 + (overdue_0 - threshold) * 0.02)
        return 0, conf, f"الراعي متأخر {overdue_0} جولة"
    if overdue_1 > threshold and overdue_1 > overdue_0 * 2:
        conf = min(0.80, 0.55 + (overdue_1 - threshold) * 0.02)
        return 1, conf, f"الثور متأخر {overdue_1} جولة"
    return None, 0.0, ""

# ════════════════════════════════════════════════════════════════════
# 🔀 محرك جديد: كاشف ما بعد الانقطاع (Post-Break Predictor)
# ════════════════════════════════════════════════════════════════════
_post_break_cache: Dict[str, Tuple] = {}
_post_break_ts: float = 0.0

def post_break_predict(gap_classify_result: str, b_gap: Optional[float]) -> Tuple[Optional[int], float, str]:
    global _post_break_cache, _post_break_ts
    if gap_classify_result == 'connected':
        return None, 0.0, ""
    cache_key = f"pb_{gap_classify_result}"
    if cache_key in _post_break_cache and time.time() - _post_break_ts < 120:
        return _post_break_cache[cache_key]
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT h2.winner,
                           EXTRACT(EPOCH FROM (h2.created_at - h1.created_at)) AS gap_s
                    FROM history h1
                    JOIN history h2 ON h2.id = h1.id + 1
                    WHERE h1.winner IS NOT NULL AND h2.winner IS NOT NULL
                      AND h1.created_at IS NOT NULL AND h2.created_at IS NOT NULL
                    ORDER BY h2.id DESC LIMIT 400
                """)
                rows = cur.fetchall()
        counts = {0: 0, 1: 0}
        for winner_str, gap_s in rows:
            if gap_s is None:
                continue
            gap_s = float(gap_s)
            if gap_classify_result == 'soft_break':
                if not (SESSION_CONNECTED_SEC < gap_s <= SESSION_SOFT_BREAK_SEC):
                    continue
            else:
                if gap_s <= SESSION_SOFT_BREAK_SEC:
                    continue
            w = WINNER_MAP.get(winner_str, 2)
            if w in [0, 1]:
                counts[w] += 1
        total = counts[0] + counts[1]
        if total >= 8:
            pred = 0 if counts[0] > counts[1] else 1
            conf = max(counts[0], counts[1]) / total
            if conf >= 0.55:
                label = "ناعم" if gap_classify_result == 'soft_break' else "قوي"
                result = (pred, conf,
                          f"ما بعد الانقطاع-{label}: {counts[0]}🔴:{counts[1]}🔵/{total}")
                _post_break_cache[cache_key] = result
                _post_break_ts = time.time()
                return result
    except Exception as e:
        logger.debug(f"post_break_predict: {e}")
    return None, 0.0, ""

# ════════════════════════════════════════════════════════════════════
# 🔢 محرك جديد: عداد السلسلة المتصلة (Session Chain Counter)
# ════════════════════════════════════════════════════════════════════
def session_chain_stats(connected_history: List[int]) -> Tuple[Optional[int], float, str]:
    clean = [x for x in connected_history if x in [0, 1]]
    n = len(clean)
    if n < 4:
        return None, 0.0, ""
    r = clean.count(0)
    b = clean.count(1)
    total = r + b
    if total == 0:
        return None, 0.0, ""
    bias = abs(r - b) / total
    if bias >= 0.30 and total >= 6:
        pred = 0 if r > b else 1
        conf = min(0.68, 0.55 + bias * 0.4)
        dominant = WINNER_NAMES[pred]
        return pred, conf, f"انحياز-جلسة({n} جولة): {r}🔴:{b}🔵 → {dominant}"
    if n >= 6:
        last_half = clean[n//2:]
        first_half = clean[:n//2]
        lh_bias = (last_half.count(1) - last_half.count(0)) / len(last_half)
        fh_bias = (first_half.count(1) - first_half.count(0)) / len(first_half)
        if abs(lh_bias) > abs(fh_bias) + 0.20 and abs(lh_bias) >= 0.35:
            pred = 1 if lh_bias > 0 else 0
            return pred, 0.62, f"تسارع-جلسة: {pred==1 and 'أزرق' or 'أحمر'} يتسارع"
    return None, 0.0, ""

# ════════════════════════════════════════════════════════════════════
# 📐 المحرك الأسطوري 5: معايرة الثقة بالأداء الفعلي
# ════════════════════════════════════════════════════════════════════
def calibrate_confidence(raw_conf: int, scores: Dict[int, float]) -> int:
    total = scores[0] + scores[1]
    if total > 0:
        dominance = abs(scores[0] - scores[1]) / total
    else:
        dominance = 0.0
    overall = _signal_perf.get('OVERALL', [0, 0])
    if overall[1] >= 30:
        real_acc = overall[0] / overall[1]
        if real_acc < 0.48:
            raw_conf = max(55, int(raw_conf * 0.82))
        elif real_acc > 0.67:
            raw_conf = min(97, int(raw_conf * 1.08))
    if dominance > 0.70:
        raw_conf = min(97, raw_conf + 4)
    elif dominance < 0.10:
        raw_conf = max(55, raw_conf - 5)
    return raw_conf

# ════════════════════════════════════════════════════════════════════
# 🎯 محرك v19-1: أنماط EXACT (بذلة+رتبة+رقم مجتمعة)
# ════════════════════════════════════════════════════════════════════
def exact_pattern_predict(suit: str, rank: str, last_digit: int) -> Tuple[Optional[int], float, str]:
    pattern_id = f"EXACT_{suit}_{rank}_{last_digit}"
    res = get_pattern(pattern_id)
    if res['w'] == 2 or res['c'] < 0.05:
        pattern_id2 = f"RANK_{rank}_SUIT_{suit}"
        res2 = get_pattern(pattern_id2)
        if res2['w'] != 2 and res2['c'] > 0.05:
            return res2['w'], res2['c'], f"EXACT≈{pattern_id2} {res2['log']}"
        return None, 0.0, ""
    return res['w'], res['c'], f"EXACT {pattern_id} {res['log']}"

# ════════════════════════════════════════════════════════════════════
# 🧬 محرك v19-2: N-Gram من قاعدة البيانات الكاملة
# ════════════════════════════════════════════════════════════════════
_full_history_cache: List[int] = []
_full_hist_ts: float = 0.0

def get_full_history(n: int = 600) -> List[int]:
    global _full_history_cache, _full_hist_ts
    if _full_history_cache and time.time() - _full_hist_ts < 30:
        return _full_history_cache
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT %s", (n,))
                rows = cur.fetchall()
        hist = [WINNER_MAP.get(r[0], 2) for r in rows]
        hist.reverse()
        _full_history_cache = [x for x in hist if x in [0, 1]]
        _full_hist_ts = time.time()
        return _full_history_cache
    except Exception:
        return []

def deep_ngram_predict(recent: List[int]) -> Tuple[Optional[int], float, str]:
    full = get_full_history(600)
    if len(full) < 20:
        return None, 0.0, ""
    clean_recent = [x for x in recent if x in [0,1]]
    if len(clean_recent) < 3:
        return None, 0.0, ""
    best = (None, 0.0, "")
    for n in [6, 5, 4, 3]:
        if len(clean_recent) < n or len(full) < n + 3:
            continue
        needle = tuple(clean_recent[-n:])
        counts = {0: 0, 1: 0}
        for i in range(len(full) - n - 1):
            if tuple(full[i:i+n]) == needle:
                nxt = full[i+n]
                if nxt in [0,1]:
                    counts[nxt] += 1
        total = counts[0] + counts[1]
        if total >= 4:
            pred = 0 if counts[0] > counts[1] else 1
            conf = max(counts[0], counts[1]) / total
            if conf >= 0.60 and conf > best[1]:
                best = (pred, conf, f"DeepNGram({n}): {counts[0]}🔴:{counts[1]}🔵/{total}")
    return best

# ════════════════════════════════════════════════════════════════════
# ⚡ محرك v19-3: كاشف الانتقال السريع (Hot-Switch Detector)
# ════════════════════════════════════════════════════════════════════
def hot_switch_detector(history: List[int]) -> Tuple[Optional[int], float, str]:
    clean = [x for x in history if x in [0,1]]
    if len(clean) < 8:
        return None, 0.0, ""
    last8 = clean[-8:]
    switches = sum(1 for i in range(1, len(last8)) if last8[i] != last8[i-1])
    if switches >= 6:
        pred = 1 - last8[-1]
        return pred, 0.72, f"تبادل سريع ({switches}/7)"
    elif switches <= 1:
        pred = last8[-1]
        return pred, 0.68, f"ثبات كامل ({8-switches}/7)"
    return None, 0.0, ""

# ════════════════════════════════════════════════════════════════════
# 🧲 محرك v19-4: الجذب التاريخي (Historical Gravity)
# ════════════════════════════════════════════════════════════════════
_gravity_cache: Tuple = (None, 0.0, "")
_gravity_ts: float = 0.0

def historical_gravity() -> Tuple[Optional[int], float, str]:
    global _gravity_cache, _gravity_ts
    if _gravity_cache[0] is not None and time.time() - _gravity_ts < 20:
        return _gravity_cache
    full = get_full_history(300)
    if len(full) < 50:
        return None, 0.0, ""
    windows = [(50, 0.40), (100, 0.35), (200, 0.25)]
    weighted = {0: 0.0, 1: 0.0}
    total_w = 0.0
    for win_size, weight in windows:
        if len(full) < win_size:
            continue
        window = full[-win_size:]
        r = window.count(0); b = window.count(1)
        tot = r + b
        if tot == 0: continue
        dominant = 0 if r > b else 1
        bias = abs(r-b)/tot
        if bias >= 0.05:
            weighted[dominant] += bias * weight
            total_w += weight
    if total_w == 0:
        _gravity_cache = (None, 0.0, "")
        _gravity_ts = time.time()
        return _gravity_cache
    best = 0 if weighted[0] > weighted[1] else 1
    score = max(weighted[0], weighted[1]) / max(total_w, 0.01)
    if score < 0.04:
        _gravity_cache = (None, 0.0, "")
    else:
        conf = min(0.72, 0.52 + score * 3.0)
        _gravity_cache = (best, conf, f"جذب تاريخي={'🔴' if best==0 else '🔵'} s={score:.2f}")
    _gravity_ts = time.time()
    return _gravity_cache

# ════════════════════════════════════════════════════════════════════
# 🏆 محرك v19-5: تصويت الأغلبية الديناميكي (Dynamic Majority Vote)
# ════════════════════════════════════════════════════════════════════
def dynamic_majority_vote(signals: List[Tuple[Optional[int], float, str]]) -> Tuple[Optional[int], float, int, int]:
    votes = {0: 0.0, 1: 0.0}
    n_valid = 0
    for pred, conf, _ in signals:
        if pred in [0, 1]:
            votes[pred] += conf
            n_valid += 1
    if n_valid < 2:
        return None, 0.0, 0, 0
    total_v = votes[0] + votes[1]
    winner = 0 if votes[0] > votes[1] else 1
    conf = max(votes[0], votes[1]) / max(total_v, 0.01)
    agree = sum(1 for p,_,_ in signals if p == winner)
    return winner, conf, agree, n_valid

# ==================== 🔮 محرك التنبؤ الرئيسي ====================
def baccarat_card_counter(history_ranks: List[str]) -> Tuple[Optional[int], float, str]:
    if len(history_ranks) < 10:
        return None, 0.0, ""
    running_count = 0
    for rank in history_ranks:
        r = str(rank).upper().strip()
        if r in ['4', '5', '6']:
            running_count += 2
        elif r in ['8', '9']:
            running_count -= 2
    if running_count >= 6:
        conf = min(0.82, 0.55 + running_count * 0.02)
        return 0, conf, f"عد الأوراق (+{running_count}) → الراعي 🔴"
    elif running_count <= -6:
        conf = min(0.82, 0.55 + abs(running_count) * 0.02)
        return 1, conf, f"عد الأوراق ({running_count}) → الثور 🔵"
    return None, 0.0, ""

def shannon_entropy_sniper(history: List[int]) -> Tuple[bool, float, str]:
    clean = [x for x in history if x in [0, 1]]
    if len(clean) < 12:
        return False, 0.0, ""
    last15  = clean[-15:]
    p_red   = last15.count(0) / len(last15)
    p_blue  = last15.count(1) / len(last15)
    if p_red == 0 or p_blue == 0:
        entropy = 0.0
    else:
        entropy = -(p_red * math.log2(p_red) + p_blue * math.log2(p_blue))
    switches   = sum(1 for i in range(1, len(last15)) if last15[i] != last15[i-1])
    volatility = switches / len(last15)
    if entropy > 0.95 and volatility > 0.65:
        return True, entropy, f"⚠️ فوضى رياضية (entropy={entropy:.2f}, vol={volatility:.2f})"
    return False, entropy, f"استقرار (entropy={entropy:.2f})"

# ==================== 🗝️ دوال إدارة مفاتيح API ====================
async def _get_api_key(service: str) -> Optional[str]:
    """جلب مفتاح API من DB إذا كان ساري المفعول."""
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT api_key, expiry FROM api_keys WHERE service = %s", (service,))
                row = cur.fetchone()
                if not row:
                    return None
                key, expiry = row
                if expiry and datetime.now() > expiry:
                    return None
                return key
    except Exception:
        return None

async def _kimi_analyze(messages: list, timeout: int = 600) -> str:
    """Kimi K2 Thinking — يقرأ البيانات ويطرح النظريات المعقدة."""
    loop = asyncio.get_event_loop()
    key = await _get_api_key('kimi')
    if not key:
        key = "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"  # fallback
        logger.info("Kimi: using hardcoded key (no DB key or expired)")

    def _sync():
        client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=key)
        comp = client.chat.completions.create(
            model="moonshotai/kimi-k2-thinking",
            messages=messages,
            temperature=0.7,
            top_p=0.9,
            max_tokens=16384,
            stream=False,
        )
        text = comp.choices[0].message.content or ""
        return re.sub(r"(?s)<think>.*?</think>", "", text).strip()

    try:
        return await asyncio.wait_for(loop.run_in_executor(None, _sync), timeout=timeout)
    except Exception as e:
        logger.error(f"Kimi error: {e}")
        return f"فشل Kimi: {e}"

async def _minimax_critique(messages: list, timeout: int = 600) -> str:
    """MiniMax M2.5 — ينتقد نظريات Kimi إحصائياً."""
    loop = asyncio.get_event_loop()
    key = await _get_api_key('minimax')
    if not key:
        key = "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"  # fallback
        logger.info("MiniMax: using hardcoded key (no DB key or expired)")

    def _sync():
        client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=key)
        comp = client.chat.completions.create(
            model="minimaxai/minimax-m2.5",
            messages=messages,
            temperature=0.3,
            top_p=0.95,
            max_tokens=8192,
            stream=False,
        )
        return comp.choices[0].message.content or ""

    try:
        return await asyncio.wait_for(loop.run_in_executor(None, _sync), timeout=timeout)
    except Exception as e:
        logger.error(f"MiniMax error: {e}")
        return f"فشل MiniMax: {e}"

# ==================== 🏛️ مجلس القادة (Council of Leaders) ====================
async def run_council_debate(status_callback) -> Dict:
    await status_callback("🏛️ <b>مجلس القادة يجتمع...</b>\n📥 جاري سحب وتجهيز البيانات...")
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, b_num, suit, rank, bonus_last_digit, winner, created_at
                    FROM history WHERE winner IS NOT NULL AND suit IS NOT NULL
                    ORDER BY id ASC
                """)
                rows = cur.fetchall()
    except Exception as e:
        return {"error": str(e)}

    rounds = _filter_valid_rounds(rows)
    memory = _build_math_memory(rounds)

    data_context = (
        f"بيانات تحليلية لـ {len(rounds)} جولة باكرات:\n"
        f"أنماط مؤكدة: {json.dumps(memory['confirmed_patterns'][:30], ensure_ascii=False)}\n"
        f"انتقالات: {json.dumps(memory['transition_stats'], ensure_ascii=False)}\n"
        f"عينة آخر جولات: {json.dumps(memory['raw_sample_last40'][-50:], ensure_ascii=False)}\n"
        f"تعريف: winner=0 الراعي/أحمر, winner=1 الثور/أزرق"
    )

    await status_callback("🌑 <b>Kimi (قائد الرؤية) يتحدث...</b>\nيقرأ البيانات ويبحث عن ارتباطات مخفية معقدة.")
    kimi_resp = await _kimi_analyze([{"role": "user", "content":
        f"أنت عالم بيانات عبقري. حلل بيانات الباكرات وابحث عن تقاطعات معقدة (فجوة + سلسلة + بذلة). "
        f"اطرح 7 نظريات قوية مدعومة بالأرقام.\n{data_context}"
    }])
    if "فشل" in kimi_resp:
        # Kimi فشل → DeepSeek يعمل مباشرة على البيانات
        await status_callback("⚠️ Kimi لم يستجب — DeepSeek سيعمل مباشرة على البيانات.")
        kimi_resp = f"Kimi لم يستجب. اعتمد على البيانات التالية مباشرة:\n{data_context}"

    await status_callback("🌊 <b>MiniMax (قائد التحليل) يتدخل...</b>\nيفحص نظريات Kimi ويمزق الضعيفة.")
    minimax_resp = await _minimax_critique([{"role": "user", "content":
        f"أنت مدقق إحصائي صارم. انتقد هذه النظريات ضد البيانات الحقيقية:\n"
        f"--- نظريات Kimi ---\n{kimi_resp}\n--- البيانات ---\n{data_context}\n"
        f"ارفض النظريات الضعيفة، وصقّل القوية، واكتب تقرير القواعد الناجية."
    }])
    if "فشل" in minimax_resp:
        # MiniMax فشل → نكمل بدونه (DeepSeek يحكم على Kimi مباشرة)
        await status_callback("⚠️ MiniMax لم يستجب — سيكمل DeepSeek بناءً على تحليل Kimi.")
        minimax_resp = "MiniMax لم يستجب. اعتمد على تحليل Kimi مباشرة."

    await status_callback("⚡ <b>DeepSeek (القائد الأعلى) يحكم...</b>\nيصيغ القواعد الذهبية النهائية في JSON.")
    deepseek_prompt = (
        f"أنت القاضي النهائي. حوّل القواعد المتفق عليها إلى JSON:\n"
        f"--- تحليل Kimi:\n{kimi_resp[:2000]}\n"
        f"--- نقد MiniMax:\n{minimax_resp[:2000]}\n"
        f"أنشئ مصفوفة JSON فقط مع شروط: streak, gap_sec_gt/lt, suit. "
        f"prediction:0أو1, confidence:60-78. أعد JSON فقط بلا نص."
    )
    deepseek_text = await _nvidia_chat(
        [{"role": "user", "content": deepseek_prompt}],
        max_tokens=4000, temperature=0.2
    )
    laws_data = extract_json_safe(deepseek_text)
    if not laws_data or not isinstance(laws_data, list):
        return {"error": "فشل DeepSeek في صياغة JSON النهائي."}

    backtest_rows = _fetch_backtest_rows()
    saved = 0
    rejected = 0
    with db_pool.get_conn() as conn:
        with conn.cursor() as cur:
            for law in laws_data:
                if not isinstance(law, dict): continue
                if law.get("prediction") not in [0, 1]: continue
                bt_passes, bt_acc, bt_n = backtest_law(law, backtest_rows)
                if not bt_passes:
                    rejected += 1
                    continue
                cur.execute("""
                    INSERT INTO ai_laws
                        (law_type, conditions, prediction, confidence,
                         accuracy, description, source, times_used)
                    VALUES (%s, %s, %s, %s, %s, %s, 'COUNCIL_DEBATE', %s)
                """, (
                    law.get("law_type", "COUNCIL_RULE"),
                    json.dumps(law.get("conditions", {}), ensure_ascii=False),
                    int(law["prediction"]),
                    float(law.get("confidence", 75)),
                    round(bt_acc * 100, 1),
                    f"{law.get('description','')} [Council BT:{bt_acc:.0%}]",
                    bt_n,
                ))
                saved += 1
        conn.commit()

    load_laws(force=True)
    return {
        "saved": saved, "rejected": rejected,
        "kimi_summary": kimi_resp[:300] + "...",
        "minimax_summary": minimax_resp[:300] + "...",
    }

# ==================== 💎 تعدين القواعد الذهبية ====================
def _run_golden_miner_sync() -> str:
    MIN_OCCURRENCES = 12
    MIN_WIN_RATE    = 0.78
    MAX_LAWS_TO_ADD = 15

    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        h.id, h.b_num, h.suit, h.rank, h.winner,
                        ABS(h.b_num::bigint - LAG(h.b_num::bigint) OVER (ORDER BY h.id)) AS b_gap,
                        EXTRACT(EPOCH FROM (h.created_at - LAG(h.created_at) OVER (ORDER BY h.id))) AS gap_sec
                    FROM history h
                    WHERE h.winner IS NOT NULL AND h.rank IS NOT NULL AND h.rank != 'NULL'
                      AND h.b_num ~ '^[0-9]+$'
                    ORDER BY h.id ASC
                """)
                rows = cur.fetchall()

        if len(rows) < 100:
            return "بيانات غير كافية للتعدين."

        patterns: Dict = defaultdict(lambda: {0: 0, 1: 0})

        for r in rows:
            rid, b_num, suit, rank, winner_str, b_gap, gap_sec = r
            winner = 0 if 'الراعي' in str(winner_str) else (1 if 'الثور' in str(winner_str) else 2)
            if winner == 2:
                continue

            clean_b   = clean_digits(b_num)
            last_digit = int(clean_b[-1]) if clean_b else 0

            conditions = []
            if suit:  conditions.append(("suit", suit))
            if rank:  conditions.append(("rank", rank))
            if rank in ['J', 'Q', 'K']:
                conditions.append(("rank_family", "face"))
            conditions.append(("digit_parity", "even" if last_digit % 2 == 0 else "odd"))
            if gap_sec is not None:
                if gap_sec < 15:   conditions.append(("gap_sec_lt", 15))
                elif gap_sec > 45: conditions.append(("gap_sec_gt", 45))
            if b_gap is not None:
                if b_gap < 500:    conditions.append(("b_gap_lt", 500))
                elif b_gap > 3000: conditions.append(("b_gap_gt", 3000))

            for size in [2, 3]:
                for combo in itertools.combinations(conditions, size):
                    patterns[tuple(sorted(combo))][winner] += 1

        golden_rules = []
        for combo_key, outcomes in patterns.items():
            red, blue = outcomes[0], outcomes[1]
            total = red + blue
            if total < MIN_OCCURRENCES:
                continue
            if red / total >= MIN_WIN_RATE:
                golden_rules.append((combo_key, 0, red / total, total))
            elif blue / total >= MIN_WIN_RATE:
                golden_rules.append((combo_key, 1, blue / total, total))

        golden_rules.sort(key=lambda x: (x[2], x[3]), reverse=True)
        top_rules = golden_rules[:MAX_LAWS_TO_ADD]

        injected = 0
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ai_laws WHERE source = 'GOLDEN_MINER'")
                for combo_key, prediction, win_rate, total_plays in top_rules:
                    cond_dict  = {k: v for k, v in combo_key}
                    confidence = int(win_rate * 100)
                    winner_name = WINNER_NAMES.get(prediction, "?")
                    desc = (f"قاعدة ذهبية: {confidence}% من {total_plays} جولة → {winner_name}")
                    cur.execute("""
                        INSERT INTO ai_laws
                            (law_name, law_type, conditions, prediction, confidence,
                             accuracy, description, source, times_used)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'GOLDEN_MINER', %s)
                    """, (
                        f"GOLDEN_{injected}_{int(time.time())}",
                        "golden_intersection",
                        json.dumps(cond_dict, ensure_ascii=False),
                        prediction,
                        confidence - 5,
                        float(confidence),
                        desc,
                        total_plays,
                    ))
                    injected += 1
                conn.commit()

        load_laws(force=True)
        return f"💎 تم! اكتشاف وحقن {injected} قاعدة ذهبية من أصل {len(golden_rules)} مكتشفة."

    except Exception as e:
        logger.error(f"Golden Miner Error: {e}", exc_info=True)
        return f"❌ خطأ: {e}"

# ==================== أوامر إدارة مفاتيح API ====================
async def cmd_set_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين مفتاح API لخدمة Kimi أو MiniMax مع صلاحية محددة."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "⚠️ الاستخدام: <code>/set_key &lt;service&gt; &lt;key&gt; [duration]</code>\n"
            "مثال: <code>/set_key kimi sk-xxx 1d</code> (صلاحية يوم)\n"
            "الخدمات: kimi, minimax\n"
            "duration: 30m, 1h, 1d, 1w (افتراضي 7 أيام)",
            parse_mode="HTML"
        )
        return

    service = args[0].lower()
    api_key = args[1]
    duration_str = args[2] if len(args) > 2 else "7d"

    if service not in ['kimi', 'minimax']:
        await update.message.reply_text("❌ الخدمة غير معروفة. اختر kimi أو minimax.")
        return

    import re
    match = re.match(r"(\d+)([mhd])", duration_str)
    if not match:
        await update.message.reply_text("❌ صيغة المدة غير صالحة. استخدم مثل: 30m, 1h, 1d, 1w")
        return
    num, unit = int(match[1]), match[2]
    if unit == 'm':
        minutes = num
    elif unit == 'h':
        minutes = num * 60
    elif unit == 'd':
        minutes = num * 1440
    elif unit == 'w':
        minutes = num * 10080
    else:
        minutes = 10080

    expiry = datetime.now() + timedelta(minutes=minutes)

    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO api_keys (service, api_key, expiry, set_by)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (service) DO UPDATE
                        SET api_key = EXCLUDED.api_key,
                            expiry = EXCLUDED.expiry,
                            set_by = EXCLUDED.set_by,
                            created_at = CURRENT_TIMESTAMP
                """, (service, api_key, expiry, update.effective_user.id))
                conn.commit()
        await update.message.reply_text(
            f"✅ تم تعيين مفتاح {service.upper()} بنجاح.\n"
            f"⏳ ينتهي في {expiry.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def cmd_get_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض مفتاح API (مشفر) وصلاحيته."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ استخدم: <code>/get_key &lt;service&gt;</code>", parse_mode="HTML")
        return
    service = args[0].lower()
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT api_key, expiry FROM api_keys WHERE service = %s", (service,))
                row = cur.fetchone()
                if not row:
                    await update.message.reply_text(f"⚠️ لا يوجد مفتاح مسجل للخدمة {service}.")
                    return
                key, expiry = row
                masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
                expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S") if expiry else "غير محدد"
                await update.message.reply_text(
                    f"🔑 مفتاح {service.upper()}: <code>{masked}</code>\n"
                    f"⏳ ينتهي: {expiry_str}",
                    parse_mode="HTML"
                )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def cmd_revoke_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء مفتاح API (حذفه)."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ استخدم: <code>/revoke_key &lt;service&gt;</code>", parse_mode="HTML")
        return
    service = args[0].lower()
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM api_keys WHERE service = %s", (service,))
                conn.commit()
        await update.message.reply_text(f"✅ تم حذف مفتاح {service.upper()}.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


# ==================== 🔐 نظام الاشتراكات ====================

PLANS = {
    "30m":  ("30 دقيقة",   30),
    "1d":   ("يوم واحد",   1440),
    "1w":   ("أسبوع",      10080),
    "1mo":  ("شهر",        43200),
    "life": ("مدى الحياة", None),
}

async def check_subscription(user_id: int):
    """التحقق من اشتراك المستخدم. يعيد (مسموح, رسالة)."""
    if user_id == ADMIN_ID:
        return True, ""
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT plan, expiry FROM subscriptions WHERE user_id = %s",
                    (user_id,)
                )
                row = cur.fetchone()
                if not row:
                    return False, (
                        "🔒 <b>ليس لديك اشتراك نشط</b>\n"
                        "تواصل مع المشرف للحصول على اشتراك.\n\n"
                        "📋 الخطط المتاحة:\n"
                        "  • 30 دقيقة تجريبية\n"
                        "  • يوم  |  أسبوع  |  شهر"
                    )
                plan, expiry = row
                if plan == "life":
                    return True, ""
                if expiry and datetime.now() > expiry:
                    return False, (
                        f"⏰ <b>انتهى اشتراكك</b> (خطة: {plan})\n"
                        "تواصل مع المشرف للتجديد."
                    )
                if expiry:
                    delta = expiry - datetime.now()
                    total_sec = int(delta.total_seconds())
                    if total_sec < 3600:
                        remaining = f"{total_sec // 60} دقيقة"
                    elif total_sec < 86400:
                        remaining = f"{total_sec // 3600} ساعة"
                    else:
                        remaining = f"{total_sec // 86400} يوم"
                    return True, f"⏳ متبقي: {remaining}"
                return True, ""
    except Exception as e:
        logger.error(f"check_subscription: {e}")
        return False, "❌ خطأ في التحقق من الاشتراك."

async def cmd_add_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة / تجديد اشتراك مستخدم. للأدمن فقط."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    args = context.args or []
    if len(args) < 2:
        plans_list = "\n".join(f"  • {k} — {v[0]}" for k, v in PLANS.items())
        await update.message.reply_text(
            "⚠️ الاستخدام: <code>/add_sub &lt;user_id&gt; &lt;plan&gt;</code>\n\n"
            f"الخطط المتاحة:\n{plans_list}\n\n"
            "مثال: <code>/add_sub 123456789 1w</code>",
            parse_mode="HTML"
        )
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id يجب أن يكون رقماً.")
        return
    plan_key = args[1].lower()
    if plan_key not in PLANS:
        await update.message.reply_text(
            f"❌ خطة غير معروفة. الخطط: {', '.join(PLANS.keys())}"
        )
        return
    plan_label, minutes = PLANS[plan_key]
    expiry = None if minutes is None else datetime.now() + timedelta(minutes=minutes)
    username = None
    try:
        chat = await context.bot.get_chat(target_id)
        username = chat.username or chat.full_name
    except Exception:
        pass
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO subscriptions (user_id, username, plan, expiry, granted_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id) DO UPDATE
                        SET plan       = EXCLUDED.plan,
                            expiry     = EXCLUDED.expiry,
                            granted_by = EXCLUDED.granted_by,
                            username   = COALESCE(EXCLUDED.username, subscriptions.username),
                            updated_at = NOW()
                """, (target_id, username, plan_key, expiry, update.effective_user.id))
                conn.commit()
        expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S") if expiry else "مدى الحياة ♾️"
        await update.message.reply_text(
            f"✅ <b>تم منح الاشتراك</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 المستخدم: <code>{target_id}</code>"
            + (f" (@{username})" if username else "") + "\n"
            f"📋 الخطة: <b>{plan_label}</b>\n"
            f"⏳ ينتهي: <b>{expiry_str}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"🎉 <b>تم تفعيل اشتراكك!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📋 الخطة: <b>{plan_label}</b>\n"
                    f"⏳ ينتهي: <b>{expiry_str}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"اضغط /start للبدء 🚀"
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def cmd_revoke_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء اشتراك مستخدم. للأدمن فقط."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "⚠️ استخدم: <code>/revoke_sub &lt;user_id&gt;</code>",
            parse_mode="HTML"
        )
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id يجب أن يكون رقماً.")
        return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM subscriptions WHERE user_id = %s", (target_id,))
                deleted = cur.rowcount
                conn.commit()
        if deleted:
            await update.message.reply_text(
                f"✅ تم إلغاء اشتراك المستخدم <code>{target_id}</code>.", parse_mode="HTML"
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="⚠️ <b>تم إلغاء اشتراكك.</b>\nتواصل مع المشرف للتجديد.",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        else:
            await update.message.reply_text(
                f"⚠️ لا يوجد اشتراك للمستخدم <code>{target_id}</code>.", parse_mode="HTML"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def cmd_list_subs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة المشتركين. للأدمن فقط."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT user_id, username, plan, expiry, created_at
                    FROM subscriptions
                    ORDER BY created_at DESC LIMIT 30
                """)
                rows = cur.fetchall()
        if not rows:
            await update.message.reply_text("📋 لا يوجد مشتركون بعد.")
            return
        now = datetime.now()
        lines = ["📋 <b>قائمة المشتركين</b>\n━━━━━━━━━━━━━━━━━━━━"]
        active_count = 0
        expired_count = 0
        for uid, uname, plan, expiry, created_at in rows:
            plan_label = PLANS.get(plan, (plan,))[0]
            if plan == "life":
                status = "♾️ مدى الحياة"
                active_count += 1
            elif expiry and now > expiry:
                status = "❌ منتهي"
                expired_count += 1
            else:
                if expiry:
                    delta = expiry - now
                    h = int(delta.total_seconds() // 3600)
                    status = f"✅ {h}س" if h < 48 else f"✅ {h//24}ي"
                else:
                    status = "✅ نشط"
                active_count += 1
            name_str = f"@{uname}" if uname else f"id:{uid}"
            lines.append(f"👤 <code>{uid}</code> {name_str}\n   {plan_label} | {status}")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━\n✅ نشط: {active_count}  |  ❌ منتهي: {expired_count}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def cmd_my_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض للمستخدم حالة اشتراكه."""
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👑 <b>أنت المشرف — وصول مفتوح مدى الحياة.</b>", parse_mode="HTML"
        )
        return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT plan, expiry, created_at FROM subscriptions WHERE user_id = %s",
                    (user_id,)
                )
                row = cur.fetchone()
        if not row:
            await update.message.reply_text(
                "🔒 <b>ليس لديك اشتراك نشط.</b>\nتواصل مع المشرف للاشتراك.",
                parse_mode="HTML"
            )
            return
        plan, expiry, created_at = row
        plan_label = PLANS.get(plan, (plan,))[0]
        if plan == "life":
            status = "♾️ مدى الحياة"
        elif expiry and datetime.now() > expiry:
            status = "❌ منتهي"
        else:
            if expiry:
                delta = expiry - datetime.now()
                total_sec = int(delta.total_seconds())
                if total_sec < 3600:
                    status = f"✅ متبقي {total_sec // 60} دقيقة"
                elif total_sec < 86400:
                    status = f"✅ متبقي {total_sec // 3600} ساعة"
                else:
                    status = f"✅ متبقي {total_sec // 86400} يوم"
            else:
                status = "✅ نشط"
        expiry_str = expiry.strftime("%Y-%m-%d %H:%M") if expiry else "بلا انتهاء"
        await update.message.reply_text(
            f"📋 <b>اشتراكك</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 الخطة: <b>{plan_label}</b>\n"
            f"⏳ الحالة: <b>{status}</b>\n"
            f"📅 ينتهي: <b>{expiry_str}</b>\n"
            f"🗓️ تاريخ الاشتراك: {created_at.strftime('%Y-%m-%d') if created_at else '?'}\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== أوامر البوت ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ── التحقق من الاشتراك ────────────────────────────────────────
    allowed, sub_msg = await check_subscription(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(sub_msg, parse_mode="HTML")
        return
    # ─────────────────────────────────────────────────────────────
    laws_count = len(load_laws())
    active_data_laws = len([l for l in DATA_LAWS if l.get("active")])
    await update.message.reply_text(
        f"<b>🧠 HADES V19 — نظام التنبؤ الأسطوري</b>\n"
        f"{'━'*24}\n"
        f"⚙️ <b>المحركات النشطة: 19</b>\n"
        f"  ⚖️ قوانين AI: <b>{laws_count}</b>  |  📊 قوانين بيانات: <b>{active_data_laws}</b>\n"
        f"  🔗 ماركوف-جلسة  |  🔄 دورات  |  🧬 DeepNGram\n"
        f"  🕰️ ارتباط زمني  |  🎯 EXACT  |  🏆 أغلبية\n"
        f"  ⚡ Hot-Switch  |  🧲 جذب تاريخي  |  ⏳ متأخر\n"
        f"  🔀 ما بعد الانقطاع  |  🔢 إحصاءات السلسلة\n"
        f"  ⏱️ حد الاتصال: <b>17 ث</b>  |  كسر ناعم: 17-90 ث\n"
        f"{'━'*24}\n"
        f"📋 <b>الأوامر:</b>\n"
        f"  🎮 /start — بدء جولة جديدة\n"
        f"  📊 /stats — لوحة الإحصاءات الحية\n"
        f"  ⚖️ /laws  — عرض القوانين النشطة\n"
        f"  📥 /download — تصدير قاعدة البيانات\n"
        f"  🔬 /force_learn — تعلم عميق (مشرف)\n"
        f"  ✂️ /prune — تنظيف القوانين الميتة (مشرف)\n"
        f"  🔄 /reset_laws — إعادة تعيين (مشرف)\n"
        f"  ⛏️ /mine_gold — تعدين القواعد الذهبية (مشرف)\n"
        f"  🏛️ /council_learn — مجلس القادة (مشرف)\n"
        f"  🔑 /set_key — تعيين مفتاح API (مشرف)\n"
        f"  🔑 /get_key — عرض مفتاح API (مشرف)\n"
        f"  🔑 /revoke_key — إلغاء مفتاح API (مشرف)\n"
        f"{'━'*24}\n"
        f"👥 <b>إدارة المشتركين (مشرف):</b>\n"
        f"  ➕ /add_sub — منح اشتراك\n"
        f"  ➖ /revoke_sub — إلغاء اشتراك\n"
        f"  📋 /list_subs — قائمة المشتركين\n"
        f"  ℹ️ /my_sub — حالة اشتراكي\n"
        f"{'━'*24}\n"
        f"🎴 اختر البذلة للبدء:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(SUITS[i], callback_data=f"suit_{i}")
            for i in range(len(SUITS))
        ]])
    )

async def cmd_force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    msg = await update.message.reply_text(
        "🧠 <b>بدء جلسة التعلم العميق...</b>\n"
        "سيتم تحليل كل الجولات السابقة واستخراج قوانين ذكية.\n"
        "<i>لا تُلغِ العملية — قد تستغرق عدة دقائق.</i>",
        parse_mode="HTML"
    )
    async def status_update(text: str):
        try: await msg.edit_text(text, parse_mode="HTML")
        except Exception: pass
    result = await force_learn_engine(status_update)
    if "error" in result:
        await msg.edit_text(f"❌ <b>فشلت جلسة التعلم</b>\n\n<code>{result['error']}</code>", parse_mode="HTML")
        return
    sample_text = ""
    for i, law in enumerate(result.get("sample_laws", []), 1):
        pred_name = WINNER_NAMES.get(law.get("prediction",2),"?")
        sample_text += f"\n<b>{i}.</b> [{law.get('law_type','?')}] → {pred_name} ({law.get('confidence',0):.0f}%)\n   <i>{law.get('description','')[:80]}</i>"
    await msg.edit_text(
        f"✅ <b>اكتملت جلسة التعلم العميق!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎮 الجولات المحللة: <b>{result['total_rounds']}</b>\n"
        f"🔬 Backtest على: <b>{result.get('backtest_rows',0)}</b> جولة حقيقية\n"
        f"✅ قوانين نجحت: <b>{result['laws_saved']}</b>\n"
        f"❌ مرفوضة (backtest): <b>{result.get('laws_rejected',0)}</b>\n"
        f"⏭️ غير صالحة: <b>{result['laws_skipped']}</b>\n"
        f"🆔 رقم الجلسة: <b>#{result.get('session_id','?')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>عينة من القوانين المكتشفة:</b>{sample_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 الذاكرة السياقية تم تحديثها.",
        parse_mode="HTML"
    )

async def cmd_engine_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    anti_active, recent_acc = check_anti_mode()
    regime_str = "غير محدد"
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 20")
                hist = [WINNER_MAP.get(r[0],2) for r in cur.fetchall()]
                hist.reverse()
        regime, reg_conf = detect_regime([x for x in hist if x in [0,1]])
        regime_labels = {
            "banker_streak":  "🔴 سيطرة الراعي",
            "player_streak":  "🔵 سيطرة الثور",
            "alternating":    "🔁 تبادل منتظم",
            "chaotic":        "❓ فوضى — لا نمط"
        }
        regime_str = f"{regime_labels.get(regime, regime)} ({reg_conf:.0%})"
    except Exception:
        pass

    sig_lines = []
    for name, vals in sorted(_signal_perf.items()):
        if vals[1] >= 3:
            acc = vals[0] / vals[1]
            bar = "█" * int(acc * 10) + "░" * (10 - int(acc * 10))
            sig_lines.append(f"  <code>{name:<12}</code> [{bar}] {acc:.0%} ({int(vals[1])} جولة)")
    sig_text = "\n".join(sig_lines) if sig_lines else "  لا بيانات بعد — العب جولات ليُسجَّل الأداء"

    laws = load_laws()
    active_laws = len(laws)

    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ <b>حالة المحركات — HADES V19</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📈 <b>الدقة الحالية (آخر 15):</b> {recent_acc:.0%}\n"
        f"{'🔃 <b>وضع الانعكاس نشط!</b>' if anti_active else '✅ وضع عادي'}\n\n"
        f"🧠 <b>نظام اللعبة الحالي:</b>\n  {regime_str}\n\n"
        f"⚖️ <b>القوانين الذكية النشطة:</b> {active_laws}\n\n"
        f"📊 <b>أداء الإشارات (تكيّفي):</b>\n{sig_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 المحركات: Lookalike • Regime • Bayesian • Anti-Mode\n"
        f"  + Markov-Session • PostBreak • ChainStats\n"
        f"  + Cycle • Streak • MemShort • SuitBias • Laws\n"
        f"  ⏱️ حد الاتصال: 17ث | كسر ناعم: 17-90ث | كسر قوي: >90ث"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def cmd_laws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = update.effective_user.id == ADMIN_ID
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, law_type, prediction, confidence, accuracy, times_used, description FROM ai_laws WHERE active = TRUE ORDER BY accuracy DESC, times_used DESC LIMIT 25")
                all_active = cur.fetchall()
    except Exception:
        all_active = []
    if not all_active:
        await update.message.reply_text("⚠️ لا توجد قوانين نشطة. استخدم /force_learn أولاً.")
        return
    text = f"⚖️ <b>القوانين النشطة ({len(all_active)})</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"
    buttons = []
    for row in all_active[:20]:
        lid, ltype, lpred, lconf, lacc, lused, ldesc = row
        pred_name = WINNER_NAMES.get(lpred,"?")
        pred_icon = "🔴" if lpred==0 else "🔵"
        text += f"\n<b>#{lid}</b> {pred_icon} [{ltype}] → {pred_name}\n  دقة: {lacc:.0f}% | conf: {lconf:.0f}% | ×{lused}\n  <i>{html.escape(str(ldesc or ''))[:65]}</i>\n"
        if is_admin:
            buttons.append([InlineKeyboardButton(f"🗑️ حذف #{lid} [{ltype[:20]}]", callback_data=f"deact_law_{lid}")])
    if len(all_active) > 20:
        text += f"\n<i>... و{len(all_active)-20} قانون إضافي — استخدم /prune للتنظيف</i>"
    kb = InlineKeyboardMarkup(buttons) if buttons else None
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)

async def cmd_deactivate_law(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("⚠️ استخدم: <code>/deactivate &lt;id&gt;</code>", parse_mode="HTML")
        return
    try:
        law_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ الـ ID يجب أن يكون رقماً.")
        return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT law_type, prediction, accuracy, times_used FROM ai_laws WHERE id = %s", (law_id,))
                row = cur.fetchone()
                if not row:
                    await update.message.reply_text(f"⚠️ لا يوجد قانون بالـ ID {law_id}")
                    return
                ltype, lpred, lacc, lused = row
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE id = %s", (law_id,))
                conn.commit()
        load_laws(force=True)
        pred_name = WINNER_NAMES.get(lpred,"?")
        await update.message.reply_text(
            f"✅ <b>تم تعطيل القانون #{law_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 النوع: [{ltype}] → {pred_name}\n"
            f"📊 الدقة: {lacc:.0f}% | الاستخدام: {lused}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔄 الذاكرة النشطة تم تحديثها.",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ جارٍ تحميل الإحصاءات...")
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM history WHERE rank IS NOT NULL AND rank NOT IN ('NULL','')")
                total = cur.fetchone()[0]
                cur.execute("SELECT winner, COUNT(*) FROM history WHERE winner IS NOT NULL AND rank IS NOT NULL AND rank NOT IN ('NULL','') GROUP BY winner")
                dist = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute("""
                    SELECT
                        SUM(CASE WHEN winner = CASE prediction WHEN 0 THEN 'الراعي 🔴' WHEN 1 THEN 'الثور 🔵' END THEN 1 ELSE 0 END) AS correct,
                        COUNT(*) AS total
                    FROM history
                    WHERE winner IS NOT NULL
                      AND prediction IN (0,1)
                      AND winner IN ('الراعي 🔴','الثور 🔵')
                      AND rank IS NOT NULL AND rank NOT IN ('NULL','')
                """)
                acc_r2 = cur.fetchone()
                correct_cnt = int(acc_r2[0] or 0)
                predicted_total = int(acc_r2[1] or 1)
                cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                laws_cnt = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = FALSE")
                inactive_cnt = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*), MAX(created_at) FROM learn_sessions")
                ls = cur.fetchone()
                sessions_cnt, last_learn_time = ls
                cur.execute("SELECT winner, prediction FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 15")
                last15 = cur.fetchall()
                cur.execute("SELECT signal_name, correct_count, total_count FROM signal_performance WHERE total_count >= 5 ORDER BY (correct_count::float/total_count) DESC LIMIT 5")
                sig_rows = cur.fetchall()
        r_cnt = dist.get("الراعي 🔴",0)
        b_cnt = dist.get("الثور 🔵",0)
        t_cnt = dist.get("تعادل ⚪",0)
        played = max(r_cnt + b_cnt, 1)
        acc = round(correct_cnt/max(predicted_total,1)*100,1)
        last_l = last_learn_time.strftime("%Y-%m-%d %H:%M") if last_learn_time else "لم يُجرَ"
        streak_str = ""
        for row in last15:
            w = WINNER_MAP.get(row[0],2)
            p = WINNER_MAP.get(row[1],2) if row[1] else -1
            streak_str += ("✅" if w==p else ("⬜" if p==-1 else "❌"))
        sig_txt = ""
        for sig in sig_rows:
            sn, sc, st = sig
            sa = round(sc/max(st,1)*100)
            sig_txt += f"  {sn}: {sa}%\n"
        perf = "🏆" if acc>=65 else ("✅" if acc>=55 else "⚠️")
        msg_text = (
            f"<b>🧠 HADES الإحصاءات</b>\n{'━'*20}\n"
            f"🎮 {total} جولة  |  {perf} دقة: <b>{acc}%</b>\n"
            f"🔴{r_cnt}  🔵{b_cnt}  ⚪{t_cnt}\n"
            f"آخر 15: <code>{streak_str}</code>\n{'━'*20}\n"
            f"⚖️ قوانين: <b>{laws_cnt}</b> نشط / {inactive_cnt} معطّل\n"
            f"📚 جلسات تعلم: <b>{sessions_cnt}</b>  |  آخر: <b>{last_l}</b>\n"
            + (f"{'━'*20}\n📡 أفضل محركات:\n{sig_txt}" if sig_txt else "")
            + f"{'━'*20}"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit"),
                                     InlineKeyboardButton("🔄 تحديث", callback_data="stats")]])
        await msg.edit_text(msg_text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

async def cmd_prune(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    msg = await update.message.reply_text("✂️ جارٍ تنظيف القوانين الميتة...")
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE times_used = 0 AND created_at < NOW() - INTERVAL '12 hours' AND active = TRUE")
                dead_by_usage = cur.rowcount
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE accuracy < 40 AND times_used >= 50 AND active = TRUE")
                dead_by_acc = cur.rowcount
                cur.execute("""
                    WITH ranked AS (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY conditions::text ORDER BY accuracy DESC, times_used DESC) as rn
                        FROM ai_laws WHERE active = TRUE
                    )
                    UPDATE ai_laws SET active = FALSE WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
                """)
                dead_dupes = cur.rowcount
                conn.commit()
                cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                remaining = cur.fetchone()[0]
        load_laws(force=True)
        await msg.edit_text(
            f"✅ <b>تنظيف اكتمل</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💤 لم تُستخدم قط:   <b>{dead_by_usage}</b>\n"
            f"📉 دقة ضعيفة (&lt;30%): <b>{dead_by_acc}</b>\n"
            f"♻️ مكررة:            <b>{dead_dupes}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚖️ القوانين الباقية: <b>{remaining}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

async def cmd_reset_bias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تصفير الانحياز الإحصائي: يُعطّل القوانين + يُعيد حساب DIGIT weights."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    args = context.args or []
    if 'confirm' not in args:
        await update.message.reply_text(
            "⚠️ هذا سيُصفّر الانحياز للأزرق!\nللتأكيد: <code>/reset_bias confirm</code>",
            parse_mode="HTML"
        )
        return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE ai_laws SET active = FALSE")
                laws_disabled = cur.rowcount
                cur.execute("UPDATE pattern_stats SET blue_count = GREATEST(0, blue_count - (blue_count - red_count) / 2) WHERE pattern_id = 'DIGIT_0' AND blue_count > red_count + 5")
                digit0_fixed = cur.rowcount
                cur.execute("UPDATE pattern_stats SET blue_count = GREATEST(0, blue_count - (blue_count - red_count) / 3) WHERE pattern_id LIKE 'SD_%_0' AND blue_count > red_count + 8")
                sd_fixed = cur.rowcount
                conn.commit()
        live_cache.cache.clear()
        global _markov_cache, _full_history_cache, _gravity_cache, _session_markov_cache
        _markov_cache = None; _session_markov_cache = None
        _full_history_cache = []; _gravity_cache = (None, 0.0, "")
        load_laws(force=True)
        await update.message.reply_text(f"✅ <b>تم تصفير الانحياز!</b>\nقوانين مُعطَّلة: {laws_disabled}\nالآن شغّل /force_learn", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

async def cmd_reset_laws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    args = context.args or []
    if 'confirm' not in args:
        await update.message.reply_text("⚠️ هذا سيُعطّل جميع القوانين!\nللتأكيد اكتب: <code>/reset_laws confirm</code>", parse_mode="HTML")
        return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE ai_laws SET active = FALSE")
                n = cur.rowcount
                conn.commit()
        load_laws(force=True)
        await update.message.reply_text(f"✅ تم تعطيل <b>{n}</b> قانون.\nالآن شغّل /force_learn", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")
async def cmd_mine_gold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    msg = await update.message.reply_text("⛏️ <b>جاري تعدين البيانات...</b>\nيبحث في التقاطعات المعقدة دون استخدام AI.", parse_mode="HTML")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_golden_miner_sync)
    await msg.edit_text(f"<b>نتائج التعدين:</b>\n{result}", parse_mode="HTML")

async def cmd_council_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    msg = await update.message.reply_text("🏛️ <b>تم استدعاء مجلس القادة...</b>\nالحوار قد يستغرق 5-15 دقيقة.", parse_mode="HTML")
    async def status_update(text: str):
        try: await msg.edit_text(text, parse_mode="HTML")
        except Exception: pass
    result = await run_council_debate(status_update)
    if "error" in result:
        await msg.edit_text(f"❌ <b>فشلت المحاكمة</b>\n\n<code>{result['error'][:300]}</code>", parse_mode="HTML")
        return
    await msg.edit_text(
        f"✅ <b>انتهى اجتماع مجلس القادة!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚖️ القوانين المعتمدة: <b>{result['saved']}</b>\n"
        f"🗑️ المرفوضة: <b>{result['rejected']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 تم دمج حكمة 3 نماذج AI. البوت جاهز للعمل بالقوانين الجديدة.",
        parse_mode="HTML"
    )

async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at
                    FROM history
                    WHERE rank IS NOT NULL AND rank NOT IN ('NULL','') AND suit IS NOT NULL
                    ORDER BY id DESC LIMIT 1
                """)
                row = cur.fetchone()
                if not row:
                    cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at FROM history ORDER BY id DESC LIMIT 1")
                    row = cur.fetchone()
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")
        return
    if not row:
        await update.message.reply_text("⚠️ لا توجد جولات مسجّلة.")
        return
    rid, bnum, suit, rank, digit, winner_str, pred_str, created_at = row
    t = created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else "?"
    icon = {"الراعي 🔴":"🔴","الثور 🔵":"🔵","تعادل ⚪":"⚪"}.get(winner_str or "", "?")
    if isinstance(pred_str, int):
        pred_display = WINNER_NAMES.get(pred_str, str(pred_str))
    else:
        pred_display = pred_str or "NULL"
    correct = ""
    if pred_str is not None and winner_str:
        pred_int = WINNER_MAP.get(pred_str, pred_str) if isinstance(pred_str, str) else pred_str
        win_int = WINNER_MAP.get(winner_str, -1)
        correct = " ✅" if pred_int == win_int else " ❌"
    await update.message.reply_text(
        f"🕐 <b>آخر جولة مسجّلة</b>\n{'━'*22}\n🆔 ID: <code>{rid}</code>  |  🕐 {t}\n🔑 B_NUM: <code>{bnum}</code>\n🃏 {suit or '?'} {rank or '?'}  |  🔢 آخر رقم: <b>{digit}</b>\n🏆 النتيجة: <b>{winner_str} {icon}</b>\n🎯 التوقع: {pred_display}{correct}\n{'━'*22}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑️ حذف هذه الجولة", callback_data=f"del_confirm_{rid}"),
            InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit")
        ]])
    )

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    bnum_input = clean_digits(args[0]) if args else ""
    found_rows = []
    if bnum_input:
        try:
            with db_pool.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id
                        FROM history
                        WHERE TRIM(b_num::text) = %s ORDER BY id DESC LIMIT 3
                    """, (bnum_input,))
                    found_rows = cur.fetchall()
                    if not found_rows:
                        cur.execute("""
                            SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id
                            FROM history
                            WHERE b_num::text LIKE %s ORDER BY id DESC LIMIT 3
                        """, (f"%{bnum_input}%",))
                        found_rows = cur.fetchall()
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")
            return
    if len(found_rows) == 1:
        r = found_rows[0]
        rid, bnum, suit, rank, digit, winner_str, pred_str, created_at, _ = r
        t = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "?"
        icon = {"الراعي 🔴":"🔴","الثور 🔵":"🔵","تعادل ⚪":"⚪"}.get(winner_str or "", "?")
        await update.message.reply_text(
            f"🗑️ <b>تأكيد الحذف</b>\n{'━'*22}\n🔑 B_NUM: <code>{bnum}</code>\n🃏 {suit or '?'} {rank or '?'}  |  🔢 آخر رقم: <b>{digit}</b>\n🏆 {winner_str} {icon}  |  التوقع: {pred_str or 'NULL'}\n🕐 {t}\n{'━'*22}\nهل تريد حذف هذه الجولة؟",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ نعم احذف", callback_data=f"del_confirm_{rid}"),
                InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel")
            ]])
        )
        return
    display_rows = found_rows if len(found_rows) > 1 else await _fetch_last_rounds(8)
    if not display_rows:
        await update.message.reply_text("⚠️ لا توجد جولات مسجّلة في قاعدة البيانات.")
        return
    header = f"🔍 نتائج البحث عن <code>{bnum_input}</code> — اختر جولة:" if found_rows else "🗑️ <b>اختر الجولة التي تريد حذفها</b> — آخر 8 جولات مسجّلة"
    buttons = [[InlineKeyboardButton(_row_btn_label(row), callback_data=f"del_confirm_{row[0]}")] for row in display_rows]
    buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel")])
    await update.message.reply_text(header, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def cmd_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    msg = await update.message.reply_text("⏳ جارٍ تجميع البيانات...")
    try:
        from datetime import datetime as _dt
        import io
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        filename = f"hades_db_{_dt.now().strftime('%Y%m%d_%H%M%S')}.txt"
        lines = []
        def sec(title: str):
            lines.append(""); lines.append("╔"+"═"*58+"╗"); lines.append(f"║  {title:<56}║"); lines.append("╚"+"═"*58+"╝")
        lines.append("╔"+"═"*58+"╗")
        lines.append("║"+" "*15+"HADES V19 — DB EXPORT"+" "*20+"║")
        lines.append(f"║  Generated : {now_str:<44}║")
        lines.append("╚"+"═"*58+"╝")
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                sec("SUMMARY")
                counts = {}
                for tbl in ["history","pattern_stats","ai_laws","learn_sessions"]:
                    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                    counts[tbl] = cur.fetchone()[0]
                cur.execute("""
                    SELECT SUM(CASE WHEN winner = CASE prediction::text WHEN '0' THEN 'الراعي 🔴' WHEN '1' THEN 'الثور 🔵' END THEN 1 ELSE 0 END) AS correct,
                           COUNT(*) AS total
                    FROM history
                    WHERE winner IS NOT NULL AND prediction IN (0,1) AND winner IN ('الراعي 🔴','الثور 🔵') AND rank IS NOT NULL AND rank NOT IN ('NULL','')
                """)
                row2 = cur.fetchone()
                correct = int(row2[0] or 0); played = int(row2[1] or 1); acc = round(correct/played*100,1)
                cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                active_laws = cur.fetchone()[0]
                lines.append(f"  History rows   : {counts['history']}")
                lines.append(f"  Pattern stats  : {counts['pattern_stats']}")
                lines.append(f"  AI Laws total  : {counts['ai_laws']}  (active: {active_laws})")
                lines.append(f"  Learn sessions : {counts['learn_sessions']}")
                lines.append(f"  Prediction acc : {acc}%  ({correct}/{played} non-tie predicted)")
                sec("PATTERN_STATS")
                cur.execute("SELECT pattern_id, pattern_type, red_count, blue_count, tie_count FROM pattern_stats ORDER BY pattern_type, pattern_id")
                lines.append(f"  {'PATTERN_ID':<25} {'TYPE':<8} {'RED':>6} {'BLUE':>6} {'TIE':>5}  BIAS%")
                lines.append("  " + "-"*56)
                for r in cur.fetchall():
                    red = float(r[2] or 0); blue = float(r[3] or 0); tie = float(r[4] or 0); tot = red+blue+tie
                    bias = round((blue-red)/max(tot,1)*100,1)
                    arrow = "→🔵" if bias>5 else ("→🔴" if bias<-5 else "  =")
                    lines.append(f"  {_safe(r[0]):<25} {_safe(r[1]):<8} {red:>6.0f} {blue:>6.0f} {tie:>5.0f}  {bias:+.1f}% {arrow}")
                sec("AI_LAWS  (sorted by accuracy DESC)")
                cur.execute("SELECT id, law_name, law_type, conditions, prediction, confidence, accuracy, times_used, description, active FROM ai_laws ORDER BY accuracy DESC, confidence DESC")
                rows_laws = cur.fetchall()
                lines.append(f"  {'ID':>4}  {'TYPE':<28} {'PRED':<10} {'CONF':>5} {'ACC':>5} {'USED':>5}  ACT")
                lines.append("  " + "-"*70)
                for r in rows_laws:
                    pred_name = "🔴 Banker" if r[4]==0 else ("🔵 Player" if r[4]==1 else "?")
                    conf = float(r[5]) if r[5] is not None else 0.0
                    acc = float(r[6]) if r[6] is not None else 0.0
                    used = int(r[7]) if r[7] is not None else 0
                    active_flag = "✅" if r[9] else "❌"
                    lines.append(f"  {_safe(r[0]):>4}  {_safe(r[2]):<28} {pred_name:<10} {conf:>4.0f}% {acc:>4.0f}% {used:>5}  {active_flag}")
                    if r[3]:
                        cond_str = str(r[3]) if not isinstance(r[3],str) else r[3]
                        lines.append(f"       CONDITIONS: {cond_str[:90]}")
                    if r[8]:
                        lines.append(f"       DESC      : {_safe(r[8])[:90]}")
                    lines.append("")
                sec("LEARN_SESSIONS")
                cur.execute("SELECT id, rounds_used, laws_created, laws_updated, summary, created_at FROM learn_sessions ORDER BY id DESC")
                for r in cur.fetchall():
                    lines.append(f"  #{_safe(r[0])}  [{_safe(r[5])}]  rounds={_safe(r[1])}  laws_new={_safe(r[2])}  laws_upd={_safe(r[3])}")
                    if r[4]:
                        lines.append(f"     {_safe(r[4])[:80]}")
                sec("HISTORY  (all rows, ASC)")
                cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at FROM history ORDER BY id ASC")
                lines.append(f"  {'ID':>6}  {'B_NUM':<12} {'SUIT':<5} {'RANK':<5} {'DIG':>3}  {'WINNER':<14} {'PRED':<14}  CREATED_AT")
                lines.append("  " + "-"*85)
                for r in cur.fetchall():
                    lines.append(f"  {_safe(r[0]):>6}  {_safe(r[1]):<12} {_safe(r[2]):<5} {_safe(r[3]):<5} {_safe(r[4]):>3}  {_safe(r[5]):<14} {_safe(r[6]):<14}  {_safe(r[7])}")
        lines.append(""); lines.append("╔"+"═"*58+"╗"); lines.append(f"║  END OF EXPORT — {len(lines)} lines{' '*(40-len(str(len(lines))))}║"); lines.append("╚"+"═"*58+"╝")
        content_txt = "\n".join(lines)
        file_bytes = io.BytesIO(content_txt.encode("utf-8"))
        file_bytes.name = filename
        h_count = counts.get("history",0)
        l_count = counts.get("ai_laws",0)
        await msg.delete()
        await update.message.reply_document(
            document=file_bytes, filename=filename,
            caption=f"<b>HADES DB Export</b>\n<code>{now_str}</code>\nHistory: <b>{h_count}</b> | Laws: <b>{l_count}</b> | Acc: <b>{acc}%</b>\n<i>{len(lines)} lines</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        try: await msg.edit_text(f"❌ خطأ في التصدير:<code>{e}</code>", parse_mode="HTML")
        except Exception: pass

# ==================== دوال مساعدة للحذف ====================
def _row_btn_label(row) -> str:
    rid, bnum, suit, rank, digit, winner_str, pred_str, created_at, _ = row
    t = created_at.strftime("%d/%m %H:%M") if created_at else "?"
    icon = {"الراعي 🔴":"🔴","الثور 🔵":"🔵","تعادل ⚪":"⚪"}.get(winner_str or "", "?")
    ok = " ✅" if (pred_str and winner_str and pred_str==winner_str) else (" ❌" if pred_str else "")
    return f"{bnum} | {suit or '?'}{rank or '?'} {icon}{ok} | {t}"

_delete_row_label = _row_btn_label

async def _fetch_last_rounds(n: int = 8):
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id
                    FROM history
                    WHERE rank IS NOT NULL AND rank NOT IN ('NULL','') AND suit IS NOT NULL
                    ORDER BY id DESC LIMIT %s
                """, (n,))
                rows = cur.fetchall()
                if not rows:
                    cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id FROM history ORDER BY id DESC LIMIT %s", (n,))
                    rows = cur.fetchall()
                return rows
    except Exception as e:
        logger.error(f"_fetch_last_rounds: {e}")
        return []

async def _exec_delete(rid: int, bnum, suit, rank, digit, winner_str: str, pred_str, created_at) -> dict:
    result = {"rolled_back":0, "laws_adjusted":0, "error":None}
    try:
        winner_int = WINNER_MAP.get(winner_str,2)
        digit_int = int(digit) if digit is not None else 0
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM history WHERE id = %s", (rid,))
                col = {0:"red_count",1:"blue_count",2:"tie_count"}.get(winner_int)
                if col and suit and rank:
                    for pid in [f"SUIT_{suit}", f"DIGIT_{digit_int}", f"RANK_{rank}", f"SD_{suit}_{digit_int}"]:
                        cur.execute(f"UPDATE pattern_stats SET {col} = GREATEST(0, {col}-1) WHERE pattern_id = %s", (pid,))
                        result["rolled_back"] += cur.rowcount
                        live_cache.cache.pop(pid, None)
                conn.commit()
        for law in load_laws():
            if match_law(law, suit or "", str(rank or ""), digit_int, []) >= 0.5:
                try:
                    was_ok = (law["prediction"] == winner_int)
                    restored = max(0.0, min(100.0, (law["accuracy"] - 0.10*(100.0 if was_ok else 0.0))/0.90))
                    with db_pool.get_conn() as c2:
                        with c2.cursor() as cx:
                            cx.execute("UPDATE ai_laws SET accuracy=%s, times_used=GREATEST(0,times_used-1) WHERE id=%s", (restored, law["id"]))
                            c2.commit()
                    result["laws_adjusted"] += 1
                except Exception:
                    pass
        live_cache.cache.clear()
        global _markov_cache, _full_history_cache, _gravity_cache, _session_markov_cache, _post_break_cache
        _markov_cache = None; _session_markov_cache = None; _post_break_cache = {}
        _full_history_cache = []; _gravity_cache = (None,0.0,"")
        load_laws(force=True)
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"_exec_delete: {e}", exc_info=True)
    return result

# ==================== معالجات الأزرار والرسائل ====================
async def safe_edit(query, text: str, reply_markup=None):
    from telegram.error import BadRequest
    try: await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error(f"safe_edit: {e}")
    except Exception as e:
        logger.error(f"safe_edit: {e}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try: await query.answer()
    except Exception: pass
    data = query.data
    logger.info(f"CB [{query.from_user.id}]: {data!r}")
    try:
        if data in ("choose_suit", "new_connected", "new_disconnected"):
            context.user_data.pop('suit', None); context.user_data.pop('rank', None)
            context.user_data.pop('session_mode', None)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(SUITS[i], callback_data=f"suit_{i}") for i in range(len(SUITS))]])
            await safe_edit(query, "🎴 اختر البذلة:", reply_markup=kb)
        elif data.startswith("suit_"):
            idx = int(data.split("_")[1])
            suit = SUITS[idx]
            context.user_data['suit'] = suit; context.user_data['suit_idx'] = idx
            rows = [[InlineKeyboardButton(r, callback_data=f"rank_{r}") for r in row] for row in RANKS_LAYOUT]
            rows.append([InlineKeyboardButton("🔙 تغيير البذلة", callback_data="choose_suit")])
            await safe_edit(query, f"البذلة: <b>{suit}</b>\nاختر الرتبة:", reply_markup=InlineKeyboardMarkup(rows))
        elif data.startswith("rank_"):
            rank = data[5:]; suit = context.user_data.get('suit','?'); suit_idx = context.user_data.get('suit_idx',0)
            context.user_data['rank'] = rank
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 تغيير الرتبة", callback_data=f"suit_{suit_idx}")]])
            await safe_edit(query, f"✅ البذلة: <b>{suit}</b>  |  الرتبة: <b>{rank}</b>\n\n📩 أرسل رقم البونص (مثال: <code>7022088</code>)", reply_markup=kb)
        elif data.startswith("save_"):
            parts = data.split("_",2)
            winner = int(parts[1])
            b_num = parts[2] if len(parts)>2 else context.user_data.get('last_b_num','')
            suit = context.user_data.get('suit',''); rank = context.user_data.get('rank','')
            pred = context.user_data.get('last_pred',2)
            if not (b_num and suit and rank):
                await safe_edit(query, "❌ بيانات ناقصة — اضغط /start")
                return
            last_digit = get_last_digit(b_num)
            correct = (winner == pred)
            saved_id = None; save_error = None
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        winner_int = int(winner) if isinstance(winner,int) and winner in [0,1,2] else WINNER_MAP.get(winner,0)
                        if isinstance(pred,int) and pred in [0,1,2]: pred_int = pred
                        elif isinstance(pred,str): pred_int = WINNER_MAP.get(pred, None)
                        else: pred_int = None
                        winner_text = WINNER_NAMES.get(winner_int, WINNER_NAMES.get(winner, "تعادل ⚪"))
                        try:
                            # منع تكرار نفس الجولة
                            cur.execute("SELECT id FROM history WHERE b_num=%s AND suit=%s AND created_at>=NOW()-INTERVAL '2 minutes' LIMIT 1", (b_num, suit))
                            _dup = cur.fetchone()
                            if _dup:
                                saved_id = _dup[0]
                                logger.info(f"Duplicate skipped: {b_num}/{suit}")
                            else:
                                cur.execute("""
                                    INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, prediction, user_id, "timestamp", created_at)
                                    VALUES (%s, %s, %s, %s, %s, %s::integer, %s, NOW(), NOW()) RETURNING id
                                """, (b_num, suit, rank, last_digit, winner_text, pred_int, query.from_user.id))
                                _r = cur.fetchone()
                                if not _dup: saved_id = _r[0] if _r else None
                        except Exception:
                            conn.rollback()
                            cur.execute("""
                                INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, prediction, user_id, created_at)
                                VALUES (%s, %s, %s, %s, %s, %s::integer, %s, NOW()) RETURNING id
                            """, (b_num, suit, rank, last_digit, winner_text, pred_int, query.from_user.id))
                        row = cur.fetchone()
                        saved_id = row[0] if row else None
                        conn.commit()
                        context.user_data['last_saved_id'] = saved_id
                        context.user_data['last_saved_bnum'] = b_num
                        context.user_data['last_saved_time'] = time.time()
                        logger.info(f"✅ Saved round id={saved_id} b_num={b_num}")
            except Exception as e:
                save_error = str(e)
                logger.error(f"Save FAILED: {e}", exc_info=True)
            update_pattern_db(suit, rank, last_digit, winner)
            laws = load_laws()
            recent_hist: List[int] = []
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 20")
                        recent_hist = [WINNER_MAP.get(r[0],2) for r in cur.fetchall()]; recent_hist.reverse()
            except Exception: pass
            for law in laws:
                if match_law(law, suit, rank, last_digit, recent_hist) >= 0.5:
                    update_law_accuracy(law["id"], law["prediction"] == winner)
            pred_signal = context.user_data.get('last_signals', {})
            for sig_name, sig_pred in pred_signal.items():
                if sig_pred in [0,1]:
                    update_signal_perf(sig_name, sig_pred == winner)
            save_signal_perf_to_db()
            auto_manage_laws()
            if save_error:
                await safe_edit(query, f"⚠️ <b>فشل حفظ الجولة!</b>\n<code>{save_error[:300]}</code>\n\nاضغط /start وأعد إدخال الجولة.", reply_markup=None)
                return
            verdict = "<b>صحيح! 🎯</b>" if correct else "خاطئ ❌"
            icon = "✅" if correct else "❌"
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT winner, prediction FROM history WHERE winner IS NOT NULL AND prediction IS NOT NULL ORDER BY id DESC LIMIT 20")
                        recent_results = cur.fetchall()
                def _is_correct(w,p):
                    if p is None: return False
                    expected = {"الراعي 🔴":0,"الثور 🔵":1,"تعادل ⚪":2}
                    return expected.get(w,-1) == int(p)
                recent_acc = sum(1 for r in recent_results if _is_correct(r[0],r[1])) / max(len(recent_results),1)
                streak_disp = "".join("✅" if _is_correct(r[0],r[1]) else "❌" for r in recent_results[:10])
                acc_txt = f"\n📈 دقة آخر 20: <b>{recent_acc:.0%}</b>  <code>{streak_disp}</code>"
            except Exception:
                acc_txt = ""
            _uid2 = query.from_user.id if query.from_user else 0
            if _uid2 == ADMIN_ID:
                buttons = [[InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")],
                            [InlineKeyboardButton("📊 إحصاءات",    callback_data="stats")]]
                if saved_id:
                    buttons.append([InlineKeyboardButton(f"🗑️ حذف هذه الجولة (#{saved_id})", callback_data=f"del_confirm_{saved_id}")])
            else:
                buttons = [[InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")]]
                if saved_id:
                    buttons.append([InlineKeyboardButton(f"🗑️ حذف هذه الجولة (#{saved_id})", callback_data=f"del_confirm_{saved_id}")])
            save_note = ""
            if save_error: save_note = f"\n⚠️ <b>خطأ في الحفظ:</b> <code>{save_error[:120]}</code>"
            elif saved_id: save_note = f"\n💾 محفوظة  ID: <code>{saved_id}</code>"
            await safe_edit(query, f"{icon} <b>{WINNER_NAMES[winner]}</b>  ({verdict})\nالتوقع: {WINNER_NAMES.get(pred,'?')}  |  {suit} {rank}  |  #{b_num}{acc_txt}{save_note}", reply_markup=InlineKeyboardMarkup(buttons))
        elif data == "stats":
            await safe_edit(query, "⏳ جارٍ تحميل الإحصاءات...")
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT COUNT(*) FROM history"); total = cur.fetchone()[0]
                        cur.execute("SELECT winner, COUNT(*) FROM history WHERE winner IS NOT NULL GROUP BY winner"); dist = {r[0]:r[1] for r in cur.fetchall()}
                        cur.execute("""
                            SELECT SUM(CASE WHEN winner = CASE prediction::text WHEN '0' THEN 'الراعي 🔴' WHEN '1' THEN 'الثور 🔵' END THEN 1 ELSE 0 END) AS correct,
                                   COUNT(*) AS total
                            FROM history
                            WHERE winner IS NOT NULL AND prediction IN (0,1) AND winner IN ('الراعي 🔴','الثور 🔵') AND rank IS NOT NULL AND rank NOT IN ('NULL','')
                        """)
                        acc_r2 = cur.fetchone()
                        correct_cnt = int(acc_r2[0] or 0); predicted_total = int(acc_r2[1] or 1)
                        cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE"); laws_cnt = cur.fetchone()[0]
                        cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = FALSE"); inactive_cnt = cur.fetchone()[0]
                        cur.execute("SELECT COUNT(*), MAX(created_at) FROM learn_sessions"); ls = cur.fetchone()
                        sessions_cnt, last_learn_time = ls
                        cur.execute("SELECT winner, prediction FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 15"); last15 = cur.fetchall()
                        cur.execute("SELECT signal_name, correct_count, total_count FROM signal_performance WHERE total_count >= 5 ORDER BY (correct_count::float/total_count) DESC LIMIT 5"); sig_rows = cur.fetchall()
                r_cnt = dist.get("الراعي 🔴",0); b_cnt = dist.get("الثور 🔵",0); t_cnt = dist.get("تعادل ⚪",0); played = max(r_cnt+b_cnt,1)
                acc = round(correct_cnt/max(predicted_total,1)*100,1)
                last_l = last_learn_time.strftime("%Y-%m-%d %H:%M") if last_learn_time else "لم يُجرَ"
                streak_str = ""
                for row in last15:
                    w = WINNER_MAP.get(row[0],2); p = WINNER_MAP.get(row[1],2) if row[1] else -1
                    streak_str += ("✅" if w==p else ("⬜" if p==-1 else "❌"))
                sig_txt = ""
                for sig in sig_rows:
                    sn,sc,st = sig; sa = round(sc/max(st,1)*100); sig_txt += f"  {sn}: {sa}%\n"
                perf = "🏆" if acc>=65 else ("✅" if acc>=55 else "⚠️")
                msg_text = (
                    f"<b>🧠 HADES الإحصاءات</b>\n{'━'*20}\n"
                    f"🎮 {total} جولة  |  {perf} دقة: <b>{acc}%</b>\n"
                    f"🔴{r_cnt}  🔵{b_cnt}  ⚪{t_cnt}\n"
                    f"آخر 15: <code>{streak_str}</code>\n{'━'*20}\n"
                    f"⚖️ قوانين: <b>{laws_cnt}</b> نشط / {inactive_cnt} معطّل\n"
                    f"📚 جلسات تعلم: <b>{sessions_cnt}</b>  |  آخر: <b>{last_l}</b>\n"
                    + (f"{'━'*20}\n📡 أفضل محركات:\n{sig_txt}" if sig_txt else "")
                    + f"{'━'*20}"
                )
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit"), InlineKeyboardButton("🔄 تحديث", callback_data="stats")]])
                await safe_edit(query, msg_text, reply_markup=kb)
            except Exception as e:
                await safe_edit(query, f"❌ خطأ: <code>{e}</code>")
        elif data.startswith("del_confirm_"):
            target_id = int(data.split("_")[2])
            await safe_edit(query, "⏳ جارٍ الحذف...", reply_markup=None)
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id FROM history WHERE id = %s", (target_id,))
                        r = cur.fetchone()
                if not r:
                    await safe_edit(query, f"⚠️ لا توجد جولة بالـ ID {target_id}.")
                    return
                _, bnum, suit, rank, digit, winner_str, pred_str, created_at, _ = r
                t = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "?"
                res = await _exec_delete(target_id, bnum, suit, rank, digit, winner_str, pred_str, created_at)
                if res["error"]:
                    await safe_edit(query, f"❌ خطأ: <code>{res['error']}</code>")
                else:
                    await safe_edit(
                        query,
                        f"✅ <b>تم الحذف — كأن الجولة لم تحدث</b>\n{'━'*22}\n🔑 B_NUM: <code>{bnum}</code>  |  🕐 {t}\n🃏 {suit or '?'} {rank or '?'}  |  🏆 {winner_str}\n{'━'*22}\n♻️ rollback: <b>{res['rolled_back']}</b> نمط  |  ⚖️ <b>{res['laws_adjusted']}</b> قانون",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ حذف أخرى", callback_data="del_list"), InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")]])
                    )
            except Exception as e:
                await safe_edit(query, f"❌ خطأ: <code>{e}</code>")
        elif data == "del_list":
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id
                            FROM history
                            WHERE rank IS NOT NULL AND rank != 'NULL' AND suit IS NOT NULL
                            ORDER BY created_at DESC, id DESC LIMIT 8
                        """)
                        rows = cur.fetchall()
                if not rows:
                    await safe_edit(query, "⚠️ لا توجد جولات.")
                    return
                buttons = [[InlineKeyboardButton(_delete_row_label(r), callback_data=f"del_confirm_{r[0]}")] for r in rows]
                buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel")])
                await safe_edit(query, "🗑️ <b>اختر الجولة للحذف:</b>", reply_markup=InlineKeyboardMarkup(buttons))
            except Exception as e:
                await safe_edit(query, f"❌ خطأ: <code>{e}</code>")
        elif data == "del_cancel":
            await safe_edit(query, "✅ تم الإلغاء.")
        elif data.startswith("deact_law_"):
            if query.from_user.id != ADMIN_ID:
                await safe_edit(query, "⛔ للمشرف فقط.")
                return
            try:
                law_id = int(data.split("_")[2])
            except (IndexError, ValueError):
                await safe_edit(query, "❌ بيانات غير صالحة.")
                return
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT law_type, prediction, accuracy FROM ai_laws WHERE id = %s", (law_id,))
                        row = cur.fetchone()
                        if not row:
                            await safe_edit(query, f"⚠️ لا يوجد قانون #{law_id}")
                            return
                        ltype, lpred, lacc = row
                        cur.execute("UPDATE ai_laws SET active = FALSE WHERE id = %s", (law_id,))
                        conn.commit()
                load_laws(force=True)
                pred_name = WINNER_NAMES.get(lpred,"?")
                pred_icon = "🔴" if lpred==0 else "🔵"
                await safe_edit(query, f"🗑️ <b>تم تعطيل القانون #{law_id}</b>\n[{ltype}] → {pred_icon} {pred_name}\nدقة: {lacc:.0f}%\n\n✅ الذاكرة تم تحديثها.")
            except Exception as e:
                await safe_edit(query, f"❌ خطأ: <code>{e}</code>")
        elif data == "del_more":
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id
                            FROM history
                            WHERE rank IS NOT NULL AND rank != 'NULL' AND suit IS NOT NULL
                            ORDER BY id DESC LIMIT 5
                        """)
                        rows = cur.fetchall()
                        if not rows:
                            cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id FROM history ORDER BY id DESC LIMIT 5")
                            rows = cur.fetchall()
                if not rows:
                    await safe_edit(query, "⚠️ لا توجد جولات إضافية.")
                    return
                buttons = [[InlineKeyboardButton(_delete_row_label(row), callback_data=f"del_confirm_{row[0]}")] for row in rows]
                buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel")])
                await safe_edit(query, "🗑️ <b>اختر الجولة التي تريد حذفها:</b>", reply_markup=InlineKeyboardMarkup(buttons))
            except Exception as e:
                await safe_edit(query, f"❌ خطأ: <code>{e}</code>")
        else:
            logger.warning(f"Unhandled callback: {data!r}")
    except Exception as e:
        logger.error(f"callback_handler crash [{data}]: {e}", exc_info=True)
        try: await safe_edit(query, f"⚠️ خطأ: <code>{str(e)[:200]}</code>")
        except Exception: pass


async def predict(b_num: str, suit: str, rank: str, session_mode: str = 'auto') -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b:
        return 2, 0, "❌ رقم بونص غير صالح"

    last_digit  = int(clean_b[-1])
    scores: Dict[int, float] = {0: 0.0, 1: 0.0}
    logs:   List[str]        = []

    # تهيئة متغيرات الإشارات الجديدة لمنع UnboundLocalError
    pb_pred: Optional[int] = None
    pb_conf: float = 0.0
    pb_log:  str   = ""
    sc_pred: Optional[int] = None
    sc_conf: float = 0.0
    sc_log:  str   = ""
    connected_rows: List = []   # للـ Card Counter

    # ── تاريخ حديث + فجوة b_num الأخيرة ────────────────────────────
    recent_history: List[int] = []
    all_history:    List[int] = []
    b_gap:   Optional[float] = None
    gap_sec: Optional[float] = None
    round_index: int = 0
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                # جلب آخر 40 جولة مع الوقت لتحديد الجلسة الحالية
                cur.execute("""
                    SELECT winner, b_num, created_at
                    FROM history
                    WHERE winner IS NOT NULL
                      AND rank IS NOT NULL AND rank NOT IN ('NULL','')
                    ORDER BY id DESC LIMIT 40
                """)
                rows = cur.fetchall()
                if rows:
                    # فجوة رقم البونص مع آخر جولة
                    last_b = clean_digits(str(rows[0][1] or ""))
                    if last_b and clean_b:
                        try:
                            b_gap = abs(int(clean_b) - int(last_b))
                        except Exception:
                            pass
                    # فجوة زمنية
                    if rows[0][2]:
                        gap_sec = (datetime.now() - rows[0][2]).total_seconds()

                    # ── تحديد الجولات المتسلسلة فقط ──────────────────
                    # القاعدة: gap_sec ≤ 17 ث = متصل، أكثر = انقطاع
                    connected_rows = [rows[0]]  # أحدث جولة دائماً تُضاف
                    for i in range(1, len(rows)):
                        t_curr = rows[i-1][2]
                        t_prev = rows[i][2]
                        if t_curr and t_prev:
                            dt = (t_curr - t_prev).total_seconds()
                            if dt > SESSION_CONNECTED_SEC:
                                break  # انقطاع — نوقف السلسلة
                        # b_gap لا يكسر الجلسة — في هذه اللعبة b_gap كبير دائماً (97%>500)
                        connected_rows.append(rows[i])

                    # recent_history = الجولات المتصلة بالجلسة الحالية (مرتبة تصاعدياً)
                    connected_rows.reverse()
                    recent_history = [WINNER_MAP.get(r[0], 2) for r in connected_rows]

                    # للمحركات التي تحتاج تاريخاً أطول نُرفق الكل (تنازلياً)
                    all_history = [WINNER_MAP.get(r[0], 2) for r in rows]
                    all_history.reverse()

                    # موضع الجولة + unix timestamp للـ ts_mod conditions
                    cur.execute("SELECT COUNT(*) FROM history WHERE winner IS NOT NULL")
                    round_index = int(time.time())  # unix timestamp للـ ts_mod
                else:
                    all_history = []
                    connected_rows = []
    except Exception as e:
        logger.warning(f"History fetch: {e}")

    # ── تحديد حالة الجلسة الدقيقة (3 مستويات) ──────────────────────
    # بناءً على gap_sec بين الجولة الحالية وآخر جولة مسجّلة
    # ── تطبيق session_mode (اختيار المستخدم: متصلة/منقطعة) ────────────
    if session_mode == 'connected':
        gap_sec = 12.0           # متصلة: ضمن السلسلة
    elif session_mode == 'disconnected':
        gap_sec = 9999.0         # منقطعة: hard break
        recent_history = []      # مسح الذاكرة القصيرة — لا نبني على ما قبل الانقطاع
        connected_rows = []      # مسح الجولات المتصلة

    session_type  = gap_classify(gap_sec)   # 'connected' / 'soft_break' / 'hard_break'
    is_new_session = session_type != 'connected'
    seq_weight     = seq_weight_from_gap(gap_sec)
    chain_length   = len(recent_history)    # عدد الجولات في السلسلة الحالية

    # ── حماية gap_sec من None ──
    gap_str = f"{gap_sec:.0f}" if gap_sec is not None else "?"
    SESSION_LABELS = {
        'connected':  f"🟢 متصلة ({chain_length} جولة)",
        'soft_break': f"🟡 كسر ناعم ({gap_str}ث)",
        'hard_break': f"🔴 جلسة جديدة ({gap_str}ث)" if gap_sec is not None else "🔴 بداية",
    }
    if b_gap is not None:
        logs.append(f"🔗 b_gap={int(b_gap)} | ⏱️ {gap_str}ث | {SESSION_LABELS[session_type]} | seq_w={seq_weight}")
    elif gap_sec is not None:
        logs.append(f"⏱️ فجوة: {gap_str}ث | {SESSION_LABELS[session_type]}")

    # ── AI متوازٍ ────────────────────────────────────────────────────
    ai_task = asyncio.create_task(ai_predict(all_history[-20:] if all_history else recent_history))

    # ── 1. القوانين الذكية (الذاكرة السياقية) ──────────────────────
    law_scores, law_logs = apply_laws(
        suit, rank, last_digit, recent_history,
        b_num=clean_b, b_gap=b_gap, gap_sec=gap_sec, round_index=round_index
    )
    for k in [0, 1]:
        scores[k] += law_scores[k]
    logs.extend(law_logs)

    # ── 2. الزخم ──────────────────────────────────────────────────
    mom_pred, mom_conf, mom_log = detect_momentum()
    if mom_pred is not None:
        scores[mom_pred] += mom_conf * WEIGHTS['MOMENTUM']
        logs.append(f"⏱️ الزخم: {WINNER_NAMES[mom_pred]} ({mom_log})")

    # ── 3. الأنماط الإحصائية ────────────────────────────────────────
    pattern_map = [
        (f"SD_{suit}_{last_digit}", 'SD',    '✨ بذلة+رقم'),
        (f"SUIT_{suit}",            'SUIT',  '🎴 البذلة'),
        (f"DIGIT_{last_digit}",     'DIGIT', '🔢 الرقم'),
        (f"RANK_{rank}",            'RANK',  '🃏 الرتبة'),
    ]
    for pid, wkey, desc in pattern_map:
        res = get_pattern(pid)
        if res['w'] != 2 and res['c'] > 0.0:
            # ✅ DIGIT وزن أضعف بكثير لكسر الانحياز للأزرق
            w_factor = 0.3 if wkey == 'DIGIT' else (0.8 if wkey == 'RANK' else 1.0)
            scores[res['w']] += res['c'] * WEIGHTS[wkey] * w_factor
            logs.append(f"{desc}: {WINNER_NAMES[res['w']]} {res['log']}")

    # ── 4. نتيجة AI الآني ───────────────────────────────────────────
    try:
        ai_pred, ai_conf, ai_log = await asyncio.wait_for(ai_task, timeout=0.8)
        if ai_pred in [0, 1]:
            scores[ai_pred] += (ai_conf / 100) * WEIGHTS['AI']
            logs.append(f"🤖 Qwen: {WINNER_NAMES[ai_pred]} — {ai_log}")
        else:
            logs.append(f"⚠️ Qwen: {ai_log}")
    except asyncio.TimeoutError:
        logs.append("⚠️ Qwen: لم يكتمل في الوقت المحدد")
    except Exception:
        logs.append("⚠️ Qwen: خطأ")

    # ── T1: كاشف الزخم الحقيقي ─────────────────────────────────────
    streak_pred, streak_conf = detect_real_streak(recent_history)
    if streak_pred is not None and not is_new_session:
        w = get_adaptive_weight('STREAK', WEIGHTS['MOMENTUM'])
        scores[streak_pred] += streak_conf * w
        logs.append(f"⚡ كسر سلسلة: {WINNER_NAMES[streak_pred]} ({streak_conf:.0%}) w={w:.1f}")
    elif streak_pred is not None:
        logs.append(f"⚡ كسر سلسلة (معطّل — جلسة جديدة)")

    # ── T2: الذاكرة القصيرة ──────────────────────────────────────────
    mem_pred, mem_conf = short_memory_bias(recent_history)
    if mem_pred is not None:
        w = get_adaptive_weight('SHORT_MEM', 1.4) * seq_weight
        scores[mem_pred] += mem_conf * w
        logs.append(f"🧠 ذاكرة قصيرة: {WINNER_NAMES[mem_pred]} ({mem_conf:.0%}) {'⚠️ جديدة' if is_new_session else ''}")

    # ── T3: انحياز البذلة الذكي ──────────────────────────────────────
    sb_pred, sb_conf = suit_bias_from_history(suit)
    if sb_pred is not None:
        w = get_adaptive_weight('SUIT_BIAS', 1.6)
        scores[sb_pred] += sb_conf * w
        logs.append(f"📊 انحياز البذلة: {WINNER_NAMES[sb_pred]} ({sb_conf:.0%})")

    # ── M1: ماركوف ───────────────────────────────────────────────────
    # يستخدم الجلسة المتصلة أولاً، ثم الماركوف العام كاحتياط
    _markov_src = recent_history if len(recent_history) >= 4 else all_history
    mkv_pred, mkv_conf, mkv_log = markov_predict(_markov_src, session_history=recent_history)
    if mkv_pred is not None:
        w = get_adaptive_weight('MARKOV', 2.5) * seq_weight
        scores[mkv_pred] += mkv_conf * w
        logs.append(f"🔗 {mkv_log} → {WINNER_NAMES[mkv_pred]} ({mkv_conf:.0%}) w={w:.1f} {'⚠️ جلسة جديدة' if is_new_session else ''}")

    # ── M2: كاشف الدورات ─────────────────────────────────────────────
    cyc_pred, cyc_conf, cyc_log = detect_cycle(recent_history if len(recent_history) >= 6 else all_history)
    if cyc_pred is not None:
        w = get_adaptive_weight('CYCLE', 2.0)
        scores[cyc_pred] += cyc_conf * w
        logs.append(f"🔄 {cyc_log} → {WINNER_NAMES[cyc_pred]} ({cyc_conf:.0%})")

    # ── M3: بصمة b_num متعددة الأبعاد ───────────────────────────────
    fp_signals = bnum_fingerprint(clean_b, rank)
    active_signals = 0
    for fp_pred, fp_w, fp_label in fp_signals:
        if fp_pred in [0, 1]:
            scores[fp_pred] += fp_w
            active_signals  += 1
    if active_signals > 0:
        # اجمع في سطر واحد
        fp_summary = " | ".join(
            f"{WINNER_NAMES[p][0]}{l}"
            for p, w, l in fp_signals if p in [0, 1]
        )
        logs.append(f"🧮 بصمة رقمية ({active_signals}): {fp_summary}")

    # ── T6: قانون مجموع الأرقام + prime ─────────────────────────────
    digit_sum = sum(int(d) for d in clean_b)
    math_rule = (digit_sum + last_digit) % 2
    boost     = 0.4 if is_prime(int(clean_b) % 97) else 0.0
    scores[math_rule] += 0.8 + boost
    logs.append(f"🔢 مجموع الأرقام={digit_sum} {'(أولي✨)' if boost else ''} → {WINNER_NAMES[math_rule]}")

    # ── X1: Lookalike KNN ────────────────────────────────────────────
    lk_pred, lk_conf, lk_log = lookalike_predict(recent_history)
    if lk_pred is not None:
        w = get_adaptive_weight('LOOKALIKE', 2.2)
        scores[lk_pred] += lk_conf * w
        logs.append(f"🧬 {lk_log} → {WINNER_NAMES[lk_pred]} ({lk_conf:.0%}) w={w:.1f}")

    # ── X2: Regime Detector ──────────────────────────────────────────
    regime, reg_conf = detect_regime(recent_history)
    rg_pred, rg_conf, rg_log = regime_vote(regime, reg_conf, recent_history)
    if rg_pred is not None:
        w = get_adaptive_weight('REGIME', 2.8)
        scores[rg_pred] += rg_conf * w
        regime_emoji = {"banker_streak":"🔴","player_streak":"🔵","alternating":"🔁","chaotic":"❓"}.get(regime,"")
        logs.append(f"🧠 النظام {regime_emoji}: {rg_log} ({rg_conf:.0%})")

    # ── X3: Bayesian Engine ───────────────────────────────────────────
    bay_pred, bay_conf, bay_log = bayesian_predict(suit, rank, last_digit)
    if bay_pred is not None:
        w = get_adaptive_weight('BAYESIAN', 3.0)
        scores[bay_pred] += bay_conf * w
        logs.append(f"📊 بايز: {bay_log} → {WINNER_NAMES[bay_pred]} ({bay_conf:.0%})")

    # ── N1: الارتباط الزمني ──────────────────────────────────────────
    ac_pred, ac_conf, ac_log = temporal_autocorr(recent_history)
    if ac_pred is not None:
        w = get_adaptive_weight('AUTOCORR', 1.4)
        scores[ac_pred] += ac_conf * w
        logs.append(f"🕰️ {ac_log} → {WINNER_NAMES[ac_pred]} ({ac_conf:.0%})")

    # ── N2: N-Gram في التاريخ ─────────────────────────────────────
    ng_pred, ng_conf, ng_log = ngram_db_predict(recent_history)
    if ng_pred is not None:
        w = get_adaptive_weight('NGRAM', 2.4)
        scores[ng_pred] += ng_conf * w
        logs.append(f"🔍 {ng_log} → {WINNER_NAMES[ng_pred]} ({ng_conf:.0%})")

    # ── N3: ذاكرة الفجوة التاريخية ──────────────────────────────
    gh_pred, gh_conf, gh_log = gap_history_predict(b_gap)
    if gh_pred is not None:
        w = get_adaptive_weight('GAP_HIST', 1.8)
        scores[gh_pred] += gh_conf * w
        logs.append(f"📏 {gh_log} → {WINNER_NAMES[gh_pred]} ({gh_conf:.0%})")

    # ── N4: كاشف النتيجة المتأخرة ────────────────────────────────
    od_pred, od_conf, od_log = overdue_detector(recent_history)
    if od_pred is not None:
        w = get_adaptive_weight('OVERDUE', 1.5)
        scores[od_pred] += od_conf * w
        logs.append(f"⏳ {od_log} → {WINNER_NAMES[od_pred]} ({od_conf:.0%})")

    # ── M4: مضخّم الإجماع ────────────────────────────────────────────
    active_signal_count = sum(1 for x in [
        mom_pred, streak_pred, mem_pred, sb_pred,
        mkv_pred, cyc_pred, lk_pred, rg_pred, bay_pred,
        ac_pred, ng_pred, gh_pred, od_pred,
    ] if x is not None)
    consensus = amplify_consensus(scores, active_signal_count)
    if consensus > 1.05:
        dominant = 0 if scores[0] >= scores[1] else 1
        scores[dominant] *= consensus
        logs.append(f"📡 إجماع ×{consensus:.2f} ({active_signal_count}/9 إشارات)")

    # ── X4: Anti-Mode — مُعطَّل (كان يسبب حلقة عكس مفرغة) ──────────────
    # التحليل أثبت: المحركات الأساسية دقتها 67% لكن anti-mode كان يعكسها → 33%
    # نحتفظ بـ recent_acc فقط لضبط الثقة
    _, recent_acc = check_anti_mode()

    # ── V1: أنماط EXACT ─────────────────────────────────────────────
    ex_pred, ex_conf, ex_log = exact_pattern_predict(suit, rank, last_digit)
    if ex_pred is not None:
        w = get_adaptive_weight('EXACT', 2.6)
        scores[ex_pred] += ex_conf * w
        logs.append(f"🎯 EXACT: {ex_log} → {WINNER_NAMES[ex_pred]} ({ex_conf:.0%})")

    # ── V2: DeepNGram (600 جولة) ─────────────────────────────────
    dn_pred, dn_conf, dn_log = deep_ngram_predict(recent_history)
    if dn_pred is not None:
        w = get_adaptive_weight('DEEP_NGRAM', 1.8)
        scores[dn_pred] += dn_conf * w
        logs.append(f"🧬 {dn_log} → {WINNER_NAMES[dn_pred]} ({dn_conf:.0%})")

    # ── V3: Hot-Switch Detector ─────────────────────────────────
    hs_pred, hs_conf, hs_log = hot_switch_detector(recent_history)
    if hs_pred is not None:
        w = get_adaptive_weight('HOT_SWITCH', 1.8)
        scores[hs_pred] += hs_conf * w
        logs.append(f"⚡ {hs_log} → {WINNER_NAMES[hs_pred]} ({hs_conf:.0%})")

    # ── V4: الجذب التاريخي ───────────────────────────────────────
    gv_pred, gv_conf, gv_log = historical_gravity()
    if gv_pred is not None:
        w = get_adaptive_weight('GRAVITY', 1.0)
        scores[gv_pred] += gv_conf * w
        logs.append(f"🧲 {gv_log} ({gv_conf:.0%})")

    # ── PB1: كاشف ما بعد الانقطاع ────────────────────────────────
    # يعمل فقط عند كسر ناعم أو قوي — يُكمّل الفراغ الذي تتركه محركات التسلسل
    pb_pred, pb_conf, pb_log = None, 0.0, ""
    try:
        pb_pred, pb_conf, pb_log = post_break_predict(session_type, b_gap)
    except Exception:
        pass
    if pb_pred is not None:
        pb_weight = 2.0 if session_type == 'hard_break' else 1.2
        w = get_adaptive_weight('POST_BREAK', pb_weight)
        scores[pb_pred] += pb_conf * w
        logs.append(f"🔀 {pb_log} → {WINNER_NAMES[pb_pred]} ({pb_conf:.0%}) {'[انقطاع قوي]' if session_type=='hard_break' else '[انقطاع ناعم]'}")

    # ── SC1: إحصاءات السلسلة المتصلة ────────────────────────────
    # يعمل فقط عندما الجلسة متصلة وبها 4+ جولات
    sc_pred, sc_conf, sc_log = None, 0.0, ""
    try:
        sc_pred, sc_conf, sc_log = session_chain_stats(recent_history)
    except Exception:
        pass
    if sc_pred is not None and session_type == 'connected':
        w = get_adaptive_weight('SESSION_CHAIN', 1.6)
        scores[sc_pred] += sc_conf * w
        logs.append(f"🔢 {sc_log} ({sc_conf:.0%})")

    # ── T8: عد الأوراق (Card Counter) ─────────────────────────────
    # connected_rows = (winner, b_num, created_at) — نستخدم rank الجولة الحالية كبداية
    # + نجلب ranks من DB مباشرة للجلسة المتصلة
    cc_pred, cc_conf, cc_log = None, 0.0, ""
    try:
        with db_pool.get_conn() as _cc_conn:
            with _cc_conn.cursor() as _cc_cur:
                _cc_cur.execute("""
                    SELECT rank FROM history
                    WHERE rank IS NOT NULL AND rank NOT IN ('NULL','')
                      AND created_at >= NOW() - INTERVAL '30 minutes'
                    ORDER BY id DESC LIMIT 40
                """)
                recent_ranks = [r[0] for r in _cc_cur.fetchall() if r[0]]
        recent_ranks.append(rank)  # أضف رتبة الجولة الحالية
        cc_pred, cc_conf, cc_log = baccarat_card_counter(recent_ranks)
    except Exception:
        pass
    if cc_pred is not None:
        w = get_adaptive_weight('CARD_COUNT', 3.5)
        scores[cc_pred] += cc_conf * w
        logs.append(f"🃏 {cc_log} (w={w:.1f})")

    # ── X5: مصفوفة الفوضى (Shannon Entropy) ────────────────────────
    is_chaos, entropy_val, chaos_log = shannon_entropy_sniper(recent_history)
    if is_chaos:
        logs.append(f"🛑 {chaos_log}")
        logs.append("🛡️ وضع القناص: فوضى رياضية — تخطي الجولة")
        return 2, 0, "\n".join(logs)

    # ── ✨ التقاطع الذهبي: بايز + ماركوف + عد الأوراق ────────────
    golden = [bay_pred, mkv_pred, cc_pred]
    if all(p is not None for p in golden) and len(set(golden)) == 1:
        golden_pred = golden[0]
        scores[golden_pred] *= 2.5
        logs.append(f"✨ التقاطع الذهبي: بايز + ماركوف + عد الأوراق → {WINNER_NAMES[golden_pred]}")

    # ── V5: تصويت الأغلبية الديناميكي ─────────────────────────
    # تصويت الأغلبية: 5 محركات كبرى فقط — المحركات الصغيرة تُلغي بعضها
    # Lookalike, Regime, Bayesian, DeepNGram, PostBreak = أعلى دقة إحصائياً
    all_point_signals = [
        (lk_pred,  lk_conf,                                    "lk"),   # Lookalike
        (rg_pred,  rg_conf,                                    "rg"),   # Regime
        (bay_pred, bay_conf if bay_pred is not None else 0.0,  "bay"),  # Bayesian
        (dn_pred,  dn_conf,                                    "dn"),   # DeepNGram
        (pb_pred,  pb_conf if pb_pred is not None else 0.0,    "pb"),   # Post-break
    ]
    mv_pred, mv_conf, mv_agree, mv_total = dynamic_majority_vote(all_point_signals)
    if mv_pred is not None and mv_total >= 4:
        mv_boost = mv_conf * 1.8 * (mv_agree / max(mv_total, 1))
        scores[mv_pred] += mv_boost
        logs.append(f"🏆 أغلبية: {WINNER_NAMES[mv_pred]} ({mv_agree}/{mv_total} محركات، ثقة {mv_conf:.0%})")

    # ── حماية من overfitting: منع هيمنة اتجاه واحد ────────────────
    total_score = scores[0] + scores[1]
    if total_score > 0:
        ratio = max(scores[0], scores[1]) / total_score
        if ratio > 0.80:
            # اسحب نحو 70/30 حداً أقصى
            correction = (ratio - 0.70) * total_score
            if scores[0] > scores[1]:
                scores[0] -= correction
                scores[1] += correction
            else:
                scores[1] -= correction
                scores[0] += correction

    # ── Decision Gate: لا تتنبأ إذا الإشارة ضعيفة ──────────────────
    if not should_predict(scores[0], scores[1]):
        total_s = scores[0] + scores[1]
        edge_pct = max(scores[0], scores[1]) / max(total_s, 0.001) * 100
        logs.append(f"🚫 إشارة ضعيفة ({edge_pct:.0f}% < {MIN_EDGE_THRESHOLD*100:.0f}%) — تخطي الجولة")
        return 2, 50, "\n".join(logs)

    # ── الحساب النهائي ──────────────────────────────────────────────
    total_score = scores[0] + scores[1]
    if total_score == 0:
        padded   = clean_b.zfill(3)
        math_res = ((sum(int(d) for d in padded[-3:]) * RANK_VALUE.get(rank.upper(), 1)) + last_digit) % 2
        logs.append("🧮 تحليل رياضي احتياطي")
        return math_res, 60, "\n".join(logs)

    p0 = scores[0] / total_score
    p1 = scores[1] / total_score
    entropy = -(p0 * math.log2(p0 + 1e-9) + p1 * math.log2(p1 + 1e-9))

    # ضبط الثقة بناءً على دقة حالية + إجماع
    base_conf   = 55 + 40 * (1 - entropy)
    acc_bonus   = max(0, (recent_acc - 0.50) * 30)   # +0 to +18 بناءً على الدقة
    final_conf  = int(min(97, max(55, base_conf + acc_bonus)))
    # ── قرار نهائي: الحسم دائماً — لا تعادل إلا في حالة نادرة جداً ───
    delta = abs(scores[0] - scores[1])
    if delta < 0.05 * max(scores[0], scores[1], 0.01):
        # إجماع شبه معدوم → الحاكم البايزي يفصل
        if bay_pred is not None:
            final = bay_pred
            logs.append(f"⚖️ حاكم بايزي → {WINNER_NAMES[final]}")
        elif gv_pred is not None:
            final = gv_pred
            logs.append(f"⚖️ جذب تاريخي → {WINNER_NAMES[final]}")
        else:
            logs.append("⚠️ إجماع معدوم — تخطي")
            return 2, 50, "\n".join(logs)
    elif scores[0] > scores[1]:
        final = 0
    else:
        final = 1

    # ── Cap النقاط + conflict ratio + overconfidence guard ──────────
    scores[0] = min(scores[0], 1.5)
    scores[1] = min(scores[1], 1.5)
    # conflict ratio: إذا الأصوات متقاربة → خفّض النتيجة النهائية
    if scores[0] > 0 and scores[1] > 0:
        conflict_ratio = min(scores[0], scores[1]) / max(scores[0], scores[1])
        if conflict_ratio > 0.6:
            scores[0] *= 0.75
            scores[1] *= 0.75
            logs.append(f"⚠️ تعارض إشارات ({conflict_ratio:.0%}) → خفض الثقة")
    # overconfidence guard: إذا الفارق ضعيف → خفض الثقة
    total_score = scores[0] + scores[1]
    if total_score > 0 and abs(scores[0] - scores[1]) / total_score < 0.15:
        final_conf = int(final_conf * 0.7)
    # أضف معلومات التوازن للـ logs
    total_score = scores[0] + scores[1]
    if total_score > 0:
        r_pct = scores[0] / total_score * 100
        b_pct = scores[1] / total_score * 100
        logs.append(f"📊 🔴{scores[0]:.2f} vs 🔵{scores[1]:.2f} | {r_pct:.0f}%/{b_pct:.0f}% | Δ={delta:.2f}")

    # معايرة الثقة الأسطورية
    final_conf = calibrate_confidence(final_conf, scores)

    # حفظ الإشارات مخفياً لتحديث الأداء لاحقاً
    signal_json = json.dumps({
        'AI': ai_pred if 'ai_pred' in dir() else None,
        'MARKOV': mkv_pred, 'CYCLE': cyc_pred,
        'STREAK': streak_pred, 'SHORT_MEM': mem_pred,
        'SUIT_BIAS': sb_pred, 'MOM': mom_pred,
        'LOOKALIKE': lk_pred, 'REGIME': rg_pred,
        'BAYESIAN': bay_pred,
        'AUTOCORR': ac_pred, 'NGRAM': ng_pred,
        'GAP_HIST': gh_pred, 'OVERDUE': od_pred,
        'EXACT': ex_pred, 'DEEP_NGRAM': dn_pred,
        'HOT_SWITCH': hs_pred, 'GRAVITY': gv_pred,
        'POST_BREAK': pb_pred,
        'SESSION_CHAIN': sc_pred,
        'OVERALL': final,
    })
    logs.append(f"__signals__{signal_json}")

    return final, final_conf, "\n".join(logs)

# ==================== تنسيق الرسائل الأسطوري ====================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    # ── التحقق من الاشتراك ────────────────────────────────────────
    allowed, sub_msg = await check_subscription(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(sub_msg, parse_mode="HTML")
        return
    # ─────────────────────────────────────────────────────────────
    suit = context.user_data.get('suit')
    rank = context.user_data.get('rank')
    if not suit or not rank:
        await update.message.reply_text("ابدأ بالضغط على /start واختيار البذلة والرتبة.")
        return
    b_num = clean_digits(text)
    if not b_num:
        await update.message.reply_text("❌ أرسل رقم البونص فقط.")
        return
    context.user_data['last_b_num'] = b_num
    wait_msg = await update.message.reply_text("🔄 جارٍ التحليل...")
    _session_mode = context.user_data.get('session_mode', 'auto')
    try:
        pred, conf, reason = await predict(b_num, suit, rank, session_mode=_session_mode)
        context.user_data['last_pred'] = pred
        signals_data = {}
        clean_reason_lines = []
        for line in reason.split("\n"):
            if line.startswith("__signals__"):
                try: signals_data = json.loads(line[11:])
                except Exception: pass
            else: clean_reason_lines.append(line)
        context.user_data['last_signals'] = signals_data
        clean_reason = "\n".join(clean_reason_lines)
        await wait_msg.delete()
        _uid = update.effective_user.id if update.effective_user else 0
        await update.message.reply_text(format_prediction(pred, conf, clean_reason, suit, rank, b_num),
                                        parse_mode="HTML", reply_markup=result_keyboard(pred, b_num, _uid))
    except Exception as e:
        logger.error(f"predict error: {e}", exc_info=True)
        await wait_msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

# ==================== تنسيق الرسائل ====================
CONFIDENCE_TIER = [(90,"🔥 عالية جداً","▓▓▓▓▓▓▓▓▓▓"), (80,"⚡ عالية","▓▓▓▓▓▓▓▓░░"),
                   (70,"✅ متوسطة-عالية","▓▓▓▓▓▓░░░░"), (60,"📊 متوسطة","▓▓▓▓░░░░░░"), (0,"❓ ضعيفة","▓▓░░░░░░░░")]

def confidence_display(conf: int):
    for threshold, label, bar in CONFIDENCE_TIER:
        if conf >= threshold:
            return label, bar
    return "❓ ضعيفة", "▓▓░░░░░░░░"

def format_prediction(pred: int, conf: int, reason: str,
                      suit: str, rank: str, b_num: str) -> str:
    ld = get_last_digit(b_num)
    name = WINNER_NAMES[pred]
    laws_count = len(load_laws())
    sig_count = len([v for v in _signal_perf.values() if v[1] > 0])
    conf_label, conf_bar = confidence_display(conf)

    analysis_lines = [l if any(t in l for t in ["<b>","</b>","<i>","</i>","<code>","</code>"]) else html.escape(l)
                      for l in reason.split("\n") if l.strip() and not l.startswith("__signals__")]
    pred_symbol = "🔴" if pred == 0 else "🔵"
    agree = [l for l in analysis_lines if pred_symbol in l]
    disagree = [l for l in analysis_lines if pred_symbol not in l and "🔗" not in l and "⏱️" not in l][:3]
    context = [l for l in analysis_lines if "🔗" in l or "⏱️" in l]

    analysis_txt = ""
    if agree:
        analysis_txt += "\n".join(agree[:8]) + "\n"
    if disagree:
        analysis_txt += "\n".join(disagree[:3]) + "\n"
    if context:
        analysis_txt += "\n".join(context) + "\n"

    if sig_count >= 15:  engine_status = "⚡ 19 محرك نشط"
    elif sig_count >= 10: engine_status = "⚡ محركات كاملة"
    elif sig_count >= 6: engine_status = "🔄 محركات متقدمة"
    else:                engine_status = "🔧 تعلم أولي"

    header_emoji = "🔴" if pred == 0 else "🔵"
    return (
        f"{'━'*22}\n"
        f"{header_emoji}  <b>التوقع: {name}</b>  {header_emoji}\n"
        f"{'━'*22}\n"
        f"🃏 {suit} {rank}  |  #{b_num}  |  رقم: {ld}\n\n"
        f"📊 الثقة: <b>{conf}%</b>  {conf_label}\n<code>{conf_bar}</code>\n\n"
        f"⚙️ {engine_status}  |  ⚖️ {laws_count} قانون\n"
        f"{'━'*22}\n"
        f"<b>📋 التحليل ({len(agree)} موافق / {len(disagree)} معارض):</b>\n{analysis_txt}"
        f"{'━'*22}"
    )

def result_keyboard(pred: int, b_num: str, user_id: int = 0) -> InlineKeyboardMarkup:
    """للأدمن: لوحة كاملة. للمشترك العادي: جولة جديدة فقط."""
    if user_id == ADMIN_ID:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ الراعي 🔴", callback_data=f"save_0_{b_num}"),
             InlineKeyboardButton("✅ الثور 🔵",  callback_data=f"save_1_{b_num}"),
             InlineKeyboardButton("✅ تعادل ⚪",  callback_data=f"save_2_{b_num}")],
            [InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit"),
             InlineKeyboardButton("📊 إحصاءات",    callback_data="stats")],
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ الراعي 🔴", callback_data=f"save_0_{b_num}"),
             InlineKeyboardButton("✅ الثور 🔵",  callback_data=f"save_1_{b_num}"),
             InlineKeyboardButton("✅ تعادل ⚪",  callback_data=f"save_2_{b_num}")],
            [InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")],
        ])

def _safe(v, fmt=None) -> str:
    if v is None: return "NULL"
    if fmt and isinstance(v, (int,float)):
        try: return format(v, fmt)
        except Exception: return str(v)
    return str(v)

# ==================== التشغيل ====================
_last_auto_learn: float = 0.0
_auto_learn_lock = asyncio.Lock()

async def auto_learn_job(context) -> None:
    global _last_auto_learn
    async with _auto_learn_lock:
        try:
            with db_pool.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COUNT(*) FROM history
                        WHERE winner IS NOT NULL
                          AND rank IS NOT NULL AND rank NOT IN ('NULL','')
                          AND created_at > (SELECT COALESCE(MAX(created_at), '2000-01-01') FROM learn_sessions)
                    """)
                    new_rounds = cur.fetchone()[0]
            if new_rounds < 30:
                logger.info(f"Auto-learn skipped: only {new_rounds} new rounds")
                return
            logger.info(f"Auto-learn triggered: {new_rounds} new rounds")
            msgs = []
            async def status_cb(msg):
                msgs.append(msg)
            result = await force_learn_engine(status_cb)
            if "error" not in result:
                summary = f"🤖 <b>تعلم تلقائي</b>\n📊 جولات جديدة: {new_rounds}\n⚖️ قوانين جديدة: {result.get('saved',0)}\n📈 جلسة #{result.get('session_id','?')}"
                try: await context.bot.send_message(chat_id=ADMIN_ID, text=summary, parse_mode="HTML")
                except Exception: pass
                _last_auto_learn = time.time()
        except Exception as e:
            logger.error(f"auto_learn_job error: {e}")


# ==================== Keep-Alive Web Server ====================
_flask_app = Flask(__name__)

@_flask_app.route("/")
def _health():
    return "🟢 HADES V19 is alive", 200

@_flask_app.route("/health")
def _health2():
    return "OK", 200

def _run_web():
    """تشغيل Flask في خيط منفصل لإبقاء Render مستيقظاً."""
    import os
    port = int(os.environ.get("PORT", 10000))
    _flask_app.run(host="0.0.0.0", port=port, use_reloader=False)

# ==================== التشغيل الرئيسي ====================
def main():
    from telegram.error import Conflict

    ensure_tables()
    load_laws()
    load_signal_perf_from_db()

    # ── بدء سيرفر Keep-Alive في خيط خلفي ──────────────────────────
    web_thread = threading.Thread(target=_run_web, daemon=True)
    web_thread.start()
    logger.info("🌐 Keep-alive web server started")

    # ── بناء التطبيق ──────────────────────────────────────────────
    app = ApplicationBuilder().token(TOKEN).build()

    app.job_queue.run_repeating(auto_learn_job, interval=3600, first=300)
    logger.info("⏰ Auto-learn job: every 60min, starts after 5min")

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("force_learn",   cmd_force_learn))
    app.add_handler(CommandHandler("mine_gold",     cmd_mine_gold))
    app.add_handler(CommandHandler("council_learn", cmd_council_learn))
    app.add_handler(CommandHandler("set_key",       cmd_set_key))
    app.add_handler(CommandHandler("get_key",       cmd_get_key))
    app.add_handler(CommandHandler("revoke_key",    cmd_revoke_key))
    app.add_handler(CommandHandler("laws",          cmd_laws))
    app.add_handler(CommandHandler("deactivate",    cmd_deactivate_law))
    app.add_handler(CommandHandler("stats",         cmd_stats))
    app.add_handler(CommandHandler("prune",         cmd_prune))
    app.add_handler(CommandHandler("reset_laws",    cmd_reset_laws))
    app.add_handler(CommandHandler("reset_bias",    cmd_reset_bias))
    app.add_handler(CommandHandler("last",          cmd_last))
    app.add_handler(CommandHandler("delete",        cmd_delete))
    app.add_handler(CommandHandler("download",      cmd_download))
    app.add_handler(CommandHandler("engine",        cmd_engine_status))
    app.add_handler(CommandHandler("add_sub",       cmd_add_sub))
    app.add_handler(CommandHandler("revoke_sub",    cmd_revoke_sub))
    app.add_handler(CommandHandler("list_subs",     cmd_list_subs))
    app.add_handler(CommandHandler("my_sub",        cmd_my_sub))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("🚀 HADES V19.0 is running...")

    try:
        app.run_polling(drop_pending_updates=True)
    except Conflict:
        logger.error("❌ Conflict: البوت يعمل في مكان آخر — أوقف النسخة الأخرى أولاً")
    except Exception as e:
        logger.error(f"❌ خطأ في run_polling: {e}", exc_info=True)


if __name__ == "__main__":
    main()
