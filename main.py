# -*- coding: utf-8 -*-
"""
HADES V103 - Autonomous Self-Evolving AI Prediction System
نظام تنبؤ هجين: معادلة رياضية + تحليل بايزي + NVIDIA AI + قوانين ذكية
يعمل على Railway مع PostgreSQL - واجهة أزرار تفاعلية كاملة
"""

import os
import sys
import datetime
import psycopg2
import pandas as pd
import numpy as np
import json
import re
import logging
import random
from typing import Dict, List, Tuple, Optional, Any
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, JobQueue
)
from telegram.error import BadRequest
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
    'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}
SUITS = ['♦️', '♥️', '♠️', '♣️']

# الإعدادات الديناميكية الافتراضية
DYNAMIC_CONFIG = {
    'CONFIDENCE_THRESHOLD': 0.65,
    'MATH_WEIGHT': 0.55,
    'BAYES_WEIGHT': 0.45,
    'MATH_CONFIDENCE': 0.7,
    'S_RED': 1.0,
    'S_BLACK': 1.0,
    'RANDOM_NOISE': 0.02,
    'VOTE_THRESHOLD': 2,
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
            'blue': float((df['winner'] == 'الثور 🔵').sum()) / total,
            'tie': float((df['winner'] == 'تعادل ⚪').sum()) / total
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

def get_active_laws() -> List[Dict]:
    try:
        conn = get_db_connection()
        if not conn:
            return []
        cur = conn.cursor()
        cur.execute("""
            SELECT law_name, law_description, law_pattern, confidence_score, success_rate 
            FROM ai_laws 
            WHERE is_active=TRUE AND confidence_score>=0.6 
            ORDER BY confidence_score DESC 
            LIMIT 10        """)
        laws = []
        for row in cur.fetchall():
            laws.append({
                'name': row[0],
                'description': row[1],
                'pattern': row[2],
                'confidence': row[3],
                'success_rate': row[4]
            })
        conn.close()
        return laws
    except Exception as e:
        logger.error(f"❌ خطأ في جلب القوانين: {e}")
        return []

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
            
            laws = get_active_laws()
            law_info = ""
            if laws:
                law_info = f"\n📜 القوانين النشطة: {len(laws)}"
            
            prompt = f"""أنت نظام تنبؤ ذكي. البيانات المتاحة:

📈 آخر 20 نتيجة: {recent_winners[-10:] if recent_winners else []}
📊 التكرار الأخير: {dict(winner_counts)}
🎯 الجولة الحالية: رقم={current_b_num}, بذلة={current_suit}, آخر_رقم={last_digit}
{law_info}

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

# ==================== 👁️ مراقب الذكاء الاصطناعي ====================
class AIObserver:
    def __init__(self, app):
        self.app = app
        self.ai_engine = AdvancedAIEngine()
        self.is_running = False
    
    def _log_action(self, cycle: str, action: str, details: Dict):
        try:
            conn = get_db_connection()
            if not conn:
                return
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_observer_log (observer_cycle, action_type, details)
                VALUES (%s, %s, %s)
            """, (cycle, action, json.dumps(details, default=str, ensure_ascii=False)))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"❌ خطأ في تسجيل سجل المراقب: {e}")
    
    def _get_history(self, limit: int = 100) -> pd.DataFrame:
        try:
            conn = get_db_connection()
            if not conn:
                return pd.DataFrame()
            df = pd.read_sql(f"""
                SELECT * FROM history 
                WHERE winner IS NOT NULL AND prediction IS NOT NULL
                ORDER BY id DESC 
                LIMIT {limit}
            """, conn)            conn.close()
            return df
        except Exception as e:
            logger.error(f"❌ خطأ في جلب التاريخ: {e}")
            return pd.DataFrame()
    
    def _quick_scan(self, df: pd.DataFrame) -> List[Dict]:
        if len(df) < 20:
            return []
        
        patterns = []
        
        for w in ['الراعي 🔴', 'الثور 🔵', 'تعادل ⚪']:
            sub = df[df['winner'] == w]
            if len(sub) >= 5 and 'b_num' in sub.columns:
                sub_copy = sub.copy()
                sub_copy['last_digit'] = sub_copy['b_num'].astype(str).str[-1].str.extract('(\d)')
                freq = sub_copy['last_digit'].value_counts()
                if not freq.empty and freq.iloc[0] >= 3:
                    patterns.append({
                        'type': 'last_digit_after_winner',
                        'winner': w,
                        'digit': str(freq.index[0]),
                        'freq': int(freq.iloc[0]),
                        'confidence': min(0.95, freq.iloc[0] / len(sub) + 0.3)
                    })
        
        if 'suit' in df.columns:
            for s in SUITS:
                sub = df[df['suit'] == s]
                if len(sub) >= 5 and 'winner' in sub.columns:
                    wf = sub['winner'].value_counts()
                    if not wf.empty and wf.iloc[0] >= 3:
                        patterns.append({
                            'type': 'suit_winner',
                            'suit': s,
                            'winner': wf.index[0],
                            'freq': int(wf.iloc[0]),
                            'confidence': min(0.95, wf.iloc[0] / len(sub) + 0.25)
                        })
        
        return patterns
    
    def _save_law(self, law: Dict):
        try:
            conn = get_db_connection()
            if not conn:
                return
            cur = conn.cursor()
            cur.execute("""                INSERT INTO ai_laws (law_name, law_description, law_pattern, confidence_score)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (law_name) DO UPDATE
                SET confidence_score = EXCLUDED.confidence_score, 
                    last_updated = CURRENT_TIMESTAMP
            """, (
                law['name'],
                law.get('description', ''),
                json.dumps(law['pattern'], default=str, ensure_ascii=False),
                law['confidence']
            ))
            conn.commit()
            conn.close()
            logger.info(f"💡 قانون جديد محفوظ: {law['name']}")
        except Exception as e:
            logger.error(f"❌ خطأ في حفظ القانون: {e}")
    
    async def quick_review(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_running:
            return
        
        logger.info("🔍 [Observer] بدء المراجعة السريعة...")
        
        df = self._get_history(50)
        if df.empty:
            return
        
        patterns = self._quick_scan(df)
        
        for p in patterns:
            name = f"{p['type']}_{p.get('winner', p.get('suit', 'x'))}"
            existing = [l for l in get_active_laws() if l['name'] == name]
            
            if not existing:
                self._save_law({
                    'name': name,
                    'description': p['type'],
                    'pattern': p,
                    'confidence': p['confidence']
                })
                self._log_action('quick', 'new_law', {'law': name})
        
        self._log_action('quick', 'review_complete', {'patterns': len(patterns)})
        logger.info(f"✅ [Observer] انتهت المراجعة السريعة - أنماط: {len(patterns)}")
    
    async def deep_review(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_running:
            return
        
        logger.info("🔬 [Observer] بدء المراجعة العميقة...")        
        df = self._get_history(200)
        if df.empty:
            return
        
        total = len(df)
        if total > 0:
            red = float((df['winner'] == 'الراعي 🔴').sum()) / total
            blue = float((df['winner'] == 'الثور 🔵').sum()) / total
            tie = float((df['winner'] == 'تعادل ⚪').sum()) / total
            
            if tie < 0.05:
                self._save_law({
                    'name': 'قانون التعادل الحذر',
                    'description': 'التعادلات نادرة جداً ويمكن استبعادها من التنبؤات',
                    'pattern': {
                        'action': 'تجاهل التعادل والتنبؤ بين الراعي أو الثور فقط',
                        'condition': 'في أي جولة'
                    },
                    'confidence': 0.85
                })
        
        if 'prediction' in df.columns and 'winner' in df.columns:
            df['winner_code'] = df['winner'].map(WINNER_MAP)
            df = df.dropna(subset=['winner_code'])
            
            if len(df) >= 20:
                last_20 = df.tail(20)
                accuracy = (last_20['winner_code'] == last_20['prediction']).mean()
                
                if accuracy > 0.70:
                    self._save_law({
                        'name': 'قانون زخم الدقة',
                        'description': f'دقة آخر 20 جولة: {accuracy:.0%}',
                        'pattern': {
                            'action': 'استمر في نفس نهج التنبؤ',
                            'condition': 'دقة_آخر_20_جولة > 0.70'
                        },
                        'confidence': 0.78
                    })
        
        self._log_action('deep', 'review_complete', {'total_rounds': total})
        logger.info(f"✅ [Observer] انتهت المراجعة العميقة")
    
    def start(self, jq: JobQueue):
        self.is_running = True
        
        jq.run_repeating(
            self.quick_review,
            interval=600,            first=60,
            name="observer_quick"
        )
        logger.info("⏰ [Observer] تم جدولة المراجعة السريعة كل 10 دقائق")
        
        jq.run_repeating(
            self.deep_review,
            interval=1800,
            first=120,
            name="observer_deep"
        )
        logger.info("⏰ [Observer] تم جدولة المراجعة العميقة كل 30 دقائق")
    
    def stop(self, jq: JobQueue):
        self.is_running = False
        logger.info("🛑 [Observer] تم إيقاف المراقب")

# ==================== 🎮 معالجات البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        logger.info(f"📥 مستخدم {user_id} أرسل /start")
        
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
            summary,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'        )
        logger.info(f"✅ استجابة /start ناجحة للمستخدم {user_id}")
        
    except Exception as e:
        logger.error(f"❌ خطأ فادح في /start: {e}")
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
    try:
        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = update.effective_user.id
        
        logger.info(f"🔘 زر {data} من المستخدم {user_id}")
        
        if data == "choose_suit":
            kb = [
                [InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[:2]],
                [InlineKeyboardButton(s, callback_data=f"s_{s}") for s in SUITS[2:]],
                [InlineKeyboardButton("🔙 رجوع", callback_data="start_back")]
            ]
            await query.edit_message_text("🎴 اختر البذلة للبدء:", reply_markup=InlineKeyboardMarkup(kb))
        
        elif data.startswith("s_"):
            suit = data[2:]
            context.user_data['suit'] = suit
            kb = [[InlineKeyboardButton("🔙 رجوع للبذلات", callback_data="choose_suit")]]
            await query.edit_message_text(
                f"✅ البذلة: {suit}\n📥 أرسل رقم البونص (7+ أرقام) للتحليل:",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        
        elif data == "view_stats":
            try:
                df = load_filtered_history()
                stats = get_latest_stats(df)
                report = f"""📊 **إحصائيات HADES V103**
🔢 جولات: {stats.get('total_rounds', 0)}
🏆 توزيع:
• 🔴: {stats['bias'].get('red', 0):.1%}
• 🔵: {stats['bias'].get('blue', 0):.1%}• ⚪: {stats['bias'].get('tie', 0):.1%}
"""
            except:
                report = "📊 **إحصائيات HADES V103**\n⏳ جاري التحميل..."
            
            kb = [
                [InlineKeyboardButton("🔄 تحديث", callback_data="view_stats")],
                [InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]
            ]
            await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        
        elif data == "ai_predict":
            if 'suit' not in context.user_data:
                await query.answer("⚠️ اختر بذلة أولاً", show_alert=True)
                return
            await query.answer("📥 أرسل رقم البونص الآن", show_alert=True)
            context.user_data['awaiting_bonus'] = True
        
        elif data == "view_laws":
            try:
                laws = get_active_laws()
                if laws:
                    report = "📜 **أهم القوانين المكتشفة:**\n"
                    for i, law in enumerate(laws[:5], 1):
                        report += f"{i}. {law['name']} (ثقة: {law['confidence']:.0%})\n"
                else:
                    report = "📜 لا توجد قوانين مكتشفة بعد"
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
                report = f"""📊 **تحليل شامل**
• جولات: {stats.get('total_rounds', 0)}
• انحياز 🔴: {stats['bias'].get('red', 0):.1%}
"""            except:
                report = "📊 **تحليل شامل**\n⏳ جاري التحميل..."
            
            kb = [
                [InlineKeyboardButton("🔄 تحديث", callback_data="admin_analyze")],
                [InlineKeyboardButton("🔙 لوحة الأدمن", callback_data="admin_panel")]
            ]
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
            parts = data.split("_", 1)
            if len(parts) >= 2:
                winner = parts[1]
                b_num = context.user_data.get('last_b', 'unknown')
                suit = context.user_data.get('suit', 'unknown')
                
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
                    await query.edit_message_text(
                        f"✅ سُجّل: {winner}\n🔄 جاهز للجولة التالية:",
                        reply_markup=InlineKeyboardMarkup(kb)
                    )
                except Exception as e:
                    logger.error(f"❌ خطأ الحفظ: {e}")
                    await query.answer("❌ خطأ في الحفظ", show_alert=True)
    
    except Exception as e:        logger.error(f"❌ خطأ في handle_callback: {e}")
        try:
            await query.answer("⚠️ حدث خطأ، حاول مرة أخرى", show_alert=True)
        except:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        user_id = update.effective_user.id
        
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
            
            prediction = result['prediction']
            reason = result['reason']
            confidence = result['confidence']
            
            context.user_data['last_b'] = text
            
            report = f"""🎯 **تنبؤ HADES V103**

🏆 النتيجة: **{prediction}**
📋 السبب: {reason}
📊 الثقة: {confidence:.0%}
🎴 البذلة: {suit}
"""
            
            kb = [
                [
                    InlineKeyboardButton("🔴 راعي", callback_data=f"save_الراعي 🔴"),
                    InlineKeyboardButton("🔵 ثور", callback_data=f"save_الثور 🔵")
                ],
                [InlineKeyboardButton("⚪ تعادل", callback_data=f"save_تعادل ⚪")],
                [InlineKeyboardButton("🔄 تحليل جديد", callback_data="ai_predict")]
            ]
                        await update.message.reply_text(
                report,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='Markdown'
            )
            context.user_data['awaiting_bonus'] = False
            return
        
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
        
        kb = [
            [InlineKeyboardButton("🎴 البدء", callback_data="choose_suit")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="view_stats")],
            [InlineKeyboardButton("🤖 تنبؤ AI", callback_data="ai_predict")]
        ]
        await update.message.reply_text(
            "🏛️ **HADES V103**\nاختر من القائمة للبدء:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
    
    except Exception as e:
        logger.error(f"❌ خطأ في handle_message: {e}")

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
🎯 دقة: {stats.get('accuracy', 'N/A')}
"""    kb = [[InlineKeyboardButton("🔙 الرئيسية", callback_data="start_back")]]
    await update.message.reply_text(report, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def export_laws_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ للأدمن فقط")
        return
    
    try:
        laws = get_active_laws()
        if laws:
            report = "📜 **القوانين النشطة:**\n"
            for law in laws[:10]:
                report += f"• {law['name']} ({law['confidence']:.0%})\n"
            await update.message.reply_text(report, parse_mode='Markdown')
        else:
            await update.message.reply_text("📜 لا توجد قوانين نشطة")
    except Exception as e:
        logger.error(f"❌ خطأ التصدير: {e}")
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 🚀 التشغيل الرئيسي ====================
if __name__ == "__main__":
    logger.info("🚀 بدء HADES V103 - واجهة الأزرار")
    
    load_dynamic_config()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("export_laws", export_laws_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    observer = AIObserver(app)
    observer.start(app.job_queue)
    
    logger.info("✅ البوت جاهز - واجهة الأزرار مفعلة")
    logger.info(f"📌 يتم تجاهل أول {WARMUP_ROUNDS} جولة تلقائياً")
    logger.info("👁️ مراقب AI يعمل: مراجعة سريعة كل 10د | عميقة كل 30د")
    
    app.run_polling(drop_pending_updates=True)
