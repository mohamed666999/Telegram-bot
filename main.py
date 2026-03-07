"""
HADES V16.7 - Fast Neural Hybrid (Mistral Devstral via NVIDIA)
تم تحديث الموديل إلى mistralai/devstral-2-123b-instruct-2512 مع إعدادات دقيقة.
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
    MessageHandler,
    filters,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from openai import AsyncOpenAI

# ==================== 🛡️ الإعدادات ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

# إعدادات NVIDIA API (موديل Mistral Devstral)
AI_BASE_URL = "https://integrate.api.nvidia.com/v1"
AI_API_KEY = "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"
AI_MODEL = "mistralai/devstral-2-123b-instruct-2512"
AI_TIMEOUT = 3.0  # مهلة قصيرة: 3 ثوان فقط (يمكن زيادتها إلى 5 إن لزم)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== تجمع اتصالات قاعدة البيانات ====================
class DatabasePool:
    _instance = None
    _pool = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_pool()
        return cls._instance

    def _init_pool(self):
        try:
            self._pool = psycopg2.pool.SimpleConnectionPool(
                1, 10,
                dsn=DATABASE_URL,
                sslmode='require',
                connect_timeout=3
            )
            logger.info("✅ Database connection pool created")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise

    @contextmanager
    def get_conn(self):
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

db_pool = DatabasePool()

# ==================== تخزين مؤقت للأنماط (TTL cache) ====================
class TTLCache:
    def __init__(self, ttl_seconds=60):
        self.cache = OrderedDict()
        self.ttl = ttl_seconds

    def get(self, key):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None

    def set(self, key, value):
        self.cache[key] = (value, time.time())
        if len(self.cache) > 100:
            self.cache.popitem(last=False)

pattern_cache = TTLCache(ttl_seconds=30)

# ==================== خرائط ثابتة ====================
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2,
    '🔴': 0, '🔵': 1, '⚪': 2, 0: 0, 1: 1, 2: 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]
RANK_VALUE = {k: v for k, v in zip(
    ["A", "K", "Q", "J", "10", "9", "8", "7", "6", "5", "4", "3", "2"],
    [14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2]
)}

WEIGHTS = {'GPT': 2.5, 'SD': 2.8, 'SUIT': 1.8, 'DIGIT': 1.2, 'MOMENTUM': 1.5}

# ==================== دوال مساعدة ====================
def clean_digits(text: str) -> str:
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

def ensure_columns():
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS history(
                        id SERIAL PRIMARY KEY,
                        b_num TEXT,
                        suit TEXT,
                        rank TEXT,
                        bonus_last_digit INT,
                        winner TEXT,
                        user_id BIGINT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pattern_stats (
                        pattern_id VARCHAR(50) PRIMARY KEY,
                        red_count FLOAT DEFAULT 0,
                        blue_count FLOAT DEFAULT 0,
                        tie_count FLOAT DEFAULT 0
                    )
                """)
                conn.commit()
    except Exception as e:
        logger.error(f"DB Init Error: {e}")

# ==================== 🤖 محرك Mistral Devstral مع مهلة صارمة ====================
def extract_json_from_text(text: str) -> Optional[dict]:
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    cleaned = re.sub(r'^```json\n|```$', '', text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None

class CustomAIEngine:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=AI_API_KEY,
            base_url=AI_BASE_URL,
            timeout=AI_TIMEOUT + 1
        )

    async def get_prediction_with_timeout(self, recent_history: list) -> Tuple[Optional[int], float, str]:
        try:
            task = asyncio.create_task(self._fetch_prediction(recent_history))
            result = await asyncio.wait_for(task, timeout=AI_TIMEOUT)
            return result
        except asyncio.TimeoutError:
            logger.warning("⚠️ AI request timed out")
            return None, 0.0, "المهلة الزمنية تجاوزت 3 ثوان"
        except Exception as e:
            logger.error(f"AI error: {e}")
            return None, 0.0, f"خطأ: {str(e)[:30]}"

    async def _fetch_prediction(self, recent_history: list) -> Tuple[Optional[int], float, str]:
        if len(recent_history) < 3:
            return None, 0.0, "بيانات غير كافية"

        prompt = f"""
        أنت محلل متخصص في لعبة الكازينو هذه. النتائج: 0 = أحمر (الراعي)، 1 = أزرق (الثور).
        التسلسل الأخير: {recent_history}
        هل سيستمر الاتجاه أم سينعكس؟ أعد فقط JSON بالصيغة التالية:
        {{"winner": 0 أو 1, "confidence": 50-95, "reason": "سبب مختصر بالعربية"}}
        """
        # استخدام stream=True لجمع الرد بسرعة
        stream = await self.client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.15,          # كما في الكود المقدم
            top_p=0.95,
            max_tokens=8192,            # الحد الأقصى
            seed=42,                    # لإعادة الإنتاجية
            stream=True
        )

        full_content = ""
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                full_content += delta.content
            # إذا وجدنا JSON كامل يمكننا التوقف مبكراً
            if "}" in full_content and full_content.strip().startswith("{"):
                try:
                    json.loads(extract_json_from_text(full_content) or "{}")
                    break
                except:
                    pass

        data = extract_json_from_text(full_content)
        if data:
            winner = int(data.get("winner", 2))
            conf = float(data.get("confidence", 50))
            reason = data.get("reason", "تحليل السلسلة")
            return winner, conf, reason
        else:
            logger.warning(f"لم نتمكن من استخراج JSON من الرد: {full_content[:100]}")
            return None, 0.0, "خطأ في قراءة الرد"

gpt_engine = CustomAIEngine()

# ==================== 📊 محرك الإحصائيات مع التخزين المؤقت ====================
def fetch_patterns_bulk(pattern_ids: List[str]) -> Dict[str, dict]:
    if not pattern_ids:
        return {}
    results = {}
    ids_to_fetch = []
    for pid in pattern_ids:
        cached = pattern_cache.get(pid)
        if cached:
            results[pid] = cached
        else:
            ids_to_fetch.append(pid)
    if not ids_to_fetch:
        return results

    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pattern_id, red_count, blue_count, tie_count
                    FROM pattern_stats
                    WHERE pattern_id = ANY(%s)
                """, (ids_to_fetch,))
                rows = cur.fetchall()
                for pid, red, blue, tie in rows:
                    total = red + blue + tie
                    if total == 0:
                        res = {'w': 2, 'c': 0.0, 'log': '[No Data]', 'tie_ratio': 0.0}
                    else:
                        smoothed_red = red + 2
                        smoothed_blue = blue + 2
                        smoothed_tie = tie + 1
                        smoothed_total = smoothed_red + smoothed_blue + smoothed_tie

                        p_red = smoothed_red / smoothed_total
                        p_blue = smoothed_blue / smoothed_total
                        p_tie = smoothed_tie / smoothed_total

                        winner = 0 if p_red > p_blue else 1

                        confidence_raw = max(p_red, p_blue)
                        conf_penalty = min(1.0, total / 10.0)
                        confidence = confidence_raw * conf_penalty

                        tie_ratio = tie / total if total > 0 else 0
                        confidence *= (1 - tie_ratio * 0.5)

                        res = {
                            'w': winner,
                            'c': confidence,
                            'log': f"[{int(red)}🔴:{int(blue)}🔵:{int(tie)}⚪]",
                            'tie_ratio': tie_ratio
                        }
                    results[pid] = res
                    pattern_cache.set(pid, res)
                for pid in ids_to_fetch:
                    if pid not in results:
                        default_res = {'w': 2, 'c': 0.0, 'log': '[No Data]', 'tie_ratio': 0.0}
                        results[pid] = default_res
                        pattern_cache.set(pid, default_res)
    except Exception as e:
        logger.error(f"Error fetching patterns: {e}")
        for pid in ids_to_fetch:
            results[pid] = {'w': 2, 'c': 0.0, 'log': '[Error]', 'tie_ratio': 0.0}
    return results

def detect_streak_breaker() -> Tuple[Optional[int], float, str]:
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT winner, timestamp
                    FROM history
                    WHERE winner IS NOT NULL
                    ORDER BY id DESC LIMIT 4
                """)
                rows = cur.fetchall()
                if len(rows) < 3:
                    return None, 0.0, ""
                time_diff = (datetime.now() - rows[0][1]).total_seconds()
                if time_diff > 300:
                    return None, 0.0, ""
                recent = [WINNER_MAP.get(r[0], 2) for r in rows[:3]]
                if recent == [0, 0, 0]:
                    return 1, 0.85, "⚠️ كسر سلسلة الراعي (توقع الثور)"
                elif recent == [1, 1, 1]:
                    return 0, 0.85, "⚠️ كسر سلسلة الثور (توقع الراعي)"
    except Exception as e:
        logger.error(f"Streak breaker error: {e}")
    return None, 0.0, ""

# ==================== 🧠 دمج العقول مع أولوية السرعة ====================
async def predict_hybrid_fast(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b:
        return 2, 0, "❌ رقم غير صالح"
    last_digit = int(clean_b[-1])

    logs = []
    scores = {0: 0.0, 1: 0.0}

    # 1. جلب التاريخ الحديث
    recent_history = []
    try:
        with db_pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 15")
                recent_history = [WINNER_MAP.get(r[0], 2) for r in cur.fetchall()]
                recent_history.reverse()
    except Exception as e:
        logger.error(f"History fetch error: {e}")

    # 2. بدء مهمة AI
    ai_task = asyncio.create_task(gpt_engine.get_prediction_with_timeout(recent_history))

    # 3. الزخم
    streak_pred, streak_conf, streak_log = detect_streak_breaker()
    if streak_pred is not None:
        scores[streak_pred] += streak_conf * WEIGHTS['MOMENTUM']
        logs.append(f"⏱️ **الزخم:** {WINNER_NAMES[streak_pred]} ({streak_log})")

    # 4. الأنماط الإحصائية
    p_sd = f"SD_{suit}_{last_digit}"
    p_suit = f"SUIT_{suit}"
    p_digit = f"DIGIT_{last_digit}"
    patterns = fetch_patterns_bulk([p_sd, p_suit, p_digit])

    logic_map = [
        ('SD', p_sd, '✨ نمط (بذلة+رقم)'),
        ('SUIT', p_suit, '🎴 نمط البذلة'),
        ('DIGIT', p_digit, '🔢 نمط الرقم')
    ]

    for weight_key, pid, desc in logic_map:
        res = patterns.get(pid, {'w': 2, 'c': 0.0, 'log': '[No Data]'})
        if res['w'] != 2 and res['c'] > 0.0:
            scores[res['w']] += res['c'] * WEIGHTS[weight_key]
            logs.append(f"{desc}: {WINNER_NAMES[res['w']]} {res['log']}")

    # 5. انتظار نتيجة AI (مع مهلة قصيرة جداً)
    try:
        ai_pred, ai_conf, ai_log = await asyncio.wait_for(ai_task, timeout=0.5)
        if ai_pred in [0, 1]:
            scores[ai_pred] += (ai_conf / 100) * WEIGHTS['GPT']
            logs.append(f"🤖 **{AI_MODEL}:** {WINNER_NAMES[ai_pred]} ({ai_log})")
        else:
            logs.append(f"⚠️ **حالة {AI_MODEL}:** {ai_log}")
    except asyncio.TimeoutError:
        logs.append(f"⚠️ **{AI_MODEL}:** لم يكتمل في الوقت المحدد (تم التجاهل)")
    except Exception:
        logs.append(f"⚠️ **{AI_MODEL}:** خطأ غير متوقع")

    # =============== الحساب النهائي ===============
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]

    if total_score == 0:
        padded_b = clean_b.zfill(3)
        math_res = ((sum(int(d) for d in padded_b[-3:]) * RANK_VALUE.get(rank.upper(), 0)) + last_digit) % 2
        return math_res, 60, "🧮 **تحليل رياضي احتياطي**\n" + "\n".join(logs)

    p0 = scores[0] / total_score
    p1 = scores[1] / total_score
    entropy = - (p0 * math.log2(p0 + 1e-9) + p1 * math.log2(p1 + 1e-9))
    normalized_entropy = 1 - entropy
    raw_conf = 50 + 45 * normalized_entropy
    confidence = int(min(99, max(50, raw_conf)))

    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

# ==================== 🎮 معالجات التيليجرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text(
        "<b>🏛️ HADES V16.7 (Mistral Devstral)</b>\n"
        "تحليل فائق السرعة مع مهلة 3 ثوان.\n"
        "اضغط للبدء:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='HTML'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    try:
        if data == "choose_suit":
            context.user_data.pop('suit', None); context.user_data.pop('rank', None)
            kb = [[InlineKeyboardButton(s, callback_data=f"suit_{s}") for s in SUITS]]
            await query.edit_message_text("🎴 <b>اختر البذلة:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

        elif data.startswith("suit_"):
            suit = data.split("_")[1]
            context.user_data['suit'] = suit
            kb = [[InlineKeyboardButton(r, callback_data=f"rank_{r}") for r in row] for row in RANKS_LAYOUT]
            kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="choose_suit")])
            await query.edit_message_text(f"✅ البذلة: <b>{suit}</b>\n🃏 <b>اختر الورقة:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

        elif data.startswith("rank_"):
            rank = data.split("_")[1]
            context.user_data['rank'] = rank
            suit = context.user_data.get('suit', '')
            kb = [[InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ جاهز: <b>{suit} {rank}</b>\n\n📥 <b>أرسل رقم البونص الآن:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

        elif data == "delete_last":
            try:
                with db_pool.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM history WHERE id = (SELECT max(id) FROM history WHERE user_id = %s)", (update.effective_user.id,))
                        conn.commit()
            except Exception as e:
                logger.error(f"Delete error: {e}")
            kb = [[InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text("🗑️ تم حذف الجولة الخاطئة.\n📥 أرسل الرقم الصحيح:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

        elif data.startswith("save_"):
            w_code = int(data.split("_")[1])
            b_num = context.user_data.get('last_b_num', '00000')
            suit = context.user_data.get('last_suit', '♦️')
            rank = context.user_data.get('last_rank', 'A')
            if b_num and suit and rank:
                last_digit = int(clean_digits(b_num)[-1])
                try:
                    with db_pool.get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("INSERT INTO history (b_num, suit, rank, bonus_last_digit, winner, user_id) VALUES (%s,%s,%s,%s,%s,%s)",
                                        (b_num, suit, rank, last_digit, WINNER_NAMES[w_code], update.effective_user.id))
                            col = "red_count" if w_code == 0 else "blue_count" if w_code == 1 else "tie_count"
                            for pid in [f"SD_{suit}_{last_digit}", f"SUIT_{suit}", f"DIGIT_{last_digit}"]:
                                cur.execute(f"INSERT INTO pattern_stats (pattern_id, {col}) VALUES (%s, 1) ON CONFLICT (pattern_id) DO UPDATE SET {col} = pattern_stats.{col} + 1", (pid,))
                            conn.commit()
                except Exception as e:
                    logger.error(f"Save error: {e}")
            pattern_cache.cache.clear()
            kb = [[InlineKeyboardButton("🗑️ تصحيح", callback_data="delete_last")], [InlineKeyboardButton("🔄 تغيير", callback_data="choose_suit")]]
            await query.edit_message_text(f"✅ تم التسجيل: <b>{WINNER_NAMES[w_code]}</b>\n\n📥 <b>أرسل الرقم التالي لـ ({suit} {rank}):</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

    except Exception as e:
        logger.error(f"Callback Error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        clean_text = clean_digits(text)
        if not clean_text:
            return
        suit = context.user_data.get('suit')
        rank = context.user_data.get('rank')
        if not suit or not rank:
            kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
            await update.message.reply_text("⚠️ <b>يجب اختيار البذلة والورقة أولاً!</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            return
        processing_msg = await update.message.reply_text("⏳ <b>جاري التحليل السريع...</b>", parse_mode='HTML')

        start_time = time.time()
        pred_code, confidence, reason = await predict_hybrid_fast(clean_text, suit, rank)
        elapsed = time.time() - start_time

        context.user_data['last_b_num'] = clean_text
        context.user_data['last_suit'] = suit
        context.user_data['last_rank'] = rank

        kb = [
            [InlineKeyboardButton("راعي 🔴", callback_data="save_0"), InlineKeyboardButton("ثور 🔵", callback_data="save_1")],
            [InlineKeyboardButton("تعادل ⚪", callback_data="save_2")]
        ]

        bar = generate_progress_bar(confidence)
        report = f"""🎯 <b>تقرير V16.7 (سريع)</b> ⏱️ {elapsed:.1f} ثانية
━━━━━━━━━━━━━━━
🃏 الورقة: {suit} {rank} | 📥 البونص: <code>{clean_text}</code>

🏆 <b>التوقع: {WINNER_NAMES[pred_code]}</b>
📊 الثقة: [{bar}] {confidence}%

<b>🔍 محركات التحليل:</b>
{reason}
━━━━━━━━━━━━━━━
اختر الفائز الفعلي لتسجيل النتيجة:"""

        await processing_msg.edit_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        logger.error(f"Handle Msg Error: {e}")

# ==================== التشغيل الرئيسي ====================
if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 HADES V16.7 (Mistral Devstral) is running...")
    app.run_polling(drop_pending_updates=True)
