"""
HADES V-INFINITY - The Chaos Theory Engine (Fixed Import)
ابتكار خاص: محرك التطابق الفراكتلي (Fractal Parity)، مذبذب الفوضى (Entropy Oscillator)، وبروتوكول التناقض (Paradox).
"""

import os, re, datetime, psycopg2, pandas as pd, json, logging
from typing import Tuple, Dict, Optional, List  # 🌟 تم إصلاح هذا السطر ليتضمن List
from contextlib import contextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s" 
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']
RANKS_LAYOUT = [["A", "K", "Q", "J"], ["10", "9", "8", "7"], ["6", "5", "4", "3", "2"]]

# ==================== 🗄️ البنية التحتية ====================
@contextmanager
def get_db_cursor():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()

def clean_digits(text: str) -> str:
    if not text: return ""
    return re.sub(r"\D", "", str(text))

def generate_progress_bar(percentage: int) -> str:
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

# ==================== 🌌 ابتكار 1: شيفرة الفراكتل (Fractal Parity) ====================
def get_fractal_signature(b_num: str) -> str:
    """يحول آخر 4 أرقام من البونص إلى بصمة ثنائية (0 للزوجي، 1 للفردي) لكشف تسريب معالج الكازينو"""
    padded = b_num.zfill(4)
    last_four = padded[-4:]
    signature = "".join(["0" if int(d)%2==0 else "1" for d in last_four])
    return f"FRACTAL_{signature}"

# ==================== 🌌 ابتكار 2: مذبذب الفوضى (Entropy Oscillator) ====================
def measure_chaos_entropy() -> Tuple[float, str, bool]:
    """يقيس مدى تذبذب اللعبة. الفوضى العالية تعني انعكاساً قادماً"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT winner FROM history WHERE winner IS NOT NULL ORDER BY id DESC LIMIT 8")
            rows = cur.fetchall()
            if len(rows) < 8: return 0.0, "استقرار", False
            
            recent = [WINNER_MAP.get(r[0], 2) for r in rows]
            recent.reverse() # ترتيب من الأقدم للأحدث
            
            # حساب التغيرات (Transitions)
            changes = sum(1 for i in range(1, len(recent)) if recent[i] != recent[i-1])
            entropy_level = changes / 7.0 # النسبة المئوية للتغير
            
            if entropy_level > 0.7:
                return entropy_level, "⚠️ فوضى عارمة (اللعبة تعكس النتائج باستمرار)", True
            elif entropy_level < 0.2:
                return entropy_level, "⚠️ ركود خوارزمي (الهدوء الذي يسبق العاصفة، سيحدث كسر قريباً)", True
            else:
                return entropy_level, "متوازن (اللعبة تسير بنمط طبيعي)", False
    except: pass
    return 0.0, "مجهول", False

# ==================== 🌌 ابتكار 3: بروتوكول التناقض (The Paradox Engine) ====================
def fetch_paradoxical_patterns(suit: str, last_digit: int, fractal_sig: str) -> Tuple[Dict[int, float], List[str]]:
    """يجلب الأنماط، وإذا وجد نمطاً نسبة نجاحه وهمية/فائقة (كفخ من الكازينو)، يقوم بعكسه فوراً!"""
    scores = {0: 0.0, 1: 0.0}
    logs = []
    
    queries = [
        (fractal_sig, "بصمة معالج الكازينو", 2.5),
        (f"SD_{suit}_{last_digit}", "نمط البذلة+الرقم", 2.0),
        (f"SUIT_{suit}", "نمط البذلة", 1.2)
    ]
    
    try:
        with get_db_cursor() as (conn, cur):
            for pid, desc, weight in queries:
                cur.execute("SELECT red_count, blue_count FROM pattern_stats WHERE pattern_id = %s", (pid,))
                row = cur.fetchone()
                if row:
                    red, blue = row[0], row[1]
                    total = red + blue
                    if total > 0:
                        p_red = red / total
                        p_blue = blue / total
                        
                        # 🚨 THE PARADOX PROTOCOL 🚨
                        # إذا كان النمط يبدو مضموناً بشكل مبالغ فيه (+85%)، الكازينو سيقوم بكسره! نعكس التوقع!
                        if p_red > 0.85 and total >= 4:
                            scores[1] += weight * 3.0 # نعطي الثور قوة مضاعفة لكسر الفخ
                            logs.append(f"🌀 **بروتوكول التناقض:** فخ مكشوف للراعي في ({desc}) -> انعكاس إجباري للثور 🔵!")
                        elif p_blue > 0.85 and total >= 4:
                            scores[0] += weight * 3.0 
                            logs.append(f"🌀 **بروتوكول التناقض:** فخ مكشوف للثور في ({desc}) -> انعكاس إجباري للراعي 🔴!")
                        else:
                            # حساب طبيعي
                            winner = 0 if p_red > p_blue else 1
                            scores[winner] += max(p_red, p_blue) * weight
                            logs.append(f"🔍 {desc}: {WINNER_NAMES[winner]} [✅{int(max(red,blue))}|❌{int(min(red,blue))}]")
    except Exception as e:
        logger.error(f"Paradox Engine Error: {e}")
        
    return scores, logs

# ==================== 🧠 محرك INFINITY المركزي ====================
async def predict_infinity(b_num: str, suit: str, rank: str) -> Tuple[int, int, str]:
    clean_b = clean_digits(b_num)
    if not clean_b: return 2, 0, "❌ رقم غير صالح"
    
    last_digit = int(clean_b[-1])
    fractal_sig = get_fractal_signature(clean_b)
    
    logs = []
    
    # 1. قياس الفوضى (هل اللعبة في وضع جنون؟)
    entropy_val, entropy_msg, is_danger = measure_chaos_entropy()
    logs.append(f"🌊 **مذبذب الفوضى:** {entropy_msg} (معدل: {entropy_val:.2f})")

    # 2. استدعاء بروتوكول التناقض والبصمة
    scores, paradox_logs = fetch_paradoxical_patterns(suit, last_digit, fractal_sig)
    logs.extend(paradox_logs)
    
    # 3. دمج الحسابات
    final_pred = 0 if scores[0] >= scores[1] else 1
    total_score = scores[0] + scores[1]
    
    # حماية ضد نقص البيانات
    if total_score == 0:
        math_res = (sum(int(d) for d in clean_b[-3:]) + last_digit) % 2
        logs.append(f"🧮 **تحليل احتياطي (لم يسبق رؤية هذه البصمة)**")
        return math_res, 60, "\n".join(logs)
        
    raw_conf = (scores[final_pred] / total_score) * 100
    confidence = int(min(99, max(50, raw_conf)))
    
    # إذا كانت اللعبة في وضع خطر (فوضى أو ركود عالي)، نخفض الثقة لنخبرك بالحذر
    if is_danger:
        confidence = min(65, confidence)
        logs.append("\n⚠️ **نصيحة الآلة:** اللعبة في مرحلة تحول خوارزمي، العب بحذر شديد.")
    
    reason_str = "\n".join(logs)
    return final_pred, confidence, reason_str

# ==================== 🛠️ التعلم المستمر والآني ====================
def live_train_infinity(b_num: str, suit: str, winner_code: int):
    """تحديث البصمة الفراكتلية والأنماط فوراً بعد كل جولة"""
    last_digit = int(clean_digits(b_num)[-1])
    fractal_sig = get_fractal_signature(clean_digits(b_num))
    
    patterns = [
        fractal_sig,
        f"SD_{suit}_{last_digit}",
        f"SUIT_{suit}"
    ]
    
    col = "red_count" if winner_code == 0 else "blue_count" if winner_code == 1 else "tie_count"
    
    try:
        with get_db_cursor() as (conn, cur):
            for pid in patterns:
                cur.execute(f"""
                    INSERT INTO pattern_stats (pattern_id, {col}) VALUES (%s, 1) 
                    ON CONFLICT (pattern_id) DO UPDATE SET {col} = pattern_stats.{col} + 1
                """, (pid,))
            conn.commit()
    except: pass

# ==================== 🎮 الواجهة ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
    await update.message.reply_text("<b>🌌 HADES V-INFINIT
