python
"""
HADES V21.0 - The Balanced Ensemble (Quant Edition)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- نظام Probabilistic Ensemble يمنع هيمنة قانون واحد.
- مكافأة للتكتلات الإحصائية (Cluster Boost).
- فلترة ذكية للضوضاء وفصل الكود من التكرارات.
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
from openai import OpenAI  

# ==================== الإعدادات ====================
TOKEN        = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID     = 6033203084

AI_INVOKE_URL  = "https://integrate.api.nvidia.com/v1"   
AI_API_KEY     = "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"
AI_MODEL       = "deepseek-ai/deepseek-v3.2"             
AI_MODEL_SMALL = "meta/llama-3.1-8b-instruct"            
AI_TIMEOUT    = 12.0
LEARN_TIMEOUT = 900  

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
    'SD': 3.0, 'SUIT': 1.5, 'DIGIT': 1.2, 'RANK': 2.8,
    'MOMENTUM': 1.8, 'AI': 2.5,
    'LAW': 2.2,      
}

DATA_LAWS: List[Dict] = []
EMBEDDED_PATTERNS: Dict[str, Dict] = {} 

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

    @contextmanager
    def get_conn(self):
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

db_pool = DatabasePool()

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

_laws_cache: List[Dict] = []
_laws_loaded_at: float  = 0.0

def get_temporal_weight(gap_sec: Optional[float]) -> float:
    if gap_sec is None or gap_sec <= 0:
        return 1.0
    return math.exp(-gap_sec / 60.0)

def get_continuity_weight(b_gap: Optional[float]) -> float:
    if b_gap is None or b_gap <= 0:
        return 1.0
    return math.exp(-b_gap / 3000.0)

def is_noisy_state(gap_sec: Optional[float], b_gap: Optional[float]) -> bool:
    g = gap_sec if gap_sec is not None else 0.0
    b = b_gap   if b_gap   is not None else 0.0
    return g > 45 or b > 3000

def _is_sequential_law(cond: dict) -> bool:
    return "streak" in cond or "cycle_position" in cond

def def_absolute_weight(temporal_weight: float) -> float:
    return 1.0 + 0.5 * (1.0 - temporal_weight)

def load_laws(force: bool = False) -> List[Dict]:
    global _laws_cache, _laws_loaded_at
    if not force and time.time() - _laws_loaded_at < 300:
        return _laws_cache
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, law_type, conditions, prediction,
                           confidence, accuracy, times_used,
                           description, created_at,
                           COALESCE(momentum, 0.5) AS momentum,
                           accuracy_recent
                    FROM ai_laws
                    WHERE active = TRUE
                      AND times_used >= 5
                      AND accuracy >= 52
                    ORDER BY accuracy DESC, times_used DESC
                    LIMIT 20
                """)
                proven = cur.fetchall()

                cur.execute("""
                    SELECT id, law_type, conditions, prediction,
                           confidence, accuracy, times_used,
                           description, created_at,
                           COALESCE(momentum, 0.5) AS momentum,
                           accuracy_recent
                    FROM ai_laws
                    WHERE active = TRUE
                      AND times_used < 5
                    ORDER BY confidence DESC
                    LIMIT 15
                """)
                probation = cur.fetchall()

        def _is_aliasing_law(cond_raw) -> bool:
            try:
                c = cond_raw if isinstance(cond_raw, dict) else json.loads(cond_raw or "{}")
                ts_m = c.get("ts_mod", {})
                return bool(ts_m) and int(ts_m.get("mod", 0)) in (11, 13, 16, 17)
            except Exception:
                return False

        laws = []
        for row in proven:
            if _is_aliasing_law(row[2]): continue
            laws.append({
                "id":              row[0],
                "law_type":        row[1],
                "conditions":      row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}"),
                "prediction":      row[3],
                "confidence":      float(row[4]),
                "accuracy":        float(row[5]),
                "times_used":      int(row[6]),
                "description":     row[7],
                "created_at":      row[8],
                "momentum":        float(row[9]),
                "accuracy_recent": float(row[10]) if row[10] is not None else None,
                "tier":            "proven",
            })

        for row in probation:
            if _is_aliasing_law(row[2]): continue
            laws.append({
                "id":              row[0],
                "law_type":        row[1],
                "conditions":      row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}"),
                "prediction":      row[3],
                "confidence":      float(row[4]),
                "accuracy":        50.0,   
                "times_used":      int(row[6]),
                "description":     row[7],
                "created_at":      row[8],
                "momentum":        float(row[9]),
                "accuracy_recent": float(row[10]) if row[10] is not None else None,
                "tier":            "probation",
            })

        _laws_cache     = laws
        _laws_loaded_at = time.time()
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
        if condition: score += 1

    if "suit"      in cond: chk(suit == cond["suit"])
    if "suits_in"  in cond: chk(suit in cond["suits_in"])
    if "digit"     in cond: chk(str(last_digit) == str(cond["digit"]))
    if "digits_in" in cond: chk(str(last_digit) in [str(d) for d in cond["digits_in"]])
    if "rank"      in cond: chk(rank == cond["rank"])
    if "digit_parity" in cond:
        chk(("even" if last_digit % 2 == 0 else "odd") == cond["digit_parity"])
    
    if "streak" in cond:
        slen = cond["streak"]["length"]
        if len(recent) >= slen:
            chk(recent[-slen:] == [cond["streak"]["value"]] * slen)

    if b_num and "digit_sum_mod" in cond:
        c    = cond["digit_sum_mod"]
        dsum = sum(int(d) for d in b_num if d.isdigit())
        chk(dsum % int(c["mod"]) == int(c["remainder"]))

    if b_num and "rank_value_mod" in cond:
        c  = cond["rank_value_mod"]
        rv = RANK_VALUE.get(rank.upper(), 0)
        chk(rv % int(c["mod"]) == int(c["remainder"]))

    if "cycle_position" in cond and round_index > 0:
        c = cond["cycle_position"]
        chk(round_index % int(c["cycle"]) == int(c["position"]))

    if b_gap is not None:
        if "b_gap_gt"      in cond: chk(b_gap > float(cond["b_gap_gt"]))
        if "b_gap_lt"      in cond: chk(b_gap < float(cond["b_gap_lt"]))
        if "after_big_gap" in cond: chk(b_gap > 2000)

    if gap_sec is not None:
        if "gap_sec_lt" in cond: chk(gap_sec < float(cond["gap_sec_lt"]))
        if "gap_sec_gt" in cond: chk(gap_sec > float(cond["gap_sec_gt"]))

    if "ts_mod" in cond:
        c = cond["ts_mod"]
        try:
            ts_val = int(time.time()) if round_index == 0 else round_index
            chk(ts_val % int(c["mod"]) == int(c["remainder"]))
        except: pass

    if total == 0: return 0.5
    return score / total

def apply_laws(suit: str, rank: str, last_digit: int,
               recent: List[int], b_num: str = "",
               b_gap: Optional[float] = None, gap_sec: Optional[float] = None,
               round_index: int = 0) -> Tuple[Dict[int, float], List[str]]:
    
    laws   = load_laws()
    scores = {0: 0.0, 1: 0.0}
    logs   = []
    law_votes = {0: 0, 1: 0}

    temporal_w   = get_temporal_weight(gap_sec)
    continuity_w = get_continuity_weight(b_gap)
    env_conf     = temporal_w * continuity_w
    noisy        = is_noisy_state(gap_sec, b_gap)

    if noisy:
        logs.append(f"🌊 Noise Gate: gap={gap_sec}s / b_gap={b_gap} — تعطيل التسلسلات")

    MAX_SINGLE_LAW = WEIGHTS['LAW'] * 0.85
    all_laws = laws + list(DATA_LAWS)

    for law in all_laws:
        law_id = law.get("id", 0)
        cond   = law.get("conditions", {})
        num_conditions = len(cond) if isinstance(cond, dict) else 0
        accuracy = law.get("accuracy", 0)
        used = law.get("times_used", 0)
        is_seq   = _is_sequential_law(cond)

        if noisy and is_seq and law_id > 0:
            continue

        if law_id > 0:
            if used >= 10 and accuracy < 50.0: continue
            acc_recent = law.get("accuracy_recent")
            if acc_recent is not None and acc_recent < 45.0 and used >= 5: continue
            law_momentum = law.get("momentum", 0.5)
            if law_momentum < 0.1: continue
        else:
            law_momentum = 0.5

        is_illusion = "ts_mod" in cond or ("digit" in cond and num_conditions == 1)
        if is_illusion and accuracy < 65.0:
            continue

        match = match_law(law, suit, rank, last_digit, recent,
                          b_num=b_num, b_gap=b_gap, gap_sec=gap_sec, round_index=round_index)
        if match < 0.7:
            continue

        pred = law.get("prediction")
        if pred not in [0, 1]: continue

        if is_seq:
            effective_match = match * (0.4 + 0.6 * env_conf)
        else:
            effective_match = match

        trust = 0.5 if law_id < 0 else (0.1 if used < 5 else (0.1 + 0.9 * min(1.0, (used - 5) / 15.0)))
        complexity_multiplier = 0.6 if num_conditions == 1 else (1.0 if num_conditions == 2 else 1.3)

        if is_seq: time_factor = env_conf
        else:      time_factor = min(1.5, def_absolute_weight(temporal_w)) * continuity_w

        law_weight = WEIGHTS['LAW'] * trust * complexity_multiplier * max(0.2, law_momentum) * time_factor
        raw_score    = (law["confidence"] / 100) * max(0.5, accuracy / 100) * effective_match * law_weight
        capped_score = min(raw_score, MAX_SINGLE_LAW)

        scores[pred]    += capped_score
        law_votes[pred] += 1

        if effective_match >= 0.6:
            tier_label = " 🔬" if law.get('tier') == 'probation' else ""
            icon = "⚠️" if num_conditions == 1 else "🎯" if num_conditions == 2 else "🔗"
            logs.append(f"{icon} قانون #{law_id}{tier_label} (ثقة:{trust:.0%}, وزن:{capped_score:.2f}): {WINNER_NAMES[pred]} — {law.get('description', '')[:45]}")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running(): loop.run_in_executor(None, _increment_law_usage, law_id)
        except: pass

    # 🐜 دعم التكتلات (Ensemble Boost)
    for p in [0, 1]:
        opp = 1 - p
        if law_votes[p] >= 3 and law_votes[p] > law_votes[opp] * 2:
            cluster_bonus = min(1.15 + (law_votes[p] * 0.05), 1.40)
            scores[p] *= cluster_bonus
            logs.append(f"🐜 تكتل القوانين ({law_votes[p]} إشارات): {WINNER_NAMES[p]} ×{cluster_bonus:.2f}")

    max_law_score = WEIGHTS['LAW'] * 2.5
    scores[0] = min(scores[0], max_law_score)
    scores[1] = min(scores[1], max_law_score)

    return scores, logs

def _increment_law_usage(law_id: int):
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE ai_laws SET times_used = times_used + 1 WHERE id = %s", (law_id,))
                conn.commit()
    except: pass

def update_law_momentum(law_id: int, is_correct: bool, gap_sec: Optional[float] = None, b_gap: Optional[float] = None, law_type: str = "") -> None:
    t_weight = get_temporal_weight(gap_sec)
    c_weight = get_continuity_weight(b_gap)
    env_conf = t_weight * c_weight  

    REWARD_BASE  = 0.05   
    PENALTY_BASE = 0.08   

    noisy = is_noisy_state(gap_sec, b_gap)
    is_sequential = any(k in law_type for k in ("streak", "cycle", "gap_sec", "gap_b"))
    if noisy and is_sequential: return  

    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                if is_correct:
                    reward = REWARD_BASE * (1.0 + (1.0 - env_conf))
                    cur.execute("UPDATE ai_laws SET momentum = LEAST(1.0, COALESCE(momentum, 0.5) + %s) WHERE id = %s", (reward, law_id))
                else:
                    penalty = PENALTY_BASE * (1.0 + env_conf)
                    cur.execute("UPDATE ai_laws SET momentum = GREATEST(0.0, COALESCE(momentum, 0.5) - %s) WHERE id = %s", (penalty, law_id))
                conn.commit()
    except Exception: pass

def update_law_accuracy(law_id: int, correct: bool, gap_sec: Optional[float] = None, b_gap: Optional[float] = None, law_type: str = ""):
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                new_val = 100.0 if correct else 0.0
                cur.execute("""
                    UPDATE ai_laws
                    SET accuracy        = accuracy * 0.95 + %s * 0.05,
                        accuracy_recent = COALESCE(accuracy_recent, accuracy) * 0.90 + %s * 0.10
                    WHERE id = %s
                """, (new_val, new_val, law_id))
                conn.commit()
    except Exception as e: logger.error(f"update_law_accuracy error: {e}")

    try: update_law_momentum(law_id, correct, gap_sec=gap_sec, b_gap=b_gap, law_type=law_type)
    except: pass

def auto_manage_laws():
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE active = TRUE AND times_used IN (4, 5, 6) AND accuracy_recent < 40")
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE active = TRUE AND times_used >= 30 AND times_used < 50 AND accuracy < 45")
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE active = TRUE AND times_used >= 15 AND times_used < 30 AND accuracy < 48")
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE active = TRUE AND times_used >= 50 AND accuracy < 52")
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE active = TRUE AND times_used >= 20 AND accuracy_recent IS NOT NULL AND accuracy_recent < accuracy - 20 AND accuracy_recent < 48")
                cur.execute("UPDATE ai_laws SET confidence = LEAST(97, confidence * 1.05) WHERE active = TRUE AND times_used >= 10 AND accuracy > 70")
                conn.commit()
    except Exception: pass

async def force_learn_engine(status_callback) -> Dict:
    await status_callback("📥 <b>المرحلة 1/5</b> — جلب كل الجولات...")
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, b_num, suit, rank, bonus_last_digit, winner, created_at
                    FROM history WHERE winner IS NOT NULL AND suit IS NOT NULL ORDER BY id ASC
                """)
                rows = cur.fetchall()
    except Exception as e: return {"error": str(e)}

    if len(rows) < 50: return {"error": "بيانات غير كافية"}

    raw_total = len(rows)
    await status_callback(f"✅ <b>المرحلة 1/5</b> — {raw_total} جولة\n\n🔬 <b>المرحلة 2/5</b> — تحليل رياضي...")

    rounds = _filter_valid_rounds(rows)
    memory = _build_math_memory(rounds)

    confirmed_patterns = memory.get("confirmed_patterns", [])
    hints_text = ""
    if confirmed_patterns:
        hints_text = "الإشارات الموثوقة (استخدمها كمراجع):\n"
        for p in confirmed_patterns[:15]:
            winner_str = "الثور" if p["prediction"] == 1 else "الراعي"
            hints_text += f"- {p['pattern']} → {winner_str} (انحياز {p['bias_pct']}%)\n"

    prompt = f"""
أنت محلل بيانات رياضي متخصص في إيجاد ارتباطات معقدة.
0=الراعي🔴, 1=الثور🔵

{hints_text}

القواعد الصارمة لإنشاء القوانين:
1. ممنوع: streak, cycle_position, digit_sum_mod, rank (حساسة جداً للضوضاء).
2. مسموح: 
   - "suit": "♦️/♥️/♠️/♣️"
   - "gap_sec_lt" أو "gap_sec_gt"
   - "b_gap_lt" أو "b_gap_gt"
   - "digit": 0-9
3. ادمج شرطين معاً (مثال: suit + gap_sec).
4. نوّع النتائج بين 0 (الراعي) و 1 (الثور) لضمان التوازن.
5. استخرج 12 قانوناً (6 للراعي و 6 للثور).
6. confidence بين 55 و 68 فقط.

مثال:
{{"law_type":"suit_time_combo","conditions":{{"suit":"♦️","gap_sec_lt":35}},"prediction":1,"confidence":58,"description":"بذلة ♦️ مع وقت قصير → ثور"}}

أعد JSON array فقط:
"""
    try:
        raw_text = await _nvidia_chat([{"role": "user", "content": prompt}], max_tokens=8192, temperature=0.7, enable_thinking=True, timeout=LEARN_TIMEOUT)
    except Exception as e: return {"error": str(e)}

    await status_callback("✅ <b>المرحلة 3/5</b> — Qwen أكمل\n\n🔬 <b>المرحلة 4/5</b> — Backtest...")

    backtest_rows = _fetch_backtest_rows()
    laws_data = extract_json_safe(raw_text)
    if not laws_data or not isinstance(laws_data, list):
        recovered = _scan_json_objects(raw_text)
        if recovered: laws_data = recovered
        else: return {"error": "فشل استخراج JSON"}

    saved = 0
    with db_pool.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM learn_sessions")
            session_id = cur.fetchone()[0]
            cur.execute("SELECT conditions::text FROM ai_laws WHERE active = TRUE")
            existing_conds = set(r[0] for r in cur.fetchall())

            for law in laws_data:
                if not isinstance(law, dict): continue
                pred = law.get("prediction")
                if pred not in [0, 1]: continue
                cond = law.get("conditions", {})
                if not cond: continue

                is_sequential = isinstance(cond, dict) and _is_sequential_law(cond)
                law_category  = "SEQUENTIAL" if is_sequential else "ABSOLUTE"

                cond_str = json.dumps(cond, ensure_ascii=False, sort_keys=True)
                if cond_str in existing_conds: continue

                bt_passes, bt_acc, bt_n = backtest_law(law, backtest_rows)
                if not bt_passes: continue

                cur.execute("""
                    INSERT INTO ai_laws (law_name, law_type, conditions, prediction, confidence, accuracy, description, source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'force_learn')
                """, (f"LAW_{saved}_{int(time.time())}", law.get("law_type", "COMBINED"), cond_str, int(pred), float(law.get("confidence", 60)), round(bt_acc * 100, 1), f"[{law_category}] {law.get('description', '')} [bt:{bt_acc:.0%}/{bt_n}]"))
                existing_conds.add(cond_str)
                saved += 1

            cur.execute("INSERT INTO learn_sessions (rounds_used, laws_created) VALUES (%s, %s)", (raw_total, saved))
            conn.commit()

    load_laws(force=True)
    return {"total_rounds": raw_total, "laws_saved": saved, "session_id": session_id, "backtest_rows": len(backtest_rows)}

def _run_law_on_rows(law_dict: Dict, rows: List, weighted: bool = False) -> Tuple[float, float]:
    pred = law_dict.get("prediction")
    correct_score = 0.0
    total_score   = 0.0

    cond = law_dict.get("conditions", {})
    is_seq = isinstance(cond, dict) and _is_sequential_law(cond)

    for row in rows:
        b_num_r   = str(row[1] or "")
        suit_r    = str(row[2] or "")
        rank_r    = str(row[3] or "")
        digit_r   = int(row[4]) if row[4] is not None else 0
        winner_r  = WINNER_MAP.get(row[5], 2)
        created_r = row[6]
        b_gap_r   = row[7]
        gap_sec_r = float(row[8]) if row[8] is not None else None

        if winner_r not in [0, 1]: continue
        if is_seq and is_noisy_state(gap_sec_r, b_gap_r): continue

        clean_b   = clean_digits(b_num_r)
        unix_ts_r = int(created_r.timestamp()) if created_r else int(time.time())
        match = match_law(law_dict, suit_r, rank_r, digit_r, recent=[], b_num=clean_b, b_gap=b_gap_r, gap_sec=gap_sec_r, round_index=unix_ts_r)
        
        if match < 0.7: continue

        if weighted:
            t_w = get_temporal_weight(gap_sec_r)
            c_w = get_continuity_weight(b_gap_r)
            row_weight = t_w * c_w
        else:
            row_weight = 1.0

        total_score += row_weight
        if winner_r == pred:
            correct_score += row_weight

    return correct_score, total_score

def backtest_law(law_dict: Dict, backtest_rows: List) -> Tuple[bool, float, int]:
    MIN_TOTAL_SCORE  = 12.0   
    MIN_TOTAL_ACC    = 0.52

    pred = law_dict.get("prediction")
    if pred not in [0, 1]: return False, 0.0, 0

    env_vals = []
    for row in backtest_rows:
        gs = float(row[8]) if row[8] is not None else None
        bg = row[7]
        if gs is not None: env_vals.append(get_temporal_weight(gs) * get_continuity_weight(bg))
    avg_bt_env = sum(env_vals) / len(env_vals) if env_vals else 0.5
    MIN_TOTAL_SCORE = 8.0 if avg_bt_env > 0.5 else 5.0

    c_total, t_total = _run_law_on_rows(law_dict, backtest_rows, weighted=True)

    if t_total < MIN_TOTAL_SCORE: return False, 0.0, int(t_total)
    acc_total = c_total / t_total
    if acc_total < MIN_TOTAL_ACC: return False, acc_total, int(t_total)

    mid      = len(backtest_rows) // 2
    rows_new = backtest_rows[:mid]   
    rows_old = backtest_rows[mid:]   

    c_new, t_new = _run_law_on_rows(law_dict, rows_new, weighted=True)
    c_old, t_old = _run_law_on_rows(law_dict, rows_old, weighted=True)

    acc_new = (c_new / t_new) if t_new > 0 else 0.0
    acc_old = (c_old / t_old) if t_old > 0 else 0.0

    if t_new >= 6.0 and acc_new < 0.50: return False, acc_total, int(t_total)
    return True, acc_total, int(t_total)

def _fetch_backtest_rows() -> List:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT h.id, h.b_num, h.suit, h.rank, h.bonus_last_digit, h.winner, h.created_at,
                        ABS(h.b_num::bigint - LAG(h.b_num::bigint) OVER (ORDER BY h.id)) AS b_gap,
                        EXTRACT(EPOCH FROM (h.created_at - LAG(h.created_at) OVER (ORDER BY h.id))) AS gap_sec
                    FROM history h
                    WHERE h.winner IS NOT NULL AND h.rank IS NOT NULL AND h.rank NOT IN ('NULL','') AND h.b_num ~ '^[0-9]+$'
                    ORDER BY h.id DESC LIMIT 600
                """)
                return cur.fetchall()
    except Exception: return []

def _build_statistical_memory(rows) -> Dict:
    rounds = []
    for row in rows:
        w = WINNER_MAP.get(row[5], 2)
        if w == 2: continue
        rounds.append({"suit": row[2] or "", "rank": row[3] or "", "digit": int(row[4]) if row[4] is not None else -1, "winner": w})

    if not rounds: return {}

    total = len(rounds)
    red   = sum(1 for r in rounds if r["winner"] == 0)
    blue  = sum(1 for r in rounds if r["winner"] == 1)

    suit_stats = defaultdict(lambda: [0, 0])
    for r in rounds: suit_stats[r["suit"]][r["winner"]] += 1

    digit_stats = defaultdict(lambda: [0, 0])
    for r in rounds:
        if r["digit"] >= 0: digit_stats[str(r["digit"])][r["winner"]] += 1

    rank_stats = defaultdict(lambda: [0, 0])
    for r in rounds: rank_stats[r["rank"]][r["winner"]] += 1

    sd_stats = defaultdict(lambda: [0, 0])
    for r in rounds:
        if r["digit"] >= 0: sd_stats[f"{r['suit']}_{r['digit']}"][r["winner"]] += 1

    return {
        "overview": {"total": total, "red_pct": round(red / total * 100, 1), "blue_pct": round(blue / total * 100, 1)},
        "suit_win_rates": {s: {"red": v[0], "blue": v[1], "blue_dominance": round((v[1] - v[0]) / max(v[0] + v[1], 1) * 100, 1)} for s, v in suit_stats.items()},
        "digit_win_rates": {d: {"red": v[0], "blue": v[1], "blue_dominance": round((v[1] - v[0]) / max(v[0] + v[1], 1) * 100, 1)} for d, v in digit_stats.items()},
        "rank_win_rates": {r: {"red": v[0], "blue": v[1], "blue_dominance": round((v[1] - v[0]) / max(v[0] + v[1], 1) * 100, 1)} for r, v in rank_stats.items()},
        "top_sd_patterns": dict(sorted({k: {"red": v[0], "blue": v[1]} for k, v in sd_stats.items()}.items(), key=lambda x: abs(x[1]["blue"] - x[1]["red"]), reverse=True)[:15]),
        "transition_stats": _analyze_streaks([r["winner"] for r in rounds]),
    }

def _analyze_streaks(winners: List[int]) -> Dict:
    results = {"after_red_streak": {}, "after_blue_streak": {}}
    i = 0
    while i < len(winners):
        j = i
        while j < len(winners) and winners[j] == winners[i]: j += 1
        streak_len = j - i
        val        = winners[i]
        if streak_len >= 2 and j < len(winners):
            key = f"len_{min(streak_len, 5)}"
            side = "after_red_streak" if val == 0 else "after_blue_streak"
            next_val = winners[j]
            if key not in results[side]: results[side][key] = {"continued": 0, "broke": 0}
            if next_val == val: results[side][key]["continued"] += 1
            else: results[side][key]["broke"] += 1
        i = j
    return results

def detect_real_streak(history: List[int]) -> Tuple[Optional[int], float]:
    if len(history) < 4: return None, 0.0
    last = history[-1]
    streak = 1
    for i in range(len(history) - 2, -1, -1):
        if history[i] == last: streak += 1
        else: break
    if streak >= 4:
        opposite = 1 if last == 0 else 0
        conf = min(0.90, 0.75 + (streak - 4) * 0.03)
        return opposite, conf
    return None, 0.0

def short_memory_bias(history: List[int]) -> Tuple[Optional[int], float]:
    if len(history) < 10: return None, 0.0
    last10 = history[-10:]
    r = last10.count(0); b = last10.count(1)
    if abs(r - b) >= 5: return (0, 0.65) if r > b else (1, 0.65)
    return None, 0.0

def suit_bias_from_history(suit: str) -> Tuple[Optional[int], float]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL AND suit = %s ORDER BY id DESC LIMIT 80", (suit,))
                rows = cur.fetchall()
        if len(rows) < 10: return None, 0.0
        r = sum(1 for x in rows if WINNER_MAP.get(x[0], 2) == 0)
        b = sum(1 for x in rows if WINNER_MAP.get(x[0], 2) == 1)
        t = r + b
        if t == 0: return None, 0.0
        diff = (b - r) / t
        if abs(diff) > 0.20: return (1 if diff > 0 else 0), min(0.70, abs(diff))
    except: pass
    return None, 0.0

def is_prime(n: int) -> bool:
    if n < 2: return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0: return False
    return True

_signal_perf: Dict[str, List[int]] = {}   

def get_adaptive_weight(signal: str, base_weight: float) -> float:
    perf = _signal_perf.get(signal)
    if not perf or perf[1] < 20: return base_weight
    acc = perf[0] / perf[1]
    if acc >= 0.65:   factor = 1.20
    elif acc >= 0.55: factor = 1.10
    elif acc >= 0.45: factor = 1.00
    elif acc >= 0.35: factor = 0.85
    else:             factor = 0.70
    return base_weight * factor

def update_signal_perf(signal: str, correct: bool, window: int = 60):
    if signal not in _signal_perf: _signal_perf[signal] = [0, 0]
    _signal_perf[signal][1] += 1
    if correct: _signal_perf[signal][0] += 1
    if _signal_perf[signal][1] > window:
        decay = 1 / window
        _signal_perf[signal][0] = max(0, _signal_perf[signal][0] - decay)
        _signal_perf[signal][1] = window

def load_signal_perf_from_db():
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT signal_name, correct_count, total_count FROM signal_performance WHERE total_count > 0")
                for row in cur.fetchall(): _signal_perf[row[0]] = [int(row[1]), int(row[2])]
    except: pass  

def save_signal_perf_to_db():
    if not _signal_perf: return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                for sig, vals in _signal_perf.items():
                    cur.execute("""
                        INSERT INTO signal_performance (signal_name, correct_count, total_count)
                        VALUES (%s, %s, %s) ON CONFLICT (signal_name) DO UPDATE
                        SET correct_count = EXCLUDED.correct_count, total_count = EXCLUDED.total_count
                    """, (sig, vals[0], vals[1]))
                conn.commit()
    except: pass

SESSION_CONNECTED_SEC  = 45   
SESSION_SOFT_BREAK_SEC = 180  

def gap_classify(gap_sec: Optional[float]) -> str:
    if gap_sec is None: return 'hard_break'
    if gap_sec <= SESSION_CONNECTED_SEC: return 'connected'
    if gap_sec <= SESSION_SOFT_BREAK_SEC: return 'soft_break'
    return 'hard_break'

def seq_weight_from_gap(gap_sec: Optional[float], b_gap: Optional[float] = None) -> float:
    temporal_w   = get_temporal_weight(gap_sec)
    continuity_w = get_continuity_weight(b_gap)
    b_gap_penalty = math.exp(-(b_gap - 1000) / 3000.0) if b_gap is not None and b_gap > 1000 else 1.0
    return temporal_w * continuity_w * b_gap_penalty

_markov_cache: Optional[Dict] = None
_markov_ts: float = 0.0
_session_markov_cache: Optional[Dict] = None
_session_markov_ts: float = 0.0

def build_markov_from_seq(seq: List[int]) -> Dict:
    matrix = defaultdict(lambda: {0: 0, 1: 0})
    for i in range(len(seq) - 3): matrix[f"{seq[i]}{seq[i+1]}{seq[i+2]}"][seq[i+3]] += 1
    return dict(matrix)

def build_session_markov(connected_seq: List[int]) -> Dict:
    global _session_markov_cache, _session_markov_ts
    if _session_markov_cache is not None and time.time() - _session_markov_ts < 15: return _session_markov_cache
    clean = [x for x in connected_seq if x in [0, 1]]
    if len(clean) < 6: return {}
    _session_markov_cache = build_markov_from_seq(clean)
    _session_markov_ts    = time.time()
    return _session_markov_cache

def build_markov_matrix() -> Dict:
    global _markov_cache, _markov_ts
    if _markov_cache and time.time() - _markov_ts < 60: return _markov_cache
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner, created_at FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 600")
                rows = list(reversed(cur.fetchall()))
        connected_seq = [WINNER_MAP.get(w, 2) for w, _ in rows if WINNER_MAP.get(w, 2) in [0, 1]]
        _markov_cache = build_markov_from_seq(connected_seq)
        _markov_ts    = time.time()
        return _markov_cache
    except: return {}

def markov_predict(history: List[int], session_history: Optional[List[int]] = None) -> Tuple[Optional[int], float, str]:
    clean = [x for x in history if x in [0, 1]]
    if len(clean) < 3: return None, 0.0, ""
    key = f"{clean[-3]}{clean[-2]}{clean[-1]}"

    if session_history and len([x for x in session_history if x in [0,1]]) >= 6:
        sess_matrix = build_session_markov(session_history)
        counts = sess_matrix.get(key)
        if counts and (counts.get(0, 0) + counts.get(1, 0)) >= 3:
            r, b = counts.get(0, 0), counts.get(1, 0)
            pred = 0 if r > b else 1
            conf = max(r, b) / (r + b)
            if conf >= 0.55: return pred, conf, f"ماركوف-جلسة[{key}]→{r}🔴:{b}🔵"

    matrix = build_markov_matrix()
    counts = matrix.get(key)
    if not counts: return None, 0.0, ""
    r, b = counts.get(0, 0), counts.get(1, 0)
    if (r + b) < 4: return None, 0.0, ""
    pred = 0 if r > b else 1
    conf = max(r, b) / (r + b)
    if conf < 0.55: return None, 0.0, ""
    return pred, conf, f"ماركوف[{key}]→{r}🔴:{b}🔵"

def detect_cycle(history: List[int]) -> Tuple[Optional[int], float, str]:
    if len(history) < 6: return None, 0.0, ""
    for cycle_len in [2, 3, 4, 5, 6]:
        if len(history) < cycle_len * 2: continue
        recent = history[-cycle_len * 2:]
        if recent[:cycle_len] == recent[cycle_len:]:
            pred = recent[:cycle_len][len(history) % cycle_len]
            if pred in [0, 1]: return pred, min(0.70 + (cycle_len - 2) * 0.03, 0.88), f"دورة طولها {cycle_len}"
    if len(history) >= 4 and history[-4:] in ([0, 1, 0, 1], [1, 0, 1, 0]): return 1 - history[-1], 0.72, "نمط تبادلي"
    return None, 0.0, ""

def amplify_consensus(scores: Dict[int, float], signal_count: int) -> float:
    total = scores[0] + scores[1]
    if total == 0: return 1.0
    return min(1.0 + (abs(scores[0] - scores[1]) / total) * 0.6 * min(signal_count / 8, 1.0), 1.8)

def bnum_fingerprint(b_num: str, rank: str) -> List[Tuple[int, float, str]]:
    signals = []
    if not b_num: return signals
    digits = [int(d) for d in b_num]
    d_sum = sum(digits)
    d_prod = 1
    for d in digits: d_prod = (d_prod * max(d, 1)) % 97
    rv = RANK_VALUE.get(rank.upper(), 7)
    
    signals.append((0 if d_sum % 3 in [0, 2] else 1, 0.55, f"Σmod3={d_sum % 3}"))
    signals.append((0 if (d_sum + rv) % 4 in [0, 3] else 1, 0.58, f"(Σ+rank)mod4={(d_sum + rv) % 4}"))
    signals.append((0 if d_prod % 7 in [0, 1, 6] else 1, 0.52, f"Πmod7={d_prod % 7}"))
    signals.append(((digits[-1] * max(digits[0], 1) + rv) % 2, 0.54, f"L×F+rv"))
    signals.append((0 if sum(1 for d in digits if d % 2 == 1) % 2 == 0 else 1, 0.53, f"odds"))
    
    return signals

_lookalike_history_cache: List[int] = []
_lookalike_cache_ts: float = 0.0

def _refresh_lookalike_cache():
    global _lookalike_history_cache, _lookalike_cache_ts
    if time.time() - _lookalike_cache_ts < 45: return
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 800")
                _lookalike_history_cache = [x for x in reversed([WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]) if x in [0, 1]]
                _lookalike_cache_ts = time.time()
    except: pass

def lookalike_predict(recent: List[int], window: int = 8) -> Tuple[Optional[int], float, str]:
    _refresh_lookalike_cache()
    hist = _lookalike_history_cache
    if len(recent) < window or len(hist) < window + 1: return None, 0.0, ""
    query = recent[-window:]
    matches = []
    for i in range(len(hist) - window - 1):
        sim = sum(1 for a, b in zip(query, hist[i:i+window]) if a == b) / window
        if sim >= 0.70 and hist[i + window] in [0, 1]: matches.append((sim, hist[i + window]))
    if len(matches) < 3: return None, 0.0, ""
    matches.sort(key=lambda x: -x[0])
    votes = {0: 0.0, 1: 0.0}
    for sim, res in matches[:8]: votes[res] += sim
    total_v = votes[0] + votes[1]
    if total_v == 0: return None, 0.0, ""
    pred = 0 if votes[0] >= votes[1] else 1
    conf = max(votes[0], votes[1]) / total_v
    if conf < 0.58: return None, 0.0, ""
    return pred, conf, f"lookalike ({matches[0][0]:.0%} أعلى)"

def detect_regime(history: List[int]) -> Tuple[str, float]:
    last12 = [x for x in history[-12:] if x in [0, 1]]
    if len(last12) < 6: return "chaotic", 0.5
    r, b, n = last12.count(0), last12.count(1), len(last12)
    if r / n >= 0.70: return "banker_streak", r / n
    if b / n >= 0.70: return "player_streak", b / n
    if sum(1 for i in range(n-1) if last12[i] != last12[i+1]) / (n-1) >= 0.70: return "alternating", sum(1 for i in range(n-1) if last12[i] != last12[i+1]) / (n-1)
    return "chaotic", 0.5

def regime_vote(regime: str, conf: float, history: List[int]) -> Tuple[Optional[int], float, str]:
    def streak_of(val):
        n = 0
        for v in reversed(history):
            if v == val: n += 1
            else: break
        return n
    if regime == "banker_streak": return (1, 0.72, "كسر سيطرة الراعي") if streak_of(0) >= 5 else (0, conf * 0.85, "استمرار سيطرة الراعي")
    if regime == "player_streak": return (0, 0.72, "كسر سيطرة الثور") if streak_of(1) >= 5 else (1, conf * 0.85, "استمرار سيطرة الثور")
    if regime == "alternating":
        last = next((v for v in reversed(history) if v in [0,1]), None)
        if last is not None: return 1 - last, conf * 0.90, "تبادل"
    return None, 0.0, ""

def check_anti_mode() -> Tuple[bool, float]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner, prediction FROM history WHERE winner IS NOT NULL AND prediction IS NOT NULL ORDER BY id DESC LIMIT 15")
                rows = cur.fetchall()
        if len(rows) < 8: return False, 0.5
        acc = sum(1 for r in rows if WINNER_MAP.get(r[0],-1) == WINNER_MAP.get(r[1],-2)) / len(rows)
        return acc < 0.38, round(acc, 3)
    except: return False, 0.5

def bayesian_predict(suit: str, rank: str, last_digit: int) -> Tuple[Optional[int], float, str]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT SUM(CASE WHEN winner IN ('الراعي 🔴','راعي') THEN 1 ELSE 0 END)::float, SUM(CASE WHEN winner IN ('الثور 🔵','ثور') THEN 1 ELSE 0 END)::float, COUNT(*)::float FROM history WHERE winner IS NOT NULL")
                pr = cur.fetchone()
                if not pr or not pr[2] or pr[2] < 20: return None, 0.0, ""
                prior_r, prior_b = (pr[0] + 1) / (pr[2] + 2), (pr[1] + 1) / (pr[2] + 2)

                cur.execute("SELECT SUM(CASE WHEN winner IN ('الراعي 🔴','راعي') THEN 1 ELSE 0 END)::float, SUM(CASE WHEN winner IN ('الثور 🔵','ثور') THEN 1 ELSE 0 END)::float, COUNT(*)::float FROM history WHERE suit = %s AND bonus_last_digit = %s AND winner IS NOT NULL", (suit, last_digit))
                lk = cur.fetchone()
                if not lk or not lk[2] or lk[2] < 5: return None, 0.0, ""

                post_r, post_b = prior_r * ((lk[0] + 1) / (lk[2] + 2)), prior_b * ((lk[1] + 1) / (lk[2] + 2))
                if post_r + post_b == 0: return None, 0.0, ""
                nr, nb = post_r / (post_r + post_b), post_b / (post_r + post_b)
                if abs(nr - nb) < 0.06: return None, 0.0, ""
                return (0 if nr > nb else 1), max(nr, nb), f"P(🔴)={nr:.2f} P(🔵)={nb:.2f} n={int(lk[2])}"
    except: return None, 0.0, ""

def detect_momentum() -> Tuple[Optional[int], float, str]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner, created_at FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 4")
                rows = cur.fetchall()
        if len(rows) < 3 or (datetime.now() - rows[0][1]).total_seconds() > 300: return None, 0.0, ""
        recent = [WINNER_MAP.get(r[0], 2) for r in rows[:3]]
        if recent == [0, 0, 0]: return 1, 0.85, "كسر سلسلة الراعي"
        if recent == [1, 1, 1]: return 0, 0.85, "كسر سلسلة الثور"
    except: pass
    return None, 0.0, ""

async def ai_predict(recent_history: List[int]) -> Tuple[Optional[int], float, str]:
    if len(recent_history) < 3: return None, 0.0, "بيانات غير كافية"
    try:
        task = asyncio.create_task(_nvidia_chat([{"role": "user", "content": f"أنت محلل باكارات. 0=راعي، 1=ثور.\nالتسلسل: {recent_history}\nتوقّع الجولة التالية. أعد JSON فقط:\n{{\"winner\":0أو1,\"confidence\":50-95,\"reason\":\"سبب\"}}"}], max_tokens=256, temperature=0.3, enable_thinking=False, timeout=int(AI_TIMEOUT)))
        full = await asyncio.wait_for(task, timeout=AI_TIMEOUT)
        data = extract_json_safe(full)
        if data and isinstance(data, dict): return int(data.get("winner", 2)), float(data.get("confidence", 50)), data.get("reason", "")
    except: pass
    return None, 0.0, "خطأ"

def temporal_autocorr(history: List[int]) -> Tuple[Optional[int], float, str]:
    seq = [x for x in history if x in [0, 1]]
    if len(seq) < 20: return None, 0.0, ""
    best_lag, best_score, best_match = None, 0.0, 0.5
    for lag in range(1, min(16, len(seq) - 5)):
        pairs = [(seq[i - lag], seq[i]) for i in range(lag, len(seq))]
        if len(pairs) < 8: continue
        match_rate = sum(1 for a, b in pairs if a == b) / len(pairs)
        score = abs(match_rate - 0.5) * 2
        if score > best_score: best_score, best_lag, best_match = score, lag, match_rate
    if best_lag is None or best_score < 0.12: return None, 0.0, ""
    return (seq[-best_lag] if best_match >= 0.5 else 1 - seq[-best_lag]), min(0.54 + best_score * 0.35, 0.89), f"ارتباط زمني lag={best_lag}"

_ngram_cache: Dict[str, Tuple] = {}
_ngram_ts: float = 0.0

def ngram_db_predict(history: List[int]) -> Tuple[Optional[int], float, str]:
    global _ngram_cache, _ngram_ts
    clean = [x for x in history if x in [0, 1]]
    if len(clean) < 5: return None, 0.0, ""
    for n in [5, 4, 3]:
        if len(clean) < n: continue
        cache_key = f"ngram_{''.join(map(str, clean[-n:]))}"
        if cache_key in _ngram_cache and time.time() - _ngram_ts < 45:
            if _ngram_cache[cache_key][0] is not None: return _ngram_cache[cache_key]
        counts = {0: 0, 1: 0}
        for i in range(len(clean) - n - 1):
            if tuple(clean[i:i+n]) == tuple(clean[-n:]) and clean[i + n] in [0, 1]: counts[clean[i + n]] += 1
        total = counts[0] + counts[1]
        if total >= 3:
            conf = max(counts[0], counts[1]) / total
            if conf >= 0.58:
                result = (0 if counts[0] > counts[1] else 1, conf, f"N-gram({n}): {counts[0]}🔴:{counts[1]}🔵")
                _ngram_cache[cache_key] = result
                _ngram_ts = time.time()
                return result
    return None, 0.0, ""

_gap_hist_cache: Dict[str, Tuple] = {}
_gap_hist_ts: float = 0.0

def gap_history_predict(b_gap: Optional[float]) -> Tuple[Optional[int], float, str]:
    global _gap_hist_cache, _gap_hist_ts
    if b_gap is None: return None, 0.0, ""
    if b_gap < 50: gap_range, lo, hi = "nano", 0, 50
    elif b_gap < 200: gap_range, lo, hi = "tiny", 50, 200
    elif b_gap < 800: gap_range, lo, hi = "small", 200, 800
    elif b_gap < 3000: gap_range, lo, hi = "medium", 800, 3000
    elif b_gap < 10000: gap_range, lo, hi = "large", 3000, 10000
    else: gap_range, lo, hi = "xlarge", 10000, 9999999
    
    ck = f"gap_{gap_range}"
    if ck in _gap_hist_cache and time.time() - _gap_hist_ts < 120: return _gap_hist_cache[ck]
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT h2.winner FROM history h1 JOIN history h2 ON h2.id = h1.id + 1 WHERE h1.winner IS NOT NULL AND h2.winner IS NOT NULL AND h1.b_num ~ '^[0-9]+$' AND h2.b_num ~ '^[0-9]+$' AND ABS(h2.b_num::bigint - h1.b_num::bigint) BETWEEN %s AND %s ORDER BY h2.id DESC LIMIT 80", (lo, hi))
                rows = cur.fetchall()
        counts = {0: 0, 1: 0}
        for r in rows:
            w = WINNER_MAP.get(r[0], 2)
            if w in [0, 1]: counts[w] += 1
        total = counts[0] + counts[1]
        if total >= 6:
            conf = max(counts[0], counts[1]) / total
            if conf >= 0.55:
                result = (0 if counts[0] > counts[1] else 1, conf, f"فجوة-تاريخ {gap_range}: {counts[0]}🔴:{counts[1]}🔵")
                _gap_hist_cache[ck] = result
                _gap_hist_ts = time.time()
                return result
    except: pass
    return None, 0.0, ""

def overdue_detector(history: List[int]) -> Tuple[Optional[int], float, str]:
    clean = [x for x in history if x in [0, 1]]
    if len(clean) < 15: return None, 0.0, ""
    last_seen = {0: 0, 1: 0}
    for i, v in enumerate(reversed(clean)):
        if v in last_seen and last_seen[v] == 0: last_seen[v] = i + 1
        if all(last_seen.values()): break
    threshold = max(6, (len(clean) / max(clean.count(0) + clean.count(1), 1) * 2) * 1.5)
    if last_seen[0] > threshold and last_seen[0] > last_seen[1] * 2: return 0, min(0.80, 0.55 + (last_seen[0] - threshold) * 0.02), f"الراعي متأخر {last_seen[0]} جولة"
    if last_seen[1] > threshold and last_seen[1] > last_seen[0] * 2: return 1, min(0.80, 0.55 + (last_seen[1] - threshold) * 0.02), f"الثور متأخر {last_seen[1]} جولة"
    return None, 0.0, ""

_post_break_cache: Dict[str, Tuple] = {}
_post_break_ts: float = 0.0

def post_break_predict(gap_classify_result: str, b_gap: Optional[float]) -> Tuple[Optional[int], float, str]:
    global _post_break_cache, _post_break_ts
    if gap_classify_result == 'connected': return None, 0.0, ""
    cache_key = f"pb_{gap_classify_result}"
    if cache_key in _post_break_cache and time.time() - _post_break_ts < 120: return _post_break_cache[cache_key]
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT h2.winner, EXTRACT(EPOCH FROM (h2.created_at - h1.created_at)) AS gap_s FROM history h1 JOIN history h2 ON h2.id = h1.id + 1 WHERE h1.winner IS NOT NULL AND h2.winner IS NOT NULL AND h1.created_at IS NOT NULL AND h2.created_at IS NOT NULL ORDER BY h2.id DESC LIMIT 400")
                counts = {0: 0, 1: 0}
                for winner_str, gap_s in cur.fetchall():
                    if gap_s is None: continue
                    gap_s = float(gap_s)
                    if (gap_classify_result == 'soft_break' and not (SESSION_CONNECTED_SEC < gap_s <= SESSION_SOFT_BREAK_SEC)) or (gap_classify_result == 'hard_break' and gap_s <= SESSION_SOFT_BREAK_SEC): continue
                    w = WINNER_MAP.get(winner_str, 2)
                    if w in [0, 1]: counts[w] += 1
                total = counts[0] + counts[1]
                if total >= 8:
                    conf = max(counts[0], counts[1]) / total
                    if conf >= 0.55:
                        result = (0 if counts[0] > counts[1] else 1, conf, f"ما بعد الانقطاع: {counts[0]}🔴:{counts[1]}🔵")
                        _post_break_cache[cache_key] = result
                        _post_break_ts = time.time()
                        return result
    except: pass
    return None, 0.0, ""

def session_chain_stats(connected_history: List[int]) -> Tuple[Optional[int], float, str]:
    clean = [x for x in connected_history if x in [0, 1]]
    n = len(clean)
    if n < 4: return None, 0.0, ""
    r, b = clean.count(0), clean.count(1)
    if r + b == 0: return None, 0.0, ""
    bias = abs(r - b) / (r + b)
    if bias >= 0.30 and (r + b) >= 6: return (0 if r > b else 1), min(0.68, 0.55 + bias * 0.4), f"انحياز-جلسة({n} جولة)"
    if n >= 6:
        lh_bias = (clean[n//2:].count(1) - clean[n//2:].count(0)) / len(clean[n//2:])
        fh_bias = (clean[:n//2].count(1) - clean[:n//2].count(0)) / len(clean[:n//2])
        if abs(lh_bias) > abs(fh_bias) + 0.20 and abs(lh_bias) >= 0.35: return (1 if lh_bias > 0 else 0), 0.62, "تسارع-جلسة"
    return None, 0.0, ""

def calibrate_confidence(raw_conf: int, scores: Dict[int, float]) -> int:
    total = scores[0] + scores[1]
    dominance = abs(scores[0] - scores[1]) / total if total > 0 else 0.0
    overall = _signal_perf.get('OVERALL', [0, 0])
    if overall[1] >= 30:
        real_acc = overall[0] / overall[1]
        if real_acc < 0.48: raw_conf = max(55, int(raw_conf * 0.82))
        elif real_acc > 0.67: raw_conf = min(97, int(raw_conf * 1.08))
    if dominance > 0.70: raw_conf = min(97, raw_conf + 4)
    elif dominance < 0.10: raw_conf = max(55, raw_conf - 5)
    return raw_conf

def exact_pattern_predict(suit: str, rank: str, last_digit: int) -> Tuple[Optional[int], float, str]:
    res = get_pattern(f"EXACT_{suit}_{rank}_{last_digit}")
    if res['w'] == 2 or res['c'] < 0.05:
        res2 = get_pattern(f"RANK_{rank}_SUIT_{suit}")
        if res2['w'] != 2 and res2['c'] > 0.05: return res2['w'], res2['c'], f"EXACT≈RANK_SUIT"
        return None, 0.0, ""
    return res['w'], res['c'], f"EXACT"

_full_history_cache: List[int] = []
_full_hist_ts: float = 0.0

def get_full_history(n: int = 600) -> List[int]:
    global _full_history_cache, _full_hist_ts
    if _full_history_cache and time.time() - _full_hist_ts < 30: return _full_history_cache
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT %s", (n,))
                _full_history_cache = [x for x in reversed([WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]) if x in [0, 1]]
                _full_hist_ts = time.time()
                return _full_history_cache
    except: return []

def deep_ngram_predict(recent: List[int]) -> Tuple[Optional[int], float, str]:
    full = get_full_history(600)
    clean_recent = [x for x in recent if x in [0,1]]
    if len(clean_recent) < 3 or len(full) < 20: return None, 0.0, ""
    best = (None, 0.0, "")
    for n in [6, 5, 4, 3]:
        if len(clean_recent) < n or len(full) < n + 3: continue
        needle = tuple(clean_recent[-n:])
        counts = {0: 0, 1: 0}
        for i in range(len(full) - n - 1):
            if tuple(full[i:i+n]) == needle and full[i+n] in [0,1]: counts[full[i+n]] += 1
        total = counts[0] + counts[1]
        if total >= 4:
            conf = max(counts[0], counts[1]) / total
            if conf >= 0.60 and conf > best[1]: best = (0 if counts[0] > counts[1] else 1, conf, f"DeepNGram({n})")
    return best

def hot_switch_detector(history: List[int]) -> Tuple[Optional[int], float, str]:
    clean = [x for x in history if x in [0,1]]
    if len(clean) < 8: return None, 0.0, ""
    last8 = clean[-8:]
    switches = sum(1 for i in range(1, len(last8)) if last8[i] != last8[i-1])
    if switches >= 6: return 1 - last8[-1], 0.72, f"تبادل سريع ({switches}/7)"
    elif switches <= 1: return last8[-1], 0.68, f"ثبات كامل ({8-switches}/7)"
    return None, 0.0, ""

_gravity_cache: Tuple = (None, 0.0, "")
_gravity_ts: float = 0.0

def historical_gravity() -> Tuple[Optional[int], float, str]:
    global _gravity_cache, _gravity_ts
    if _gravity_cache[0] is not None and time.time() - _gravity_ts < 20: return _gravity_cache
    full = get_full_history(300)
    if len(full) < 50: return None, 0.0, ""
    weighted, total_w = {0: 0.0, 1: 0.0}, 0.0
    for win_size, weight in [(50, 0.40), (100, 0.35), (200, 0.25)]:
        if len(full) < win_size: continue
        window = full[-win_size:]
        r, b = window.count(0), window.count(1)
        if r + b == 0: continue
        bias = abs(r-b)/(r+b)
        if bias >= 0.05:
            weighted[0 if r > b else 1] += bias * weight
            total_w += weight
    if total_w == 0 or max(weighted[0], weighted[1]) / total_w < 0.04:
        _gravity_cache = (None, 0.0, "")
    else:
        best = 0 if weighted[0] > weighted[1] else 1
        _gravity_cache = (best, min(0.72, 0.52 + (max(weighted[0], weighted[1]) / total_w) * 3.0), "جذب تاريخي")
    _gravity_ts = time.time()
    return _gravity_cache

def dynamic_majority_vote(signals: List[Tuple[Optional[int], float, str]]) -> Tuple[Optional[int], float, int, int]:
    votes, n_valid = {0: 0.0, 1: 0.0}, 0
    for pred, conf, _ in signals:
        if pred in [0, 1]:
            votes[pred] += conf
            n_valid += 1
    if n_valid < 2: return None, 0.0, 0, 0
    return (0 if votes[0] > votes[1] else 1), max(votes[0], votes[1]) / max(votes[0] + votes[1], 0.01), sum(1 for p,_,_ in signals if p == (0 if votes[0] > votes[1] else 1)), n_valid

def baccarat_card_counter(history_ranks: List[str]) -> Tuple[Optional[int], float, str]:
    if len(history_ranks) < 10: return None, 0.0, ""
    running_count = sum(2 if str(r).upper().strip() in ['4', '5', '6'] else (-2 if str(r).upper().strip() in ['8', '9'] else 0) for r in history_ranks)
    if running_count >= 6: return 0, min(0.82, 0.55 + running_count * 0.02), f"عد الأوراق (+{running_count})"
    elif running_count <= -6: return 1, min(0.82, 0.55 + abs(running_count) * 0.02), f"عد الأوراق ({running_count})"
    return None, 0.0, ""

def shannon_entropy_sniper(history: List[int]) -> Tuple[bool, float, str]:
    clean = [x for x in history if x in [0, 1]]
    if len(clean) < 12: return False, 0.0, ""
    last15 = clean[-15:]
    p_red, p_blue = last15.count(0) / len(last15), last15.count(1) / len(last15)
    entropy = 0.0 if p_red == 0 or p_blue == 0 else -(p_red * math.log2(p_red) + p_blue * math.log2(p_blue))
    volatility = sum(1 for i in range(1, len(last15)) if last15[i] != last15[i-1]) / len(last15)
    if entropy > 0.95 and volatility > 0.65: return True, entropy, f"فوضى رياضية (entropy={entropy:.2f}, vol={volatility:.2f})"
    return False, entropy, f"استقرار (entropy={entropy:.2f})"

async def predict(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم بونص غير صالح"
    last_digit = int(clean_b[-1])
    scores, logs = {0: 0.0, 1: 0.0}, []

    recent_history, all_history, b_gap, gap_sec, round_index = [], [], None, None, int(time.time())
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner, b_num, created_at FROM history WHERE winner IS NOT NULL AND rank IS NOT NULL AND rank NOT IN ('NULL','') ORDER BY id DESC LIMIT 40")
                rows = cur.fetchall()
                if rows:
                    last_b = clean_digits(str(rows[0][1] or ""))
                    if last_b and clean_b:
                        try: b_gap = abs(int(clean_b) - int(last_b))
                        except: pass
                    if rows[0][2]: gap_sec = (datetime.now() - rows[0][2]).total_seconds()
                    
                    connected_rows = [rows[0]]
                    for i in range(1, len(rows)):
                        if rows[i-1][2] and rows[i][2] and (rows[i-1][2] - rows[i][2]).total_seconds() > SESSION_CONNECTED_SEC: break
                        connected_rows.append(rows[i])
                    recent_history = [WINNER_MAP.get(r[0], 2) for r in reversed(connected_rows)]
                    all_history = [WINNER_MAP.get(r[0], 2) for r in reversed(rows)]
    except: pass

    session_type = gap_classify(gap_sec)
    seq_weight = seq_weight_from_gap(gap_sec, b_gap=b_gap)
    is_new_session = session_type != 'connected'

    SESSION_LABELS = {'connected': f"🟢 متصلة ({len(recent_history)} جولة)", 'soft_break': f"🟡 كسر ناعم ({gap_sec:.0f}ث)" if gap_sec else "🟡 كسر ناعم", 'hard_break': f"🔴 جلسة جديدة ({gap_sec:.0f}ث)" if gap_sec else "🔴 بداية"}
    logs.append(f"{'🔗 b_gap=' + str(int(b_gap)) + ' | ' if b_gap else ''}⏱️ {gap_sec:.0f}ث | {SESSION_LABELS[session_type]} | seq_w={seq_weight:.2f}")

    ai_task = asyncio.create_task(ai_predict(all_history[-20:] if all_history else recent_history))

    law_scores, law_logs = apply_laws(suit, rank, last_digit, recent_history, b_num=clean_b, b_gap=b_gap, gap_sec=gap_sec, round_index=round_index)
    scores[0] += law_scores[0]; scores[1] += law_scores[1]
    logs.extend(law_logs)

    mom_pred, mom_conf, mom_log = detect_momentum()
    if mom_pred is not None:
        scores[mom_pred] += mom_conf * WEIGHTS['MOMENTUM']
        logs.append(f"⏱️ الزخم: {WINNER_NAMES[mom_pred]} ({mom_log})")

    for pid, wkey, desc in [(f"SD_{suit}_{last_digit}", 'SD', '✨ بذلة+رقم'), (f"SUIT_{suit}", 'SUIT', '🎴 البذلة'), (f"DIGIT_{last_digit}", 'DIGIT', '🔢 الرقم'), (f"RANK_{rank}", 'RANK', '🃏 الرتبة')]:
        res = get_pattern(pid)
        if res['w'] != 2 and res['c'] > 0.0:
            scores[res['w']] += res['c'] * WEIGHTS[wkey]
            logs.append(f"{desc}: {WINNER_NAMES[res['w']]} {res['log']}")

    try:
        ai_pred, ai_conf, ai_log = await asyncio.wait_for(ai_task, timeout=0.8)
        if ai_pred in [0, 1]:
            scores[ai_pred] += (ai_conf / 100) * WEIGHTS['AI']
            logs.append(f"🤖 Qwen: {WINNER_NAMES[ai_pred]} — {ai_log}")
    except: pass

    streak_pred, streak_conf = detect_real_streak(recent_history)
    if streak_pred is not None and not is_new_session:
        scores[streak_pred] += streak_conf * get_adaptive_weight('STREAK', WEIGHTS['MOMENTUM'])
        logs.append(f"⚡ كسر سلسلة: {WINNER_NAMES[streak_pred]}")

    mem_pred, mem_conf = short_memory_bias(recent_history)
    if mem_pred is not None:
        scores[mem_pred] += mem_conf * get_adaptive_weight('SHORT_MEM', 1.4) * seq_weight
        logs.append(f"🧠 ذاكرة قصيرة: {WINNER_NAMES[mem_pred]}")

    sb_pred, sb_conf = suit_bias_from_history(suit)
    if sb_pred is not None:
        scores[sb_pred] += sb_conf * get_adaptive_weight('SUIT_BIAS', 1.6)
        logs.append(f"📊 انحياز البذلة: {WINNER_NAMES[sb_pred]}")

    mkv_pred, mkv_conf, mkv_log = markov_predict(recent_history if len(recent_history) >= 4 else all_history, session_history=recent_history)
    if mkv_pred is not None:
        scores[mkv_pred] += mkv_conf * get_adaptive_weight('MARKOV', 2.5) * seq_weight
        logs.append(f"🔗 {mkv_log}")

    cyc_pred, cyc_conf, cyc_log = detect_cycle(recent_history if len(recent_history) >= 6 else all_history)
    if cyc_pred is not None:
        scores[cyc_pred] += cyc_conf * get_adaptive_weight('CYCLE', 2.0)
        logs.append(f"🔄 {cyc_log} → {WINNER_NAMES[cyc_pred]}")

    fp_signals = bnum_fingerprint(clean_b, rank)
    for fp_pred, fp_w, _ in fp_signals:
        if fp_pred in [0, 1]: scores[fp_pred] += fp_w
    if fp_signals: logs.append(f"🧮 بصمة رقمية ({len(fp_signals)}): {' | '.join(f'{WINNER_NAMES[p][0]}{l}' for p, _, l in fp_signals if p in [0, 1])}")

    math_rule = (sum(int(d) for d in clean_b) + last_digit) % 2
    boost = 0.4 if is_prime(int(clean_b) % 97) else 0.0
    scores[math_rule] += 0.8 + boost
    logs.append(f"🔢 مجموع الأرقام → {WINNER_NAMES[math_rule]}")

    lk_pred, lk_conf, lk_log = lookalike_predict(recent_history)
    if lk_pred is not None:
        scores[lk_pred] += lk_conf * get_adaptive_weight('LOOKALIKE', 2.2)
        logs.append(f"🧬 {lk_log} → {WINNER_NAMES[lk_pred]}")

    regime, reg_conf = detect_regime(recent_history)
    rg_pred, rg_conf, rg_log = regime_vote(regime, reg_conf, recent_history)
    if rg_pred is not None:
        scores[rg_pred] += rg_conf * get_adaptive_weight('REGIME', 2.8)
        logs.append(f"🧠 النظام: {rg_log}")

    bay_pred, bay_conf, bay_log = bayesian_predict(suit, rank, last_digit)
    if bay_pred is not None:
        scores[bay_pred] += bay_conf * get_adaptive_weight('BAYESIAN', 3.0)
        logs.append(f"📊 بايز: {bay_log} → {WINNER_NAMES[bay_pred]}")

    ac_pred, ac_conf, ac_log = temporal_autocorr(recent_history)
    if ac_pred is not None:
        scores[ac_pred] += ac_conf * get_adaptive_weight('AUTOCORR', 1.4)
        logs.append(f"🕰️ {ac_log} → {WINNER_NAMES[ac_pred]}")

    ng_pred, ng_conf, ng_log = ngram_db_predict(recent_history)
    if ng_pred is not None:
        scores[ng_pred] += ng_conf * get_adaptive_weight('NGRAM', 2.4)
        logs.append(f"🔍 {ng_log} → {WINNER_NAMES[ng_pred]}")

    gh_pred, gh_conf, gh_log = gap_history_predict(b_gap)
    if gh_pred is not None:
        scores[gh_pred] += gh_conf * get_adaptive_weight('GAP_HIST', 1.8)
        logs.append(f"📏 {gh_log} → {WINNER_NAMES[gh_pred]}")

    od_pred, od_conf, od_log = overdue_detector(recent_history)
    if od_pred is not None:
        scores[od_pred] += od_conf * get_adaptive_weight('OVERDUE', 1.5)
        logs.append(f"⏳ {od_log} → {WINNER_NAMES[od_pred]}")

    pb_pred, pb_conf, pb_log = None, 0.0, ""
    try: pb_pred, pb_conf, pb_log = post_break_predict(session_type, b_gap)
    except: pass
    if pb_pred is not None:
        scores[pb_pred] += pb_conf * get_adaptive_weight('POST_BREAK', 2.0 if session_type == 'hard_break' else 1.2)
        logs.append(f"🔀 {pb_log} → {WINNER_NAMES[pb_pred]}")

    sc_pred, sc_conf, sc_log = None, 0.0, ""
    try: sc_pred, sc_conf, sc_log = session_chain_stats(recent_history)
    except: pass
    if sc_pred is not None and session_type == 'connected':
        scores[sc_pred] += sc_conf * get_adaptive_weight('SESSION_CHAIN', 1.6)
        logs.append(f"🔢 {sc_log}")

    cc_pred, cc_conf, cc_log = None, 0.0, ""
    try:
        with db_pool.get_conn() as _cc_conn:
            with _cc_conn.cursor() as _cc_cur:
                _cc_cur.execute("SELECT rank FROM history WHERE rank IS NOT NULL AND rank NOT IN ('NULL','') AND created_at >= NOW() - INTERVAL '30 minutes' ORDER BY id DESC LIMIT 40")
                recent_ranks = [r[0] for r in _cc_cur.fetchall() if r[0]]
        recent_ranks.append(rank)
        cc_pred, cc_conf, cc_log = baccarat_card_counter(recent_ranks)
    except: pass
    if cc_pred is not None:
        scores[cc_pred] += cc_conf * get_adaptive_weight('CARD_COUNT', 3.5)
        logs.append(f"🃏 {cc_log}")

    is_chaos, entropy_val, chaos_log = shannon_entropy_sniper(recent_history)
    if is_chaos:
        logs.extend([f"🛑 {chaos_log}", "🛡️ وضع القناص: فوضى رياضية — تخطي الجولة"])
        return 2, 0, "\n".join(logs)

    golden = [bay_pred, mkv_pred, cc_pred]
    if all(p is not None for p in golden) and len(set(golden)) == 1:
        scores[golden[0]] *= 2.5
        logs.append(f"✨ التقاطع الذهبي: بايز + ماركوف + عد الأوراق → {WINNER_NAMES[golden[0]]}")

    mv_pred, mv_conf, mv_agree, mv_total = dynamic_majority_vote([(lk_pred, lk_conf, "lk"), (rg_pred, rg_conf, "rg"), (bay_pred, bay_conf if bay_pred is not None else 0.0, "bay"), (ng_pred, ng_conf if ng_pred is not None else 0.0, "dn"), (pb_pred, pb_conf if pb_pred is not None else 0.0, "pb")])
    if mv_pred is not None and mv_total >= 4:
        scores[mv_pred] += mv_conf * 1.8 * (mv_agree / max(mv_total, 1))
        logs.append(f"🏆 أغلبية: {WINNER_NAMES[mv_pred]} ({mv_agree}/{mv_total} محركات)")

    total_score = scores[0] + scores[1]
    if total_score > 0:
        ratio = max(scores[0], scores[1]) / total_score
        if ratio > 0.80:
            correction = (ratio - 0.70) * total_score
            scores[0] += correction if scores[0] < scores[1] else -correction
            scores[1] += correction if scores[1] < scores[0] else -correction

    total_score = scores[0] + scores[1]
    if total_score == 0:
        math_res = ((sum(int(d) for d in clean_b.zfill(3)[-3:]) * RANK_VALUE.get(rank.upper(), 1)) + last_digit) % 2
        logs.append("🧮 تحليل رياضي احتياطي")
        return math_res, 60, "\n".join(logs)

    p0, p1 = scores[0] / total_score, scores[1] / total_score
    entropy = -(p0 * math.log2(p0 + 1e-9) + p1 * math.log2(p1 + 1e-9))
    
    _, recent_acc = check_anti_mode()
    final_conf = int(min(97, max(55, 55 + 40 * (1 - entropy) + max(0, (recent_acc - 0.50) * 30))))

    delta = abs(scores[0] - scores[1])
    if delta < 0.05 * max(scores[0], scores[1], 0.01):
        if bay_pred is not None: final, logs_msg = bay_pred, "⚖️ حاكم بايزي"
        elif gv_pred is not None if 'gv_pred' in locals() else False: final, logs_msg = gv_pred, "⚖️ جذب تاريخي"
        else:
            logs.append("⚠️ إجماع معدوم — تخطي")
            return 2, 50, "\n".join(logs)
        logs.append(f"{logs_msg} → {WINNER_NAMES[final]}")
    else: final = 0 if scores[0] > scores[1] else 1

    if total_score > 0: logs.append(f"📊 🔴{scores[0]:.2f} vs 🔵{scores[1]:.2f} | {scores[0]/total_score*100:.0f}%/{scores[1]/total_score*100:.0f}% | Δ={delta:.2f}")

    final_conf = calibrate_confidence(final_conf, scores)

    signal_json = json.dumps({
        'MARKOV': mkv_pred, 'CYCLE': cyc_pred, 'STREAK': streak_pred, 'SHORT_MEM': mem_pred,
        'SUIT_BIAS': sb_pred, 'MOM': mom_pred, 'LOOKALIKE': lk_pred, 'REGIME': rg_pred,
        'BAYESIAN': bay_pred, 'AUTOCORR': ac_pred, 'NGRAM': ng_pred, 'GAP_HIST': gh_pred,
        'OVERDUE': od_pred, 'POST_BREAK': pb_pred, 'SESSION_CHAIN': sc_pred, 'OVERALL': final,
    })
    logs.append(f"__signals__{signal_json}")

    return final, final_conf, "\n".join(logs)

CONFIDENCE_TIER = [(90, "🔥 عالية جداً", "▓▓▓▓▓▓▓▓▓▓"), (80, "⚡ عالية", "▓▓▓▓▓▓▓▓░░"), (70, "✅ متوسطة-عالية", "▓▓▓▓▓▓░░░░"), (60, "📊 متوسطة", "▓▓▓▓░░░░░░"), (0, "❓ ضعيفة", "▓▓░░░░░░░░")]

def confidence_display(conf: int):
    return next((label, bar) for threshold, label, bar in CONFIDENCE_TIER if conf >= threshold)

def format_prediction(pred: int, conf: int, reason: str, suit: str, rank: str, b_num: str) -> str:
    ld, name, laws_count, sig_count = get_last_digit(b_num), WINNER_NAMES[pred], len(load_laws()), sum(1 for v in _signal_perf.values() if v[1] > 0)
    conf_label, conf_bar = confidence_display(conf)
    
    analysis_lines = [l if any(t in l for t in ["<b>","</b>","<i>","</i>","<code>","</code>"]) else html.escape(l) for l in reason.split("\n") if l.strip() and not l.startswith("__signals__")]
    pred_symbol = "🔴" if pred == 0 else "🔵"
    agree = [l for l in analysis_lines if pred_symbol in l]
    disagree = [l for l in analysis_lines if pred_symbol not in l and "🔗" not in l and "⏱️" not in l][:3]
    context = [l for l in analysis_lines if "🔗" in l or "⏱️" in l]
    
    analysis_txt = ("\n".join(agree[:8]) + "\n" if agree else "") + ("\n".join(disagree[:3]) + "\n" if disagree else "") + ("\n".join(context) + "\n" if context else "")
    engine_status = "⚡ 19 محرك نشط" if sig_count >= 15 else "⚡ محركات كاملة" if sig_count >= 10 else "🔄 محركات متقدمة" if sig_count >= 6 else "🔧 تعلم أولي"
    header_emoji = "🔴" if pred == 0 else "🔵"

    return f"{'━'*22}\n{header_emoji}  <b>التوقع: {name}</b>  {header_emoji}\n{'━'*22}\n🃏 {suit} {rank}  |  #{b_num}  |  رقم: {ld}\n\n📊 الثقة: <b>{conf}%</b>  {conf_label}\n<code>{conf_bar}</code>\n\n⚙️ {engine_status}  |  ⚖️ {laws_count} قانون\n{'━'*22}\n<b>📋 التحليل ({len(agree)} موافق / {len(disagree)} معارض):</b>\n{analysis_txt}{'━'*22}"

def result_keyboard(pred: int, b_num: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ الراعي 🔴", callback_data=f"save_0_{b_num}"), InlineKeyboardButton("✅ الثور 🔵", callback_data=f"save_1_{b_num}"), InlineKeyboardButton("✅ تعادل ⚪", callback_data=f"save_2_{b_num}")], [InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")]])

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"<b>🧠 HADES V21 — نظام التنبؤ الأسطوري</b>\n{'━'*24}\n⚙️ <b>المحركات النشطة: 21</b>\n  ⚖️ قوانين AI: <b>{len(load_laws())}</b>\n  🔗 ماركوف-جلسة  |  🔄 دورات  |  🧬 DeepNGram\n  🕰️ ارتباط زمني  |  🎯 EXACT  |  🏆 أغلبية\n  ⚡ Hot-Switch  |  🧲 جذب تاريخي  |  ⏳ متأخر\n  🔀 ما بعد الانقطاع  |  🔢 إحصاءات السلسلة\n  ⏱️ حد الاتصال: <b>45 ث</b> | كسر: >45 ث\n{'━'*24}\n📋 <b>الأوامر:</b>\n  🎮 /start — بدء جولة جديدة\n  📊 /stats — لوحة الإحصاءات الحية\n  ⚖️ /laws  — عرض القوانين النشطة\n  📥 /download — تصدير قاعدة البيانات\n  🔬 /force_learn — تعلم عميق (مشرف)\n  ⛏️ /mine_gold — تعدين ذهبي (مشرف)\n  🏛️ /council_learn — مجلس الآلهة (مشرف)\n  ✂️ /prune — تنظيف القوانين الميتة (مشرف)\n  🔄 /reset_laws — إعادة تعيين (مشرف)\n{'━'*24}\n🎴 اختر البذلة للبدء:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(SUITS[i], callback_data=f"suit_{i}") for i in range(len(SUITS))]]))

async def cmd_force_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
    msg = await update.message.reply_text("🧠 <b>بدء جلسة التعلم العميق...</b>\nسيتم تحليل كل الجولات السابقة واستخراج قوانين ذكية.\n<i>لا تُلغِ العملية — قد تستغرق عدة دقائق.</i>", parse_mode="HTML")
    async def status_update(text: str):
        try: await msg.edit_text(text, parse_mode="HTML")
        except: pass
    result = await force_learn_engine(status_update)
    if "error" in result: return await msg.edit_text(f"❌ <b>فشلت جلسة التعلم</b>\n\n<code>{result['error']}</code>", parse_mode="HTML")
    sample_text = "".join(f"\n<b>{i}.</b> [{law.get('law_type','?')}] → {WINNER_NAMES.get(law.get('prediction', 2), '?')} ({law.get('confidence',0):.0f}%)\n   <i>{law.get('description','')[:80]}</i>" for i, law in enumerate(result.get("sample_laws", []), 1))
    await msg.edit_text(f"✅ <b>اكتملت جلسة التعلم العميق!</b>\n\n━━━━━━━━━━━━━━━━━━━━━━\n🎮 الجولات المحللة: <b>{result['total_rounds']}</b>\n🔬 Backtest على: <b>{result.get('backtest_rows', 0)}</b> جولة\n✅ قوانين نجحت: <b>{result['laws_saved']}</b>\n❌ مرفوضة (backtest): <b>{result.get('laws_rejected', 0)}</b>\n⏭️ غير صالحة: <b>{result.get('laws_skipped', 0)}</b>\n🆔 رقم الجلسة: <b>#{result.get('session_id', '?')}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<b>عينة من القوانين:</b>{sample_text}\n━━━━━━━━━━━━━━━━━━━━━━\n🧠 الذاكرة السياقية تم تحديثها.", parse_mode="HTML")

async def cmd_engine_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
    _, recent_acc = check_anti_mode()
    regime_str = "غير محدد"
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 20")
                hist = [WINNER_MAP.get(r[0], 2) for r in reversed(cur.fetchall())]
        regime, reg_conf = detect_regime([x for x in hist if x in [0,1]])
        regime_str = f"{({'banker_streak':'🔴 سيطرة الراعي','player_streak':'🔵 سيطرة الثور','alternating':'🔁 تبادل منتظم','chaotic':'❓ فوضى'}.get(regime, regime))} ({reg_conf:.0%})"
    except: pass
    sig_text = "\n".join(f"  <code>{name:<12}</code> [{'█'*int(vals[0]/vals[1]*10)+'░'*(10-int(vals[0]/vals[1]*10))}] {vals[0]/vals[1]:.0%} ({int(vals[1])} جولة)" for name, vals in sorted(_signal_perf.items()) if vals[1] >= 3) or "  لا بيانات بعد"
    await update.message.reply_text(f"━━━━━━━━━━━━━━━━━━━━━━\n⚙️ <b>حالة المحركات — HADES V21</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n📈 <b>الدقة الحالية (آخر 15):</b> {recent_acc:.0%}\n\n🧠 <b>نظام اللعبة الحالي:</b>\n  {regime_str}\n\n⚖️ <b>القوانين الذكية النشطة:</b> {len(load_laws())}\n\n📊 <b>أداء الإشارات (تكيّفي):</b>\n{sig_text}\n\n━━━━━━━━━━━━━━━━━━━━━━\n🤖 المحركات: Ensemble • Regime • Bayesian • Markov • Cluster Boost\n  ⏱️ حد الاتصال: 45ث | كسر قوي: >45ث | بونص جاب: 3000", parse_mode="HTML")

async def cmd_laws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, law_type, prediction, confidence, accuracy, times_used, description FROM ai_laws WHERE active = TRUE ORDER BY accuracy DESC, times_used DESC LIMIT 25")
                all_active = cur.fetchall()
    except: all_active = []
    if not all_active: return await update.message.reply_text("⚠️ لا توجد قوانين نشطة. استخدم /force_learn أولاً.")
    text = f"⚖️ <b>القوانين النشطة ({len(all_active)})</b>\n━━━━━━━━━━━━━━━━━━━━━━\n" + "".join(f"\n<b>#{r[0]}</b> {'🔴' if r[2]==0 else '🔵'} [{r[1]}] → {WINNER_NAMES.get(r[2], '?')}\n  دقة: {r[4]:.0f}% | conf: {r[3]:.0f}% | ×{r[5]}\n  <i>{html.escape(str(r[6] or ''))[:65]}</i>\n" for r in all_active[:20]) + (f"\n<i>... و{len(all_active)-20} قانون إضافي — استخدم /prune للتنظيف</i>" if len(all_active)>20 else "")
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🗑️ حذف #{r[0]} [{r[1][:20]}]", callback_data=f"deact_law_{r[0]}")] for r in all_active[:20]]) if update.effective_user.id == ADMIN_ID else None)

async def cmd_deactivate_law(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return await update.message.reply_text("⛔ للمشرف فقط.")
    if not context.args: return await update.message.reply_text("⚠️ استخدم: <code>/deactivate &lt;id&gt;</code>", parse_mode="HTML")
    try: law_id = int(context.args[0])
    except: return await update.message.reply_text("❌ الـ ID يجب أن يكون رقماً.")
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT law_type, prediction, accuracy, times_used FROM ai_laws WHERE id = %s", (law_id,))
                row = cur.fetchone()
                if not row: return await update.message.reply_text(f"⚠️ لا يوجد قانون بالـ ID {law_id}")
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE id = %s", (law_id,))
                conn.commit()
        load_laws(force=True)
        await update.message.reply_text(f"✅ <b>تم تعطيل القانون #{law_id}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n📌 النوع: [{row[0]}] → {WINNER_NAMES.get(row[1], '?')}\n📊 الدقة: {row[2]:.0f}% | الاستخدام: {row[3]}\n━━━━━━━━━━━━━━━━━━━━━━\n🔄 الذاكرة النشطة تم تحديثها.", parse_mode="HTML")
    except Exception as e: await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

async def safe_edit(query, text: str, reply_markup=None):
    from telegram.error import BadRequest
    try: await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" not in str(e): logger.error(f"safe_edit: {e}")
    except Exception as e: logger.error(f"safe_edit: {e}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try: await query.answer()
    except: pass
    data = query.data
    try:
        if data == "choose_suit":
            context.user_data.pop('suit', None); context.user_data.pop('rank', None)
            await safe_edit(query, "🎴 اختر البذلة:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(SUITS[i], callback_data=f"suit_{i}") for i in range(len(SUITS))]]))
        elif data.startswith("suit_"):
            idx = int(data.split("_")[1])
            context.user_data.update({'suit': SUITS[idx], 'suit_idx': idx})
            rows = [[InlineKeyboardButton(r, callback_data=f"rank_{r}") for r in row] for row in RANKS_LAYOUT] + [[InlineKeyboardButton("🔙 تغيير البذلة", callback_data="choose_suit")]]
            await safe_edit(query, f"البذلة: <b>{SUITS[idx]}</b>\nاختر الرتبة:", reply_markup=InlineKeyboardMarkup(rows))
        elif data.startswith("rank_"):
            context.user_data['rank'] = data[5:]
            await safe_edit(query, f"✅ البذلة: <b>{context.user_data.get('suit', '?')}</b>  |  الرتبة: <b>{context.user_data['rank']}</b>\n\n📩 أرسل رقم البونص", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 تغيير الرتبة", callback_data=f"suit_{context.user_data.get('suit_idx', 0)}")]]))
        elif data.startswith("save_"):
            parts = data.split("_", 2)
            winner, b_num = int(parts[1]), parts[2] if len(parts) > 2 else context.user_data.get('last_b_num', '')
            suit, rank, pred = context.user_data.get('suit', ''), context.user_data.get('rank', ''), context.user_data.get('last_pred', 2)
            if not (b_num and suit and rank): return await safe_edit(query, "❌ بيانات ناقصة — اضغط /start")
            
            last_digit, correct, saved_id, save_error = get_last_digit(b_num), winner == pred, None, None
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        winner_text = WINNER_NAMES.get(winner, "تعادل ⚪")
                        pred_int = pred if isinstance(pred, int) and pred in [0,1,2] else None
                        try:
                            cur.execute("INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, prediction, user_id, \"timestamp\", created_at) VALUES (%s, %s, %s, %s, %s, %s::integer, %s, NOW(), NOW()) RETURNING id", (b_num, suit, rank, last_digit, winner_text, pred_int, query.from_user.id))
                        except:
                            conn.rollback()
                            cur.execute("INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, prediction, user_id, created_at) VALUES (%s, %s, %s, %s, %s, %s::integer, %s, NOW()) RETURNING id", (b_num, suit, rank, last_digit, winner_text, pred_int, query.from_user.id))
                        saved_id = cur.fetchone()[0]
                        conn.commit()
            except Exception as e: save_error = str(e)

            update_pattern_db(suit, rank, last_digit, winner)

            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 20")
                        recent_hist = [WINNER_MAP.get(r[0], 2) for r in reversed(cur.fetchall())]
            except: recent_hist = []

            for law in load_laws():
                if match_law(law, suit, rank, last_digit, recent_hist) >= 0.5: update_law_accuracy(law["id"], law["prediction"] == winner)

            for sig_name, sig_pred in context.user_data.get('last_signals', {}).items():
                if sig_pred in [0, 1]: update_signal_perf(sig_name, sig_pred == winner)
            save_signal_perf_to_db()
            auto_manage_laws()

            if save_error: return await safe_edit(query, f"⚠️ <b>فشل حفظ الجولة!</b>\n<code>{save_error[:300]}</code>\n\nاضغط /start وأعد إدخال الجولة.")

            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT winner, prediction FROM history WHERE winner IS NOT NULL AND prediction IS NOT NULL ORDER BY id DESC LIMIT 20")
                        recent_results = cur.fetchall()
                recent_acc = sum(1 for r in recent_results if (WINNER_MAP.get(r[0],-1) == r[1])) / max(len(recent_results), 1)
                acc_txt = f"\n📈 دقة آخر 20: <b>{recent_acc:.0%}</b>  <code>{''.join('✅' if WINNER_MAP.get(r[0],-1)==r[1] else '❌' for r in recent_results[:10])}</code>"
            except: acc_txt = ""

            buttons = [[InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit"), InlineKeyboardButton("📊 إحصاءات", callback_data="stats")]]
            if saved_id: buttons.append([InlineKeyboardButton(f"🗑️ حذف هذه الجولة (#{saved_id})", callback_data=f"del_confirm_{saved_id}")])

            await safe_edit(query, f"{'✅' if correct else '❌'} <b>{WINNER_NAMES[winner]}</b>  ({'<b>صحيح! 🎯</b>' if correct else 'خاطئ ❌'})\nالتوقع: {WINNER_NAMES.get(pred, '?')}  |  {suit} {rank}  |  #{b_num}{acc_txt}{f'{chr(10)}💾 محفوظة ID: <code>{saved_id}</code>' if saved_id else ''}", reply_markup=InlineKeyboardMarkup(buttons))

        elif data == "stats":
            await safe_edit(query, "⏳ جارٍ تحميل الإحصاءات...")
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT COUNT(*) FROM history WHERE rank IS NOT NULL AND rank NOT IN ('NULL','')")
                        total = cur.fetchone()[0]
                        cur.execute("SELECT winner, COUNT(*) FROM history WHERE winner IS NOT NULL AND rank IS NOT NULL AND rank NOT IN ('NULL','') GROUP BY winner")
                        dist = {r[0]: r[1] for r in cur.fetchall()}
                        cur.execute("SELECT SUM(CASE WHEN winner = CASE prediction WHEN 0 THEN 'الراعي 🔴' WHEN 1 THEN 'الثور 🔵' END THEN 1 ELSE 0 END) AS correct, COUNT(*) AS total FROM history WHERE winner IS NOT NULL AND prediction IN (0, 1) AND winner IN ('الراعي 🔴', 'الثور 🔵') AND rank IS NOT NULL AND rank NOT IN ('NULL', '')")
                        acc_row = cur.fetchone()
                        correct_cnt, predicted_total = int(acc_row[0] or 0), int(acc_row[1] or 1)
                        cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                        laws_cnt = cur.fetchone()[0]
                        cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = FALSE")
                        inactive_cnt = cur.fetchone()[0]
                        cur.execute("SELECT COUNT(*), MAX(created_at) FROM learn_sessions")
                        sessions_cnt, last_learn_time = cur.fetchone()
                        cur.execute("SELECT winner, prediction FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 20")
                        last20 = cur.fetchall()
                        cur.execute("SELECT law_type, prediction, accuracy, times_used FROM ai_laws WHERE active = TRUE AND times_used > 2 ORDER BY accuracy DESC LIMIT 5")
                        top_laws = cur.fetchall()
                        cur.execute("SELECT signal_name, correct_count, total_count FROM signal_performance WHERE total_count >= 5 ORDER BY (correct_count::float / total_count) DESC LIMIT 8")
                        sig_rows = cur.fetchall()

                r_cnt, b_cnt, t_cnt = dist.get("الراعي 🔴", 0), dist.get("الثور 🔵", 0), dist.get("تعادل ⚪", 0)
                acc = round(correct_cnt / max(predicted_total, 1) * 100, 1)
                
                streak_str = "".join("✅" if WINNER_MAP.get(r[0], 2) == r[1] else ("⬜" if r[1] is None else "❌") for r in last20)
                sig_txt = "".join(f"  <code>{n:<12}</code> {round(c/max(t,1)*100,1):>5.1f}% {'█'*int(c/max(t,1)*10)+'░'*(10-int(c/max(t,1)*10))}\n" for n,c,t in sig_rows)
                laws_txt = "".join(f"  {'🔴' if l[1]==0 else '🔵'} [{l[0]}] acc={l[2]:.0f}% ×{l[3]}\n" for l in top_laws)
                
                text = f"<b>🧠 HADES — لوحة الإحصاءات الأسطورية</b>\n{'━'*24}\n🎮 الجولات: <b>{total}</b>  |  🎯 الدقة: <b>{acc}%</b> ({correct_cnt}/{predicted_total})  {'🏆 ممتاز' if acc>=65 else '✅ جيد' if acc>=58 else '📊 متوسط' if acc>=50 else '⚠️ ضعيف'}\n🔴 الراعي: {r_cnt} ({round(r_cnt/max(r_cnt+b_cnt,1)*100,1)}%)  🔵 الثور: {b_cnt} ({round(b_cnt/max(r_cnt+b_cnt,1)*100,1)}%)  ⚪ تعادل: {t_cnt}\n{'━'*24}\n📅 آخر 20 جولة:\n<code>{streak_str}</code>\n{'━'*24}\n⚖️ القوانين: <b>{laws_cnt}</b> نشط / {inactive_cnt} معطّل\n📚 جلسات تعلم: <b>{sessions_cnt}</b>  |  آخر: <b>{last_learn_time.strftime('%Y-%m-%d %H:%M') if last_learn_time else 'لم يُجرَ'}</b>\n" + (f"{'━'*24}\n🏅 أفضل القوانين:\n{laws_txt}" if laws_txt else "") + (f"{'━'*24}\n📡 أداء المحركات:\n{sig_txt}" if sig_txt else "") + f"{'━'*24}"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit"), InlineKeyboardButton("🔄 تحديث", callback_data="stats")]]))
            except Exception as e: await safe_edit(query, f"❌ خطأ: <code>{e}</code>")

        elif data.startswith("del_confirm_"):
            target_id = int(data.split("_")[2])
            await safe_edit(query, "⏳ جارٍ الحذف...")
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id FROM history WHERE id = %s", (target_id,))
                        r = cur.fetchone()
            except Exception as e: return await safe_edit(query, f"❌ خطأ: <code>{e}</code>")
            if not r: return await safe_edit(query, f"⚠️ لا توجد جولة بالـ ID {target_id}.")
            res = await _exec_delete(target_id, r[1], r[2], r[3], r[4], r[5], r[6], r[7])
            if res["error"]: await safe_edit(query, f"❌ خطأ: <code>{res['error']}</code>")
            else: await safe_edit(query, f"✅ <b>تم الحذف — كأن الجولة لم تحدث</b>{'━'*22}🔑 B_NUM: <code>{r[1]}</code>  |  🕐 {r[7].strftime('%Y-%m-%d %H:%M') if r[7] else '?'}🃏 {r[2] or '?'} {r[3] or '?'}  |  🏆 {r[5]}{'━'*22}♻️ rollback: <b>{res['rolled_back']}</b> نمط  |  ⚖️ <b>{res['laws_adjusted']}</b> قانون", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ حذف أخرى", callback_data="del_list"), InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit")]]))

        elif data == "del_list":
            rows = await _fetch_last_rounds(8)
            if not rows: return await safe_edit(query, "⚠️ لا توجد جولات.")
            await safe_edit(query, "🗑️ <b>اختر الجولة للحذف:</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(_delete_row_label(r), callback_data=f"del_confirm_{r[0]}")] for r in rows] + [[InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel")]]))

        elif data == "del_cancel": await safe_edit(query, "✅ تم الإلغاء.")
        
        elif data.startswith("deact_law_"):
            if query.from_user.id != ADMIN_ID: return await safe_edit(query, "⛔ للمشرف فقط.")
            try:
                law_id = int(data.split("_")[2])
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT law_type, prediction, accuracy FROM ai_laws WHERE id = %s", (law_id,))
                        row = cur.fetchone()
                        if not row: return await safe_edit(query, f"⚠️ لا يوجد قانون #{law_id}")
                        cur.execute("UPDATE ai_laws SET active = FALSE WHERE id = %s", (law_id,))
                        conn.commit()
                load_laws(force=True)
                await safe_edit(query, f"🗑️ <b>تم تعطيل القانون #{law_id}</b>\n[{row[0]}] → {'🔴' if row[1]==0 else '🔵'} {WINNER_NAMES.get(row[1], '?')}\nدقة: {row[2]:.0f}%\n\n✅ الذاكرة تم تحديثها.")
            except Exception as e: await safe_edit(query, f"❌ خطأ: <code>{e}</code>")
    except Exception as e: logger.error(f"callback_handler crash [{data}]: {e}", exc_info=True)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, suit, rank = update.message.text.strip(), context.user_data.get('suit'), context.user_data.get('rank')
    if not suit or not rank: return await update.message.reply_text("ابدأ بالضغط على /start واختيار البذلة والرتبة.")
    b_num = clean_digits(text)
    if not b_num: return await update.message.reply_text("❌ أرسل رقم البونص فقط.")
    context.user_data['last_b_num'] = b_num
    wait_msg = await update.message.reply_text("🔄 جارٍ التحليل...")
    try:
        pred, conf, reason = await predict(b_num, suit, rank)
        context.user_data['last_pred'] = pred
        signals_data = {}
        clean_reason_lines = []
        for line in reason.split("\n"):
            if line.startswith("__signals__"):
                try: signals_data = json.loads(line[11:])
                except: pass
            else: clean_reason_lines.append(line)
        context.user_data['last_signals'] = signals_data
        await wait_msg.delete()
        await update.message.reply_text(format_prediction(pred, conf, "\n".join(clean_reason_lines), suit, rank, b_num), parse_mode="HTML", reply_markup=result_keyboard(pred, b_num))
    except Exception as e:
        logger.error(f"predict error: {e}", exc_info=True)
        await wait_msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

async def cmd_prune(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
    msg = await update.message.reply_text("✂️ جارٍ تنظيف القوانين الميتة...")
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE times_used = 0 AND created_at < NOW() - INTERVAL '12 hours' AND active = TRUE")
                dead_by_usage = cur.rowcount
                cur.execute("UPDATE ai_laws SET active = FALSE WHERE accuracy < 40 AND times_used >= 50 AND active = TRUE")
                dead_by_acc = cur.rowcount
                cur.execute("WITH ranked AS (SELECT id, ROW_NUMBER() OVER (PARTITION BY conditions::text ORDER BY accuracy DESC, times_used DESC) as rn FROM ai_laws WHERE active = TRUE) UPDATE ai_laws SET active = FALSE WHERE id IN (SELECT id FROM ranked WHERE rn > 1)")
                dead_dupes = cur.rowcount
                conn.commit()
                cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                remaining = cur.fetchone()[0]
        load_laws(force=True)
        await msg.edit_text(f"✅ <b>تنظيف اكتمل</b>\n━━━━━━━━━━━━━━━━━━━━━━\n💤 لم تُستخدم قط:   <b>{dead_by_usage}</b>\n📉 دقة ضعيفة (&lt;40%): <b>{dead_by_acc}</b>\n♻️ مكررة:            <b>{dead_dupes}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n⚖️ القوانين الباقية: <b>{remaining}</b>", parse_mode="HTML")
    except Exception as e: await msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

async def cmd_reset_laws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
    if 'confirm' not in (context.args or []): return await update.message.reply_text("⚠️ للتأكيد اكتب: <code>/reset_laws confirm</code>", parse_mode="HTML")
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE ai_laws SET active = FALSE")
                n = cur.rowcount
                conn.commit()
        load_laws(force=True)
        await update.message.reply_text(f"✅ تم تعطيل <b>{n}</b> قانون.\nالآن شغّل /force_learn لبدء تعلم جديد.", parse_mode="HTML")
    except Exception as e: await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bnum_input = clean_digits(context.args[0]) if context.args else ""
    found_rows = []
    if bnum_input:
        try:
            with db_pool.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id FROM history WHERE TRIM(b_num::text) = %s ORDER BY id DESC LIMIT 3", (bnum_input,))
                    found_rows = cur.fetchall()
                    if not found_rows:
                        cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at, user_id FROM history WHERE b_num::text LIKE %s ORDER BY id DESC LIMIT 3", (f"%{bnum_input}%",))
                        found_rows = cur.fetchall()
        except Exception as e: return await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")

    if len(found_rows) == 1:
        r = found_rows[0]
        await update.message.reply_text(f"🗑️ <b>تأكيد الحذف</b>\n{'━'*22}\n🔑 B_NUM: <code>{r[1]}</code>\n🃏 {r[2] or '?'} {r[3] or '?'}  |  🔢 آخر رقم: <b>{r[4]}</b>\n🏆 {r[5]} {'🔴' if r[5]=='الراعي 🔴' else '🔵' if r[5]=='الثور 🔵' else '⚪'}  |  التوقع: {r[6] or 'NULL'}\n🕐 {r[7].strftime('%Y-%m-%d %H:%M') if r[7] else '?'}\n{'━'*22}\nهل تريد حذف هذه الجولة؟", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ نعم احذف", callback_data=f"del_confirm_{r[0]}"), InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel")]]))
        return

    display_rows = found_rows if len(found_rows) > 1 else await _fetch_last_rounds(8)
    if not display_rows: return await update.message.reply_text("⚠️ لا توجد جولات مسجّلة في قاعدة البيانات.")
    
    await update.message.reply_text(f"🔍 نتائج البحث عن <code>{bnum_input}</code> — اختر جولة:" if found_rows else "🗑️ <b>اختر الجولة التي تريد حذفها</b> — آخر 8 جولات مسجّلة", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(_row_btn_label(r), callback_data=f"del_confirm_{r[0]}")] for r in display_rows] + [[InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel")]]))

async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at FROM history WHERE rank IS NOT NULL AND rank NOT IN ('NULL','') AND suit IS NOT NULL ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                if not row:
                    cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at FROM history ORDER BY id DESC LIMIT 1")
                    row = cur.fetchone()
    except Exception as e: return await update.message.reply_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")
    if not row: return await update.message.reply_text("⚠️ لا توجد جولات مسجّلة.")
    
    pred_display = WINNER_NAMES.get(row[6], str(row[6])) if isinstance(row[6], int) else row[6] or "NULL"
    correct = " ✅" if row[6] is not None and row[5] and (WINNER_MAP.get(row[6], row[6]) if isinstance(row[6], str) else row[6]) == WINNER_MAP.get(row[5], -1) else (" ❌" if row[6] is not None else "")
    await update.message.reply_text(f"🕐 <b>آخر جولة مسجّلة</b>\n{'━'*22}\n🆔 ID: <code>{row[0]}</code>  |  🕐 {row[7].strftime('%Y-%m-%d %H:%M:%S') if row[7] else '?'}\n🔑 B_NUM: <code>{row[1]}</code>\n🃏 {row[2] or '?'} {row[3] or '?'}  |  🔢 آخر رقم: <b>{row[4]}</b>\n🏆 النتيجة: <b>{row[5]} {'🔴' if row[5]=='الراعي 🔴' else '🔵' if row[5]=='الثور 🔵' else '⚪'}</b>\n🎯 التوقع: {pred_display}{correct}\n{'━'*22}", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ حذف هذه الجولة", callback_data=f"del_confirm_{row[0]}"), InlineKeyboardButton("🎴 جولة جديدة", callback_data="choose_suit")]]))

async def cmd_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
    msg = await update.message.reply_text("⏳ جارٍ تجميع البيانات...")
    try:
        import io
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        filename = f"hades_db_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        lines = []
        def sec(t): lines.extend(["", "╔" + "═"*58 + "╗", f"║  {t:<56}║", "╚" + "═"*58 + "╝"])
        lines.extend(["╔" + "═"*58 + "╗", "║" + " "*15 + "HADES V21 — DB EXPORT" + " "*22 + "║", f"║  Generated : {now_str:<44}║", "╚" + "═"*58 + "╝"])
        
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                sec("SUMMARY")
                counts = {tbl: cur.execute(f"SELECT COUNT(*) FROM {tbl}") or cur.fetchone()[0] for tbl in ["history", "pattern_stats", "ai_laws", "learn_sessions"]}
                cur.execute("SELECT COUNT(*) FROM history WHERE rank IS NOT NULL AND rank NOT IN ('NULL','')")
                counts["history_real"] = cur.fetchone()[0]
                cur.execute("SELECT SUM(CASE WHEN winner = CASE prediction WHEN 0 THEN 'الراعي 🔴' WHEN 1 THEN 'الثور 🔵' END THEN 1 ELSE 0 END), COUNT(*) FROM history WHERE winner IS NOT NULL AND prediction IN (0, 1) AND winner IN ('الراعي 🔴', 'الثور 🔵') AND rank IS NOT NULL AND rank NOT IN ('NULL', '')")
                row2 = cur.fetchone()
                correct, played = int(row2[0] or 0), int(row2[1] or 1)
                cur.execute("SELECT COUNT(*) FROM ai_laws WHERE active = TRUE")
                active_laws = cur.fetchone()[0]
                lines.extend([f"  History rows   : {counts.get('history_real', counts['history'])} (حقيقية) / {counts['history']} (كلي)", f"  Pattern stats  : {counts['pattern_stats']}", f"  AI Laws total  : {counts['ai_laws']}  (active: {active_laws})", f"  Learn sessions : {counts['learn_sessions']}", f"  Prediction acc : {round(correct / played * 100, 1)}%  ({correct}/{played} non-tie predicted)"])
                
                sec("PATTERN_STATS")
                cur.execute("SELECT pattern_id, pattern_type, red_count, blue_count, tie_count FROM pattern_stats ORDER BY pattern_type, pattern_id")
                lines.extend([f"  {'PATTERN_ID':<25} {'TYPE':<8} {'RED':>6} {'BLUE':>6} {'TIE':>5}  BIAS%", "  " + "-" * 56])
                for r in cur.fetchall():
                    red, blue, tie = float(r[2] or 0), float(r[3] or 0), float(r[4] or 0)
                    bias = round((blue - red) / max(red + blue + tie, 1) * 100, 1)
                    lines.append(f"  {str(r[0] or 'NULL'):<25} {str(r[1] or 'NULL'):<8} {red:>6.0f} {blue:>6.0f} {tie:>5.0f}  {bias:+.1f}% {'→🔵' if bias>5 else '→🔴' if bias<-5 else '  ='}")
                
                sec("AI_LAWS  (sorted by accuracy DESC)")
                cur.execute("SELECT id, law_name, law_type, conditions, prediction, confidence, accuracy, times_used, description, active FROM ai_laws ORDER BY accuracy DESC, confidence DESC")
                lines.extend([f"  {'ID':>4}  {'TYPE':<28} {'PRED':<10} {'CONF':>5} {'ACC':>5} {'USED':>5}  ACT", "  " + "-" * 70])
                for r in cur.fetchall():
                    lines.append(f"  {str(r[0] or 'NULL'):>4}  {str(r[2] or 'NULL'):<28} {'🔴 Banker' if r[4]==0 else '🔵 Player' if r[4]==1 else '?':<10} {float(r[5] or 0):>4.0f}% {float(r[6] or 0):>4.0f}% {int(r[7] or 0):>5}  {'✅' if r[9] else '❌'}")
                    if r[3]: lines.append(f"       CONDITIONS: {(str(r[3]) if not isinstance(r[3], str) else r[3])[:90]}")
                    if r[8]: lines.append(f"       DESC      : {str(r[8])[:90]}")
                    lines.append("")
                
                sec("LEARN_SESSIONS")
                cur.execute("SELECT id, rounds_used, laws_created, laws_updated, summary, created_at FROM learn_sessions ORDER BY id DESC")
                for r in cur.fetchall():
                    lines.append(f"  #{str(r[0] or 'NULL')}  [{str(r[5] or 'NULL')}]  rounds={str(r[1] or 'NULL')}  laws_new={str(r[2] or 'NULL')}  laws_upd={str(r[3] or 'NULL')}")
                    if r[4]: lines.append(f"     {str(r[4])[:80]}")
                
                sec("HISTORY  (all rows, ASC)")
                cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, prediction, created_at FROM history ORDER BY id ASC")
                lines.extend([f"  {'ID':>6}  {'B_NUM':<12} {'SUIT':<5} {'RANK':<5} {'DIG':>3}  {'WINNER':<14} {'PRED':<14}  CREATED_AT", "  " + "-" * 85])
                for r in cur.fetchall(): lines.append(f"  {str(r[0] or 'NULL'):>6}  {str(r[1] or 'NULL'):<12} {str(r[2] or 'NULL'):<5} {str(r[3] or 'NULL'):<5} {str(r[4] or 'NULL'):>3}  {str(r[5] or 'NULL'):<14} {str(r[6] or 'NULL'):<14}  {str(r[7] or 'NULL')}")

        lines.extend(["", "╔" + "═"*58 + "╗", f"║  END OF EXPORT — {len(lines)} lines{' ' * (40 - len(str(len(lines))))}║", "╚" + "═"*58 + "╝"])
        file_bytes = io.BytesIO("\n".join(lines).encode("utf-8"))
        file_bytes.name = filename
        await msg.delete()
        await update.message.reply_document(document=file_bytes, filename=filename, caption=f"<b>HADES DB Export</b>\n<code>{now_str}</code>\nHistory: <b>{counts.get('history', 0)}</b> | Laws: <b>{counts.get('ai_laws', 0)}</b> | Acc: <b>{acc}%</b>\n<i>{len(lines)} lines</i>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        try: await msg.edit_text(f"❌ خطأ في التصدير:<code>{e}</code>", parse_mode="HTML")
        except: pass

async def auto_learn_job(context) -> None:
    global _last_auto_learn
    async with _auto_learn_lock:
        try:
            with db_pool.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM history WHERE winner IS NOT NULL AND rank IS NOT NULL AND rank NOT IN ('NULL','') AND created_at > (SELECT COALESCE(MAX(created_at), '2000-01-01') FROM learn_sessions)")
                    new_rounds = cur.fetchone()[0]
            if new_rounds < 30: return
            msgs = []
            async def status_cb(msg): msgs.append(msg)
            result = await force_learn_engine(status_cb)
            if "error" not in result:
                try: await context.bot.send_message(chat_id=ADMIN_ID, text=f"🤖 <b>تعلم تلقائي</b>\n📊 جولات جديدة: {new_rounds}\n⚖️ قوانين جديدة: {result.get('laws_saved', 0)}\n📈 جلسة #{result.get('session_id', '?')}", parse_mode="HTML")
                except: pass
                _last_auto_learn = time.time()
        except: pass

def _run_golden_miner_sync() -> str:
    MIN_OCCURRENCES = 12
    MIN_WIN_RATE    = 0.78
    MAX_LAWS_TO_ADD = 15
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT h.id, h.b_num, h.suit, h.rank, h.winner, ABS(h.b_num::bigint - LAG(h.b_num::bigint) OVER (ORDER BY h.id)) AS b_gap, EXTRACT(EPOCH FROM (h.created_at - LAG(h.created_at) OVER (ORDER BY h.id))) AS gap_sec FROM history h WHERE h.winner IS NOT NULL AND h.rank IS NOT NULL AND h.rank != 'NULL' AND h.b_num ~ '^[0-9]+$' ORDER BY h.id ASC")
                rows = cur.fetchall()
        if len(rows) < 100: return "بيانات غير كافية للتعدين."
        patterns = defaultdict(lambda: {0: 0, 1: 0})
        for r in rows:
            winner = 0 if 'الراعي' in str(r[4]) else (1 if 'الثور' in str(r[4]) else 2)
            if winner == 2: continue
            last_digit = int(clean_digits(r[1])[-1]) if clean_digits(r[1]) else 0
            conditions = []
            if r[2]: conditions.append(("suit", r[2]))
            if r[3]: conditions.append(("rank", r[3]))
            if r[3] in ['J', 'Q', 'K']: conditions.append(("rank_family", "face"))
            conditions.append(("digit_parity", "even" if last_digit % 2 == 0 else "odd"))
            if r[6] is not None:
                if r[6] < 15: conditions.append(("gap_sec_lt", 15))
                elif r[6] > 45: conditions.append(("gap_sec_gt", 45))
            if r[5] is not None:
                if r[5] < 500: conditions.append(("b_gap_lt", 500))
                elif r[5] > 3000: conditions.append(("b_gap_gt", 3000))
            for size in [2, 3]:
                for combo in itertools.combinations(conditions, size): patterns[tuple(sorted(combo))][winner] += 1
        golden_rules = []
        for combo_key, outcomes in patterns.items():
            total = outcomes[0] + outcomes[1]
            if total < MIN_OCCURRENCES: continue
            if outcomes[0] / total >= MIN_WIN_RATE: golden_rules.append((combo_key, 0, outcomes[0] / total, total))
            elif outcomes[1] / total >= MIN_WIN_RATE: golden_rules.append((combo_key, 1, outcomes[1] / total, total))
        golden_rules.sort(key=lambda x: (x[2], x[3]), reverse=True)
        injected = 0
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ai_laws WHERE source = 'GOLDEN_MINER'")
                for combo_key, prediction, win_rate, total_plays in golden_rules[:MAX_LAWS_TO_ADD]:
                    cur.execute("INSERT INTO ai_laws (law_name, law_type, conditions, prediction, confidence, accuracy, description, source, times_used) VALUES (%s, %s, %s, %s, %s, %s, %s, 'GOLDEN_MINER', %s)", (f"GOLDEN_{injected}_{int(time.time())}", "golden_intersection", json.dumps({k: v for k, v in combo_key}, ensure_ascii=False), prediction, int(win_rate * 100) - 5, float(int(win_rate * 100)), f"قاعدة ذهبية: {int(win_rate * 100)}% من {total_plays} جولة → {WINNER_NAMES.get(prediction, '?')}", total_plays))
                    injected += 1
                conn.commit()
        load_laws(force=True)
        return f"💎 تم! اكتشاف وحقن {injected} قاعدة ذهبية من أصل {len(golden_rules)} مكتشفة."
    except Exception as e: return f"❌ خطأ: {e}"

async def cmd_mine_gold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
    msg = await update.message.reply_text("⛏️ <b>جاري تعدين البيانات...</b>\nيبحث في التقاطعات المعقدة دون استخدام AI.", parse_mode="HTML")
    await msg.edit_text(f"<b>نتائج التعدين:</b>\n{await asyncio.get_event_loop().run_in_executor(None, _run_golden_miner_sync)}", parse_mode="HTML")

async def run_council_debate(status_callback) -> Dict:
    await status_callback("🏛️ <b>مجلس الآلهة يجتمع...</b>\n📥 جاري سحب وتجهيز البيانات...")
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, b_num, suit, rank, bonus_last_digit, winner, created_at FROM history WHERE winner IS NOT NULL AND suit IS NOT NULL ORDER BY id ASC")
                rows = cur.fetchall()
    except Exception as e: return {"error": str(e)}
    rounds = _filter_valid_rounds(rows)
    memory = _build_math_memory(rounds)
    data_context = f"بيانات تحليلية لـ {len(rounds)} جولة باكرات:\nأنماط مؤكدة: {json.dumps(memory['confirmed_patterns'][:30], ensure_ascii=False)}\nانتقالات: {json.dumps(memory['transition_stats'], ensure_ascii=False)}\nعينة آخر جولات: {json.dumps(memory['raw_sample_last40'][-50:], ensure_ascii=False)}\nتعريف: winner=0 الراعي/أحمر, winner=1 الثور/أزرق"
    await status_callback("🌑 <b>Kimi (إله الرؤية) يتحدث...</b>\nيقرأ البيانات ويبحث عن ارتباطات مخفية معقدة.")
    kimi_resp = await _kimi_analyze([{"role": "user", "content": f"أنت عالم بيانات عبقري. حلل بيانات الباكرات وابحث عن تقاطعات معقدة (فجوة + سلسلة + بذلة). اطرح 7 نظريات قوية مدعومة بالأرقام.\n{data_context}"}])
    if "فشل" in kimi_resp: return {"error": kimi_resp}
    await status_callback("🌊 <b>MiniMax (إله الشك) يتدخل...</b>\nيفحص نظريات Kimi ويمزق الضعيفة.")
    minimax_resp = await _minimax_critique([{"role": "user", "content": f"أنت مدقق إحصائي صارم. انتقد هذه النظريات ضد البيانات الحقيقية:\n--- نظريات Kimi ---\n{kimi_resp}\n--- البيانات ---\n{data_context}\nارفض النظريات الضعيفة، وصقّل القوية، واكتب تقرير القواعد الناجية."}])
    if "فشل" in minimax_resp: return {"error": minimax_resp}
    await status_callback("⚡ <b>DeepSeek (كبير الآلهة) يحكم...</b>\nيصيغ القواعد الذهبية النهائية في JSON.")
    deepseek_text = await _nvidia_chat([{"role": "user", "content": f"أنت القاضي النهائي. حوّل القواعد المتفق عليها إلى JSON:\n--- تحليل Kimi:\n{kimi_resp[:2000]}\n--- نقد MiniMax:\n{minimax_resp[:2000]}\nأنشئ مصفوفة JSON فقط مع شروط: streak, gap_sec_gt/lt, suit. prediction:0أو1, confidence:60-78. أعد JSON فقط بلا نص."}], max_tokens=4000, temperature=0.2)
    laws_data = extract_json_safe(deepseek_text)
    if not laws_data or not isinstance(laws_data, list): return {"error": "فشل DeepSeek في صياغة JSON النهائي."}
    backtest_rows = _fetch_backtest_rows()
    saved, rejected = 0, 0
    with db_pool.get_conn() as conn:
        with conn.cursor() as cur:
            for law in laws_data:
                if not isinstance(law, dict) or law.get("prediction") not in [0, 1]: continue
                bt_passes, bt_acc, bt_n = backtest_law(law, backtest_rows)
                if not bt_passes:
                    rejected += 1
                    continue
                cur.execute("INSERT INTO ai_laws (law_name, law_type, conditions, prediction, confidence, accuracy, description, source, times_used) VALUES (%s, %s, %s, %s, %s, %s, %s, 'COUNCIL_DEBATE', %s)", (f"COUNCIL_{saved}_{int(time.time())}", law.get("law_type", "COUNCIL_RULE"), json.dumps(law.get("conditions", {}), ensure_ascii=False), int(law["prediction"]), float(law.get("confidence", 75)), round(bt_acc * 100, 1), f"{law.get('description','')} [Council BT:{bt_acc:.0%}]", bt_n))
                saved += 1
        conn.commit()
    load_laws(force=True)
    return {"saved": saved, "rejected": rejected, "kimi_summary": kimi_resp[:300] + "...", "minimax_summary": minimax_resp[:300] + "..."}

async def cmd_council_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return await update.message.reply_text("⛔ هذا الأمر للمشرف فقط.")
    msg = await update.message.reply_text("🏛️ <b>تم استدعاء مجلس الآلهة...</b>\nالحوار قد يستغرق 5-15 دقيقة.", parse_mode="HTML")
    async def status_update(text: str):
        try: await msg.edit_text(text, parse_mode="HTML")
        except: pass
    result = await run_council_debate(status_update)
    if "error" in result: return await msg.edit_text(f"❌ <b>فشلت المحاكمة</b>\n\n<code>{result['error'][:300]}</code>", parse_mode="HTML")
    await msg.edit_text(f"✅ <b>انتهى اجتماع مجلس الآلهة!</b>\n\n━━━━━━━━━━━━━━━━━━━━━━\n⚖️ القوانين المعتمدة: <b>{result['saved']}</b>\n🗑️ المرفوضة: <b>{result['rejected']}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🧠 تم دمج حكمة 3 نماذج AI. البوت جاهز للعمل بالقوانين الجديدة.", parse_mode="HTML")

def main():
    ensure_tables()
    load_laws()               
    load_signal_perf_from_db()  
    app = ApplicationBuilder().token(TOKEN).build()
    app.job_queue.run_repeating(auto_learn_job, interval=3600, first=300)
    logger.info("⏰ Auto-learn job: every 60min, starts after 5min")
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("force_learn", cmd_force_learn))
    app.add_handler(CommandHandler("mine_gold",   cmd_mine_gold))
    app.add_handler(CommandHandler("council_learn", cmd_council_learn))
    app.add_handler(CommandHandler("laws",        cmd_laws))
    app.add_handler(CommandHandler("deactivate",  cmd_deactivate_law))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("prune",       cmd_prune))
    app.add_handler(CommandHandler("reset_laws",  cmd_reset_laws))
    app.add_handler(CommandHandler("last",        cmd_last))
    app.add_handler(CommandHandler("delete",      cmd_delete))
    app.add_handler(CommandHandler("download",    cmd_download))
    app.add_handler(CommandHandler("engine",      cmd_engine_status))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("🚀 HADES V21.0 is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
