import os
import datetime
import psycopg2
import pandas as pd
import secrets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

# ==================== 1. الإعدادات والثوابت ====================
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084  # معرف المسؤول (لأوامر الاشتراكات)

# خطط الاشتراك (بالأيام)
PLANS = {
    'day': 1,
    'two_days': 2,
    'week': 7,
    'month': 30
}

# خريطة تحويل أسماء الفائزين إلى أرقام
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الراعي': 0, '🔴': 0,
    'الثور 🔵': 1, 'ثور': 1, 'الثور': 1, '🔵': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '⚪': 2
}

WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الثور 🔵', 2: 'تعادل ⚪'}

# ==================== 2. دوال مساعدة ====================
def get_time_period(hour: int) -> str:
    """تحديد الفترة الزمنية بناءً على الساعة"""
    if 6 <= hour < 12: return "morning"
    elif 12 <= hour < 18: return "afternoon"
    elif 18 <= hour < 24: return "evening"
    else: return "night"

def period_translate(period: str) -> str:
    """ترجمة الفترة إلى العربية مع رمز"""
    return {
        "morning": "🌅 الصباح",
        "afternoon": "☀️ الظهر",
        "evening": "🌇 المساء",
        "night": "🌙 الليل"
    }.get(period, period)

# ==================== 3. دوال إدارة الاشتراكات ====================
def init_subscription_table():
    """إنشاء جدول الاشتراكات إذا لم يكن موجودًا"""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscription_keys (
            id SERIAL PRIMARY KEY,
            key_code VARCHAR(50) UNIQUE NOT NULL,
            plan VARCHAR(20) NOT NULL,
            is_used BOOLEAN DEFAULT FALSE,
            used_by BIGINT,
            used_at TIMESTAMP,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def generate_keys():
    """
    توليد 5 مفاتيح جديدة لكل خطة في كل مرة يتم استدعاء هذه الدالة.
    """
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    for plan in PLANS.keys():
        for _ in range(5):
            key = secrets.token_urlsafe(16)  # مفتاح عشوائي آمن
            try:
                cur.execute(
                    "INSERT INTO subscription_keys (key_code, plan) VALUES (%s, %s)",
                    (key, plan)
                )
            except psycopg2.IntegrityError:
                # في حالة وجود مفتاح مكرر (نادر جداً)، نتجاهل ونستمر
                conn.rollback()
                continue
    conn.commit()
    conn.close()

def is_user_subscribed(user_id: int) -> tuple:
    """
    التحقق مما إذا كان المستخدم لديه اشتراك صالح
    تُرجع (True/False, الخطة, الأيام المتبقية)
    """
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("""
        SELECT plan, expires_at FROM subscription_keys 
        WHERE used_by = %s AND expires_at > NOW() 
        ORDER BY expires_at DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    
    if row:
        plan = row[0]
        expires = row[1]
        remaining = (expires - datetime.datetime.now()).days
        return True, plan, remaining
    return False, None, 0

def activate_subscription(user_id: int, key_code: str) -> bool:
    """تفعيل الاشتراك بمفتاح معين لمستخدم"""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    
    # البحث عن المفتاح
    cur.execute("SELECT id, plan, is_used FROM subscription_keys WHERE key_code = %s", (key_code,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False  # مفتاح غير موجود
    
    key_id, plan, is_used = row
    if is_used:
        conn.close()
        return False  # مفتاح مستخدم مسبقًا
    
    # حساب تاريخ الانتهاء
    days = PLANS.get(plan)
    if not days:
        conn.close()
        return False
    
    expires_at = datetime.datetime.now() + datetime.timedelta(days=days)
    
    # تحديث المفتاح
    cur.execute("""
        UPDATE subscription_keys 
        SET is_used = TRUE, used_by = %s, used_at = NOW(), expires_at = %s
        WHERE id = %s
    """, (user_id, expires_at, key_id))
    
    conn.commit()
    conn.close()
    return True

# ==================== 4. المحرك الرياضي ====================
def sovereign_math_engine(b_num: str, suit: str, last_timestamp, current_timestamp):
    """المعادلة الرياضية السيادية الأساسية"""
    last_3 = b_num[-3:] if len(b_num) >= 3 else b_num
    B = sum(int(d) for d in last_3 if d.isdigit())
    S = 1 if suit in ['♦️', '♥️'] else 2
    delta_t = int((current_timestamp - last_timestamp).total_seconds()) if last_timestamp else 0
    R = (B * S) + delta_t
    prediction_code = 1 if (R % 2 == 0) else 0  # 1=ثور, 0=راعي
    prediction_text = WINNER_NAMES[prediction_code]
    return prediction_text, prediction_code, R, delta_t, B, S

# ==================== 5. الذكاء البايزي (Bayesian Layer) ====================
def bayesian_adjustment(prediction_code: int, current_hour: int, conn, min_samples: int = 15):
    """تعديل التوقع بناءً على أداء الخوارزمية في هذه الساعة تحديداً"""
    try:
        period = get_time_period(current_hour)
        
        # جلب أحدث 200 جولة فقط
        df = pd.read_sql("""
            SELECT winner, prediction, timestamp 
            FROM history 
            WHERE prediction IS NOT NULL 
            ORDER BY id DESC LIMIT 200
        """, conn)
        
        if len(df) < min_samples: return prediction_code, None
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['period'] = df['timestamp'].dt.hour.apply(get_time_period)
        
        period_data = df[df['period'] == period].copy()
        if len(period_data) < min_samples: return prediction_code, None
        
        period_data['winner_code'] = period_data['winner'].map(WINNER_MAP)
        period_data = period_data.dropna(subset=['winner_code'])
        
        if len(period_data) < min_samples: return prediction_code, None
        
        total = len(period_data)
        p_rai = (period_data['winner_code'] == 0).sum() / total
        p_thawr = (period_data['winner_code'] == 1).sum() / total
        
        # Prior probabilities (المعادلة الرياضية تعطى ثقة 80%)
        prior_rai, prior_thawr = (0.80, 0.20) if prediction_code == 0 else (0.20, 0.80)
        
        # Bayesian Update
        norm_rai = prior_rai * p_rai
        norm_thawr = prior_thawr * p_thawr
        
        if (norm_rai + norm_thawr) == 0: return prediction_code, None
        
        posterior_rai = norm_rai / (norm_rai + norm_thawr)
        posterior_thawr = norm_thawr / (norm_rai + norm_thawr)
        
        adjusted_code = 0 if posterior_rai > posterior_thawr else 1
        return adjusted_code, (posterior_rai, posterior_thawr)
        
    except Exception as e:
        print(f"Bayesian Error: {e}")
        return prediction_code, None

# ==================== 6. أوامر البوت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء التفاعل مع التحقق من الاشتراك"""
    user_id = update.effective_user.id
    
    # التحقق من الاشتراك (المسؤول مستثنى)
    subscribed, plan, remaining = is_user_subscribed(user_id)
    
    if not subscribed and user_id != ADMIN_ID:
        # إذا لم يكن مشتركًا وليس أدمن، نطلب إدخال مفتاح
        await update.message.reply_text(
            "🔐 **مرحبًا بك في HADES V3**\n"
            "للاستخدام، يجب عليك إدخال مفتاح اشتراك صالح.\n"
            "أرسل المفتاح الآن، أو تواصل مع المسؤول للحصول على مفتاح.\n\n"
            "إذا كان لديك مفتاح، أرسله كرسالة مباشرة."
        )
        return
    
    # إذا كان مشتركًا أو أدمن، نكمل
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("♦️ ديناري (أحمر)", callback_data="s_♦️"), 
         InlineKeyboardButton("♥️ قلب (أحمر)", callback_data="s_♥️")],
        [InlineKeyboardButton("♠️ سبايد (أسود)", callback_data="s_♠️"), 
         InlineKeyboardButton("♣️ كلبة (أسود)", callback_data="s_♣️")]
    ]
    remaining_text = f"اشتراكك ({plan}) متبقي {remaining} يوم." if subscribed else ""
    await update.message.reply_text(
        f"🏛️ **محرك HADES V3 - الإصدار الشخصي النخبوي**\n"
        f"{remaining_text}\n\n"
        "🎴 اختر نوع البذلة للبدء:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إدخال مفتاح الاشتراك"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # محاولة تفعيل الاشتراك
    if activate_subscription(user_id, text):
        await update.message.reply_text("✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن استخدام /start للبدء.")
    else:
        await update.message.reply_text("❌ المفتاح غير صالح أو مستخدم مسبقًا. تأكد من المفتاح وحاول مرة أخرى.")

async def generate_keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر للمسؤول لتوليد مفاتيح جديدة وعرضها"""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر متاح للمسؤول فقط.")
        return

    generate_keys()

    # جلب المفاتيح غير المستخدمة من قاعدة البيانات
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT key_code, plan FROM subscription_keys WHERE is_used = FALSE ORDER BY plan, id")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("⚠️ لا توجد مفاتيح غير مستخدمة حالياً.")
        return

    # تجميع المفاتيح حسب الخطة
    result = "🔑 **المفاتيح المتاحة:**\n\n"
    plans_keys = {plan: [] for plan in PLANS.keys()}
    for key, plan in rows:
        plans_keys[plan].append(key)

    for plan in PLANS.keys():
        plan_name = {
            'day': '📆 يوم',
            'two_days': '📆📆 يومين',
            'week': '📅 أسبوع',
            'month': '📅 شهر'
        }.get(plan, plan)
        keys = plans_keys[plan]
        result += f"**{plan_name}** ({len(keys)} مفتاح):\n"
        if keys:
            for k in keys:
                result += f"`{k}`\n"
        else:
            result += "لا توجد مفاتيح.\n"
        result += "\n"

    await update.message.reply_text(result, parse_mode='Markdown')

async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض حالة الاشتراك الحالية للمستخدم"""
    user_id = update.effective_user.id
    subscribed, plan, remaining = is_user_subscribed(user_id)
    
    if subscribed or user_id == ADMIN_ID:
        plan_name = {
            'day': 'يوم',
            'two_days': 'يومين',
            'week': 'أسبوع',
            'month': 'شهر'
        }.get(plan, plan) if subscribed else "مشرف"
        await update.message.reply_text(
            f"✅ أنت مشترك حاليًا في خطة **{plan_name}**.\n"
            f"⏳ متبقي: {remaining if subscribed else 'غير محدود'} يوم."
        )
    else:
        await update.message.reply_text("❌ لا يوجد اشتراك نشط. استخدم /start وأدخل مفتاحًا صالحًا.")

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحليل الأداء المتقدم"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        df = pd.read_sql("SELECT winner, prediction, timestamp, suit FROM history WHERE prediction IS NOT NULL", conn)
        conn.close()

        if len(df) < 10:
            await update.message.reply_text("⚠️ البيانات غير كافية للتحليل (نحتاج 10 جولات على الأقل).")
            return

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['winner_code'] = df['winner'].map(WINNER_MAP)
        df = df.dropna(subset=['winner_code', 'prediction'])
        df['correct'] = (df['winner_code'] == df['prediction']).astype(int)

        accuracy = df['correct'].mean() * 100
        hour_stats = df.groupby('hour').agg(acc=('correct', 'mean'), count=('correct', 'count'))
        hour_stats = hour_stats[hour_stats['count'] >= 5]
        
        report = f"📊 **تقرير الأداء الشامل**\n━━━━━━━━━━━━━━\n📈 **الدقة العامة:** {accuracy:.1f}%\n"
        
        if not hour_stats.empty:
            best_hour = hour_stats['acc'].idxmax()
            worst_hour = hour_stats['acc'].idxmin()
            report += f"🏆 **أفضل ساعة للعب:** {best_hour:02d}:00 ({hour_stats.loc[best_hour, 'acc']*100:.1f}%)\n"
            report += f"⚠️ **أسوأ ساعة للعب:** {worst_hour:02d}:00 ({hour_stats.loc[worst_hour, 'acc']*100:.1f}%)\n"

        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف آخر إدخال في حالة الخطأ"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT id FROM history ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM history WHERE id = %s", (row[0],))
            conn.commit()
            await update.message.reply_text("🗑️ تم حذف آخر جولة بنجاح.")
        else:
            await update.message.reply_text("⚠️ لا توجد بيانات للحذف.")
        conn.close()
    except Exception as e:
         await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== 7. معالج الرسائل والأزرار ====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال البونص وإصدار التوقع الهجين (مع التحقق من الاشتراك)"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # التحقق من الاشتراك أولاً
    subscribed, _, _ = is_user_subscribed(user_id)
    if not subscribed and user_id != ADMIN_ID:
        # إذا لم يكن مشتركًا وليس أدمن، نتعامل مع الرسالة كمحاولة اشتراك
        await subscribe(update, context)
        return
    
    # متابعة المعالجة للمشتركين
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

        # 1. التوقع الرياضي
        pred_text, pred_code, R, gap, B, S = sovereign_math_engine(
            text, context.user_data['suit'], last_time, current_time
        )

        # 2. التعديل البايزي (الذكاء الاصطناعي)
        adjusted_code, posteriors = bayesian_adjustment(pred_code, current_time.hour, conn)
        
        cur.close()
        conn.close()

        warning_text = ""
        if adjusted_code is not None and adjusted_code != pred_code and posteriors is not None:
            pred_code = adjusted_code
            pred_text = WINNER_NAMES[pred_code]
            p_rai, p_thawr = posteriors
            warning_text = (
                f"🧠 **تصحيح ذكي (بايز):**\n"
                f"البيانات ترجح {pred_text} بنسبة {max(p_rai, p_thawr)*100:.0f}%\n"
                f"تم تعديل التوقع تلقائياً لحمايتك.\n\n"
            )

        context.user_data['bonus'] = text
        context.user_data['prediction_code'] = pred_code
        context.user_data['current_time'] = current_time

        kb = [
            [InlineKeyboardButton("🔴 فاز الراعي", callback_data="save_الراعي 🔴"),
             InlineKeyboardButton("🔵 فاز الثور", callback_data="save_الثور 🔵")],
            [InlineKeyboardButton("⚪ تعادل", callback_data="save_تعادل ⚪")]
        ]

        await update.message.reply_text(
            f"{warning_text}"
            f"🎯 **التوقع النهائي:** {pred_text}\n"
            f"🎴 البذلة: {context.user_data['suit']}\n"
            f"🔢 المعادلة: B={B} × S={S} + ΔT={gap} → R={R}\n"
            f"━━━━━━━━━━━━━━\n"
            f"اختر النتيجة الحقيقية بعد انتهاء الجولة:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ أدخل رقم صحيح (7 أرقام على الأقل).")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حفظ النتيجة في قاعدة البيانات"""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("s_"):
        suit = query.data[2:]
        context.user_data['suit'] = suit
        await query.edit_message_text(f"✅ تم اختيار: {suit}\n📥 أرسل رقم البونص للجولة القادمة:")

    elif query.data.startswith("save_"):
        winner_db = query.data[5:]
        pred_code = context.user_data.get('prediction_code')
        
        if pred_code is None:
            await query.edit_message_text("❌ خطأ: لا يوجد توقع مخزن. ابدأ من جديد /start.")
            return

        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO history (b_num, suit, winner, timestamp, prediction) 
                VALUES (%s, %s, %s, %s, %s)
            """, (
                context.user_data['bonus'], context.user_data['suit'],
                winner_db, context.user_data['current_time'], pred_code
            ))
            conn.commit()
            conn.close()

            pred_winner = WINNER_NAMES[pred_code]
            is_correct = "✅" if winner_db == pred_winner else "❌"
            
            kb = [[InlineKeyboardButton("🔄 بدء جولة جديدة", callback_data="new_round")]]
            
            await query.edit_message_text(
                f"{is_correct} **تم التسجيل بنجاح**\n\n"
                f"🎯 توقعنا: {pred_winner}\n"
                f"🏆 النتيجة الفعلية: {winner_db}\n"
                f"━━━━━━━━━━━━━━\n"
                f"/performance - تقرير الأداء\n"
                f"/delete - التراجع عن التسجيل",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الحفظ: {e}")

    elif query.data == "new_round":
        await start(update, context)

# ==================== 8. التشغيل والتأسيس ====================
if __name__ == "__main__":
    # --- تأسيس قاعدة البيانات تلقائياً ---
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        # إضافة عمود prediction إذا لم يكن موجوداً
        cur.execute("ALTER TABLE history ADD COLUMN IF NOT EXISTS prediction INTEGER;")
        # إضافة عمود user_id إذا لم يكن موجوداً (قد يكون مفيداً)
        cur.execute("ALTER TABLE history ADD COLUMN IF NOT EXISTS user_id BIGINT;")
        conn.commit()
        cur.close()
        conn.close()
        print("✅ قاعدة البيانات جاهزة ومحدثة.")
    except Exception as e:
        print(f"⚠️ ملاحظة حول قاعدة البيانات: {e}")
    
    # تهيئة جدول الاشتراكات
    init_subscription_table()
    
    # توليد مفاتيح أولية إذا لم توجد
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM subscription_keys")
        count = cur.fetchone()[0]
        if count == 0:
            generate_keys()
        conn.close()
    except Exception as e:
        print(f"⚠️ خطأ في توليد المفاتيح: {e}")
    # ------------------------------------

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("generate_keys", generate_keys_command))
    app.add_handler(CommandHandler("mysub", my_subscription))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🚀 محرك HADES V3 (مع نظام اشتراكات) يعمل الآن...")
    app.run_polling()
