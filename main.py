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

import re
import json
import logging
import math
import asyncio
import time
from typing import Tuple, Dict, Optional, List, Any
from contextlib import contextmanager
from datetime import datetime
from collections import OrderedDict, defaultdict

import psycopg2
from psycopg2 import pool
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from openai import AsyncOpenAI

# ==================== الإعدادات ====================
TOKEN        = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID     = 6033203084

AI_BASE_URL  = "https://integrate.api.nvidia.com/v1"
AI_API_KEY   = "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"
AI_MODEL     = "mistralai/devstral-2-123b-instruct-2512"
AI_TIMEOUT   = 3.0
LEARN_TIMEOUT = 300  # 5 دقائق للتعلم العميق

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
    'SD': 2.8, 'SUIT': 1.8, 'DIGIT': 1.2, 'RANK': 1.5,
    'MOMENTUM': 1.5, 'AI': 2.5,
    'LAW': 3.5,      # قوانين الذاكرة السياقية — أعلى وزن
}
# ════════════════════════════════════════════════════════════════════
# 📊 قوانين مستخلصة من تحليل 1780 جولة حقيقية (v19)
# ════════════════════════════════════════════════════════════════════
DATA_LAWS: List[Dict] = [
    # Gap micro (100-500) → RED (bias=0.20, n=122)
    {"id": -1, "law_type": "data_gap_micro", "conditions": {"b_gap_gte": 100, "b_gap_lt": 500},
     "prediction": 0, "confidence": 62, "accuracy": 60.0, "times_used": 122,
     "description": "فجوة 100-500 → الراعي 🔴 (تحليل حقيقي)", "active": True},
    # Gap nano (0-100) → BLUE (bias=0.20, n=35)
    {"id": -2, "law_type": "data_gap_nano", "conditions": {"b_gap_lt": 100},
     "prediction": 1, "confidence": 60, "accuracy": 60.0, "times_used": 35,
     "description": "فجوة 0-100 → الثور 🔵 (تحليل حقيقي)", "active": True},
    # After 4+ RED streak → BLUE (bias=0.29, n=34)
    {"id": -3, "law_type": "data_after_4x_red", "conditions": {"streak": {"length": 4, "value": 0}},
     "prediction": 1, "confidence": 64, "accuracy": 64.0, "times_used": 34,
     "description": "بعد 4 رواعٍ متتالية → الثور 🔵 (bias=0.29)", "active": True},
    # Cycle 8 pos=1 → RED (bias=0.11, n=223)
    {"id": -4, "law_type": "data_cycle8_pos1", "conditions": {"cycle_position": {"cycle": 8, "position": 1}},
     "prediction": 0, "confidence": 56, "accuracy": 55.5, "times_used": 223,
     "description": "دورة 8 موضع 1 → الراعي 🔴", "active": True},
    # Cycle 8 pos=5 → BLUE (bias=0.12, n=222)
    {"id": -5, "law_type": "data_cycle8_pos5", "conditions": {"cycle_position": {"cycle": 8, "position": 5}},
     "prediction": 1, "confidence": 56, "accuracy": 56.0, "times_used": 222,
     "description": "دورة 8 موضع 5 → الثور 🔵", "active": True},
    # digit_sum mod9=6 → RED (bias=0.11, n=206)
    {"id": -6, "law_type": "data_digsum_mod9_r6", "conditions": {"digit_sum_mod": {"mod": 9, "remainder": 6}},
     "prediction": 0, "confidence": 56, "accuracy": 55.3, "times_used": 206,
     "description": "مجموع الأرقام mod9=6 → الراعي 🔴", "active": True},
    # digit_sum mod7=1 → BLUE (bias=0.10, n=241)
    {"id": -7, "law_type": "data_digsum_mod7_r1", "conditions": {"digit_sum_mod": {"mod": 7, "remainder": 1}},
     "prediction": 1, "confidence": 55, "accuracy": 55.0, "times_used": 241,
     "description": "مجموع الأرقام mod7=1 → الثور 🔵", "active": True},
    # After 4+ BLUE streak → RED (bias=0.17, n=41)
    {"id": -8, "law_type": "data_after_4x_blue", "conditions": {"streak": {"length": 4, "value": 1}},
     "prediction": 0, "confidence": 58, "accuracy": 58.5, "times_used": 41,
     "description": "بعد 4 ثيران متتالية → الراعي 🔴 (bias=0.17)", "active": True},
]
DATA_LAW_WEIGHT = 2.2   # وزن القوانين الحقيقية


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

# ==================== DB Pool ====================
class DatabasePool:
    _instance = None
    _pool     = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_pool()
        return cls._instance

    def _init_pool(self):
        self._pool = psycopg2.pool.SimpleConnectionPool(
            1, 10, dsn=DATABASE_URL, sslmode='require', connect_timeout=3
        )
        logger.info("✅ Database pool created")

    @contextmanager
    def get_conn(self):
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

db_pool = DatabasePool()

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

# ==================== 🧠 الذاكرة السياقية ====================
# تُحمَّل عند بدء التشغيل وتُحدَّث بعد كل /force_learn
_laws_cache: List[Dict] = []
_laws_loaded_at: float  = 0.0

def load_laws(force: bool = False) -> List[Dict]:
    """
    يُحمِّل القوانين من قاعدة البيانات.
    يُعيد الكاش إن كان حديثاً (< 5 دقائق)، إلا إذا force=True.
    """
    global _laws_cache, _laws_loaded_at
    if not force and time.time() - _laws_loaded_at < 300:
        return _laws_cache
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, law_type, conditions, prediction,
                           confidence, accuracy, times_used,
                           description, created_at
                    FROM ai_laws
                    WHERE active = TRUE
                    ORDER BY accuracy DESC, confidence DESC
                    LIMIT 50
                """)
                rows = cur.fetchall()
        laws = []
        for row in rows:
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
            })
        _laws_cache     = laws
        _laws_loaded_at = time.time()
        logger.info(f"✅ Loaded {len(laws)} active laws from DB")
        return laws
    except Exception as e:
        logger.error(f"load_laws error: {e}")
        return _laws_cache  # أعِد الكاش القديم

def match_law(law: Dict, suit: str, rank: str, last_digit: int,
              recent: List[int], b_num: str = "", b_gap: Optional[float] = None,
              gap_sec: Optional[float] = None, round_index: int = 0) -> float:
    """
    يُطابق القانون مع الجولة الحالية — يدعم الشروط الرياضية والفجوات.
    يُعيد [0, 1]: 1 = انطباق كامل.
    """
    cond  = law.get("conditions", {})
    score = 0.0
    total = 0

    def chk(condition: bool):
        nonlocal score, total
        total += 1
        if condition:
            score += 1

    # ── شروط أساسية ─────────────────────────────────────────────────
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

    # ── شروط تسلسلية ────────────────────────────────────────────────
    if "streak" in cond:
        slen = cond["streak"]["length"]
        if len(recent) >= slen:
            chk(recent[-slen:] == [cond["streak"]["value"]] * slen)
    if "after_pattern" in cond:
        pat = cond["after_pattern"]
        if len(recent) >= len(pat):
            chk(recent[-len(pat):] == pat)

    # ── شروط رياضية (b_num) ──────────────────────────────────────────
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

    # ── شروط الدورة ──────────────────────────────────────────────────
    if "cycle_position" in cond and round_index > 0:
        c = cond["cycle_position"]
        chk(round_index % int(c["cycle"]) == int(c["position"]))

    # ── شروط الفجوة الرقمية ──────────────────────────────────────────
    if b_gap is not None:
        if "b_gap_gt"      in cond: chk(b_gap > float(cond["b_gap_gt"]))
        if "b_gap_lt"      in cond: chk(b_gap < float(cond["b_gap_lt"]))
        if "b_gap_gte"     in cond: chk(b_gap >= float(cond["b_gap_gte"]))
        if "b_gap_lte"     in cond: chk(b_gap <= float(cond["b_gap_lte"]))
        if "after_big_gap" in cond: chk(b_gap > 2000)

    # ── شروط الفجوة الزمنية ──────────────────────────────────────────
    if gap_sec is not None:
        if "gap_sec_lt" in cond: chk(gap_sec < float(cond["gap_sec_lt"]))
        if "gap_sec_gt" in cond: chk(gap_sec > float(cond["gap_sec_gt"]))

    if total == 0:
        return 0.5
    return score / total

def apply_laws(suit: str, rank: str, last_digit: int,
               recent: List[int], b_num: str = "",
               b_gap: Optional[float] = None, gap_sec: Optional[float] = None,
               round_index: int = 0) -> Tuple[Dict[int, float], List[str]]:
    """
    يُطبّق كل القوانين النشطة — يدعم الشروط الرياضية والفجوات.
    """
    laws   = load_laws()
    scores = {0: 0.0, 1: 0.0}
    logs   = []

    # ── قوانين مستخلصة من البيانات الحقيقية ──────────────────────────
    all_laws = list(DATA_LAWS) + laws
    for law in all_laws:
        match = match_law(law, suit, rank, last_digit, recent,
                          b_num=b_num, b_gap=b_gap,
                          gap_sec=gap_sec, round_index=round_index)
        if match < 0.5:
            continue

        pred = law.get("prediction")
        if pred not in [0, 1]:
            continue

        weight = (law["confidence"] / 100) * max(0.5, law["accuracy"] / 100) * match
        scores[pred] += weight * WEIGHTS['LAW']

        if match >= 0.8:
            logs.append(
                f"⚖️ قانون #{law['id']} ({law['law_type']}): "
                f"{WINNER_NAMES[pred]} — {law['description'][:60]}"
            )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.run_in_executor(None, _increment_law_usage, law["id"])
        except Exception:
            pass

    return scores, logs

def _increment_law_usage(law_id: int):
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ai_laws SET times_used = times_used + 1 WHERE id = %s",
                    (law_id,)
                )
                conn.commit()
    except Exception:
        pass

def update_law_accuracy(law_id: int, correct: bool):
    """بعد تسجيل نتيجة حقيقية: حدّث دقة القانون."""
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                # دقة متحركة: 90% وزن للقديم + 10% للجديد
                new_val = 100.0 if correct else 0.0
                cur.execute("""
                    UPDATE ai_laws
                    SET accuracy = accuracy * 0.90 + %s * 0.10,
                        active   = CASE WHEN accuracy * 0.90 + %s * 0.10 < 30
                                        THEN FALSE ELSE active END
                    WHERE id = %s
                """, (new_val, new_val, law_id))
                conn.commit()
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
                # أنشئ جدول ai_laws بأبسط هيكل أولاً
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ai_laws (
                        id         SERIAL PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # أضف الأعمدة الناقصة بشكل آمن (تتجاهل إن كانت موجودة)
                migrate_cols = [
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS law_type    VARCHAR(50)",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS conditions  JSONB",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS prediction  INT",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS confidence  FLOAT DEFAULT 70",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS accuracy    FLOAT DEFAULT 70",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS times_used  INT DEFAULT 0",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS description TEXT",
                    "ALTER TABLE ai_laws ADD COLUMN IF NOT EXISTS source      TEXT DEFAULT \'force_learn\'",
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
def _score_pattern(raw: Dict) -> Dict:
    r, b, t = raw.get("r", 0), raw.get("b", 0), raw.get("t", 0)
    total = r + b + t
    if total == 0:
        return {"w": 2, "c": 0.0, "log": "[No Data]", "tie_ratio": 0.0}
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
                    result = _score_pattern({"r": row[0], "b": row[1], "t": row[2]})
                    live_cache.set(pattern_id, result)
                    return result
    except Exception as e:
        logger.warning(f"DB pattern fetch ({pattern_id}): {e}")
    raw = EMBEDDED_PATTERNS.get(pattern_id)
    if raw:
        result = _score_pattern(raw)
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
ai_client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)

def extract_json_safe(text: str) -> Optional[Any]:
    # محاولة مباشرة
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    # استخراج أول كائن JSON
    match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    # إزالة code blocks
    cleaned = re.sub(r'```(?:json)?\n?', '', text).replace('```', '').strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return None

# ==================== 🧬 /force_learn: التعلم الرياضي العميق ====================
def _filter_valid_rounds(rows) -> List[Dict]:
    """
    تنقية الجولات:
    1. تجاهل أول 700 جولة (كانت تعادلات مضللة)
    2. حساب فجوات الوقت بين الجولات
    3. تمييز الجولات المتصلة (فجوة < 20 ثانية) عن المنفصلة
    """
    valid = []
    rows_list = list(rows)

    # تجاهل أول 700 جولة
    working = rows_list[700:] if len(rows_list) > 700 else rows_list

    for i, row in enumerate(working):
        b_num   = clean_digits(str(row[1] or ""))
        suit    = row[2] or ""
        rank    = row[3] or ""
        digit   = int(row[4]) if row[4] is not None else -1
        winner  = WINNER_MAP.get(row[5], 2)
        ts      = row[6]  # created_at

        if winner == 2 or not b_num or not suit:
            continue

        # فجوة الوقت مع الجولة السابقة
        gap_sec = None
        if i > 0 and working[i-1][6] and ts:
            gap_sec = abs((ts - working[i-1][6]).total_seconds())

        # فجوة رقم البونص (الفرق بين الأرقام)
        b_gap = None
        if i > 0:
            prev_b = clean_digits(str(working[i-1][1] or ""))
            if b_num and prev_b:
                try:
                    b_gap = abs(int(b_num) - int(prev_b))
                except Exception:
                    pass

        valid.append({
            "idx":       i,
            "b_num":     b_num,
            "suit":      suit,
            "rank":      rank,
            "digit":     digit,
            "winner":    winner,
            "ts":        ts,
            "gap_sec":   gap_sec,
            "b_gap":     b_gap,
            # الجولة متصلة إن كانت الفجوة < 20 ثانية أو الفجوة الرقمية صغيرة
            "connected": (gap_sec is not None and gap_sec <= 20) or
                         (b_gap is not None and b_gap <= 500),
        })

    return valid

def _build_math_memory(rounds: List[Dict]) -> Dict:
    """
    يبني ذاكرة رياضية — لا إحصاء عادي.
    التركيز على: الفجوات، الدورات، المعادلات، الأنماط الزمنية.
    """
    connected = [r for r in rounds if r["connected"]]
    total     = len(rounds)
    conn_cnt  = len(connected)

    # ── تحليل الفجوة الرقمية ────────────────────────────────────────
    _ga_raw = {"small_bnum_gap_lt200": [0, 0], "medium_bnum_gap_200_1000": [0, 0], "large_bnum_gap_gt1000": [0, 0]}
    for r in rounds:
        if r["b_gap"] is None:
            continue
        w = r["winner"]
        if w not in [0, 1]:
            continue
        if r["b_gap"] < 200:
            _ga_raw["small_bnum_gap_lt200"][w] += 1
        elif r["b_gap"] < 1000:
            _ga_raw["medium_bnum_gap_200_1000"][w] += 1
        else:
            _ga_raw["large_bnum_gap_gt1000"][w] += 1
    gap_analysis = {
        k: {"red_banker_0": v[0], "blue_player_1": v[1],
            "likely_prediction": 0 if v[0] > v[1] else 1,
            "note": "0=راعي_red_banker | 1=ثور_blue_player"}
        for k, v in _ga_raw.items()
    }

    # ── تحليل آخر رقم من b_num (الرقم الكامل لا digit البونص فقط) ──
    _ld_raw = defaultdict(lambda: [0, 0])
    for r in rounds:
        if r["b_num"] and r["winner"] in [0, 1]:
            ld = int(r["b_num"][-1])
            _ld_raw[str(ld)][r["winner"]] += 1
    last_digit_of_bnum = {
        k: {"red_banker_0": v[0], "blue_player_1": v[1],
            "likely_prediction": 0 if v[0] > v[1] else 1}
        for k, v in _ld_raw.items()
    }

    # ── تحليل مجموع أرقام b_num mod N ──────────────────────────────
    digit_sum_mod = {}
    for mod in [2, 3, 5, 7]:
        mod_stats = defaultdict(lambda: [0, 0])
        for r in rounds:
            if r["b_num"] and r["winner"] in [0, 1]:
                s = sum(int(d) for d in r["b_num"]) % mod
                mod_stats[str(s)][r["winner"]] += 1
        digit_sum_mod[f"mod_{mod}"] = {
            k: {"red": v[0], "blue": v[1],
                "bias": round((v[1]-v[0]) / max(v[0]+v[1], 1) * 100, 1)}
            for k, v in mod_stats.items()
        }

    # ── تحليل الدورة (كل N جولة ماذا يتكرر) ─────────────────────────
    cycle_analysis = {}
    for cycle in [3, 4, 5, 6, 7]:
        cycle_stats = defaultdict(lambda: [0, 0])
        for i, r in enumerate(connected):
            if r["winner"] in [0, 1]:
                pos = i % cycle
                cycle_stats[str(pos)][r["winner"]] += 1
        cycle_analysis[f"cycle_{cycle}"] = {
            k: {"red": v[0], "blue": v[1],
                "dominant": "red" if v[0] > v[1] else "blue"}
            for k, v in cycle_stats.items()
            if v[0] + v[1] >= 5
        }

    # ── تحليل الانتكاس بعد الفجوة ───────────────────────────────────
    # 0=راعي🔴(red/banker)  1=ثور🔵(blue/player)
    _ag = {"after_big_gap": [0, 0], "after_small_gap": [0, 0]}
    for r in rounds:
        if r["winner"] not in [0, 1] or r["b_gap"] is None:
            continue
        if r["b_gap"] > 2000:
            _ag["after_big_gap"][r["winner"]] += 1
        elif r["b_gap"] < 300:
            _ag["after_small_gap"][r["winner"]] += 1
    after_gap = {
        k: {"red_banker_0": v[0], "blue_player_1": v[1],
            "likely_prediction": 0 if v[0] > v[1] else 1,
            "note": "0=راعي_red_banker | 1=ثور_blue_player"}
        for k, v in _ag.items()
    }

    # ── تحليل الفجوة الزمنية ────────────────────────────────────────
    _tg = {"fresh_gap_lt_15s": [0, 0], "stale_gap_gt_15s": [0, 0]}
    for r in rounds:
        if r["winner"] not in [0, 1] or r["gap_sec"] is None:
            continue
        if r["gap_sec"] <= 15:
            _tg["fresh_gap_lt_15s"][r["winner"]] += 1
        else:
            _tg["stale_gap_gt_15s"][r["winner"]] += 1
    time_gap_analysis = {
        k: {"red_banker_0": v[0], "blue_player_1": v[1],
            "likely_prediction": 0 if v[0] > v[1] else 1}
        for k, v in _tg.items()
    }

    # ── تسلسلات الفوز عند الاتصال ───────────────────────────────────
    _sc = {"connected_after_red_0": [0, 0], "connected_after_blue_1": [0, 0]}
    for i in range(1, len(connected)):
        prev_w = connected[i-1]["winner"]
        curr_w = connected[i]["winner"]
        if prev_w == 0 and curr_w in [0, 1]:
            _sc["connected_after_red_0"][curr_w] += 1
        elif prev_w == 1 and curr_w in [0, 1]:
            _sc["connected_after_blue_1"][curr_w] += 1
    streaks_after_connect = {
        k: {"red_banker_0": v[0], "blue_player_1": v[1],
            "likely_prediction": 0 if v[0] > v[1] else 1}
        for k, v in _sc.items()
    }

    # ── قيمة b_num mod (مجموع الأرقام) مقابل الرتبة ─────────────────
    rank_digit_sum_bias = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rounds:
        if r["b_num"] and r["winner"] in [0, 1] and r["rank"]:
            s = sum(int(d) for d in r["b_num"]) % 10
            rank_digit_sum_bias[r["rank"]][str(s)][r["winner"]] += 1

    top_rank_bias = {}
    for rank, smap in rank_digit_sum_bias.items():
        for s, v in smap.items():
            t = v[0] + v[1]
            if t >= 5:
                bias = (v[1] - v[0]) / t
                if abs(bias) > 0.25:
                    top_rank_bias[f"{rank}_sum{s}"] = {
                        "red": v[0], "blue": v[1],
                        "bias_pct": round(bias * 100, 1)
                    }

    # ── عينة من الجولات المتصلة للـ AI ──────────────────────────────
    sample_connected = [
        {
            "b_num": r["b_num"], "suit": r["suit"],
            "rank": r["rank"], "digit": r["digit"],
            "winner": r["winner"], "b_gap": r["b_gap"],
            "gap_sec": round(r["gap_sec"], 1) if r["gap_sec"] else None,
        }
        for r in connected[-150:]  # آخر 150 جولة متصلة
    ]

    return {
        "overview": {
            "total_after_filter": total,
            "connected_rounds":   conn_cnt,
            "skipped_first_700":  True,
        },
        "gap_analysis":          gap_analysis,
        "time_gap_analysis":     time_gap_analysis,
        "after_gap_winner":      after_gap,
        "last_digit_of_bnum":    dict(last_digit_of_bnum),
        "digit_sum_mod":         digit_sum_mod,
        "cycle_analysis":        cycle_analysis,
        "streaks_after_connect": streaks_after_connect,
        "rank_digit_sum_bias":   top_rank_bias,
        "sample_connected_150":  sample_connected,
    }

async def force_learn_engine(status_callback) -> Dict:
    """
    تعلم رياضي عميق:
    - تجاهل أول 700 جولة (مضللة)
    - تحليل الفجوات الزمنية والرقمية
    - AI يكتشف قوانين رياضية (mod، دورات، فجوات) لا إحصاء بسيط
    """
    await status_callback("📥 <b>المرحلة 1/5</b> — جلب كل الجولات...")

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

    # القوانين الحالية (ذاكرة تراكمية)
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
        f"🤖 <b>المرحلة 3/5</b> — Devstral يحلل الأنماط الرياضية...\n"
        f"<i>لا مهلة زمنية — انتظر حتى الاكتمال</i>"
    )

    prompt = f"""
أنت عقل رياضي متخصص في اكتشاف القوانين الخفية في لعبة الباكارات.

━━━ تعريف المتغيرات — مهم جداً ━━━
prediction=0  يعني  الراعي 🔴 (red/banker)
prediction=1  يعني  الثور 🔵  (blue/player)
red_banker_0  = عدد مرات فوز الراعي
blue_player_1 = عدد مرات فوز الثور
likely_prediction = التوقع المقترح (0=راعي، 1=ثور)

━━━ السياق ━━━
- تم تجاهل أول 700 جولة (كانت تعادلات مضللة)
- الجولات ليست متتالية — هناك جولات لم تُسجَّل بينها
- الفجوة الزمنية (gap_sec) والفجوة الرقمية (b_gap) مهمتان جداً
- الفجوة > 20 ثانية أو b_gap > 500 تعني وجود جولات غير مسجلة بينها

━━━ البيانات الرياضية ━━━
{json.dumps(memory, ensure_ascii=False, indent=1)}
{prev_laws_txt}

━━━ المطلوب: قوانين رياضية لا إحصائية ━━━
اكتشف قوانين من هذا النوع (أمثلة للتوجيه فقط، ابتكر ما هو أفضل):
1. مجموع أرقام b_num mod N يعطي نتيجة محددة
2. الجولة بعد فجوة رقمية كبيرة (b_gap > X) تميل لـ red/blue
3. في الجولة رقم K من كل دورة طولها N، النتيجة غالباً X
4. إذا كانت الفجوة الزمنية قصيرة (< 15 ث) والبذلة X، النتيجة Y
5. (digit_sum + rank_value) mod N → نتيجة
6. بعد انقطاع (فجوة كبيرة) ثم عودة، النمط يبدأ من جديد

أنواع الشروط المتاحة في conditions:
- "digit_sum_mod": {{"mod": N, "remainder": K}}
- "b_gap_gt": عدد (b_gap أكبر من)
- "b_gap_lt": عدد (b_gap أصغر من)
- "gap_sec_lt": ثواني (فجوة زمنية أصغر من)
- "gap_sec_gt": ثواني (فجوة زمنية أكبر من)
- "cycle_position": {{"cycle": N, "position": K}}
- "suit": بذلة
- "digit": آخر رقم من b_num
- "rank": رتبة الورقة
- "rank_value_mod": {{"mod": N, "remainder": K}}
- "digit_plus_rank_mod": {{"mod": N, "remainder": K}}
- "streak": {{"length": N, "value": 0أو1}}
- "after_big_gap": true (بعد انقطاع > 2000)

أعد JSON فقط — مصفوفة:
[
  {{
    "law_type": "اسم_نوع_القانون",
    "conditions": {{ ... }},
    "prediction": 0أو1,
    "confidence": 50-97,
    "description": "شرح رياضي مختصر بالعربية — لماذا هذا القانون يعمل"
  }}
]

أنشئ 25-35 قانوناً. اتبع هذا التوزيع:
- 10 قوانين رياضية بسيطة (mod, cycle, gap)
- 10 قوانين متعددة الشروط (AND): ادمج شرطين في conditions مثل: digit_sum_mod + gap_sec_lt
- 8 قوانين زمنية (استخدم gap_sec لاكتشاف أنماط الوقت الفعلي)
- 7 قوانين من نوع جديد لم تظهر من قبل

لقوانين AND استخدم هذا الشكل:
{{
  "law_type": "compound_gap_digit",
  "conditions": {{
    "b_gap_lt": 500,
    "digit_sum_mod": {{"mod": 6, "remainder": 2}}
  }},
  "prediction": 1,
  "confidence": 88,
  "description": "عندما تكون الفجوة صغيرة (<500) ومجموع الأرقام mod 6 = 2"
}}

تذكير: prediction=0 دائماً يعني الراعي🔴، prediction=1 دائماً يعني الثور🔵.
القوانين متعددة الشروط ذات الدقة الأعلى يجب أن تشترط شرطين معاً.
"""

    try:
        response = await asyncio.wait_for(
            ai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.25,
                max_tokens=8192,
                seed=42,
            ),
            timeout=LEARN_TIMEOUT
        )
        raw_text = response.choices[0].message.content
    except asyncio.TimeoutError:
        return {"error": "انتهت المهلة الزمنية"}
    except Exception as e:
        return {"error": f"خطأ في AI: {e}"}

    await status_callback(
        "✅ <b>المرحلة 3/5</b> — Devstral أكمل التحليل\n\n"
        "💾 <b>المرحلة 4/5</b> — حفظ القوانين في قاعدة البيانات..."
    )

    # ── استخراج وحفظ القوانين ────────────────────────────────────────
    laws_data = extract_json_safe(raw_text)
    if not laws_data or not isinstance(laws_data, list):
        return {"error": f"فشل استخراج JSON من رد AI:\n{raw_text[:300]}"}

    saved = 0
    skipped = 0

    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                # احصل على رقم الجلسة الجديدة من جدول learn_sessions
                cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM learn_sessions")
                session_id = cur.fetchone()[0]

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

                    law_name = f"{law.get('law_type', 'COMBINED')}_{saved}_{int(time.time())}"
                    cur.execute("""
                        INSERT INTO ai_laws
                            (law_name, law_type, conditions, prediction, confidence,
                             accuracy, description, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'force_learn')
                        ON CONFLICT (law_name) DO UPDATE
                            SET conditions  = EXCLUDED.conditions,
                                prediction  = EXCLUDED.prediction,
                                confidence  = EXCLUDED.confidence,
                                description = EXCLUDED.description,
                                active      = TRUE
                    """, (
                        law_name,
                        law.get("law_type", "COMBINED"),
                        json.dumps(cond, ensure_ascii=False),
                        int(pred),
                        float(law.get("confidence", 70)),
                        float(law.get("confidence", 70)),
                        law.get("description", ""),
                    ))
                    saved += 1

                # احفظ ملخص الجلسة
                cur.execute("""
                    INSERT INTO learn_sessions
                        (rounds_used, laws_created, laws_updated, summary, context)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    total_rounds, saved, 0,
                    f"جلسة #{session_id}: {saved} قانون جديد من {total_rounds} جولة",
                    json.dumps({"memory_keys": list(memory.keys())}, ensure_ascii=False)
                ))
                conn.commit()
    except Exception as e:
        return {"error": f"خطأ في حفظ القوانين: {e}"}

    await status_callback(
        f"✅ <b>المرحلة 4/5</b> — تم حفظ <b>{saved}</b> قانون\n\n"
        f"🔄 <b>المرحلة 5/5</b> — تحديث الذاكرة النشطة..."
    )

    # ── تحديث الكاش ─────────────────────────────────────────────────
    load_laws(force=True)

    return {
        "total_rounds": total_rounds,
        "laws_saved":   saved,
        "laws_skipped": skipped,
        "session_id":   session_id,
        "sample_laws":  laws_data[:3],
    }

def _build_statistical_memory(rows) -> Dict:
    """
    يبني ملخصاً إحصائياً شاملاً من كل الجولات
    ليُغذّي AI بسياق غني.
    """
    # تحويل الصفوف إلى قائمة منظمة
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

    # أنماط البذلة
    suit_stats = defaultdict(lambda: [0, 0])
    for r in rounds:
        suit_stats[r["suit"]][r["winner"]] += 1

    # أنماط الرقم الأخير
    digit_stats = defaultdict(lambda: [0, 0])
    for r in rounds:
        if r["digit"] >= 0:
            digit_stats[str(r["digit"])][r["winner"]] += 1

    # أنماط الرتبة
    rank_stats = defaultdict(lambda: [0, 0])
    for r in rounds:
        rank_stats[r["rank"]][r["winner"]] += 1

    # أنماط SD (بذلة + رقم)
    sd_stats = defaultdict(lambda: [0, 0])
    for r in rounds:
        if r["digit"] >= 0:
            key = f"{r['suit']}_{r['digit']}"
            sd_stats[key][r["winner"]] += 1

    # تحليل السلاسل (streaks)
    streak_analysis = _analyze_streaks([r["winner"] for r in rounds])

    # تحليل التسلسلات الثلاثية
    triplet_analysis = _analyze_triplets([r["winner"] for r in rounds])

    # أنماط الانتقال بين البذلات
    suit_transition = _analyze_suit_transitions(rounds)

    # أفضل وأسوأ الأنماط
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
    """يحلل طول السلاسل وماذا يحدث بعدها."""
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
    """بعد كل ثلاثية — ماذا حدث؟"""
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
    """عند تغيير البذلة — ما النتيجة الأكثر؟"""
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
    """أقوى وأضعف الأنماط (أعلى انحياز)."""
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
    """يكتشف سلسلة 4+ متتالية ويقترح الكسر."""
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
        # كلما طالت السلسلة كلما ارتفعت الثقة (حد 0.90)
        conf = min(0.90, 0.75 + (streak - 4) * 0.03)
        return opposite, conf
    return None, 0.0

# ==================== 🧠 الذاكرة القصيرة (T2) ====================
def short_memory_bias(history: List[int]) -> Tuple[Optional[int], float]:
    """آخر 10 جولات — إن كان هناك انحياز واضح يُعزَّز."""
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
    """
    يحسب انحياز البذلة الحالية من آخر 80 جولة في DB مباشرة.
    """
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT winner FROM history
                    WHERE winner IS NOT NULL AND suit = %s
                    ORDER BY id DESC LIMIT 80
                """, (suit,))
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
# يتتبع دقة كل إشارة في آخر 30 جولة ويُعدّل وزنها تلقائياً
# ════════════════════════════════════════════════════════════════════
_signal_perf: Dict[str, List[int]] = {}   # signal_name → [correct, total]

def get_adaptive_weight(signal: str, base_weight: float) -> float:
    """
    يُعيد وزناً ديناميكياً بناءً على دقة الإشارة مؤخراً.
    إن لم تكن بيانات كافية → يعود للوزن الأساسي.
    """
    perf = _signal_perf.get(signal)
    if not perf or perf[1] < 5:
        return base_weight
    acc = perf[0] / perf[1]          # 0.0 – 1.0
    # خريطة: دقة 80%+ → ×1.6 | 50% → ×1.0 | 30%- → ×0.4
    if acc >= 0.80:   factor = 1.6
    elif acc >= 0.65: factor = 1.3
    elif acc >= 0.50: factor = 1.0
    elif acc >= 0.35: factor = 0.7
    else:             factor = 0.4
    return base_weight * factor

def update_signal_perf(signal: str, correct: bool, window: int = 30):
    """يُحدّث سجل أداء الإشارة (نافذة متحركة)."""
    if signal not in _signal_perf:
        _signal_perf[signal] = [0, 0]
    _signal_perf[signal][1] += 1
    if correct:
        _signal_perf[signal][0] += 1
    # حافظ على النافذة
    if _signal_perf[signal][1] > window:
        # تلاشٍ: اطرح أقدم نقطة (تقدير)
        decay = 1 / window
        _signal_perf[signal][0] = max(0, _signal_perf[signal][0] - decay)
        _signal_perf[signal][1] = window

def load_signal_perf_from_db():
    """يُحمّل أداء الإشارات من قاعدة البيانات عند بدء التشغيل."""
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT signal_name, correct_count, total_count
                    FROM signal_performance
                    WHERE total_count > 0
                """)
                for row in cur.fetchall():
                    _signal_perf[row[0]] = [int(row[1]), int(row[2])]
        logger.info(f"✅ Loaded {len(_signal_perf)} signal performance records")
    except Exception:
        pass  # الجدول قد لا يكون موجوداً بعد

def save_signal_perf_to_db():
    """يحفظ أداء الإشارات في قاعدة البيانات."""
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
# يحسب احتمالات الانتقال من آخر 3 نتائج → التالية
# ════════════════════════════════════════════════════════════════════
_markov_cache: Optional[Dict] = None
_markov_ts: float = 0.0

def build_markov_matrix() -> Dict:
    """يبني مصفوفة انتقال ثلاثية الترتيب من آخر 400 جولة."""
    global _markov_cache, _markov_ts
    if _markov_cache and time.time() - _markov_ts < 60:
        return _markov_cache
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT winner FROM history
                    WHERE winner IS NOT NULL
                    ORDER BY id DESC LIMIT 400
                """)
                raw = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
                raw.reverse()
        hist = [x for x in raw if x in [0, 1]]
        matrix: Dict[str, Dict[int, int]] = defaultdict(lambda: {0: 0, 1: 0})
        for i in range(len(hist) - 3):
            key = f"{hist[i]}{hist[i+1]}{hist[i+2]}"
            matrix[key][hist[i+3]] += 1
        _markov_cache = dict(matrix)
        _markov_ts    = time.time()
        return _markov_cache
    except Exception:
        return {}

def markov_predict(history: List[int]) -> Tuple[Optional[int], float, str]:
    """يستخدم سلسلة ماركوف للتنبؤ بالنتيجة التالية."""
    if len(history) < 3:
        return None, 0.0, ""
    key    = f"{history[-3]}{history[-2]}{history[-1]}"
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
# يكتشف دورات متكررة في التسلسل الحديث
# ════════════════════════════════════════════════════════════════════
def detect_cycle(history: List[int]) -> Tuple[Optional[int], float, str]:
    """
    يبحث عن دورة بطول 2-6 في التسلسل الأخير.
    إن وُجدت دورة → يتنبأ بالعنصر التالي.
    """
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
                conf = 0.70 + (cycle_len - 2) * 0.03  # دورات أطول = ثقة أعلى
                return pred, min(conf, 0.88), f"دورة طولها {cycle_len}"
    # كشف تبادل (R,B,R,B,...)
    if len(history) >= 4:
        last4 = history[-4:]
        if last4 == [0, 1, 0, 1] or last4 == [1, 0, 1, 0]:
            pred = 1 - history[-1]
            return pred, 0.72, "نمط تبادلي"
    return None, 0.0, ""

# ════════════════════════════════════════════════════════════════════
# 📡 المحرك 4: مضخّم الإجماع (Consensus Amplifier)
# عندما تتفق كل الإشارات → رفع الثقة بشكل كبير
# ════════════════════════════════════════════════════════════════════
def amplify_consensus(scores: Dict[int, float], signal_count: int) -> float:
    """
    يُعيد معامل تضخيم [1.0 – 1.8] بناءً على مدى الإجماع.
    كلما كانت الفجوة بين الطرفين أكبر وعدد الإشارات أكثر → تضخيم أعلى.
    """
    s0, s1    = scores[0], scores[1]
    total     = s0 + s1
    if total == 0:
        return 1.0
    dominance = abs(s0 - s1) / total   # 0 = تعادل تام، 1 = إجماع كامل
    sig_bonus = min(signal_count / 8, 1.0)
    amplifier = 1.0 + dominance * 0.6 * sig_bonus
    return min(amplifier, 1.8)

# ════════════════════════════════════════════════════════════════════
# 🧮 المحرك 5: بصمة b_num متعددة الأبعاد
# يستخرج 5 خصائص رياضية من رقم البونص دفعة واحدة
# ════════════════════════════════════════════════════════════════════
def bnum_fingerprint(b_num: str, rank: str) -> List[Tuple[int, float, str]]:
    """
    يحسب 5 قوانين رياضية من b_num ويُعيد قائمة من (pred, weight, label).
    """
    signals = []
    if not b_num:
        return signals

    digits   = [int(d) for d in b_num]
    d_sum    = sum(digits)
    d_prod   = 1
    for d in digits:
        d_prod = (d_prod * max(d, 1)) % 97   # mod لتجنب overflow
    rv       = RANK_VALUE.get(rank.upper(), 7)
    last_d   = digits[-1]
    first_d  = digits[0]

    # Q1: مجموع الأرقام mod 3
    r1 = d_sum % 3
    w1 = 0 if r1 in [0, 2] else 1
    signals.append((w1, 0.55, f"Σmod3={r1}"))

    # Q2: (مجموع + قيمة الرتبة) mod 4
    r2 = (d_sum + rv) % 4
    w2 = 0 if r2 in [0, 3] else 1
    signals.append((w2, 0.58, f"(Σ+rank)mod4={r2}"))

    # Q3: حاصل ضرب الأرقام mod 7
    r3 = d_prod % 7
    w3 = 0 if r3 in [0, 1, 6] else 1
    signals.append((w3, 0.52, f"Πmod7={r3}"))

    # Q4: (آخر رقم × أول رقم + قيمة الرتبة) mod 2
    r4 = (last_d * max(first_d, 1) + rv) % 2
    signals.append((r4, 0.54, f"(L×F+rv)mod2={r4}"))

    # Q5: عدد الأرقام الفردية mod 2
    odd_count = sum(1 for d in digits if d % 2 == 1)
    r5 = odd_count % 2
    w5 = 0 if r5 == 0 else 1
    signals.append((w5, 0.53, f"odds_mod2={r5}"))

    return signals

# ════════════════════════════════════════════════════════════════════
# 🔮 المحرك 6: مدير القوانين الذاتي (Auto-Law Manager)
# يُعطّل القوانين السيئة ويُعزّز الجيدة تلقائياً بعد كل نتيجة
# ════════════════════════════════════════════════════════════════════
def auto_manage_laws():
    """
    يُشغَّل بعد كل تسجيل نتيجة:
    - يُعطّل القوانين التي دقتها < 35% (ولُعبت > 5 مرات)
    - يرفع confidence القوانين التي دقتها > 80%
    """
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                # تعطيل القوانين السيئة
                cur.execute("""
                    UPDATE ai_laws SET active = FALSE
                    WHERE accuracy < 35 AND times_used > 5 AND active = TRUE
                """)
                disabled = cur.rowcount

                # تعزيز القوانين الممتازة
                cur.execute("""
                    UPDATE ai_laws
                    SET confidence = LEAST(99, confidence * 1.05)
                    WHERE accuracy > 80 AND times_used > 10 AND active = TRUE
                """)
                boosted = cur.rowcount

                conn.commit()
                if disabled or boosted:
                    load_laws(force=True)
                    logger.info(f"AutoLaw: disabled={disabled}, boosted={boosted}")
    except Exception as e:
        logger.warning(f"auto_manage_laws: {e}")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🧬 المحرك الخرافي 1: LOOKALIKE ENGINE                             ║
# ║  يبحث في 800 جولة سابقة عن أكثر المواضع تشابهاً مع الوضع الحالي  ║
# ║  ثم يُصوّت بنتائج تلك المواضع — Weighted K-Nearest Neighbor       ║
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
                cur.execute("""
                    SELECT winner FROM history
                    WHERE winner IS NOT NULL
                    ORDER BY id DESC LIMIT 800
                """)
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
# ║  يُشخّص نظام اللعبة الحالي: سيطرة / تبادل / فوضى                ║
# ║  ويُوصي بالاستراتيجية الأمثل تلقائياً                            ║
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
# ║  إن كانت دقة آخر 15 جولة < 38% → المحرك يعكس توقعاته            ║
# ║  مبدأ: إن كنت مخطئاً دائماً فالعكس صحيح                         ║
# ╚══════════════════════════════════════════════════════════════════════╝
def check_anti_mode() -> Tuple[bool, float]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT winner, prediction FROM history
                    WHERE winner IS NOT NULL AND prediction IS NOT NULL
                    ORDER BY id DESC LIMIT 15
                """)
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
# ║  يحسب P(winner | suit, digit) بيز كامل مع Laplace smoothing       ║
# ║  الأدق رياضياً لأنه يجمع Prior العام + Likelihood السياق الحالي   ║
# ╚══════════════════════════════════════════════════════════════════════╝
def bayesian_predict(suit: str, rank: str, last_digit: int) -> Tuple[Optional[int], float, str]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                # Prior
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

                # Likelihood: نفس البذلة + نفس الرقم
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
                cur.execute("""
                    SELECT winner, created_at FROM history
                    WHERE winner IS NOT NULL
                    ORDER BY id DESC LIMIT 4
                """)
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
    stream = await ai_client.chat.completions.create(
        model=AI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.15, max_tokens=150, seed=42, stream=True
    )
    full = ""
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            full += chunk.choices[0].delta.content
        if "}" in full:
            break
    data = extract_json_safe(full)
    if data and isinstance(data, dict):
        return int(data.get("winner", 2)), float(data.get("confidence", 50)), data.get("reason", "")
    return None, 0.0, "خطأ في قراءة الرد"


# ════════════════════════════════════════════════════════════════════
# 🕰️ المحرك الأسطوري 1: الارتباط الزمني (Temporal Autocorrelation)
# يحسب الارتباط بين النتيجة الحالية والنتائج قبل lag=1..15
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
# يبحث عن آخر 5 نتائج في التاريخ الكامل ويرى ما أعقبها
# ════════════════════════════════════════════════════════════════════
_ngram_cache: Dict[str, Tuple] = {}
_ngram_ts: float = 0.0

def ngram_db_predict(history: List[int]) -> Tuple[Optional[int], float, str]:
    global _ngram_cache, _ngram_ts
    clean = [x for x in history if x in [0, 1]]
    if len(clean) < 5:
        return None, 0.0, ""
    # حاول n=5 ثم n=4 ثم n=3
    for n in [5, 4, 3]:
        if len(clean) < n:
            continue
        key = "".join(map(str, clean[-n:]))
        cache_key = f"ngram_{key}"
        # TTL cache
        if cache_key in _ngram_cache and time.time() - _ngram_ts < 45:
            cached = _ngram_cache[cache_key]
            if cached[0] is not None:
                return cached
        # بحث في المصفوفة المحلية
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
# يبحث في DB عن جولات بنفس نطاق الفجوة ويرى ما أعقبها
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
# يحسب كم جولة مرّت منذ آخر ظهور لكل نتيجة
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
    # إذا غابت نتيجة لأكثر من 7 جولات، هي "متأخرة"
    overdue_0 = last_seen[0]
    overdue_1 = last_seen[1]
    # احسب المتوسط الطبيعي للغياب
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
# 📐 المحرك الأسطوري 5: معايرة الثقة بالأداء الفعلي
# يضبط الثقة بناءً على الدقة الحقيقية للبوت
# ════════════════════════════════════════════════════════════════════
def calibrate_confidence(raw_conf: int, scores: Dict[int, float]) -> int:
    # معامل الاستقرار: نسبة الفائز في النقاط
    total = scores[0] + scores[1]
    if total > 0:
        dominance = abs(scores[0] - scores[1]) / total
    else:
        dominance = 0.0
    # أداء البوت الفعلي
    overall = _signal_perf.get('OVERALL', [0, 0])
    if overall[1] >= 30:
        real_acc = overall[0] / overall[1]
        if real_acc < 0.48:
            raw_conf = max(55, int(raw_conf * 0.82))
        elif real_acc > 0.67:
            raw_conf = min(97, int(raw_conf * 1.08))
    # مكافأة الهيمنة القوية
    if dominance > 0.70:
        raw_conf = min(97, raw_conf + 4)
    elif dominance < 0.10:
        raw_conf = max(55, raw_conf - 5)
    return raw_conf


# ════════════════════════════════════════════════════════════════════
# 🎯 محرك v19-1: أنماط EXACT (بذلة+رتبة+رقم مجتمعة)
# يستخدم إحصائيات الثلاثية المجتمعة من pattern_stats
# ════════════════════════════════════════════════════════════════════
def exact_pattern_predict(suit: str, rank: str, last_digit: int) -> Tuple[Optional[int], float, str]:
    """يبحث عن نمط EXACT_{suit}_{rank}_{digit} في pattern_stats."""
    pattern_id = f"EXACT_{suit}_{rank}_{last_digit}"
    res = get_pattern(pattern_id)
    if res['w'] == 2 or res['c'] < 0.05:
        # جرّب بدون رقم: EXACT_{suit}_{rank}
        pattern_id2 = f"RANK_{rank}_SUIT_{suit}"
        res2 = get_pattern(pattern_id2)
        if res2['w'] != 2 and res2['c'] > 0.05:
            return res2['w'], res2['c'], f"EXACT≈{pattern_id2} {res2['log']}"
        return None, 0.0, ""
    return res['w'], res['c'], f"EXACT {pattern_id} {res['log']}"

# ════════════════════════════════════════════════════════════════════
# 🧬 محرك v19-2: N-Gram من قاعدة البيانات الكاملة
# يجلب آخر 600 جولة من DB لبحث أعمق
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
                cur.execute("""
                    SELECT winner FROM history
                    WHERE winner IS NOT NULL
                    ORDER BY id DESC LIMIT %s
                """, (n,))
                rows = cur.fetchall()
        hist = [WINNER_MAP.get(r[0], 2) for r in rows]
        hist.reverse()
        _full_history_cache = [x for x in hist if x in [0, 1]]
        _full_hist_ts = time.time()
        return _full_history_cache
    except Exception:
        return []

def deep_ngram_predict(recent: List[int]) -> Tuple[Optional[int], float, str]:
    """N-Gram في 600 جولة كاملة (أعمق من ngram_db_predict)."""
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
# عندما تتبدل النتيجة بسرعة 4+ مرات → انتقال نمط
# ════════════════════════════════════════════════════════════════════
def hot_switch_detector(history: List[int]) -> Tuple[Optional[int], float, str]:
    """يكتشف أنماط التبادل السريع ويتنبأ باستمراره أو كسره."""
    clean = [x for x in history if x in [0,1]]
    if len(clean) < 8:
        return None, 0.0, ""
    # عدد التبدّلات في آخر 8 جولات
    last8 = clean[-8:]
    switches = sum(1 for i in range(1, len(last8)) if last8[i] != last8[i-1])
    if switches >= 6:
        # تبادل شبه كامل — تابع النمط
        pred = 1 - last8[-1]
        return pred, 0.72, f"تبادل سريع ({switches}/7)"
    elif switches <= 1:
        # ثبات كامل — استمر
        pred = last8[-1]
        return pred, 0.68, f"ثبات كامل ({8-switches}/7)"
    return None, 0.0, ""

# ════════════════════════════════════════════════════════════════════
# 🧲 محرك v19-4: الجذب التاريخي (Historical Gravity)
# يحسب متوسط الفوز في آخر 50/100/200 جولة ويوجّه التوقع
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
# يجمع التوقعات النقطية من كل المحركات ويُعطي حكماً نهائياً
# ════════════════════════════════════════════════════════════════════
def dynamic_majority_vote(signals: List[Tuple[Optional[int], float, str]]) -> Tuple[Optional[int], float, int, int]:
    """
    يُعيد (pred, conf, agree_count, total_count).
    يُوزن كل صوت بثقته.
    """
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
async def predict(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b:
        return 2, 0, "❌ رقم بونص غير صالح"

    last_digit  = int(clean_b[-1])
    scores: Dict[int, float] = {0: 0.0, 1: 0.0}
    logs:   List[str]        = []

    # ── تاريخ حديث + فجوة b_num الأخيرة ────────────────────────────
    recent_history: List[int] = []
    b_gap:   Optional[float] = None
    gap_sec: Optional[float] = None
    round_index: int = 0
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT winner, b_num, created_at
                    FROM history
                    WHERE winner IS NOT NULL
                    ORDER BY id DESC LIMIT 20
                """)
                rows = cur.fetchall()
                if rows:
                    recent_history = [WINNER_MAP.get(r[0], 2) for r in rows]
                    recent_history.reverse()
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
                    # موضع الجولة
                    cur.execute("SELECT COUNT(*) FROM history WHERE winner IS NOT NULL")
                    round_index = cur.fetchone()[0]
    except Exception as e:
        logger.warning(f"History fetch: {e}")

    # ── تسجيل معلومات الفجوة في السجل ──────────────────────────────
    if b_gap is not None:
        gap_label = "🟢 متصلة" if b_gap < 500 else "🔴 منفصلة"
        logs.append(f"🔗 فجوة b_num: {int(b_gap)} ({gap_label})")
    if gap_sec is not None:
        logs.append(f"⏱️ فجوة زمنية: {gap_sec:.0f}ث {'(جولات مفقودة محتملة)' if gap_sec > 20 else ''}")

    # ── AI متوازٍ ────────────────────────────────────────────────────
    ai_task = asyncio.create_task(ai_predict(recent_history))

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
            scores[res['w']] += res['c'] * WEIGHTS[wkey]
            logs.append(f"{desc}: {WINNER_NAMES[res['w']]} {res['log']}")

    # ── 4. نتيجة AI الآني ───────────────────────────────────────────
    try:
        ai_pred, ai_conf, ai_log = await asyncio.wait_for(ai_task, timeout=0.8)
        if ai_pred in [0, 1]:
            scores[ai_pred] += (ai_conf / 100) * WEIGHTS['AI']
            logs.append(f"🤖 Devstral: {WINNER_NAMES[ai_pred]} — {ai_log}")
        else:
            logs.append(f"⚠️ Devstral: {ai_log}")
    except asyncio.TimeoutError:
        logs.append("⚠️ Devstral: لم يكتمل في الوقت المحدد")
    except Exception:
        logs.append("⚠️ Devstral: خطأ")

    # ── T1: كاشف الزخم الحقيقي ─────────────────────────────────────
    streak_pred, streak_conf = detect_real_streak(recent_history)
    if streak_pred is not None:
        w = get_adaptive_weight('STREAK', WEIGHTS['MOMENTUM'])
        scores[streak_pred] += streak_conf * w
        logs.append(f"⚡ كسر سلسلة: {WINNER_NAMES[streak_pred]} ({streak_conf:.0%}) w={w:.1f}")

    # ── T2: الذاكرة القصيرة ──────────────────────────────────────────
    mem_pred, mem_conf = short_memory_bias(recent_history)
    if mem_pred is not None:
        w = get_adaptive_weight('SHORT_MEM', 1.4)
        scores[mem_pred] += mem_conf * w
        logs.append(f"🧠 ذاكرة قصيرة: {WINNER_NAMES[mem_pred]} ({mem_conf:.0%})")

    # ── T3: انحياز البذلة الذكي ──────────────────────────────────────
    sb_pred, sb_conf = suit_bias_from_history(suit)
    if sb_pred is not None:
        w = get_adaptive_weight('SUIT_BIAS', 1.6)
        scores[sb_pred] += sb_conf * w
        logs.append(f"📊 انحياز البذلة: {WINNER_NAMES[sb_pred]} ({sb_conf:.0%})")

    # ── M1: ماركوف ───────────────────────────────────────────────────
    mkv_pred, mkv_conf, mkv_log = markov_predict(recent_history)
    if mkv_pred is not None:
        w = get_adaptive_weight('MARKOV', 2.2)
        scores[mkv_pred] += mkv_conf * w
        logs.append(f"🔗 {mkv_log} → {WINNER_NAMES[mkv_pred]} ({mkv_conf:.0%}) w={w:.1f}")

    # ── M2: كاشف الدورات ─────────────────────────────────────────────
    cyc_pred, cyc_conf, cyc_log = detect_cycle(recent_history)
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
        w = get_adaptive_weight('LOOKALIKE', 2.8)
        scores[lk_pred] += lk_conf * w
        logs.append(f"🧬 {lk_log} → {WINNER_NAMES[lk_pred]} ({lk_conf:.0%}) w={w:.1f}")

    # ── X2: Regime Detector ──────────────────────────────────────────
    regime, reg_conf = detect_regime(recent_history)
    rg_pred, rg_conf, rg_log = regime_vote(regime, reg_conf, recent_history)
    if rg_pred is not None:
        w = get_adaptive_weight('REGIME', 2.4)
        scores[rg_pred] += rg_conf * w
        regime_emoji = {"banker_streak":"🔴","player_streak":"🔵","alternating":"🔁","chaotic":"❓"}.get(regime,"")
        logs.append(f"🧠 النظام {regime_emoji}: {rg_log} ({rg_conf:.0%})")

    # ── X3: Bayesian Engine ───────────────────────────────────────────
    bay_pred, bay_conf, bay_log = bayesian_predict(suit, rank, last_digit)
    if bay_pred is not None:
        w = get_adaptive_weight('BAYESIAN', 2.6)
        scores[bay_pred] += bay_conf * w
        logs.append(f"📊 بايز: {bay_log} → {WINNER_NAMES[bay_pred]} ({bay_conf:.0%})")

    # ── N1: الارتباط الزمني ──────────────────────────────────────────
    ac_pred, ac_conf, ac_log = temporal_autocorr(recent_history)
    if ac_pred is not None:
        w = get_adaptive_weight('AUTOCORR', 2.0)
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
        ac_pred, ng_pred, gh_pred, od_pred
    ] if x is not None)
    consensus = amplify_consensus(scores, active_signal_count)
    if consensus > 1.05:
        dominant = 0 if scores[0] >= scores[1] else 1
        scores[dominant] *= consensus
        logs.append(f"📡 إجماع ×{consensus:.2f} ({active_signal_count}/9 إشارات)")

    # ── X4: Anti-Mode (الانعكاس التلقائي) ────────────────────────────
    anti_active, recent_acc = check_anti_mode()
    pre_anti_final = 0 if scores[0] >= scores[1] else 1
    if anti_active:
        scores[0], scores[1] = scores[1], scores[0]   # اعكس كل الأوزان
        logs.append(f"🔃 وضع الانعكاس (دقة حالية {recent_acc:.0%}) — تم عكس التوقع")
    elif recent_acc > 0.62:
        logs.append(f"✅ دقة حالية ممتازة: {recent_acc:.0%}")

    # ── V1: أنماط EXACT ─────────────────────────────────────────────
    ex_pred, ex_conf, ex_log = exact_pattern_predict(suit, rank, last_digit)
    if ex_pred is not None:
        w = get_adaptive_weight('EXACT', 2.6)
        scores[ex_pred] += ex_conf * w
        logs.append(f"🎯 EXACT: {ex_log} → {WINNER_NAMES[ex_pred]} ({ex_conf:.0%})")

    # ── V2: DeepNGram (600 جولة) ─────────────────────────────────
    dn_pred, dn_conf, dn_log = deep_ngram_predict(recent_history)
    if dn_pred is not None:
        w = get_adaptive_weight('DEEP_NGRAM', 2.8)
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
        w = get_adaptive_weight('GRAVITY', 1.5)
        scores[gv_pred] += gv_conf * w
        logs.append(f"🧲 {gv_log} ({gv_conf:.0%})")

    # ── V5: تصويت الأغلبية الديناميكي ─────────────────────────
    all_point_signals = [
        (mom_pred, 0.85, "mom"), (streak_pred, streak_conf if 'streak_conf' in dir() else 0.0, "streak"),
        (mkv_pred, mkv_conf, "mkv"), (cyc_pred, cyc_conf if 'cyc_pred' in dir() and cyc_pred is not None else 0.0, "cyc"),
        (ng_pred, ng_conf if 'ng_pred' in dir() and ng_pred is not None else 0.0, "ng"),
        (dn_pred, dn_conf, "dn"), (gv_pred, gv_conf, "gv"),
        (ac_pred, ac_conf if 'ac_pred' in dir() and ac_pred is not None else 0.0, "ac"),
    ]
    mv_pred, mv_conf, mv_agree, mv_total = dynamic_majority_vote(all_point_signals)
    if mv_pred is not None and mv_total >= 4:
        mv_boost = mv_conf * 1.8 * (mv_agree / max(mv_total, 1))
        scores[mv_pred] += mv_boost
        logs.append(f"🏆 أغلبية: {WINNER_NAMES[mv_pred]} ({mv_agree}/{mv_total} محركات، ثقة {mv_conf:.0%})")

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
    final       = 0 if scores[0] >= scores[1] else 1

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
        'OVERALL': final,
    })
    logs.append(f"__signals__{signal_json}")

    return final, final_conf, "\n".join(logs)

# ==================== تنسيق الرسائل الأسطوري ====================
CONFIDENCE_TIER = [
    (90, "🔥 عالية جداً",  "▓▓▓▓▓▓▓▓▓▓"),
    (80, "⚡ عالية",       "▓▓▓▓▓▓▓▓░░"),
    (70, "✅ متوسطة-عالية","▓▓▓▓▓▓░░░░"),
    (60, "📊 متوسطة",      "▓▓▓▓░░░░░░"),
    (0,  "❓ ضعيفة",       "▓▓░░░░░░░░"),
]

def confidence_display(conf: int):
    for threshold, label, bar in CONFIDENCE_TIER:
        if conf >= threshold:
            return label, bar
    return "❓ ضعيفة", "▓▓░░░░░░░░"

def format_prediction(pred: int, conf: int, reason: str,
                      suit: str, rank: str, b_num: str) -> str:
    ld         = get_last_digit(b_num)
    name       = WINNER_NAMES[pred]
    laws_count = len(load_laws())
    sig_count  = len([v for v in _signal_perf.values() if v[1] > 0])
    conf_label, conf_bar = confidence_display(conf)

    # فرز سطور التحليل — أخفِ السطر المخفي
    analysis_lines = [
        l for l in reason.split("\n")
        if l.strip() and not l.startswith("__signals__")
    ]
    # تمييز: الأولوية لسطور تتفق مع التوقع النهائي
    pred_symbol = "🔴" if pred == 0 else "🔵"
    agree   = [l for l in analysis_lines if pred_symbol in l]
    disagree= [l for l in analysis_lines if pred_symbol not in l and "🔗" not in l and "⏱️" not in l][:3]
    context = [l for l in analysis_lines if "🔗" in l or "⏱️" in l]

    analysis_txt = ""
    if agree:
        analysis_txt += "\n".join(agree[:8]) + "\n"
    if disagree:
        analysis_txt += "\n".join(disagree[:3]) + "\n"
    if context:
        analysis_txt += "\n".join(context) + "\n"

    if sig_count >= 10:  engine_status = "⚡ 13 محرك نشط"
    elif sig_count >= 6: engine_status = "🔄 محركات متقدمة"
    else:                engine_status = "🔧 تعلم أولي"

    header_emoji = "🔴" if pred == 0 else "🔵"

    return (
        f"{'━'*22}\n"
        f"{header_emoji}  <b>التوقع: {name}</b>  {header_emoji}\n"
        f"{'━'*22}\n"
        f"🃏 {suit} {rank}  |  #{b_num}  |  رقم: {ld}\n"
        f"\n"
        f"📊 الثقة: <b>{conf}%</b>  {conf_label}\n"
        f"<code>{conf_bar}</code>\n"
        f"\n"
        f"⚙️ {engine_status}  |  ⚖️ {laws_count} قانون\n"
        f"{'━'*22}\n"
        f"<b>📋 التحليل ({len(agree)} موافق / {len(disagree)} معارض):</b>\n"
        f"{analysis_txt}"
        f"{'━'*22}"
    )

def result_keyboard(pred: int, b_num: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ الراعي 🔴", callback_data=f"save_0_{b_num}"),
            InlineKeyboardButton("✅ الثور 🔵",  callback_data=f"save_1_{b_num}"),
            InlineKeyboardButton("✅ تعادل ⚪",  callback_data=f"save_2_{b_num}"),
        ],
        [InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")],
    ])

# ==================== معالجات تيليجرام ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    laws_count = len(load_laws())
    active_data_laws = len([l for l in DATA_LAWS if l.get("active")])
    await update.message.reply_text(
        f"<b>🧠 HADES V19 — نظام التنبؤ الأسطوري</b>\n"
        f"{'━'*24}\n"
        f"⚙️ <b>المحركات النشطة: 17</b>\n"
        f"  ⚖️ قوانين AI: <b>{laws_count}</b>  |  📊 قوانين بيانات: <b>{active_data_laws}</b>\n"
        f"  🔗 ماركوف  |  🔄 دورات  |  🧬 DeepNGram\n"
        f"  🕰️ ارتباط زمني  |  🎯 EXACT  |  🏆 أغلبية\n"
        f"  ⚡ Hot-Switch  |  🧲 جذب تاريخي  |  ⏳ متأخر\n"
        f"{'━'*24}\n"
        f"📋 <b>الأوامر:</b>\n"
        f"  🎮 /start — بدء جولة جديدة\n"
        f"  📊 /stats — لوحة الإحصاءات الحية\n"
        f"  ⚖️ /laws  — عرض القوانين النشطة\n"
        f"  📥 /download — تصدير قاعدة البيانات\n"
        f"  🔬 /force_learn — تعلم عميق (مشرف)\n"
        f"  ✂️ /prune — تنظيف القوانين الميتة (مشرف)\n"
        f"  🔄 /reset_laws — إعادة تعيين (مشرف)\n"
        f"{'━'*24}\n"
        f"🎴 اختر البذلة للبدء:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(SUITS[i], callback_data=f"suit_{i}")
            for i in range(len(SUITS))
        ]])
    )

async def cmd_force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعليم عميق من كل الجولات — لا حد زمني."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return

    msg = await update.message.reply_text(
        "🧠 <b>بدء جلسة التعلم العميق...</b>\n"
        "سيتم تحليل كل الجولات السابقة واستخراج قوانين ذكية.\n"
        "<i>لا تُلغِ العملية — قد تستغرق عدة دقائق.</i>",
        parse_mode="HTML"
    )

    # دالة لتحديث رسالة الحالة
    async def status_update(text: str):
        try:
            await msg.edit_text(text, parse_mode="HTML")
        except Exception:
            pass

    result = await force_learn_engine(status_update)

    if "error" in result:
        await msg.edit_text(
            f"❌ <b>فشلت جلسة التعلم</b>\n\n<code>{result['error']}</code>",
            parse_mode="HTML"
        )
        return

    # بناء ملخص القوانين المُنشأة
    sample_text = ""
    for i, law in enumerate(result.get("sample_laws", []), 1):
        pred_name = WINNER_NAMES.get(law.get("prediction", 2), "?")
        sample_text += (
            f"\n<b>{i}.</b> [{law.get('law_type','?')}] → {pred_name} "
            f"({law.get('confidence',0):.0f}%)\n"
            f"   <i>{law.get('description','')[:80]}</i>"
        )

    await msg.edit_text(
        f"✅ <b>اكتملت جلسة التعلم العميق!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎮 الجولات المحللة: <b>{result['total_rounds']}</b>\n"
        f"⚖️ قوانين جديدة حُفظت: <b>{result['laws_saved']}</b>\n"
        f"⏭️ قوانين مرفوضة: <b>{result['laws_skipped']}</b>\n"
        f"🆔 رقم الجلسة: <b>#{result.get('session_id', '?')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>عينة من القوانين المكتشفة:</b>"
        f"{sample_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 الذاكرة السياقية تم تحديثها — التنبؤات القادمة ستستفيد من هذه القوانين.",
        parse_mode="HTML"
    )

async def cmd_engine_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض حالة كل المحركات وأداؤها الحالي."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return

    anti_active, recent_acc = check_anti_mode()
    regime_str = "غير محدد"
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT winner FROM history WHERE winner IS NOT NULL
                    ORDER BY id DESC LIMIT 20
                """)
                hist = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
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

    # أداء الإشارات
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
        f"  + Markov • Cycle • Streak • MemShort • SuitBias • Laws"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def cmd_laws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القوانين النشطة."""
    laws = load_laws(force=True)
    if not laws:
        await update.message.reply_text("⚠️ لا توجد قوانين نشطة. استخدم /force_learn أولاً.")
        return

    text = f"⚖️ <b>القوانين الذكية النشطة ({len(laws)})</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, law in enumerate(laws[:15], 1):
        pred_name = WINNER_NAMES.get(law["prediction"], "?")
        text += (
            f"\n<b>#{law['id']}</b> [{law['law_type']}] → {pred_name}\n"
            f"  دقة: {law['accuracy']:.0f}% | استخدام: {law['times_used']}\n"
            f"  <i>{law['description'][:70]}</i>\n"
        )
    if len(laws) > 15:
        text += f"\n<i>... و{len(laws)-15} قانون إضافي</i>"

    await update.message.reply_text(text, parse_mode="HTML")

# ── helper: تعديل آمن ────────────────────────────────────────────────────────
async def safe_edit(query, text: str, reply_markup=None):
    from telegram.error import BadRequest
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error(f"safe_edit: {e}")
    except Exception as e:
        logger.error(f"safe_edit: {e}")

# ==================== Callback Handler ====================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    data = query.data
    logger.info(f"CB [{query.from_user.id}]: {data!r}")

    try:
        if data == "choose_suit":
            context.user_data.pop('suit', None)
            context.user_data.pop('rank', None)
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(SUITS[i], callback_data=f"suit_{i}")
                for i in range(len(SUITS))
            ]])
            await safe_edit(query, "🎴 اختر البذلة:", reply_markup=kb)

        elif data.startswith("suit_"):
            idx  = int(data.split("_")[1])
            suit = SUITS[idx]
            context.user_data['suit']     = suit
            context.user_data['suit_idx'] = idx
            rows = [
                [InlineKeyboardButton(r, callback_data=f"rank_{r}") for r in row]
                for row in RANKS_LAYOUT
            ]
            rows.append([InlineKeyboardButton("🔙 تغيير البذلة", callback_data="choose_suit")])
            await safe_edit(
                query, f"البذلة: <b>{suit}</b>\nاختر الرتبة:",
                reply_markup=InlineKeyboardMarkup(rows)
            )

        elif data.startswith("rank_"):
            rank     = data[5:]
            suit     = context.user_data.get('suit', '?')
            suit_idx = context.user_data.get('suit_idx', 0)
            context.user_data['rank'] = rank
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 تغيير الرتبة", callback_data=f"suit_{suit_idx}")
            ]])
            await safe_edit(
                query,
                f"✅ البذلة: <b>{suit}</b>  |  الرتبة: <b>{rank}</b>\n\n"
                f"📩 أرسل رقم البونص (مثال: <code>7022088</code>)",
                reply_markup=kb
            )

        elif data.startswith("save_"):
            parts  = data.split("_", 2)
            winner = int(parts[1])
            b_num  = parts[2] if len(parts) > 2 else context.user_data.get('last_b_num', '')
            suit   = context.user_data.get('suit', '')
            rank   = context.user_data.get('rank', '')
            pred   = context.user_data.get('last_pred', 2)

            if not (b_num and suit and rank):
                await safe_edit(query, "❌ بيانات ناقصة — اضغط /start")
                return

            last_digit = get_last_digit(b_num)
            correct    = (winner == pred)

            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO history
                                (b_num, suit, rank, bonus_last_digit, winner,
                                 prediction, user_id, timestamp, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                            RETURNING id
                        """, (b_num, suit, rank, last_digit,
                              WINNER_NAMES[winner], WINNER_NAMES.get(pred, ''),
                              query.from_user.id))
                        saved_id = cur.fetchone()[0]
                        conn.commit()
                        # ✅ احفظ ID الجولة في context للحذف السريع لاحقاً
                        context.user_data['last_saved_id']   = saved_id
                        context.user_data['last_saved_time'] = __import__('time').time()
            except Exception as e:
                logger.error(f"Save error: {e}")

            update_pattern_db(suit, rank, last_digit, winner)

            # تحديث دقة القوانين التي انطبقت
            laws = load_laws()
            recent_hist: List[int] = []
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT winner FROM history
                            WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 20
                        """)
                        recent_hist = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
                        recent_hist.reverse()
            except Exception:
                pass

            for law in laws:
                match = match_law(law, suit, rank, last_digit, recent_hist)
                if match >= 0.5:
                    update_law_accuracy(law["id"], law["prediction"] == winner)

            # تحديث أداء الإشارات من آخر توقع
            pred_signal = context.user_data.get('last_signals', {})
            for sig_name, sig_pred in pred_signal.items():
                if sig_pred in [0, 1]:
                    update_signal_perf(sig_name, sig_pred == winner)
            save_signal_perf_to_db()

            # مدير القوانين الذاتي
            auto_manage_laws()

            verdict = "<b>صحيح! 🎯</b>" if correct else "خاطئ ❌"
            icon    = "✅" if correct else "❌"
            # احسب الدقة الحديثة (آخر 20 جولة)
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT winner, prediction FROM history
                            WHERE winner IS NOT NULL AND prediction IS NOT NULL
                            ORDER BY id DESC LIMIT 20
                        """)
                        recent_results = cur.fetchall()
                recent_acc = sum(1 for r in recent_results if r[0] == r[1]) / max(len(recent_results), 1)
                streak_disp = "".join("✅" if r[0]==r[1] else "❌" for r in recent_results[:10])
                acc_txt = f"\n📈 دقة آخر 20: <b>{recent_acc:.0%}</b>  <code>{streak_disp}</code>"
            except Exception:
                acc_txt = ""
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit"),
                 InlineKeyboardButton("📊 إحصاءات",    callback_data="stats")],
            ])
            await safe_edit(
                query,
                f"{icon} <b>{WINNER_NAMES[winner]}</b>  ({verdict})\n"
                f"التوقع: {WINNER_NAMES.get(pred, '?')}  |  {suit} {rank}  |  #{b_num}{acc_txt}",
                reply_markup=kb
            )

        elif data == "stats":
            await safe_edit(query, "⏳ جارٍ تحميل الإحصاءات...")
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT COUNT(*) FROM history")
                        total = cur.fetchone()[0]
                        cur.execute("SELECT winner, COUNT(*) FROM history WHERE winner IS NOT NULL GROUP BY winner")
                        dist = {r[0]: r[1] for r in cur.fetchall()}
                        cur.execute("SELECT COUNT(*) FROM history WHERE winner IS NOT NULL AND prediction IS NOT NULL AND winner::text = prediction::text")
                        correct_cnt = cur.fetchone()[0]
                        cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                        laws_cnt = cur.fetchone()[0]
                        cur.execute("SELECT COUNT(*), MAX(created_at) FROM learn_sessions")
                        ls = cur.fetchone()
                        sessions_cnt, last_learn_time = ls
                        cur.execute("SELECT winner, prediction FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 15")
                        last15 = cur.fetchall()
                        cur.execute("SELECT signal_name, correct_count, total_count FROM signal_performance WHERE total_count >= 5 ORDER BY (correct_count::float/total_count) DESC LIMIT 5")
                        sig_rows = cur.fetchall()

                r_cnt  = dist.get("الراعي 🔴", 0)
                b_cnt  = dist.get("الثور 🔵",  0)
                t_cnt  = dist.get("تعادل ⚪",  0)
                played = max(r_cnt + b_cnt + t_cnt, 1)
                acc    = round(correct_cnt / max(played, 1) * 100, 1)
                last_l = last_learn_time.strftime("%Y-%m-%d %H:%M") if last_learn_time else "لم يُجرَ"
                streak_str = ""
                for row in last15:
                    w = WINNER_MAP.get(row[0], 2)
                    p = WINNER_MAP.get(row[1], 2) if row[1] else -1
                    streak_str += ("✅" if w == p else ("⬜" if p == -1 else "❌"))
                sig_txt = ""
                for sig in sig_rows:
                    sn, sc, st = sig
                    sa = round(sc / max(st, 1) * 100)
                    sig_txt += f"  {sn}: {sa}%\n"
                if acc >= 65:   perf = "🏆"
                elif acc >= 55: perf = "✅"
                else:           perf = "⚠️"
                msg = (
                    f"<b>🧠 HADES الإحصاءات</b>\n{'━'*20}\n"
                    f"🎮 {total} جولة  |  {perf} دقة: <b>{acc}%</b>\n"
                    f"🔴{r_cnt}  🔵{b_cnt}  ⚪{t_cnt}\n"
                    f"آخر 15: <code>{streak_str}</code>\n{'━'*20}\n"
                    f"⚖️ قوانين: <b>{laws_cnt}</b>  |  جلسات: <b>{sessions_cnt}</b>\n"
                    f"🕐 آخر تعلم: <b>{last_l}</b>\n"
                    + (f"{'━'*20}\n📡 أفضل محركات:\n{sig_txt}" if sig_txt else "")
                    + f"{'━'*20}"
                )
            except Exception as e:
                msg = f"❌ خطأ: <code>{e}</code>"

            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit"),
                InlineKeyboardButton("🔄 تحديث", callback_data="stats"),
            ]])
            await safe_edit(query, msg, reply_markup=kb)

        elif data.startswith("del_confirm_"):
            target_id = int(data.split("_")[2])
            await safe_edit(query, f"⏳ جارٍ الحذف...", reply_markup=None)
            # جلب بيانات الجولة أولاً
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id, b_num, suit, rank, bonus_last_digit,
                                   winner, prediction, created_at, user_id
                            FROM history WHERE id = %s
                        """, (target_id,))
                        r = cur.fetchone()
            except Exception as e:
                await safe_edit(query, f"❌ خطأ: <code>{e}</code>")
                return
            if not r:
                await safe_edit(query, f"⚠️ لا توجد جولة بالـ ID {target_id}.")
                return
            _, bnum, suit, rank, digit, winner_str, pred_str, created_at, _ = r
            t = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "?"
            res = await _exec_delete(target_id, bnum, suit, rank, digit,
                                     winner_str, pred_str, created_at)
            if res["error"]:
                await safe_edit(query, f"❌ خطأ: <code>{res['error']}</code>")
            else:
                await safe_edit(
                    query,
                    f"✅ <b>تم الحذف — كأن الجولة لم تحدث</b>"
                    f"{'━'*22}"
                    f"🔑 B_NUM: <code>{bnum}</code>  |  🕐 {t}"
                    f"🃏 {suit or '?'} {rank or '?'}  |  🏆 {winner_str}"
                    f"{'━'*22}"
                    f"♻️ rollback: <b>{res['rolled_back']}</b> نمط  |  ⚖️ <b>{res['laws_adjusted']}</b> قانون",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🗑️ حذف أخرى", callback_data="del_list"),
                        InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit"),
                    ]])
                )

        elif data == "del_list":
            # عرض قائمة الجولات الأخيرة
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id, b_num, suit, rank, bonus_last_digit,
                                   winner, prediction, created_at, user_id
                            FROM history
                            WHERE rank IS NOT NULL AND rank != 'NULL'
                              AND suit IS NOT NULL
                            ORDER BY created_at DESC, id DESC LIMIT 8
                        """)
                        rows = cur.fetchall()
            except Exception as e:
                await safe_edit(query, f"❌ خطأ: <code>{e}</code>")
                return
            if not rows:
                await safe_edit(query, "⚠️ لا توجد جولات.")
                return
            buttons = [[InlineKeyboardButton(_delete_row_label(r),
                        callback_data=f"del_confirm_{r[0]}")] for r in rows]
            buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel")])
            await safe_edit(query, "🗑️ <b>اختر الجولة للحذف:</b>",
                            reply_markup=InlineKeyboardMarkup(buttons))

        elif data == "del_cancel":
            await safe_edit(query, "✅ تم الإلغاء.")

        elif data == "del_more":
            # إعادة عرض قائمة الجولات للحذف
            uid = query.from_user.id
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id, b_num, suit, rank, bonus_last_digit,
                                   winner, prediction, created_at, user_id
                            FROM history
                            WHERE rank IS NOT NULL AND rank != 'NULL'
                              AND suit IS NOT NULL
                            ORDER BY id DESC LIMIT 5
                        """)
                        rows = cur.fetchall()
                        if not rows:
                            cur.execute("""
                                SELECT id, b_num, suit, rank, bonus_last_digit,
                                       winner, prediction, created_at, user_id
                                FROM history ORDER BY id DESC LIMIT 5
                            """)
                            rows = cur.fetchall()
            except Exception as e:
                await safe_edit(query, f"❌ خطأ: <code>{e}</code>")
                return
            if not rows:
                await safe_edit(query, "⚠️ لا توجد جولات إضافية.")
                return
            buttons = []
            for row in rows:
                label = _delete_row_label(row)
                buttons.append([InlineKeyboardButton(label, callback_data=f"del_confirm_{row[0]}")])
            buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel")])
            await safe_edit(
                query,
                f"🗑️ <b>اختر الجولة التي تريد حذفها:</b>",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        else:
            logger.warning(f"Unhandled callback: {data!r}")

    except Exception as e:
        logger.error(f"callback_handler crash [{data}]: {e}", exc_info=True)
        try:
            await safe_edit(query, f"⚠️ خطأ: <code>{str(e)[:200]}</code>")
        except Exception:
            pass

# ==================== Message Handler ====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    suit = context.user_data.get('suit')
    rank = context.user_data.get('rank')

    if not suit or not rank:
        await update.message.reply_text(
            "ابدأ بالضغط على /start واختيار البذلة والرتبة."
        )
        return

    b_num = clean_digits(text)
    if not b_num:
        await update.message.reply_text("❌ أرسل رقم البونص فقط.")
        return

    context.user_data['last_b_num'] = b_num
    wait_msg = await update.message.reply_text("🔄 جارٍ التحليل...")

    try:
        pred, conf, reason = await predict(b_num, suit, rank)
        context.user_data['last_pred'] = pred
        # استخرج بيانات الإشارات من السطر المخفي
        signals_data = {}
        clean_reason_lines = []
        for line in reason.split("\n"):
            if line.startswith("__signals__"):
                try:
                    signals_data = json.loads(line[11:])
                except Exception:
                    pass
            else:
                clean_reason_lines.append(line)
        context.user_data['last_signals'] = signals_data
        clean_reason = "\n".join(clean_reason_lines)

        await wait_msg.delete()
        await update.message.reply_text(
            format_prediction(pred, conf, clean_reason, suit, rank, b_num),
            parse_mode="HTML",
            reply_markup=result_keyboard(pred, b_num)
        )
    except Exception as e:
        logger.error(f"predict error: {e}", exc_info=True)
        await wait_msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")


# ==================== /stats: لوحة الإحصاءات الأسطورية ====================
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لوحة إحصاءات حية شاملة."""
    msg = await update.message.reply_text("⏳ جارٍ تحميل الإحصاءات...")
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM history")
                total = cur.fetchone()[0]
                cur.execute("""
                    SELECT winner, COUNT(*) FROM history
                    WHERE winner IS NOT NULL GROUP BY winner
                """)
                dist = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute("""
                    SELECT COUNT(*) FROM history
                    WHERE winner IS NOT NULL
                      AND prediction IS NOT NULL
                      AND winner::text = prediction::text
                """)
                correct_cnt = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                laws_cnt = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = FALSE")
                inactive_cnt = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*), MAX(created_at) FROM learn_sessions")
                ls = cur.fetchone()
                sessions_cnt, last_learn_time = ls
                # آخر 20 جولة للتحليل
                cur.execute("""
                    SELECT winner, prediction FROM history
                    WHERE winner IS NOT NULL
                    ORDER BY id DESC LIMIT 20
                """)
                last20 = cur.fetchall()
                # أفضل 5 قوانين
                cur.execute("""
                    SELECT law_type, prediction, accuracy, times_used
                    FROM ai_laws WHERE active = TRUE AND times_used > 2
                    ORDER BY accuracy DESC LIMIT 5
                """)
                top_laws = cur.fetchall()
                # أداء المحركات
                cur.execute("""
                    SELECT signal_name, correct_count, total_count
                    FROM signal_performance
                    WHERE total_count >= 5
                    ORDER BY (correct_count::float / total_count) DESC LIMIT 8
                """)
                sig_rows = cur.fetchall()

        r_cnt  = dist.get("الراعي 🔴", 0)
        b_cnt  = dist.get("الثور 🔵",  0)
        t_cnt  = dist.get("تعادل ⚪",  0)
        played = max(r_cnt + b_cnt + t_cnt, 1)
        acc    = round(correct_cnt / max(played, 1) * 100, 1)
        last_l = last_learn_time.strftime("%Y-%m-%d %H:%M") if last_learn_time else "لم يُجرَ"

        # سلسلة آخر 20 جولة
        streak_str = ""
        correct_streak = 0
        for row in last20:
            w = WINNER_MAP.get(row[0], 2)
            p = WINNER_MAP.get(row[1], 2) if row[1] else -1
            if w == p:
                streak_str += "✅"
                correct_streak += 1
            elif p == -1:
                streak_str += "⬜"
            else:
                streak_str += "❌"
                correct_streak = 0

        # أداء المحركات
        sig_txt = ""
        for sig in sig_rows:
            name, corr, tot = sig
            sig_acc = round(corr / max(tot, 1) * 100, 1)
            bar = "█" * int(sig_acc / 10) + "░" * (10 - int(sig_acc / 10))
            sig_txt += f"  <code>{name:<12}</code> {sig_acc:>5.1f}% {bar}\n"

        # أفضل القوانين
        laws_txt = ""
        for l in top_laws:
            pred_icon = "🔴" if l[1] == 0 else "🔵"
            laws_txt += f"  {pred_icon} [{l[0]}] acc={l[2]:.0f}% ×{l[3]}\n"

        # تحديد مستوى الأداء
        if acc >= 65:   perf_emoji = "🏆 ممتاز"
        elif acc >= 58: perf_emoji = "✅ جيد"
        elif acc >= 50: perf_emoji = "📊 متوسط"
        else:           perf_emoji = "⚠️ ضعيف"

        text = (
            f"<b>🧠 HADES — لوحة الإحصاءات الأسطورية</b>\n"
            f"{'━'*24}\n"
            f"🎮 الجولات: <b>{total}</b>  |  🎯 الدقة: <b>{acc}%</b>  {perf_emoji}\n"
            f"🔴 الراعي: {r_cnt} ({round(r_cnt/played*100,1)}%)  "
            f"🔵 الثور: {b_cnt} ({round(b_cnt/played*100,1)}%)  "
            f"⚪ تعادل: {t_cnt}\n"
            f"{'━'*24}\n"
            f"📅 آخر 20 جولة:\n<code>{streak_str}</code>\n"
            f"{'━'*24}\n"
            f"⚖️ القوانين: <b>{laws_cnt}</b> نشط / {inactive_cnt} معطّل\n"
            f"📚 جلسات تعلم: <b>{sessions_cnt}</b>  |  آخر: <b>{last_l}</b>\n"
        )
        if laws_txt:
            text += f"{'━'*24}\n🏅 أفضل القوانين:\n{laws_txt}"
        if sig_txt:
            text += f"{'━'*24}\n📡 أداء المحركات:\n{sig_txt}"
        text += f"{'━'*24}"

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit"),
            InlineKeyboardButton("🔄 تحديث",       callback_data="stats"),
        ]])
        await msg.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.error(f"cmd_stats: {e}", exc_info=True)
        await msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")


# ════════════════════════════════════════════════════════════════════
# ✂️ /prune: تنظيف القوانين الميتة (ADMIN)
# ════════════════════════════════════════════════════════════════════
async def cmd_prune(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    msg = await update.message.reply_text("✂️ جارٍ تنظيف القوانين الميتة...")
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                # عدّ إجمالي الجولات
                cur.execute("SELECT COUNT(*) FROM history WHERE winner IS NOT NULL")
                total_rounds = cur.fetchone()[0]
                # احذف القوانين التي لم تُستخدم قط بعد 100+ جولة
                cur.execute("""
                    UPDATE ai_laws SET active = FALSE
                    WHERE times_used = 0
                      AND created_at < NOW() - INTERVAL '2 hours'
                      AND active = TRUE
                """)
                dead_by_usage = cur.rowcount
                # احذف القوانين دقتها < 30% وتمت أكثر من 8 مرات
                cur.execute("""
                    UPDATE ai_laws SET active = FALSE
                    WHERE accuracy < 30 AND times_used >= 8 AND active = TRUE
                """)
                dead_by_acc = cur.rowcount
                # احذف قوانين مكررة (نفس law_type + prediction، احتفظ بالأفضل)
                cur.execute("""
                    WITH ranked AS (
                        SELECT id, law_type, prediction,
                               ROW_NUMBER() OVER (
                                   PARTITION BY law_type, prediction
                                   ORDER BY accuracy DESC, times_used DESC
                               ) as rn
                        FROM ai_laws WHERE active = TRUE
                    )
                    UPDATE ai_laws SET active = FALSE
                    WHERE id IN (
                        SELECT id FROM ranked WHERE rn > 3
                    )
                """)
                dead_dupes = cur.rowcount
                conn.commit()
                # احسب الباقي
                cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                remaining = cur.fetchone()[0]
        load_laws(force=True)
        await msg.edit_text(
            f"✅ <b>تنظيف اكتمل</b>"
            f"━━━━━━━━━━━━━━━━━━━━━━"
            f"💤 لم تُستخدم قط:   <b>{dead_by_usage}</b>"
            f"📉 دقة ضعيفة (<30%): <b>{dead_by_acc}</b>"
            f"♻️ مكررة:            <b>{dead_dupes}</b>"
            f"━━━━━━━━━━━━━━━━━━━━━━"
            f"⚖️ القوانين الباقية: <b>{remaining}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"prune error: {e}", exc_info=True)
        await msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

# ════════════════════════════════════════════════════════════════════
# 🔄 /reset_laws: إعادة تعيين القوانين وبدء من جديد (ADMIN)
# ════════════════════════════════════════════════════════════════════
async def cmd_reset_laws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return
    args = context.args or []
    if 'confirm' not in args:
        await update.message.reply_text(
            "⚠️ هذا سيُعطّل جميع القوانين!"
            "للتأكيد اكتب: <code>/reset_laws confirm</code>",
            parse_mode="HTML"
        )
        return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE ai_laws SET active = FALSE")
                n = cur.rowcount
                conn.commit()
        load_laws(force=True)
        await update.message.reply_text(
            f"✅ تم تعطيل <b>{n}</b> قانون."
            f"الآن شغّل /force_learn لبدء تعلم جديد.",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")


# ════════════════════════════════════════════════════════════════════
# 🗑️ /delete — حذف جولة برقم البونص مباشرة
#
#  الاستخدام:
#   /delete 7888847   ← يحذف الجولة التي b_num = 7888847
#   /delete           ← يطلب منك إرسال رقم البونص
# ════════════════════════════════════════════════════════════════════

async def _exec_delete(rid: int, bnum: str, suit: str, rank, digit,
                       winner_str: str, pred_str, created_at) -> dict:
    """ينفّذ الحذف الكامل + rollback."""
    result = {"rolled_back": 0, "laws_adjusted": 0, "error": None}
    try:
        winner_int = WINNER_MAP.get(winner_str, 2)
        digit_int  = int(digit) if digit is not None else 0

        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM history WHERE id = %s", (rid,))

                # rollback pattern_stats
                col = {0:"red_count", 1:"blue_count", 2:"tie_count"}.get(winner_int)
                if col and suit and rank:
                    for pid in [f"SUIT_{suit}", f"DIGIT_{digit_int}",
                                f"RANK_{rank}", f"SD_{suit}_{digit_int}"]:
                        cur.execute(f"""
                            UPDATE pattern_stats
                            SET {col} = GREATEST(0, {col} - 1)
                            WHERE pattern_id = %s
                        """, (pid,))
                        result["rolled_back"] += cur.rowcount
                        live_cache.cache.pop(pid, None)
                conn.commit()

        # rollback قوانين
        for law in load_laws():
            if match_law(law, suit or "", rank or "", digit_int, []) >= 0.5:
                try:
                    was_ok  = (law["prediction"] == winner_int)
                    restored = max(0.0, min(100.0,
                        (law["accuracy"] - 0.10 * (100.0 if was_ok else 0.0)) / 0.90))
                    with db_pool.get_conn() as c2:
                        with c2.cursor() as cx:
                            cx.execute("""UPDATE ai_laws SET accuracy=%s,
                                times_used=GREATEST(0,times_used-1) WHERE id=%s""",
                                (restored, law["id"]))
                            c2.commit()
                    result["laws_adjusted"] += 1
                except Exception:
                    pass

        # مسح cache
        live_cache.cache.clear()
        global _markov_cache, _full_history_cache, _gravity_cache
        _markov_cache = None; _full_history_cache = []; _gravity_cache = (None,0.0,"")
        load_laws(force=True)

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"_exec_delete: {e}", exc_info=True)
    return result


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []

    # ── لا يوجد رقم → اطلب من المستخدم ─────────────────────────────
    if not args:
        await update.message.reply_text(
            "🗑️ <b>حذف جولة برقم البونص</b>"
            "━━━━━━━━━━━━━━━━━━━━━━"
            "أرسل رقم البونص للجولة التي تريد حذفها:"
            "<code>/delete 7888847</code>",
            parse_mode="HTML"
        )
        return

    bnum_input = clean_digits(args[0])
    if not bnum_input:
        await update.message.reply_text("❌ رقم غير صالح. مثال: <code>/delete 7888847</code>",
                                        parse_mode="HTML")
        return

    # ── ابحث عن الجولة بالـ b_num ────────────────────────────────────
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                # قد يكون هناك أكثر من جولة بنفس b_num — خذ الأحدث
                cur.execute("""
                    SELECT id, b_num, suit, rank, bonus_last_digit,
                           winner, prediction, created_at, user_id
                    FROM history
                    WHERE b_num::text = %s
                    ORDER BY id DESC
                    LIMIT 3
                """, (bnum_input,))
                rows = cur.fetchall()
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")
        return

    if not rows:
        await update.message.reply_text(
            f"⚠️ لا توجد جولة بالرقم <code>{bnum_input}</code>"
            f"تأكد من الرقم وأعد المحاولة.",
            parse_mode="HTML"
        )
        return

    # ── جولة واحدة → اعرض تفاصيل + تأكيد ──────────────────────────
    if len(rows) == 1:
        r = rows[0]
        rid, bnum, suit, rank, digit, winner_str, pred_str, created_at, _ = r
        t = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "?"
        winner_icon = {"الراعي 🔴":"🔴","الثور 🔵":"🔵","تعادل ⚪":"⚪"}.get(winner_str,"?")
        await update.message.reply_text(
            f"🗑️ <b>تأكيد الحذف</b>"
            f"━━━━━━━━━━━━━━━━━━━━━━"
            f"🔑 B_NUM: <code>{bnum}</code>"
            f"🃏 {suit or '?'} {rank or '?'}  |  🔢 رقم: <b>{digit}</b>"
            f"🏆 {winner_str} {winner_icon}  |  التوقع: {pred_str or 'NULL'}"
            f"🕐 {t}"
            f"━━━━━━━━━━━━━━━━━━━━━━"
            f"هل تريد حذف هذه الجولة؟",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ نعم احذف", callback_data=f"del_confirm_{rid}"),
                InlineKeyboardButton("❌ إلغاء",    callback_data="del_cancel"),
            ]])
        )

    # ── أكثر من جولة بنفس الرقم → اعرض الخيارات ────────────────────
    else:
        buttons = []
        for r in rows:
            rid, bnum, suit, rank, digit, winner_str, pred_str, created_at, _ = r
            t = created_at.strftime("%d/%m %H:%M") if created_at else "?"
            icon = {"الراعي 🔴":"🔴","الثور 🔵":"🔵","تعادل ⚪":"⚪"}.get(winner_str,"?")
            buttons.append([InlineKeyboardButton(
                f"#{rid} {icon} {t} — {suit or '?'}{rank or '?'}",
                callback_data=f"del_confirm_{rid}"
            )])
        buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel")])
        await update.message.reply_text(
            f"⚠️ وُجدت <b>{len(rows)}</b> جولات بالرقم <code>{bnum_input}</code>\nاختر الجولة:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )



# ==================== /download: تصدير احترافي شامل ====================
def _safe(v, fmt=None) -> str:
    """تحويل آمن لأي قيمة — يتجنب NoneType format errors."""
    if v is None:
        return "NULL"
    if fmt and isinstance(v, (int, float)):
        try:
            return format(v, fmt)
        except Exception:
            return str(v)
    return str(v)

async def cmd_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تصدير قاعدة البيانات كاملة بتنسيق احترافي."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
        return

    msg = await update.message.reply_text("⏳ جارٍ تجميع البيانات...")
    try:
        from datetime import datetime as _dt
        import io

        now_str  = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        filename = f"hades_db_{_dt.now().strftime('%Y%m%d_%H%M%S')}.txt"
        lines    = []

        def sec(title: str):
            lines.append("")
            lines.append("╔" + "═" * 58 + "╗")
            lines.append(f"║  {title:<56}║")
            lines.append("╚" + "═" * 58 + "╝")

        # ── رأس الملف ──────────────────────────────────────────────
        lines.append("╔" + "═" * 58 + "╗")
        lines.append("║" + " " * 15 + "HADES V19 — DB EXPORT" + " " * 22 + "║")
        lines.append(f"║  Generated : {now_str:<44}║")
        lines.append("╚" + "═" * 58 + "╝")

        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:

                # ── ملخص سريع ──────────────────────────────────────
                sec("SUMMARY")
                counts = {}
                for tbl in ["history", "pattern_stats", "ai_laws", "learn_sessions"]:
                    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                    counts[tbl] = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM history WHERE winner IS NOT NULL AND prediction IS NOT NULL AND winner::text = prediction::text")
                correct = cur.fetchone()[0]
                played  = max(counts["history"], 1)
                acc     = round(correct / played * 100, 1)

                cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                active_laws = cur.fetchone()[0]

                lines.append(f"  History rows   : {counts['history']}")
                lines.append(f"  Pattern stats  : {counts['pattern_stats']}")
                lines.append(f"  AI Laws total  : {counts['ai_laws']}  (active: {active_laws})")
                lines.append(f"  Learn sessions : {counts['learn_sessions']}")
                lines.append(f"  Prediction acc : {acc}%  ({correct}/{played})")

                # ── PATTERN STATS ───────────────────────────────────
                sec("PATTERN_STATS")
                cur.execute("""
                    SELECT pattern_id, pattern_type,
                           red_count, blue_count, tie_count
                    FROM pattern_stats
                    ORDER BY pattern_type, pattern_id
                """)
                lines.append(f"  {'PATTERN_ID':<25} {'TYPE':<8} {'RED':>6} {'BLUE':>6} {'TIE':>5}  BIAS%")
                lines.append("  " + "-" * 56)
                for r in cur.fetchall():
                    red  = float(r[2] or 0)
                    blue = float(r[3] or 0)
                    tie  = float(r[4] or 0)
                    tot  = red + blue + tie
                    bias = round((blue - red) / max(tot, 1) * 100, 1)
                    arrow = "→🔵" if bias > 5 else ("→🔴" if bias < -5 else "  =")
                    lines.append(
                        f"  {_safe(r[0]):<25} {_safe(r[1]):<8} "
                        f"{red:>6.0f} {blue:>6.0f} {tie:>5.0f}  {bias:+.1f}% {arrow}"
                    )

                # ── AI LAWS ─────────────────────────────────────────
                sec("AI_LAWS  (sorted by accuracy DESC)")
                cur.execute("""
                    SELECT id, law_name, law_type, conditions, prediction,
                           confidence, accuracy, times_used, description, active
                    FROM ai_laws
                    ORDER BY accuracy DESC, confidence DESC
                """)
                rows_laws = cur.fetchall()
                lines.append(f"  {'ID':>4}  {'TYPE':<28} {'PRED':<10} {'CONF':>5} {'ACC':>5} {'USED':>5}  ACT")
                lines.append("  " + "-" * 70)
                for r in rows_laws:
                    pred_name = "🔴 Banker" if r[4] == 0 else ("🔵 Player" if r[4] == 1 else "?")
                    conf = float(r[5]) if r[5] is not None else 0.0
                    acc  = float(r[6]) if r[6] is not None else 0.0
                    used = int(r[7]) if r[7] is not None else 0
                    active_flag = "✅" if r[9] else "❌"
                    lines.append(
                        f"  {_safe(r[0]):>4}  {_safe(r[2]):<28} {pred_name:<10} "
                        f"{conf:>4.0f}% {acc:>4.0f}% {used:>5}  {active_flag}"
                    )
                    # شروط + وصف في سطور منفصلة
                    if r[3]:
                        cond_str = str(r[3]) if not isinstance(r[3], str) else r[3]
                        lines.append(f"       CONDITIONS: {cond_str[:90]}")
                    if r[8]:
                        lines.append(f"       DESC      : {_safe(r[8])[:90]}")
                    lines.append("")

                # ── LEARN SESSIONS ──────────────────────────────────
                sec("LEARN_SESSIONS")
                cur.execute("""
                    SELECT id, rounds_used, laws_created, laws_updated,
                           summary, created_at
                    FROM learn_sessions ORDER BY id DESC
                """)
                for r in cur.fetchall():
                    lines.append(
                        f"  #{_safe(r[0])}  [{_safe(r[5])}]  "
                        f"rounds={_safe(r[1])}  laws_new={_safe(r[2])}  laws_upd={_safe(r[3])}"
                    )
                    if r[4]:
                        lines.append(f"     {_safe(r[4])[:80]}")

                # ── HISTORY (full) ──────────────────────────────────
                sec("HISTORY  (all rows, ASC)")
                cur.execute("""
                    SELECT id, b_num, suit, rank, bonus_last_digit,
                           winner, prediction, created_at
                    FROM history ORDER BY id ASC
                """)
                lines.append(
                    f"  {'ID':>6}  {'B_NUM':<12} {'SUIT':<5} {'RANK':<5} "
                    f"{'DIG':>3}  {'WINNER':<14} {'PRED':<14}  CREATED_AT"
                )
                lines.append("  " + "-" * 85)
                for r in cur.fetchall():
                    lines.append(
                        f"  {_safe(r[0]):>6}  {_safe(r[1]):<12} {_safe(r[2]):<5} {_safe(r[3]):<5} "
                        f"{_safe(r[4]):>3}  {_safe(r[5]):<14} {_safe(r[6]):<14}  {_safe(r[7])}"
                    )

        # ── ذيل الملف ───────────────────────────────────────────────
        lines.append("")
        lines.append("╔" + "═" * 58 + "╗")
        lines.append(f"║  END OF EXPORT — {len(lines)} lines{' ' * (40 - len(str(len(lines))))}║")
        lines.append("╚" + "═" * 58 + "╝")

        content_txt = "\n".join(lines)
        file_bytes  = io.BytesIO(content_txt.encode("utf-8"))
        file_bytes.name = filename

        # إحصاء سريع للـ caption
        h_count = counts.get("history", 0)
        l_count = counts.get("ai_laws", 0)

        await msg.delete()
        await update.message.reply_document(
            document=file_bytes,
            filename=filename,
            caption=f"<b>HADES DB Export</b>\n<code>{now_str}</code>\nHistory: <b>{h_count}</b> | Laws: <b>{l_count}</b> | Acc: <b>{acc}%</b>\n<i>{len(lines)} lines</i>",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        try:
            await msg.edit_text(
                f"❌ خطأ في التصدير:<code>{e}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass

# ==================== التشغيل ====================
def main():
    ensure_tables()
    load_laws()               # تحميل القوانين
    load_signal_perf_from_db()  # تحميل أداء الإشارات
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("force_learn", cmd_force_learn))
    app.add_handler(CommandHandler("laws",        cmd_laws))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("prune",       cmd_prune))
    app.add_handler(CommandHandler("reset_laws",  cmd_reset_laws))
    app.add_handler(CommandHandler("delete",      cmd_delete))
    app.add_handler(CommandHandler("download",    cmd_download))
    app.add_handler(CommandHandler("engine",      cmd_engine_status))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("🚀 HADES V19.0 is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
