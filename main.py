"""
HADES V103 - Advanced AI Analysis & Command Engine (Button-First Edition)
نظام تحليلي ذكي يتجاهل أول 700 جولة (فترة التدفئة)
يعتمد على PostgreSQL + NVIDIA AI للتحليل الدقيق
واجهة تفاعلية تعتمد على الأزرار بدلاً من الدردشة النصية
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

# ==================== 🛡️ الإعدادات الأساسية (كما طلبت - دون تغيير) ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ✅ المفاتيح بقيت كما هي تماماً
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

# 🔄 المفاتيح المحدثة للنموذج الجديد
NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

# ثوابت النظام
WARMUP_ROUNDS = 700
WINNER_MAP = {'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1, 'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

# ==================== 🗄️ إدارة قاعدة البيانات ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def load_filtered_history(min_id: int = WARMUP_ROUNDS + 1) -> pd.DataFrame:
    try:
        conn = get_db_connection()
        query = f"""
            SELECT id, b_num, suit, winner, timestamp, prediction, user_id,
                   final_prediction, gap_pred, math_pred, file_pred, created_at            FROM history 
            WHERE winner IS NOT NULL AND id >= {min_id}
            ORDER BY id ASC
        """
        df = pd.read_sql(query, conn)
        conn.close()
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code'])
        logger.info(f"✅ تم تحميل {len(df)} جولة (بعد تجاهل أول {WARMUP_ROUNDS})")
        return df
    except Exception as e:
        logger.error(f"❌ خطأ في تحميل البيانات: {e}")
        return pd.DataFrame()

def get_latest_stats(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty: return {}
    stats = {
        'total_rounds': len(df),
        'winner_dist': df['winner'].value_counts().to_dict(),
        'suit_dist': df['suit'].value_counts().to_dict(),
        'accuracy': None, 'bias': {}, 'patterns': {}, 'time_analysis': {}
    }
    if 'prediction' in df.columns and df['prediction'].notna().any():
        valid = df[df['prediction'].notna()]
        if len(valid) > 0:
            stats['accuracy'] = float((valid['winner_code'] == valid['prediction']).mean())
    total = len(df)
    stats['bias'] = {
        'red': float((df['winner'] == 'الراعي 🔴').sum() / total),
        'blue': float((df['winner'] == 'الثور 🔵').sum() / total),
        'tie': float((df['winner'] == 'تعادل ⚪').sum() / total)
    }
    suit_winner = {}
    for suit in SUITS:
        subset = df[df['suit'] == suit]
        if len(subset) >= 10:
            top = subset['winner'].value_counts().idxmax()
            freq = subset['winner'].value_counts().max() / len(subset)
            suit_winner[suit] = {'top_winner': top, 'frequency': round(freq, 3)}
    stats['patterns']['suit_winner'] = suit_winner
    df['last_digit'] = df['b_num'].astype(str).str[-1].str.extract('(\d)')
    digit_winner = {}
    for digit in range(10):
        subset = df[df['last_digit'] == str(digit)]
        if len(subset) >= 5:
            top = subset['winner'].value_counts().idxmax()
            digit_winner[str(digit)] = {'top_winner': top, 'count': len(subset)}
    stats['patterns']['last_digit'] = digit_winner
    if 'timestamp' in df.columns and df['timestamp'].notna().any():        df['hour'] = df['timestamp'].dt.hour
        hourly = df.groupby('hour')['winner'].value_counts().unstack(fill_value=0)
        stats['time_analysis']['hourly'] = hourly.to_dict() if not hourly.empty else {}
    return stats

# ==================== 🤖 محرك الذكاء الاصطناعي ====================
class AdvancedAIEngine:
    def __init__(self):
        self.client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
        self.model = NVIDIA_MODEL
    
    def generate_analysis_prompt(self, stats: Dict, df: pd.DataFrame) -> str:
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
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "أجب بصيغة JSON صالحة فقط. لا تضيف أي نص إضافي."},
                    {"role": "user", "content": prompt}                ],
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
    
    def generate_prediction_command(self, df: pd.DataFrame, current_b_num: str, current_suit: str) -> Dict:
        last_20 = df.tail(20) if len(df) >= 20 else df
        recent_winners = last_20['winner'].tolist()
        winner_counts = Counter(recent_winners)
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
            return {
                'prediction': result['prediction'],
                'reason': result.get('reason', ''),
                'confidence': result.get('confidence', 0)
            }
        return {'prediction': '⚠️ تعذر', 'reason': 'خطأ في التحليل', 'confidence': 0}

# ==================== 🎮 معالجات البوت الأساسية (واجهة أزرار) ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر البداية - واجهة أزرار رئيسية"""
    user_id = update.effective_user.id
    df = load_filtered_history()
    stats = get_latest_stats(df) if not df.empty else {}
    
    # زر رئيسي مع ملخص سريع
    kb = [
        [InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")],
        [InlineKeyboardButton("📊 تحليل البيانات", callback_data="view_stats")],        [InlineKeyboardButton("🤖 تنبؤ AI", callback_data="ai_predict")],
        [InlineKeyboardButton("📜 القوانين المكتشفة", callback_data="view_laws")]
    ]
    
    if user_id == ADMIN_ID:
        kb.append([
            InlineKeyboardButton("🎛️ لوحة الأدمن", callback_data="admin_panel"),
            InlineKeyboardButton("📤 تصدير", callback_data="admin_export")
        ])
    
    summary = f"🏛️ **HADES V103**\n📊 جولات: {stats.get('total_rounds', 0)} | 🎯 دقة: {stats.get('accuracy', 'N/A') if stats.get('accuracy') else 'جاري التعلم'}"
    
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار التفاعلية - النظام المركزي"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    
    # === اختيار البذلة ===
    if data == "choose_suit":
        kb = [[InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[:2]],
              [InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[2:]],
              [InlineKeyboardButton("🔙 رجوع", callback_data="start_back")]]
        await query.edit_message_text("🎴 اختر البذلة للبدء:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("s_"):
        suit = data[2:]
        context.user_data['suit'] = suit
        kb = [[InlineKeyboardButton("🔙 رجوع للبذلات", callback_data="choose_suit")]]
        await query.edit_message_text(f"✅ البذلة: {suit}\n📥 أرسل رقم البونص (7+ أرقام) للتحليل:", reply_markup=InlineKeyboardMarkup(kb))
    
    # === عرض الإحصائيات ===
    elif data == "view_stats":
        df = load_filtered_history()
        stats = get_latest_stats(df)
        if not stats:
            await query.answer("❌ لا توجد بيانات", show_alert=True)
            return
        
        report = f"""📊 **إحصائيات HADES V103**
🔢 جولات: {stats.get('total_rounds', 0)}
🏆 توزيع:
• 🔴: {stats['bias'].get('red', 0):.1%}
• 🔵: {stats['bias'].get('blue', 0):.1%}
• ⚪: {stats['bias'].get('tie', 0):.1%}"""
        
        kb = [[InlineKeyboardButton("🔄 تحديث", callback_data="view_stats")],              [InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]]
        await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    # === التنبؤ بالذكاء الاصطناعي ===
    elif data == "ai_predict":
        if 'suit' not in context.user_data:
            await query.answer("⚠️ اختر بذلة أولاً", show_alert=True)
            return
        await query.answer("📥 أرسل رقم البونص الآن", show_alert=True)
        context.user_data['awaiting_bonus'] = True
    
    # === عرض القوانين ===
    elif data == "view_laws":
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT law_name, confidence_score FROM ai_laws WHERE is_active=TRUE ORDER BY confidence_score DESC LIMIT 5")
            laws = cur.fetchall()
            conn.close()
            
            if not laws:
                await query.answer("لا توجد قوانين مكتشفة بعد", show_alert=True)
                return
            
            report = "📜 **أهم 5 قوانين مكتشفة:**\n"
            kb = []
            for i, (name, conf) in enumerate(laws, 1):
                report += f"{i}. {name} (ثقة: {conf:.0%})\n"
                kb.append([InlineKeyboardButton(f"🔍 تفاصيل #{i}", callback_data=f"law_detail_{i}")])
            
            kb.append([InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")])
            await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"❌ خطأ عرض القوانين: {e}")
            await query.answer("خطأ في جلب القوانين", show_alert=True)
    
    # === لوحة الأدمن ===
    elif data == "admin_panel" and user_id == ADMIN_ID:
        kb = [
            [InlineKeyboardButton("📊 تحليل شامل", callback_data="admin_analyze")],
            [InlineKeyboardButton("🔄 إعادة تحميل البيانات", callback_data="admin_reload")],
            [InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]
        ]
        await query.edit_message_text("🎛️ **لوحة تحكم الأدمن**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "admin_analyze" and user_id == ADMIN_ID:
        await query.edit_message_text("🔄 جاري التحليل...")
        df = load_filtered_history()
        stats = get_latest_stats(df)        ai_engine = AdvancedAIEngine()
        
        if stats:
            report = f"""📊 **تحليل شامل**
• جولات: {stats.get('total_rounds', 0)}
• دقة: {stats.get('accuracy', 'N/A')}
• انحياز 🔴: {stats['bias'].get('red', 0):.1%}"""
            
            # تحليل AI إضافي
            ai_prompt = ai_engine.generate_analysis_prompt(stats, df)
            ai_result = ai_engine.ask_json(ai_prompt)
            if ai_result and ai_result.get('next_round_strategy'):
                report += f"\n\n🤖 **توصية AI:**\n{ai_result['next_round_strategy']}"
            
            kb = [[InlineKeyboardButton("🔄 تحديث", callback_data="admin_analyze")],
                  [InlineKeyboardButton("🔙 لوحة الأدمن", callback_data="admin_panel")]]
            await query.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "admin_export" and user_id == ADMIN_ID:
        await export_laws_command(update, context)
        await query.answer("✅ تم بدء التصدير", show_alert=True)
    
    elif data == "admin_reload" and user_id == ADMIN_ID:
        # إعادة تحميل البيانات من القاعدة
        context.user_data.pop('suit', None)
        context.user_data.pop('last_b', None)
        await query.answer("✅ تم إعادة التحميل", show_alert=True)
        await start(update, context)
    
    # === الرجوع ===
    elif data == "start_back":
        await start(update, context)
    
    # === حفظ النتيجة (من أزرار التنبؤ) ===
    elif data.startswith("save_"):
        parts = data.split("_")
        if len(parts) >= 4:
            b_num = parts[1]
            suit = parts[2]
            winner = "_".join(parts[3:])
            
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO history (b_num, suit, winner, timestamp, prediction, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (b_num, suit, winner, datetime.datetime.now(), 
                      WINNER_MAP.get(winner.split()[0], -1), user_id))
                conn.commit()                conn.close()
                
                kb = [[InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")]]
                await query.edit_message_text(f"✅ سُجّل: {winner}\n🔄 جاهز للجولة التالية:", reply_markup=InlineKeyboardMarkup(kb))
                
            except Exception as e:
                logger.error(f"❌ خطأ الحفظ: {e}")
                await query.answer("❌ خطأ في الحفظ", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل - يحول المدخلات إلى تفاعل بالأزرار"""
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # === حالة انتظار رقم البونص ===
    if context.user_data.get('awaiting_bonus') and text.isdigit() and len(text) >= 7:
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
        result = ai_engine.generate_prediction_command(df, text, suit)
        
        # عرض التنبؤ كأزرار بدلاً من نص
        prediction = result['prediction']
        reason = result['reason']
        confidence = result['confidence']
        
        report = f"""🎯 **تنبؤ HADES V103**
🏆 النتيجة: **{prediction}**
📋 السبب: {reason}
📊 الثقة: {confidence:.0%}
🎴 البذلة: {suit}"""
        
        # أزرار تسجيل النتيجة
        kb = [
            [InlineKeyboardButton("🔴 راعي", callback_data=f"save_{text}_{suit}_الراعي 🔴"),
             InlineKeyboardButton("🔵 ثور", callback_data=f"save_{text}_{suit}_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data=f"save_{text}_{suit}_تعادل ⚪")],
            [InlineKeyboardButton("🔄 تحليل جديد", callback_data="ai_predict")]
        ]
                await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        context.user_data['awaiting_bonus'] = False
        return
    
    # === أوامر سريعة عبر نص ===
    if text.lower() in ['تحليل', 'stats', '/analyze']:
        if user_id == ADMIN_ID:
            await analyze_command(update, context)
        else:
            await update.message.reply_text("❌ هذا الأمر للأدمن فقط")
        return
    
    if text.lower() in ['خروج', 'exit', 'back', '/start']:
        context.user_data.clear()
        await start(update, context)
        return
    
    # === رد افتراضي بأزرار التوجيه ===
    kb = [
        [InlineKeyboardButton("🎴 البدء", callback_data="choose_suit")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="view_stats")],
        [InlineKeyboardButton("🤖 تنبؤ AI", callback_data="ai_predict")]
    ]
    await update.message.reply_text("🏛️ **HADES V103**\nاختر من القائمة للبدء:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# ==================== 📊 أوامر الأدمن (تبقى نصية للإدارة) ====================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ للأدمن فقط")
        return
    
    df = load_filtered_history()
    if df.empty:
        await update.message.reply_text("❌ لا توجد بيانات")
        return
    
    stats = get_latest_stats(df)
    report = f"""📊 **تقرير HADES V103**
🔢 جولات: {stats.get('total_rounds', 0)}
🏆 🔴:{stats['bias'].get('red',0):.1%} 🔵:{stats['bias'].get('blue',0):.1%} ⚪:{stats['bias'].get('tie',0):.1%}
🎯 دقة: {stats.get('accuracy', 'N/A')}"""
    
    kb = [[InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]]
    await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def export_laws_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ للأدمن فقط")
        return
    try:        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT law_name, confidence_score FROM ai_laws WHERE is_active=TRUE ORDER BY confidence_score DESC LIMIT 10")
        laws = cur.fetchall()
        conn.close()
        
        report = "📜 **القوانين النشطة:**\n" + "\n".join([f"• {name} ({conf:.0%})" for name, conf in laws])
        await update.message.reply_text(report)
    except Exception as e:
        logger.error(f"❌ خطأ التصدير: {e}")
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 🚀 التشغيل الرئيسي ====================
if __name__ == "__main__":
    logger.info("🚀 بدء HADES V103 - واجهة الأزرار")
    
    try:
        df = load_filtered_history()
        if not df.empty:
            stats = get_latest_stats(df)
            logger.info(f"✅ جاهز: {stats.get('total_rounds', 0)} جولة | 🔴{stats['bias'].get('red',0):.1%} 🔵{stats['bias'].get('blue',0):.1%}")
    except Exception as e:
        logger.warning(f"⚠️ تحذير التهيئة: {e}")
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # تسجيل المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("export_laws", export_laws_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ البوت جاهز - واجهة الأزرار مفعلة")
    app.run_polling(drop_pending_updates=True)
