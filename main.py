import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from collections import deque

class HADES_Engine:
    def __init__(self, db_conn):
        self.conn = db_conn
        self.digit_model = None
        self.temporal_model = None
        self.scaler = StandardScaler()
        self.history_df = None
        self.recent_accuracy = {'digit': 0.5, 'temporal': 0.5, 'sequential': 0.5, 'frequency': 0.5}
        self.last_50_results = deque(maxlen=50)
        self.last_50_predictions = {'digit': deque(maxlen=50), 'temporal': deque(maxlen=50), 
                                    'sequential': deque(maxlen=50), 'frequency': deque(maxlen=50)}
        self.load_data()
        self.train_models()

    def load_data(self):
        # تحميل جميع الجولات من قاعدة البيانات وتحويلها إلى DataFrame مع الميزات
        query = "SELECT b_num, suit, winner, timestamp FROM history ORDER BY id ASC"
        df = pd.read_sql(query, self.conn)
        # فلترة البيانات الرقمية وتحويلها (كما في التحليل أعلاه)
        # ... (نفس كود التحويل السابق)
        self.history_df = processed_df

    def train_models(self):
        # تدريب نموذج الأرقام
        X_digit = self.history_df[['len','sum_digits','last_digit','parity_sum','num_even_digits','mod_3','mod_5','suit_code']]
        y = self.history_df['winner_code']
        self.digit_model = RandomForestClassifier(n_estimators=100, max_depth=10)
        self.digit_model.fit(X_digit, y)

        # تدريب نموذج الزمني
        X_temp = self.history_df[['delta_t','hour','day_of_week']]
        # تطبيع
        X_temp_scaled = self.scaler.fit_transform(X_temp)
        self.temporal_model = GradientBoostingClassifier(n_estimators=100, max_depth=5)
        self.temporal_model.fit(X_temp_scaled, y)

        # تجهيز سلاسل ماركوف للتسلسلي
        self.build_markov_chain()

    def build_markov_chain(self):
        # حساب احتمالات الانتقال من آخر نتيجتين
        # نقوم ببناء قاموس transition[(prev2, prev1)] = [count0, count1, count2]
        # يتم تحديثه لاحقًا مع كل جولة جديدة
        self.transition_counts = {}
        winners = self.history_df['winner_code'].values
        for i in range(2, len(winners)):
            key = (winners[i-2], winners[i-1])
            if key not in self.transition_counts:
                self.transition_counts[key] = [0,0,0]
            self.transition_counts[key][winners[i]] += 1

    def sequential_prediction(self, last_two_results):
        # last_two_results = (prev_winner_code, prev_prev_winner_code) أو None
        if last_two_results is None or last_two_results not in self.transition_counts:
            return [1/3, 1/3, 1/3]  # احتمالات متساوية
        counts = self.transition_counts[last_two_results]
        total = sum(counts)
        if total == 0:
            return [1/3, 1/3, 1/3]
        return [c/total for c in counts]

    def frequency_prediction(self, b_num_features, suit):
        # البحث عن جولات مشابهة (نفس last_digit، نفس suit) في التاريخ
        similar = self.history_df[(self.history_df['last_digit'] == b_num_features['last_digit']) & 
                                  (self.history_df['suit_code'] == suit)]
        if len(similar) == 0:
            # توسيع البحث: نفس parity_last
            similar = self.history_df[(self.history_df['parity_last'] == b_num_features['last_digit']%2) & 
                                      (self.history_df['suit_code'] == suit)]
        if len(similar) == 0:
            return [1/3, 1/3, 1/3]
        # وزن زمني: الجولات الأحدث لها وزن أكبر
        weights = np.exp(-np.arange(len(similar))[::-1] / 50)  # توزيع أسي
        winner_counts = np.bincount(similar['winner_code'].values, weights=weights, minlength=3)
        return winner_counts / winner_counts.sum()

    def predict(self, b_num_str, suit, last_timestamp, current_timestamp, last_two_results):
        # استخراج ميزات b_num
        features = extract_features(b_num_str)  # دالة مساعدة
        suit_code = 1 if suit in ['♦️','♥️'] else 2

        # ميزات رقمية
        X_digit = np.array([[features['len'], features['sum_digits'], features['last_digit'],
                              features['parity_sum'], features['num_even_digits'],
                              features['mod_3'], features['mod_5'], suit_code]])
        prob_digit = self.digit_model.predict_proba(X_digit)[0]

        # ميزات زمنية
        delta_t = (current_timestamp - last_timestamp).total_seconds() if last_timestamp else 0
        hour = current_timestamp.hour
        day = current_timestamp.weekday()
        X_temp = np.array([[delta_t, hour, day]])
        X_temp_scaled = self.scaler.transform(X_temp)
        prob_temp = self.temporal_model.predict_proba(X_temp_scaled)[0]

        # تسلسلي
        prob_seq = self.sequential_prediction(last_two_results)

        # تكراري
        prob_freq = self.frequency_prediction(features, suit_code)

        # الدمج بالأوزان الديناميكية
        weights = np.array([self.recent_accuracy['digit'], self.recent_accuracy['temporal'],
                            self.recent_accuracy['sequential'], self.recent_accuracy['frequency']])
        weights = weights / weights.sum()
        prob_final = (weights[0] * prob_digit + weights[1] * prob_temp +
                      weights[2] * prob_seq + weights[3] * prob_freq)

        prediction = np.argmax(prob_final)
        confidence = prob_final[prediction]

        # تخزين التنبؤات الحالية لتحديث الأوزان لاحقًا
        self.last_50_predictions['digit'].append(np.argmax(prob_digit))
        self.last_50_predictions['temporal'].append(np.argmax(prob_temp))
        self.last_50_predictions['sequential'].append(np.argmax(prob_seq))
        self.last_50_predictions['frequency'].append(np.argmax(prob_freq))
        self.last_50_results.append(prediction)  # هذا مؤقت حتى نعرف النتيجة الحقيقية

        return prediction, confidence, prob_final

    def update_after_result(self, actual_winner):
        # تحديث الأوزان بناءً على دقة كل مصنف في آخر 50 جولة
        # يجب استدعاء هذه الدالة بعد معرفة النتيجة الحقيقية
        # لدينا last_50_predictions لكل مصنف و last_50_results (التوقعات النهائية فقط، نحتاج الفعلية)
        # هنا نفترض أننا نخزن النتائج الفعلية في قائمة actual_results
        # سيتم تنفيذ هذا الجزء بشكل منفصل في البوت
        pass
