"""
HADES V102 - Autonomous Self-Evolving AI Prediction System
4 عقول ذكية: Math + Bayesian + Laws + Self-Optimizer
يعمل على Railway مع PostgreSQL + NVIDIA AI
"""

import os, sys, datetime, psycopg2, pandas as pd, numpy as np
import secrets, json, re, time, logging, random, asyncio
import io  # ✅ إضافة io لإنشاء الملفات
from typing import Dict, Any, Tuple, Optional, List
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, JobQueue
)
from openai import OpenAI

# ==================== 🛡️ إعدادات الأمان والتسجيل ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ==================== 🔑 الثوابت (مضمنة) ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

# تم التحديث إلى المفتاح والنموذج الجديدين (minimax-m2.5)
NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

LAWS_BACKUP_FILE = Path("ai_laws_backup.json")
EQUATIONS_BACKUP_FILE = Path("ai_equations_backup.json")

PLANS = {'day': 1, 'two_days': 2, 'week': 7, 'month': 30}

WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

DYNAMIC_CONFIG = {
    'CONFIDENCE_THRESHOLD': 0.65, 'MATH_WEIGHT': 0.55, 'BAYES_WEIGHT': 0.45,
    'MATH_CONFIDENCE': 0.7, 'S_RED': 1.0, 'S_BLACK': 1.0,
    'RANDOM_NOISE': 0.02, 'VOTE_THRESHOLD': 2,
}

PLAY_SESSION_MINUTES = 30
COOL_DOWN_1_MIN = (5, 10)
COOL_DOWN_2_MIN = 15

# ==================== 🕐 دوال الوقت ====================
def get_time_period(hour: int) -> str:
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

# ==================== 🗄️ إدارة قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_database():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""CREATE TABLE IF NOT EXISTS subscription_keys (
        id SERIAL PRIMARY KEY, key_code VARCHAR(50) UNIQUE NOT NULL,
        plan VARCHAR(20) NOT NULL, is_used BOOLEAN DEFAULT FALSE,
        used_by BIGINT, used_at TIMESTAMP, expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    
    cur.execute("""CREATE TABLE IF NOT EXISTS ai_settings (
        id SERIAL PRIMARY KEY, config_name VARCHAR(50) UNIQUE NOT NULL,
        config_value TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    
    cur.execute("""CREATE TABLE IF NOT EXISTS history (
        id SERIAL PRIMARY KEY, b_num VARCHAR(20), suit VARCHAR(10),
        winner VARCHAR(20), timestamp TIMESTAMP, prediction INTEGER, user_id BIGINT)""")
    
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
    
    # معادلة افتراضية
    cur.execute("SELECT COUNT(*) FROM ai_equations")
    if cur.fetchone()[0] == 0:
        cur.execute("""INSERT INTO ai_equations (equation_name, equation_code, is_active)
            VALUES ('default_v1', '(B * S) + (delta_t % 7) + (last_digit * 3)', TRUE)""")
    
    conn.commit()
    conn.close()
    logger.info("✅ تم تهيئة قاعدة البيانات")

def load_dynamic_config():
    global DYNAMIC_CONFIG
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT config_name, config_value FROM ai_settings")
        for name, value in cur.fetchall():
            if name in DYNAMIC_CONFIG:
                try: DYNAMIC_CONFIG[name] = json.loads(value)
                except: DYNAMIC_CONFIG[name] = value
        conn.close()
    except Exception as e: logger.warning(f"⚠️ فشل تحميل الإعدادات: {e}")

def save_dynamic_config(updates: Dict[str, Any]):
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

# ==================== 🔐 الاشتراكات ====================
def is_user_subscribed(user_id: int) -> Tuple[bool, Optional[str], int]:
    if user_id == ADMIN_ID: return True, "Admin", 999
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""SELECT plan, expires_at FROM subscription_keys
            WHERE used_by = %s AND expires_at > NOW() ORDER BY expires_at DESC LIMIT 1""", (user_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            plan, expires = row
            return True, plan, max(0, (expires - datetime.datetime.now()).days)
    except Exception as e: logger.error(f"❌ خطأ الاشتراك: {e}")
    return False, None, 0

def activate_subscription(user_id: int, key_code: str) -> Tuple[bool, str]:
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, plan, is_used FROM subscription_keys WHERE key_code = %s", (key_code,))
        row = cur.fetchone()
        if not row or row[2]: conn.close(); return False, "مفتاح غير صالح"
        key_id, plan, _ = row
        days = PLANS.get(plan)
        if not days: conn.close(); return False, "خطة غير معروفة"
        expires = datetime.datetime.now() + datetime.timedelta(days=days)
        cur.execute("""UPDATE subscription_keys SET is_used=TRUE, used_by=%s,
            used_at=NOW(), expires_at=%s WHERE id=%s""", (user_id, expires, key_id))
        conn.commit(); conn.close()
        return True, f"✅ اشتراك {plan} مفعل"
    except Exception as e: logger.error(f"❌ خطأ التفعيل: {e}"); return False, "خطأ داخلي"

# ==================== 🎮 إدارة الجلسات ====================
def init_user_session(ctx: ContextTypes.DEFAULT_TYPE):
    if 'session_start' not in ctx.user_data:
        ctx.user_data.update({
            'session_start': None, 'session_play_minutes': 0, 'cool_until': None,
            'cool_stage': 0, 'correct_streak': 0, 'last_predictions': []
        })

def can_user_play(uid: int, ctx: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, str]:
    if uid == ADMIN_ID: return True, ""
    init_user_session(ctx)
    now = datetime.datetime.now()
    cool = ctx.user_data.get('cool_until')
    if cool and now < cool:
        rem = (cool - now).seconds; m, s = divmod(rem, 60)
        return False, f"⏳ تبريد: {m}د {s}ث"
    if ctx.user_data['session_start'] is None:
        ctx.user_data['session_start'] = now; return True, ""
    duration = (now - ctx.user_data['session_start']).total_seconds() / 60
    played = ctx.user_data['session_play_minutes'] + duration
    if played >= PLAY_SESSION_MINUTES:
        cm = COOL_DOWN_2_MIN if ctx.user_data['cool_stage'] else random.randint(*COOL_DOWN_1_MIN)
        ctx.user_data.update({'cool_stage':1,'cool_until':now+datetime.timedelta(minutes=cm),
            'session_start':None,'session_play_minutes':0})
        return False, f"⏸️ انتهت الجلسة. انتظر {cm}د"
    return True, ""

def update_session_after_play(ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data.get('session_start') is None: return
    now = datetime.datetime.now()
    dur = (now - ctx.user_data['session_start']).total_seconds() / 60
    ctx.user_data['session_play_minutes'] += dur
    ctx.user_data['session_start'] = now

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
    except: return "(B * S) + (delta_t % 7) + (last_digit * 3)"

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
    S = DYNAMIC_CONFIG['S_RED'] if suit in ['♦️','♥️'] else DYNAMIC_CONFIG['S_BLACK']
    delta_t = int((current_ts - last_ts).total_seconds()) if last_ts else 0
    equation = load_active_equation()
    pred_code = safe_eval_equation(equation, B, S, delta_t, last_digit)
    R = (B * S) + (delta_t % 7) + (last_digit * 3)
    return WINNER_NAMES[pred_code], pred_code, R, delta_t, B, S

# ==================== 📊 التحليل البايزي ====================
def bayesian_analysis(conn, current_hour: int, min_samples: int = 20) -> Optional[Dict]:
    try:
        df = pd.read_sql("SELECT winner, timestamp FROM history WHERE winner IS NOT NULL", conn)
        if len(df) < min_samples: return None
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code'])
        probs = {}
        for p in ['morning','afternoon','evening','night']:
            pd_data = df[df['period']==p]
            if len(pd_data) >= min_samples:
                t = len(pd_data)
                probs[p] = ((pd_data['winner_code']==0).sum()/t,
                           (pd_data['winner_code']==1).sum()/t,
                           (pd_data['winner_code']==2).sum()/t)
            else: probs[p] = None
        return probs
    except Exception as e: logger.error(f"❌ Bayesian error: {e}"); return None

# ==================== 🔍 كشف الانحياز ====================
def detect_game_bias(df: pd.DataFrame) -> Dict[str, float]:
    if len(df) < 30: return {}
    total = len(df)
    return {
        "red_bias": float((df['winner']=='الراعي 🔴').sum() / total),
        "blue_bias": float((df['winner']=='الثور 🔵').sum() / total),
        "tie_bias": float((df['winner']=='تعادل ⚪').sum() / total)
    }

def apply_bias_correction(bias: Dict[str, float], math_code: int) -> Optional[int]:
    if not bias: return None
    if bias.get('red_bias', 0) > 0.57 and math_code != 0: return 0
    if bias.get('blue_bias', 0) > 0.57 and math_code != 1: return 1
    if bias.get('tie_bias', 0) > 0.35 and math_code != 2: return 2
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
            laws.append({'name':row[0],'pattern':row[1],'confidence':row[2],'success_rate':row[3]})
        conn.close()
        return laws
    except: return []

def apply_ai_laws(b_num: str, suit: str, gap: int, bayes_probs: Optional[Dict]) -> Optional[Tuple[str,int]]:
    laws = get_active_laws()
    if not laws: return None
    last_digit = int(b_num[-1]) if b_num[-1].isdigit() else 0
    current_period = get_time_period(datetime.datetime.now().hour)
    for law in laws:
        pat = law['pattern']
        score = 0
        if 'last_digit' in pat and pat['last_digit'] == last_digit: score += 0.4
        if 'suit' in pat and pat['suit'] == suit: score += 0.3
        if 'max_gap' in pat and gap <= pat['max_gap']: score += 0.2
        if 'period' in pat and pat['period'] == current_period: score += 0.1
        if score >= 0.6:
            winner = pat.get('predicted_winner')
            if winner in WINNER_MAP:
                logger.info(f"🎯 قانون مطبق: {law['name']}")
                return WINNER_NAMES[WINNER_MAP[winner]], WINNER_MAP[winner]
    return None

# ==================== 🗳️ نظام التصويت الهجين ====================
def hybrid_voting_prediction(b_num: str, suit: str, last_ts, current_ts, bayes_probs, bias) -> Tuple[str,int,str]:
    votes = {0:0, 1:0, 2:0}
    reasons = []
    
    math_text, math_code, R, gap, B, S = sovereign_math_engine(b_num, suit, last_ts, current_ts)
    votes[math_code] += 1
    reasons.append(f"M:{math_text}")
    
    if bayes_probs:
        period = get_time_period(current_ts.hour)
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
    
    bias_correction = apply_bias_correction(bias, math_code)
    if bias_correction is not None:
        votes[bias_correction] += 1
        reasons.append(f"X:{WINNER_NAMES[bias_correction]}")
    
    threshold = DYNAMIC_CONFIG.get('VOTE_THRESHOLD', 2)
    winner_code = max(votes, key=votes.get)
    if votes[winner_code] < threshold:
        winner_code = math_code
        reasons.append("→fallback:math")
    
    reason_str = " | ".join(reasons) + f" | Votes:{votes}"
    return WINNER_NAMES[winner_code], winner_code, reason_str

# ==================== 🤖 خدمة NVIDIA AI ====================
class NVIDIAService:
    def __init__(self):
        self.client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
        self.model = NVIDIA_MODEL
    
    def ask(self, prompt: str, temp: float = 0.7, tokens: int = 2048) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=[{"role":"user","content":prompt}],
                temperature=temp, max_tokens=tokens)
            return resp.choices[0].message.content
        except Exception as e:
            logger.error(f"❌ NVIDIA error: {e}")
            return f"⚠️ خطأ AI: {str(e)[:100]}"
    
    def ask_json(self, prompt: str, temp: float = 0.2) -> Optional[Dict]:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role":"system","content":"أجب بصيغة JSON صالحة فقط."},
                    {"role":"user","content":prompt}
                ], temperature=temp, max_tokens=1500)
            content = resp.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match: return json.loads(match.group())
        except Exception as e: logger.error(f"❌ JSON parse error: {e}")
        return None

nvidia_ai = NVIDIAService()

# ==================== 🔄 النسخ الاحتياطي ====================
def backup_ai_laws():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT law_name, law_pattern, confidence_score, success_rate FROM ai_laws WHERE is_active=TRUE")
        laws = [{"name":r[0],"pattern":r[1],"confidence":r[2],"success_rate":r[3]} for r in cur.fetchall()]
        conn.close()
        with open(LAWS_BACKUP_FILE, 'w', encoding='utf-8') as f:
            json.dump(laws, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 نسخ احتياطي: {len(laws)} قانون")
    except Exception as e: logger.error(f"❌ خطأ النسخ: {e}")

def backup_ai_equations():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT equation_name, equation_code, success_rate FROM ai_equations WHERE is_active=TRUE")
        eqs = [{"name":r[0],"code":r[1],"success_rate":r[2]} for r in cur.fetchall()]
        conn.close()
        with open(EQUATIONS_BACKUP_FILE, 'w', encoding='utf-8') as f:
            json.dump(eqs, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 نسخ احتياطي: {len(eqs)} معادلة")
    except Exception as e: logger.error(f"❌ خطأ النسخ: {e}")

def restore_from_backup():
    if not LAWS_BACKUP_FILE.exists(): return
    try:
        with open(LAWS_BACKUP_FILE, 'r', encoding='utf-8') as f:
            laws = json.load(f)
        conn = get_db_connection()
        cur = conn.cursor()
        for law in laws:
            cur.execute("""INSERT INTO ai_laws (law_name, law_description, law_pattern, confidence_score, success_rate)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT (law_name) DO NOTHING""",
                (law['name'], f"Restored", json.dumps(law['pattern']), law['confidence'], law['success_rate']))
        conn.commit(); conn.close()
        logger.info(f"♻️ استعادة: {len(laws)} قانون")
    except Exception as e: logger.error(f"❌ خطأ الاستعادة: {e}")

# ==================== 👁️ مراقب الذكاء الاصطناعي ====================
class AIObserver:
    def __init__(self, app):
        self.app = app
        self.is_running = False
    
    def _log(self, cycle: str, action: str, details: Dict):
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO ai_observer_log (observer_cycle, action_type, details) VALUES (%s,%s,%s)",
                       (cycle, action, json.dumps(details)))
            conn.commit(); conn.close()
        except: pass
    
    def _get_history(self, limit: int = 100) -> pd.DataFrame:
        try:
            conn = get_db_connection()
            df = pd.read_sql(f"""SELECT * FROM history WHERE winner IS NOT NULL AND prediction IS NOT NULL
                ORDER BY id DESC LIMIT {limit}""", conn)
            conn.close()
            return df
        except: return pd.DataFrame()
    
    def _quick_scan(self, df: pd.DataFrame) -> List[Dict]:
        if len(df) < 20: return []
        patterns = []
        for w in ['الراعي 🔴','الثور 🔵','تعادل ⚪']:
            sub = df[df['winner']==w]
            if len(sub) >= 5:
                freq = sub['b_num'].str[-1].value_counts()
                if not freq.empty and freq.iloc[0] >= 3:
                    patterns.append({'type':'last_digit_winner','winner':w,'digit':freq.index[0],
                        'freq':int(freq.iloc[0]),'confidence':min(0.95, freq.iloc[0]/len(sub)+0.3)})
        for s in ['♦️','♥️','♠️','♣️']:
            sub = df[df['suit']==s]
            if len(sub) >= 5:
                wf = sub['winner'].value_counts()
                if not wf.empty and wf.iloc[0] >= 3:
                    patterns.append({'type':'suit_winner','suit':s,'winner':wf.index[0],
                        'freq':int(wf.iloc[0]),'confidence':min(0.95, wf.iloc[0]/len(sub)+0.25)})
        return patterns
    
    def _deep_analysis(self, df: pd.DataFrame) -> Tuple[List[Dict], Optional[Dict]]:
        if len(df) < 50: return [], None
        new_laws, config_updates = [], None
        bias = detect_game_bias(df)
        if bias.get('red_bias',0) > 0.6:
            new_laws.append({'name':'RED_DOMINANCE','description':'انحياز قوي للأحمر',
                'pattern':{'predicted_winner':'الراعي 🔴','min_bias':0.6},
                'confidence':min(0.9, bias['red_bias']), 'type':'bias_law'})
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code'])
        if len(df) >= 30:
            acc = (df['winner_code'] == df['prediction']).mean()
            if acc < 0.6:
                config_updates = {'MATH_WEIGHT': max(0.3, DYNAMIC_CONFIG['MATH_WEIGHT'] - 0.05),
                                 'BAYES_WEIGHT': min(0.7, DYNAMIC_CONFIG['BAYES_WEIGHT'] + 0.05)}
        if len(df) >= 80:
            prompt = f"""أنت خبير أنماط. بيانات آخر {len(df)} جولة:
- النتائج: {df['winner'].value_counts().to_dict()}
- الدقة: {(df['winner_code']==df['prediction']).mean():.2%}
اقترح 1-2 قانون جديد بصيغة JSON: {{"new_laws":[{{"name":"X","description":"Y","pattern":{{"condition":"Z","predicted_winner":"W"}},"confidence":0.X}}]}}"""
            result = nvidia_ai.ask_json(prompt)
            if result and 'new_laws' in result:
                for law in result['new_laws']:
                    if law.get('confidence',0) >= 0.6:
                        new_laws.append(law)
        return new_laws, config_updates
    
    def _save_law(self, law: Dict):
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""INSERT INTO ai_laws (law_name, law_description, law_pattern, confidence_score)
                VALUES (%s,%s,%s,%s) ON CONFLICT (law_name) DO UPDATE
                SET confidence_score=EXCLUDED.confidence_score, last_updated=CURRENT_TIMESTAMP""",
                (law['name'], law.get('description',''), json.dumps(law['pattern']), law['confidence']))
            conn.commit(); conn.close()
            logger.info(f"💡 قانون جديد: {law['name']}")
        except Exception as e: logger.error(f"❌ حفظ القانون: {e}")
    
    async def quick_review(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_running: return
        logger.info("🔍 [Observer] مراجعة سريعة...")
        df = self._get_history(50)
        if df.empty: return
        patterns = self._quick_scan(df)
        for p in patterns:
            name = f"{p['type']}_{p.get('winner',p.get('suit','x'))}"
            existing = [l for l in get_active_laws() if l['name']==name]
            if not existing:
                self._save_law({'name':name,'description':p['type'],'pattern':p,'confidence':p['confidence']})
                self._log('quick','new_law',{'law':name})
        backup_ai_laws()
        self._log('quick','done',{'patterns':len(patterns)})
    
    async def deep_review(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_running: return
        logger.info("🔬 [Observer] مراجعة عميقة...")
        df = self._get_history(200)
        if df.empty: return
        new_laws, config_updates = self._deep_analysis(df)
        for law in new_laws:
            self._save_law(law)
            self._log('deep','new_law',law)
        if config_updates:
            safe = {k:v for k,v in config_updates.items() if k in DYNAMIC_CONFIG}
            if safe:
                save_dynamic_config(safe)
                self._log('deep','config_update',safe)
        backup_ai_laws()
        backup_ai_equations()
        self._log('deep','done',{'laws':len(new_laws),'config':config_updates is not None})
    
    def start(self, jq: JobQueue):
        self.is_running = True
        jq.run_repeating(self.quick_review, interval=600, first=60, name="observer_quick")
        jq.run_repeating(self.deep_review, interval=1800, first=120, name="observer_deep")
        logger.info("⏰ [Observer] مُجدول: سريع/10د | عميق/30د")
    
    def stop(self, jq: JobQueue):
        self.is_running = False
        jq.stop()
        logger.info("🛑 [Observer] متوقف")

# ==================== 🗑️ أوامر الحذف ====================
async def delete_rounds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ للأدمن فقط")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ الاستخدام: /delete_rounds <عدد>")
        return
    count = min(int(context.args[0]), 1000)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM history ORDER BY id DESC LIMIT %s", (count,))
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            cur.execute("DELETE FROM history WHERE id = ANY(%s)", (ids,))
            conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ حُذفت {len(ids)} جولة")
    except Exception as e:
        logger.error(f"❌ حذف جولات: {e}")
        await update.message.reply_text(f"❌ خطأ: {e}")

async def delete_last_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id,b_num,suit,winner,timestamp FROM history WHERE user_id=%s ORDER BY id DESC LIMIT 1",(uid,))
        row = cur.fetchone()
        if not row:
            conn.close()
            await update.message.reply_text("ℹ️ لا توجد جولات لحذفها")
            return
        cur.execute("DELETE FROM history WHERE id=%s AND user_id=%s",(row[0],uid))
        conn.commit(); conn.close()
        await update.message.reply_text(f"✅ حُذفت آخر جولة:\n🎴{row[2]}|🔢{row[1]}|🏆{row[3]}")
    except Exception as e:
        logger.error(f"❌ حذف آخر: {e}")
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 📥 أمر تحميل قاعدة البيانات (للأدمن) ====================
async def download_database_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحميل جميع جداول قاعدة البيانات كملف Excel (للأدمن فقط)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر متاح للمسؤول فقط.")
        return
    try:
        conn = get_db_connection()
        # جلب جميع الجداول المهمة
        tables = {
            "history": pd.read_sql("SELECT * FROM history ORDER BY id", conn),
            "subscription_keys": pd.read_sql("SELECT * FROM subscription_keys ORDER BY id", conn),
            "ai_settings": pd.read_sql("SELECT * FROM ai_settings ORDER BY id", conn),
            "ai_laws": pd.read_sql("SELECT * FROM ai_laws ORDER BY id", conn),
            "ai_equations": pd.read_sql("SELECT * FROM ai_equations ORDER BY id", conn),
            "ai_observer_log": pd.read_sql("SELECT * FROM ai_observer_log ORDER BY id", conn)
        }
        conn.close()
        
        # إنشاء ملف Excel في الذاكرة
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for sheet_name, df in tables.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        output.seek(0)
        
        # إرسال الملف
        await update.message.reply_document(
            document=output,
            filename=f"hades_db_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            caption="📥 نسخة احتياطية كاملة من قاعدة بيانات HADES"
        )
        logger.info(f"📥 تم تحميل قاعدة البيانات بواسطة الأدمن {update.effective_user.id}")
    except Exception as e:
        logger.error(f"❌ خطأ في تحميل قاعدة البيانات: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء التحميل: {str(e)[:100]}")

# ==================== 🤖 معالجات البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    sub, plan, rem = is_user_subscribed(uid)
    if not sub and uid != ADMIN_ID:
        await update.message.reply_text("🔐 **HADES V102**\nأرسل مفتاح الاشتراك للتفعيل")
        return
    context.user_data.clear()
    init_user_session(context)
    kb = [[InlineKeyboardButton("♦️ ديناري",callback_data="s_♦️"),InlineKeyboardButton("♥️ قلب",callback_data="s_♥️")],
          [InlineKeyboardButton("♠️ سبايد",callback_data="s_♠️"),InlineKeyboardButton("♣️ كلبة",callback_data="s_♣️")],
          [InlineKeyboardButton("🤖 دردشة AI",callback_data="ai_chat")]]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("🗑️ إدارة",callback_data="admin_tools")])
    status = f"📊 {plan} | ⏳ {rem}يوم" if sub else ""
    await update.message.reply_text(f"🏛️ **HADES V102**\n{status}\n\n🎴 اختر للبدء:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("s_"):
        context.user_data['suit'] = q.data[2:]
        await q.edit_message_text(f"✅ {q.data[2:]}\n📥 أرسل البونص (7+ أرقام):")
    elif q.data == "ai_chat":
        context.user_data['mode'] = "AI"
        await q.edit_message_text("🤖 **AI نشط**\nاكتب سؤالك أو 'خروج' للعودة:")
    elif q.data == "admin_tools":
        if update.effective_user.id != ADMIN_ID:
            await q.answer("❌",show_alert=True); return
        await q.edit_message_text("🗑️ **أدوات الحذف**\n• للأدمن: `/delete_rounds 10`\n• للمستخدم: `/delete_last`")
    elif q.data.startswith("save_"):
        winner = q.data[5:]
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""INSERT INTO history (b_num,suit,winner,timestamp,prediction,user_id)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                (context.user_data.get('last_b'), context.user_data.get('suit'), winner,
                 datetime.datetime.now(), context.user_data.get('last_p'), update.effective_user.id))
            conn.commit(); conn.close()
            context.user_data.update({'last_b':None,'last_p':None})
            await q.edit_message_text(f"✅ سُجّل: {winner}\n🔄 أرسل البونص القادم:")
        except Exception as e:
            logger.error(f"❌ حفظ: {e}")
            await q.edit_message_text("⚠️ خطأ في الحفظ")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    uid = update.effective_user.id
    sub,_,_ = is_user_subscribed(uid)
    if not sub and uid != ADMIN_ID:
        ok,msg = activate_subscription(uid, text)
        await update.message.reply_text(f"{'✅' if ok else '❌'} {msg}" + ("\n/start للبدء" if ok else ""))
        return
    if context.user_data.get('mode') == "AI":
        if text.lower() in ['exit','خروج','رجوع','back','/start']:
            context.user_data['mode'] = None
            await update.message.reply_text("🔙 تم الخروج")
            return
        await update.message.reply_text(f"🤖 **AI:**\n\n{nvidia_ai.ask(text)}", parse_mode='Markdown')
        return
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً"); return
        can,msg = can_user_play(uid, context)
        if not can:
            await update.message.reply_text(msg); return
        now = datetime.datetime.now()
        suit = context.user_data['suit']
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            last_ts = row[0] if row else now
            conn.close()
        except: last_ts = now
        try:
            conn = get_db_connection()
            bayes = bayesian_analysis(conn, now.hour)
            df = pd.read_sql("SELECT winner FROM history WHERE winner IS NOT NULL LIMIT 200", conn)
            conn.close()
            bias = detect_game_bias(df) if not df.empty else {}
        except: bayes, bias = None, {}
        pred_text, pred_code, reason = hybrid_voting_prediction(text, suit, last_ts, now, bayes, bias)
        context.user_data.update({'last_b':text, 'last_p':pred_code})
        update_session_after_play(context)
        kb = [[InlineKeyboardButton("🔴 راعي",callback_data="save_الراعي 🔴"),
               InlineKeyboardButton("🔵 ثور",callback_data="save_الثور 🔵")],
              [InlineKeyboardButton("⚪ تعادل",callback_data="save_تعادل ⚪")]]
        await update.message.reply_text(
            f"🎯 **HADES V102**\n\n🏆 **{pred_text}**\n"
            f"📊 {reason}\n🎴 {suit}\n\nسجل النتيجة:",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.message.reply_text("⚠️ أدخل رقم بونص صحيح (7+ أرقام)")

# ==================== 🚀 التشغيل الرئيسي ====================
if __name__ == "__main__":
    logger.info("🚀 HADES V102 Autonomous System starting...")
    init_database()
    load_dynamic_config()
    restore_from_backup()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM subscription_keys")
        if cur.fetchone()[0] == 0:
            for _ in range(10):
                cur.execute("INSERT INTO subscription_keys (key_code,plan) VALUES (%s,%s)",
                           (secrets.token_urlsafe(16),'month'))
            conn.commit()
        conn.close()
    except: pass
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("delete_rounds", delete_rounds_cmd))
    app.add_handler(CommandHandler("delete_last", delete_last_cmd))
    app.add_handler(CommandHandler("download", download_database_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    observer = AIObserver(app)
    observer.start(app.job_queue)
    backup_ai_laws()
    backup_ai_equations()
    logger.info("✅ جاهز. المراقب الذاتي يعمل: 10د/30د")
    logger.info("🧠 4 محركات: Math | Bayes | Laws | Bias + Voting")
    app.run_polling(drop_pending_updates=True)
