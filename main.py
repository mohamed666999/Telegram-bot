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
import gplearn.genetic as gpl
from mlxtend.frequent_patterns import apriori, association_rules

# -------------------- مكتبات البوت --------------------
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

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
        self.df_history = None
        self.last_analyzed_id = 0
        self.rules = []
        self.models = {}
        self.symbolic_functions = []
        self.last_update = None

    def load_new_data(self) -> int:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql(f"SELECT * FROM history WHERE id > {self.last_analyzed_id} ORDER BY id", conn)
        conn.close()
        if df.empty:
            return 0
        if self.df_history is not None:
            self.df_history = pd.concat([self.df_history, df], ignore_index=True).tail(500)
        else:
            self.df_history = df.tail(500)
        new_count = len(df)
        self.last_analyzed_id = self.df_history['id'].max()
        return new_count

    def prepare_data(self):
        if self.df_history is None or len(self.df_history) < 30:
            return None, None
        df = self.df_history.copy()
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
        df_feat = pd.DataFrame(rows).dropna()
        X = df_feat.drop('winner', axis=1)
        y = df_feat['winner']
        return X, y

    def run_association_rules(self, X, y, min_support=0.1, min_threshold=0.6):
        df_temp = X.copy()
        df_temp['winner'] = y
        df_disc = df_temp.copy()
        for col in df_disc.columns:
            if col in ['hour', 'b_num_len', 'b_num_sum', 'b_num_avg', 'b_num_max', 'b_num_min', 'last_digit', 'even_digits_count', 'odd_digits_count']:
                df_disc[col] = pd.cut(df_disc[col], bins=5, labels=False)
            else:
                df_disc[col] = df_disc[col].astype(str)
        df_encoded = pd.get_dummies(df_disc)
        try:
            frequent_itemsets = apriori(df_encoded, min_support=min_support, use_colnames=True)
            rules = association_rules(frequent_itemsets, metric="confidence", min_threshold=min_threshold)
            rules_with_winner = rules[rules['consequents'].apply(lambda x: any('winner' in str(i) for i in x))]
            return rules_with_winner
        except:
            return pd.DataFrame()

    def train_decision_tree(self, X, y, max_depth=4):
        clf = DecisionTreeClassifier(max_depth=max_depth, random_state=42)
        clf.fit(X, y)
        rules_text = export_text(clf, feature_names=list(X.columns))
        return clf, rules_text

    def train_random_forest(self, X, y):
        rf = RandomForestClassifier(n_estimators=100, random_state=42)
        rf.fit(X, y)
        importance = pd.DataFrame({'feature': X.columns, 'importance': rf.feature_importances_}).sort_values('importance', ascending=False)
        return rf, importance

    def symbolic_regression(self, X, y):
        try:
            numeric_cols = ['b_num_len', 'b_num_sum', 'b_num_avg', 'b_num_max', 'b_num_min', 'last_digit', 'even_digits_count', 'odd_digits_count', 'hour']
            X_num = X[numeric_cols].fillna(0)
            y_bin = (y == 1).astype(int)
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
        X, y = self.prepare_data()
        if X is None:
            return
        results = {}
        assoc_rules = self.run_association_rules(X, y)
        results['association_rules'] = assoc_rules
        dt_model, dt_rules_text = self.train_decision_tree(X, y)
        results['decision_tree'] = {'model': dt_model, 'rules_text': dt_rules_text}
        rf_model, rf_importance = self.train_random_forest(X, y)
        results['random_forest'] = {'model': rf_model, 'importance': rf_importance}
        sym_func = self.symbolic_regression(X, y)
        results['symbolic_function'] = sym_func
        self.models = results
        self.last_update = datetime.datetime.now()
        return results

    def generate_report(self) -> str:
        if self.models is None or len(self.models) == 0:
            return "⚠️ لم يتم إجراء أي تحليل بعد."
        report = f"📊 **تقرير HADES X التحليلي**\n"
        report += f"🕐 آخر تحديث: {self.last_update.strftime('%Y-%m-%d %H:%M')}\n"
        report += f"📈 عدد الجولات المحللة: {len(self.df_history) if self.df_history is not None else 0}\n"
        report += "━━━━━━━━━━━━━━━━━━━━\n\n"
        if 'random_forest' in self.models:
            imp = self.models['random_forest']['importance']
            top_features = imp.head(5)
            report += "**🔥 أهم 5 ميزات مؤثرة:**\n"
            for _, row in top_features.iterrows():
                report += f"▪️ {row['feature']}: {row['importance']:.3f}\n"
            report += "\n"
        if 'decision_tree' in self.models:
            report += "**🌳 قواعد شجرة القرار (أهم المسارات):**\n"
            rules_text = self.models['decision_tree']['rules_text']
            lines = rules_text.split('\n')[:15]
            report += "```\n" + "\n".join(lines) + "\n```\n\n"
        if 'association_rules' in self.models and not self.models['association_rules'].empty:
            rules = self.models['association_rules'].sort_values('confidence', ascending=False).head(5)
            report += "**🔗 أقوى قواعد الارتباط:**\n"
            for idx, rule in rules.iterrows():
                antecedents = ', '.join(list(rule['antecedents']))
                consequents = ', '.join(list(rule['consequents']))
                report += f"▪️ إذا {{{antecedents}}} ← {{{consequents}}} (ثقة: {rule['confidence']:.2f})\n"
            report += "\n"
        report += "**💡 توصيات ذكية:**\n"
        if 'random_forest' in self.models:
            imp = self.models['random_forest']['importance']
            top_feat = imp.iloc[0]['feature']
            report += f"▪️ الميزة الأكثر تأثيراً هي `{top_feat}`، راقبها.\n"
        report += "▪️ يُنصح باللعب في الأوقات التي يكون فيها النموذج أكثر دقة.\n"
        return report

analytics = HadesXAnalytics()

# ==================== 4. دوال البوت التفاعلية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض أزرار اختيار البذلة"""
    keyboard = [
        [InlineKeyboardButton("♦️", callback_data="suit_♦️"),
         InlineKeyboardButton("♥️", callback_data="suit_♥️")],
        [InlineKeyboardButton("♠️", callback_data="suit_♠️"),
         InlineKeyboardButton("♣️", callback_data="suit_♣️")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🧠 **HADES X - البوت التحليلي الفائق**\n"
        "اختر نوع الورق لبدء جولة جديدة:\n\n"
        "الأوامر الأخرى:\n"
        "/report - عرض آخر تقرير تحليلي\n"
        "/rules - عرض القوانين المكتشفة\n"
        "/importance - أهم الميزات\n"
        "/force - تشغيل تحليل جديد (للمسؤول)",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def suit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تسجيل اختيار البذلة وطلب رقم البونص"""
    query = update.callback_query
    await query.answer()
    suit = query.data.split('_')[1]  # مثلاً suit_♦️ -> ♦️
    context.user_data['suit'] = suit
    await query.edit_message_text(
        f"✅ تم اختيار: {suit}\n"
        "الآن أرسل رقم البونص (مكون من 7 أرقام على الأقل):"
    )

async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال رقم البونص"""
    if 'suit' not in context.user_data:
        await update.message.reply_text("⚠️ عليك اختيار نوع الورق أولاً عبر /start.")
        return
    text = update.message.text.strip()
    if not text.isdigit() or len(text) < 7:
        await update.message.reply_text("❌ الرقم يجب أن يتكون من 7 أرقام على الأقل وبدون أحرف.")
        return
    # تنظيف بيانات التوقع السابقة
    context.user_data.pop('prediction', None)
    # حساب التوقع البسيط (مثال: مجموع الأرقام زوجي -> ثور)
    total = sum(int(d) for d in text)
    pred = 1 if total % 2 == 0 else 0
    pred_text = WINNER_NAMES[pred]
    context.user_data['b_num'] = text
    context.user_data['prediction'] = pred
    # أزرار النتيجة
    keyboard = [
        [InlineKeyboardButton("🔴 الراعي", callback_data="win_الراعي 🔴"),
         InlineKeyboardButton("🔵 الثور", callback_data="win_الثور 🔵")],
        [InlineKeyboardButton("⚪ تعادل", callback_data="win_تعادل ⚪")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🎯 **توقع النموذج:** {pred_text}\n"
        f"🔢 الرقم: {text}\n"
        "بعد انتهاء الجولة، اختر النتيجة الفعلية:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def win_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تسجيل النتيجة الفعلية وحفظها في قاعدة البيانات"""
    query = update.callback_query
    await query.answer()
    winner_name = query.data.split('_', 1)[1]  # مثلاً win_الراعي 🔴 -> الراعي 🔴
    winner_code = WINNER_MAP.get(winner_name, 2)

    b_num = context.user_data.get('b_num')
    suit = context.user_data.get('suit')
    pred = context.user_data.get('prediction')
    user_id = update.effective_user.id

    if not b_num or not suit or pred is None:
        await query.edit_message_text("❌ حدث خطأ في بيانات الجولة. ابدأ من جديد.")
        return

    # حفظ في قاعدة البيانات
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO history (b_num, suit, winner, timestamp, prediction, user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (b_num, suit, winner_name, datetime.datetime.now(), pred, user_id))
        conn.commit()
        cur.close()
        conn.close()
        # عرض نتيجة التوقع
        pred_winner = WINNER_NAMES[pred]
        is_correct = "✅" if winner_name == pred_winner else "❌"
        # أزرار إضافية
        keyboard = [
            [InlineKeyboardButton("🔄 بدء جولة جديدة", callback_data="new_round"),
             InlineKeyboardButton("🗑️ حذف آخر إدخال", callback_data="delete_last")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"{is_correct} **تم الحفظ**\n\n"
            f"🎯 توقعنا: {pred_winner}\n"
            f"🏆 النتيجة الفعلية: {winner_name}",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        await query.edit_message_text(f"❌ خطأ في الحفظ: {e}")

async def delete_last_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف آخر إدخال للمستخدم الحالي"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT id FROM history WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM history WHERE id = %s", (row[0],))
            conn.commit()
            await query.edit_message_text("🗑️ تم حذف آخر إدخال لك.")
        else:
            await query.edit_message_text("⚠️ لا يوجد إدخال سابق لك.")
        cur.close()
        conn.close()
    except Exception as e:
        await query.edit_message_text(f"❌ خطأ: {e}")

async def new_round_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء جولة جديدة عبر زر"""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("♦️", callback_data="suit_♦️"),
         InlineKeyboardButton("♥️", callback_data="suit_♥️")],
        [InlineKeyboardButton("♠️", callback_data="suit_♠️"),
         InlineKeyboardButton("♣️", callback_data="suit_♣️")]
    ]
    await query.edit_message_text(
        "🔄 **جولة جديدة**\nاختر نوع الورق:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ==================== 5. أوامر التحليل (كما هي) ====================
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
        report = analytics.generate_report()
        await update.message.reply_text(report, parse_mode='Markdown')
    else:
        await update.message.reply_text("ℹ️ لا توجد بيانات جديدة.")

# ==================== 6. المهام الدورية ====================
async def periodic_analysis(app):
    while True:
        try:
            new_count = analytics.load_new_data()
            if new_count >= 10:
                print(f"🔍 تحليل دوري: {new_count} جولة جديدة.")
                analytics.run_full_analysis()
                report = analytics.generate_report()
                await app.bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode='Markdown')
            else:
                print(f"⏳ انتظار بيانات جديدة (آخر {new_count} جولة)")
        except Exception as e:
            print(f"❌ خطأ في التحليل الدوري: {e}")
        await asyncio.sleep(3600)

async def post_init(app):
    asyncio.create_task(periodic_analysis(app))
    print("✅ بدأت المهام الدورية.")

# ==================== 7. التشغيل الرئيسي ====================
if __name__ == "__main__":
    # التأكد من وجود الأعمدة
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("ALTER TABLE history ADD COLUMN IF NOT EXISTS prediction INTEGER;")
        cur.execute("ALTER TABLE history ADD COLUMN IF NOT EXISTS user_id BIGINT;")
        # إضافة created_at لتسهيل التحليل الزمني
        cur.execute("ALTER TABLE history ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();")
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"⚠️ تحذير: {e}")

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    # أوامر التحليل
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("rules", rules_command))
    app.add_handler(CommandHandler("importance", importance_command))
    app.add_handler(CommandHandler("force", force_analysis))

    # معالجات الأزرار والرسائل
    app.add_handler(CallbackQueryHandler(suit_callback, pattern="^suit_"))
    app.add_handler(CallbackQueryHandler(win_callback, pattern="^win_"))
    app.add_handler(CallbackQueryHandler(delete_last_callback, pattern="^delete_last$"))
    app.add_handler(CallbackQueryHandler(new_round_callback, pattern="^new_round$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_number))

    print("🚀 HADES X Stable يعمل الآن مع أزرار تفاعلية...")
    app.run_polling()
