#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 🧠  QUANTUM SAGE v2.1 — BREATHING PROFIT HUNTER  (Binance USDT-M Futures)
==============================================================================
 بوت ذكي للحساب التجريبي (100 دولار) — يختبر على الديمو قبل أي شيء.

 ما الذي يجعله ذكيًا (المؤشر المركب من 7 ركائز — يجمع كل بيانات بينانس):
   [T] بنية الاتجاه     — تكدسات EMA متعددة الأطر (5m/15m/1h/4h) + ADX
   [M] الزخم            — RSI / MACD / ROC / انفجار 1m
   [V] حالة التقلب      — مئينات ATR وعرض بولنجر + التوسع
   [F] الحجم والتدفق    — z-score للحجم، MFI، نسبة المشترين/البائعين الفورية
   [B] ضغط دفتر الأوامر — عدم توازن العمق (15 مستوى) + زخم عدم التوازن
   [D] المشتقات         — معدل التمويل (عكسي) + مصفوفة OI/السعر
   [G] جاذبية الارتداد  — المسافة عن VWAP، تشبعات RSI، %B

 محرك نوع السوق (البوت "يعرف" السوق ويتعامل معه):
   TREND_UP / TREND_DOWN / RANGE / VOLATILE_CHOP / SQUEEZE / DEAD
   → أوزان ركائز تكيفية + مضاعفات SL/TP + حدود زمنية وحجم حسب النظام.

 إدارة الصفقة (محرك إعادة التقييم):
   * عند 70% من الطريق إلى الهدف → إعادة تقييم كاملة → إلغاء SL/TP القديمين
     ووضع جديدين (أوضاع RIDE / SECURE / BAIL) ثم Trailing متحرك بـ ATR.
   * عند 70% من الطريق إلى وقف الخسارة → إعادة تقييم → خروج مبكر / شدّ SL / صبر.
   * الصفقة الراكدة → إعادة تقييم → إغلاق إذا ماتت أو تنبيه.
   * الخروج عن الاستراتيجية → 🚨 تنبيه في لوق Railway كل 10 ثوان
     (أنت تغلق يدويًا — البوت لا يغلق تلقائيًا عند الانحراف).

 نظافة الأوامر (لا تكرار):
   * صفقة واحدة = أمر SL واحد + أمر TP واحد فقط، مرئيان دائمًا على بينانس.
   * الأوامر تُجدَّد (يُلغى القديم ويوضع الجديد مكانه) فقط إذا تحرك المستوى
     أكثر من 0.1% — لن ترى 22/50 أمرًا متراكمًا أبدًا.

 إدارة المخاطر (مضبوطة على 100 دولار):
   * مخاطرة 2% لكل صفقة | أقصى صفقتان | أقصى حجم فعلي 4x من رأس المال
   * قاطع خسارة يومي 6% | تهدئة 30 دقيقة بعد 3 خسائر متتالية
   * هامش معزول، وضع اتجاه واحد، رافعة ≤ 6x

 التشغيل:
   pip install -U "ccxt>=4.3.0" numpy
   python main.py
   (Railway: requirements.txt → سطران: ccxt>=4.3.0 و numpy)

 v1.1 — إصلاحات مطلوبة فقط (الاستراتيجية والخوارزميات كما هي بلا أي تغيير):
   * ✅ أوامر SL/TP: سلسلة 4 محاولات (نداء خام مباشر إلى بينانس ثم
     create_order ثم reduceOnly بنوعيه) — توضع مع أي إصدار ccxt قديمًا
     أو جديدًا + طباعة إصدار ccxt عند الإقلاع مع تحذير وتعليمات الحل.
   * ✅ عند الوصول للهدف (أو للوقف) وإغلاق الصفقة: إلغاء تلقائي فوري
     لكل أوامر TP/SL المتبقية مع تحقق و3 محاولات + ماسح أوامر يتيمة
     كل دورة (لا أوامر معلقة بعد إغلاق الصفقة أبدًا).
   * ✅ 📐 حاسبة SL/TP دقيقة: وقف خلف آخر قاع/قمة محلية + هامش ATR،
     والهدف عند أقرب حاجز هيكلي قابل للتحقيق (لا يقل عن 1.2R) —
     فما دون ذلك هدف RR النظام — فيصل البوت لجني الأرباح بسهولة.

 v1.2 — إصلاح سباق التوقيت وأنواع الأوامر (تشخيص اللوق):
   * ✅ بعد أمر الدخول: انتظار ظهور الصفقة (6 محاولات × 1ث) + جلب مباشر
     للرمز + إغلاق احترازي فوري إن لم تظهر — مستحيل صفقة مكشوفة.
   * ✅ تبنّي تلقائي (adopt=True) في كل دورة: أي صفقة غير مسجلة
     يتبناها البوت فورًا ويضع لها SL/TP بدل بقائها مكشوفة.
   * ✅ _otype(): تطبيع نوع الأمر مهما كان حجم أحرفه في ccxt —
     البوت يرى أوامر SL/TP التي وضعها بنفسه دائمًا.
   * ✅ priceProtect='TRUE' كنص (لا boolean) + دقة السعر مضبوطة.

 v1.3 — 🔴 اكتشاف جوهري + التجديد بالترتيب الصحيح:
   * ✅ بينانس نقلت الأوامر الشرطية (SL/TP) إلى Algo Order API الجديدة
     (الخطأ -4120 على endpoint القديم) — البوت الآن يضع SL/TP عبر
     POST /fapi/v1/algoOrder (algotype=conditional) ويجلبها عبر
     openAlgoOrders ويلغيها عبر DELETE algoOrder — مع إبقاء
     endpoint القديم كاحتياط للتوافق مع أي خادم.
   * ✅ "ضع الجديد أولًا ثم ألغِ القديم": عند تجديد SL/TP يوضع الأمر
     الجديد على بينانس قبل إلغاء القديم (والقديم ما زال يحمي) —
     لا لحظة واحدة بلا حماية أبدًا. ولو فشل الجديد يبقى القديم حاميًا.
   * ✅ بينانس تقبل أمر closePosition واحدًا لكل نوع/اتجاه (-4130) →
     عند التجديد يوضع الجديد بصيغة الكمية+reduceOnly المكافئة، وبعد
     إلغاء القديم تعود صيغة closePosition في التجديد التالي.
   * ✅ الإلغاء الشامل يشمل الأوامر الشرطية (cancel_all_orders القديم
     لا يراها) — لا أوامر معلقة بعد إغلاق الصفقة أبدًا.

 v1.4 — 🛡️ الحارس (حل نهائي لـ "مراكز دون طلبات"):
   * ✅ حارس حماية كل دورة: كل مركز على الصرف (من البوت أو مُتبنّى
     من جلسة سابقة) يُفحص مباشرة — إن نقصت رجل SL أو TP تُشفى فورًا
     في نفس الدورة، دون انتظار محرك الإدارة.
   * ✅ تصعيد صارم: إن تعذر وضع الحماية 3 دورات متتالية → إغلاق طارئ
     بسعر السوق + تنبيه 🆘🆘🆘 (مركز مغلق أفضل من مركز مكشوف).
   * ✅ قراءة صادقة للأوامر: فشل الجلب من المصدرين لا يُعتبر "لا أوامر"
     (يُنتظر الدورة التالية) — لا شفاء أعمى ولا تكرار أوامر خاطئ.
   * ✅ -4130 = يوجد أمر قائم يحمي: عند التعارض يُتبنّى الأمر القائم
     بدل وضع نسخة كمية مكررة — استحالة تراكم الأوامر.
   * ✅ النبض 💓 يعرض حالة الحماية لكل مركز (🆘 إن كان مكشوفًا).

 v2.1 — 🌬️ التنفس (BREATHING) — إعادة فتح صنابير الدخول بذكاء:
   * v2.0 خنقت الدخول بـ 5 بوابات متراكبة (عتبات مرتفعة + CHOP محجوب
     كليًا + انصهار 4/6 + HTF إلزامي + تطرف RSI إلزامي) — البوت توقف
     عن الدخول. v2.1 تُنفس البوت: صفقات أكثر بكثير مع الحفاظ على
     كل أدوات الربحية.
   * ✅ العتبات: 44/41/46 (كانت 48/45/50) — أقرب لـ v1.4 مع ركائز
     أقوى تدفع الدرجة لأعلى.
   * ✅ CHOP عاد للعمل بعتبة عالية 62 + حجم نصفي (0.5×) — تنفس
     بلا فتح باب الخسائر.
   * ✅ الانصهار 3/6 بدل 4/6 + فحوص أخف (زخم ≥ 8، تدفق ≥ 6،
     نطاقات RSI أوسع، حجم ≥ 0.2).
   * ✅ HTF المعاكس في الترند: لم يعد حجبًا مطلقًا — يتطلب انصهارًا
     أعلى 4/6 (زخم قوي مثبت) بدل الحرمان الكامل.
   * ✅ RR: 2.1/1.6/1.5 + الحد الأدنى 1.15 — أهداف أقرب للتحقق.
   * 💰 كل أدوات الربحية باقية حرفيًا: الجني الجزئي 50% عند +1R مع
     بريك-إيفن + القاطع الزمني + الركائز المقواة + الحماية v1.4.

 v2.0 — 💰 محرك صائد الأرباح (PROFIT HUNTER) — تغيير الاستراتيجية بأكملها:
   * ✅ مؤشرات أقوى مدمجة في الركائز: انحياز الأطر الأعلى 1h/4h داخل
     ركيزة الاتجاه [T]، كسر بنية 20 شمعة (Donchian) داخل الزخم [M]،
     وانحراف RSI (تباعد السعر/الزخم) داخل الجاذبية [G].
   * ✅ بوابات انصهار فوق الدرجة المركبة: HTF غير معاكس +
     زخم مؤكد + تدفق مؤكد + منطقة RSI ملائمة + تأكيد حجم/انفجار +
     كسر بنية أو انحراف — والرينج يفرض تطرف RSI.
   * ✅ 💰 جني أرباح جزئي عند +1R: يقفل 50% ربحًا مؤكدًا وينقل الوقف
     إلى البريك-إيفن +0.05R — النصف الثاني يجري شبه بلا مخاطرة
     (نسبة ربح أعلى + منحنى رصيد أملس + الأرباح الكبيرة تبقى).
   * ✅ ⏱️ قاطع زمني للخاسر الراكد (-0.4R بعد 1.2× حد الصمود مع درجة
     ميتة) + تكبير الحجم 15% عند القناعة القوية (درجة ≥ 60).
   * (طبقة الحماية v1.4 كاملة كما هي: الحارس + Algo API + الاستبدال الآمن)

 التحويل للحقيقي لاحقًا:
   1) MODE = "live"
   2) LIVE_CONFIRM = True   (مفتاح أمان يمنع التشغيل الحقيقي بالخطأ)
==============================================================================
"""

import asyncio
import math
import os
import signal
import sys
import time
import traceback
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import ccxt.async_support as ccxt

# ============================================================================
# 🗝️ الإعدادات — عدّل هنا فقط
# ============================================================================
MODE = "demo"            # "demo" (demo-fapi.binance.com) | "testnet" | "live"
LIVE_CONFIRM = False     # يجب أن يكون True أيضًا لتفعيل MODE="live" (أمان)

API_KEYS = {
    # مفاتيح حساب الديمو (demo-fapi.binance.com)
    "demo": {
        "key": "uQozmWB6O6ZvdEPU7GCoTjFTdJWnhIGDsMuEqgI99wIWnS11EZCU7ArCvDUOTtwj",
        "secret": "WLi3YMbZWhXEicrAuUeODNiGnjlhvYgO9GlN6HaDlb9FAXiUxO1CprlVjKvCqRwK",
    },
    # تست نت الكلاسيكي (testnet.binancefuture.com) — ضع مفاتيحك إن استخدمته
    "testnet": {"key": "", "secret": ""},
    # أموال حقيقية (fapi.binance.com) — يتطلب MODE="live" و LIVE_CONFIRM=True
    "live": {
        "key": "IX7kLH0ssWHP5TpYMUGcp0pzq4LX4Lqi7m4XtlqMkkq6DCZAsLhoeYZ3533jJFF4",
        "secret": "LmICnpSpMxL1riv4RfIf0HBGRfhDTP5JhDUYdlPSukpqV7kDTonrZ0j3DWp1a7hU",
    },
}

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]

CAPITAL_CAP_USDT = 100.0     # المحاكاة بحساب 100$ حتى لو كان محفظة الديمو أكبر
RISK_PER_TRADE   = 0.02      # مخاطرة 2% من رأس المال الفعلي لكل صفقة
MAX_POSITIONS    = 2         # أقصى عدد صفقات متزامنة (واحدة لكل رمز)
MAX_LEVERAGE     = 6         # رافعة الصرف (معزول)
MAX_NOTIONAL_MULT = 4.0      # أقصى حجم = 4 أضعاف رأس المال الفعلي
DAILY_LOSS_LIMIT  = 0.06     # خسارة يوم -6% → إيقاف الدخول حتى يوم UTC جديد
CONSEC_LOSS_PAUSE = 1800     # تهدئة 30 دقيقة بعد 3 خسائر متتالية

CYCLE_SECONDS   = 10         # دورة الحلقة (تنبيهات كل 10 ثوان كما طلبت)
ENTRY_COOLDOWN_S = 120       # تهدئة لكل رمز بعد الدخول
POST_EXIT_COOLDOWN_S = 180   # تهدئة لكل رمز بعد الخروج
GLOBAL_ENTRY_GAP_S = 30      # أدنى فاصل بين أي دخولين (v2.1: كان 45)

# ═══ v2.1 🌬️ التنفس — بوابات مفتوحة بذكاء بعد أن خنقتها v2.0 ═══
# v2.0 رفعت كل شيء معًا (عتبات + CHOP محجوب + انصهار 4/6 + HTF إلزامي)
# فتوقف الدخول تمامًا. v2.1: عتبات قريبة من v1.4 (مع ركائز أقوى تدفع
# الدرجة)، CHOP مفتوح بعتبة عالية وحجم نصفي، انصهار 3/6 أخف.
ENTRY_THRESHOLD_BASE  = 44.0   # الدرجة المطلوبة من 100 (v1.4: 42 / v2.0: 48)
ENTRY_THRESHOLD_TREND = 41.0   # (v1.4: 40 / v2.0: 45)
ENTRY_THRESHOLD_RANGE = 46.0   # (v1.4: 45 / v2.0: 50)
ENTRY_THRESHOLD_CHOP  = 62.0   # v2.1: CHOP عاد للعمل بعتبة عالية (v1.4: 55)
AGREEMENT_MIN = 4              # 4 من 7 ركائز يجب أن تتفق
CONFLUENCE_MIN = 3             # v2.1: 3 من 6 انصهار (v2.0 كانت 4 — خانقت)
CONFLUENCE_MIN_STRICT = 4      # v2.1: انصهار أعلى مطلوب فقط ضد اتجاه HTF

SL_ATR_MULT = 1.4              # مسافة الوقف = 1.4 × ATR(5m) (معدلة بالنظام)
SL_PCT_MIN  = 0.0035           # 0.35%
SL_PCT_MAX  = 0.012            # 1.2%
RR_TREND, RR_RANGE, RR_CHOP = 2.1, 1.6, 1.5   # v2.1: أهداف أقرب للتحقق (كانت 2.4/1.7/1.5)

PROFIT_LOCK_TRIGGER  = 0.70    # إعادة تقييم عند 70% من الطريق للهدف
PROFIT_LOCK2_TRIGGER = 0.85    # شدّ التتبع أكثر عند 85%
LOSS_REVAL_TRIGGER   = 0.70    # إعادة تقييم عند 70% من الطريق للوقف
LOSS_REVAL_REARM_S   = 300     # إعادة تقييم الخسارة كل 5 دقائق كحد أقصى
TRAIL_ATR       = 1.0          # مسافة التتبع (× ATR الحالي)
TRAIL_ATR_TIGHT = 0.7          # بعد 85% من الهدف
MIN_REPLACE_MOVE = 0.001       # تجديد SL/TP فقط إذا تحرك المستوى > 0.1%
PROTECTION_MAX_HEALS = 3       # v1.4: فشل الحماية 3 دورات → إغلاق طارئ (لا مركز مكشوف)

# ═══════════════ 💰 v2.0 — محرك صائد الأرباح ═══════════════
PARTIAL_TP_R       = 1.0     # عند +1R: يقفل 50% ويصبح الوقف بريك-إيفن
PARTIAL_TP_FRAC    = 0.5     # نسبة الجزء المقفول من الصفقة
BE_OFFSET_R        = 0.05    # البريك-إيفن +0.05R (تغطية العمولات)
TIME_STOP_R        = -0.40   # خاسر راكد أعمق من هذا → خروج زمني
TIME_STOP_AGE_MULT = 1.2     # بعد 1.2× حد الصمود الزمني للنظام
MIN_RR_ACHIEVABLE  = 1.15    # v2.1: أدنى RR قابل للتحقيق (v1.4: 1.2 / v2.0: 1.25)

HOLD_TREND_MIN, HOLD_RANGE_MIN, HOLD_CHOP_MIN, HOLD_DEFAULT_MIN = 60, 30, 35, 45

DEVIATION_SCORE_FLIP = 35.0    # انقلاب الدرجة ضد الصفقة → تنبيه
MAX_SPREAD_BPS = {"BTCUSDT": 2.5, "ETHUSDT": 3.5, "SOLUSDT": 6.0,
                  "BNBUSDT": 6.0, "XRPUSDT": 14.0, "DOGEUSDT": 18.0}
DEFAULT_MAX_SPREAD_BPS = 8.0
NEAR_LOG_INTERVAL_S = 60       # سجل الإشارات القريبة كل 60 ثانية كحد أقصى
STATS_EVERY_CYCLES = 30        # إحصائيات مفصلة كل 30 دورة (5 دقائق)

PILLAR_ORDER = ['trend', 'mom', 'vol', 'flow', 'book', 'deriv', 'grav']
PILLAR_LETTER = {'trend': 'T', 'mom': 'M', 'vol': 'V', 'flow': 'F',
                 'book': 'B', 'deriv': 'D', 'grav': 'G'}
BASE_WEIGHTS = {'trend': 0.22, 'mom': 0.18, 'vol': 0.08, 'flow': 0.15,
                'book': 0.15, 'deriv': 0.10, 'grav': 0.12}
REGIME_SHORT = {'TREND_UP': 'TR↑', 'TREND_DOWN': 'TR↓', 'RANGE': 'RNG',
                'VOLATILE_CHOP': 'CHOP', 'SQUEEZE': 'SQZ', 'DEAD': 'DEAD',
                'UNKNOWN': '?'}

# ============================================================================
# 🛠️ أدوات عامة
# ============================================================================
def clamp(v, lo=-100.0, hi=100.0):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return max(lo, min(hi, v))


def now_utc_str():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def log(msg):
    print(f"{now_utc_str()} | {msg}", flush=True)


def lastf(arr, default=0.0):
    try:
        v = float(arr[-1])
        return v if math.isfinite(v) else default
    except Exception:
        return default


def _pillar_str(pillars):
    return " ".join(f"{PILLAR_LETTER.get(k, '?')}{pillars.get(k, 0.0):+.0f}"
                    for k in PILLAR_ORDER)


def _otype(o):
    """v1.2: نوع الأمر بشكل موحّد مهما كانت نسخة ccxt — الإصدارات الحديثة
    تعيد 'stop_market' بأحرف صغيرة بينما القديمة 'STOP_MARKET' —
    بدون التطبيع يعتبر البوت أوامره الخاصة مفقودة ويتصرف غلط!"""
    raw = o.get('type') or (o.get('info') or {}).get('type') or ''
    return str(raw).upper()


# ============================================================================
# 📐 مؤشرات فنية (numpy خالص — بدون أي مكتبات ثقيلة)
# ============================================================================
def _shift(x):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return x
    return np.concatenate(([x[0]], x[:-1]))


def _ewm(x, alpha):
    """تلطيف أُسّي (وائلدر) يتعامل مع القيم غير المعرفة في البداية."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    started = False
    prev = 0.0
    for i in range(len(x)):
        v = x[i]
        if not math.isfinite(v):
            continue
        if not started:
            prev = v
            started = True
        else:
            prev = alpha * v + (1.0 - alpha) * prev
        out[i] = prev
    return out


def ema(x, n):
    return _ewm(x, 2.0 / (n + 1.0))


def _rolling_sum(x, n):
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.concatenate(([0.0], np.cumsum(x)))
        out[n - 1:] = cs[n:] - cs[:-n]
    return out


def rsi(closes, n=14):
    c = np.asarray(closes, dtype=float)
    if len(c) < n + 2:
        return np.full(len(c), 50.0)
    d = np.diff(c)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = _ewm(up, 1.0 / n)
    ad = _ewm(dn, 1.0 / n)
    rs = au / np.where(ad == 0, 1e-12, ad)
    out = 100.0 - 100.0 / (1.0 + rs)
    out[:n] = 50.0
    return out


def true_range(h, l, c):
    prev_c = _shift(c)
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    return tr


def atr(h, l, c, n=14):
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    if len(c) < 2:
        return np.abs(h - l)
    return _ewm(true_range(h, l, c), 1.0 / n)


def adx(h, l, c, n=14):
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    if len(c) < 2 * n:
        return 15.0, 20.0, 20.0
    prev_h = _shift(h)
    prev_l = _shift(l)
    up = h - prev_h
    dn = prev_l - l
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr_ = _ewm(true_range(h, l, c), 1.0 / n)
    safe_atr = np.where(atr_ == 0, 1e-12, atr_)
    pdi = 100.0 * _ewm(plus_dm, 1.0 / n) / safe_atr
    mdi = 100.0 * _ewm(minus_dm, 1.0 / n) / safe_atr
    dsum = np.where((pdi + mdi) == 0, 1e-12, pdi + mdi)
    dx = 100.0 * np.abs(pdi - mdi) / dsum
    adx_ = _ewm(dx, 1.0 / n)
    return (lastf(adx_, 15.0), lastf(pdi, 20.0), lastf(mdi, 20.0))


def bollinger(c, n=20, k=2.0):
    c = np.asarray(c, dtype=float)
    mid = _rolling_sum(c, n) / n
    cs2 = _rolling_sum(c * c, n)
    var = np.maximum(cs2 / n - mid * mid, 0.0)
    sd = np.sqrt(var)
    up = mid + k * sd
    lo = mid - k * sd
    safe_mid = np.where(mid == 0, 1e-12, mid)
    bw = (up - lo) / safe_mid
    return mid, up, lo, bw


def mfi(h, l, c, v, n=14):
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    v = np.asarray(v, dtype=float)
    tp = (h + l + c) / 3.0
    mf = tp * v
    prev_tp = _shift(tp)
    pos = np.where(tp > prev_tp, mf, 0.0)
    neg = np.where(tp < prev_tp, mf, 0.0)
    pos_s = _rolling_sum(pos, n)
    neg_s = _rolling_sum(neg, n)
    ratio = pos_s / np.where(neg_s == 0, 1e-12, neg_s)
    out = 100.0 - 100.0 / (1.0 + ratio)
    out = np.where(np.isfinite(out), out, 50.0)
    return out


def vwap_roll(h, l, c, v, n=96):
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    v = np.asarray(v, dtype=float)
    n = min(n, len(c))
    tp = (h + l + c) / 3.0
    num = _rolling_sum(tp * v, n)
    den = _rolling_sum(v, n)
    return num / np.where(den == 0, 1e-12, den)


def macd(c, fast=12, slow=26, sig=9):
    c = np.asarray(c, dtype=float)
    line = ema(c, fast) - ema(c, slow)
    signal = _ewm(line, 2.0 / (sig + 1.0))
    hist = line - signal
    return line, signal, hist


def obv(c, v):
    c = np.asarray(c, dtype=float)
    v = np.asarray(v, dtype=float)
    if len(c) < 2:
        return np.zeros(len(c))
    d = np.diff(c)
    signed = np.where(d > 0, v[1:], np.where(d < 0, -v[1:], 0.0))
    return np.concatenate(([0.0], np.cumsum(signed)))


def zscore_last(x, n=50):
    a = np.asarray(x, dtype=float)[-n:]
    a = a[np.isfinite(a)]
    if len(a) < 5:
        return 0.0
    sd = float(np.std(a))
    if sd == 0:
        return 0.0
    return float((a[-1] - float(np.mean(a))) / sd)


def pctile_rank(arr, val):
    a = np.asarray(arr, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 10 or not math.isfinite(val):
        return 50.0
    return float((a < val).sum() / len(a) * 100.0)


# ============================================================================
# 📡 محرك البيانات — يجمع كل ما توفره بينانس في وقت واحد (مع كاش ذكي)
# ============================================================================
TF_SPECS = {
    '1m':  {'limit': 120, 'ttl': 12},    # يُحدَّث كل دورة (10 ثوان)
    '5m':  {'limit': 300, 'ttl': 55},
    '15m': {'limit': 200, 'ttl': 170},
    '1h':  {'limit': 120, 'ttl': 600},
    '4h':  {'limit': 80,  'ttl': 1800},
}


class MarketData:
    """يجمع الشموع (5 أطر زمنية) + دفتر الأوامر + الصفقات الأخيرة
    + العقود المفتوحة + معدل التمويل — كل رمز على حدة، مع كاش زمني."""

    def __init__(self, symbol, ex):
        self.symbol = symbol
        self.ex = ex
        self.k = {}                    # tf -> {'h','l','c','v','ts'}
        self.book = None               # {'bids': [...], 'asks': [...]}
        self.trades = []               # آخر الصفقات (taker side)
        self.oi_hist = deque(maxlen=300)   # (ts, openInterest)
        self.funding = 0.0             # نسبة/8س
        self.funding_ts = 0.0          # آخر تحديث للتمويل
        self.prev_obi = None           # عدم توازن الدفتر السابق (للزخم)
        self._last_err = {}

    # ---- مساعد سجل أخطاء مهدّأ (لا يغرق اللوق) ----
    def _err(self, key, e):
        now = time.time()
        if now - self._last_err.get(key, 0) > 300:
            self._last_err[key] = now
            log(f"⚠️ data[{self.symbol}] {key}: {type(e).__name__}: {str(e)[:120]}")

    def ready(self):
        if not all(tf in self.k for tf in TF_SPECS):
            return False
        if self.book is None:
            return False
        if time.time() - self.k['5m'].get('ts', 0) > 900:
            return False
        return True

    async def refresh(self):
        jobs = []
        now = time.time()
        for tf, spec in TF_SPECS.items():
            if now - self.k.get(tf, {}).get('ts', 0) > spec['ttl']:
                jobs.append(self._fetch_klines(tf, spec['limit']))
        jobs.append(self._fetch_book())
        jobs.append(self._fetch_trades())
        if now - (self.oi_hist[-1][0] if self.oi_hist else 0) > 25:
            jobs.append(self._fetch_oi())
        if now - self.funding_ts > 300:
            jobs.append(self._fetch_funding())
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    async def _fetch_klines(self, tf, limit):
        try:
            ohlcv = await self.ex.fetch_ohlcv(self.symbol, tf, limit=limit)
            if ohlcv and len(ohlcv) > 30:
                a = np.array(ohlcv, dtype=float)
                self.k[tf] = {'ts': time.time(), 'h': a[:, 2], 'l': a[:, 3],
                              'c': a[:, 4], 'v': a[:, 5]}
        except Exception as e:
            self._err('klines' + tf, e)

    async def _fetch_book(self):
        try:
            b = await self.ex.fetch_order_book(self.symbol, 50)
            if b and b.get('bids') and b.get('asks'):
                self.book = b
        except Exception as e:
            self._err('book', e)

    async def _fetch_trades(self):
        try:
            t = await self.ex.fetch_trades(self.symbol, limit=200)
            if t:
                self.trades = t
        except Exception as e:
            self._err('trades', e)

    async def _fetch_oi(self):
        try:
            oi = await self.ex.fetch_open_interest(self.symbol)
            val = float((oi or {}).get('openInterest') or 0)
            if val > 0:
                self.oi_hist.append((time.time(), val))
        except Exception as e:
            self._err('oi', e)

    async def _fetch_funding(self):
        try:
            fr = await self.ex.fetch_funding_rate(self.symbol)
            self.funding = float((fr or {}).get('fundingRate') or 0.0)
            self.funding_ts = time.time()
        except Exception as e:
            self._err('funding', e)
            self.funding_ts = time.time()


# ============================================================================
# 🧮 حساب كل المؤشرات دفعة واحدة
# ============================================================================
def compute_indicators(md):
    try:
        k1, k5 = md.k.get('1m'), md.k.get('5m')
        k15, k60, k240 = md.k.get('15m'), md.k.get('1h'), md.k.get('4h')
        if not all([k1, k5, k15, k60, k240]):
            return None
        if not (md.book and md.book.get('bids') and md.book.get('asks')):
            return None
        if len(k5['c']) < 80 or len(k15['c']) < 40 or len(k60['c']) < 60 \
                or len(k240['c']) < 25 or len(k1['c']) < 5:
            return None

        bid = float(md.book['bids'][0][0])
        ask = float(md.book['asks'][0][0])
        if bid <= 0 or ask <= 0 or ask < bid:
            return None
        price = (bid + ask) / 2.0
        spread_bps = (ask - bid) / price * 1e4

        h5, l5, c5, v5 = k5['h'], k5['l'], k5['c'], k5['v']

        atr5s = atr(h5, l5, c5, 14)
        atr5 = lastf(atr5s, price * 0.004)
        if atr5 <= 0:
            atr5 = price * 0.004
        atr_pct = atr5s / np.where(c5 == 0, 1e-12, c5) * 100.0
        atr_pct_pctile = pctile_rank(atr_pct[-300:], float(atr_pct[-1]))

        mid, bbu, bbl, bbw = bollinger(c5, 20, 2.0)
        bbw_pctile = pctile_rank(bbw[-300:], lastf(bbw, 0.01))
        rng_bb = float(bbu[-1] - bbl[-1])
        pct_b = float((c5[-1] - bbl[-1]) / rng_bb) if rng_bb > 0 else 0.5
        bw_now = lastf(bbw, 0.01)
        bw_prev3 = float(bbw[-4]) if len(bbw) >= 4 and math.isfinite(bbw[-4]) else bw_now

        adx15, pdi15, mdi15 = adx(k15['h'], k15['l'], k15['c'], 14)
        atr15 = lastf(atr(k15['h'], k15['l'], k15['c'], 14), price * 0.005)
        rsi5 = lastf(rsi(c5, 14), 50.0)
        mfi5 = lastf(mfi(h5, l5, c5, v5, 14), 50.0)
        vwap5 = lastf(vwap_roll(h5, l5, c5, v5, 96), price)

        e9_5, e21_5, e50_5 = lastf(ema(c5, 9), price), lastf(ema(c5, 21), price), \
            lastf(ema(c5, 50), price)
        e21s = ema(k15['c'], 21)
        e21_15 = lastf(e21s, price)
        e21_15_p3 = float(e21s[-4]) if len(e21s) >= 4 and math.isfinite(e21s[-4]) else e21_15
        e50_60 = lastf(ema(k60['c'], 50), price)
        e21_240 = lastf(ema(k240['c'], 21), price)

        _, _, mh = macd(c5)
        macd_hist = lastf(mh, 0.0)

        roc5 = float((c5[-1] / c5[-6] - 1.0) * 100.0) if len(c5) >= 6 else 0.0
        burst1m = float((k1['c'][-1] / k1['c'][-4] - 1.0) * 100.0) if len(k1['c']) >= 4 else 0.0
        vol_z = zscore_last(v5, 50)
        last_candle_dir = 1.0 if c5[-1] > c5[-2] else (-1.0 if c5[-1] < c5[-2] else 0.0)

        obv_arr = obv(c5, v5)
        obv_slope = 0.0
        if len(obv_arr) >= 11:
            diffs = np.abs(np.diff(obv_arr)[-50:])
            denom = float(np.mean(diffs)) + 1e-12
            obv_slope = float((obv_arr[-1] - obv_arr[-10]) / denom)

        pct_chg_15m = float((c5[-1] / c5[-4] - 1.0) * 100.0) if len(c5) >= 4 else 0.0

        # ═══ v2.0 مؤشرات صائد الأرباح — أطر أعلى + انحراف + كسر بنية ═══
        e21_60 = lastf(ema(k60['c'], 21), price)
        htf_60 = 1.0 if e21_60 > e50_60 else (-1.0 if e21_60 < e50_60 else 0.0)
        htf_240 = 1.0 if price > e21_240 else -1.0
        htf_bias = (htf_60 + htf_240) / 2.0

        rsi_div = 0.0
        try:
            rsi_arr = rsi(c5, 14)
            n = min(34, len(c5) - 1)
            if n >= 20:
                c_seg = np.asarray(c5[-n:], dtype=float)
                r_seg = rsi_arr[-n:]
                h1 = n // 2
                lo1, lo2 = int(np.argmin(c_seg[:h1])), h1 + int(np.argmin(c_seg[h1:]))
                hi1, hi2 = int(np.argmax(c_seg[:h1])), h1 + int(np.argmax(c_seg[h1:]))
                if c_seg[lo2] < c_seg[lo1] and r_seg[lo2] > r_seg[lo1] + 1.0:
                    rsi_div = 1.0      # انحراف صاعد: قاع أدنى بزخم أقوى
                elif c_seg[hi2] > c_seg[hi1] and r_seg[hi2] < r_seg[hi1] - 1.0:
                    rsi_div = -1.0     # انحراف هابط: قمة أعلى بزخم أضعف
        except Exception:
            rsi_div = 0.0

        structure_break = 0
        try:
            if len(h5) >= 21:
                dc_hi = float(np.max(h5[-21:-1]))
                dc_lo = float(np.min(l5[-21:-1]))
                if c5[-1] > dc_hi:
                    structure_break = 1
                elif c5[-1] < dc_lo:
                    structure_break = -1
        except Exception:
            structure_break = 0

        pullback_atr = (e21_5 - price) / max(atr5, 1e-12)
        burst_dir = 1.0 if burst1m > 0.02 else (-1.0 if burst1m < -0.02 else 0.0)

        # تغير العقود المفتوحة (آخر 20 دقيقة)
        oi_chg = None
        now = time.time()
        hist = [x for x in md.oi_hist if now - x[0] <= 1200]
        if len(hist) >= 2:
            t0, o0 = hist[0]
            t1, o1 = hist[-1]
            if (t1 - t0) >= 480 and o0 > 0:
                oi_chg = (o1 / o0 - 1.0) * 100.0

        return {
            'price': price, 'spread_bps': spread_bps,
            'atr5': atr5, 'atr_pct_pctile': atr_pct_pctile, 'atr15': atr15,
            'bbw_pctile': bbw_pctile, 'pct_b': pct_b, 'bw_now': bw_now,
            'bw_prev3': bw_prev3, 'adx15': adx15, 'pdi15': pdi15, 'mdi15': mdi15,
            'rsi5': rsi5, 'mfi5': mfi5, 'vwap5': vwap5,
            'e9_5': e9_5, 'e21_5': e21_5, 'e50_5': e50_5,
            'e21_15': e21_15, 'e21_15_p3': e21_15_p3,
            'e50_60': e50_60, 'e21_240': e21_240,
            'macd_hist': macd_hist, 'roc5': roc5, 'burst1m': burst1m,
            'vol_z': vol_z, 'last_candle_dir': last_candle_dir,
            'obv_slope': obv_slope, 'pct_chg_15m': pct_chg_15m,
            'oi_chg_pct': oi_chg, 'funding': md.funding,
            # ═══ v2.0 مؤشرات صائد الأرباح ═══
            'e21_60': e21_60, 'htf_bias': htf_bias, 'rsi_div': rsi_div,
            'structure_break': structure_break, 'pullback_atr': pullback_atr,
            'burst_dir': burst_dir,
        }
    except Exception:
        return None


# ============================================================================
# 🧭 كاشف نوع السوق — البوت يعرف السوق ويتعامل معه
# ============================================================================
REGIME_PARAMS = {
    # name: (sl_mult, rr, hold_min, size_mult)
    'TREND_UP':     (1.15, RR_TREND, HOLD_TREND_MIN, 1.00),
    'TREND_DOWN':   (1.15, RR_TREND, HOLD_TREND_MIN, 1.00),
    'RANGE':        (1.00, RR_RANGE, HOLD_RANGE_MIN, 0.90),
    'VOLATILE_CHOP': (1.35, RR_CHOP, HOLD_CHOP_MIN, 0.50),
    'SQUEEZE':      (1.00, 1.50, 30, 0.0),
    'DEAD':         (1.00, 1.50, 30, 0.0),
}


def detect_regime(ind):
    ap = ind['atr_pct_pctile']
    bp = ind['bbw_pctile']
    a15 = ind['adx15']
    name = 'RANGE'
    if ap < 12 or bp < 12:
        name = 'SQUEEZE' if bp < 12 else 'DEAD'
    elif ap > 90 and a15 < 20:
        name = 'VOLATILE_CHOP'
    elif a15 >= 23:
        if ind['pdi15'] > ind['mdi15'] * 1.05:
            name = 'TREND_UP'
        elif ind['mdi15'] > ind['pdi15'] * 1.05:
            name = 'TREND_DOWN'
    sl_mult, rr, hold_min, size_mult = REGIME_PARAMS[name]
    strong = name in ('TREND_UP', 'TREND_DOWN') and a15 >= 32
    if strong:
        size_mult *= 1.10
    return {'name': name, 'strong': strong, 'sl_mult': sl_mult,
            'rr': rr, 'hold_min': hold_min, 'size_mult': size_mult}


# ============================================================================
# 🏛️ ركائز التقييم السبع — كل ركيزة من -100 إلى +100
# ============================================================================
def _score_trend(ind):
    """[T] بنية الاتجاه متعدد الأطر + قوة ADX."""
    s = 0.0
    px = ind['price']
    e9, e21, e50 = ind['e9_5'], ind['e21_5'], ind['e50_5']
    if e9 > e21 > e50:
        stack = 40.0 if px > e9 else 25.0
    elif e9 < e21 < e50:
        stack = -40.0 if px < e9 else -25.0
    else:
        stack = 0.0
    s += stack * 0.35
    a15 = max(ind['atr15'], 1e-12)
    slope = (ind['e21_15'] - ind['e21_15_p3']) / (a15 * 3.0)
    s += clamp(slope * 100.0) * 0.20
    if ind['e50_60'] > 0:
        rel = px / ind['e50_60'] - 1.0
        s += clamp(rel * 4000.0) * 0.20
    s += (60.0 if px > ind['e21_240'] else -60.0) * 0.10
    if ind['adx15'] > 22:
        w = 0.15 if ind['adx15'] > 30 else 0.10
        s += clamp((ind['pdi15'] - ind['mdi15']) * 6.0) * w
    # v2.0: انحياز الأطر الأعلى (1h/4h) — أقوى مرشح اتجاهي على الإطلاق
    s += clamp(ind.get('htf_bias', 0.0) * 55.0) * 0.15
    return clamp(s)


def _score_momentum(ind):
    """[M] الزخم عبر RSI/MACD/ROC/انفجار الدقيقة."""
    s = 0.0
    s += clamp((ind['rsi5'] - 50.0) * 5.0) * 0.30
    a = max(ind['atr5'], 1e-12)
    s += clamp(ind['macd_hist'] / (a * 0.35) * 60.0) * 0.25
    s += clamp(ind['roc5'] * 80.0) * 0.20
    s += clamp(ind['burst1m'] * 300.0) * 0.25
    # v2.0: كسر بنية 20 شمعة (Donchian) — تأكيد اختراق حقيقي لا وهمي
    s += clamp(ind.get('structure_break', 0) * 45.0) * 0.15
    return clamp(s)


def _score_volatility(ind):
    """[V] اتجاه التقلب: موقع بولنجر × التوسع."""
    expanding = ind['bw_now'] > ind['bw_prev3'] * 1.05
    base = (ind['pct_b'] - 0.5) * 160.0
    return clamp(base * (1.25 if expanding else 0.45))


def _score_flow(ind, md):
    """[F] الحجم والتدفق: MFI + نسبة المنفذين + حجم + OBV."""
    s = 0.0
    s += clamp(ind['vol_z'] * 30.0) * ind['last_candle_dir'] * 0.15
    s += clamp((ind['mfi5'] - 50.0) * 4.0) * 0.30
    bv = sv = 0.0
    try:
        for t in md.trades:
            amt = float(t.get('amount') or 0)
            if amt <= 0:
                continue
            if t.get('side') == 'buy':
                bv += amt
            elif t.get('side') == 'sell':
                sv += amt
    except Exception:
        pass
    tot = bv + sv
    if tot > 0:
        ratio = bv / tot
        s += clamp((ratio - 0.5) * 300.0) * 0.40
    s += clamp(ind['obv_slope'] * 8.0) * 0.15
    return clamp(s)


def _obi(book, levels=15):
    try:
        bids = book['bids'][:levels]
        asks = book['asks'][:levels]
        bv = sum(float(b[1]) for b in bids)
        av = sum(float(a[1]) for a in asks)
        if bv + av <= 0:
            return 0.0
        obi15 = (bv - av) / (bv + av)
        b5 = sum(float(b[1]) for b in bids[:5])
        a5 = sum(float(a[1]) for a in asks[:5])
        obi5 = (b5 - a5) / (b5 + a5) if (b5 + a5) > 0 else 0.0
        return 0.65 * obi15 + 0.35 * obi5
    except Exception:
        return 0.0


def _score_orderbook(md):
    """[B] ضغط دفتر الأوامر + زخم عدم التوازن."""
    obi_now = _obi(md.book)
    s = clamp(obi_now * 120.0)
    if md.prev_obi is not None:
        s += clamp((obi_now - md.prev_obi) * 150.0, -40.0, 40.0)
    md.prev_obi = obi_now
    return clamp(s)


def _score_derivatives(ind, md):
    """[D] المشتقات: تمويل عكسي + مصفوفة OI/السعر."""
    s = 0.0
    fr = float(ind.get('funding') or 0.0)
    if fr > 0.0005:
        s -= min(fr / 0.001, 1.5) * 40.0
    elif fr < -0.0005:
        s += min(-fr / 0.001, 1.5) * 40.0
    oic = ind.get('oi_chg_pct')
    dp = ind.get('pct_chg_15m', 0.0)
    if oic is not None:
        if oic > 0.25 and dp > 0.10:
            s = s * 0.5 + 45.0
        elif oic > 0.25 and dp < -0.10:
            s = s * 0.5 - 45.0
        elif oic < -0.25 and dp > 0.10:
            s = s * 0.5 + 30.0
        elif oic < -0.25 and dp < -0.10:
            s = s * 0.5 - 30.0
    return clamp(s)


def _score_gravity(ind):
    """[G] جاذبية الارتداد: المسافة عن VWAP + تشبعات + %B."""
    s = 0.0
    d = (ind['price'] - ind['vwap5']) / max(ind['atr5'], 1e-12)
    s -= clamp(d * 35.0)
    r = ind['rsi5']
    if r > 76:
        s -= 30.0
    elif r < 24:
        s += 30.0
    pb = ind['pct_b']
    if pb > 0.97:
        s -= 25.0
    elif pb < 0.03:
        s += 25.0
    # v2.0: انحراف RSI — أقوى إشارة ارتداد (صيد القيعان/القمم الحقيقية)
    s += clamp(ind.get('rsi_div', 0.0) * 35.0) * 0.20
    return clamp(s)


def composite_score(pillars, regime_name):
    """أوزان تكيفية حسب نوع السوق ثم تجميع نهائي -100..+100."""
    W = dict(BASE_WEIGHTS)
    if regime_name in ('TREND_UP', 'TREND_DOWN'):
        W['trend'] *= 1.30
        W['grav'] *= 0.40
        W['mom'] *= 1.10
    elif regime_name == 'RANGE':
        W['trend'] *= 0.45
        W['grav'] *= 1.90
        W['mom'] *= 0.75
        W['book'] *= 1.20
    elif regime_name == 'VOLATILE_CHOP':
        W['grav'] *= 0.60
        W['vol'] *= 0.50
        W['book'] *= 0.80
    total = sum(W.values())
    W = {k: v / total for k, v in W.items()}
    score = sum(pillars.get(k, 0.0) * W[k] for k in PILLAR_ORDER)
    score = clamp(score)
    agreement = sum(1 for k in PILLAR_ORDER
                    if pillars.get(k, 0.0) * score > 0 and abs(pillars.get(k, 0.0)) > 10)
    return score, agreement, W


def build_snapshot(md):
    """يبني لقطة كاملة للسوق: سعر + نظام + 7 ركائز + درجة مركبة + بوابات."""
    ind = compute_indicators(md)
    if ind is None:
        return None
    regime = detect_regime(ind)
    pillars = {
        'trend': _score_trend(ind),
        'mom': _score_momentum(ind),
        'vol': _score_volatility(ind),
        'flow': _score_flow(ind, md),
        'book': _score_orderbook(md),
        'deriv': _score_derivatives(ind, md),
        'grav': _score_gravity(ind),
    }
    score, agreement, weights = composite_score(pillars, regime['name'])
    max_spread = MAX_SPREAD_BPS.get(md.symbol, DEFAULT_MAX_SPREAD_BPS)
    gates = {
        'spread': ind['spread_bps'] > max_spread,
        'dead': regime['name'] in ('DEAD', 'SQUEEZE'),
        'extreme_vol': ind['atr_pct_pctile'] > 92,
    }
    return {
        'price': ind['price'], 'atr': ind['atr5'],
        'atr_pctile': ind['atr_pct_pctile'], 'bbw_pctile': ind['bbw_pctile'],
        'spread_bps': ind['spread_bps'], 'regime': regime,
        'pillars': pillars, 'score': score, 'agreement': agreement,
        'weights': weights, 'gates': gates, 'funding': ind['funding'],
        'oi_chg_pct': ind.get('oi_chg_pct'), 'ts': time.time(),
        # ═══ v2.0: حقول بوابات الانصهار الصارم ═══
        'rsi5': ind['rsi5'], 'vol_z': ind['vol_z'],
        'last_dir': ind['last_candle_dir'],
        'htf_bias': ind.get('htf_bias', 0.0), 'rsi_div': ind.get('rsi_div', 0.0),
        'structure_break': ind.get('structure_break', 0),
        'burst_dir': ind.get('burst_dir', 0.0),
    }


def entry_confluence(snap, dir_):
    """🌬️ v2.1: شروط الانصهار — 6 فحوص نوعية فوق الدرجة المركبة (مخففة):
      1) HTF   : الأطر الأعلى (1h/4h) ليست ضد الاتجاه
      2) MOM   : ركيزة الزخم تؤكد (+8 على الأقل مع الاتجاه — كان 12)
      3) FLOW  : ركيزة التدفق (حجم/MFI/منفذون/OBV) تؤكد (+6 — كان 10)
      4) RSI   : منطقة ملائمة (ترند شراء 42-75 / بيع 25-58؛
                 رينج: تطرف لصالح الاتجاه ≤42 / ≥58 — كانت 38/62)
      5) VOL   : تأكيد حجم أو انفجار دقيقة باتجاه الصفقة (0.2 — كان 0.3)
      6) STR   : كسر بنية 20 شمعة أو انحراف RSI باتجاه الصفقة
    v2.1: المطلوب 3/6 بدل 4/6 (v2.0 خنقت الدخول تمامًا).
    """
    reg = snap['regime']['name']
    p = snap['pillars']
    r = float(snap.get('rsi5') or 50.0)
    if reg in ('TREND_UP', 'TREND_DOWN'):
        rsi_ok = (42.0 <= r <= 75.0) if dir_ > 0 else (25.0 <= r <= 58.0)
    else:                                     # RANGE / CHOP
        rsi_ok = (r <= 42.0) if dir_ > 0 else (r >= 58.0)
    checks = {
        'HTF':  float(snap.get('htf_bias') or 0.0) * dir_ > -0.5,
        'MOM':  p.get('mom', 0.0) * dir_ >= 8.0,
        'FLOW': p.get('flow', 0.0) * dir_ >= 6.0,
        'RSI':  rsi_ok,
        'VOL':  (float(snap.get('vol_z') or 0.0) >= 0.2 and
                 snap.get('last_dir') == dir_) or
                snap.get('burst_dir') == dir_,
        'STR':  snap.get('structure_break') == dir_ or
                snap.get('rsi_div') == dir_,
    }
    return checks, sum(1 for v in checks.values() if v)


def evaluate_signal(snap):
    """قرار الدخول v2.1 🌬️ التنفس — الدرجة المركبة + بوابات النظام +
    انصهار نوعي (3/6). CHOP عاد للعمل بعتبة عالية 62 وحجم نصفي —
    v2.0 حجبته كليًا فخنقت البوت بلا داعٍ (الترشيد بالعتبة والحجم
    يكفي، الحرمان الكلي يقتل التنفس)."""
    reg = snap['regime']['name']
    if reg in ('DEAD', 'SQUEEZE'):
        return {'ok': False, 'dir': 0, 'need': 99.0,
                'why': f"regime {reg} (no edge)", 'near': False, 'conf': 0}
    if snap['gates'].get('spread'):
        return {'ok': False, 'dir': 0, 'need': 99.0,
                'why': f"spread {snap['spread_bps']:.1f}bps too wide",
                'near': False, 'conf': 0}
    score = snap['score']
    dir_ = 1 if score > 0 else -1
    mag = abs(score)
    need = ENTRY_THRESHOLD_BASE
    if reg in ('TREND_UP', 'TREND_DOWN'):
        rdir = 1 if reg == 'TREND_UP' else -1
        if dir_ != rdir:
            return {'ok': False, 'dir': dir_, 'need': need,
                    'why': 'counter-trend blocked in trend regime',
                    'near': False, 'conf': 0}
        need = ENTRY_THRESHOLD_TREND
    elif reg == 'RANGE':
        need = ENTRY_THRESHOLD_RANGE
        if snap['pillars']['grav'] * dir_ < 8:
            return {'ok': False, 'dir': dir_, 'need': need,
                    'why': 'range entry needs an extreme (gravity pillar)',
                    'near': False, 'conf': 0}
    elif reg == 'VOLATILE_CHOP':
        need = ENTRY_THRESHOLD_CHOP     # 🌬️ v2.1: عتبة عالية بدل الحجب
    if mag < need:
        return {'ok': False, 'dir': dir_, 'need': need,
                'why': f"score {score:+.0f} < {need:.0f}",
                'near': mag >= need * 0.72, 'conf': 0}
    if snap['agreement'] < AGREEMENT_MIN:
        return {'ok': False, 'dir': dir_, 'need': need,
                'why': f"agreement {snap['agreement']}/7 < {AGREEMENT_MIN}",
                'near': True, 'conf': 0}
    # 🌬️ v2.1: الانصهار النوعي — 3/6 يكفي (كان 4/6 خانقًا)
    checks, conf = entry_confluence(snap, dir_)
    if conf < CONFLUENCE_MIN:
        passed = ''.join(k[0] for k, v in checks.items() if v) or '—'
        return {'ok': False, 'dir': dir_, 'need': need,
                'why': f"confluence {conf}/6 [{passed}]",
                'near': conf >= CONFLUENCE_MIN - 1, 'conf': conf}
    # 🌬️ v2.1: الترند ضد HTF لم يعد حجبًا مطلقًا — يتطلب انصهارًا أعلى
    # 4/6 (زخم قوي مثبت من مصادر متعددة) بدل الحرمان الكامل
    if reg in ('TREND_UP', 'TREND_DOWN') and not checks['HTF']:
        if conf < CONFLUENCE_MIN_STRICT:
            return {'ok': False, 'dir': dir_, 'need': need,
                    'why': f'counter-HTF needs {CONFLUENCE_MIN_STRICT}/6 fusion',
                    'near': True, 'conf': conf}
    # الرينج يتطلب تطرف RSI لصالح الاتجاه (إلزامي — منطق الارتداد نفسه،
    # لكن النطاقات أوسع في v2.1: 42/58 بدل 38/62)
    if reg == 'RANGE' and not checks['RSI']:
        return {'ok': False, 'dir': dir_, 'need': need,
                'why': 'range entry needs RSI extreme',
                'near': True, 'conf': conf}
    return {'ok': True, 'dir': dir_, 'need': need, 'why': 'PASS',
            'near': False, 'conf': conf, 'checks': checks}


# ============================================================================
# 📋 حالة الصفقة
# ============================================================================
@dataclass
class PositionState:
    symbol: str
    side: str              # 'LONG' | 'SHORT'
    qty: float
    entry_price: float
    initial_sl: float
    initial_tp: float
    current_sl: float
    current_tp: float
    entry_time: float
    entry_score: float
    entry_regime: str
    atr_entry: float
    sl_order_id: str = None
    tp_order_id: str = None
    r_unit: float = 0.0
    locked: bool = False           # تفعّل بعد إعادة التقييم عند 70% من الهدف
    lock_mode: str = ""            # RIDE / SECURE / BAIL
    loss_reval_ts: float = 0.0
    stag_extended: bool = False
    adopted: bool = False
    reval_count: int = 0
    high_water_R: float = 0.0
    last_price: float = 0.0
    last_pnl_R: float = 0.0
    entry_atr_pctile: float = 50.0
    deviation_active: bool = False
    deviation_reasons: list = field(default_factory=list)
    closed: bool = False
    heal_fails: int = 0            # v1.4: مرات فشل شفاء الحماية المتتالية
    last_protected: bool = True    # v1.4: آخر حالة حماية مؤكدة (للنبض)
    partial_taken: bool = False    # v2.0: تم جني 50% عند +1R
    partial_try_ts: float = 0.0    # v2.0: تهدئة إعادة محاولة الجني الجزئي


# ============================================================================
# 🤖 البوت
# ============================================================================
class Bot:
    def __init__(self):
        requested = MODE
        self.mode = requested
        if requested == "live" and not LIVE_CONFIRM:
            self.mode = "demo"
        self.ex = self._make_exchange()
        self.md = {s: MarketData(s, self.ex) for s in SYMBOLS}
        self.positions = {}          # symbol -> PositionState
        self.cooldowns = {}          # symbol -> ts حتى مسموح الدخول
        self._near_log = {}
        self._orders_cache = {}
        self._exch_positions = {}
        self._orphan_check = {}         # v1.1: آخر فحص للأوامر اليتيمة
        self._positions_fresh_ts = 0.0  # v1.1: آخر جلب ناجح لحالة الصفقات
        self._err_log_ts = {}
        self.stats = {'trades': 0, 'wins': 0, 'losses': 0,
                      'cum_R': 0.0, 'cum_pnl': 0.0, 'by_reason': Counter()}
        self.wallet = 0.0
        self.free = 0.0
        self.day_key = ''
        self.day_start_eq = None
        self.pause_until = 0.0
        self.last_entry_ts = 0.0
        self.consecutive_losses = 0
        self.cycle_count = 0
        self.cycle_s = CYCLE_SECONDS
        self.err_streak = 0
        self.shutdown = False
        self.auth_failed = False       # مفاتيح غير صالحة → وضع التحليل فقط
        self._auth_log_ts = 0.0
        self._forced_mode_warning = (requested == "live" and self.mode != requested)

    # ------------------------------------------------------------------
    # إعداد الصرف
    # ------------------------------------------------------------------
    def _make_exchange(self):
        keys = API_KEYS.get(self.mode, {'key': '', 'secret': ''})
        ex = ccxt.binanceusdm({
            'apiKey': keys.get('key', ''),
            'secret': keys.get('secret', ''),
            'enableRateLimit': True,
            'timeout': 20000,
            'options': {'defaultType': 'future',
                        'adjustForTimeDifference': True,
                        # مهم للديمو: لا حاجة لعملات سبوت — يجنب استدعاءات sapi
                        # الموقعة التي ترفض مفاتيح الديمو (ملاحظة النسخة السابقة)
                        'fetchCurrencies': False},
        })
        if self.mode == 'testnet':
            try:
                ex.set_sandbox_mode(True)
            except Exception as e:
                log(f"⚠️ sandbox mode: {e}")
        elif self.mode == 'demo':
            self._override_demo_urls(ex)
        return ex

    @staticmethod
    def _override_demo_urls(ex):
        """تحويل كل مسارات fapi إلى خوادم الديمو (نفس أسلوب النسخة السابقة
        الذي كان يعمل — لكن أكثر أمانًا عبر الدمج بدل الاستبدال)."""
        try:
            api = dict(ex.urls.get('api', {}))
            for k in list(api.keys()):
                if k.startswith('fapi') and isinstance(api[k], str):
                    api[k] = api[k].replace('https://fapi.binance.com',
                                            'https://demo-fapi.binance.com')
            ex.urls['api'] = api
        except Exception as e:
            log(f"⚠️ demo URL override failed: {e}")

    def _endpoint_str(self):
        try:
            api = self.ex.urls.get('api', {})
            for k in ('fapi', 'fapiPublic', 'fapiPrivate'):
                if k in api:
                    return str(api[k])
            for k, v in api.items():
                if k.startswith('fapi'):
                    return str(v)
        except Exception:
            pass
        return '?'

    # ------------------------------------------------------------------
    # التشغيل الأولي
    # ------------------------------------------------------------------
    async def startup(self):
        self._banner()
        self._check_ccxt_version()
        if self._forced_mode_warning:
            log("🛑🛑🛑 MODE='live' بدون LIVE_CONFIRM=True → عاد البوت للديمو تلقائيًا 🛑🛑🛑")
        keys = API_KEYS.get(self.mode, {})
        if not keys.get('key'):
            log(f"🛑 لا توجد مفاتيح API لوضع {self.mode} — النقاط الخاصة ستفشل!")
        log(f"⚙️  تحميل الأسواق ({self.mode}) ...")
        try:
            await self.ex.load_markets()
        except ccxt.AuthenticationError as e:
            # خوادم الديمو ترفض حتى النقاط العامة إذا كان المفتاح خاطئًا
            # → ننزع المفتاح ونعيد التحميل كي يعمل التحليل ببيانات حقيقية
            self.auth_failed = True
            self.ex.apiKey = None
            self.ex.secret = None
            log(f"🔑 مفتاح غير صالح عند تحميل الأسواق ({str(e)[:70]}) — "
                f"التحويل لوضع التحليل بلا مفاتيح")
            await self.ex.load_markets()
        if not self.auth_failed:
            try:
                await self.ex.set_position_mode(False)   # وضع الاتجاه الواحد
            except Exception as e:
                log(f"   وضع الاتجاه: {type(e).__name__} (غالبًا مضبوط مسبقًا)")
            await asyncio.gather(*(self._setup_symbol(s) for s in SYMBOLS))
        await self._fetch_balance_safe()
        if self.auth_failed:
            print("", flush=True)
            log("🔑🔑🔑 المفاتيح غير صالحة — البوت سيعمل في وضع التحليل فقط 🔑🔑🔑")
            log("   التحليل الكامل يعمل (أنظمة السوق + الدرجات + الإشارات القريبة)")
            log("   لكن لا يمكن فتح صفقات دون مفاتيح صالحة.")
            if self.mode == 'demo':
                log("   ✦ مفاتيح الديمو تنتهي مدتها! أنشئ مفاتيح جديدة:")
                log("     بينانس ← Futures ← Demo Trading ← API Management ← إنشاء مفتاح")
                log("     ثم الصق المفتاح والسر في API_KEYS['demo'] بأعلى الملف وأعد النشر")
            else:
                log("   ✦ تحقق: صلاحية Futures مفعّلة + قيود IP تشمل عنوان هذا الخادم")
            print("", flush=True)
        else:
            eff = self._eff_equity()
            log(f"💰 المحفظة: ${self.wallet:.2f} | رأس المال الفعلي للتسيير (سقف "
                f"${CAPITAL_CAP_USDT:.0f}): ${eff:.2f}")
            await self.sync_positions(adopt=True)
        log("✅ المحرك جاهز — بدأت حلقة التداول (10 ثوانٍ)")

    async def _setup_symbol(self, sym):
        try:
            await self.ex.set_margin_mode('isolated', sym)
        except Exception:
            pass
        try:
            await self.ex.set_leverage(MAX_LEVERAGE, sym)
        except Exception:
            pass

    def _banner(self):
        lines = [
            "=" * 78,
            "  🧠 QUANTUM SAGE v2.1 — BREATHING PROFIT HUNTER 🌬",
            "=" * 78,
            f"  الوضع            : {self.mode.upper()}  ({self._endpoint_str()})",
            f"  الرموز           : {', '.join(SYMBOLS)}",
            f"  رأس المال        : المحفظة مسقوفة عند ${CAPITAL_CAP_USDT:.0f} لأغراض الحجم",
            f"  المخاطرة/صفقة    : {RISK_PER_TRADE*100:.1f}% | أقصى {MAX_POSITIONS} صفقات | "
            f"رافعة {MAX_LEVERAGE}x معزول",
            f"  فلتر الدخول      : درجة ≥ {ENTRY_THRESHOLD_BASE:.0f} "
            f"(ترند {ENTRY_THRESHOLD_TREND:.0f} / رينج {ENTRY_THRESHOLD_RANGE:.0f} / "
            f"تشوب {ENTRY_THRESHOLD_CHOP:.0f}) + {AGREEMENT_MIN}/7 ركائز + "
            f"انصهار {CONFLUENCE_MIN}/6 (ضد HTF: {CONFLUENCE_MIN_STRICT}/6) — 🌬 v2.1",
            f"  💰 جني جزئي      : عند +1R يقفل {PARTIAL_TP_FRAC:.0%} والوقف → "
            f"بريك-إيفن | ⏱️ قاطع زمني للخاسر الراكد ({TIME_STOP_R}R)",
            f"  إعادة التقييم    : {int(PROFIT_LOCK_TRIGGER*100)}% نحو الهدف → إلغاء SL/TP القديم"
            f" ووضع جديد + تتبع | {int(LOSS_REVAL_TRIGGER*100)}% نحو الوقف → خفض/شد/صبر",
            f"  تنبيه الانحراف    : كل {CYCLE_SECONDS}s في هذا اللوق (الإغلاق يدوي — لا إغلاق تلقائي)",
            f"  نظافة الأوامر    : SL واحد + TP واحد فقط لكل صفقة (تجديد فقط إذا تحرك > "
            f"{MIN_REPLACE_MOVE*100:.1f}%)",
            f"  الحارس 🛡 v1.4  : فحص الحماية كل دورة — نقص SL/TP يُشفى فورًا،"
            f" وفشل {PROTECTION_MAX_HEALS} دورات → إغلاق طارئ (لا مركز مكشوف)",
            "=" * 78,
        ]
        for l in lines:
            print(l, flush=True)

    def _check_ccxt_version(self):
        """v1.1: يظهر إصدار ccxt عند الإقلاع ويحذر إن كان قديمًا —
        الإصدار القديم سبب رئيسي لفشل وضع أوامر SL/TP عبر create_order."""
        try:
            ver = str(getattr(ccxt, '__version__', '') or '')
            log(f"📦 مكتبة ccxt المثبتة: {ver if ver else 'غير معروفة'}")
            head = ver.split('.')[0]
            if head.isdigit() and 0 < int(head) < 4:
                print("", flush=True)
                log("⚠️⚠️ ccxt قديم — أوامر SL/TP قد تفشل عبر create_order!")
                log("   ✦ الحل النهائي على Railway (اختر واحدًا):")
                log("     1) أضف ملف requirements.txt في جذر المشروع يحتوي:")
                log("          ccxt>=4.3.0")
                log("          numpy")
                log("     2) أو اجعل أمر التشغيل Start:")
                log("          pip install -U 'ccxt>=4.3.0' numpy && python main.py")
                log("   (البوت v2.0 يضع الأوامر عبر Algo API الجديدة أو")
                log("    endpoint القديم — يعمل مع أي إصدار ccxt)")
                print("", flush=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # الحساب
    # ------------------------------------------------------------------
    def _eff_equity(self):
        eq = self.wallet
        if CAPITAL_CAP_USDT and CAPITAL_CAP_USDT > 0:
            eq = min(eq, CAPITAL_CAP_USDT)
        return max(eq, 0.0)

    async def _fetch_balance_safe(self):
        try:
            b = await self.ex.fetch_balance()
            usdt = b.get('USDT', {}) or {}
            self.wallet = float(usdt.get('total') or 0.0)
            self.free = float(usdt.get('free') or 0.0)
            if self.auth_failed:
                self.auth_failed = False
                log("🔑 عادت المصادقة للعمل — التداول الفعلي مفعّل من الآن")
        except ccxt.AuthenticationError as e:
            was_ok = not self.auth_failed
            self.auth_failed = True
            # مهم:demo-fapi يرفض حتى النقاط العامة إذا كان المفتاح خاطئًا
            # → نزيل المفتاح كي يستمر جلب بيانات السوق (وضع التحليل)
            if getattr(self.ex, 'apiKey', None):
                self.ex.apiKey = None
                self.ex.secret = None
            if was_ok or time.time() - self._auth_log_ts > 900:
                self._auth_log_ts = time.time()
                log(f"🔑 مصادقة فاشلة ({str(e)[:80]}) — وضع التحليل فقط: "
                    f"التحليل يعمل ولا تُفتح صفقات. أنشئ مفاتيح جديدة والصقها في "
                    f"API_KEYS['{self.mode}'] ثم أعد النشر")
        except Exception as e:
            if time.time() - self._err_log_ts.get('balance', 0) > 300:
                self._err_log_ts['balance'] = time.time()
                log(f"⚠️ فشل جلب الرصيد: {type(e).__name__}: {str(e)[:120]}")
        return self.wallet, self.free

    async def _fetch_positions_map(self):
        out = {}
        try:
            raw = await self.ex.fetch_positions()
        except Exception as e:
            if time.time() - self._err_log_ts.get('positions', 0) > 300:
                self._err_log_ts['positions'] = time.time()
                log(f"⚠️ فشل جلب الصفقات: {type(e).__name__}: {str(e)[:120]}")
            return self._exch_positions
        for p in raw or []:
            try:
                sym = p.get('symbol')
                if sym not in SYMBOLS:
                    continue
                info = p.get('info') or {}
                try:
                    amt = float(info.get('positionAmt') or 0)
                except (TypeError, ValueError):
                    amt = 0.0
                if amt == 0:
                    try:
                        amt = float(p.get('contracts') or 0)
                        if p.get('side') == 'short':
                            amt = -amt
                    except (TypeError, ValueError):
                        amt = 0.0
                if amt == 0:
                    continue
                try:
                    entry = float(info.get('entryPrice') or p.get('entryPrice') or 0)
                except (TypeError, ValueError):
                    entry = 0.0
                try:
                    upnl = float(info.get('unRealizedProfit')
                                 or p.get('unrealizedPnl') or 0)
                except (TypeError, ValueError):
                    upnl = 0.0
                out[sym] = {'side': 'LONG' if amt > 0 else 'SHORT',
                            'qty': abs(amt), 'entry': entry, 'upnl': upnl}
            except Exception:
                continue
        self._exch_positions = out
        self._positions_fresh_ts = time.time()   # v1.1: جلب ناجح للصفقات
        return out

    async def _open_orders(self, sym, force=False):
        """v1.3: الأوامر المفتوحة = العادية + الشرطية (Algo API) مدموجة —
        بينانس نقلت SL/TP إلى openAlgoOrders فلا تظهر في endpoint القديم."""
        now = time.time()
        cached = self._orders_cache.get(sym)
        if not force and cached and now - cached['ts'] < 8:
            return cached['list']
        merged = []
        old_failed = False
        try:
            lst = await self.ex.fetch_open_orders(sym)
            merged.extend(lst or [])
        except Exception as e:
            old_failed = True
            if time.time() - self._err_log_ts.get('orders:' + sym, 0) > 300:
                self._err_log_ts['orders:' + sym] = time.time()
                log(f"⚠️ fetch_open_orders {sym}: {type(e).__name__}")
        algo_failed = False
        try:
            algo = await self.ex.fapiPrivateGetOpenAlgoOrders(
                {'symbol': self.ex.market_id(sym)})
            for row in (algo or []):
                try:
                    if not row.get('algoId'):
                        continue
                    merged.append({
                        'id': str(row.get('algoId')),
                        'type': row.get('orderType'),
                        'stopPrice': float(row.get('triggerPrice') or 0),
                        'amount': float(row.get('quantity') or 0),
                        'status': row.get('algoStatus'),
                        'algo': True, 'info': row,
                    })
                except Exception:
                    continue
        except Exception as e:
            algo_failed = True
            if time.time() - self._err_log_ts.get('algoorders:' + sym, 0) > 300:
                self._err_log_ts['algoorders:' + sym] = time.time()
                log(f"⚠️ openAlgoOrders {sym}: {type(e).__name__}")
        # v1.4: فشل المصدران معًا؟ الكاش القديم إن وُجد، وإلا "مجهول" (None)
        # — لا نُعيد قائمة فارغة كاذبة تستفز شفاءً أعمى وتكرارًا للأوامر
        if old_failed and algo_failed:
            if cached:
                return cached['list']
            return None
        self._orders_cache[sym] = {'ts': now, 'list': merged}
        return merged

    async def _find_existing_stop(self, sym, otype):
        """v1.4: ابحث عن أمر وقف قائم من نوع معيّن على الصرف (لتبنّيه
        عند تعارض -4130 بدل وضع نسخة مكررة)."""
        try:
            lst = await self._open_orders(sym, force=True)
        except Exception:
            return None
        if not lst:
            return None
        for o in lst:
            if _otype(o) == otype:
                return o
        return None

    # ------------------------------------------------------------------
    # أوامر الحماية: SL/TP — وضع / إلغاء / تجديد / شفاء
    # ------------------------------------------------------------------
    async def _place_stop_order(self, pos, kind, stop_price, conflict_ok=False):
        """kind='SL' أو 'TP' — v1.3: سلسلة 6 محاولات (Algo API الجديدة
        أولًا — بينانس نقلت الأوامر الشرطية إليها والقديم يرد بالخطأ -4120):
          1) ALGO closePosition   (algotype=conditional)
          2) ALGO quantity+reduceOnly (تتعايش مع القديم عند -4130)
          3) قديم خام closePosition | 4) قديم ccxt closePosition
          5) قديم خام reduceOnly   | 6) قديم ccxt reduceOnly
        conflict_ok=True أثناء التجديد: تعارض -4130 متوقع (القديم قائم)
        فيسكت اللوج وينتقل لصيغة الكمية مباشرة.
        v1.4: conflict_ok=False (مسار الشفاء): -4130 يعني أن أمرًا قائمًا
        يحمي بالفعل → يُتبنّى القائم بدل وضع نسخة كمية مكررة."""
        side = 'sell' if pos.side == 'LONG' else 'buy'
        otype = 'STOP_MARKET' if kind == 'SL' else 'TAKE_PROFIT_MARKET'
        sp_str = f"{stop_price:.10g}"
        try:
            sp_str = self.ex.price_to_precision(pos.symbol, stop_price)
            stop_price = float(sp_str)
        except Exception:
            pass

        def _cid(n):
            return f"QS1{kind}{int(time.time() * 1000)}{n}"[:36]

        # 1) ALGO: closePosition — المسار الأساسي على الخوادم الجديدة
        try:
            r = await self.ex.fapiPrivatePostAlgoOrder({
                'symbol': self.ex.market_id(pos.symbol),
                'side': side.upper(),
                'algotype': 'conditional',
                'type': otype,
                'triggerprice': sp_str,
                'closePosition': 'true',
                'workingType': 'CONTRACT_PRICE',
            })
            if r and r.get('algoId'):
                log(f"✅ وُضع {kind} [{pos.symbol}] @ {sp_str} "
                    f"(Algo closePosition) #{r['algoId']}")
                return {'id': str(r['algoId']),
                        'stopPrice': r.get('triggerPrice') or sp_str,
                        'algo': True}
        except Exception as e1:
            if '-4130' in str(e1):
                if conflict_ok:
                    log(f"   {kind}: closePosition مشغول بالقديم → صيغة "
                        f"الكمية (متوقع أثناء التجديد)")
                else:
                    # v1.4: -4130 = يوجد أمر closePosition قائم من نفس
                    # النوع/الاتجاه → المركز محمي فعلًا! لا نكمل لصيغة
                    # الكمية (تكرار) — نتبنّى القائم أو نعيد علامة وجود
                    exist = await self._find_existing_stop(pos.symbol, otype)
                    if exist is not None:
                        log(f"✅ {kind} [{pos.symbol}] قائم بالفعل "
                            f"#{exist.get('id')} — تبنّي بدل التكرار")
                        return exist
                    log(f"🛡️ {kind} [{pos.symbol}]: تعارض -4130 (أمر قائم "
                            f"لم يُقرأ الآن) — محمي، ويُعاد التحقق لاحقًا")
                    return {'id': None, 'stopPrice': sp_str, 'exists': True}
            else:
                log(f"   {kind}: محاولة 1 (Algo closePosition): "
                    f"{str(e1)[:100]}")
        # 2) ALGO: quantity + reduceOnly — تتعايش مع الأمر القديم
        try:
            q = None
            try:
                q = self.ex.amount_to_precision(pos.symbol, pos.qty)
            except Exception:
                q = f"{pos.qty:.8f}".rstrip('0').rstrip('.')
            r = await self.ex.fapiPrivatePostAlgoOrder({
                'symbol': self.ex.market_id(pos.symbol),
                'side': side.upper(),
                'algotype': 'conditional',
                'type': otype,
                'triggerprice': sp_str,
                'quantity': q,
                'reduceOnly': 'true',
                'workingType': 'CONTRACT_PRICE',
            })
            if r and r.get('algoId'):
                log(f"✅ وُضع {kind} [{pos.symbol}] @ {sp_str} "
                    f"(Algo reduceOnly) #{r['algoId']}")
                return {'id': str(r['algoId']),
                        'stopPrice': r.get('triggerPrice') or sp_str,
                        'algo': True}
        except Exception as e2:
            log(f"   {kind}: محاولة 2 (Algo reduceOnly): {str(e2)[:100]}")
        # 3) قديم خام: closePosition
        try:
            r = await self.ex.fapiPrivatePostOrder({
                'symbol': self.ex.market_id(pos.symbol),
                'side': side.upper(),
                'type': otype,
                'stopPrice': sp_str,
                'closePosition': 'true',
                'workingType': 'CONTRACT_PRICE',
                'priceProtect': 'TRUE',
                'newClientOrderId': _cid(1),
            })
            if r and r.get('orderId'):
                log(f"✅ وُضع {kind} [{pos.symbol}] @ {sp_str} "
                    f"(خام closePosition) #{r['orderId']}")
                return {'id': str(r['orderId']), 'stopPrice': sp_str}
        except Exception as e3:
            log(f"   {kind}: محاولة 3 (خام closePosition): {str(e3)[:100]}")
        # 4) قديم ccxt: closePosition
        try:
            o = await self.ex.create_order(
                pos.symbol, otype, side, None, None,
                {'stopPrice': stop_price, 'closePosition': True,
                 'workingType': 'CONTRACT_PRICE', 'priceProtect': 'TRUE',
                 'newClientOrderId': _cid(2)})
            if o and o.get('id'):
                log(f"✅ وُضع {kind} [{pos.symbol}] @ {sp_str} "
                    f"(ccxt closePosition) #{o['id']}")
                return o
        except Exception as e4:
            log(f"   {kind}: محاولة 4 (ccxt closePosition): {str(e4)[:100]}")
        # 5) قديم خام: reduceOnly + الكمية
        try:
            q = None
            try:
                q = self.ex.amount_to_precision(pos.symbol, pos.qty)
            except Exception:
                q = f"{pos.qty:.8f}".rstrip('0').rstrip('.')
            r = await self.ex.fapiPrivatePostOrder({
                'symbol': self.ex.market_id(pos.symbol),
                'side': side.upper(),
                'type': otype,
                'quantity': q,
                'stopPrice': sp_str,
                'reduceOnly': 'true',
                'workingType': 'CONTRACT_PRICE',
                'newClientOrderId': _cid(3),
            })
            if r and r.get('orderId'):
                log(f"✅ وُضع {kind} [{pos.symbol}] @ {sp_str} "
                    f"(خام reduceOnly) #{r['orderId']}")
                return {'id': str(r['orderId']), 'stopPrice': sp_str}
        except Exception as e5:
            log(f"   {kind}: محاولة 5 (خام reduceOnly): {str(e5)[:100]}")
        # 6) قديم ccxt: reduceOnly + الكمية
        try:
            o = await self.ex.create_order(
                pos.symbol, otype, side, pos.qty, None,
                {'stopPrice': stop_price, 'reduceOnly': True,
                 'workingType': 'CONTRACT_PRICE', 'newClientOrderId': _cid(4)})
            if o and o.get('id'):
                log(f"✅ وُضع {kind} [{pos.symbol}] @ {sp_str} "
                    f"(ccxt reduceOnly) #{o['id']}")
                return o
        except Exception as e6:
            log(f"❌ فشل وضع {kind} [{pos.symbol}] بعد 6 محاولات — "
                f"الأخيرة: {str(e6)[:110]}")
            return None

    async def _place_bracket(self, pos):
        sl_o = await self._place_stop_order(pos, 'SL', pos.current_sl)
        tp_o = await self._place_stop_order(pos, 'TP', pos.current_tp)
        pos.sl_order_id = (sl_o or {}).get('id')
        pos.tp_order_id = (tp_o or {}).get('id')
        return {'sl': sl_o, 'tp': tp_o}

    async def _cancel_order_id(self, sym, oid):
        """v1.3: إلغاء أمر محدد بالمعرف — Algo API أولًا (الأوامر الشرطية
        على الخوادم الجديدة لا يراها endpoint القديم) ثم القديم كاحتياط."""
        if not oid:
            return
        # 1) Algo API الجديدة
        try:
            await self.ex.fapiPrivateDeleteAlgoOrder({
                'symbol': self.ex.market_id(sym), 'algoId': oid})
            return
        except Exception:
            pass
        # 2) endpoint القديم
        try:
            await self.ex.cancel_order(oid, sym)
            return
        except Exception:
            pass
        # 3) خام قديم
        try:
            await self.ex.fapiPrivateDeleteOrder({
                'symbol': self.ex.market_id(sym), 'orderId': int(oid)})
        except Exception as e:
            log(f"   إلغاء #{oid} [{sym}]: {type(e).__name__} (قد يكون نُفّذ)")

    async def _cancel_leg(self, pos, leg):
        oid = pos.sl_order_id if leg == 'SL' else pos.tp_order_id
        await self._cancel_order_id(pos.symbol, oid)

    async def _replace_bracket(self, pos, new_sl=None, new_tp=None,
                               reason="", force=False):
        """❗ جوهر 'تجديد الأوامر' v1.3 — ضع الجديد أولًا ثم ألغِ القديم:
          1) يوضع الأمر الجديد على بينانس أولًا والقديم ما زال يحمي.
          2) بعد نجاح وضعه يُلغى القديم فورًا — لا لحظة واحدة بلا حماية.
          3) لو فشل وضع الجديد يبقى القديم حاميًا (لا يُلغى بدون بديل)
             وتُعاد المحاولة في الدورة التالية.
        (بينانس تقبل أمر closePosition واحدًا لكل نوع/اتجاه -4130 → عند
         وجود القديم يوضع الجديد بصيغة quantity+reduceOnly المكافئة
         تمامًا، وبعد إلغاء القديم تعود صيغة closePosition لاحقًا)"""
        px = pos.last_price or pos.entry_price
        changes = []                      # (leg, سعر جديد, معرف الأمر القديم)
        if new_sl is not None:
            try:
                new_sl = float(self.ex.price_to_precision(pos.symbol, new_sl))
            except Exception:
                pass
            valid = (new_sl < px) if pos.side == 'LONG' else (new_sl > px)
            if valid and pos.current_sl and not math.isfinite(pos.current_sl):
                valid = False
            if valid and (force or pos.current_sl is None or
                          abs(new_sl / pos.current_sl - 1.0) > MIN_REPLACE_MOVE):
                changes.append(('SL', new_sl, pos.sl_order_id))
        if new_tp is not None:
            try:
                new_tp = float(self.ex.price_to_precision(pos.symbol, new_tp))
            except Exception:
                pass
            valid = (new_tp > px) if pos.side == 'LONG' else (new_tp < px)
            if valid and (force or pos.current_tp is None or
                          abs(new_tp / pos.current_tp - 1.0) > MIN_REPLACE_MOVE):
                changes.append(('TP', new_tp, pos.tp_order_id))
        if not changes:
            return
        old_sl, old_tp = pos.current_sl, pos.current_tp
        for leg, price, old_id in changes:
            # (1) ضع الجديد أولًا — القديم ما زال قائمًا يحمي المركز
            o = await self._place_stop_order(pos, leg, price, conflict_ok=True)
            if o:
                # (2) الجديد أصبح على بينانس → الآن ألغِ القديم
                if old_id and str(old_id) != str(o.get('id')):
                    await self._cancel_order_id(pos.symbol, old_id)
                if leg == 'SL':
                    pos.sl_order_id = o.get('id')
                    pos.current_sl = price
                else:
                    pos.tp_order_id = o.get('id')
                    pos.current_tp = price
            else:
                # (3) فشل الجديد → القديم يبقى حاميًا (لا إلغاء بدون بديل)
                log(f"⚠️ فشل وضع {leg} الجديد [{pos.symbol}] @ {price} — "
                    f"الأمر القديم يبقى حاميًا وستُعاد المحاولة لاحقًا")
        # تحقق + شفاء فوري
        await self._verify_bracket(pos, reason=reason)
        log(f"♻️ ORDER REFRESH [{pos.symbol} {pos.side}] {reason} | "
            f"SL {old_sl} → {pos.current_sl} | TP {old_tp} → {pos.current_tp}")

    async def _verify_bracket(self, pos, reason=""):
        """يقرأ الأوامر الفعلية على الصرف، يعتمدها، ويشفي المفقود.
        v1.3: يفضّل المعرف المتتبع (أثناء نافذة وجود الجديد+القديم معًا)
        v1.4: قراءة مجهولة → لا شفاء أعمى؛ فشل الشفاء المتكرر → إغلاق طارئ"""
        lst = await self._open_orders(pos.symbol, force=True)
        if lst is None:
            # v1.4: فشلت القراءة من المصدرين — لا قرار على حالة مجهولة؛
            # المتبقي هو آخر حالة معروفة (المعرفات المتتبعة)
            return bool(pos.sl_order_id and pos.tp_order_id)
        sl_o = next((o for o in lst if pos.sl_order_id and
                     str(o.get('id')) == str(pos.sl_order_id)), None) \
            or next((o for o in lst if _otype(o) == 'STOP_MARKET'), None)
        tp_o = next((o for o in lst if pos.tp_order_id and
                     str(o.get('id')) == str(pos.tp_order_id)), None) \
            or next((o for o in lst if _otype(o)
                     in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT')), None)
        px = pos.last_price or pos.entry_price
        atr = pos.atr_entry or px * 0.005
        dir_ = 1 if pos.side == 'LONG' else -1
        healed = []
        missing = []
        if sl_o is None:
            lvl = pos.current_sl
            if not lvl or not math.isfinite(lvl) or \
                    ((dir_ > 0 and lvl >= px) or (dir_ < 0 and lvl <= px)):
                lvl = px - dir_ * 1.3 * atr
                try:
                    lvl = float(self.ex.price_to_precision(pos.symbol, lvl))
                except Exception:
                    pass
            o = await self._place_stop_order(pos, 'SL', lvl)
            if o:
                sl_o = o
                sp = float(o.get('stopPrice') or 0)
                pos.current_sl = sp if sp > 0 else lvl
                if not o.get('exists'):
                    healed.append('SL')
            else:
                missing.append('SL')
        if tp_o is None:
            lvl = pos.current_tp
            if not lvl or not math.isfinite(lvl) or \
                    ((dir_ > 0 and lvl <= px) or (dir_ < 0 and lvl >= px)):
                lvl = px + dir_ * 1.5 * atr
                try:
                    lvl = float(self.ex.price_to_precision(pos.symbol, lvl))
                except Exception:
                    pass
            o = await self._place_stop_order(pos, 'TP', lvl)
            if o:
                tp_o = o
                sp = float(o.get('stopPrice') or 0)
                pos.current_tp = sp if sp > 0 else lvl
                if not o.get('exists'):
                    healed.append('TP')
            else:
                missing.append('TP')
        if sl_o is not None:
            pos.sl_order_id = sl_o.get('id')
            sp = float(sl_o.get('stopPrice') or 0)
            if sp > 0:
                pos.current_sl = sp
        if tp_o is not None:
            pos.tp_order_id = tp_o.get('id')
            sp = float(tp_o.get('stopPrice') or 0)
            if sp > 0:
                pos.current_tp = sp
        if healed:
            log(f"🛡️ [{pos.symbol}] شفاء أوامر الحماية المفقودة: {','.join(healed)} "
                f"({reason})")
        # v1.4: عدّاد فشل الحماية + تصعيد صارم — لا مركز مكشوف أبدًا
        if sl_o is None or tp_o is None:
            pos.last_protected = False
            pos.heal_fails += 1
            if pos.heal_fails >= PROTECTION_MAX_HEALS and not pos.closed:
                print("", flush=True)
                log(f"🆘🆘🆘 [{pos.symbol} {pos.side}] تعذر وضع الحماية "
                    f"{pos.heal_fails} دورات متتالية → إغلاق طارئ بسعر "
                    f"السوق (مركز مغلق أفضل من مركز مكشوف)")
                await self._market_close(pos, 'PROTECTION_FAILED')
                await self._cancel_symbol_orders(pos.symbol)
                return False
            if missing:
                log(f"⚠️ [{pos.symbol}] فشل وضع {','.join(missing)} "
                    f"(محاولة {pos.heal_fails}/{PROTECTION_MAX_HEALS}) — "
                    f"إعادة المحاولة الدورة القادمة")
        else:
            pos.heal_fails = 0
            pos.last_protected = True
        return sl_o is not None

    async def _ensure_bracket(self, pos):
        """كل دورة: يجب أن تكون الصفقة محمية دائمًا بـ SL+TP بالضبط.
        v1.3: يفضّل المعرف المتتبع قبل البحث بالنوع.
        v1.4: قراءة مجهولة → تخطي هذه الدورة (لا شفاء أعمى ولا تكرار)."""
        lst = await self._open_orders(pos.symbol)
        if lst is None:
            return          # v1.4: حالة مجهولة — القرار مؤجل للدورة التالية
        sl_o = next((o for o in lst if pos.sl_order_id and
                     str(o.get('id')) == str(pos.sl_order_id)), None) \
            or next((o for o in lst if _otype(o) == 'STOP_MARKET'), None)
        tp_o = next((o for o in lst if pos.tp_order_id and
                     str(o.get('id')) == str(pos.tp_order_id)), None) \
            or next((o for o in lst if _otype(o)
                     in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT')), None)
        # تحديث المعرفات دائمًا
        if sl_o is not None:
            pos.sl_order_id = sl_o.get('id')
        if tp_o is not None:
            pos.tp_order_id = tp_o.get('id')
        # أمر reduceOnly قديم لا يغطي الكمية الحالية؟ → إعادة وضعه
        if sl_o is not None and pos.qty > 0:
            try:
                amt = float(sl_o.get('amount') or 0)
                if amt > 0 and abs(amt - pos.qty) / max(pos.qty, 1e-9) > 0.02:
                    await self._replace_bracket(pos, new_sl=pos.current_sl,
                                                reason='SL qty ≠ position → resync',
                                                force=True)
                    return
            except (TypeError, ValueError):
                pass
        if sl_o is None or tp_o is None:
            await self._verify_bracket(pos, reason='🛡️ heal')
            return
        # اعتماد التعديلات اليدوية من المستخدم (سحب SL/TP من تطبيق بينانس)
        for o, leg in ((sl_o, 'SL'), (tp_o, 'TP')):
            sp = float(o.get('stopPrice') or 0)
            cur = pos.current_sl if leg == 'SL' else pos.current_tp
            if sp > 0 and cur and abs(sp / cur - 1.0) > 0.0005:
                log(f"👤 {pos.symbol}: حُرّك {leg} يدويًا {cur} → {sp} — تم الاعتماد")
                if leg == 'SL':
                    pos.current_sl = sp
                else:
                    pos.current_tp = sp

    async def _partial_tp(self, pos, px):
        """💰 v2.0: جني أرباح جزئي عند +1R — يقفل 50% بسعر السوق
        وينقل الوقف إلى البريك-إيفن +0.05R (تغطية العمولات):
          * نصف الصفقة يُقفل ربحًا مؤكدًا → رفع نسبة الربح بسلاسة
          * النصف الثاني يجري بلا مخاطرة تقريبًا → الأرباح الكبيرة تبقى
        الأوامر تُجدّد بالترتيب الآمن (الجديد أولًا ثم إلغاء القديم)."""
        if pos.closed or pos.partial_taken:
            return
        now = time.time()
        if now - pos.partial_try_ts < 30:
            return
        pos.partial_try_ts = now
        dir_ = 1 if pos.side == 'LONG' else -1
        half = pos.qty * PARTIAL_TP_FRAC
        try:
            half = float(self.ex.amount_to_precision(pos.symbol, half))
        except Exception:
            half = round(half, 6)
        remain = pos.qty - half
        # لا جزئي لو صار الجزء/الباقي أصغر من الحد الأدنى المقبول للصرف
        try:
            m = self.ex.market(pos.symbol)
            min_qty = float(((m.get('limits') or {}).get('amount') or {})
                            .get('min') or 0.0)
            min_cost = float(((m.get('limits') or {}).get('cost') or {})
                             .get('min') or 5.0)
        except Exception:
            min_qty, min_cost = 0.0, 5.0
        if half <= 0 or remain <= 0 or \
                (min_qty and (half < min_qty or remain < min_qty)) or \
                half * px < min_cost or remain * px < min_cost:
            pos.partial_taken = True   # الكمية صغيرة جدًا للتقسيم — تخطٍ للأبد
            return
        side = 'buy' if pos.side == 'SHORT' else 'sell'
        try:
            await self.ex.create_order(pos.symbol, 'market', side, half,
                                       None, {'reduceOnly': True})
        except Exception as e:
            log(f"⚠️ فشل الجني الجزئي [{pos.symbol}]: {str(e)[:100]} — "
                f"إعادة المحاولة الدورة القادمة (الوقف يحمي)")
            return
        pos.partial_taken = True
        pos.qty = remain
        gained = (px - pos.entry_price) * dir_ * half
        self.stats['by_reason']['PARTIAL_1R'] += 1
        print("", flush=True)
        log(f"💰 جني جزئي [{pos.symbol} {pos.side}] عند +1R: قفل {half} "
            f"(~${gained:+.2f}) | المتبقي {remain} يجري بلا مخاطرة")
        # الوقف → بريك-إيفن +0.05R (والهدف يُعاد وضعه بالكمية الجديدة)
        be = pos.entry_price + dir_ * BE_OFFSET_R * max(pos.r_unit, 1e-9)
        try:
            be = float(self.ex.price_to_precision(pos.symbol, be))
        except Exception:
            pass
        await self._replace_bracket(pos, new_sl=be, new_tp=pos.current_tp,
                                    reason='PARTIAL@1R → بريك-إيفن', force=True)
        print("", flush=True)

    async def _market_close(self, pos, reason):
        side = 'buy' if pos.side == 'SHORT' else 'sell'
        try:
            await self.ex.create_order(pos.symbol, 'market', side, pos.qty,
                                       None, {'reduceOnly': True})
            log(f"✂️ إغلاق بسعر السوق [{pos.symbol} {pos.side}] — {reason}")
            pos.closed = True
        except Exception as e:
            log(f"❌ فشل الإغلاق [{pos.symbol}]: {e} — الوقف على الصرف يبقى حاميًا")

    async def _cancel_symbol_orders(self, sym):
        """v1.3: إلغاء كل أوامر الرمز (عادية + شرطية Algo — cancel_all_orders
        القديم لا يرى الشرطية!) مع تحقق فعلي و3 محاولات — لا أوامر معلقة
        بعد إغلاق الصفقة أبدًا."""
        for _attempt in range(3):
            try:
                await self.ex.cancel_all_orders(sym)          # الأوامر العادية
            except Exception as e:
                log(f"   إلغاء الكل {sym}: {type(e).__name__}")
            try:
                lst = await self._open_orders(sym, force=True)   # + الشرطية
                for o in lst or []:
                    await self._cancel_order_id(sym, o.get('id'))
            except Exception:
                pass
            await asyncio.sleep(0.35)
            lst = await self._open_orders(sym, force=True)
            if lst is None:
                continue          # v1.4: قراءة مجهولة → أعد المحاولة
            if not lst:
                self._orders_cache.pop(sym, None)
                return
        remaining = await self._open_orders(sym, force=True)
        if remaining:
            log(f"⚠️ {sym}: بقي {len(remaining)} أمر بعد 3 محاولات — "
                f"ستُلغى في الدورة القادمة")
        self._orders_cache.pop(sym, None)

    # ------------------------------------------------------------------
    # مزامنة الصفقات مع الصرف
    # ------------------------------------------------------------------
    async def sync_positions(self, adopt=False, snaps=None):
        snaps = snaps or {}
        exch = await self._fetch_positions_map()
        involved = set(list(exch.keys()) + list(self.positions.keys()))
        for sym in involved:
            await self._open_orders(sym, force=True)
        for sym in list(self.positions.keys()):
            if sym not in exch:
                await self._on_position_closed(sym, snaps)
        for sym, p in exch.items():
            pos = self.positions.get(sym)
            if pos is None:
                if adopt:
                    await self._adopt_position(sym, p)
                else:
                    log(f"⚠️ صفقة خارجية {sym} {p['side']} qty {p['qty']} — "
                        f"ليست من البوت ولن تُدار. أغلقها بنفسك أو أعد تشغيل البوت "
                        f"لتبنّيها.")
            else:
                if pos.qty > 0 and p['qty'] > 0 and \
                        abs(p['qty'] - pos.qty) / pos.qty > 0.05:
                    log(f"👤 {sym}: تغيرت الكمية خارجيًا {pos.qty} → {p['qty']} "
                        f"(أوامر closePosition تغطي تلقائيًا)")
                    pos.qty = p['qty']
                if p['entry'] > 0 and pos.entry_price > 0 and \
                        abs(p['entry'] / pos.entry_price - 1.0) > 0.002:
                    log(f"👤 {sym}: تحديث سعر الدخول (متوسط) "
                        f"{pos.entry_price} → {p['entry']}")
                    pos.entry_price = p['entry']

        # 🧹 v1.1: ماسح الأوامر اليتيمة — رمز بلا صفقة لكن مع أوامر SL/TP
        # متبقية (وصل السعر للهدف/الوقف وأُغلقت الصفقة، أو بقيت من جلسة
        # سابقة) → إلغاء تلقائي. يعمل فقط بعد جلب ناجح للصفقات (أمان).
        if time.time() - self._positions_fresh_ts < 90:
            now = time.time()
            for sym in SYMBOLS:
                if sym in exch or sym in self.positions:
                    continue
                if now - self._orphan_check.get(sym, 0) < 45:
                    continue
                self._orphan_check[sym] = now
                lst = await self._open_orders(sym, force=True)
                if lst:
                    log(f"🧹 {sym}: الصفقة مغلقة وبقي {len(lst)} أمر SL/TP → "
                        f"إلغاء تلقائي (وصل الهدف/الوقف)")
                    await self._cancel_symbol_orders(sym)

    async def _protection_guardian(self):
        """🛡️ v1.4 الحارس — القاعدة المطلقة: لا مركز على الصرف بلا SL+TP.
        يعمل كل دورة فوق محرك الإدارة: يفحص الأوامر الفعلية لكل مركز قائم
        (مسجل أو مُتبنّى من جلسة سابقة/إعادة نشر)، وأي رجل مفقودة تُشفى
        فورًا في نفس الدورة؛ فإن تعذر الشفاء 3 دورات متتالية → إغلاق طارئ
        (داخل _verify_bracket). أي مركز خارجي جديد تتبنّه sync_positions
        مباشرة قبل تشغيل الحارس في نفس الدورة."""
        if self.auth_failed:
            return
        # قراءة الصفقات قديمة/فاشلة → لا قرار هذه الدورة (لا نغلق أعمى)
        if time.time() - self._positions_fresh_ts > 120:
            return
        for sym in list(self._exch_positions.keys()):
            pos = self.positions.get(sym)
            if pos is None or pos.closed:
                continue
            lst = await self._open_orders(sym)     # كاش ≤8ث كافٍ هنا
            if lst is None:
                continue                           # مجهول → الدورة القادمة
            has_sl = any(_otype(o) == 'STOP_MARKET' for o in lst)
            has_tp = any(_otype(o) in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT')
                         for o in lst)
            pos.last_protected = has_sl and has_tp
            if not has_sl or not has_tp:
                await self._verify_bracket(pos, reason='🛡️ guardian')

    async def _adopt_position(self, sym, p):
        # v1.4: قراءة مجهولة تُعالج كقائمة فارغة بأمان — لأن -4130 يمنع
        # تكرار أي أمر closePosition قائم لم يُقرأ
        lst = await self._open_orders(sym, force=True) or []
        sl_o = next((o for o in lst if _otype(o) == 'STOP_MARKET'), None)
        tp_o = next((o for o in lst if _otype(o)
                     in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT')), None)
        entry = p['entry'] or 0.0
        if entry <= 0:
            return
        dir_ = 1 if p['side'] == 'LONG' else -1
        sl = float(sl_o.get('stopPrice') or 0) if sl_o else 0.0
        tp = float(tp_o.get('stopPrice') or 0) if tp_o else 0.0
        if not sl:
            sl = entry * (1 - dir_ * 0.006)
        if not tp:
            tp = entry * (1 + dir_ * 0.012)
        try:
            sl = float(self.ex.price_to_precision(sym, sl))
            tp = float(self.ex.price_to_precision(sym, tp))
        except Exception:
            pass
        pos = PositionState(
            symbol=sym, side=p['side'], qty=p['qty'], entry_price=entry,
            initial_sl=sl, initial_tp=tp, current_sl=sl, current_tp=tp,
            entry_time=time.time(), entry_score=0.0, entry_regime='UNKNOWN',
            atr_entry=entry * 0.006, r_unit=abs(entry - sl), adopted=True)
        self.positions[sym] = pos
        if sl_o is None or tp_o is None:
            await self._place_bracket(pos)
            await self._verify_bracket(pos, reason='adopt — وضع الحماية الناقصة')
        log(f"🔁 تبنّي صفقة قائمة {p['side']} {sym} @ {entry} qty {p['qty']} "
            f"(إعادة تشغيل) — SL {pos.current_sl} | TP {pos.current_tp}")

    async def _on_position_closed(self, sym, snaps):
        pos = self.positions.get(sym)
        if pos is None:
            return
        lst = await self._open_orders(sym, force=True) or []
        sl_still = any(_otype(o) == 'STOP_MARKET' for o in lst)
        tp_still = any(_otype(o) in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT')
                       for o in lst)
        snap = snaps.get(sym) or {}
        px = snap.get('price') or pos.last_price or pos.entry_price
        exit_px, reason = await self._infer_exit(pos, sl_still, tp_still, px)
        await self._cancel_symbol_orders(sym)
        net = await self._realized_pnl(pos, exit_px)
        self.positions.pop(sym, None)
        self._bookkeep(pos, exit_px, reason, net)

    async def _infer_exit(self, pos, sl_still, tp_still, fallback_px):
        async def avg_of(oid):
            if not oid:
                return None
            try:
                o = await self.ex.fetch_order(oid, pos.symbol)
                a = o.get('average') or (o.get('info') or {}).get('avgPrice')
                if a and float(a) > 0:
                    return float(a)
            except Exception:
                pass
            return None
        if not tp_still and sl_still:
            a = await avg_of(pos.tp_order_id)
            return (a or fallback_px), 'TP-HIT 🎯'
        if not sl_still and tp_still:
            a = await avg_of(pos.sl_order_id)
            return (a or fallback_px), 'SL-HIT 🛑'
        d_tp = abs(fallback_px - pos.current_tp) / max(pos.current_tp, 1e-9)
        d_sl = abs(fallback_px - pos.current_sl) / max(pos.current_sl, 1e-9)
        if d_tp < d_sl:
            return fallback_px, 'TP-HIT 🎯(inferred)'
        if d_sl < d_tp:
            return fallback_px, 'SL-HIT 🛑(inferred)'
        return fallback_px, 'MANUAL 👤'

    async def _realized_pnl(self, pos, exit_px):
        try:
            trades = await self.ex.fetch_my_trades(
                pos.symbol, since=int(pos.entry_time * 1000), limit=80)
            if trades:
                net = 0.0
                for t in trades:
                    info = t.get('info') or {}
                    pnl = float(info.get('realizedPnl') or 0)
                    fee = abs(float(info.get('commission') or 0))
                    net += pnl - fee
                return net
        except Exception:
            pass
        dir_ = 1 if pos.side == 'LONG' else -1
        gross = (exit_px - pos.entry_price) * dir_ * pos.qty
        fees = (pos.entry_price + exit_px) * pos.qty * 0.0005
        return gross - fees

    def _bookkeep(self, pos, exit_px, reason, net):
        dir_ = 1 if pos.side == 'LONG' else -1
        r = ((exit_px - pos.entry_price) * dir_) / max(pos.r_unit, 1e-9)
        st = self.stats
        st['trades'] += 1
        st['cum_R'] += r
        st['cum_pnl'] += net
        st['by_reason'][reason.split(' ')[0]] += 1
        if r >= 0:
            st['wins'] += 1
            self.consecutive_losses = 0
        else:
            st['losses'] += 1
            self.consecutive_losses += 1
        if self.consecutive_losses >= 3:
            self.pause_until = time.time() + CONSEC_LOSS_PAUSE
            log(f"🧊 3 خسائر متتالية → تهدئة {CONSEC_LOSS_PAUSE // 60} دقيقة "
                f"(لا دخول جديد)")
            self.consecutive_losses = 0
        self.cooldowns[pos.symbol] = time.time() + POST_EXIT_COOLDOWN_S
        held = (time.time() - pos.entry_time) / 60.0
        wr = st['wins'] / st['trades']
        print("", flush=True)
        log(f"🏁 خروج [{pos.symbol} {pos.side}] — {reason}")
        log(f"   دخول {pos.entry_price:.6g} → خروج {exit_px:.6g} | {r:+.2f}R | "
            f"صافي ${net:+.2f} | المدة {held:.0f}د | إعادة تقييم {pos.reval_count}")
        log(f"   الجلسة: {st['trades']} صفقة | ر/خ {st['wins']}/{st['losses']} "
            f"({wr:.0%}) | تراكمي {st['cum_R']:+.1f}R / ${st['cum_pnl']:+.2f}")
        print("", flush=True)


    # ==================================================================
    # 🎯 محرك إدارة الصفقة — إعادة التقييم + التتبع + الانحراف (كل 10 ثوان)
    # ==================================================================
    async def manage_position(self, pos, snap):
        px = snap.get('price') or pos.last_price or pos.entry_price
        atr = snap.get('atr') or pos.atr_entry or px * 0.005
        score = snap.get('score', 0.0)
        regime = (snap.get('regime') or {}).get('name', pos.entry_regime)
        dir_ = 1 if pos.side == 'LONG' else -1
        pos.last_price = px

        r_unit = pos.r_unit if pos.r_unit > 0 else max(pos.entry_price * 0.004, 1e-9)
        move = (px - pos.entry_price) * dir_
        pnl_R = move / r_unit
        pos.last_pnl_R = pnl_R
        pos.high_water_R = max(pos.high_water_R, pnl_R)

        # ---- 0) 💰 v2.0: جني جزئي عند +1R — قفل 50% + وقف بريك-إيفن ----
        if (not pos.partial_taken) and (not pos.closed) and \
                pnl_R >= PARTIAL_TP_R:
            await self._partial_tp(pos, px)

        tp_dist0 = abs(pos.initial_tp - pos.entry_price)
        sl_dist0 = r_unit
        prog_tp = move / tp_dist0 if tp_dist0 > 0 else 0.0
        prog_sl = -move / sl_dist0 if sl_dist0 > 0 else 0.0
        age_min = (time.time() - pos.entry_time) / 60.0

        # ---- 1) قفل الربح عند 70% من الهدف: إعادة تقييم كاملة ----
        # ----    إلغاء SL/TP القديمين ووضع جديدين مكانهم مباشرة      ----
        if (not pos.locked) and prog_tp >= PROFIT_LOCK_TRIGGER:
            pos.reval_count += 1
            aligned = score * dir_
            gain = move                     # > 0 بالضرورة هنا
            if aligned >= 35:
                mode = 'RIDE'               # السوق معنا → مركز الربح يجري
            elif aligned >= 0:
                mode = 'SECURE'             # حياد → تأمين أغلب الربح
            else:
                mode = 'BAIL'               # انقلب → اقفل قريبًا جدًا
            if mode == 'RIDE':
                new_sl = pos.entry_price + dir_ * 0.35 * gain
                new_tp = pos.entry_price + dir_ * 1.50 * tp_dist0
            elif mode == 'SECURE':
                new_sl = pos.entry_price + dir_ * 0.50 * gain
                new_tp = px + dir_ * 0.30 * gain
            else:
                new_sl = pos.entry_price + dir_ * 0.65 * gain
                new_tp = px + dir_ * 0.12 * gain
            pos.locked = True
            pos.lock_mode = mode
            print("", flush=True)
            log(f"🎯 إعادة تقييم عند {int(prog_tp * 100)}% من الهدف "
                f"[{pos.symbol} {pos.side}] — الدرجة {pos.entry_score:+.0f} → "
                f"{score:+.0f} | النظام {pos.entry_regime} → {regime}")
            log(f"   وضع {mode}: قفل الربح + إلغاء SL/TP القديمين ووضع جديدين "
                f"مكانهم على بينانس")
            await self._replace_bracket(pos, new_sl=new_sl, new_tp=new_tp,
                                        reason=f"REVAL@{int(prog_tp * 100)}%TP/{mode}")
            print("", flush=True)

        # ---- 2) تتبع متحرك مستمر بعد القفل (ترقية فقط — لا تراجع) ----
        elif pos.locked:
            tight = TRAIL_ATR if prog_tp < PROFIT_LOCK2_TRIGGER else TRAIL_ATR_TIGHT
            cand = px - dir_ * tight * atr
            if pos.current_sl:
                if dir_ > 0:
                    improve = cand > pos.current_sl * (1 + MIN_REPLACE_MOVE)
                else:
                    improve = cand < pos.current_sl * (1 - MIN_REPLACE_MOVE)
                if improve:
                    await self._replace_bracket(
                        pos, new_sl=cand,
                        reason=f"TRAIL-{tight:.1f}ATR/{pos.lock_mode}")

        # ---- 3) إعادة تقييم الخسارة عند 70% من الطريق للوقف ----
        if (not pos.closed) and prog_sl >= LOSS_REVAL_TRIGGER and \
                time.time() - pos.loss_reval_ts > LOSS_REVAL_REARM_S:
            pos.loss_reval_ts = time.time()
            pos.reval_count += 1
            aligned = score * dir_
            print("", flush=True)
            log(f"🔬 إعادة تقييم خسارة عند {int(prog_sl * 100)}% من الوقف "
                f"[{pos.symbol} {pos.side}] — الدرجة {score:+.0f} "
                f"(انحياز {aligned:+.0f}) | PnL {pnl_R:+.2f}R")
            if aligned < -30:
                log(f"   ☠️ انتهت صلاحية الفكرة — خفض مبكر يوفر "
                    f"{(1 - prog_sl) * 100:.0f}% من الوقف")
                await self._market_close(pos, 'EARLY_CUT_THESIS_INVALID')
                return
            elif aligned < 30:
                new_sl = pos.entry_price - dir_ * 0.85 * sl_dist0
                tighten = (new_sl > pos.current_sl) if dir_ > 0 \
                    else (new_sl < pos.current_sl)
                if tighten:
                    await self._replace_bracket(pos, new_sl=new_sl,
                                                reason='LOSS-REVAL/TIGHTEN')
                log(f"   ⚠️ قناعة ضعيفة → تم شد الوقف نحو {new_sl:.6g}")
            else:
                log(f"   💪 القناعة قائمة (الدرجة {score:+.0f}) → صبر مع الوقف الأصلي")
            print("", flush=True)

        # ---- 4) الصفقة الراكدة (تتقلب دون تحقيق الهدف) ----
        hold_limit = {
            'TREND_UP': HOLD_TREND_MIN, 'TREND_DOWN': HOLD_TREND_MIN,
            'RANGE': HOLD_RANGE_MIN, 'VOLATILE_CHOP': HOLD_CHOP_MIN,
        }.get(pos.entry_regime, HOLD_DEFAULT_MIN)
        if pos.stag_extended:
            hold_limit *= 1.5
        stagnant = (age_min > hold_limit) and (abs(pnl_R) < 0.35)
        if (not pos.closed) and stagnant and not pos.stag_extended:
            if abs(score) < 25:
                await self._market_close(
                    pos, f'STAGNANT_DEAD (الدرجة {score:+.0f}، {age_min:.0f}د)')
                return
            pos.stag_extended = True
            log(f"⏳ [{pos.symbol} {pos.side}] راكدة {age_min:.0f}د لكن الدرجة "
                f"{score:+.0f} حية → تمديد الحد إلى {hold_limit * 1.5:.0f}د")
        elif (not pos.closed) and stagnant and pos.stag_extended and abs(score) < 25:
            await self._market_close(
                pos, f'STAGNANT_DEAD_EXT (الدرجة {score:+.0f}، {age_min:.0f}د)')
            return

        # ---- 4.5) ⏱️ v2.0: قاطع زمني للخاسر الراكد — رأس المال أولًا ----
        if (not pos.closed) and pnl_R <= TIME_STOP_R and \
                age_min > hold_limit * TIME_STOP_AGE_MULT and abs(score) < 20:
            await self._market_close(
                pos, f'TIME_STOP (خاسر راكد {pnl_R:+.2f}R لمدة {age_min:.0f}د '
                     f'مع درجة ميتة {score:+.0f})')
            return

        # ---- 5) كشف الانحراف عن الاستراتيجية → تنبيه كل 10 ثوان ----
        reasons = []
        if score * dir_ <= -DEVIATION_SCORE_FLIP:
            reasons.append(f"الدرجة المركبة انقلبت ضد الصفقة: عند الدخول "
                           f"{pos.entry_score:+.0f} → الآن {score:+.0f}")
        unfav = {('LONG', 'TREND_DOWN'), ('SHORT', 'TREND_UP'),
                 ('LONG', 'VOLATILE_CHOP'), ('SHORT', 'VOLATILE_CHOP'),
                 ('LONG', 'DEAD'), ('SHORT', 'DEAD')}
        if (pos.side, regime) in unfav:
            reasons.append(f"تحول نوع السوق {pos.entry_regime} → {regime} "
                           f"(غير ملائم لصفقة {pos.side})")
        if pos.stag_extended and stagnant:
            reasons.append(f"راكدة {age_min:.0f}د (الحد {hold_limit:.0f}د) "
                           f"مع PnL {pnl_R:+.2f}R")
        fr = float(snap.get('funding') or 0.0)
        if (dir_ > 0 and fr > 0.0010) or (dir_ < 0 and fr < -0.0010):
            reasons.append(f"تمويل ثقيل ضد الصفقة: {fr * 100:.3f}%/8س")
        atr_now_pct = float(snap.get('atr_pctile') or 50)
        if atr_now_pct > 93 and pos.entry_atr_pctile < 70:
            reasons.append(f"انفجار تقلب مفاجئ (مئين ATR {atr_now_pct:.0f} "
                           f"بعد {pos.entry_atr_pctile:.0f} عند الدخول)")
        pos.deviation_active = bool(reasons)
        pos.deviation_reasons = reasons
        if reasons:
            self._print_deviation(pos, px, pnl_R, reasons, hold_limit, score,
                                  regime, age_min)

        # ---- 6) سلامة أوامر الحماية ----
        if not pos.closed:
            await self._ensure_bracket(pos)

    def _print_deviation(self, pos, px, pnl_R, reasons, hold_limit, score,
                         regime, age_min):
        pnl_usd = (px - pos.entry_price) * (1 if pos.side == 'LONG' else -1) \
            * pos.qty
        bar = "🚨" * 24
        print("", flush=True)
        print(bar, flush=True)
        print("🚨 STRATEGY DEVIATION — MANUAL REVIEW REQUIRED "
              "(انحراف عن الاستراتيجية — مراجعة يدوية) 🚨", flush=True)
        print(f"📌 {pos.symbol} {pos.side} | دخول {pos.entry_price:.6g} | "
              f"الآن {px:.6g} | PnL {pnl_R:+.2f}R (~${pnl_usd:+.2f})", flush=True)
        for r in reasons:
            print(f"⛔ {r}", flush=True)
        print(f"🕐 المدة {age_min:.0f}د (الحد {hold_limit:.0f}د) | إعادة تقييم "
              f"{pos.reval_count} | قفل {pos.lock_mode or '—'} | النظام الآن "
              f"{regime} | الدرجة الآن {score:+.0f}", flush=True)
        print("👉 البوت لن يغلق تلقائيًا بسبب الانحراف — أغلقها يدويًا من "
              "بينانس إن وافقت على التقييم.", flush=True)
        print(f"🚨 (يتكرر التنبيه كل {CYCLE_SECONDS} ثانية حتى يُحل الأمر) 🚨",
              flush=True)
        print(bar, flush=True)
        print("", flush=True)

    # ==================================================================
    # 🟢 الدخول v2.1 🌬 — التنفس: أفضل إشارة عبر الرموز تدخل فورًا
    #     (فُتحت بوابات v2.0 الخانقة مع إبقاء فلاتر الجودة الحية)
    # ==================================================================
    def _swing_levels(self, sym, lookback=90):
        """أعلى قمة وأخفض قاع لآخر N شمعة 5m (مع تجاهل الشمعة الجارية)."""
        try:
            md = self.md.get(sym)
            k = md.k.get('5m') if md else None
            if k is None:
                return None, None
            h = np.asarray(k['h'], dtype=float)
            l = np.asarray(k['l'], dtype=float)
            if len(h) < 6:
                return None, None
            n = min(lookback + 1, len(h))
            return float(np.max(h[-n:-1])), float(np.min(l[-n:-1]))
        except Exception:
            return None, None

    def _calc_tp_sl(self, sym, px, dir_, snap):
        """
        📐 v1.1: حاسبة SL/TP الدقيقة — هدف قريب يصل إليه السعر بسهولة:
          * SL : خلف آخر قاع/قمة محلية (14 شمعة 5m) + هامش 0.30×ATR
                 (لا أضيق من 60% من مسافة ATR) — وإلا الوقف الكلاسيكي
                 1.4×ATR — محصور دائمًا ضمن 0.35%..1.2%.
          * TP : أقرب هدف قابل للتحقيق من هدف RR النظام والحاجز الهيكلي
                 (أقصى 90 شمعة قبل الحاجز بـ 0.20×ATR) — نختار الأقرب
                 بشرط ألا يقل عن 1.2R، فيصبح جني الأرباح في المتناول.
        """
        atr = max(float(snap.get('atr') or px * 0.004), px * 1e-6)
        reg = snap.get('regime') or {}
        sl_mult = float(reg.get('sl_mult') or 1.0)
        rr = float(reg.get('rr') or RR_RANGE)

        atr_sl_pct = (atr / px) * SL_ATR_MULT * sl_mult
        sl_lo_pct = max(SL_PCT_MIN, 0.60 * atr_sl_pct)  # لا أضيق من 60% ATR

        # ---- وقف الخسارة: هيكل محلي + هامش ATR ----
        local_hi, local_lo = self._swing_levels(sym, 14)
        sl = None
        if dir_ > 0 and local_lo is not None and local_lo < px:
            cand = local_lo - 0.30 * atr
            d = (px - cand) / px
            if sl_lo_pct <= d <= SL_PCT_MAX:
                sl = cand
        elif dir_ < 0 and local_hi is not None and local_hi > px:
            cand = local_hi + 0.30 * atr
            d = (cand - px) / px
            if sl_lo_pct <= d <= SL_PCT_MAX:
                sl = cand
        if sl is None:
            d = min(max(atr_sl_pct, SL_PCT_MIN), SL_PCT_MAX)
            sl = px * (1 - dir_ * d)
        sl_pct = abs(px - sl) / px

        # ---- جني الأرباح: أقرب هدف قابل للتحقيق ----
        r_px = abs(px - sl)
        tp = px + dir_ * r_px * rr
        tp_src = f"RR {rr:.1f}"
        swing_hi, swing_lo = self._swing_levels(sym, 90)
        if dir_ > 0 and swing_hi is not None and swing_hi > px:
            barrier = swing_hi - 0.20 * atr
            if r_px * MIN_RR_ACHIEVABLE <= (barrier - px) < r_px * rr:
                tp = barrier
                tp_src = "هيكل قريب"
        elif dir_ < 0 and swing_lo is not None and swing_lo < px:
            barrier = swing_lo + 0.20 * atr
            if r_px * MIN_RR_ACHIEVABLE <= (px - barrier) < r_px * rr:
                tp = barrier
                tp_src = "هيكل قريب"
        try:
            sl = float(self.ex.price_to_precision(sym, sl))
            tp = float(self.ex.price_to_precision(sym, tp))
        except Exception:
            pass
        rr_eff = abs(tp - px) / max(r_px, 1e-12)
        return sl, tp, sl_pct, tp_src, rr_eff

    def _compute_size(self, sym, px, sl_pct, eff_eq, free, size_mult):
        risk_usd = eff_eq * RISK_PER_TRADE * size_mult
        notional = risk_usd / max(sl_pct, 1e-9)
        max_notional = min(eff_eq * MAX_NOTIONAL_MULT,
                           max(free or eff_eq, 0.0) * MAX_LEVERAGE * 0.90)
        if max_notional <= 0:
            return None, 0.0
        notional = min(notional, max_notional)
        min_cost, min_qty = 5.0, 0.0
        try:
            m = self.ex.market(sym)
            min_cost = float(((m.get('limits') or {}).get('cost') or {})
                             .get('min') or 5.0)
            min_qty = float(((m.get('limits') or {}).get('amount') or {})
                            .get('min') or 0.0)
        except Exception:
            pass
        floor_notional = max(min_cost * 1.10, 6.0)
        if notional < floor_notional:
            notional = min(floor_notional, max_notional)
            if notional < min_cost * 1.02:
                return None, 0.0
        qty = notional / px
        try:
            qty = float(self.ex.amount_to_precision(sym, qty))
        except Exception:
            qty = round(qty, 6)
        if qty <= 0 or qty * px < min_cost * 1.01:
            try:
                qty = float(self.ex.amount_to_precision(sym, floor_notional / px))
                if qty * px < min_cost or qty * px > max_notional * 1.02:
                    return None, 0.0
            except Exception:
                return None, 0.0
        if min_qty and qty < min_qty:
            return None, 0.0
        return qty, qty * px

    async def _try_entries(self, snaps, eff_eq, free):
        now = time.time()
        if now - self.last_entry_ts < GLOBAL_ENTRY_GAP_S:
            return
        if len(self.positions) >= MAX_POSITIONS:
            return
        best = None
        for sym, snap in snaps.items():
            if sym in self.positions:
                continue
            if now < self.cooldowns.get(sym, 0):
                continue
            try:
                ev = evaluate_signal(snap)
            except Exception:
                continue
            if ev['ok']:
                if best is None or abs(snap['score']) > abs(best[2]['score']):
                    best = (sym, ev['dir'], snap)
            elif ev.get('near') and \
                    now - self._near_log.get(sym, 0) > NEAR_LOG_INTERVAL_S:
                self._near_log[sym] = now
                log(f"🌡️ قريبة {sym} {snap['score']:+.0f}/{ev['need']:.0f} | "
                    f"{_pillar_str(snap['pillars'])} | {snap['regime']['name']} | "
                    f"{ev['why']}")
        if best:
            await self._enter(best[0], best[1], best[2], eff_eq, free)

    async def _enter(self, sym, dir_, snap, eff_eq, free):
        px = snap['price']
        atr = snap['atr']
        reg = snap['regime']
        ev = evaluate_signal(snap)
        # 📐 v1.1: حاسبة SL/TP الدقيقة (هيكل السوق + ATR) — هدف قابل للتحقيق
        sl, tp, sl_pct, tp_src, rr = self._calc_tp_sl(sym, px, dir_, snap)
        if not ((sl < px < tp) if dir_ > 0 else (tp < px < sl)):
            log(f"⚠️ {sym}: هندسة SL/TP غير صالحة — تخطٍ")
            self.cooldowns[sym] = time.time() + 60
            return
        size_mult = reg.get('size_mult', 1.0)
        if abs(snap['score']) >= 60:      # v2.0: قناعة قوية → حجم أكبر قليلًا
            size_mult *= 1.15
        qty, notional = self._compute_size(sym, px, sl_pct, eff_eq, free,
                                           size_mult)
        if not qty:
            log(f"⚠️ {sym}: الحجم أقل من حدود الصرف — تخطٍ")
            self.cooldowns[sym] = time.time() + 120
            return
        side = 'buy' if dir_ > 0 else 'sell'
        try:
            await self.ex.create_order(sym, 'market', side, qty)
        except Exception as e:
            log(f"❌ فشل أمر الدخول [{sym}]: {str(e)[:140]}")
            self.cooldowns[sym] = time.time() + 60
            return
        # 🛡️ v1.2: انتظار ظهور الصفقة على بينانس (تحتاج ~0.5-2ث بعد
        # التنفيذ) — 6 محاولات، ثم جلب مباشر للرمز، ثم إغلاق احترازي:
        # ممنوع نهائيًا صفقة مفتوحة بلا حماية.
        p = None
        for _attempt in range(6):
            await asyncio.sleep(1.0)
            exch = await self._fetch_positions_map()
            p = exch.get(sym)
            if p:
                break
        if not p:
            # محاولة أخيرة مباشرة على الرمز فقط
            try:
                direct = await self.ex.fetch_positions([sym])
                for dp in direct or []:
                    amt = float((dp.get('info') or {}).get('positionAmt') or 0)
                    if amt != 0:
                        p = {'side': 'LONG' if amt > 0 else 'SHORT',
                             'qty': abs(amt),
                             'entry': float((dp.get('info') or {})
                                            .get('entryPrice') or px)}
                        break
            except Exception:
                pass
        if not p:
            # أسوأ سيناريو: الدخول غير مؤكد — إغلاق احترازي فوري
            log(f"🆘 {sym}: دخول غير مؤكد بعد المحاولات — إغلاق احترازي فوري "
                f"(ممنوع صفقة مكشوفة)")
            try:
                await self.ex.create_order(sym, 'market',
                                           'sell' if dir_ > 0 else 'buy',
                                           qty, None, {'reduceOnly': True})
            except Exception as e:
                log(f"   إغلاق احترازي [{sym}]: {str(e)[:110]} "
                    f"(طبيعي إن لم تكن هناك صفقة أصلًا)")
            await self._cancel_symbol_orders(sym)
            # تأكيد نهائي: هل بقيت صفقة مكشوفة؟
            try:
                await asyncio.sleep(0.8)
                check = await self.ex.fetch_positions([sym])
                for cp in check or []:
                    amt = float((cp.get('info') or {}).get('positionAmt') or 0)
                    if amt != 0:
                        log(f"🆘🆘🆘 {sym}: ما زالت هناك صفقة مكشوفة "
                            f"qty {abs(amt)} — أغلقها يدويًا الآن من بينانس!")
            except Exception:
                pass
            self.cooldowns[sym] = time.time() + 120
            return
        entry = p['entry'] if p['entry'] > 0 else px
        pos = PositionState(
            symbol=sym, side=p['side'], qty=p['qty'] or qty,
            entry_price=entry, initial_sl=sl, initial_tp=tp,
            current_sl=sl, current_tp=tp, entry_time=time.time(),
            entry_score=snap['score'], entry_regime=reg['name'],
            atr_entry=atr, r_unit=abs(entry - sl))
        pos.entry_atr_pctile = float(snap.get('atr_pctile') or 50.0)
        br = await self._place_bracket(pos)
        if not br['sl']:
            placed = None
            for _ in range(2):
                await asyncio.sleep(1.0)
                placed = await self._place_stop_order(pos, 'SL', pos.current_sl)
                if placed:
                    pos.sl_order_id = placed.get('id')
                    break
            if not placed:
                log(f"🆘 {sym}: تعذر وضع الوقف → إغلاق طارئ بسعر السوق")
                await self._market_close(pos, 'NO_SL_EMERGENCY')
                await self._cancel_symbol_orders(sym)
                return
        self.positions[sym] = pos
        self.last_entry_ts = time.time()
        self.cooldowns[sym] = time.time() + ENTRY_COOLDOWN_S
        risk_usd = abs(entry - sl) * pos.qty
        print("", flush=True)
        log(f"🟢 دخول [{sym} {pos.side}] @ {entry:.6g}")
        conf_str = ''
        if ev.get('checks'):
            conf_str = ' | انصهار ' + '+'.join(k for k, v in ev['checks'].items()
                                             if v)
        log(f"   الدرجة {snap['score']:+.1f} (المطلوب {ev['need']:.0f}) | الركائز "
            f"{_pillar_str(snap['pillars'])} | اتفاق {snap['agreement']}/7{conf_str}")
        log(f"   النظام {reg['name']}{'+' if reg['strong'] else ''} | "
            f"SL {sl:.6g} ({abs(entry - sl) / entry * 100:.2f}%) | "
            f"TP {tp:.6g} ({abs(tp - entry) / entry * 100:.2f}%) | "
            f"RR 1:{rr:.2f} [{tp_src}]")
        log(f"   الكمية {pos.qty} (~${pos.qty * entry:.2f}) | المخاطرة "
            f"${risk_usd:.2f} ({risk_usd / max(eff_eq, 1e-9) * 100:.1f}% من "
            f"${eff_eq:.0f}) | رافعة {MAX_LEVERAGE}x معزول")
        log(f"   على الصرف الآن: SL #{pos.sl_order_id} @ {pos.current_sl} | "
            f"TP #{pos.tp_order_id} @ {pos.current_tp}")
        print("", flush=True)

    # ==================================================================
    # 💓 النبض والإحصائيات والمخاطر اليومية
    # ==================================================================
    def _risk_state(self, eff_eq):
        dk = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        if dk != self.day_key:
            self.day_key = dk
            self.day_start_eq = self.wallet or eff_eq
            log("📅 يوم UTC جديد — تصفير العدادات اليومية")
        halted, why = False, ''
        if self.day_start_eq and self.day_start_eq > 0:
            dd = (self.wallet - self.day_start_eq) / self.day_start_eq
            if dd <= -DAILY_LOSS_LIMIT:
                halted = True
                why = f"يوم {dd * 100:+.1f}% ≤ -{DAILY_LOSS_LIMIT * 100:.0f}%"
        return halted, why

    def _heartbeat(self, snaps, eff_eq, halted, why):
        pos_bits = []
        for sym, p in self.positions.items():
            mark = '🚨' if p.deviation_active else ''
            prot = '' if p.last_protected else '🆘'    # v1.4: حالة الحماية
            half = '½' if p.partial_taken else ''      # v2.0: جني جزئي تم
            pos_bits.append(f"{sym.replace('USDT', '')}"
                            f"{'▲' if p.side == 'LONG' else '▼'}"
                            f"{p.last_pnl_R:+.1f}R{half}{prot}{mark}")
        reg_bits = []
        for s in sorted(snaps, key=lambda x: -abs(snaps[x]['score']))[:len(SYMBOLS)]:
            reg_bits.append(f"{s.replace('USDT', '')}:"
                            f"{REGIME_SHORT.get(snaps[s]['regime']['name'], '?')}")
        top = max(snaps.values(), key=lambda x: abs(x['score'])) if snaps else None
        if top is not None:
            top_sym = [s for s, v in snaps.items() if v is top][0]
            top_s = f"{top_sym.replace('USDT', '')} {top['score']:+.0f}"
        else:
            top_s = '—'
        day_pnl = (self.wallet - self.day_start_eq) if self.day_start_eq else 0.0
        st = self.stats
        extra = ''
        if self.auth_failed:
            extra += " | 🔑 وضع التحليل فقط (المفاتيح غير صالحة)"
        if self.pause_until > time.time():
            extra += f" | 🧊 تهدئة {int(self.pause_until - time.time())}ث"
        if halted:
            extra += f" | ⛔ إيقاف يومي: {why}"
        log(f"💓 {self.mode.upper()} | محفظة ${self.wallet:.2f} → فعلي "
            f"${eff_eq:.2f} | يوم ${day_pnl:+.2f} | تراكمي "
            f"${st['cum_pnl']:+.2f}/{st['cum_R']:+.1f}R | صفقات "
            f"{len(self.positions)}/{MAX_POSITIONS} "
            f"[{' '.join(pos_bits) if pos_bits else '—'}] | "
            f"{' '.join(reg_bits)} | أعلى {top_s}{extra}")

    def _stats_log(self):
        st = self.stats
        if st['trades'] == 0:
            log("📊 الجلسة: لا صفقات مغلقة بعد — الإشارات القريبة تظهر بسطر 🌡️")
            return
        wr = st['wins'] / st['trades']
        log(f"📊 الجلسة: {st['trades']} صفقة | نسبة الربح {wr:.0%} | تراكمي "
            f"{st['cum_R']:+.1f}R / ${st['cum_pnl']:+.2f} | الخروجات: "
            f"{dict(st['by_reason'])}")

    # ==================================================================
    # 🔁 الحلقة الرئيسية (10 ثوانٍ)
    # ==================================================================
    async def _cycle(self):
        self.cycle_count += 1
        await self._fetch_balance_safe()
        eff_eq = self._eff_equity()
        await asyncio.gather(*(md.refresh() for md in self.md.values()))
        snaps = {}
        for s in SYMBOLS:
            try:
                snap = build_snapshot(self.md[s])
                if snap:
                    snaps[s] = snap
            except Exception as e:
                if time.time() - self._err_log_ts.get('snap:' + s, 0) > 300:
                    self._err_log_ts['snap:' + s] = time.time()
                    log(f"⚠️ لقطة {s}: {type(e).__name__}: {str(e)[:120]}")
        if not self.auth_failed:
            # v1.2: adopt=True — أي صفقة غير مسجلة (سباق توقيت/إعادة نشر)
            # تُتبنّى فورًا ويُوضع لها SL/TP بدل بقائها مكشوفة
            await self.sync_positions(adopt=True, snaps=snaps)
            await self._protection_guardian()   # 🛡️ v1.4: لا مركز بلا SL/TP
            halted, why = self._risk_state(eff_eq)
            for sym, pos in list(self.positions.items()):
                snap = snaps.get(sym) or {
                    'price': pos.last_price or pos.entry_price,
                    'atr': pos.atr_entry, 'score': 0.0,
                    'regime': {'name': pos.entry_regime}, 'pillars': {},
                    'gates': {}, 'funding': 0.0, 'atr_pctile': 50.0,
                }
                try:
                    await self.manage_position(pos, snap)
                except Exception as e:
                    log(f"❗ إدارة {sym}: {type(e).__name__}: {str(e)[:120]}")
                    log(traceback.format_exc(limit=3))
            if snaps and not halted and len(self.positions) < MAX_POSITIONS and \
                    time.time() >= self.pause_until:
                await self._try_entries(snaps, eff_eq, self.free)
        else:
            halted, why = False, ''
        self._heartbeat(snaps, eff_eq, halted, why)
        if self.cycle_count % STATS_EVERY_CYCLES == 0:
            self._stats_log()

    async def run(self):
        await self.startup()
        while not self.shutdown:
            t0 = time.time()
            try:
                await self._cycle()
                self.err_streak = 0
            except ccxt.RateLimitExceeded:
                self.err_streak += 1
                self.cycle_s = min(60, self.cycle_s * 2)
                log(f"🐢 حد المعدل → إبطاء الدورة إلى {self.cycle_s}ث")
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable,
                    ccxt.RequestTimeout) as e:
                self.err_streak += 1
                log(f"🌐 شبكة: {type(e).__name__} (تتابع {self.err_streak})")
            except Exception as e:
                self.err_streak += 1
                log(f"❗ خطأ دورة: {type(e).__name__}: {str(e)[:140]}")
                log(traceback.format_exc(limit=4))
            if self.err_streak == 0 and self.cycle_s > CYCLE_SECONDS and \
                    self.cycle_count % 10 == 0:
                self.cycle_s = max(CYCLE_SECONDS, int(self.cycle_s / 2))
            dt = self.cycle_s - (time.time() - t0)
            if dt > 0:
                await asyncio.sleep(dt)
        st = self.stats
        log(f"👋 إيقاف تشغيل — أوامر SL/TP تبقى حية على الصرف كحماية. "
            f"الجلسة: {st['trades']} صفقة | {st['wins']}ر/{st['losses']}خ | "
            f"{st['cum_R']:+.1f}R / ${st['cum_pnl']:+.2f}")


# ============================================================================
# 🚀 نقطة البداية
# ============================================================================
async def main():
    bot = Bot()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, setattr, bot, 'shutdown', True)
        except Exception:
            pass
    try:
        await bot.run()
    finally:
        try:
            await bot.ex.close()
        except Exception:
            pass


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"{now_utc_str()} | توقف يدوي", flush=True)
