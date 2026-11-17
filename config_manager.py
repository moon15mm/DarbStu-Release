# -*- coding: utf-8 -*-
"""
config_manager.py — إدارة الإعدادات وقوالب الرسائل
"""
import os, json, base64, secrets, datetime
from typing import Dict, Any, List, Optional
import constants as _const
from constants import (DATA_DIR, CONFIG_JSON, DB_PATH, BASE_DIR,
                       TZ_OFFSET, _ensure_matplotlib)

# قالب التأخر الافتراضي حتى 3.6.77 — بلا بداية الدوام. مدرسةٌ ما زال قالبها
# هو هذا حرفاً تنتقل إلى الجديد عند التحميل (load_config)، والمعدَّل لا يُمسّ.
TARDY_TEMPLATE_V1 = (
    "⏱ تنبيه تأخر من {school_name}\n"
    "{guardian}/ {student_name}\n"
    "نُحيطكم علماً بأن {son} {late_v} عن الحضور اليوم ({date})\n"
    "بمقدار {minutes_late} دقيقة.\n"
    "نأمل الاهتمام ب{his_attend} في الوقت المحدد.\n"
    "مع التقدير،\nإدارة {school_name}"
)

DEFAULT_CONFIG = {
    "school_name": "اسم المدرسة",
    "education_region": "الإدارة العامة للتعليم",
    "assistant_title": "وكيل شؤون الطلاب",
    "assistant_name": "",
    "principal_title": "مدير المدرسة",
    "principal_name": "",
    "logo_path": "",
    "message_template": (
        "⚠️ تنبيه غياب من {school_name}\n"
        "{guardian}/ {student_name}\n"
        "نفيدكم بتغيب {son} عن {his_class} ({class_name}) بتاريخ {date}.\n"
        "نأمل متابعة {his} لضمان استمرارية {his_attain} العلمي.\n"
        "مع التقدير،\nإدارة المدرسة"
    ),
    "period_times": ["07:00", "07:50", "08:40", "09:50", "10:40", "11:30", "12:20"],
    # التوقيت الصيفي والشتوي للدوام: وقتان محفوظان والمختار منهما هو school_start_time
    # (المصدر الوحيد لحساب التأخر والرسائل). انظر apply_school_timing.
    "school_timing": "summer",
    "school_start_time_summer": "06:45",
    "school_start_time_winter": "07:00",
    "school_start_time": "06:45",
    "tardiness_recipients": [],
    # ── جهاز البصمة عند البوابة ──────────────────────────────────
    # biometric_devices: قائمة أجهزة، كل عنصر:
    #   {"device_id":"gate1","protocol":"zk","ip":"192.168.1.201",
    #    "port":4370,"comm_key":0,"enabled":true}
    # mode: 'tardiness' يسجّل المتأخرين فقط · 'attendance' يسجّل الحضور كله.
    # grace: دقائق سماح بعد بداية الدوام قبل احتساب التأخر.
    "biometric_enabled": False,
    "biometric_devices": [],
    "biometric_mode": "tardiness",
    "biometric_grace_min": 0,
    "biometric_notify_parent": True,
    # {start_time} بداية الدوام الرسمية من الإعدادات — تتبع التوقيت الشتوي/الصيفي
    # بلا تعديل القالب، ولا يدخلها السماح. انظر _render وTARDY_TEMPLATE_V1.
    "tardiness_message_template": (
        "⏱ تنبيه تأخر من {school_name}\n"
        "{guardian}/ {student_name}\n"
        "نُحيطكم علماً بأن {son} {late_v} عن الحضور اليوم ({date})\n"
        "بمقدار {minutes_late} دقيقة عن بداية الدوام الرسمي ({start_time}).\n"
        "نأمل الاهتمام ب{his_attend} في الوقت المحدد.\n"
        "مع التقدير،\nإدارة {school_name}"
    ),
    # ─── إعدادات الإشعارات الذكية ─────────────────────────────
    "alert_absence_threshold": 5,        # عدد أيام الغياب قبل التنبيه
    "alert_enabled": True,               # تفعيل/تعطيل الإشعارات
    "alert_notify_admin": True,          # إشعار الإدارة
    "alert_notify_parent": True,         # إشعار ولي الأمر
    "alert_admin_phone": "",             # جوال الإدارة للإشعارات (وكيل المدرسة)
    "principal_phone": "",               # جوال مدير المدرسة
    "counselor1_name":  "",              # اسم الموجّه الطلابي الأول
    "counselor1_phone": "",              # جوال الموجّه الطلابي الأول
    "counselor2_name":  "",              # اسم الموجّه الطلابي الثاني
    "counselor2_phone": "",              # جوال الموجّه الطلابي الثاني
    "active_counselor": "1",             # الموجّه النشط حالياً (1 أو 2)
    "alert_template_parent": (
        "⚠️ تنبيه هام من {school_name}\n"
        "{guardian}/ {student_name}\n"
        "نُحيطكم علماً بأن {son} {absent_v} {absence_count} أيام هذا الشهر.\n"
        "آخر غياب: {last_date}\n"
        "نرجو التواصل مع الإدارة لمتابعة الأمر.\n"
        "مع التقدير،\nإدارة {school_name}"
    ),
    "alert_template_admin": (
        "📊 تقرير غياب متكرر\n"
        "{student}: {student_name}\n"
        "الفصل: {class_name}\n"
        "عدد أيام الغياب: {absence_count} يوم\n"
        "آخر غياب: {last_date}\n"
        "جوال ولي الأمر: {parent_phone}"
    ),
    # ─── إعدادات التقرير اليومي التلقائي ─────────────────────
    "daily_report_enabled": False,
    "daily_report_hour":    13,
    "daily_report_minute":  30,
    # ─── أرقام واتساب متعددة للإرسال الجماعي ──────────────────
    # قائمة خوادم واتساب: [{"port": 3000}, {"port": 3001}, ...]
    # اتركها فارغة لاستخدام خادم واحد فقط (المنفذ 3000)
    "wa_servers": [],
    # ─── مزوّد الواتساب: محلي · سحابي (Evolution API) · تلقائي ──────────
    # local (الافتراضي): خادم Node على جهاز المدرسة كما كان حرفاً.
    # evolution: الخادم السحابي على سيرفرنا. auto: المحلي أولاً، والسحابي حين
    # يتعطّل المحلي أو يبلغ سقفه اليومي. انظر wa_evolution.py.
    # المفتاح مفتاح جلسة المدرسة وحدها (darbstu-evo-add على السيرفر) — يبقى
    # فارغاً هنا: هذه بذرة كل تنصيب، ومفتاحٌ فيها يُشحن إلى كل مدرسة.
    "whatsapp_provider":       "local",
    "evolution_server_url":    "https://wa-api.darbstu.com",
    "evolution_api_key":       "",
    "evolution_instance_name": "darbstu_main",
    "evolution_webhook_token": "",
    # ─── وقت إرسال رابط التأخر المجدوَل ────────────────────────
    "tardiness_auto_send_enabled": True,   # تفعيل الإرسال التلقائي المجدوَل
    "tardiness_auto_send_time":    "07:00",# وقت الإرسال (HH:MM)
    # ─── جنس المدرسة ────────────────────────────────────────────
    "school_gender": "boys",  # boys = بنين ، girls = بنات
    # ابتدائية البنات تضمّ أولاداً في الصفوف الأولى، وهم في الواقع
    # مدرستان في مبنى واحد ولكلٍّ فصله — لكن نور يُصدّرهم في فصل واحد
    # ولا يُصدّر الجنس. هذا المفتاح يشطر الفصل المختلط عند الاستيراد
    # بالاستنتاج من الاسم. **مطفأ افتراضياً**: مدرسةٌ خالصة الجنس لا
    # شأن لها به، وتشغيله عليها يشطر فصولها بلا سبب.
    "split_classes_by_gender": False,
    # ─── إعدادات بوتات الواتساب ─────────────────────────────────
    "absence_bot_enabled":    False,  # مغلق افتراضياً — تشغّله المدرسة عند الحاجة (مزعجٌ دائماً)
    "permission_bot_enabled": False,  # مغلق افتراضياً — تشغّله المدرسة عند الحاجة
    # ─── إعدادات الربط السحابي ─────────────────────────────────
    "cloud_mode":             False,  # تفعيل الربط بسيرفر خارجي
    "cloud_url":              "",     # رابط السيرفر السحابي (مثلاً https://school.domain.com)
    "cloud_token":            "",     # رمز الأمان (Access Token)
    # ─── إعدادات التحديث التلقائي ──────────────────────────────
    "auto_update_enabled":    False,
    "auto_update_hour":       3,
    # ─── إعدادات تعزيز الحضور الأسبوعي ───────────────────────
    "weekly_reward_enabled":  False,
    "weekly_reward_day":      4,      # 4 = الخميس
    "weekly_reward_hour":     14,
    "weekly_reward_minute":   0,
    "weekly_reward_template": (
        "🌟 تهنئة من {school_name}\n"
        "{guardian}/ {student_name}\n"
        "نحيي {son} على {his_commit} و{his_attend} المكتمل طوال هذا الأسبوع.\n"
        "الاستمرار في هذا الانضباط هو سر النجاح والتفوق. فخورون بك!\n"
        "مع التقدير،\nإدارة {school_name}"
    ),
}

_CONFIG_CACHE: Dict[str, Any] = {}
_CONFIG_MTIME: float = 0.0

def invalidate_config_cache():
    global _CONFIG_CACHE, _CONFIG_MTIME
    _CONFIG_CACHE = {}; _CONFIG_MTIME = 0.0


def get_terms() -> dict:
    """
    يُرجع المصطلحات المناسبة حسب جنس المدرسة.
    boys: طالب، طالبة الأمر ← غير صحيح
    girls: طالبة، ابنتكم، تغيّبت ...
    """
    cfg    = load_config()
    gender = cfg.get("school_gender", "boys")
    if gender == "girls":
        return {
            "student":      "الطالبة",
            "student_indef":"طالبة",
            "students":     "الطالبات",
            "absent_v":     "تغيّبت",
            "late_v":       "تأخّرت",
            "son":          "ابنتكم",
            "guardian":     "ولية أمر الطالبة",
            "absent_days":  "أيام غياب ابنتكم",
            "his":          "حضورها",
            # ضمائر كانت مثبَّتة داخل القوالب فتبقى مذكَّرة في مدارس البنات
            "his_class":    "فصلها",
            "his_attain":   "تحصيلها",
            "his_commit":   "التزامها",
            "his_attend":   "حضورها",
            "affairs":      "وكيلة شؤون الطالبات",
            "gender":       "girls",
        }
    else:
        return {
            "student":      "الطالب",
            "student_indef":"طالب",
            "students":     "الطلاب",
            "absent_v":     "تغيّب",
            "late_v":       "تأخّر",
            "son":          "ابنكم",
            "guardian":     "ولي أمر الطالب",
            "absent_days":  "أيام غياب ابنكم",
            "his":          "حضوره",
            "his_class":    "فصله",
            "his_attain":   "تحصيله",
            "his_commit":   "التزامه",
            "his_attend":   "حضوره",
            "affairs":      "وكيل شؤون الطلاب",
            "gender":       "boys",
        }

def load_config() -> Dict[str, Any]:
    """Loads configuration with file-mtime cache — بلا قراءة متكررة."""
    global _CONFIG_CACHE, _CONFIG_MTIME
    try:
        mtime = os.path.getmtime(CONFIG_JSON) if os.path.exists(CONFIG_JSON) else 0.0
    except OSError:
        mtime = 0.0
    if _CONFIG_CACHE and mtime == _CONFIG_MTIME:
        return _CONFIG_CACHE
    cfg = {}
    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, IOError):
            cfg = {}

    changes_made = False
    # التوقيت الصيفي والشتوي (3.6.78): مدرسةٌ قائمة **يبقى وقتها كما هو** — يُعدّ
    # شتوياً إن كان 7:00 فما بعد وإلا صيفياً، ويأخذ التوقيت الآخر افتراضه. قبل دمج
    # الافتراضات، وإلا صار «صيفي 6:45» لمدرسةٍ ضبطت 7:00 فتغيّر حساب تأخرها.
    if "school_timing" not in cfg and _hhmm(cfg.get("school_start_time")):
        st = _hhmm(cfg.get("school_start_time"))
        apply_school_timing(cfg, season="winter" if st >= "07:00" else "summer", start=st)
        changes_made = True
    for key, default_value in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = default_value
            changes_made = True

    # قالب التأخر الافتراضي القديم (بلا بداية الدوام) يصير الجديد — والقالب
    # الذي عدّلته المدرسة لا يُمسّ؛ تضيف {start_time} إليه متى شاءت.
    if cfg.get("tardiness_message_template") == TARDY_TEMPLATE_V1:
        cfg["tardiness_message_template"] = DEFAULT_CONFIG["tardiness_message_template"]
        changes_made = True

    # توليد توكن تلقائي إذا كان فارغاً (للجهاز الرئيسي)
    if not cfg.get("cloud_token"):
        cfg["cloud_token"] = secrets.token_urlsafe(16)
        changes_made = True

    if changes_made:
        try:
            with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except IOError:
            print(f"Warning: Could not update config file at {CONFIG_JSON}")

    # حفظ في الـ cache
    _CONFIG_CACHE = cfg
    try:
        _CONFIG_MTIME = os.path.getmtime(CONFIG_JSON) if os.path.exists(CONFIG_JSON) else 0.0
    except OSError:
        pass
    return cfg


def ar(txt: str) -> str:
    """يضبط عرض النص العربي (shaping + bidi). لو المكتبات غير متوفرة يرجّع النص كما هو."""
    try:
        _ensure_matplotlib()
        if _const.arabic_reshaper and _const.get_display:
            return _const.get_display(_const.arabic_reshaper.reshape(str(txt)))
    except Exception:
        pass
    return str(txt)



def get_message_template() -> str:
    cfg = load_config()
    return (cfg.get("message_template") or DEFAULT_CONFIG["message_template"]).strip()

class _SafeTerms(dict):
    """
    قاموس تنسيق لا ينهار على متغيّر مجهول.

    القوالب محفوظة في config.json لكل مدرسة، فقالب مدرسة قديمة قد يحوي
    متغيّراً لم يعد موجوداً — والسلوك السابق كان يرفع KeyError ثم يعيد
    التنسيق بأربعة متغيّرات فقط، فيرفع KeyError ثانية بلا التقاط
    وتفشل الرسالة كلها. الآن يُترك المجهول كما هو وتصل الرسالة.
    """
    def __missing__(self, key):
        return "{" + key + "}"


# ═══════════════════════════════════════════════════════════════
#  تأنيث النصوص لمدارس البنات
# ═══════════════════════════════════════════════════════════════
# ألفاظ التذكير مثبَّتة في مئات المواضع (عناوين مستندات، تسميات واجهة،
# نصوص خطابات)، ولا يمكن تمرير كلٍّ منها عبر get_terms يدوياً. هذه
# الدالة تعالجها عند التصيير في نقاط الاختناق.
#
# مقصورة على **الأسماء والألقاب** عمداً. الأفعال (تغيّب/تغيّبت) تُترك
# لنظام القوالب: تصريفها يعتمد على موقعها في الجملة، والاستبدال الأعمى
# يُنتج عربية مكسورة.
_FEM_RULES = [
    # الأطول أولاً — وإلا التقطت القاعدة الأقصر جزءاً من عبارة أطول
    (r"وكيل شؤون الطلاب",     "وكيلة شؤون الطالبات"),
    (r"وكيل المدرسة",          "وكيلة المدرسة"),
    # صيغة الجرّ المدغمة: «لـ + الموجّه» تُكتب «للموجّه»، فلا يظهر فيها
    # «الموجّه» حرفياً ولا تلتقطها القاعدة التالية. فكانت تُنتج «للموجّهة
    # الطلابي» — مؤنّثة النصف. نفس علّة «روابط الحصص للمعلمين» سابقاً:
    # **الإدغام يكسر المطابقة، فكل عبارة مجرورة تحتاج قاعدتها.**
    (r"للموجّه الطلابي",       "للموجّهة الطلابية"),
    (r"للموجه الطلابي",        "للموجهة الطلابية"),
    (r"للموجّه الصحي",         "للموجّهة الصحية"),
    (r"للموجه الصحي",          "للموجهة الصحية"),
    (r"الموجّه الطلابي",       "الموجّهة الطلابية"),
    (r"الموجه الطلابي",        "الموجهة الطلابية"),
    (r"الموجّه الصحي",         "الموجّهة الصحية"),
    (r"الموجه الصحي",          "الموجهة الصحية"),
    (r"موجه صحي",              "موجهة صحية"),
    # ── الطاقم: إداريون وموجهون ومعلمون ───────────────────────────
    # المصدر يُكتب بالمذكّر دائماً ويُؤنَّث هنا. غياب هذه القواعد جعلني
    # أكتب المؤنث صراحةً في أزرار تصفية الطاقم، فظهرت «المعلمات
    # والإداريات» في مدرسة بنين. الترتيب: الأطول أولاً، والمرور واحد.
    (r"الموجّهين الطلابيين",   "الموجّهات الطلابيات"),
    (r"الموجهين الطلابيين",    "الموجهات الطلابيات"),
    (r"موجه طلابي",            "موجهة طلابية"),
    (r"الإداريين",             "الإداريات"),
    (r"الاداريين",             "الاداريات"),
    (r"الإداريون",             "الإداريات"),
    (r"الاداريون",             "الاداريات"),
    (r"إداريين",               "إداريات"),
    (r"اداريين",               "اداريات"),
    (r"الموجّهين",             "الموجّهات"),
    (r"الموجهين",              "الموجهات"),
    (r"موجّهين",               "موجّهات"),
    (r"موجهين",                "موجهات"),
    # الأفراد — بحدّ كلمة حتى لا تُلتقط «معلمة» أو «معلمين» من داخلها
    (r"معلم\b",                "معلمة"),
    (r"إداري\b",               "إدارية"),
    (r"اداري\b",               "ادارية"),
    (r"موجّه\b",               "موجّهة"),
    (r"موجه\b",                "موجهة"),
    # المصطلح المعتمد «الموجّه الطلابي». يبقى السطر ليُصحّح ما خُزّن
    # في بيانات مدرسة قديمة أو بقي في نصٍّ لم يُحدَّث.
    (r"المرشدة الطلابية",      "الموجّهة الطلابية"),
    (r"المرشد الطلابي",        "الموجّهة الطلابية"),
    (r"مدير المدرسة",          "مديرة المدرسة"),
    (r"المدير\b",              "المديرة"),
    (r"ولي أمر الطالب(?!ة)",   "ولية أمر الطالبة"),
    (r"ولي الأمر",             "ولية الأمر"),
    (r"ولي أمر",               "ولية أمر"),
    (r"أولياء الأمور",         "أولياء الأمور"),       # تبقى كما هي
    (r"اسم الطالب(?!ة|ات)",    "اسم الطالبة"),
    # صفة الجمع تتبع موصوفها: «الطلاب المستثنون» كان يصير «الطالبات
    # المستثنون» — يُؤنَّث الاسم وتبقى صفته مذكّرة، وهو خطأ نحوي ظاهر
    # في تسعة مواضع معروضة. ويجب أن تسبق قواعد «الطلاب» لأن المُطابِق
    # يمسح النصّ مرّةً واحدة بتبديلٍ واحد لكل موضع.
    (r"المستثنون",             "المستثنيات"),
    (r"المستثنين",             "المستثنيات"),
    (r"مستثنون",               "مستثنيات"),
    (r"المستثنى",              "المستثناة"),
    # لا تُمسّ النسبة «الطلابي/الطلابية» — «النشاط الطلابي» ليس جمعاً
    (r"الطلاب(?!ي)",           "الطالبات"),
    (r"طلاب(?!ي)",             "طالبات"),
    (r"الطالب(?!ة|ات)",        "الطالبة"),
    (r"بالطالب(?!ة|ات)",       "بالطالبة"),
    (r"طالباً",                "طالبة"),
    # النكرة المجرَّدة «إضافة طالب». اللواحق مستثناة كي لا تُمسّ
    # «طالبة/طالبات/طالباً» ولا النسبة «طالبي»
    (r"طالب(?!ة|ات|اً|ين|ي)",  "طالبة"),
    (r"المعلمين",              "المعلمات"),
    (r"المعلمون",              "المعلمات"),
    (r"المعلم(?!ة|ات|ين|ون)",  "المعلمة"),
    (r"ابنكم",                 "ابنتكم"),
    (r"ابنك(?!م|ة)",           "ابنتك"),
]

_FEM_COMPILED = None


def feminize(text):
    """
    يؤنّث نص واجهة/مستند إذا كانت المدرسة بنات، ويعيده كما هو خلاف ذلك.

    تُستدعى في نقاط التصيير النهائية (مولّدات PDF مثلاً) لا على البيانات
    المخزّنة — تحويل المخزَّن يفسده عند تغيير نوع المدرسة.
    """
    global _FEM_COMPILED
    if not text:
        return text
    try:
        if load_config().get("school_gender") != "girls":
            return text
    except Exception:
        return text
    if _FEM_COMPILED is None:
        import re as _re
        # مرور واحد بتناوب مُرتَّب: تطبيق القواعد تِباعاً كان يجعل قاعدة
        # لاحقة تعيد مطابقة ناتج سابقة — «الموجه الطلابي» صارت
        # «الموجهة الطالباتية». المرور الواحد يستهلك كل موضع مرة.
        joined = "|".join(f"(?P<g{i}>{p})" for i, (p, _) in enumerate(_FEM_RULES))
        _FEM_COMPILED = (_re.compile(joined), [r for _, r in _FEM_RULES])

    pattern, reps = _FEM_COMPILED

    def _pick(m):
        for i, rep in enumerate(reps):
            if m.group(f"g{i}") is not None:
                return rep
        return m.group(0)

    return pattern.sub(_pick, str(text))


# ═══════════════════════════════════════════════════════════════
#  مفتاح إيقاف كل البوتات
# ═══════════════════════════════════════════════════════════════
# ستة أشياء تعمل تلقائياً: رسائل الغياب، الاستئذان، الإشعارات الذكية،
# التقرير اليومي، رابط التأخر المجدوَل، ومكافأة الحضور الأسبوعية.
# إطفاؤها واحداً واحداً متعب، ونسيان واحد يعني رسائل تخرج بلا قصد.
#
# المفتاح الرئيسي يعلو عليها جميعاً **دون أن يمحو ضبطها الفردي**:
# إطفاؤه ثم تشغيله يُعيد كل شيء كما كان، لا يشغّل ما كان مطفأً.

BOT_FLAGS = (
    "absence_bot_enabled",
    "permission_bot_enabled",
    "alert_enabled",
    "daily_report_enabled",
    "tardiness_auto_send_enabled",
    "weekly_reward_enabled",
)

# المفتاح الرئيسي يوقف ما يخرج **لأولياء الأمور** فقط. ما يدور داخل
# الطاقم الإداري يستمر، لأن سبب الإيقاف عملياً واحد من اثنين: إجازة أو
# اختبارات (فلا معنى لإزعاج الأهالي)، أو خوف من تجميد رقم الواتساب —
# والتجميد يأتي من الإرسال الكثيف لأرقام ليست في جهات الاتصال، أي
# أولياء الأمور. رسالة واحدة لجوال الإدارة لا تُسبّبه، وإيقافها يحرم
# المدير من تقريره اليومي بلا فائدة.
PARENT_FLAGS = frozenset((
    "absence_bot_enabled",
    "permission_bot_enabled",
    "tardiness_auto_send_enabled",
    "weekly_reward_enabled",
))

# يذهب للإدارة وحدها — لا يتأثر بالمفتاح
STAFF_FLAGS = frozenset(("daily_report_enabled",))

# مختلط: الإشعارات الذكية تُرسل لولي الأمر وللإدارة معاً. المهمة نفسها
# تبقى تعمل، ويُكتم شقّها الموجَّه لولي الأمر عبر parent_sending_on().
MIXED_FLAGS = frozenset(("alert_enabled",))


def parent_sending_on() -> bool:
    """
    هل يُسمح بإرسال رسائل تلقائية **لأولياء الأمور**؟

    استعملها في كل موضع يُرسل لولي أمر ضمن مهمة مختلطة، وإلا خرجت رسالة
    للأهالي والمفتاح مُطفأ.
    """
    return bots_master_on()


def bots_master_on() -> bool:
    """هل المفتاح الرئيسي للبوتات مُشغَّل؟ (الافتراضي: نعم)"""
    try:
        return bool(load_config().get("bots_master_enabled", True))
    except Exception:
        return True


def set_reply_bot(on: bool, timeout: float = 3.0) -> bool:
    """
    يشغّل/يوقف البوت المستقبِل في خادم الواتساب.

    هذا هو البوت الذي يقرأ ردود أولياء الأمور: يسجّل الأعذار ويقيّد
    موافقات الاستئذان ويردّ عليهم. حالته تعيش في خادم Node لا هنا،
    فلا بد من مناداته عبر HTTP — ونعيد False عند الفشل بدل ابتلاعه،
    وإلا ظنّ المدير أنه أوقفه وهو يعمل.
    """
    import json as _j
    import urllib.request as _ur
    # السحابي: لا خادم Node يحمل الحالة، فتُكتب في ملفه مباشرةً — الملف نفسه
    # الذي يقرؤه server.js وبوت السحابي، فالتبديل بين المزوّدين لا يغيّرها.
    try:
        import wa_evolution
        _prov = wa_evolution.provider()
        if _prov != "local":
            _wrote = wa_evolution.write_bot_config(enabled=bool(on))
            if _prov == "evolution":
                return _wrote
    except Exception as e:
        print(f"[BOTS] تعذّر حفظ حالة البوت السحابي: {e}")
    try:
        port = int(load_config().get("whatsapp_port", 3000) or 3000)
    except Exception:
        port = 3000
    try:
        req = _ur.Request("http://127.0.0.1:%d/bot-toggle" % port,
                          data=_j.dumps({"enabled": bool(on)}).encode(),
                          headers={"Content-Type": "application/json"},
                          method="POST")
        with _ur.urlopen(req, timeout=timeout) as r:
            _j.loads(r.read().decode())
        return True
    except Exception as e:
        print(f"[BOTS] تعذّر بلوغ خادم الواتساب: {e}")
        return False


def set_bots_master(on: bool) -> bool:
    """
    المفتاح الواحد: يوقف كل ما يخصّ أولياء الأمور — الصادر والوارد.

    الصادر: رسائل الغياب والتأخر والاستئذان والتعزيز (عبر PARENT_FLAGS).
    الوارد: البوت الذي يردّ على أولياء الأمور ويسجّل أعذارهم.
    ولا يمسّ ما يدور داخل الطاقم الإداري.
    """
    try:
        cfg = load_config()
        cfg["bots_master_enabled"] = bool(on)
        save_config(cfg)
        print(f"[BOTS] الإرسال لأولياء الأمور: {'تشغيل' if on else 'إيقاف'}")
    except Exception as e:
        print(f"[BOTS] تعذّر الحفظ: {e}")
        return False
    # الوارد يعيش في خادم Node — قد يكون مطفأً، ولا يمنع ذلك حفظ الإعداد
    set_reply_bot(on)
    return True


def bot_enabled(flag: str, default: bool = True) -> bool:
    """
    هل هذه المهمة التلقائية مسموح لها بالعمل؟

    استعملها بدل `cfg.get(flag)` المباشر في كل موضع يُطلق إرسالاً
    تلقائياً — وإلا أفلتت مهمة من المفتاح الرئيسي وأرسلت بلا إذن.

    المفتاح الرئيسي يوقف مهام أولياء الأمور وحدها. مهام الطاقم الإداري
    تستمر، والمختلطة تعمل ويُكتم شقّها الأبوي عبر `parent_sending_on()`.
    """
    try:
        cfg = load_config()
        if flag in PARENT_FLAGS and not cfg.get("bots_master_enabled", True):
            return False
        return bool(cfg.get(flag, default))
    except Exception:
        return default


def bots_status() -> dict:
    """حالة كل البوتات — للعرض في الواجهة."""
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    master = bool(cfg.get("bots_master_enabled", True))
    return {
        "master": master,
        "flags": {f: bool(cfg.get(f, False)) for f in BOT_FLAGS},
        "active": sum(1 for f in BOT_FLAGS if master and cfg.get(f, False)),
    }


def render_template(tpl: str, **extra) -> str:
    """
    تصيير أي قالب رسالة مع كل مصطلحات الجنس تلقائياً.

    استعملها بدل `tpl.format(...)` المباشر: تمرير المصطلحات يدوياً في كل
    موضع كان يُنسي بعضها، فتبقى الرسالة مذكَّرة في مدرسة بنات أو تفشل
    بـ KeyError عند إضافة مصطلح جديد لقالب.
    """
    return _render(tpl, **extra)


# ═══════════════════════════════════════════════════════════════
#  التوقيت الصيفي والشتوي للدوام (طلب ماهر ١٧ نوفمبر ٢٠٢٦)
# ═══════════════════════════════════════════════════════════════
# وقتان محفوظان (الصيفي 6:45 والشتوي 7:00 افتراضاً) واختيارٌ بينهما. ويبقى
# school_start_time المصدرَ الوحيد لكل حساب — التأخر والرسائل والبصمة ورابط
# التأخر — وهو دائماً وقتُ التوقيت المختار: كل كاتبٍ يمرّ بـapply_school_timing.
TIMING_SEASONS = ("summer", "winter")
TIMING_DEFAULTS = {"summer": "06:45", "winter": "07:00"}
TIMING_NAMES = {"summer": "الصيفي", "winter": "الشتوي"}


def _hhmm(v) -> str:
    """'7:5' ← '07:05'، وما لا يُفهم ← ''."""
    try:
        return datetime.datetime.strptime(str(v).strip()[:5], "%H:%M").strftime("%H:%M")
    except Exception:
        return ""


def apply_school_timing(cfg, season=None, summer=None, winter=None, start=None):
    """
    يضبط التوقيت في cfg ويجعل school_start_time وقتَ التوقيت المختار. يُرجع cfg.
      season         'summer'|'winter' — التبديل
      summer/winter  وقتا التوقيتين
      start          وقتٌ مباشر من كاتبٍ لا يعرف التوقيتين (صفحة الجدول، والمكتبي القديم)
                     ⇒ يصير وقتَ التوقيت المختار، فلا ينفصل عنه
    والقيمة غير المفهومة تُتجاهل ويبقى ما كان.
    """
    cur = cfg.get("school_timing")
    if cur not in TIMING_SEASONS:
        cur = "summer"
    if season in TIMING_SEASONS:
        cur = season
    for s, v in (("summer", summer), ("winter", winter)):
        if _hhmm(v):
            cfg["school_start_time_" + s] = _hhmm(v)
    if _hhmm(start):
        cfg["school_start_time_" + cur] = _hhmm(start)
    for s in TIMING_SEASONS:
        if not _hhmm(cfg.get("school_start_time_" + s)):
            cfg["school_start_time_" + s] = TIMING_DEFAULTS[s]
    cfg["school_timing"] = cur
    cfg["school_start_time"] = cfg["school_start_time_" + cur]
    return cfg


def format_clock(hhmm) -> str:
    """'07:05' ← «7:05 صباحاً» · '13:30' ← «1:30 مساءً». وما لا يُفهم يعود كما هو."""
    try:
        h, m = [int(x) for x in str(hhmm).strip()[:5].split(":")]
        return "%d:%02d %s" % ((h % 12) or 12, m, "صباحاً" if h < 12 else "مساءً")
    except Exception:
        return str(hhmm or "")


def _tardiness_clock(cfg, minutes_late):
    """وقت الحضور = بداية الدوام الرسمية + دقائق التأخر (تُحسب منها لا من السماح)."""
    try:
        s = datetime.datetime.strptime(str(cfg.get("school_start_time", "07:00"))[:5], "%H:%M")
        return format_clock((s + datetime.timedelta(minutes=int(minutes_late))).strftime("%H:%M"))
    except Exception:
        return ""


def _render(tpl: str, **extra) -> str:
    cfg = load_config()
    data = _SafeTerms(get_terms())
    data["school_name"] = cfg.get("school_name", "المدرسة")
    # بداية الدوام الرسمية — من الإعدادات وقت الإرسال، فتتبع التوقيت الشتوي/الصيفي
    # بلا تعديل القالب، ولا يدخلها السماح (طلب ماهر، ١٧ نوفمبر ٢٠٢٦)
    data["start_time"] = format_clock(cfg.get("school_start_time", "07:00"))
    if "minutes_late" in extra and "arrival_time" not in extra:
        data["arrival_time"] = _tardiness_clock(cfg, extra.get("minutes_late"))
    data.update(extra)
    try:
        return tpl.format_map(data)
    except Exception as e:
        print(f"[Config] تعذّر تصيير القالب: {e}")
        return tpl


def render_message(student_name: str, class_name: str, date_str: str) -> str:
    return _render(get_message_template(), student_name=student_name,
                   class_name=class_name, date=date_str)


def render_reward_message(student_name: str) -> str:
    cfg = load_config()
    tpl = cfg.get("weekly_reward_template") or DEFAULT_CONFIG["weekly_reward_template"]
    return _render(tpl, student_name=student_name)

def logo_img_tag_from_config(cfg: Dict[str, Any]) -> str:
    path = (cfg.get("logo_path") or "").strip()
    if not path: return ""
    try:
        with open(path, "rb") as f: b64 = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(path)[1].lower()
        mime = "image/png" if ext == ".png" else "image/jpeg"
        return f'<img src="data:{mime};base64,{b64}" style="height:80px"/>'
    except Exception: return ""


def get_window_title():
    """يُرجع عنوان النافذة مع نوع المدرسة."""
    try:
        cfg    = load_config()
        school = cfg.get("school_name", "")
        gender = cfg.get("school_gender", "boys")
        g_tag  = " (بنات)" if gender == "girls" else " (بنين)"
        return f"DarbStu{g_tag} — {school}" if school else f"DarbStu{g_tag}"
    except Exception:
        return "DarbStu"


def save_config(cfg: dict):
    """يحفظ الإعدادات إلى ملف config.json."""
    try:
        with open(CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        invalidate_config_cache()
    except IOError as e:
        print(f"[Config] فشل الحفظ: {e}")

