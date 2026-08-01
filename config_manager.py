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
        "نفيدكم بتغيب {son} عن فصله ({class_name}) بتاريخ {date}.\n"
        "نأمل متابعة {his} لضمان استمرارية تحصيله العلمي.\n"
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
        "نأمل الاهتمام بحضوره في الوقت المحدد.\n"
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
        "الطالب: {student_name}\n"
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
        "نحيي {his} على التزامه وحضوره المكتمل طوال هذا الأسبوع.\n"
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

def render_message(student_name: str, class_name: str, date_str: str) -> str:
    cfg   = load_config()
    terms = get_terms()
    school = cfg.get("school_name", "المدرسة")
    tpl    = get_message_template()
    try:
        return tpl.format(
            school_name=school, student_name=student_name,
            class_name=class_name, date=date_str,
            guardian=terms["guardian"], son=terms["son"],
            his=terms["his"], absent_v=terms["absent_v"],
        )
    except KeyError:
        return tpl.format(school_name=school, student_name=student_name,
                          class_name=class_name, date=date_str)

def render_reward_message(student_name: str) -> str:
    cfg   = load_config()
    terms = get_terms()
    school = cfg.get("school_name", "المدرسة")
    tpl    = cfg.get("weekly_reward_template") or DEFAULT_CONFIG["weekly_reward_template"]
    try:
        return tpl.format(
            school_name=school, student_name=student_name,
            guardian=terms["guardian"], son=terms["son"],
            his=terms["his"]
        )
    except KeyError:
        return tpl.format(school_name=school, student_name=student_name)

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

