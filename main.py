"""
HADES V103 - Advanced AI Analysis & Command Engine
نظام تحليلي ذكي يتجاهل أول 700 جولة (فترة التدفئة)
يعتمد على PostgreSQL + NVIDIA AI للتحليل الدقيق
"""

import os, sys, datetime, psycopg2, pandas as pd, numpy as np
import json, re, logging, random, secrets
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
from collections import Counter, defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, JobQueue
)
from openai import OpenAI

# ==================== 🛡️ الإعدادات الأساسية ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ✅ تم إدخال المفاتيح مباشرة كما طلبت
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

# 🔄 تم التحديث إلى المفتاح والنموذج الجديدين (minimax-m2.5)
NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

# ثوابت النظام
WARMUP_ROUNDS = 700  # عدد الجولات التي سيتم تجاهلها
WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

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
        
        # تنظيف البيانات
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
        'suit_dist': df['suit'].value_counts().to_dict(),
        'accuracy': None,
        'bias': {},
        'patterns': {},
        'time_analysis': {}
    }
    
    # دقة التنبؤ (إذا كانت البيانات متوفرة)
    if 'prediction' in df.columns and df['prediction'].notna().any():
        valid = df[df['prediction'].notna()]
        if len(valid) > 0:
            stats['accuracy'] = float((valid['winner_code'] == valid['prediction']).mean())
    
    # تحليل الانحياز
    total = len(df)
    stats['bias'] = {
        'red': float((df['winner'] == 'الراعي 🔴').sum() / total),
        'blue': float((df['winner'] == 'الثور 🔵').sum() / total),
        'tie': float((df['winner'] == 'تعادل ⚪').sum() / total)
    }
    
    # أنماط البذلة-النتيجة
    suit_winner = {}
    for suit in SUITS:
        subset = df[df['suit'] == suit]
        if len(subset) >= 10:
            top = subset['winner'].value_counts().idxmax()
            freq = subset['winner'].value_counts().max() / len(subset)
            suit_winner[suit] = {'top_winner': top, 'frequency': round(freq, 3)}
    stats['patterns']['suit_winner'] = suit_winner
    
    # تحليل الرقم الأخير
    df['last_digit'] = df['b_num'].astype(str).str[-1].str.extract('(\d)')
    digit_winner = {}
    for digit in range(10):
        subset = df[df['last_digit'] == str(digit)]
        if len(subset) >= 5:
            top = subset['winner'].value_counts().idxmax()
            digit_winner[str(digit)] = {'top_winner': top, 'count': len(subset)}
    stats['patterns']['last_digit'] = digit_winner
    
    # تحليل زمني
    if 'timestamp' in df.columns and df['timestamp'].notna().any():
        df['hour'] = df['timestamp'].dt.hour
        hourly = df.groupby('hour')['winner'].value_counts().unstack(fill_value=0)
        stats['time_analysis']['hourly'] = hourly.to_dict() if not hourly.empty else {}
    
    return stats

# ==================== 🤖 محرك الذكاء الاصطناعي ====================
class AdvancedAIEngine:
    def __init__(self):
        self.client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
        self.model = NVIDIA_MODEL
    
    def generate_analysis_prompt(self, stats: Dict, df: pd.DataFrame) -> str:
        """إنشاء برومبت تحليلي دقيق للذكاء الاصطناعي"""
        prompt = f"""أنت خبير تحليل بيانات ألعاب تنبؤية.

📊 إحصائيات البيانات (بعد تجاهل أول {WARMUP_ROUNDS} جولة):
- إجمالي الجولات المحللة: {stats.get('total_rounds', 0)}
- توزيع النتائج: {stats.get('winner_dist', {})}
- دقة التنبؤ السابقة: {stats.get('accuracy', 'N/A')}
- الانحياز: أحمر={stats.get('bias', {}).get('red', 0):.1%}، أزرق={stats.get('bias', {}).get('blue', 0):.1%}، تعادل={stats.get('bias', {}).get('tie', 0):.1%}

🔍 أنماط البذلات:
{json.dumps(stats.get('patterns', {}).get('suit_winner', {}), ensure_ascii=False, indent=2)}

🔢 أنماط الأرقام الأخيرة:
{json.dumps({k: v for k, v in list(stats.get('patterns', {}).get('last_digit', {}).items())[:5]}, ensure_ascii=False, indent=2)}

المطلوب:
1️⃣ استخرج 3-5 قوانين تنبؤية جديدة بناءً على هذه البيانات
2️⃣ لكل قانون: اسم، شرط التطبيق، الإجراء المتوقع، مستوى الثقة (0.0-1.0)
3️⃣ اقترح تعديلات على أوزان المعادلة الحالية إذا لزم الأمر
4️⃣ حدد أفضل استراتيجية للتنبؤ بالجولة القادمة
أجب بصيغة JSON فقط بهذا الهيكل:
{{
    "new_laws": [
        {{"name": "اسم_القانون", "condition": "شرط_التطبيق", "action": "الإجراء", "confidence": 0.XX}}
    ],
    "config_suggestions": {{"SETTING_NAME": new_value}},
    "next_round_strategy": "استراتيجية مختصرة للجولة القادمة",
    "confidence_level": "high/medium/low"
}}"""
        return prompt
    
    def ask_json(self, prompt: str, temperature: float = 0.2) -> Optional[Dict]:
        """إرسال طلب والحصول على رد JSON"""
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
    
    def generate_prediction_command(self, df: pd.DataFrame, current_b_num: str, current_suit: str) -> str:
        """إنشاء أمر تنبؤ دقيق للجولة الحالية"""
        # تحليل السياق الحالي
        last_20 = df.tail(20) if len(df) >= 20 else df
        recent_winners = last_20['winner'].tolist()
        winner_counts = Counter(recent_winners)
        
        # تحليل الرقم الأخير والبذلة
        last_digit = current_b_num[-1] if current_b_num and current_b_num[-1].isdigit() else '0'
        
        prompt = f"""أنت نظام تنبؤ ذكي. البيانات المتاحة:

📈 آخر 20 نتيجة: {recent_winners[-10:]}
📊 التكرار الأخير: {dict(winner_counts)}
🎯 الجولة الحالية: رقم={current_b_num}, بذلة={current_suit}, آخر_رقم={last_digit}
⚙️ انحياز عام: أحمر={winner_counts.get('الراعي 🔴', 0)/len(recent_winners):.1% if recent_winners else 0}

المطلوب: أعطِ تنبؤاً واحداً للجولة الحالية مع سبب منطقي مختصر.
أجب بصيغة JSON:
{{"prediction": "الراعي 🔴" أو "الثور 🔵" أو "تعادل ⚪", "reason": "سبب مختصر", "confidence": 0.XX}}"""
        
        result = self.ask_json(prompt)
        if result and 'prediction' in result:
            return f"🎯 {result['prediction']}\n📋 {result.get('reason', '')}\n📊 ثقة: {result.get('confidence', 0):.0%}"
        return "⚠️ تعذر توليد تنبؤ دقيق"

# ==================== 📊 أوامر التحليل للإدارة ====================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/analyze - أمر تحليل شامل (للأدمن فقط)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ هذا الأمر للأدمن فقط")
        return
    
    await update.message.reply_text("🔄 جاري تحليل البيانات (يتجاهل أول 700 جولة)...")
    
    df = load_filtered_history()
    if df.empty:
        await update.message.reply_text("❌ لا توجد بيانات كافية للتحليل")
        return
    
    stats = get_latest_stats(df)
    ai_engine = AdvancedAIEngine()
    
    # توليد تقرير تحليلي
    report = f"""📊 **تقرير HADES V103 التحليلي**

🔢 البيانات المحللة: {stats.get('total_rounds', 0)} جولة (بعد استبعاد أول {WARMUP_ROUNDS})

🏆 توزيع النتائج:
"""
    for winner, count in stats.get('winner_dist', {}).items():
        pct = count / stats.get('total_rounds', 1) * 100
        report += f"• {winner}: {count} ({pct:.1%})\n"
    
    report += f"\n⚖️ الانحياز المكتشف:\n"
    bias = stats.get('bias', {})
    report += f"• 🔴 أحمر: {bias.get('red', 0):.1%}\n"
    report += f"• 🔵 أزرق: {bias.get('blue', 0):.1%}\n"
    report += f"• ⚪ تعادل: {bias.get('tie', 0):.1%}\n"
    
    # أنماط البذلات
    suit_patterns = stats.get('patterns', {}).get('suit_winner', {})
    if suit_patterns:
        report += f"\n🎴 أنماط البذلات:\n"
        for suit, data in suit_patterns.items():
            report += f"• {suit} → {data['top_winner']} ({data['frequency']:.0%})\n"
        await update.message.reply_text(report, parse_mode='Markdown')
    
    # طلب تحليل AI متقدم
    ai_prompt = ai_engine.generate_analysis_prompt(stats, df)
    ai_result = ai_engine.ask_json(ai_prompt)
    
    if ai_result:
        ai_report = f"\n🤖 **تحليل الذكاء الاصطناعي:**\n"
        if ai_result.get('new_laws'):
            ai_report += "📜 قوانين جديدة مقترحة:\n"
            for law in ai_result['new_laws'][:3]:
                ai_report += f"• {law['name']}: {law['condition']} → {law['action']} (ثقة: {law['confidence']:.0%})\n"
        
        if ai_result.get('config_suggestions'):
            ai_report += f"\n⚙️ اقتراحات الإعدادات:\n"
            for key, val in ai_result['config_suggestions'].items():
                ai_report += f"• {key}: {val}\n"
        
        if ai_result.get('next_round_strategy'):
            ai_report += f"\n🎯 استراتيجية الجولة القادمة:\n{ai_result['next_round_strategy']}"
        
        await update.message.reply_text(ai_report, parse_mode='Markdown')

async def predict_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/predict <bonus_number> <suit> - تنبؤ دقيق للجولة الحالية"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ هذا الأمر للأدمن فقط")
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("⚠️ الاستخدام: /predict <رقم_البونص> <البذلة>\nمثال: /predict 7256327 ♦️")
        return
    
    b_num, suit = args[0], args[1]
    
    await update.message.reply_text(f"🔄 جاري تحليل الجولة: {b_num} | {suit}")
    
    df = load_filtered_history()
    if df.empty:
        await update.message.reply_text("❌ لا توجد بيانات كافية")
        return
    
    ai_engine = AdvancedAIEngine()
    prediction = ai_engine.generate_prediction_command(df, b_num, suit)
    
    await update.message.reply_text(f"🎯 **تنبؤ HADES V103**\n\n{prediction}", parse_mode='Markdown')

async def export_laws_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/export_laws - تصدير القوانين المكتشفة كملف JSON"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ للأدمن فقط")
        return
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT law_name, law_description, law_pattern, confidence_score, success_rate, is_active
            FROM ai_laws WHERE is_active = TRUE ORDER BY confidence_score DESC
        """)
        laws = []
        for row in cur.fetchall():
            laws.append({
                'name': row[0],
                'description': row[1],
                'pattern': row[2],
                'confidence': row[3],
                'success_rate': row[4],
                'active': row[5]
            })
        conn.close()
        
        # حفظ في ملف
        output_file = f"hades_laws_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(laws, f, ensure_ascii=False, indent=2)
        
        await update.message.reply_text(f"✅ تم تصدير {len(laws)} قانون إلى `{output_file}`")
        
        # إرسال الملف إذا كان صغيراً
        if os.path.getsize(output_file) < 50 * 1024 * 1024:  # <50MB
            await update.message.reply_document(document=open(output_file, 'rb'), filename=output_file)
            
    except Exception as e:
        logger.error(f"❌ خطأ في التصدير: {e}")
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 🎮 معالجات البوت الأساسية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر البداية مع عرض حالة التحليل"""
    user_id = update.effective_user.id
    
    # عرض حالة النظام
    df = load_filtered_history()
    stats = get_latest_stats(df) if not df.empty else {}
    
    status_msg = f"""🏛️ **HADES V103 - نظام التحليل المتقدم**

📊 حالة البيانات:
• جولات محللة: {stats.get('total_rounds', 0)} (بعد استبعاد أول {WARMUP_ROUNDS})
• دقة النظام: {stats.get('accuracy', 'N/A') if stats.get('accuracy') else 'جاري التعلم'}

🎮 الأوامر المتاحة:
• /analyze - تقرير تحليلي شامل
• /predict <رقم> <بذلة> - تنبؤ دقيق
• /export_laws - تصدير القوانين (أدمن)
• /start - العودة للرئيسية

🎴 اختر بذلة للبدء:"""
    
    kb = [[InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[:2]],
          [InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[2:]],
          [InlineKeyboardButton("🤖 دردشة AI", callback_data="ai_chat")]]
    
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("📊 لوحة التحكم", callback_data="admin_panel")])
    
    await update.message.reply_text(status_msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار التفاعلية"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("s_"):
        suit = query.data[2:]
        context.user_data['suit'] = suit
        await query.edit_message_text(f"✅ البذلة: {suit}\n📥 أرسل رقم البونص (7+ أرقام) للتحليل:")
    
    elif query.data == "ai_chat":
        context.user_data['mode'] = "AI"
        await query.edit_message_text("🤖 **وضع التحليل الذكي**\nاكتب سؤالك أو 'خروج' للعودة:")
    
    elif query.data == "admin_panel" and update.effective_user.id == ADMIN_ID:
        kb = [[InlineKeyboardButton("📊 تحليل", callback_data="admin_analyze")],
              [InlineKeyboardButton("📤 تصدير", callback_data="admin_export")],
              [InlineKeyboardButton("🔙 رجوع", callback_data="start_back")]]
        await query.edit_message_text("🎛️ **لوحة تحكم الأدمن**\nاختر إجراء:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif query.data == "admin_analyze" and update.effective_user.id == ADMIN_ID:
        await query.edit_message_text("🔄 جاري التحليل...")
        df = load_filtered_history()
        stats = get_latest_stats(df)
        summary = f"📈 **ملخص سريع**\n• جولات: {stats.get('total_rounds', 0)}\n• انحياز أحمر: {stats.get('bias', {}).get('red', 0):.1%}\n• انحياز أزرق: {stats.get('bias', {}).get('blue', 0):.1%}"
        await query.message.reply_text(summary, parse_mode='Markdown')
    
    elif query.data == "admin_export" and update.effective_user.id == ADMIN_ID:
        await export_laws_command(update, context)
    
    elif query.data == "start_back":
        await start(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل النصية"""
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # وضع الدردشة مع AI
    if context.user_data.get('mode') == "AI":
        if text.lower() in ['exit', 'خروج', 'رجوع', 'back', '/start']:
            context.user_data['mode'] = None
            await update.message.reply_text("🔙 تم الخروج من وضع التحليل")
            return
        
        # تحليل سؤال المستخدم باستخدام البيانات
        df = load_filtered_history()
        if df.empty:
            await update.message.reply_text("❌ لا توجد بيانات للتحليل")
            return
        
        ai_engine = AdvancedAIEngine()
        prompt = f"""المستخدم يسأل: "{text}"

بيانات النظام (بعد تجاهل أول {WARMUP_ROUNDS} جولة):
- إجمالي الجولات: {len(df)}
- النتائج الأخيرة: {df['winner'].tail(10).tolist()}
- البذلات النشطة: {df['suit'].value_counts().to_dict()}

أجب بإجابة تحليلية مختصرة ومفيدة بالعربية."""
        
        try:
            response = ai_engine.client.chat.completions.create(
                model=ai_engine.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=1000
            )
            answer = response.choices[0].message.content
            await update.message.reply_text(f"🤖 **HADES AI:**\n\n{answer}", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ في التحليل: {e}")
        return
    
    # معالجة رقم البونص للتحليل
    if text.isdigit() and len(text) >= 7:
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
        prediction = ai_engine.generate_prediction_command(df, text, suit)
        
        kb = [[InlineKeyboardButton("🔴 راعي", callback_data=f"save_{text}_{suit}_الراعي 🔴")],
              [InlineKeyboardButton("🔵 ثور", callback_data=f"save_{text}_{suit}_الثور 🔵")],
              [InlineKeyboardButton("⚪ تعادل", callback_data=f"save_{text}_{suit}_تعادل ⚪")]]
        
        await update.message.reply_text(
            f"🎯 **نتيجة التحليل**\n\n{prediction}\n\n📝 سجل النتيجة الفعلية:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("⚠️ أدخل رقم بونص صحيح (7+ أرقام) أو استخدم /help")

# ==================== 🚀 التشغيل الرئيسي ====================
if __name__ == "__main__":
    logger.info("🚀 بدء HADES V103 - محرك التحليل المتقدم")
    
    # تهيئة الاتصال والتحقق من البيانات
    try:
        df = load_filtered_history()
        if not df.empty:
            stats = get_latest_stats(df)
            logger.info(f"✅ جاهز: {stats.get('total_rounds', 0)} جولة محللة")
            logger.info(f"📊 الانحياز: 🔴{stats.get('bias', {}).get('red', 0):.1%} 🔵{stats.get('bias', {}).get('blue', 0):.1%}")
    except Exception as e:
        logger.warning(f"⚠️ تحذير في التهيئة: {e}")
    
    # بناء التطبيق
    app = ApplicationBuilder().token(TOKEN).build()
    
    # تسجيل المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("predict", predict_command))
    app.add_handler(CommandHandler("export_laws", export_laws_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ البوت جاهز للاستقبال")
    app.run_polling(drop_pending_updates=True)
