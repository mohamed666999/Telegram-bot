import os
import datetime
import psycopg2
import pandas as pd
import random
import re
from collections import Counter, defaultdict
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

# ==================== 2. معاملات نموذج الملف (مستخرجة من ملف CSV) ====================
# تم حذف الميزات التي تحتوي على 'winner' أو 'prediction' لأنها تسبب تسريبًا
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

# ==================== 3. نماذج التوقع مع إمكانية تحديث الأوزان ====================
class WeightedModelEnsemble:
    def __init__(self):
        self.model_weights = {'gap': 1.0, 'math': 1.0, 'file': 1.0}
        self.recent_predictions = defaultdict(list)  # تخزين آخر 50 توقع لكل نموذج
        self.recent_actuals = []  # آخر 50 نتيجة فعلية

    def update_weights(self, predictions, actual, window=50):
        """
        predictions: dict {'gap': pred, 'math': pred, 'file': pred}
        actual: القيمة الفعلية (0,1)
        """
        for model, pred in predictions.items():
            self.recent_predictions[model].append(pred)
            if len(self.recent_predictions[model]) > window:
                self.recent_predictions[model].pop(0)
        self.recent_actuals.append(actual)
        if len(self.recent_actuals) > window:
            self.recent_actuals.pop(0)

        # حساب دقة كل نموذج على آخر 50 جولة (أو ما توفر)
        for model in predictions:
            if len(self.recent_predictions[model]) == len(self.recent_actuals):
                correct = sum(1 for i in range(len(self.recent_actuals)) 
                              if self.recent_predictions[model][i] == self.recent_actuals[i])
                accuracy = correct / len(self.recent_actuals) if self.recent_actuals else 0.5
                self.model_weights[model] = accuracy + 0.5  # نضيف 0.5 لتجنب الوزن الصفري
            else:
                self.model_weights[model] = 1.0

    def predict(self, gap_pred, math_pred, file_pred):
        weighted_sum = (self.model_weights['gap'] * gap_pred +
                        self.model_weights['math'] * math_pred +
                        self.model_weights['file'] * file_pred)
        total_weight = sum(self.model_weights.values())
        avg = weighted_sum / total_weight
        return 1 if avg > 0.5 else 0

# إنشاء كائن عالمي للنموذج الجماعي
ensemble = WeightedModelEnsemble()

# ==================== 4. نماذج التوقع الفردية ====================
def gap_model(delta_t):
    """نموذج الفجوة الزمنية المحسن"""
    # إذا كانت الفجوة كبيرة جدًا (> 10 دقائق) => ثور
    if delta_t > 600:
        return 1
    # إذا كانت الفجوة متوسطة (2-10 دقائق) => راعي
    elif delta_t > 120:
        return 0
    # إذا كانت الفجوة صغيرة (< 2 دقيقة) => عشوائي (نرجع 0.5؟ لكن التوقع يجب أن يكون 0 أو 1)
    # هنا نستخدم قاعدة بسيطة: إذا كانت الفجوة أقل من 60 ثانية، راعي، وإلا ثور
    else:
        return 0 if delta_t < 60 else 1

def math_model(b_num, suit):
    """النموذج الرياضي الأساسي"""
    last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
    B = sum(int(d) for d in last_3 if d.isdigit())
    S = 1 if suit in ['♦️', '♥️'] else 2
    R = B * S
    return 1 if (R % 2 == 0) else 0  # 1=ثور, 0=راعي

def file_model(b_num, suit, hour):
    """نموذج الملفات المحسن"""
    score = 0
    try:
        b_num_int = int(b_num)
    except:
        return 0

    for feature, coeff in file_model_coefficients.items():
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
            # تحويل الرمز إلى الشكل المستخدم (♠️، ♣️، ♦️، ♥️)
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

        # ميزات أخرى (نضيفها بدون شرط)
        if not ('winner' in feature or 'prediction' in feature):
            score += coeff

    # تحويل score إلى 0 أو 1
    return 1 if score > 0 else 0

# ==================== 5. دوال مساعدة ====================
def get_time_period(hour):
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

def period_translate(period):
    return {
        "morning": "🌅 الصباح", "afternoon": "☀️ الظهر", 
        "evening": "🌇 المساء", "night": "🌙 الليل"
    }.get(period, period)

def ensure_columns():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS final_prediction INTEGER;")
    cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS user_id BIGINT;")
    # يمكن إضافة أعمدة لتخزين توقعات كل نموذج على حدة
    cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS gap_pred INTEGER;")
    cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS math_pred INTEGER;")
    cur.execute("ALTER TABLE IF EXISTS history ADD COLUMN IF NOT EXISTS file_pred INTEGER;")
    conn.commit()
    conn.close()

# ==================== 6. أوامر البوت ====================
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

        period_order = ["morning", "afternoon", "evening", "night"]
        period_acc = df.groupby('period')['correct'].mean().reindex(period_order) * 100

        hour_stats = df.groupby('hour').agg(accuracy=('correct', 'mean'), count=('correct', 'count'))
        hour_stats = hour_stats[hour_stats['count'] >= 10]
        hour_acc = hour_stats['accuracy'] * 100

        report = "📊 **تقرير أداء HADES**\n━━━━━━━━━━━━━━\n"
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
    """عرض حالة النموذج (آخر 50 و200 جولة)"""
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

        report = "🧠 **حالة محرك HADES**\n━━━━━━━━━━━━━━\n"
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

async def delete_last_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف آخر إدخال للمستخدم"""
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
    """تحميل قاعدة البيانات (للمسؤول فقط)"""
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

# ==================== 7. المعالجات الأساسية ====================
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
        cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        last_time = row[0] if row else None
        conn.close()

        delta_t = (current_time - last_time).total_seconds() if last_time else 0
        suit = context.user_data['suit']
        hour = current_time.hour

        # الحصول على التوقعات من النماذج الثلاثة
        pred1 = gap_model(delta_t)
        pred2 = math_model(text, suit)
        pred3 = file_model(text, suit, hour)

        # استخدام النموذج الجماعي المرجح
        final_prediction = ensemble.predict(pred1, pred2, pred3)

        # تخزين التوقعات الفردية في context لتحديث الأوزان لاحقاً
        context.user_data['predictions'] = {'gap': pred1, 'math': pred2, 'file': pred3}
        context.user_data['bonus'] = text
        context.user_data['final_prediction'] = final_prediction
        context.user_data['current_time'] = current_time

        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_الثور 🔵")]
        ]
        await update.message.reply_text(
            f"🎯 **التوقع النهائي:** {WINNER_NAMES[final_prediction]}\n"
            f"🗳️ الأصوات المرجحة: [فجوة: {WINNER_NAMES[pred1]}, رياضي: {WINNER_NAMES[pred2]}, ملف: {WINNER_NAMES[pred3]}]\n"
            f"⏱️ الفجوة: {int(delta_t)} ثانية\n"
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
        final_pred_code = context.user_data.get('final_prediction')
        predictions = context.user_data.get('predictions', {})

        if final_pred_code is None:
            await query.edit_message_text("❌ خطأ: لا يوجد توقع. ابدأ من جديد /start.")
            return

        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO history 
                   (b_num, suit, winner, timestamp, final_prediction, user_id, gap_pred, math_pred, file_pred) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    context.user_data['bonus'],
                    context.user_data['suit'],
                    winner_db,
                    context.user_data['current_time'],
                    final_pred_code,
                    update.effective_user.id,
                    predictions.get('gap'),
                    predictions.get('math'),
                    predictions.get('file')
                )
            )
            conn.commit()
            conn.close()

            # تحديث أوزان النموذج الجماعي بالنتيجة الفعلية
            actual_code = WINNER_MAP.get(winner_db, 2)
            if actual_code in (0, 1):  # نتعامل فقط مع الراعي والثور
                ensemble.update_weights(predictions, actual_code)

            pred_winner = WINNER_NAMES[final_pred_code]
            is_correct = "✅" if winner_db == pred_winner else "❌"

            # أزرار بعد الحفظ
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

# ==================== 8. التشغيل الرئيسي ====================
if __name__ == "__main__":
    ensure_columns()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("status", model_status))
    app.add_handler(CommandHandler("delete", delete_last_entry))
    app.add_handler(CommandHandler("download", download_database))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🚀 HADES V2.0 (Weighted Ensemble) is running...")
    app.run_polling()
