"""
HADES V17.0 - Neural Hybrid | Embedded Pattern Engine + Full Telegram UI
بيانات الأنماط مدمجة مباشرة (من آخر نسخة احتياطية) + واجهة أزرار كاملة.
"""

import re
import json
import logging
import math
import asyncio
import time
from typing import Tuple, Dict, Optional, List
from contextlib import contextmanager
from datetime import datetime
from collections import OrderedDict

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

AI_BASE_URL = "https://integrate.api.nvidia.com/v1"
AI_API_KEY  = "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"
AI_MODEL    = "mistralai/devstral-2-123b-instruct-2512"
AI_TIMEOUT  = 3.0

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== خرائط ثابتة ====================
WINNER_MAP   = {
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
WEIGHTS = {'SD': 2.8, 'SUIT': 1.8, 'DIGIT': 1.2, 'RANK': 1.5, 'MOMENTUM': 1.5, 'AI': 2.5}

# ==================== 📦 بيانات الأنماط المدمجة (DB Backup 2026-03-07) ====================
# المصدر: hades_db_20260307_101455.txt — يتم تحديثها تلقائياً عند كل تسجيل نتيجة
EMBEDDED_PATTERNS: Dict[str, Dict] = {
    # ── SUIT ─────────────────────────────────────────────────────────────
    "SUIT_♦️": {"r": 315, "b": 347, "t": 27},
    "SUIT_♣️": {"r": 206, "b": 194, "t": 15},
    "SUIT_♥️": {"r": 190, "b": 194, "t": 11},
    "SUIT_♠️": {"r": 202, "b": 168, "t": 13},

    # ── DIGIT ─────────────────────────────────────────────────────────────
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

    # ── RANK ──────────────────────────────────────────────────────────────
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

    # ── SD (Suit + Last Digit) ────────────────────────────────────────────
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

# ==================== تجمع اتصالات قاعدة البيانات ====================
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
            self._pool = psycopg2.pool.SimpleConnectionPool(
                1, 10, dsn=DATABASE_URL, sslmode='require', connect_timeout=3
            )
            logger.info("✅ Database pool created")
        except Exception as e:
            logger.error(f"Pool creation failed: {e}")
            raise

    @contextmanager
    def get_conn(self):
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

db_pool = DatabasePool()

# ==================== تخزين مؤقت (TTL Cache) ====================
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
        if len(self.cache) > 200:
            self.cache.popitem(last=False)

live_cache = TTLCache(ttl_seconds=30)

# ==================== دوال مساعدة ====================
def clean_digits(text: str) -> str:
    return re.sub(r"\D", "", str(text))

def get_last_digit(b: str) -> int:
    c = clean_digits(b)
    return int(c[-1]) if c else 0

def generate_bar(pct: int, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)

def ensure_tables():
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id           SERIAL PRIMARY KEY,
                        b_num        TEXT,
                        suit         TEXT,
                        hand         TEXT,
                        winner       TEXT,
                        timestamp    TIMESTAMP,
                        prediction   TEXT,
                        user_id      BIGINT,
                        final_prediction TEXT,
                        gap_pred     TEXT,
                        math_pred    TEXT,
                        file_pred    TEXT,
                        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        rank         TEXT,
                        bonus_last_digit INT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pattern_stats (
                        pattern_id  VARCHAR(60) PRIMARY KEY,
                        pattern_type VARCHAR(20),
                        red_count   FLOAT DEFAULT 0,
                        blue_count  FLOAT DEFAULT 0,
                        tie_count   FLOAT DEFAULT 0
                    )
                """)
                conn.commit()
        logger.info("✅ Tables ensured")
    except Exception as e:
        logger.error(f"DB init error: {e}")

# ==================== محرك الأنماط المدمج ====================
def _score_pattern(raw: Dict) -> Dict:
    """احسب النتيجة من بيانات الأنماط (r/b/t)."""
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

    return {
        "w": winner,
        "c": confidence,
        "log": f"[{int(r)}🔴:{int(b)}🔵:{int(t)}⚪]",
        "tie_ratio": tie_ratio,
    }

def get_pattern(pattern_id: str) -> Dict:
    """
    يجلب النمط بالترتيب:
    1. الكاش المباشر
    2. التحديثات الحية في قاعدة البيانات (إن وُجدت)
    3. البيانات المدمجة EMBEDDED_PATTERNS
    """
    cached = live_cache.get(pattern_id)
    if cached:
        return cached

    # محاولة جلب تحديثات حية من DB
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT red_count, blue_count, tie_count FROM pattern_stats WHERE pattern_id = %s",
                    (pattern_id,)
                )
                row = cur.fetchone()
                if row:
                    raw = {"r": row[0], "b": row[1], "t": row[2]}
                    result = _score_pattern(raw)
                    live_cache.set(pattern_id, result)
                    return result
    except Exception as e:
        logger.warning(f"DB pattern fetch failed ({pattern_id}): {e}")

    # الرجوع للبيانات المدمجة
    raw = EMBEDDED_PATTERNS.get(pattern_id)
    if raw:
        result = _score_pattern(raw)
        live_cache.set(pattern_id, result)
        return result

    return {"w": 2, "c": 0.0, "log": "[No Data]", "tie_ratio": 0.0}

def update_pattern_db(suit: str, rank: str, last_digit: int, winner: int):
    """
    بعد تسجيل نتيجة حقيقية: حدّث pattern_stats في DB
    ثم أبطل الكاش المحلي للأنماط المتأثرة.
    """
    col = {0: "red_count", 1: "blue_count", 2: "tie_count"}.get(winner)
    if col is None:
        return

    patterns_to_update = [
        (f"SUIT_{suit}",      "SUIT"),
        (f"DIGIT_{last_digit}", "DIGIT"),
        (f"RANK_{rank}",      "RANK"),
        (f"SD_{suit}_{last_digit}", "SD"),
    ]

    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                for pid, ptype in patterns_to_update:
                    cur.execute(f"""
                        INSERT INTO pattern_stats (pattern_id, pattern_type, red_count, blue_count, tie_count)
                        VALUES (%s, %s, 0, 0, 0)
                        ON CONFLICT (pattern_id) DO NOTHING
                    """, (pid, ptype))
                    cur.execute(f"""
                        UPDATE pattern_stats SET {col} = {col} + 1
                        WHERE pattern_id = %s
                    """, (pid,))
                    # أبطل الكاش
                    live_cache.cache.pop(pid, None)
                conn.commit()
    except Exception as e:
        logger.error(f"Pattern update error: {e}")

# ==================== 🤖 محرك Mistral Devstral ====================
ai_client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)

def extract_json(text: str) -> Optional[dict]:
    match = re.search(r'(\{.*?\})', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    cleaned = re.sub(r'^```json\n?|```$', '', text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None

async def ai_predict(recent_history: List[int]) -> Tuple[Optional[int], float, str]:
    if len(recent_history) < 3:
        return None, 0.0, "بيانات غير كافية"
    try:
        task = asyncio.create_task(_ai_fetch(recent_history))
        return await asyncio.wait_for(task, timeout=AI_TIMEOUT)
    except asyncio.TimeoutError:
        return None, 0.0, "تجاوز المهلة الزمنية"
    except Exception as e:
        return None, 0.0, f"خطأ: {str(e)[:30]}"

async def _ai_fetch(recent_history: List[int]) -> Tuple[Optional[int], float, str]:
    prompt = (
        f"أنت محلل لعبة باكارات. 0=راعي(أحمر)، 1=ثور(أزرق).\n"
        f"التسلسل الأخير: {recent_history}\n"
        f"توقّع الجولة التالية. أعد JSON فقط:\n"
        f'{{ "winner": 0 أو 1, "confidence": 50-95, "reason": "سبب مختصر" }}'
    )
    stream = await ai_client.chat.completions.create(
        model=AI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.15, top_p=0.95, max_tokens=256, seed=42, stream=True
    )
    full = ""
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            full += chunk.choices[0].delta.content
        if "}" in full:
            break

    data = extract_json(full)
    if data:
        return int(data.get("winner", 2)), float(data.get("confidence", 50)), data.get("reason", "")
    return None, 0.0, "خطأ في قراءة الرد"

# ==================== 🧠 كاشف سلاسل الزخم ====================
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

# ==================== 🔮 محرك التنبؤ الرئيسي ====================
async def predict(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b:
        return 2, 0, "❌ رقم بونص غير صالح"

    last_digit = int(clean_b[-1])
    scores: Dict[int, float] = {0: 0.0, 1: 0.0}
    logs: List[str] = []

    # ── 1. تاريخ حديث ─────────────────────────────────────────────────
    recent_history: List[int] = []
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT winner FROM history
                    WHERE winner IS NOT NULL
                    ORDER BY id DESC LIMIT 15
                """)
                recent_history = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
                recent_history.reverse()
    except Exception as e:
        logger.warning(f"History fetch: {e}")

    # ── 2. تشغيل AI بشكل متوازٍ ────────────────────────────────────────
    ai_task = asyncio.create_task(ai_predict(recent_history))

    # ── 3. الزخم ─────────────────────────────────────────────────────
    mom_pred, mom_conf, mom_log = detect_momentum()
    if mom_pred is not None:
        scores[mom_pred] += mom_conf * WEIGHTS['MOMENTUM']
        logs.append(f"⏱️ **الزخم:** {WINNER_NAMES[mom_pred]} ({mom_log})")

    # ── 4. الأنماط الإحصائية (من البيانات المدمجة + تحديثات DB) ───────
    pattern_map = [
        (f"SD_{suit}_{last_digit}",  'SD',    '✨ بذلة+رقم'),
        (f"SUIT_{suit}",             'SUIT',  '🎴 البذلة'),
        (f"DIGIT_{last_digit}",      'DIGIT', '🔢 الرقم'),
        (f"RANK_{rank}",             'RANK',  '🃏 الرتبة'),
    ]
    for pid, wkey, desc in pattern_map:
        res = get_pattern(pid)
        if res['w'] != 2 and res['c'] > 0.0:
            scores[res['w']] += res['c'] * WEIGHTS[wkey]
            logs.append(f"{desc}: {WINNER_NAMES[res['w']]} {res['log']}")

    # ── 5. نتيجة AI ───────────────────────────────────────────────────
    try:
        ai_pred, ai_conf, ai_log = await asyncio.wait_for(ai_task, timeout=0.5)
        if ai_pred in [0, 1]:
            scores[ai_pred] += (ai_conf / 100) * WEIGHTS['AI']
            logs.append(f"🤖 **Devstral:** {WINNER_NAMES[ai_pred]} — {ai_log}")
        else:
            logs.append(f"⚠️ **Devstral:** {ai_log}")
    except asyncio.TimeoutError:
        logs.append("⚠️ **Devstral:** لم يكتمل في الوقت المحدد")
    except Exception:
        logs.append("⚠️ **Devstral:** خطأ غير متوقع")

    # ── 6. الحساب النهائي ─────────────────────────────────────────────
    total_score = scores[0] + scores[1]

    if total_score == 0:
        # احتياطي رياضي
        padded = clean_b.zfill(3)
        math_res = ((sum(int(d) for d in padded[-3:]) * RANK_VALUE.get(rank.upper(), 1)) + last_digit) % 2
        logs.append("🧮 **تحليل رياضي احتياطي**")
        return math_res, 60, "\n".join(logs)

    p0 = scores[0] / total_score
    p1 = scores[1] / total_score
    entropy    = -(p0 * math.log2(p0 + 1e-9) + p1 * math.log2(p1 + 1e-9))
    confidence = int(min(99, max(51, 50 + 45 * (1 - entropy))))
    final      = 0 if scores[0] >= scores[1] else 1

    return final, confidence, "\n".join(logs)

# ==================== 🎨 تنسيق رسالة التنبؤ ====================
def format_prediction(pred: int, conf: int, reason: str,
                       suit: str, rank: str, b_num: str) -> str:
    bar      = generate_bar(conf)
    ld       = get_last_digit(b_num)
    name     = WINNER_NAMES[pred]
    emoji    = "🔴" if pred == 0 else "🔵"
    opp_name = WINNER_NAMES[1 - pred] if pred in [0, 1] else ""

    return (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🃏  {suit} {rank}   |   #{b_num} (آخر رقم: {ld})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔮  **التوقع: {name}**\n"
        f"📊  [{bar}] {conf}%\n\n"
        f"📋 **التحليل:**\n{reason}\n"
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
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎴 ابدأ جولة جديدة", callback_data="choose_suit")],
        [InlineKeyboardButton("📊 إحصائيات سريعة",  callback_data="stats")],
    ])
    await update.message.reply_text(
        "🏛️ *HADES V17.0*\n"
        "محرك تنبؤ باكارات — بيانات مدمجة + ذكاء اصطناعي\n\n"
        "اضغط ابدأ لتحديد البذلة والرتبة، ثم أرسل رقم البونص.",
        parse_mode="Markdown",
        reply_markup=kb
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── اختيار البذلة ────────────────────────────────────────────────
    if data == "choose_suit":
        context.user_data.pop('suit', None)
        context.user_data.pop('rank', None)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(s, callback_data=f"suit_{s}") for s in SUITS]
        ])
        await query.edit_message_text("🎴 اختر البذلة:", reply_markup=kb)

    # ── تحديد البذلة → اختيار الرتبة ─────────────────────────────────
    elif data.startswith("suit_"):
        suit = data[5:]
        context.user_data['suit'] = suit
        rows = [
            [InlineKeyboardButton(r, callback_data=f"rank_{r}") for r in row]
            for row in RANKS_LAYOUT
        ]
        rows.append([InlineKeyboardButton("🔙 تغيير البذلة", callback_data="choose_suit")])
        await query.edit_message_text(
            f"البذلة: *{suit}*\nاختر الرتبة:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(rows)
        )

    # ── تحديد الرتبة → انتظار رقم البونص ────────────────────────────
    elif data.startswith("rank_"):
        rank = data[5:]
        context.user_data['rank'] = rank
        suit = context.user_data.get('suit', '?')
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 تغيير الرتبة", callback_data=f"suit_{suit}")]
        ])
        await query.edit_message_text(
            f"✅ البذلة: *{suit}* | الرتبة: *{rank}*\n\n"
            f"📩 الآن أرسل رقم البونص (مثال: `7022088`)",
            parse_mode="Markdown",
            reply_markup=kb
        )

    # ── تسجيل النتيجة الحقيقية ───────────────────────────────────────
    elif data.startswith("save_"):
        parts  = data.split("_", 2)
        winner = int(parts[1])
        b_num  = parts[2] if len(parts) > 2 else context.user_data.get('last_b_num', '')
        suit   = context.user_data.get('suit', '')
        rank   = context.user_data.get('rank', '')
        pred   = context.user_data.get('last_pred', 2)

        if not (b_num and suit and rank):
            await query.edit_message_text("❌ بيانات ناقصة — ابدأ جولة جديدة.")
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
            logger.error(f"Save history error: {e}")

        # تحديث أنماط قاعدة البيانات
        update_pattern_db(suit, rank, last_digit, winner)

        result_icon = "✅" if correct else "❌"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
        ])
        await query.edit_message_text(
            f"{result_icon} تم تسجيل: *{WINNER_NAMES[winner]}*\n"
            f"التوقع كان: {WINNER_NAMES.get(pred, '?')} "
            f"{'— **صحيح!** 🎯' if correct else '— خاطئ'}\n\n"
            f"البذلة: {suit} | الرتبة: {rank} | رقم: {b_num} (آخر: {last_digit})",
            parse_mode="Markdown",
            reply_markup=kb
        )

    # ── الإحصائيات السريعة ────────────────────────────────────────────
    elif data == "stats":
        await query.edit_message_text("⏳ جارٍ تحميل الإحصائيات...")
        try:
            with db_pool.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM history")
                    total = cur.fetchone()[0]
                    cur.execute("""
                        SELECT winner, COUNT(*) FROM history
                        WHERE winner IS NOT NULL
                        GROUP BY winner
                    """)
                    dist = {r[0]: r[1] for r in cur.fetchall()}
                    cur.execute("""
                        SELECT COUNT(*) FROM history
                        WHERE winner IS NOT NULL
                          AND winner = prediction
                    """)
                    correct = cur.fetchone()[0]

            r_cnt  = dist.get('الراعي 🔴', 0)
            b_cnt  = dist.get('الثور 🔵',  0)
            t_cnt  = dist.get('تعادل ⚪',  0)
            played = r_cnt + b_cnt + t_cnt or 1
            acc    = round(correct / max(played, 1) * 100, 1)

            # أقوى نمط SD من البيانات المدمجة
            best_sd = max(
                ((k, v) for k, v in EMBEDDED_PATTERNS.items() if k.startswith("SD_")),
                key=lambda x: abs(x[1]["b"] - x[1]["r"])
            )
            bp_id  = best_sd[0]
            bp_raw = best_sd[1]
            bp_winner = "🔵 الثور" if bp_raw["b"] > bp_raw["r"] else "🔴 الراعي"

            msg = (
                f"📊 *إحصائيات HADES*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎮 إجمالي الجولات: *{total}*\n"
                f"🔴 الراعي:  {r_cnt} ({round(r_cnt/played*100,1)}%)\n"
                f"🔵 الثور:   {b_cnt} ({round(b_cnt/played*100,1)}%)\n"
                f"⚪ تعادل:   {t_cnt} ({round(t_cnt/played*100,1)}%)\n"
                f"🎯 دقة التوقع: *{acc}%*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏆 أقوى نمط مدمج:\n"
                f"  {bp_id} → {bp_winner}\n"
                f"  [{bp_raw['r']}🔴:{bp_raw['b']}🔵:{bp_raw['t']}⚪]"
            )
        except Exception as e:
            msg = f"❌ خطأ في جلب الإحصائيات: {e}"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit")]
        ])
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)

# ── استقبال رقم البونص عبر الرسائل النصية ───────────────────────────────────
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    suit = context.user_data.get('suit')
    rank = context.user_data.get('rank')

    if not suit or not rank:
        await update.message.reply_text(
            "ابدأ أولاً بالضغط على /start واختيار البذلة والرتبة."
        )
        return

    b_num = clean_digits(text)
    if not b_num:
        await update.message.reply_text("❌ أرسل رقم البونص فقط (أرقام).")
        return

    context.user_data['last_b_num'] = b_num
    await update.message.reply_text("🔄 جارٍ التحليل...")

    pred, conf, reason = await predict(b_num, suit, rank)
    context.user_data['last_pred'] = pred

    msg = format_prediction(pred, conf, reason, suit, rank, b_num)
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=result_keyboard(pred, b_num)
    )

# ==================== التشغيل ====================
def main():
    ensure_tables()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("🚀 HADES V17.0 is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
