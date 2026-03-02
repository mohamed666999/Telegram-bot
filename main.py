import os
import datetime
import asyncio
import pickle
import numpy as np
import pandas as pd
import psycopg2
import re
from collections import deque
from typing import List, Dict, Tuple, Optional

# -------------------- مكتبات التحليل المتقدم --------------------
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
import gplearn.genetic as gpl  # للانحدار الرمزي (يتطلب تثبيت: pip install gplearn)
from mlxtend.frequent_patterns import apriori, association_rules  # لقواعد الارتباط

# -------------------- مكتبات البوت --------------------
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084  # معرف المسؤول لتلقي التقارير

WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

# مسار حفظ النماذج والقوانين
MODELS_DIR = "hades_x_models"
os.makedirs(MODELS_DIR, exist_ok=True)

# ==================== 2. دوال مساعدة ====================
def get_time_period(hour: int) -> str:
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

def period_translate(period: str) -> str:
    return {"morning": "🌅 الصباح", "afternoon": "☀️ الظهر", "evening": "🌇 المساء", "night": "🌙 الليل"}.get(period, period)

def extract_features(b_num: str, suit: str, hour: int, last_winner: Optional[int] = None) -> Dict:
    """استخراج ميزات متقدمة من الجولة"""
    digits = [int(d) for d in b_num if d.isdigit()]
    features = {
        'b_num_len': len(b_num),
        'b_num_sum': sum(digits) if digits else 0,
        'b_num_avg': np.mean(digits) if digits else 0,
        'b_num_max': max(digits) if digits else 0,
        'b_num_min': min(digits) if digits else 0,
        'last_digit': digits[-1] if digits else 0,
        'last_digit_parity': digits[-1] % 2 if digits else 0,
        'even_digits_count': sum(1 for d in digits if d % 2 == 0) if digits else 0,
        'odd_digits_count': sum(1 for d in digits if d % 2 == 1) if digits else 0,
        'suit_red': 1 if suit in ['♦️', '♥️'] else 0,
        'suit_black': 1 if suit in ['♠️', '♣️'] else 0,
        'suit_♠️': 1 if suit == '♠️' else 0,
        'suit_♣️': 1 if suit == '♣️' else 0,
        'suit_♦️': 1 if suit == '♦️' else 0,
        'suit_♥️': 1 if suit == '♥️' else 0,
        'hour': hour,
        'time_period_morning': 1 if get_time_period(hour) == 'morning' else 0,
        'time_period_afternoon': 1 if get_time_period(hour) == 'afternoon' else 0,
        'time_period_evening': 1 if get_time_period(hour) == 'evening' else 0,
        'time_period_night': 1 if get_time_period(hour) == 'night' else 0,
    }
    if last_winner is not None:
        features['last_winner'] = last_winner
    return features

# ==================== 3. محرك التحليل والقوانين ====================
class HadesXAnalytics:
    def __init__(self):
        self.df_history = None          # آخر 500 جولة
        self.last_analyzed_id = 0       # آخر id تم تحليله
        self.rules = []                  # قائمة القوانين المكتشفة
        self.models = {}                  # النماذج المدربة
        self.symbolic_functions = []      # دوال رمزية مكتشفة
        self.last_update = None

    def load_new_data(self) -> int:
        """تحميل البيانات الجديدة منذ آخر تحليل"""
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql(f"SELECT * FROM history WHERE id > {self.last_analyzed_id} ORDER BY id", conn)
        conn.close()
        if df.empty:
            return 0
        # تحديث self.df_history بإضافة الجديد وحذف القديم (الاحتفاظ بـ 500)
        if self.df_history is not None:
            self.df_history = pd.concat([self.df_history, df], ignore_index=True).tail(500)
        else:
            self.df_history = df.tail(500)
        new_count = len(df)
        self.last_analyzed_id = self.df_history['id'].max()
        return new_count

    def prepare_data(self):
        """تحضير البيانات للتحليل: إضافة ميزات، ترميز الفائز"""
        if self.df_history is None or len(self.df_history) < 30:
            return None, None
        df = self.df_history.copy()
        # استخراج الميزات لكل صف
        rows = []
        last_winner = None
        for _, row in df.iterrows():
            features = extract_features(
                str(row['b_num']),
                row['suit'],
                pd.to_datetime(row['timestamp']).hour,
                last_winner
            )
            features['winner'] = WINNER_MAP.get(row['winner'], 2)
            rows.append(features)
            last_winner = features['winner']
        df_feat = pd.DataFrame(rows)
        # حذف الصفوف ذات القيم المفقودة
        df_feat = df_feat.dropna()
        X = df_feat.drop('winner', axis=1)
        y = df_feat['winner']
        return X, y

    def run_association_rules(self, X, y, min_support=0.1, min_threshold=0.6):
        """استخراج قواعد الارتباط بين الميزات والنتيجة"""
        # دمج الميزات مع النتيجة في DataFrame واحد
        df_temp = X.copy()
        df_temp['winner'] = y
        # تحويل البيانات إلى قيم قاطعة (لـ mlxtend)
        df_disc = df_temp.copy()
        for col in df_disc.columns:
            if col in ['hour', 'b_num_len', 'b_num_sum', 'b_num_avg', 'b_num_max', 'b_num_min', 'last_digit', 'even_digits_count', 'odd_digits_count']:
                df_disc[col] = pd.cut(df_disc[col], bins=5, labels=False)  # تقطيع إلى 5 فئات
            else:
                df_disc[col] = df_disc[col].astype(str)  # الباقي قاطع بالفعل
        # ترميز واحد ساخن (one-hot)
        df_encoded = pd.get_dummies(df_disc)
        try:
            frequent_itemsets = apriori(df_encoded, min_support=min_support, use_colnames=True)
            rules = association_rules(frequent_itemsets, metric="confidence", min_threshold=min_threshold)
            # تصفية القواعد التي تكون فيها النتيجة (winner) في التالي
            rules_with_winner = rules[rules['consequents'].apply(lambda x: any('winner' in str(i) for i in x))]
            return rules_with_winner
        except:
            return pd.DataFrame()

    def train_decision_tree(self, X, y, max_depth=4):
        """تدريب شجرة قرار لاستخراج قواعد سهلة الفهم"""
        clf = DecisionTreeClassifier(max_depth=max_depth, random_state=42)
        clf.fit(X, y)
        rules_text = export_text(clf, feature_names=list(X.columns))
        return clf, rules_text

    def train_random_forest(self, X, y):
        """تدريب غابة عشوائية واستخراج أهمية الميزات"""
        rf = RandomForestClassifier(n_estimators=100, random_state=42)
        rf.fit(X, y)
        importance = pd.DataFrame({'feature': X.columns, 'importance': rf.feature_importances_}).sort_values('importance', ascending=False)
        return rf, importance

    def symbolic_regression(self, X, y):
        """انحدار رمزي للعثور على معادلات رياضية تربط الميزات بالنتيجة (للتبسيط، نستخدم gplearn)"""
        # هذا الجزء متقدم ويتطلب بيانات مستمرة، وقد لا يعمل مباشرة مع القيم القاطعة.
        # سنستخدمه بشكل تجريبي.
        try:
            # اختيار ميزات عددية فقط
            numeric_cols = ['b_num_len', 'b_num_sum', 'b_num_avg', 'b_num_max', 'b_num_min', 'last_digit', 'even_digits_count', 'odd_digits_count', 'hour']
            X_num = X[numeric_cols].fillna(0)
            y_bin = (y == 1).astype(int)  # نتنبأ بالثور فقط كمثال
            function_set = ['add', 'sub', 'mul', 'div', 'sin', 'cos', 'log', 'sqrt']
            est = gpl.SymbolicRegressor(population_size=1000,
                                        generations=10,
                                        function_set=function_set,
                                        verbose=0,
                                        random_state=42)
            est.fit(X_num.values, y_bin.values)
            return est._program
        except Exception as e:
            print(f"Symbolic regression error: {e}")
            return None

    def run_full_analysis(self):
        """تشغيل جميع أنواع التحليلات وتخزين النتائج"""
        X, y = self.prepare_data()
        if X is None:
            return
        results = {}

        # 1. قواعد الارتباط
        assoc_rules = self.run_association_rules(X, y)
        results['association_rules'] = assoc_rules

        # 2. شجرة القرار
        dt_model, dt_rules_text = self.train_decision_tree(X, y)
        results['decision_tree'] = {'model': dt_model, 'rules_text': dt_rules_text}

        # 3. غابة عشوائية + أهمية الميزات
        rf_model, rf_importance = self.train_random_forest(X, y)
        results['random_forest'] = {'model': rf_model, 'importance': rf_importance}

        # 4. انحدار رمزي (اختياري)
        sym_func = self.symbolic_regression(X, y)
        results['symbolic_function'] = sym_func

        self.models = results
        self.last_update = datetime.datetime.now()
        return results

    def generate_report(self) -> str:
        """توليد تقرير بالعربية عن آخر التحليلات"""
        if self.models is None or len(self.models) == 0:
            return "⚠️ لم يتم إجراء أي تحليل بعد."

        report = f"📊 **تقرير HADES X التحليلي**\n"
        report += f"🕐 آخر تحديث: {self.last_update.strftime('%Y-%m-%d %H:%M')}\n"
        report += f"📈 عدد الجولات المحللة: {len(self.df_history) if self.df_history is not None else 0}\n"
        report += "━━━━━━━━━━━━━━━━━━━━\n\n"

        # أهمية الميزات من الغابة العشوائية
        if 'random_forest' in self.models:
            imp = self.models['random_forest']['importance']
            top_features = imp.head(5)
            report += "**🔥 أهم 5 ميزات مؤثرة:**\n"
            for _, row in top_features.iterrows():
                report += f"▪️ {row['feature']}: {row['importance']:.3f}\n"
            report += "\n"

        # قواعد شجرة القرار
        if 'decision_tree' in self.models:
            report += "**🌳 قواعد شجرة القرار (أهم المسارات):**\n"
            rules_text = self.models['decision_tree']['rules_text']
            # نأخذ أول 10 أسطر فقط للتبسيط
            lines = rules_text.split('\n')[:15]
            report += "```\n" + "\n".join(lines) + "\n```\n\n"

        # قواعد الارتباط (أقوى 5)
        if 'association_rules' in self.models and not self.models['association_rules'].empty:
            rules = self.models['association_rules'].sort_values('confidence', ascending=False).head(5)
            report += "**🔗 أقوى قواعد الارتباط:**\n"
            for idx, rule in rules.iterrows():
                antecedents = ', '.join(list(rule['antecedents']))
                consequents = ', '.join(list(rule['consequents']))
                report += f"▪️ إذا {{{antecedents}}} ← {{{consequents}}} (ثقة: {rule['confidence']:.2f})\n"
            report += "\n"

        # توصيات عامة
        report += "**💡 توصيات ذكية:**\n"
        # يمكن إضافة توصيات مبنية على النتائج، مثلاً:
        if 'random_forest' in self.models:
            imp = self.models['random_forest']['importance']
            top_feat = imp.iloc[0]['feature']
            report += f"▪️ الميزة الأكثر تأثيراً هي `{top_feat}`، راقبها.\n"
        report += "▪️ يُنصح باللعب في الأوقات التي يكون فيها النموذج أكثر دقة.\n"
        return report

# ==================== 4. البوت والجدولة ====================
# إنشاء كائن التحليل العام
analytics = HadesXAnalytics()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧠 **HADES X - البوت التحليلي الفائق**\n"
        "يقوم بتحليل قاعدة البيانات باستمرار واستخراج القوانين الرياضية.\n\n"
        "الأوامر:\n"
        "/report - عرض آخر تقرير تحليلي\n"
        "/rules - عرض القوانين المكتشفة\n"
        "/importance - أهم الميزات\n"
        "/force - تشغيل تحليل جديد (للمسؤول)"
    )

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report = analytics.generate_report()
    await update.message.reply_text(report, parse_mode='Markdown')

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if analytics.models and 'decision_tree' in analytics.models:
        rules = analytics.models['decision_tree']['rules_text']
        await update.message.reply_text(f"🌳 **قواعد شجرة القرار:**\n```\n{rules}\n```", parse_mode='Markdown')
    else:
        await update.message.reply_text("⚠️ لا توجد قواعد بعد.")

async def importance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if analytics.models and 'random_forest' in analytics.models:
        imp = analytics.models['random_forest']['importance']
        msg = "🔥 **أهمية الميزات:**\n"
        for _, row in imp.head(10).iterrows():
            msg += f"▪️ {row['feature']}: {row['importance']:.3f}\n"
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("⚠️ لا توجد بيانات.")

async def force_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر للمسؤول فقط.")
        return
    await update.message.reply_text("🔄 جاري تشغيل التحليل...")
    new = analytics.load_new_data()
    if new > 0:
        analytics.run_full_analysis()
        await update.message.reply_text(f"✅ تم تحليل {new} جولة جديدة.")
        # إرسال التقرير للمسؤول
        report = analytics.generate_report()
        await update.message.reply_text(report, parse_mode='Markdown')
    else:
        await update.message.reply_text("ℹ️ لا توجد بيانات جديدة.")

# ==================== 5. المهام الدورية ====================
async def periodic_analysis(app):
    """دالة تُستدعى بشكل دوري لفحص البيانات الجديدة وإجراء التحليل"""
    while True:
        try:
            new_count = analytics.load_new_data()
            if new_count >= 10:
                print(f"🔍 تحليل دوري: {new_count} جولة جديدة.")
                analytics.run_full_analysis()
                # إرسال التقرير إلى المسؤول
                report = analytics.generate_report()
                await app.bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode='Markdown')
            else:
                print(f"⏳ انتظار بيانات جديدة (آخر {new_count} جولة)")
        except Exception as e:
            print(f"❌ خطأ في التحليل الدوري: {e}")
        await asyncio.sleep(3600)  # فحص كل ساعة (يمكن تعديلها)

# ==================== 6. التشغيل الرئيسي ====================
async def post_init(app):
    """بعد بدء البوت، نبدأ المهمة الدورية"""
    asyncio.create_task(periodic_analysis(app))
    print("✅ بدأت المهام الدورية.")

if __name__ == "__main__":
    # تأكد من وجود عمود prediction في history (اختياري)
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("ALTER TABLE history ADD COLUMN IF NOT EXISTS prediction INTEGER;")
        conn.commit()
        cur.close()
        conn.close()
    except:
        pass

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("rules", rules_command))
    app.add_handler(CommandHandler("importance", importance_command))
    app.add_handler(CommandHandler("force", force_analysis))

    print("🚀 HADES X (البوت الفائق) يعمل الآن...")
    app.run_polling()
