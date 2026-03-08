"""
HADES V18.0 - Neural Hybrid + Deep Learning Memory
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
              recent: List[int]) -> float:
    """
    يقيّم إن كان القانون ينطبق على الجولة الحالية.
    يُعيد قيمة [0, 1]: درجة الانطباق.
    """
    cond  = law.get("conditions", {})
    score = 0.0
    total = 0

    if "suit" in cond:
        total += 1
        if suit == cond["suit"]:
            score += 1

    if "digit" in cond:
        total += 1
        if str(last_digit) == str(cond["digit"]):
            score += 1

    if "rank" in cond:
        total += 1
        if rank == cond["rank"]:
            score += 1

    if "digits_in" in cond:
        total += 1
        if str(last_digit) in [str(d) for d in cond["digits_in"]]:
            score += 1

    if "suits_in" in cond:
        total += 1
        if suit in cond["suits_in"]:
            score += 1

    if "streak" in cond and len(recent) >= cond["streak"]["length"]:
        total += 1
        expected = [cond["streak"]["value"]] * cond["streak"]["length"]
        if recent[-cond["streak"]["length"]:] == expected:
            score += 1

    if "after_pattern" in cond and len(recent) >= len(cond["after_pattern"]):
        total += 1
        pat = cond["after_pattern"]
        if recent[-len(pat):] == pat:
            score += 1

    if "rank_family" in cond:
        total += 1
        families = {
            "face":   ["J", "Q", "K"],
            "low":    ["2", "3", "4", "5"],
            "high":   ["9", "10", "A"],
            "middle": ["6", "7", "8"],
        }
        if rank in families.get(cond["rank_family"], []):
            score += 1

    if "digit_parity" in cond:
        total += 1
        parity = "even" if last_digit % 2 == 0 else "odd"
        if parity == cond["digit_parity"]:
            score += 1

    if total == 0:
        return 0.5  # قانون عام بدون شروط
    return score / total

def apply_laws(suit: str, rank: str, last_digit: int,
               recent: List[int]) -> Tuple[Dict[int, float], List[str]]:
    """
    يُطبّق كل القوانين النشطة على الجولة الحالية.
    يُعيد: (scores بالنسبة لـ red/blue, سجلات نصية)
    """
    laws   = load_laws()
    scores = {0: 0.0, 1: 0.0}
    logs   = []

    for law in laws:
        match = match_law(law, suit, rank, last_digit, recent)
        if match < 0.5:
            continue  # القانون لا ينطبق بشكل كافٍ

        pred = law.get("prediction")
        if pred not in [0, 1]:
            continue

        # وزن القانون = ثقته × دقته × درجة الانطباق
        weight = (law["confidence"] / 100) * max(0.5, law["accuracy"] / 100) * match
        scores[pred] += weight * WEIGHTS['LAW']

        if match >= 0.8:  # فقط القوانين القوية تظهر في السجل
            logs.append(
                f"⚖️ قانون #{law['id']} ({law['law_type']}): "
                f"{WINNER_NAMES[pred]} — {law['description'][:60]}"
            )

        # تحديث عداد الاستخدام بشكل غير متزامن
        asyncio.get_event_loop().run_in_executor(
            None, _increment_law_usage, law["id"]
        )

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

# ==================== 🧬 /force_learn: التعلم العميق ====================
async def force_learn_engine(status_callback) -> Dict:
    """
    يُحلّل كل الجولات السابقة ويُولّد قوانين ذكية عبر مراحل متعددة.
    status_callback: دالة async لإرسال تحديثات للمستخدم.
    """
    await status_callback("📥 <b>المرحلة 1/5</b> — جلب كل الجولات من قاعدة البيانات...")

    # ── جلب البيانات الكاملة ────────────────────────────────────────
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, b_num, suit, rank, bonus_last_digit,
                           winner, created_at
                    FROM history
                    WHERE winner IS NOT NULL
                      AND suit IS NOT NULL
                    ORDER BY id ASC
                """)
                rows = cur.fetchall()
    except Exception as e:
        return {"error": str(e)}

    if len(rows) < 10:
        return {"error": "بيانات غير كافية (أقل من 10 جولات)"}

    total_rounds = len(rows)
    await status_callback(
        f"✅ <b>المرحلة 1/5</b> — تم جلب <b>{total_rounds}</b> جولة\n\n"
        f"📊 <b>المرحلة 2/5</b> — بناء الذاكرة الإحصائية..."
    )

    # ── بناء ملخص إحصائي شامل ───────────────────────────────────────
    memory = _build_statistical_memory(rows)

    # ── جلب القوانين السابقة (الذاكرة التراكمية) ────────────────────
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, law_type, conditions, prediction, confidence,
                           accuracy, times_used, description
                    FROM ai_laws
                    WHERE active = TRUE
                    ORDER BY accuracy DESC LIMIT 20
                """)
                existing_laws = [
                    {
                        "id": r[0], "type": r[1],
                        "cond": r[2] if isinstance(r[2], dict) else {},
                        "pred": r[3], "conf": r[4],
                        "acc": r[5], "used": r[6], "desc": r[7]
                    }
                    for r in cur.fetchall()
                ]
    except Exception:
        existing_laws = []

    await status_callback(
        f"✅ <b>المرحلة 2/5</b> — الذاكرة جاهزة\n"
        f"📚 قوانين سابقة موجودة: <b>{len(existing_laws)}</b>\n\n"
        f"🤖 <b>المرحلة 3/5</b> — إرسال البيانات إلى Devstral للتحليل العميق...\n"
        f"<i>(قد تستغرق هذه المرحلة عدة دقائق)</i>"
    )

    # ── بناء الـ prompt الذكي ────────────────────────────────────────
    laws_summary = ""
    if existing_laws:
        laws_summary = "\n\nالقوانين الموجودة مسبقاً (تجنّب التكرار وحسّن عليها):\n"
        for l in existing_laws[:10]:
            laws_summary += f"- [{l['type']}] {l['desc']} | دقة: {l['acc']:.0f}% | استخدام: {l['used']}\n"

    prompt = f"""
أنت عقل تحليلي متخصص في لعبة الباكارات. لديك {total_rounds} جولة تاريخية كاملة.
المهمة: استخرج قوانين تنبؤية قوية تعمل كعقل الإنسان — تتعلم، تحفظ، وتكتشف أنماطاً جديدة.

━━━ الملخص الإحصائي الشامل ━━━
{json.dumps(memory, ensure_ascii=False, indent=2)}
{laws_summary}

━━━ التعليمات ━━━
1. حلّل الأنماط العميقة: التسلسلات، الدورات، الإيقاعات، انتهاء السلاسل.
2. ابحث عن علاقات مركّبة لم تكن في القوانين السابقة.
3. كل قانون له شروط محددة (conditions) وتنبؤ (0=راعي، 1=ثور) وثقة (50-99).

أنواع الشروط المتاحة:
- "suit": بذلة واحدة
- "suits_in": قائمة بذلات
- "digit": رقم أخير واحد
- "digits_in": قائمة أرقام
- "rank": رتبة ورقة
- "rank_family": "face"/"low"/"high"/"middle"
- "digit_parity": "even"/"odd"
- "streak": {{"length": N, "value": 0أو1}} (سلسلة من نفس النتيجة)
- "after_pattern": [0,1,0,...] (بعد تسلسل محدد)

أعد JSON فقط — مصفوفة من القوانين:
[
  {{
    "law_type": "نوع القانون",
    "conditions": {{ ... }},
    "prediction": 0 أو 1,
    "confidence": 50-99,
    "description": "شرح مختصر باللغة العربية لماذا هذا القانون منطقي"
  }},
  ...
]

أنشئ 15-25 قانوناً متنوعاً. اجعلها مفيدة وغير تافهة.
"""

    # ── استدعاء AI ──────────────────────────────────────────────────
    try:
        response = await asyncio.wait_for(
            ai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=8192,
                seed=42,
            ),
            timeout=LEARN_TIMEOUT
        )
        raw_text = response.choices[0].message.content
    except asyncio.TimeoutError:
        return {"error": "انتهت المهلة الزمنية (5 دقائق)"}
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

                    law_name = law.get("law_type", "COMBINED")
                    cur.execute("""
                        INSERT INTO ai_laws
                            (law_name, law_type, conditions, prediction, confidence,
                             accuracy, description, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'force_learn')
                    """, (
                        law_name,
                        law_name,
                        json.dumps(cond, ensure_ascii=False),
                        int(pred),
                        float(law.get("confidence", 70)),
                        float(law.get("confidence", 70)),  # accuracy = confidence مبدئياً
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

# ==================== 🔮 محرك التنبؤ الرئيسي ====================
async def predict(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b:
        return 2, 0, "❌ رقم بونص غير صالح"

    last_digit = int(clean_b[-1])
    scores: Dict[int, float] = {0: 0.0, 1: 0.0}
    logs:   List[str]        = []

    # ── تاريخ حديث ──────────────────────────────────────────────────
    recent_history: List[int] = []
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT winner FROM history
                    WHERE winner IS NOT NULL
                    ORDER BY id DESC LIMIT 20
                """)
                recent_history = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
                recent_history.reverse()
    except Exception as e:
        logger.warning(f"History fetch: {e}")

    # ── AI متوازٍ ────────────────────────────────────────────────────
    ai_task = asyncio.create_task(ai_predict(recent_history))

    # ── 1. القوانين الذكية (الذاكرة السياقية) ──────────────────────
    law_scores, law_logs = apply_laws(suit, rank, last_digit, recent_history)
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
        ai_pred, ai_conf, ai_log = await asyncio.wait_for(ai_task, timeout=0.5)
        if ai_pred in [0, 1]:
            scores[ai_pred] += (ai_conf / 100) * WEIGHTS['AI']
            logs.append(f"🤖 Devstral: {WINNER_NAMES[ai_pred]} — {ai_log}")
        else:
            logs.append(f"⚠️ Devstral: {ai_log}")
    except asyncio.TimeoutError:
        logs.append("⚠️ Devstral: لم يكتمل في الوقت المحدد")
    except Exception:
        logs.append("⚠️ Devstral: خطأ")

    # ── الحساب النهائي ──────────────────────────────────────────────
    total_score = scores[0] + scores[1]
    if total_score == 0:
        padded   = clean_b.zfill(3)
        math_res = ((sum(int(d) for d in padded[-3:]) * RANK_VALUE.get(rank.upper(), 1)) + last_digit) % 2
        logs.append("🧮 تحليل رياضي احتياطي")
        return math_res, 60, "\n".join(logs)

    p0 = scores[0] / total_score
    p1 = scores[1] / total_score
    entropy    = -(p0 * math.log2(p0 + 1e-9) + p1 * math.log2(p1 + 1e-9))
    confidence = int(min(99, max(51, 50 + 45 * (1 - entropy))))
    final      = 0 if scores[0] >= scores[1] else 1
    return final, confidence, "\n".join(logs)

# ==================== تنسيق الرسائل ====================
def format_prediction(pred: int, conf: int, reason: str,
                       suit: str, rank: str, b_num: str) -> str:
    bar  = generate_bar(conf)
    ld   = get_last_digit(b_num)
    name = WINNER_NAMES[pred]
    laws_count = len(load_laws())
    return (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🃏  {suit} {rank}   |   #{b_num} (آخر رقم: {ld})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔮  <b>التوقع: {name}</b>\n"
        f"📊  [{bar}] {conf}%\n"
        f"⚖️  القوانين النشطة: <b>{laws_count}</b>\n\n"
        f"📋 <b>التحليل:</b>\n{reason}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
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
    context.user_data.clear()
    laws_count = len(load_laws())
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎴 ابدأ جولة جديدة", callback_data="choose_suit")],
        [InlineKeyboardButton("📊 إحصائيات سريعة",  callback_data="stats")],
    ])
    await update.message.reply_text(
        f"🏛️ <b>HADES V18.0</b>\n"
        f"محرك تنبؤ باكارات — بيانات مدمجة + ذكاء اصطناعي + ذاكرة سياقية\n\n"
        f"⚖️ القوانين الذكية النشطة: <b>{laws_count}</b>\n"
        f"💡 استخدم <code>/force_learn</code> لتعليم الذكاء كل الجولات السابقة\n\n"
        f"اضغط <b>ابدأ</b> لتحديد البذلة والرتبة.",
        parse_mode="HTML",
        reply_markup=kb
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
                        """, (b_num, suit, rank, last_digit,
                              WINNER_NAMES[winner], WINNER_NAMES.get(pred, ''),
                              query.from_user.id))
                        conn.commit()
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

            verdict = "<b>صحيح! 🎯</b>" if correct else "خاطئ ❌"
            icon    = "✅" if correct else "❌"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit")],
                [InlineKeyboardButton("📊 الإحصائيات",  callback_data="stats")],
            ])
            await safe_edit(
                query,
                f"{icon} تم تسجيل: <b>{WINNER_NAMES[winner]}</b>\n"
                f"التوقع كان: {WINNER_NAMES.get(pred, '?')} — {verdict}\n\n"
                f"البذلة: {suit}  |  الرتبة: {rank}  |  آخر رقم: {last_digit}",
                reply_markup=kb
            )

        elif data == "stats":
            await safe_edit(query, "⏳ جارٍ تحميل الإحصائيات...")
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
                              AND winner::text = prediction::text
                        """)
                        correct_cnt = cur.fetchone()[0]
                        cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                        laws_cnt = cur.fetchone()[0]
                        cur.execute("""
                            SELECT COUNT(*), MAX(created_at)
                            FROM learn_sessions
                        """)
                        ls = cur.fetchone()
                        sessions_cnt    = ls[0]
                        last_learn_time = ls[1]

                r_cnt  = dist.get('الراعي 🔴', 0)
                b_cnt  = dist.get('الثور 🔵',  0)
                t_cnt  = dist.get('تعادل ⚪',  0)
                played = r_cnt + b_cnt + t_cnt or 1
                acc    = round(correct_cnt / max(played, 1) * 100, 1)
                last_l = last_learn_time.strftime("%Y-%m-%d %H:%M") if last_learn_time else "لم يُجرَ"

                msg = (
                    f"📊 <b>إحصائيات HADES V18</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎮 إجمالي الجولات: <b>{total}</b>\n"
                    f"🔴 الراعي:  {r_cnt} ({round(r_cnt/played*100,1)}%)\n"
                    f"🔵 الثور:   {b_cnt} ({round(b_cnt/played*100,1)}%)\n"
                    f"⚪ تعادل:   {t_cnt} ({round(t_cnt/played*100,1)}%)\n"
                    f"🎯 دقة التوقع: <b>{acc}%</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🧠 الذاكرة السياقية:\n"
                    f"  ⚖️ قوانين نشطة: <b>{laws_cnt}</b>\n"
                    f"  📚 جلسات تعلم: <b>{sessions_cnt}</b>\n"
                    f"  🕐 آخر تعلم: <b>{last_l}</b>"
                )
            except Exception as e:
                msg = f"❌ خطأ: <code>{e}</code>"

            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit")
            ]])
            await safe_edit(query, msg, reply_markup=kb)

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
        await wait_msg.delete()
        await update.message.reply_text(
            format_prediction(pred, conf, reason, suit, rank, b_num),
            parse_mode="HTML",
            reply_markup=result_keyboard(pred, b_num)
        )
    except Exception as e:
        logger.error(f"predict error: {e}", exc_info=True)
        await wait_msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

# ==================== التشغيل ====================
def main():
    ensure_tables()
    load_laws()  # تحميل القوانين عند البدء
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("force_learn", cmd_force_learn))
    app.add_handler(CommandHandler("laws",        cmd_laws))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("🚀 HADES V18.0 is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
