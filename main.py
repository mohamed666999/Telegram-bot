"""
HADES V103 - Advanced AI Analysis & Command Engine
نظام تنبؤ هجين: معادلة رياضية + تحليل بايزي + NVIDIA AI + قوانين ذكية
يعمل على Railway مع PostgreSQL - واجهة أزرار تفاعلية كاملة
"""

import os, sys, datetime, psycopg2, pandas as pd, numpy as np
import json, re, logging, random, secrets, asyncio
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, JobQueue
)
from openai import OpenAI

# ==================== 🛡️ الإعدادات الأساسية ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ✅ المفاتيح - كما طلبت تبقى كما هي
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

# ثوابت النظام
WARMUP_ROUNDS = 700
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

DYNAMIC_CONFIG = {
    'CONFIDENCE_THRESHOLD': 0.65, 'MATH_WEIGHT': 0.55, 'BAYES_WEIGHT': 0.45,
    'MATH_CONFIDENCE': 0.7, 'S_RED': 1.0, 'S_BLACK': 1.0,
    'RANDOM_NOISE': 0.02, 'VOTE_THRESHOLD': 2,
}
# ==================== 🗄️ إدارة قاعدة البيانات ====================
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=10)
        return conn
    except Exception as e:
        logger.error(f"❌ فشل الاتصال بقاعدة البيانات: {e}")
        return None

def load_filtered_history(min_id: int = WARMUP_ROUNDS + 1) -> pd.DataFrame:
    try:
        conn = get_db_connection()
        if not conn:
            return pd.DataFrame()
        query = f"""
            SELECT id, b_num, suit, winner, timestamp, prediction, user_id
            FROM history 
            WHERE winner IS NOT NULL AND id >= {min_id}
            ORDER BY id ASC
        """
        df = pd.read_sql(query, conn)
        conn.close()
        
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            df['winner_code'] = df['winner'].map(WINNER_MAP)
            df = df.dropna(subset=['winner_code'])
        
        logger.info(f"✅ تم تحميل {len(df)} جولة (بعد تجاهل أول {WARMUP_ROUNDS})")
        return df
    except Exception as e:
        logger.error(f"❌ خطأ في تحميل البيانات: {e}")
        return pd.DataFrame()

def get_latest_stats(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {'total_rounds': 0, 'bias': {'red': 0, 'blue': 0, 'tie': 0}}
    
    stats = {
        'total_rounds': len(df),
        'winner_dist': df['winner'].value_counts().to_dict() if 'winner' in df.columns else {},
        'bias': {'red': 0, 'blue': 0, 'tie': 0}
    }
    
    total = len(df)
    if total > 0 and 'winner' in df.columns:
        stats['bias'] = {
            'red': float((df['winner'] == 'الراعي 🔴').sum()) / total,
            'blue': float((df['winner'] == 'الثور 🔵').sum()) / total,            'tie': float((df['winner'] == 'تعادل ⚪').sum()) / total
        }
    
    return stats

def load_dynamic_config():
    global DYNAMIC_CONFIG
    try:
        conn = get_db_connection()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("SELECT config_name, config_value FROM ai_settings")
        for name, value in cur.fetchall():
            if name in DYNAMIC_CONFIG:
                try:
                    DYNAMIC_CONFIG[name] = json.loads(value)
                except:
                    DYNAMIC_CONFIG[name] = value
        conn.close()
    except Exception as e:
        logger.warning(f"⚠️ فشل تحميل الإعدادات: {e}")

# ==================== 🤖 محرك الذكاء الاصطناعي ====================
class AdvancedAIEngine:
    def __init__(self):
        try:
            self.client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
            self.model = NVIDIA_MODEL
        except Exception as e:
            logger.error(f"❌ خطأ في تهيئة AI: {e}")
            self.client = None
    
    def generate_prediction_command(self, df: pd.DataFrame, current_b_num: str, current_suit: str) -> Dict:
        if not self.client or df.empty:
            return {'prediction': 'الراعي 🔴', 'reason': 'تحليل افتراضي', 'confidence': 0.5}
        
        try:
            last_20 = df.tail(20) if len(df) >= 20 else df
            recent_winners = last_20['winner'].tolist() if 'winner' in last_20.columns else []
            winner_counts = Counter(recent_winners)
            last_digit = current_b_num[-1] if current_b_num and current_b_num[-1].isdigit() else '0'
            
            prompt = f"""أنت نظام تنبؤ ذكي. البيانات المتاحة:
📈 آخر 20 نتيجة: {recent_winners[-10:] if recent_winners else []}
📊 التكرار الأخير: {dict(winner_counts)}
🎯 الجولة الحالية: رقم={current_b_num}, بذلة={current_suit}, آخر_رقم={last_digit}

المطلوب: أعطِ تنبؤاً واحداً للجولة الحالية مع سبب منطقي مختصر.
أجب بصيغة JSON:{{"prediction": "الراعي 🔴" أو "الثور 🔵" أو "تعادل ⚪", "reason": "سبب مختصر", "confidence": 0.XX}}"""
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=500
            )
            content = response.choices[0].message.content
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {'prediction': 'الراعي 🔴', 'reason': 'تحليل AI', 'confidence': 0.5}
        except Exception as e:
            logger.error(f"❌ خطأ في تنبؤ AI: {e}")
            return {'prediction': 'الراعي 🔴', 'reason': 'تحليل افتراضي', 'confidence': 0.5}

# ==================== 🎮 معالجات البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر البداية - مع معالجة أخطاء شاملة"""
    try:
        user_id = update.effective_user.id
        logger.info(f"📥 مستخدم {user_id} أرسل /start")
        
        # محاولة تحميل الإحصائيات (بدون إيقاف البوت إذا فشلت)
        try:
            df = load_filtered_history()
            stats = get_latest_stats(df) if not df.empty else {'total_rounds': 0, 'bias': {'red': 0, 'blue': 0, 'tie': 0}}
        except Exception as e:
            logger.error(f"⚠️ خطأ في تحميل الإحصائيات: {e}")
            stats = {'total_rounds': 0, 'bias': {'red': 0, 'blue': 0, 'tie': 0}}
        
        kb = [
            [InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")],
            [InlineKeyboardButton("📊 تحليل البيانات", callback_data="view_stats")],
            [InlineKeyboardButton("🤖 تنبؤ AI", callback_data="ai_predict")],
            [InlineKeyboardButton("📜 القوانين", callback_data="view_laws")]
        ]
        
        if user_id == ADMIN_ID:
            kb.append([
                InlineKeyboardButton("🎛️ لوحة الأدمن", callback_data="admin_panel"),
                InlineKeyboardButton("📤 تصدير", callback_data="admin_export")
            ])
        
        total = stats.get('total_rounds', 0)
        summary = f"🏛️ **HADES V103**\n\n📊 جولات محللة: {total}\n🎯 جاهز للتنبؤ!"
        
        await update.message.reply_text(
            summary,            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
        logger.info(f"✅ استجابة /start ناجحة للمستخدم {user_id}")
        
    except Exception as e:
        logger.error(f"❌ خطأ فادح في /start: {e}")
        # رد احتياطي حتى لو فشل كل شيء
        try:
            kb = [[InlineKeyboardButton("🎴 اختيار البذلة", callback_data="choose_suit")]]
            await update.message.reply_text(
                "🏛️ **HADES V103**\n\n⚠️ وضع الصيانة - جاري التحميل...\n\n🎴 اختر البذلة للبدء:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='Markdown'
            )
        except:
            pass

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار التفاعلية"""
    try:
        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = update.effective_user.id
        
        logger.info(f"🔘 زر {data} من المستخدم {user_id}")
        
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
        
        elif data == "view_stats":
            try:
                df = load_filtered_history()
                stats = get_latest_stats(df)
                report = f"""📊 **إحصائيات HADES V103**
🔢 جولات: {stats.get('total_rounds', 0)}
🏆 توزيع:
• 🔴: {stats['bias'].get('red', 0):.1%}
• 🔵: {stats['bias'].get('blue', 0):.1%}
• ⚪: {stats['bias'].get('tie', 0):.1%}"""            except:
                report = "📊 **إحصائيات HADES V103**\n⏳ جاري التحميل..."
            
            kb = [[InlineKeyboardButton("🔄 تحديث", callback_data="view_stats")],
                  [InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]]
            await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        
        elif data == "ai_predict":
            if 'suit' not in context.user_data:
                await query.answer("⚠️ اختر بذلة أولاً", show_alert=True)
                return
            await query.answer("📥 أرسل رقم البونص الآن", show_alert=True)
            context.user_data['awaiting_bonus'] = True
        
        elif data == "view_laws":
            try:
                conn = get_db_connection()
                if conn:
                    cur = conn.cursor()
                    cur.execute("SELECT law_name, confidence_score FROM ai_laws WHERE is_active=TRUE ORDER BY confidence_score DESC LIMIT 5")
                    laws = cur.fetchall()
                    conn.close()
                    if laws:
                        report = "📜 **أهم 5 قوانين مكتشفة:**\n"
                        for i, (name, conf) in enumerate(laws, 1):
                            report += f"{i}. {name} (ثقة: {conf:.0%})\n"
                    else:
                        report = "📜 لا توجد قوانين مكتشفة بعد"
                else:
                    report = "📜 جاري تحميل القوانين..."
            except:
                report = "📜 جاري تحميل القوانين..."
            
            kb = [[InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]]
            await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        
        elif data == "admin_panel" and user_id == ADMIN_ID:
            kb = [
                [InlineKeyboardButton("📊 تحليل شامل", callback_data="admin_analyze")],
                [InlineKeyboardButton("🔄 إعادة تحميل", callback_data="admin_reload")],
                [InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]
            ]
            await query.edit_message_text("🎛️ **لوحة تحكم الأدمن**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        
        elif data == "admin_analyze" and user_id == ADMIN_ID:
            await query.edit_message_text("🔄 جاري التحليل...")
            try:
                df = load_filtered_history()
                stats = get_latest_stats(df)
                report = f"""📊 **تحليل شامل**• جولات: {stats.get('total_rounds', 0)}
• انحياز 🔴: {stats['bias'].get('red', 0):.1%}"""
            except:
                report = "📊 **تحليل شامل**\n⏳ جاري التحميل..."
            
            kb = [[InlineKeyboardButton("🔄 تحديث", callback_data="admin_analyze")],
                  [InlineKeyboardButton("🔙 لوحة الأدمن", callback_data="admin_panel")]]
            await query.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        
        elif data == "admin_export" and user_id == ADMIN_ID:
            await query.answer("✅ تم بدء التصدير", show_alert=True)
        
        elif data == "admin_reload" and user_id == ADMIN_ID:
            context.user_data.pop('suit', None)
            context.user_data.pop('last_b', None)
            await query.answer("✅ تم إعادة التحميل", show_alert=True)
            await start(update, context)
        
        elif data == "start_back":
            await start(update, context)
        
        elif data.startswith("save_"):
            parts = data.split("_")
            if len(parts) >= 4:
                b_num = parts[1]
                suit = parts[2]
                winner = "_".join(parts[3:])
                try:
                    conn = get_db_connection()
                    if conn:
                        cur = conn.cursor()
                        cur.execute("""
                            INSERT INTO history (b_num, suit, winner, timestamp, prediction, user_id)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (b_num, suit, winner, datetime.datetime.now(), 
                              WINNER_MAP.get(winner.split()[0], -1), user_id))
                        conn.commit()
                        conn.close()
                    
                    kb = [[InlineKeyboardButton("🔄 جولة جديدة", callback_data="choose_suit")]]
                    await query.edit_message_text(f"✅ سُجّل: {winner}\n🔄 جاهز للجولة التالية:", reply_markup=InlineKeyboardMarkup(kb))
                except Exception as e:
                    logger.error(f"❌ خطأ الحفظ: {e}")
                    await query.answer("❌ خطأ في الحفظ", show_alert=True)
    
    except Exception as e:
        logger.error(f"❌ خطأ في handle_callback: {e}")
        try:
            await query.answer("⚠️ حدث خطأ، حاول مرة أخرى", show_alert=True)
        except:            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل النصية"""
    try:
        text = update.message.text.strip()
        user_id = update.effective_user.id
        
        if context.user_data.get('awaiting_bonus') and text.isdigit() and len(text) >= 7:
            if 'suit' not in context.user_data:
                await update.message.reply
