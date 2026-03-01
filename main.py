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
file_model_coefficients = {
    'BIN_LESS_THAN_769.0_id': -2163693.286151,
    'BIN_FROM_769.0_TO_790.0_id': -2040258.406043,
    # ... (باقي المعاملات كما هي، ولكن بدون الميزات المسربة)
}
# ملاحظة: تم حذف الميزات التي تحتوي على 'winner' أو 'prediction' كما اقترحت سابقًا.

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
            state[key] = pickle.loads(val.encode('latin1'))  # استخدم encoding مناسب
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
        # كلما كانت المسافة إلى bull أصغر، زاد الاحتمال
        prob_bull = dist_to_rai / (dist_to_bull + dist_to_rai)
        return prob_bull

class MathModel:
    def predict_proba(self, b_num, suit):
        last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
        B = sum(int(d) for d in last_3 if d.isdigit())
        S = 1 if suit in ['♦️', '♥️'] else 2
        R = B * S
        # تحويل R إلى احتمال (كلما كان R زوجيًا، زاد احتمال الثور)
        # نستخدم دالة سينية على R (بعد تطبيع)
        normalized_R = (R - 15) / 15  # قيمة تقريبية
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
        # القيم كبيرة جدًا، نقسم على 1e6 تقريبًا
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
                acc_short = correct_short / len(self.actuals_short)
            else:
                acc_short = 0.5
            
            # الدقة في النافذة الطويلة
            if len(self.long_history[model]) == len(self.actuals_long):
                correct_long = sum(1 for i in range(len(self.actuals_long)) if self.long_history[model][i] == self.actuals_long[i])
                acc_long = correct_long / len(self.actuals_long)
            else:
                acc_long = 0.5
            
            # الوزن الجديد = 0.7 * acc_short + 0.3 * acc_long + 0.5 (لتجنب الصفر)
            self.weights[model] = 0.7 * acc_short + 0.3 * acc_long + 0.5
    
    def predict(self, model_probs):
        """model_probs: dict من الاحتمالات"""
        weighted_sum = 0
        total_weight = 0
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
        correct = 0
        for i, actual in enumerate(self.actuals_short):
            # نحتاج التنبؤات لكل نموذج؟ هنا نستخدم التوقع النهائي غير متوفر، لذا نستخدم متوسط بسيط
            # بدلاً من ذلك، يمكن تخزين التوقعات النهائية في قائمة منفصلة
            # للتبسيط، سنفترض أننا نخزن التوقعات النهائية في مكان آخر
            # سنقوم بإضافة قائمة final_predictions في المستقبل
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

        period_order = ["morning", "afternoon", "evening", "night"]
        period_acc = df.groupby('period')['correct'].mean().reindex(period_order) * 100
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
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def model_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, final_prediction, timestamp FROM history WHERE final_prediction IS NOT NULL ORDER BY id DESC LIMIT 200", conn)
        conn.close()

        if len(df) < 10:
            await update.message.reply_text("⚠️ بيانات غير كافية.")
            return

        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'final_prediction'])
        df['correct'] = (df['winner_code'] == df['final_prediction']).astype(int)

        acc_50 = df.head(50)['correct'].mean() * 100 if len(df) >= 50 else None
        acc_200 = df['correct'].mean() * 100

        report = "🧠 **حالة محرك HADES V3**\n━━━━━━━━━━━━━━\n"
        if acc_50:
            report += f"📉 آخر 50 جولة: {acc_50:.1f}%\n"
        report += f"📊 آخر 200 جولة: {acc_200:.1f}%\n"

        if acc_200 >= 65:
            status = "✅ ممتاز"
        elif acc_200 >= 58:
            status = "⚖️ مقبول"
        else:
            status = "🔻 ضعيف"
        report += f"\n**التقييم:** {status}"
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def drift_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """كشف الانجراف"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمسؤول فقط.")
        return
    # نستخدم آخر 30 توقعًا نهائيًا (يجب تخزينها في ensemble)
    # سنقوم بتحميل الحالة واستخراج short_history
    state = load_model_state()
    if 'ensemble_actuals_short' in state:
        actuals = state['ensemble_actuals_short']
        # نحتاج predictions أيضًا - مبسط
        await update.message.reply_text("🔍 تحليل الانجراف: غير مكتمل بعد.")
    else:
        await update.message.reply_text("لا توجد بيانات كافية.")

async def delete_last_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT id FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("⚠️ لا يوجد إدخال سابق لك.")
        return
    cur.execute("DELETE FROM history WHERE id = %s", (row[0],))
    conn.commit()
    conn.close()
    await update.message.reply_text("🗑️ تم حذف آخر إدخال لك.")

async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمسؤول فقط.")
        return
    status = await update.message.reply_text("📊 جاري التصدير...")
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT * FROM history ORDER BY id ASC", conn)
        conn.close()
        filename = f"Observer_Log_{datetime.date.today()}.xlsx"
        df.to_excel(filename, index=False)
        with open(filename, "rb") as f:
            await update.message.reply_document(document=f, filename=filename, caption=f"📊 {len(df)} جولة.")
        os.remove(filename)
        await status.delete()
    except Exception as e:
        await status.edit_text(f"❌ فشل: {e}")

# ==================== 10. المعالجات الأساسية ====================
# تهيئة النماذج مرة واحدة عند بدء التشغيل
gap_model, math_model, file_model, markov_model, ensemble = init_models()

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start.")
            return

        current_time = datetime.datetime.now()
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        
        # جلب آخر جولة (لحساب delta_t)
        cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        last_time = row[0] if row else None
        delta_t = (current_time - last_time).total_seconds() if last_time else None
        
        # جلب آخر فائز لهذا المستخدم (لنموذج Markov)
        cur.execute("SELECT winner FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        last_winner = WINNER_MAP.get(row[0]) if row else None
        
        conn.close()

        suit = context.user_data['suit']
        hour = current_time.hour

        # تحديث نموذج الفجوة من البيانات (مرة كل فترة)
        # يمكن استدعاؤها بشكل دوري، لكن للتبسيط نتركها

        # الحصول على الاحتمالات من كل نموذج
        prob_gap = gap_model.predict_proba(delta_t)
        prob_math = math_model.predict_proba(text, suit)
        prob_file = file_model.predict_proba(text, suit, hour)
        prob_markov = markov_model.predict_proba(last_winner)

        probs = {'gap': prob_gap, 'math': prob_math, 'file': prob_file, 'markov': prob_markov}
        final_prob = ensemble.predict(probs)
        final_pred = 1 if final_prob > 0.5 else 0

        # تخزين البيانات في context لحين الحفظ
        context.user_data['bonus'] = text
        context.user_data['final_pred'] = final_pred
        context.user_data['probs'] = probs
        context.user_data['current_time'] = current_time
        context.user_data['delta_t'] = delta_t
        context.user_data['last_winner'] = last_winner

        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_الثور 🔵")]
        ]
        await update.message.reply_text(
            f"🎯 **التوقع النهائي:** {WINNER_NAMES[final_pred]} (احتمال {final_prob:.2f})\n"
            f"🗳️ النماذج: فجوة {prob_gap:.2f}, رياضي {prob_math:.2f}, ملف {prob_file:.2f}, ماركوف {prob_markov:.2f}\n"
            f"⏱️ الفجوة: {int(delta_t) if delta_t else 0} ثانية\n"
            f"━━━━━━━━━━━━━━\n"
            f"اختر النتيجة الحقيقية:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ أرسل رقم بونص صحيح (7 أرقام على الأقل).")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("s_"):
        suit = query.data[2:]
        context.user_data['suit'] = suit
        await query.edit_message_text(f"✅ تم اختيار {suit}. أرسل رقم البونص:")

    elif query.data.startswith("save_"):
        winner_db = query.data[5:]
        final_pred = context.user_data.get('final_pred')
        probs = context.user_data.get('probs', {})
        last_winner = context.user_data.get('last_winner')

        if final_pred is None:
            await query.edit_message_text("❌ خطأ: لا يوجد توقع. ابدأ من جديد /start.")
            return

        actual = WINNER_MAP.get(winner_db)
        if actual not in (0, 1):
            await query.edit_message_text("⚠️ يتم تسجيل التعادل فقط (لا يؤثر على تعلم النموذج).")
            # نكمل الحفظ ولكن لا نحدث الأوزان
            should_update = False
        else:
            should_update = True

        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO history 
                   (b_num, suit, winner, timestamp, final_prediction, user_id, gap_prob, math_prob, file_prob, markov_prob) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    context.user_data['bonus'],
                    context.user_data['suit'],
                    winner_db,
                    context.user_data['current_time'],
                    final_pred,
                    update.effective_user.id,
                    probs.get('gap'),
                    probs.get('math'),
                    probs.get('file'),
                    probs.get('markov')
                )
            )
            conn.commit()
            conn.close()

            if should_update:
                # تحديث نموذج ماركوف
                if last_winner is not None:
                    markov_model.update(last_winner, actual)
                # تحديث النموذج الجماعي
                ensemble.update(probs, actual)
                # حفظ الحالة في قاعدة البيانات
                save_model_state('ensemble_weights', ensemble.weights)
                save_model_state('markov_transitions', dict(markov_model.transitions))
                save_model_state('gap_means', (gap_model.bull_mean, gap_model.rai_mean))
                # يمكن حفظ short_history أيضًا

            pred_winner = WINNER_NAMES[final_pred]
            is_correct = "✅" if winner_db == pred_winner else "❌"

            keyboard = [
                [InlineKeyboardButton("🔄 بدء جولة جديدة", callback_data="new_round"),
                 InlineKeyboardButton("🗑️ حذف آخر إدخال", callback_data="delete_last")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"{is_correct} **تم التسجيل**\n\n"
                f"🎯 توقعنا: {pred_winner}\n"
                f"🏆 النتيجة: {winner_db}\n"
                f"━━━━━━━━━━━━━━\n"
                f"/performance - تحليل\n"
                f"/status - حالة النموذج\n"
                f"/delete - حذف آخر إدخال",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {e}")

    elif query.data == "new_round":
        await start(update, context)

    elif query.data == "delete_last":
        user_id = update.effective_user.id
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT id FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM history WHERE id = %s", (row[0],))
            conn.commit()
            await query.edit_message_text("🗑️ تم حذف آخر إدخال لك.\nأرسل /start لبدء جولة جديدة.")
        else:
            await query.edit_message_text("⚠️ لا يوجد إدخال سابق لك.")
        conn.close()

# ==================== 11. التشغيل الرئيسي ====================
if __name__ == "__main__":
    ensure_tables()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("status", model_status))
    app.add_handler(CommandHandler("drift", drift_command))
    app.add_handler(CommandHandler("delete", delete_last_entry))
    app.add_handler(CommandHandler("download", download_database))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🚀 HADES V3 (Advanced Ensemble) is running...")
    app.run_polling()
