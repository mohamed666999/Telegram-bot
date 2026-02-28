import os
import datetime
import psycopg2
import pandas as pd
import numpy as np
import joblib
from collections import deque
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"

# ==================== 2. محرك HADES المتطور ====================
class HADES_Engine:
    def __init__(self, conn):
        self.conn = conn
        self.digit_model = None
        self.temporal_model = None
        self.scaler = StandardScaler()
        self.history_df = None
        # الأوزان الديناميكية
        self.recent_accuracy = {'digit': 0.5, 'temporal': 0.5, 'sequential': 0.5, 'frequency': 0.5}
        # سجلات آخر 50 جولة لتحديث الأوزان
        self.last_50_actual = deque(maxlen=50)          # النتائج الفعلية
        self.last_50_predictions = {
            'digit': deque(maxlen=50),
            'temporal': deque(maxlen=50),
            'sequential': deque(maxlen=50),
            'frequency': deque(maxlen=50)
        }
        self.load_data()
        self.train_models()

    # ========== دالة مساعدة لاستخراج الميزات من رقم b_num ==========
    def extract_features(self, b_num_str):
        digits = [int(d) for d in b_num_str if d.isdigit()]
        if not digits:
            return None
        return {
            'len': len(digits),
            'sum_digits': sum(digits),
            'first_digit': digits[0],
            'last_digit': digits[-1],
            'parity_sum': sum(digits) % 2,
            'parity_last': digits[-1] % 2,
            'num_even_digits': sum(1 for d in digits if d % 2 == 0),
            'num_odd_digits': sum(1 for d in digits if d % 2 == 1),
            'mod_3': int(b_num_str) % 3 if b_num_str.isdigit() else 0,
            'mod_5': int(b_num_str) % 5 if b_num_str.isdigit() else 0,
            'avg_digit': sum(digits) / len(digits)
        }

    # ========== تحميل البيانات من قاعدة البيانات ==========
    def load_data(self):
        query = "SELECT id, b_num, suit, winner, timestamp FROM history ORDER BY id ASC"
        df = pd.read_sql(query, self.conn)
        # تحويل b_num إلى نص
        df['b_num_str'] = df['b_num'].astype(str)
        # التصفية: فقط السجلات التي b_num رقمي (أكبر من 7 أرقام ونوعها رقمي)
        df = df[df['b_num_str'].str.isdigit()].copy()
        if df.empty:
            # لا توجد بيانات كافية، نستخدم بيانات افتراضية أو ننتظر
            self.history_df = pd.DataFrame()
            return

        df['b_num_int'] = df['b_num_str'].astype(int)

        # استخراج الميزات لكل صف
        features_list = []
        for _, row in df.iterrows():
            feats = self.extract_features(row['b_num_str'])
            if feats:
                features_list.append(feats)
        if not features_list:
            self.history_df = pd.DataFrame()
            return

        feats_df = pd.DataFrame(features_list)
        df = pd.concat([df.reset_index(drop=True), feats_df], axis=1)

        # تحويل suit إلى رمز
        suit_map = {'♦️': 1, '♥️': 1, '♠️': 2, '♣️': 2}  # 1 = أحمر, 2 = أسود
        df['suit_code'] = df['suit'].map(suit_map).fillna(0).astype(int)

        # ترتيب زمني وحساب delta_t
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        df['delta_t'] = df['timestamp'].diff().dt.total_seconds().fillna(0)
        df['hour'] = df['timestamp'].dt.hour
        df['day_of_week'] = df['timestamp'].dt.dayofweek

        # ترميز winner
        winner_map = {'الراعي 🔴': 0, 'الثور 🔵': 1, 'تعادل ⚪': 2}
        df['winner_code'] = df['winner'].map(winner_map).fillna(2).astype(int)  # تعادل افتراضي

        self.history_df = df

    # ========== تدريب النماذج ==========
    def train_models(self):
        if self.history_df.empty or len(self.history_df) < 50:
            # بيانات غير كافية، نستخدم نماذج بسيطة أو نؤجل التدريب
            self.digit_model = RandomForestClassifier(n_estimators=10, max_depth=3)
            self.temporal_model = GradientBoostingClassifier(n_estimators=10, max_depth=2)
            # نتركها غير مدربة، سنقوم بتدريب افتراضي لاحقاً
            return

        # ميزات النموذج الرقمي
        feature_cols = ['len', 'sum_digits', 'last_digit', 'parity_sum',
                        'num_even_digits', 'mod_3', 'mod_5', 'suit_code']
        X_digit = self.history_df[feature_cols]
        y = self.history_df['winner_code']

        self.digit_model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
        self.digit_model.fit(X_digit, y)

        # ميزات النموذج الزمني
        X_temp = self.history_df[['delta_t', 'hour', 'day_of_week']]
        # تطبيع
        self.scaler.fit(X_temp)
        X_temp_scaled = self.scaler.transform(X_temp)
        self.temporal_model = GradientBoostingClassifier(n_estimators=100, max_depth=5, random_state=42)
        self.temporal_model.fit(X_temp_scaled, y)

        # بناء سلسلة ماركوف
        self.build_markov_chain()

    # ========== بناء سلسلة ماركوف من الرتبة 2 ==========
    def build_markov_chain(self):
        self.transition_counts = {}
        winners = self.history_df['winner_code'].values
        for i in range(2, len(winners)):
            key = (winners[i-2], winners[i-1])
            if key not in self.transition_counts:
                self.transition_counts[key] = [0, 0, 0]
            self.transition_counts[key][winners[i]] += 1

    # ========== التنبؤ التسلسلي ==========
    def sequential_prediction(self, last_two_results):
        if last_two_results is None or last_two_results not in self.transition_counts:
            return np.array([1/3, 1/3, 1/3])
        counts = self.transition_counts[last_two_results]
        total = sum(counts)
        if total == 0:
            return np.array([1/3, 1/3, 1/3])
        return np.array([c/total for c in counts])

    # ========== التنبؤ التكراري (بالنمط) ==========
    def frequency_prediction(self, features, suit_code):
        if self.history_df.empty:
            return np.array([1/3, 1/3, 1/3])

        # بحث بنفس last_digit ونفس suit
        similar = self.history_df[
            (self.history_df['last_digit'] == features['last_digit']) &
            (self.history_df['suit_code'] == suit_code)
        ]
        if len(similar) == 0:
            # توسيع: نفس تكافؤ last_digit
            similar = self.history_df[
                (self.history_df['parity_last'] == features['last_digit'] % 2) &
                (self.history_df['suit_code'] == suit_code)
            ]
        if len(similar) == 0:
            return np.array([1/3, 1/3, 1/3])

        # وزن زمني: الجولات الأحدث وزن أكبر
        # نأخذ آخر 50 مشابهة كحد أقصى
        similar = similar.tail(50)
        # ننشئ أوزاناً أسية متناقصة
        weights = np.exp(-np.arange(len(similar))[::-1] / 10)  # نصف العمر 10 جولات
        winner_counts = np.bincount(similar['winner_code'].values, weights=weights, minlength=3)
        return winner_counts / winner_counts.sum()

    # ========== التنبؤ الرئيسي ==========
    def predict(self, b_num_str, suit, last_timestamp, current_timestamp, last_two_results):
        # استخراج الميزات
        features = self.extract_features(b_num_str)
        if features is None:
            return 2, 0.0, np.array([0,0,1])  # تعادل افتراضي

        suit_code = 1 if suit in ['♦️', '♥️'] else 2

        # --- التنبؤ الرقمي ---
        if self.digit_model is not None and hasattr(self.digit_model, 'predict_proba'):
            X_digit = np.array([[features['len'], features['sum_digits'], features['last_digit'],
                                  features['parity_sum'], features['num_even_digits'],
                                  features['mod_3'], features['mod_5'], suit_code]])
            prob_digit = self.digit_model.predict_proba(X_digit)[0]
        else:
            prob_digit = np.array([1/3, 1/3, 1/3])

        # --- التنبؤ الزمني ---
        if self.temporal_model is not None and hasattr(self.temporal_model, 'predict_proba') and last_timestamp:
            delta_t = (current_timestamp - last_timestamp).total_seconds()
            hour = current_timestamp.hour
            day = current_timestamp.weekday()
            X_temp = np.array([[delta_t, hour, day]])
            # تطبيع باستخدام scaler المدرب (إذا كان موجوداً)
            if hasattr(self.scaler, 'mean_'):
                X_temp_scaled = self.scaler.transform(X_temp)
            else:
                X_temp_scaled = X_temp
            prob_temp = self.temporal_model.predict_proba(X_temp_scaled)[0]
        else:
            prob_temp = np.array([1/3, 1/3, 1/3])

        # --- التنبؤ التسلسلي ---
        prob_seq = self.sequential_prediction(last_two_results)

        # --- التنبؤ التكراري ---
        prob_freq = self.frequency_prediction(features, suit_code)

        # الدمج بالأوزان الديناميكية
        weights = np.array([self.recent_accuracy['digit'],
                            self.recent_accuracy['temporal'],
                            self.recent_accuracy['sequential'],
                            self.recent_accuracy['frequency']])
        weights = weights / weights.sum()
        prob_final = (weights[0] * prob_digit + weights[1] * prob_temp +
                      weights[2] * prob_seq + weights[3] * prob_freq)

        prediction = int(np.argmax(prob_final))
        confidence = float(prob_final[prediction])

        # تخزين تنبؤات كل مصنف لتحديث الأوزان لاحقاً
        self.last_50_predictions['digit'].append(int(np.argmax(prob_digit)))
        self.last_50_predictions['temporal'].append(int(np.argmax(prob_temp)))
        self.last_50_predictions['sequential'].append(int(np.argmax(prob_seq)))
        self.last_50_predictions['frequency'].append(int(np.argmax(prob_freq)))

        return prediction, confidence, prob_final

    # ========== تحديث الأوزان بعد معرفة النتيجة الفعلية ==========
    def update_after_result(self, actual_winner):
        # actual_winner: 0,1,2
        self.last_50_actual.append(actual_winner)

        # نحتاج إلى قوائم prediction لكل مصنف من آخر 50 جولة
        # إذا لم يكتمل 50 جولة بعد، ننتظر
        if len(self.last_50_actual) < 10:  # نبدأ التحديث بعد 10 جولات على الأقل
            return

        # نحسب الدقة لكل مصنف على آخر 50 جولة (أو ما توفر)
        actual_list = list(self.last_50_actual)
        for model_name in self.recent_accuracy.keys():
            pred_list = list(self.last_50_predictions[model_name])
            # نأخذ آخر min(len(actual_list), len(pred_list))
            min_len = min(len(actual_list), len(pred_list))
            if min_len == 0:
                continue
            correct = sum(1 for i in range(-min_len, 0) if pred_list[i] == actual_list[i])
            self.recent_accuracy[model_name] = correct / min_len

# ==================== 3. متغيرات عامة ====================
# إنشاء اتصال بقاعدة البيانات واستخدامه في المحرك
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# سنقوم بإنشاء المحرك مرة واحدة عند بدء التشغيل
conn = get_db_connection()
engine = HADES_Engine(conn)

# لتخزين آخر نتيجتين لكل محادثة (يمكن تحسينه باستخدام قاعدة بيانات)
user_last_results = {}  # mapping user_id -> (prev_winner, prev_prev_winner)

# ==================== 4. دوال التليجرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️", callback_data="s_♦️"), InlineKeyboardButton("♥️", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️", callback_data="s_♠️"), InlineKeyboardButton("♣️", callback_data="s_♣️")]
    ]
    await update.message.reply_text(
        "🏛️ **الكيان السيادي HADES V1.0**\n"
        "محرك تنبؤي متطور قائم على التعلم الآلي.\n"
        "اختر البذلة للبدء:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def download_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("📊 جاري تصدير السجل السيادي...")
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM history ORDER BY id ASC", conn)
        conn.close()

        filename = f"Observer_Log_{datetime.date.today()}.xlsx"
        df.to_excel(filename, index=False)

        with open(filename, "rb") as f:
            await update.message.reply_document(document=f, filename=filename, caption=f"📊 السجل يحتوي على {len(df)} جولة.")
        os.remove(filename)
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ فشل الاستخراج: {str(e)}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("s_"):
        context.user_data['suit'] = data[2:]
        await query.edit_message_text(f"✅ رادار {data[2:]} نشط.\n📥 أرسل رقم البونص (b_num):")

    elif data.startswith("save_"):
        winner = data.split("_", 1)[1]  # النص بعد save_
        # تحويل winner إلى رمز
        winner_map = {'راعي': 0, 'ثور': 1, 'تعادل': 2}
        winner_code = winner_map.get(winner, 2)

        # الحصول على بيانات الجولة من context
        b_num = context.user_data.get('bonus')
        suit = context.user_data.get('suit')
        timestamp = context.user_data.get('current_time', datetime.datetime.now())

        if not b_num or not suit:
            await query.edit_message_text("❌ بيانات الجولة مفقودة! أعد المحاولة.")
            return

        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO history (b_num, suit, winner, timestamp) VALUES (%s, %s, %s, %s)",
                    (b_num, suit, winner, timestamp)
                )
                conn.commit()
            conn.close()

            # تحديث المحرك بالنتيجة الفعلية
            engine.update_after_result(winner_code)

            # تحديث آخر نتيجتين للمستخدم
            user_id = update.effective_user.id
            if user_id not in user_last_results:
                user_last_results[user_id] = []
            user_last_results[user_id].append(winner_code)
            if len(user_last_results[user_id]) > 2:
                user_last_results[user_id].pop(0)

            await query.edit_message_text(f"✅ تم أرشفة الجولة ({winner}) في السجل بنجاح.\nالمحرك يتعلم من النتيجة...")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {str(e)}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 7:
        if 'suit' not in context.user_data:
            await update.message.reply_text("⚠️ اختر البذلة أولاً عبر /start.")
            return

        context.user_data['bonus'] = text
        current_timestamp = datetime.datetime.now()
        context.user_data['current_time'] = current_timestamp

        # جلب توقيت آخر جولة مسجلة في قاعدة البيانات
        last_timestamp = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT timestamp FROM history ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                if row:
                    last_timestamp = row[0]
            conn.close()
        except Exception as e:
            print(f"Database read error: {e}")

        # جلب آخر نتيجتين للمستخدم
        user_id = update.effective_user.id
        last_two = user_last_results.get(user_id, [])
        if len(last_two) == 2:
            last_two_results = (last_two[0], last_two[1])
        else:
            last_two_results = None

        # تنفيذ التنبؤ
        prediction_code, confidence, probs = engine.predict(
            text, context.user_data['suit'],
            last_timestamp, current_timestamp,
            last_two_results
        )
        pred_text = ["الراعي 🔴", "الثور 🔵", "تعادل ⚪"][prediction_code]

        # بناء التقرير
        time_str = current_timestamp.strftime("%H:%M:%S")
        report = f"""
⏰ **توقيت الإدخال:** `{time_str}`

🧠 **تحليل HADES المتقدم**
━━━━━━━━━━━━━━━━━
• الاحتمالات:
   - الراعي 🔴: {probs[0]:.1%}
   - الثور 🔵: {probs[1]:.1%}
   - تعادل ⚪: {probs[2]:.1%}
• الثقة: {confidence:.1%}
• **التوقع النهائي:** {pred_text}
━━━━━━━━━━━━━━━━━
        """

        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_راعي"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_ثور")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل")]
        ]
        await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb))

    else:
        await update.message.reply_text("❌ الرقم يجب أن يتكون من 7 أرقام على الأقل ولا يحتوي على أحرف.")

# ==================== 5. التشغيل ====================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_database))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("🚀 بوت HADES يعمل الآن مع محرك تنبؤي متطور...")
    app.run_polling()
