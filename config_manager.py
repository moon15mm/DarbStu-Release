# -*- coding: utf-8 -*-
"""
config_manager.py — إدارة الإعدادات وقوالب الرسائل
"""
import os, json, base64, secrets, datetime
from typing import Dict, Any, List, Optional
import constants as _const
from constants import (DATA_DIR, CONFIG_JSON, DB_PATH, BASE_DIR,
                       TZ_OFFSET, _ensure_matplotlib)

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
    "school_start_time": "07:00",
    "tardiness_recipients": [],
    "tardiness_message_template": (
        "⏱ تنبيه تأخر من {school_name}\n"
        "{guardian}/ {student_name}\n"
        "نُحيطكم علماً بأن {son} {late_v} عن الحضور اليوم ({date})\n"
        "بمقدار {minutes_late} دقيقة.\n"
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
    # ─── وقت إرسال رابط التأخر المجدوَل ────────────────────────
    "tardiness_auto_send_enabled": True,   # تفعيل الإرسال التلقائي المجدوَل
    "tardiness_auto_send_time":    "07:00",# وقت الإرسال (HH:MM)
    # ─── جنس المدرسة ────────────────────────────────────────────
    "school_gender": "boys",  # boys = بنين ، girls = بنات
    # ─── إعدادات بوتات الواتساب ─────────────────────────────────
    "absence_bot_enabled":    True,   # بوت رسائل الغياب التلقائية
    "permission_bot_enabled": True,   # بوت رسائل الاستئذان التلقائية
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
    for key, default_value in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = default_value
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
    (r"الموجّه الطلابي",       "الموجّهة الطلابية"),
    (r"الموجه الطلابي",        "الموجهة الطلابية"),
    (r"المرشد الطلابي",        "المرشدة الطلابية"),
    (r"مدير المدرسة",          "مديرة المدرسة"),
    (r"ولي أمر الطالب(?!ة)",   "ولية أمر الطالبة"),
    (r"ولي الأمر",             "ولية الأمر"),
    (r"ولي أمر",               "ولية أمر"),
    (r"أولياء الأمور",         "أولياء الأمور"),       # تبقى كما هي
    (r"اسم الطالب(?!ة|ات)",    "اسم الطالبة"),
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


def bots_master_on() -> bool:
    """هل المفتاح الرئيسي للبوتات مُشغَّل؟ (الافتراضي: نعم)"""
    try:
        return bool(load_config().get("bots_master_enabled", True))
    except Exception:
        return True


def set_bots_master(on: bool) -> bool:
    """يشغّل/يوقف كل البوتات دفعةً واحدة."""
    try:
        cfg = load_config()
        cfg["bots_master_enabled"] = bool(on)
        save_config(cfg)
        print(f"[BOTS] المفتاح الرئيسي: {'تشغيل' if on else 'إيقاف'}")
        return True
    except Exception as e:
        print(f"[BOTS] تعذّر الحفظ: {e}")
        return False


def bot_enabled(flag: str, default: bool = True) -> bool:
    """
    هل هذه المهمة التلقائية مسموح لها بالعمل؟

    استعملها بدل `cfg.get(flag)` المباشر في كل موضع يُطلق إرسالاً
    تلقائياً — وإلا أفلتت مهمة من المفتاح الرئيسي وأرسلت بلا إذن.
    """
    try:
        cfg = load_config()
        if not cfg.get("bots_master_enabled", True):
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


def _render(tpl: str, **extra) -> str:
    cfg = load_config()
    data = _SafeTerms(get_terms())
    data["school_name"] = cfg.get("school_name", "المدرسة")
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

