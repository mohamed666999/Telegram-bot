"""
HADES V103 - Autonomous Self-Evolving AI Prediction System
نظام تنبؤ هجين: معادلة رياضية + تحليل بايزي + NVIDIA AI + قوانين ذكية
يعمل على Railway مع PostgreSQL - واجهة أزرار تفاعلية كاملة
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

# ثوابت النظام
WARMUP_ROUNDS = 700  # تجاهل أول 700 جولة
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

# الإعدادات الديناميكية الافتراضية
DYNAMIC_CONFIG = {
    'CONFIDENCE_THRESHOLD': 0.65, 'MATH_WEIGHT': 0.55, 'BAYES_WEIGHT': 0.45,
    'MATH_CONFIDENCE': 0.7, 'S_RED': 1.0, 'S_BLACK': 1.0,
    'RANDOM_NOISE': 0.02, 'VOTE_THRESHOLD': 2,
}

# ==================== 🗄️ إدارة قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def load_filtered_history(min_id: int = WARMUP_ROUNDS + 1) -> pd.DataFrame:
    """تحميل التاريخ مع تجاهل أول 700 جولة"""
    try:
        conn = get_db_connection()
        query = f"""
            SELECT id, b_num, suit, winner, timestamp, prediction, user_id,
                   final_prediction, gap_pred, math_pred, file_pred, created_at
            FROM history 
            WHERE winner IS NOT NULL AND id >= {min_id}
            ORDER BY id ASC
        """
        df = pd.read_sql(query, conn)
        conn.close()
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code'])
        
        logger.info(f"✅ تم تحميل {len(df)} جولة (بعد تجاهل أول {WARMUP_ROUNDS})")
        return df
    except Exception as e:
        logger.error(f"❌ خطأ في تحميل البيانات: {e}")
        return pd.DataFrame()

def get_latest_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """تحليل إحصائي دقيق للبيانات المفلترة"""
    if df.empty:
        return {}
    
    stats = {
        'total_rounds': len(df),
        'winner_dist': df['winner'].value_counts().to_dict(),
        'suit_dist': df['suit'].value_counts().to_dict() if 'suit' in df.columns else {},
        'accuracy': None, 'bias': {}, 'patterns': {}, 'time_analysis': {}
    }
    
    if 'prediction' in df.columns and df['prediction'].notna().any():
        valid = df[df['prediction'].notna()]
        if len(valid) > 0:
            stats['accuracy'] = float((valid['winner_code'] == valid['prediction']).mean())
    
    total = len(df)
    stats['bias'] = {
        'red': float((df['winner'] == 'الراعي 🔴').sum() / total) if total > 0 else 0,        
        'blue': float((df['winner'] == 'الثور 🔵').sum() / total) if total > 0 else 0,
        'tie': float((df['winner'] == 'تعادل ⚪').sum() / total) if total > 0 else 0
    }
    
    if 'suit' in df.columns:
        suit_winner = {}
        for suit in SUITS:
            subset = df[df['suit'] == suit]
            if len(subset) >= 10:
                top = subset['winner'].value_counts().idxmax() if not subset['winner'].empty else None
                if top:
                    freq = subset['winner'].value_counts().max() / len(subset)
                    suit_winner[suit] = {'top_winner': top, 'frequency': round(freq, 3)}
        stats['patterns']['suit_winner'] = suit_winner
    
    if 'b_num' in df.columns:
        df_copy = df.copy()
        df_copy['last_digit'] = df_copy['b_num'].astype(str).str[-1].str.extract(r'(\d)')
        digit_winner = {}
        for digit in range(10):
            subset = df_copy[df_copy['last_digit'] == str(digit)]
            if len(subset) >= 5 and 'winner' in subset.columns:
                top = subset['winner'].value_counts().idxmax() if not subset['winner'].empty else None
                if top:
                    digit_winner[str(digit)] = {'top_winner': top, 'count': len(subset)}
        stats['patterns']['last_digit'] = digit_winner
    
    if 'timestamp' in df.columns and df['timestamp'].notna().any():
        df_copy = df.copy()
        df_copy['hour'] = df_copy['timestamp'].dt.hour
        if 'winner' in df_copy.columns:
            hourly = df_copy.groupby('hour')['winner'].value_counts().unstack(fill_value=0)
            stats['time_analysis']['hourly'] = hourly.to_dict() if not hourly.empty else {}
    
    return stats

def load_dynamic_config():
    """تحميل الإعدادات من قاعدة البيانات"""
    global DYNAMIC_CONFIG
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT config_name, config_value FROM ai_settings")
        for name, value in cur.fetchall():
            if name in DYNAMIC_CONFIG:
                try:
                    DYNAMIC_CONFIG[name] = json.loads(value)
                except:
                    DYNAMIC_CONFIG[name] = value
        conn.close()    
    except Exception as e:
        logger.warning(f"⚠️ فشل تحميل الإعدادات: {e}")

def save_dynamic_config(updates: Dict[str, Any]):
    """حفظ تحديثات الإعدادات"""
    global DYNAMIC_CONFIG
    conn = get_db_connection()
    cur = conn.cursor()
    for name, value in updates.items():
        cur.execute("""INSERT INTO ai_settings (config_name, config_value)
            VALUES (%s, %s) ON CONFLICT (config_name) DO UPDATE
            SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP""",
            (name, json.dumps(value)))
        DYNAMIC_CONFIG[name] = value
    conn.commit()
    conn.close()
    logger.info(f"🔄 تحديث الإعدادات: {list(updates.keys())}")

# ==================== 🤖 محرك الذكاء الاصطناعي ====================
class AdvancedAIEngine:
    def __init__(self):
        self.client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
        self.model = NVIDIA_MODEL
    
    def generate_analysis_prompt(self, stats: Dict, df: pd.DataFrame) -> str:
        prompt = f"""أنت خبير تحليل بيانات ألعاب تنبؤية.

📊 إحصائيات البيانات (بعد تجاهل أول {WARMUP_ROUNDS} جولة):
- إجمالي الجولات المحللة: {stats.get('total_rounds', 0)}
- توزيع النتائج: {stats.get('winner_dist', {})}
- دقة التنبؤ السابقة: {stats.get('accuracy', 'N/A')}
- الانحياز: أحمر={stats.get('bias', {}).get('red', 0):.1%}، أزرق={stats.get('bias', {}).get('blue', 0):.1%}، تعادل={stats.get('bias', {}).get('tie', 0):.1%}

🔍 أنماط البذلات:
{json.dumps(stats.get('patterns', {}).get('suit_winner', {}), ensure_ascii=False, indent=2)}

المطلوب:
1️⃣ استخرج 1-3 قوانين تنبؤية جديدة بناءً على هذه البيانات
2️⃣ لكل قانون: اسم، شرط التطبيق، الإجراء المتوقع، مستوى الثقة (0.0-1.0)
3️⃣ اقترح تعديلات على أوزان المعادلة الحالية إذا لزم الأمر

أجب بصيغة JSON فقط بهذا الهيكل:
{{
    "new_laws": [
        {{"name": "اسم_القانون", "condition": "شرط_التطبيق", "action": "الإجراء", "confidence": 0.XX}}
    ],
    "config_suggestions": {{"SETTING_NAME": new_value}},
    "next_round_strategy": "استراتيجية مختصرة"
}}"""
        return prompt    

    def ask_json(self, prompt: str, temperature: float = 0.2) -> Optional[Dict]:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "أجب بصيغة JSON صالحة فقط. لا تضيف أي نص إضافي."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=2000
            )
            content = response.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            logger.error(f"❌ خطأ AI JSON: {e}")
        return None
    
    def generate_prediction_command(self, df: pd.DataFrame, current_b_num: str, current_suit: str) -> Dict:
        last_20 = df.tail(20) if len(df) >= 20 else df
        recent_winners = last_20['winner'].tolist() if 'winner' in last_20.columns else []
        winner_counts = Counter(recent_winners)
        last_digit = current_b_num[-1] if current_b_num and current_b_num[-1].isdigit() else '0'
        
        prompt = f"""أنت نظام تنبؤ ذكي. البيانات المتاحة:

📈 آخر 20 نتيجة: {recent_winners[-10:] if recent_winners else []}
📊 التكرار الأخير: {dict(winner_counts)}
🎯 الجولة الحالية: رقم={current_b_num}, بذلة={current_suit}, آخر_رقم={last_digit}

المطلوب: أعطِ تنبؤاً واحداً للجولة الحالية مع سبب منطقي مختصر.
أجب بصيغة JSON:
{{"prediction": "الراعي 🔴" أو "الثور 🔵" أو "تعادل ⚪", "reason": "سبب مختصر", "confidence": 0.XX}}"""
        
        result = self.ask_json(prompt)
        if result and 'prediction' in result:
            return {
                'prediction': result['prediction'],
                'reason': result.get('reason', ''),
                'confidence': result.get('confidence', 0)
            }
        return {'prediction': '⚠️ تعذر', 'reason': 'خطأ في التحليل', 'confidence': 0}

# ==================== ⚙️ المحرك الرياضي الديناميكي ====================
def load_active_equation() -> str:
    try:
        conn = get_db_connection()
        cur = conn.cursor()        
        cur.execute("""SELECT equation_code FROM ai_equations
            WHERE is_active=TRUE ORDER BY success_rate DESC, activation_count DESC LIMIT 1""")
        row = cur.fetchone()
        conn.close()
        return row[0] if row else "(B * S) + (delta_t % 7) + (last_digit * 3)"
    except:
        return "(B * S) + (delta_t % 7) + (last_digit * 3)"

def safe_eval_equation(equation: str, B: int, S: float, delta_t: int, last_digit: int) -> int:
    safe_globals = {"__builtins__": {}}
    safe_locals = {"B": B, "S": S, "delta_t": delta_t, "last_digit": last_digit, "int": int, "float": float}
    try:
        result = eval(equation, safe_globals, safe_locals)
        return int(result) % 2
    except:
        R = (B * S) + (delta_t % 7) + (last_digit * 3)
        return int(R) % 2

def sovereign_math_engine(b_num: str, suit: str, last_ts, current_ts) -> Tuple[str, int, int, int, int, float]:
    last3 = b_num[-3:]
    B = sum(int(d) for d in last3 if d.isdigit())
    last_digit = int(b_num[-1])
    S = DYNAMIC_CONFIG['S_RED'] if suit in ['♦️', '♥️'] else DYNAMIC_CONFIG['S_BLACK']
    delta_t = int((current_ts - last_ts).total_seconds()) if last_ts else 0
    
    equation = load_active_equation()
    pred_code = safe_eval_equation(equation, B, S, delta_t, last_digit)
    R = (B * S) + (delta_t % 7) + (last_digit * 3)
    return WINNER_NAMES[pred_code], pred_code, R, delta_t, B, S

# ==================== 📊 التحليل البايزي ====================
def bayesian_analysis(conn, current_hour: int, min_samples: int = 20) -> Optional[Dict]:
    try:
        df = pd.read_sql("SELECT winner, timestamp FROM history WHERE winner IS NOT NULL", conn)
        if len(df) < min_samples:
            return None
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(lambda h: "morning" if 6<=h<12 else "afternoon" if 12<=h<18 else "evening" if 18<=h<24 else "night")
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code'])
        
        probs = {}
        for p in ['morning', 'afternoon', 'evening', 'night']:
            pd_data = df[df['period'] == p]
            if len(pd_data) >= min_samples:
                t = len(pd_data)
                probs[p] = (
                    (pd_data['winner_code'] == 0).sum() / t,
                    (pd_data['winner_code'] == 1).sum() / t,                    
                    (pd_data['winner_code'] == 2).sum() / t,
                )
            else:
                probs[p] = None
        return probs
    except Exception as e:
        logger.error(f"❌ Bayesian error: {e}")
        return None

# ==================== ⚖️ نظام القوانين الذكي ====================
def get_active_laws() -> List[Dict]:
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""SELECT law_name, law_pattern, confidence_score, success_rate
            FROM ai_laws WHERE is_active=TRUE AND confidence_score>=0.6 ORDER BY confidence_score DESC""")
        laws = []
        for row in cur.fetchall():
            laws.append({'name': row[0], 'pattern': row[1], 'confidence': row[2], 'success_rate': row[3]})
        conn.close()
        return laws
    except:
        return []

def apply_ai_laws(b_num: str, suit: str, gap: int, bayes_probs: Optional[Dict]) -> Optional[Tuple[str, int]]:
    laws = get_active_laws()
    if not laws:
        return None
    last_digit = int(b_num[-1]) if b_num[-1].isdigit() else 0
    current_period = "morning" if 6<=datetime.datetime.now().hour<12 else "afternoon" if 12<=datetime.datetime.now().hour<18 else "evening" if 18<=datetime.datetime.now().hour<24 else "night"
    
    for law in laws:
        pat = law['pattern']
        score = 0
        if isinstance(pat, dict):
            if 'last_digit' in pat and pat['last_digit'] == last_digit:
                score += 0.4
            if 'suit' in pat and pat['suit'] == suit:
                score += 0.3
            if 'max_gap' in pat and gap <= pat['max_gap']:
                score += 0.2
            if 'period' in pat and pat['period'] == current_period:
                score += 0.1
            if 'condition' in pat and isinstance(pat['condition'], str):
                if 'تعادل' in pat['condition'] and 'الراعي' in pat.get('action', ''):
                    score += 0.3
        
        if score >= 0.5:
            winner = pat.get('predicted_winner') or pat.get('action', '').split()[-1] if isinstance(pat.get('action'), str) else None
            if winner in WINNER_MAP:                
                logger.info(f"🎯 قانون مطبق: {law['name']}")
                return WINNER_NAMES[WINNER_MAP[winner]], WINNER_MAP[winner]
    return None

# ==================== 🗳️ نظام التصويت الهجين ====================
def hybrid_voting_prediction(b_num: str, suit: str, last_ts, current_ts, bayes_probs, bias: Dict) -> Tuple[str, int, str]:
    votes = {0: 0, 1: 0, 2: 0}
    reasons = []
    
    math_text, math_code, R, gap, B, S = sovereign_math_engine(b_num, suit, last_ts, current_ts)
    votes[math_code] += 1
    reasons.append(f"M:{math_text}")
    
    if bayes_probs:
        period = "morning" if 6<=current_ts.hour<12 else "afternoon" if 12<=current_ts.hour<18 else "evening" if 18<=current_ts.hour<24 else "night"
        probs = bayes_probs.get(period)
        if probs:
            bayes_code = int(np.argmax(probs))
            votes[bayes_code] += 1
            reasons.append(f"B:{WINNER_NAMES[bayes_code]}")
    
    law_result = apply_ai_laws(b_num, suit, gap, bayes_probs)
    if law_result:
        law_text, law_code = law_result
        votes[law_code] += 2
        reasons.append(f"L:{law_text}")
    
    if bias.get('red_bias', 0) > 0.57 and math_code != 0:
        votes[0] += 1
        reasons.append(f"X:{WINNER_NAMES[0]}")
    elif bias.get('blue_bias', 0) > 0.57 and math_code != 1:
        votes[1] += 1
        reasons.append(f"X:{WINNER_NAMES[1]}")
    
    threshold = DYNAMIC_CONFIG.get('VOTE_THRESHOLD', 2)
    winner_code = max(votes, key=votes.get)
    
    if votes[winner_code] < threshold:
        winner_code = math_code
        reasons.append("→fallback:math")
    
    reason_str = " | ".join(reasons) + f" | Votes:{votes}"
    return WINNER_NAMES[winner_code], winner_code, reason_str

# ==================== 👁️ مراقب الذكاء الاصطناعي ====================
class AIObserver:
    def __init__(self, app):
        self.app = app
        self.ai_engine = AdvancedAIEngine()
        self.is_running = False    

    def _log(self, cycle: str, action: str, details: Dict):
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO ai_observer_log (observer_cycle, action_type, details) VALUES (%s,%s,%s)",
                       (cycle, action, json.dumps(details, default=str)))
            conn.commit()
            conn.close()
        except:
            pass
    
    def _get_history(self, limit: int = 100) -> pd.DataFrame:
        try:
            conn = get_db_connection()
            df = pd.read_sql(f"""SELECT * FROM history WHERE winner IS NOT NULL AND prediction IS NOT NULL
                ORDER BY id DESC LIMIT {limit}""", conn)
            conn.close()
            return df
        except:
            return pd.DataFrame()
    
    def _quick_scan(self, df: pd.DataFrame) -> List[Dict]:
        if len(df) < 20:
            return []
        patterns = []
        for w in ['الراعي 🔴', 'الثور 🔵', 'تعادل ⚪']:
            sub = df[df['winner'] == w]
            if len(sub) >= 5 and 'b_num' in sub.columns:
                sub_copy = sub.copy()
                sub_copy['last_digit'] = sub_copy['b_num'].astype(str).str[-1].str.extract(r'(\d)')
                freq = sub_copy['last_digit'].value_counts()
                if not freq.empty and freq.iloc[0] >= 3:
                    patterns.append({
                        'type': 'last_digit_winner', 'winner': w,
                        'digit': str(freq.index[0]), 'freq': int(freq.iloc[0]),
                        'confidence': min(0.95, freq.iloc[0] / len(sub) + 0.3)
                    })
        if 'suit' in df.columns:
            for s in SUITS:
                sub = df[df['suit'] == s]
                if len(sub) >= 5 and 'winner' in sub.columns:
                    wf = sub['winner'].value_counts()
                    if not wf.empty and wf.iloc[0] >= 3:
                        patterns.append({
                            'type': 'suit_winner', 'suit': s,
                            'winner': wf.index[0], 'freq': int(wf.iloc[0]),
                            'confidence': min(0.95, wf.iloc[0] / len(sub) + 0.25)
                        })
        return patterns    

    def _save_law(self, law: Dict):
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""INSERT INTO ai_laws (law_name, law_description, law_pattern, confidence_score)
                VALUES (%s,%s,%s,%s) ON CONFLICT (law_name) DO UPDATE
                SET confidence_score=EXCLUDED.confidence_score, last_updated=CURRENT_TIMESTAMP""",
                (law['name'], law.get('description', ''), json.dumps(law['pattern'], default=str), law['confidence']))
            conn.commit()
            conn.close()
            logger.info(f"💡 قانون جديد: {law['name']}")
        except Exception as e:
            logger.error(f"❌ حفظ القانون: {e}")
    
    async def quick_review(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_running:
            return
        logger.info("🔍 [Observer] مراجعة سريعة...")
        df = self._get_history(50)
        if df.empty:
            return
        patterns = self._quick_scan(df)
        for p in patterns:
            name = f"{p['type']}_{p.get('winner', p.get('suit', 'x'))}"
            existing = [l for l in get_active_laws() if l['name'] == name]
            if not existing:
                self._save_law({'name': name, 'description': p['type'], 'pattern': p, 'confidence': p['confidence']})
                self._log('quick', 'new_law', {'law': name})
        self._log('quick', 'done', {'patterns': len(patterns)})
    
    async def deep_review(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_running:
            return
        logger.info("🔬 [Observer] مراجعة عميقة...")
        df = self._get_history(200)
        if df.empty:
            return
        stats = get_latest_stats(df)
        ai_prompt = self.ai_engine.generate_analysis_prompt(stats, df)
        ai_result = self.ai_engine.ask_json(ai_prompt)
        
        if ai_result:
            for law in ai_result.get('new_laws', []):
                if law.get('confidence', 0) >= 0.6:
                    self._save_law(law)
                    self._log('deep', 'new_law', law)
            if ai_result.get('config_suggestions'):
                safe = {k: v for k, v in ai_result['config_suggestions'].items() if k in DYNAMIC_CONFIG}
                if safe:                    
                    save_dynamic_config(safe)
                    self._log('deep', 'config_update', safe)
        self._log('deep', 'done', {'laws': len(ai_result.get('new_laws', [])) if ai_result else 0})
    
    def start(self, jq: JobQueue):
        self.is_running = True
        jq.run_repeating(self.quick_review, interval=600, first=60, name="observer_quick")
        jq.run_repeating(self.deep_review, interval=1800, first=120, name="observer_deep")
        logger.info("⏰ [Observer] مُجدول: سريع/10د | عميق/30د")
    
    def stop(self, jq: JobQueue):
        self.is_running = False
        logger.info("🛑 [Observer] متوقف")

# ==================== 🎮 معالجات البوت (واجهة أزرار) ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر البداية - واجهة أزرار رئيسية"""
    try:
        user_id = update.effective_user.id
        df = load_filtered_history()
        stats = get_latest_stats(df) if not df.empty else {}
        
        kb = [
            [InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")],
            [InlineKeyboardButton("📊 تحليل البيانات", callback_data="view_stats")],
            [InlineKeyboardButton("🤖 تنبؤ AI", callback_data="ai_predict")],
            [InlineKeyboardButton("📜 القوانين", callback_data="view_laws")]
        ]
        if user_id == ADMIN_ID:
            kb.append([
                InlineKeyboardButton("🎛️ لوحة الأدمن", callback_data="admin_panel"),
                InlineKeyboardButton("📤 تصدير", callback_data="admin_export")
            ])
        
        summary = f"🏛️ **HADES V103**\n📊 جولات: {stats.get('total_rounds', 0)} | 🎯 دقة: {stats.get('accuracy', 'جاري التعلم') if stats.get('accuracy') else 'جاري التعلم'}"
        await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"❌ خطأ في /start: {e}")
        await update.message.reply_text("⚠️ حدث خطأ، حاول مرة أخرى")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار التفاعلية"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    
    if data == "choose_suit":
        kb = [
            [InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[:2]],
            [InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[2:]],              
            [InlineKeyboardButton("🔙 رجوع", callback_data="start_back")]
        ]
        await query.edit_message_text("🎴 اختر البذلة للبدء:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("s_"):
        suit = data[2:]
        context.user_data['suit'] = suit
        kb = [[InlineKeyboardButton("🔙 رجوع للبذلات", callback_data="choose_suit")]]
        await query.edit_message_text(f"✅ البذلة: {suit}\n📥 أرسل رقم البونص (7+ أرقام) للتحليل:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "view_stats":
        df = load_filtered_history()
        stats = get_latest_stats(df)
        if not stats:
            await query.answer("❌ لا توجد بيانات", show_alert=True)
            return
        report = f"""📊 **إحصائيات HADES V103**
🔢 جولات: {stats.get('total_rounds', 0)}
🏆 توزيع:
• 🔴: {stats['bias'].get('red', 0):.1%}
• 🔵: {stats['bias'].get('blue', 0):.1%}
• ⚪: {stats['bias'].get('tie', 0):.1%}"""
        kb = [[InlineKeyboardButton("🔄 تحديث", callback_data="view_stats")],
              [InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]]
        await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "ai_predict":
        if 'suit' not in context.user_data:
            await query.answer("⚠️ اختر بذلة أولاً", show_alert=True)
            return
        await query.answer("📥 أرسل رقم البونص الآن", show_alert=True)
        context.user_data['awaiting_bonus'] = True
    
    elif data == "view_laws":
        try:
            laws = get_active_laws()
            if not laws:
                await query.answer("لا توجد قوانين مكتشفة بعد", show_alert=True)
                return
            report = "📜 **أهم القوانين المكتشفة:**\n"
            for i, law in enumerate(laws[:5], 1):
                report += f"{i}. {law['name']} (ثقة: {law['confidence']:.0%})\n"
            kb = [[InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]]
            await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        except Exception as e:
            logger.error(f"❌ خطأ عرض القوانين: {e}")
            await query.answer("خطأ في جلب القوانين", show_alert=True)
    
    elif data == "admin_panel" and user_id == ADMIN_ID:
        kb = [
            [InlineKeyboardButton("📊 تحليل شامل", callback_data="admin_analyze")],            
            [InlineKeyboardButton("🔄 إعادة تحميل", callback_data="admin_reload")],
            [InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]
        ]
        await query.edit_message_text("🎛️ **لوحة تحكم الأدمن**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "admin_analyze" and user_id == ADMIN_ID:
        await query.edit_message_text("🔄 جاري التحليل...")
        df = load_filtered_history()
        stats = get_latest_stats(df)
        if stats:
            report = f"""📊 **تحليل شامل**
• جولات: {stats.get('total_rounds', 0)}
• دقة: {stats.get('accuracy', 'N/A')}
• انحياز 🔴: {stats['bias'].get('red', 0):.1%}"""
            kb = [[InlineKeyboardButton("🔄 تحديث", callback_data="admin_analyze")],
                  [InlineKeyboardButton("🔙 لوحة الأدمن", callback_data="admin_panel")]]
            await query.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "admin_export" and user_id == ADMIN_ID:
        await export_laws_command(update, context)
        await query.answer("✅ تم بدء التصدير", show_alert=True)
    
    elif data == "admin_reload" and user_id == ADMIN_ID:
        context.user_data.pop('suit', None)
        context.user_data.pop('last_b', None)
        await query.answer("✅ تم إعادة التحميل", show_alert=True)
        await start(update, context)
    
    elif data == "start_back":
        await start(update, context)
    
    elif data.startswith("save_"):
        parts = data.split("_")
        if len(parts) >= 4:
            b_num = parts[1]
            suit = parts[2]
            winner = "_".join(parts[3:])
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO history (b_num, suit, winner, timestamp, prediction, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (b_num, suit, winner, datetime.datetime.now(), 
                      WINNER_MAP.get(winner.split()[0], -1), user_id))
                conn.commit()
                conn.close()
                kb = [[InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")]]
                await query.edit_message_text(f"✅ سُجّل: {winner}\n🔄 جاهز للجولة التالية:", reply_markup=InlineKeyboardMarkup(kb))
            except Exception as e:                
                logger.error(f"❌ خطأ الحفظ: {e}")
                await query.answer("❌ خطأ في الحفظ", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل النصية"""
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    if context.user_data.get('awaiting_bonus') and text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start")
            return
        suit = context.user_data['suit']
        await update.message.reply_text(f"🔄 جاري تحليل {text} | {suit}...")
        
        df = load_filtered_history()
        if df.empty:
            await update.message.reply_text("❌ لا توجد بيانات كافية")
            return
        
        ai_engine = AdvancedAIEngine()
        result = ai_engine.generate_prediction_command(df, text, suit)
        
        prediction = result['prediction']
        reason = result['reason']
        confidence = result['confidence']
        
        report = f"""🎯 **تنبؤ HADES V103**
🏆 النتيجة: **{prediction}**
📋 السبب: {reason}
📊 الثقة: {confidence:.0%}
🎴 البذلة: {suit}"""
        
        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data=f"save_{text}_{suit}_الراعي 🔴"),
             InlineKeyboardButton("🔵 ثور", callback_data=f"save_{text}_{suit}_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data=f"save_{text}_{suit}_تعادل ⚪")],
            [InlineKeyboardButton("🔄 تحليل جديد", callback_data="ai_predict")]
        ]
        await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        context.user_data['awaiting_bonus'] = False
        return
    
    if text.lower() in ['تحليل', 'stats', '/analyze']:
        if user_id == ADMIN_ID:
            await analyze_command(update, context)
        else:
            await update.message.reply_text("❌ هذا الأمر للأدمن فقط")
        return
        
    if text.lower() in ['خروج', 'exit', 'back', '/start']:
        context.user_data.clear()
        await start(update, context)
        return
    
    kb = [
        [InlineKeyboardButton("🎴 البدء", callback_data="choose_suit")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="view_stats")],
        [InlineKeyboardButton("🤖 تنبؤ AI", callback_data="ai_predict")]
    ]
    await update.message.reply_text("🏛️ **HADES V103**\nاختر من القائمة للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# ==================== 📊 أوامر الأدمن ====================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ للأدمن فقط")
        return
    df = load_filtered_history()
    if df.empty:
        await update.message.reply_text("❌ لا توجد بيانات")
        return
    stats = get_latest_stats(df)
    report = f"""📊 **تقرير HADES V103**
🔢 جولات: {stats.get('total_rounds', 0)}
🏆 🔴:{stats['bias'].get('red',0):.1%} 🔵:{stats['bias'].get('blue',0):.1%} ⚪:{stats['bias'].get('tie',0):.1%}
🎯 دقة: {stats.get('accuracy', 'N/A')}"""
    kb = [[InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]]
    await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def export_laws_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ للأدمن فقط")
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT law_name, confidence_score FROM ai_laws WHERE is_active=TRUE ORDER BY confidence_score DESC LIMIT 10")
        laws = cur.fetchall()
        conn.close()
        report = "📜 **القوانين النشطة:**\n" + "\n".join([f"• {name} ({conf:.0%})" for name, conf in laws])
        await update.message.reply_text(report)
    except Exception as e:
        logger.error(f"❌ خطأ التصدير: {e}")
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 🚀 التشغيل الرئيسي ====================
if __name__ == "__main__":
    logger.info("🚀 بدء HADES V103 - واجهة الأزرار")
    
    # تهيئة القاعدة    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_laws (
            id SERIAL PRIMARY KEY, law_name VARCHAR(100) UNIQUE NOT NULL,
            law_description TEXT, law_pattern JSONB, confidence_score FLOAT DEFAULT 0.0,
            activation_count INTEGER DEFAULT 0, success_rate FLOAT DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE, created_by VARCHAR(50) DEFAULT 'AI_OBSERVER')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_equations (
            id SERIAL PRIMARY KEY, equation_name TEXT, equation_code TEXT,
            success_rate FLOAT DEFAULT 0, activation_count INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_active BOOLEAN DEFAULT TRUE)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_observer_log (
            id SERIAL PRIMARY KEY, observer_cycle VARCHAR(20), action_type VARCHAR(50),
            details JSONB, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("SELECT COUNT(*) FROM ai_equations")
        if cur.fetchone()[0] == 0:
            cur.execute("""INSERT INTO ai_equations (equation_name, equation_code, is_active)
                VALUES ('default_v1', '(B * S) + (delta_t % 7) + (last_digit * 3)', TRUE)""")
        conn.commit()
        conn.close()
        logger.info("✅ تم تهيئة الجداول")
    except Exception as e:
        logger.warning(f"⚠️ تحذير التهيئة: {e}")
    
    load_dynamic_config()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("export_laws", export_laws_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # بدء مراقب AI
    observer = AIObserver(app)
    observer.start(app.job_queue)
    
    logger.info("✅ البوت جاهز - واجهة الأزرار مفعلة")
    logger.info(f"📌 يتم تجاهل أول {WARMUP_ROUNDS} جولة تلقائياً")
    
    app.run_polling(drop_pending_updates=True)
