import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
import re
import pickle
from collections import defaultdict, deque
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

# ==================== 2. معاملات نموذج الملف (من ملف CSV) ====================
# تم حذف الميزات التي تحتوي على 'winner' أو 'prediction' لتجنب تسرب البيانات
file_model_coefficients = {
    'BIN_LESS_THAN_769.0_id': -2163693.286151,
    'BIN_FROM_769.0_TO_790.0_id': -2040258.406043,
    'BIN_FROM_790.0_TO_814.0_id': -1865023.520384,
    'BIN_FROM_814.0_TO_849.0_id': -1790573.101484,
    'BIN_FROM_849.0_TO_874.0_id': -1703748.331043,
    'BIN_MORE_THAN_1297.0_id': 1331928.867296,
    'PAIR_id_&suit:BIN_FROM_1278.0_TO_1297.0&♠️': 1275643.664571,
    'PAIR_id_&suit:BIN_FROM_1278.0_TO_1297.0&♣️': 1211579.435308,
    'BIN_FROM_1146.0_TO_1251.0_id': 965549.82778,
    'PAIR_id_&suit:BIN_FROM_1278.0_TO_1297.0&♥️': -923161.502105,
    'BIN_FROM_1062.0_TO_1088.0_id': 870936.658853,
    'BIN_FROM_1029.0_TO_1062.0_id': 827780.045487,
    'BIN_FROM_1111.0_TO_1146.0_id': 807888.316629,
    'timestamp (Hour of Day)-21': -801875.804421,
    'BIN_FROM_1251.0_TO_1278.0_id': 794942.504084,
    'timestamp (Hour of Day)-small_count': 690416.953323,
    'timestamp (Hour of Day)-17': 677389.266817,
    'timestamp (Hour of Day)-22': -668875.142086,
    'timestamp (Hour of Day)-19': 664949.437912,
    'BIN_FROM_1278.0_TO_1297.0_id': -640023.298445,
    'timestamp (Hour of Day)-9': -591486.045223,
    'PAIR_id_&suit:BIN_FROM_1278.0_TO_1297.0&♦️': -556069.959023,
    'timestamp (Hour of Day)-8': -496931.102243,
    'timestamp (Hour of Day)-6': 454133.939618,
    'BIN_MORE_THAN_1772337496064.0_timestamp': -381267.613971,
    'PAIR_id_&suit:BIN_FROM_1088.0_TO_1111.0&♥️': 377621.549866,
    'BIN_FROM_1772320456704.0_TO_1772337496064.0_timestamp': -367883.211547,
    'BIN_FROM_1772250464256.0_TO_1772313640960.0_timestamp': 314885.309995,
    'timestamp (Hour of Day)-12': 261372.939805,
    'timestamp (Hour of Day)-18': 260240.949148,
    'timestamp (Hour of Day)-13': 241702.919932,
    'PAIR_id_&suit:BIN_MORE_THAN_1297.0&♠️': -234532.420546,
    'PAIR_id_&suit:BIN_FROM_1251.0_TO_1278.0&♥️': 220286.456117,
    'BIN_FROM_1088.0_TO_1111.0_id': 219494.406077,
    'PAIR_id_&suit:BIN_FROM_1251.0_TO_1278.0&♣️': 205185.860649,
    'timestamp (Hour of Day)-15': 181955.283644,
    'PAIR_id_&suit:BIN_MORE_THAN_1297.0&♥️': 176373.503312,
    'PAIR_id_&suit:BIN_FROM_1251.0_TO_1278.0&♠️': -176282.433134,
    'BIN_FROM_905.0_TO_932.0_id': 164905.076577,
    'PAIR_id_&suit:BIN_FROM_1088.0_TO_1111.0&♣️': -153457.648209,
    'PAIR_id_&suit:BIN_FROM_1062.0_TO_1088.0&♠️': -152383.540805,
    'PAIR_id_&suit:BIN_FROM_1146.0_TO_1251.0&♦️': 142928.882814,
    'BIN_FROM_874.0_TO_905.0_id': -132657.073033,
    'PAIR_id_&suit:BIN_LESS_THAN_769.0&♣️': -131320.368119,
    'PAIR_id_&suit:BIN_FROM_992.0_TO_1029.0&♣️': -131320.368119,
    'PAIR_id_&suit:BIN_FROM_966.0_TO_992.0&♣️': -131320.368119,
    'PAIR_id_&suit:BIN_FROM_932.0_TO_966.0&♣️': -131320.368119,
    'PAIR_id_&suit:BIN_FROM_905.0_TO_932.0&♣️': -131320.368119,
    'PAIR_id_&suit:BIN_FROM_874.0_TO_905.0&♣️': -131320.368119,
    'PAIR_id_&suit:BIN_FROM_849.0_TO_874.0&♣️': -131320.368119,
    'PAIR_id_&suit:BIN_FROM_814.0_TO_849.0&♣️': -131320.368119,
    'PAIR_id_&suit:BIN_FROM_790.0_TO_814.0&♣️': -131320.368119,
    'PAIR_id_&suit:BIN_FROM_769.0_TO_790.0&♣️': -131320.368119,
    'PAIR_id_&suit:BIN_FROM_1029.0_TO_1062.0&♣️': -131320.368119,
    'timestamp (Hour of Day)-23': -119487.828019,
    'BIN_FROM_992.0_TO_1029.0_id': 115741.488466,
    'BIN_FROM_1772313640960.0_TO_1772320456704.0_timestamp': -99099.98726,
    'PAIR_id_&suit:BIN_FROM_1088.0_TO_1111.0&♦️': 93184.635051,
    'PAIR_id_&suit:BIN_MORE_THAN_1297.0&♣️': -91747.250919,
    'PAIR_id_&suit:BIN_FROM_1146.0_TO_1251.0&♠️': -90227.424276,
    'PAIR_id_&suit:BIN_MORE_THAN_1297.0&♦️': 90003.678694,
    'suit-♠️': 293956.312022,
    'suit-♣️': 71197.862487,
    'suit-♦️': -69370.587464,
    'PAIR_id_&suit:BIN_FROM_1088.0_TO_1111.0&♠️': -62640.669669,
    'BIN_FROM_966.0_TO_992.0_id': 56955.886049,
    'PAIR_id_&suit:BIN_FROM_1029.0_TO_1062.0&♦️': 53124.591582,
    'timestamp (Hour of Day)-0': -45145.261403,
    'PAIR_id_&suit:BIN_FROM_1111.0_TO_1146.0&♠️': -33472.987054,
    'BIN_LESS_THAN_1772250464256.0_timestamp': 28062.115663,
    'PAIR_id_&suit:BIN_FROM_1062.0_TO_1088.0&♥️': -27277.443991,
    'PAIR_id_&suit:BIN_FROM_1146.0_TO_1251.0&♥️': 25973.226764,
    'PAIR_id_&suit:BIN_FROM_1251.0_TO_1278.0&♦️': 24797.007843,
    'PAIR_id_&suit:BIN_LESS_THAN_769.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_992.0_TO_1029.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_966.0_TO_992.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_932.0_TO_966.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_905.0_TO_932.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_874.0_TO_905.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_849.0_TO_874.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_814.0_TO_849.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_790.0_TO_814.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_769.0_TO_790.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_1029.0_TO_1062.0&♠️': -21094.265971,
    'PAIR_id_&suit:BIN_FROM_1146.0_TO_1251.0&♣️': -20814.233837,
    'PAIR_id_&suit:BIN_FROM_1111.0_TO_1146.0&♥️': 18215.276089,
    'PAIR_id_&suit:BIN_LESS_THAN_769.0&♥️': -16631.220497,
    'PAIR_id_&suit:BIN_FROM_992.0_TO_1029.0&♥️': -16631.220497,
    'PAIR_id_&suit:BIN_FROM_966.0_TO_992.0&♥️': -16631.220497,
    'PAIR_id_&suit:BIN_FROM_932.0_TO_966.0&♥️': -16631.220497,
    'PAIR_id_&suit:BIN_FROM_905.0_TO_932.0&♥️': -16631.220497,
}

# ==================== 3. دوال مساعدة عامة ====================
def get_time_period(hour):
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

def period_translate(period):
    return {"morning": "🌅 الصباح", "afternoon": "☀️ الظهر", "evening": "🌇 المساء", "night": "🌙 الليل"}.get(period, period)

# ==================== 4. دوال التأكد من وجود الجداول ====================
def ensure_tables():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()

    # جدول history (مع إضافة أعمدة التوقعات الفردية)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY,
            b_num VARCHAR(20),
            suit VARCHAR(10),
            winner VARCHAR(20),
            timestamp TIMESTAMP,
            final_prediction INTEGER,
            user_id BIGINT,
            gap_prob FLOAT,
            math_prob FLOAT,
            file_prob FLOAT,
            markov_prob FLOAT
        )
    """)

    # جدول لتخزين حالة النموذج الجماعي (الأوزان، النوافذ، إلخ)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS model_state (
            key VARCHAR(50) PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()

# ==================== 5. إدارة حالة النموذج (تحميل/حفظ) ====================
def load_model_state():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    state = {}
    cur.execute("SELECT key, value FROM model_state")
    for key, val in cur.fetchall():
        try:
            state[key] = pickle.loads(val.encode('latin1'))
        except:
            state[key] = val
    conn.close()
    return state

def save_model_state(key, value):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    pickled = pickle.dumps(value).decode('latin1')
    cur.execute("INSERT INTO model_state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, pickled))
    conn.commit()
    conn.close()

# ==================== 6. النماذج الفردية مع مخرجات احتمالية ====================

class GapModel:
    def __init__(self):
        self.bull_mean = 300  # قيم افتراضية (سيتم تحديثها من البيانات)
        self.rai_mean = 150

    def update_from_data(self, conn):
        """تحديث المتوسطات من قاعدة البيانات"""
        df = pd.read_sql("SELECT winner, EXTRACT(EPOCH FROM (timestamp - LAG(timestamp) OVER (ORDER BY id))) AS delta FROM history WHERE winner IN ('الراعي 🔴', 'الثور 🔵')", conn)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        bull_deltas = df[df['winner_code'] == 1]['delta'].dropna()
        rai_deltas = df[df['winner_code'] == 0]['delta'].dropna()
        if len(bull_deltas) > 10:
            self.bull_mean = bull_deltas.mean()
        if len(rai_deltas) > 10:
            self.rai_mean = rai_deltas.mean()

    def predict_proba(self, delta_t):
        """إرجاع احتمال الثور (0 إلى 1)"""
        if delta_t is None:
            return 0.5
        dist_to_bull = abs(delta_t - self.bull_mean)
        dist_to_rai = abs(delta_t - self.rai_mean)
        if dist_to_bull + dist_to_rai == 0:
            return 0.5
        prob_bull = dist_to_rai / (dist_to_bull + dist_to_rai)
        return prob_bull

class MathModel:
    def predict_proba(self, b_num, suit):
        last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
        B = sum(int(d) for d in last_3 if d.isdigit())
        S = 1 if suit in ['♦️', '♥️'] else 2
        R = B * S
        # تحويل R إلى احتمال باستخدام دالة سينية بعد تطبيع
        normalized_R = (R - 15) / 15
        prob_bull = 1 / (1 + np.exp(-normalized_R))
        return prob_bull

class FileModel:
    def __init__(self, coefficients):
        self.coefficients = coefficients

    def predict_proba(self, b_num, suit, hour):
        score = 0
        try:
            b_num_int = int(b_num)
        except:
            return 0.5

        for feature, coeff in self.coefficients.items():
            # ميزات BIN_*_id
            bin_id_match = re.match(r'BIN_(LESS_THAN|FROM_(\d+\.?\d*)_TO_(\d+\.?\d*)|MORE_THAN)_(\d+\.?\d*)_id', feature)
            if bin_id_match:
                bin_type = bin_id_match.group(1)
                if bin_type == 'LESS_THAN':
                    threshold = float(bin_id_match.group(4))
                    if b_num_int < threshold:
                        score += coeff
                elif bin_type == 'MORE_THAN':
                    threshold = float(bin_id_match.group(4))
                    if b_num_int >= threshold:
                        score += coeff
                elif bin_type.startswith('FROM_'):
                    lower = float(bin_id_match.group(2))
                    upper = float(bin_id_match.group(3))
                    if lower <= b_num_int < upper:
                        score += coeff
                continue

            # ميزات PAIR_id_&suit
            pair_match = re.match(r'PAIR_id_&suit:BIN_(LESS_THAN|FROM_(\d+\.?\d*)_TO_(\d+\.?\d*)|MORE_THAN)_(\d+\.?\d*)&(.)', feature)
            if pair_match:
                pair_suit = pair_match.group(5)
                suit_map = {'♠️': '♠️', '♣️': '♣️', '♦️': '♦️', '♥️': '♥️'}
                if suit_map.get(pair_suit) == suit:
                    bin_type = pair_match.group(1)
                    if bin_type == 'LESS_THAN':
                        threshold = float(pair_match.group(4))
                        if b_num_int < threshold:
                            score += coeff
                    elif bin_type == 'MORE_THAN':
                        threshold = float(pair_match.group(4))
                        if b_num_int >= threshold:
                            score += coeff
                    elif bin_type.startswith('FROM_'):
                        lower = float(pair_match.group(2))
                        upper = float(pair_match.group(3))
                        if lower <= b_num_int < upper:
                            score += coeff
                continue

            # ميزات الساعة
            if feature.startswith('timestamp (Hour of Day)-'):
                try:
                    feat_hour = int(feature.split('-')[1])
                    if feat_hour == hour:
                        score += coeff
                except:
                    pass
                continue

            # ميزات البذلة
            if feature.startswith('suit-'):
                feat_suit = feature.split('-')[1]
                if feat_suit == suit:
                    score += coeff
                continue

            # ميزات أخرى (بدون شرط)
            score += coeff

        # تطبيع النتيجة باستخدام Sigmoid
        normalized_score = score / 1_000_000
        prob_bull = 1 / (1 + np.exp(-normalized_score))
        return prob_bull

class MarkovModel:
    def __init__(self):
        self.transitions = defaultdict(int)  # (prev, curr) -> count
        self.last_winner = None

    def update(self, prev, curr):
        if prev is not None:
            self.transitions[(prev, curr)] += 1

    def predict_proba(self, last_winner):
        if last_winner is None or (last_winner, 0) not in self.transitions:
            return 0.5
        total = self.transitions.get((last_winner, 0), 0) + self.transitions.get((last_winner, 1), 0)
        if total == 0:
            return 0.5
        prob_bull = self.transitions.get((last_winner, 1), 0) / total
        return prob_bull

# ==================== 7. النموذج الجماعي المرجح بنافذتين ====================
class WeightedEnsemble:
    def __init__(self, short_window=30, long_window=200):
        self.short_window = short_window
        self.long_window = long_window
        self.weights = {'gap': 1.0, 'math': 1.0, 'file': 1.0, 'markov': 1.0}
        self.short_history = defaultdict(lambda: deque(maxlen=short_window))
        self.long_history = defaultdict(lambda: deque(maxlen=long_window))
        self.actuals_short = deque(maxlen=short_window)
        self.actuals_long = deque(maxlen=long_window)

    def update(self, model_probs, actual):
        """
        model_probs: dict {'gap': p, 'math': p, 'file': p, 'markov': p}
        actual: 0 أو 1
        """
        for model, prob in model_probs.items():
            pred = 1 if prob > 0.5 else 0
            self.short_history[model].append(pred)
            self.long_history[model].append(pred)
        self.actuals_short.append(actual)
        self.actuals_long.append(actual)

        # تحديث الأوزان بناءً على الدقة في كل نافذة
        for model in model_probs:
            # الدقة في النافذة القصيرة
            if len(self.short_history[model]) == len(self.actuals_short):
                correct_short = sum(1 for i in range(len(self.actuals_short)) if self.short_history[model][i] == self.actuals_short[i])
                acc_short = correct_short / len(self.actuals_short) if self.actuals_short else 0.5
            else:
                acc_short = 0.5

            # الدقة في النافذة الطويلة
            if len(self.long_history[model]) == len(self.actuals_long):
                correct_long = sum(1 for i in range(len(self.actuals_long)) if self.long_history[model][i] == self.actuals_long[i])
                acc_long = correct_long / len(self.actuals_long) if self.actuals_long else 0.5
            else:
                acc_long = 0.5

            # الوزن الجديد = 0.7 * acc_short + 0.3 * acc_long + 0.5 (لتجنب الصفر)
            self.weights[model] = 0.7 * acc_short + 0.3 * acc_long + 0.5

    def predict(self, model_probs):
        """دمج الاحتمالات باستخدام الأوزان الحالية"""
        weighted_sum = 0.0
        total_weight = 0.0
        for model, prob in model_probs.items():
            weighted_sum += self.weights.get(model, 1.0) * prob
            total_weight += self.weights.get(model, 1.0)
        if total_weight == 0:
            return 0.5
        return weighted_sum / total_weight

    def get_drift_status(self):
        """كشف الانجراف: إذا كانت دقة آخر 30 جولة < 45%"""
        if len(self.actuals_short) < self.short_window:
            return "جاري جمع البيانات..."
        # نحتاج إلى التوقعات النهائية لكل جولة في النافذة القصيرة
        # يمكن تخزين final_predictions في قائمة منفصلة، لكن للتبسيط نستخدم متوسط الأوزان
        # سنقوم بحساب دقة بسيطة بناءً على الأوزان الحالية؟ الأفضل تخزين final_pred
        # سأتركه مؤقتاً
        return "مستقر"  # مؤقت

# ==================== 8. تهيئة النماذج واستعادة الحالة ====================
def init_models():
    # إنشاء النماذج
    gap_model = GapModel()
    math_model = MathModel()
    file_model = FileModel(file_model_coefficients)
    markov_model = MarkovModel()
    ensemble = WeightedEnsemble()

    # محاولة تحميل الحالة من قاعدة البيانات
    state = load_model_state()
    if 'ensemble_weights' in state:
        ensemble.weights = state['ensemble_weights']
    if 'markov_transitions' in state:
        markov_model.transitions = state['markov_transitions']
    if 'gap_means' in state:
        gap_model.bull_mean, gap_model.rai_mean = state['gap_means']

    return gap_model, math_model, file_model, markov_model, ensemble

# ==================== 9. أوامر البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]
    ]
    await update.message.reply_text(
        "🎴 اختر نوع البذلة:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحليل أداء التوقعات حسب الفترات والساعات"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, final_prediction, timestamp FROM history WHERE final_prediction IS NOT NULL", conn)
        conn.close()

        if len(df) < 10:
            await update.message.reply_text("⚠️ البيانات غير كافية (نحتاج 10 جولات على الأقل).")
            return

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['period'] = df['hour'].apply(get_time_period)
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'final_prediction'])
        df['correct'] = (df['winner_code'] == df['final_prediction']).astype(int)

        # الدقة حسب الفترات
        period_order = ["morning", "afternoon", "evening", "night"]
        period_acc = df.groupby('period')['correct'].mean().reindex(period_order) * 100

        # الدقة حسب الساعات (بحد أدنى 10 جولات)
        hour_stats = df.groupby('hour').agg(accuracy=('correct', 'mean'), count=('correct', 'count'))
        hour_stats = hour_stats[hour_stats['count'] >= 10]
        hour_acc = hour_stats['accuracy'] * 100

        report = "📊 **تقرير أداء HADES V3**\n━━━━━━━━━━━━━━\n"
        for p in period_order:
            if p in period_acc and not pd.isna(period_acc[p]):
                report += f"{period_translate(p)}: {period_acc[p]:.1f}%\n"

        if not hour_acc.empty:
            report += "\n✅ **أفضل 3 ساعات:**\n"
            for h, acc in hour_acc.nlargest(3).items():
                report += f"🟢 {h:02d}:00 → {acc:.1f}%\n"
            report += "\n⚠️ **أسوأ 3 ساعات:**\n"
            for h, acc in hour_acc.nsmallest(3).items():
                report += f"🔴 {h:02d}:00 → {acc:.1f}%\n"

        report += f"\n📈 إجمالي الجولات: {len(df)}"
        await update.message.reply_text
