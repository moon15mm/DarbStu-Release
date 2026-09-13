# -*- coding: utf-8 -*-
"""
wa_limits.py — سقوف إرسال واتساب لتقليل الحظر.

واتساب لا يقيس المدة بين الرسائل بقدر ما يقيس **الحجم من رقم حديث
إلى أرقام ليست في جهات الاتصال**. لهذا استمر التجميد ٢٤ ساعة رغم
التأخير العشوائي: التأخير يعالج عَرَضاً لا سبباً.

ثلاث حمايات هنا:

  ١. سقف يومي لكل رقم — لم يكن موجوداً إطلاقاً
  ٢. إحماء تصاعدي للرقم الجديد (أخطر مرحلة)
  ٣. تباعد متزايد كلما طالت الدفعة

وهذا يقلّل الحظر ولا يلغيه: `whatsapp-web.js` يخالف شروط واتساب
أصلاً. الحماية الأقوى خارج الكود — أن يحفظ أولياء الأمور رقم المدرسة.
"""
import datetime
import json
import os
import random
import sys
import threading

from constants import DATA_DIR

STATE_FILE = os.path.join(DATA_DIR, ".wa_limits.json")
_LOCK = threading.Lock()

# السقف اليومي حسب عمر الرقم. الرقم الجديد هو الأكثر عرضة للحظر،
# والمصادر توصي بألا يراسل أكثر من ~٢٠ جهة جديدة في أيامه الأولى.
_WARMUP = [
    (3,   20),    # أول ٣ أيام
    (7,   50),
    (14, 100),
]
_MAX_DAILY = 150          # بعد أسبوعين — لأولياء الأمور

# ── دفتر الطاقم، مستقلٌّ عن دفتر أولياء الأمور ────────────────────────
# كان الدفتر واحداً يشرب منه الجميع، وكان الطاقم يأخذ أكثر من الأهالي:
# ‏`schedule_sender` يرسل لكل معلم **رسالةً لكل حصة** — ٧ حصص × ~١٢ معلماً
# تبتلع ثلثي سقف اليوم قبل أن يُرسَل لولي أمر واحد.
#
# والفصل ليس تحايلاً على الحظر بل تصحيحٌ لنموذجه: خطر واتساب يأتي من
# مراسلة أرقام **لا تحفظك ولم تراسلك**. الطاقم عكس ذلك تماماً — موظفون
# في المدرسة، أربعون لا أربعمئة، يردّون على الرسائل. سقفهم موجود لصيد
# الحلقات الشاردة (خلل يرسل آلاف الرسائل) لا لاتّقاء بلاغات الإزعاج.
_STAFF_WARMUP = [
    (3,   40),
    (7,  100),
]
_MAX_STAFF_DAILY = 200

# ── الرقم الجديد هو القيد، لا عدد الرسائل ────────────────────────────
# ما يُشعل كاشف الإزعاج هو مراسلة أرقام **لم تراسلك ولا تحفظك**. وقائمة
# أولياء أمور المدرسة مغلقة وثابتة: بعد أسبوعين لم يبقَ فيها رقم جديد،
# فالسقف الذي يعدّ الرسائل يعاقب الاستمرار لا الخطر.
#
# فصار سقف `_WARMUP`/`_MAX_DAILY` أعلاه يحكم **الأرقام الجديدة اليوم**
# وحدها، ولرسائل الأرقام المعروفة سقفٌ أعلى بكثير غرضه صيد الحلقات
# الشاردة لا اتّقاء البلاغات.
#
# ⚠️ القاعدة التي بُني عليها هذا كله: **لا يمنع هذا النموذج شيئاً كان
# يمرّ قبله.** سقف الأرقام الجديدة هو نفس الرقم القديم بنفس الإحماء،
# والمعروف يأخذ ما هو أوسع. مدارس كثيرة تعمل الآن، وأي تضييق يعطّلها
# صامتاً. يحرس ذلك `tools/check_wa_accounting.py`.
_MAX_KNOWN_DAILY = 800

# دفتر جهات الاتصال المعروفة — ملف مستقل عن حالة اليوم عمداً: حالة اليوم
# تُكتب مع كل رسالة، والدفتر لا يُكتب إلا حين يُعرف رقمٌ جديد (نادر).
CONTACTS_FILE = os.path.join(DATA_DIR, ".wa_contacts.json")

# يُنسى الرقم بعد هذه المدة بلا مراسلة فيعود «جديداً» — وهو الصحيح:
# ولي أمر لم يصله شيء منذ نصف عام لم يعد يعرف الرقم.
_CONTACT_TTL_DAYS = 180

PARENT = "parent"
STAFF = "staff"
# دفاتر فرعية لأولياء الأمور
NEW = "parent_new"
KNOWN = "parent_known"


class _Grant(tuple):
    """
    نتيجة الحجز: `(مسموح, سبب)` — والدفترُ في خاصية لا في عنصرٍ ثالث.

    الطول اثنان عمداً. التحديث يكتب ملفات `.py` واحداً واحداً، فقد ينقطع
    ويترك `wa_limits` جديدة بجانب `whatsapp_service` قديمة تفكّ عنصرين.
    عنصرٌ ثالث كان يرفع ValueError هناك، **ويبتلعها `except Exception`
    المحيط بالفحص فيمضي الإرسال بلا أي سقف** — أسوأ ما قد يصيب رقم
    مدرسة. الخاصية تُقرأ بـ`getattr` فتتجاهلها النسخة القديمة بسلام.
    """

    def __new__(cls, ok, why, audience):
        g = super().__new__(cls, (ok, why))
        g.audience = audience
        return g

# تباعد الرسائل — يتصاعد كلما طالت الدفعة داخل اليوم نفسه
_BASE_DELAY = (8, 16)     # ثوانٍ
_SLOW_AFTER = 25          # بعد هذا العدد يبطؤ
_SLOW_DELAY = (20, 35)
_PAUSE_EVERY = 40         # كل هذا العدد وقفة أطول
_PAUSE_DELAY = (90, 150)


# ── من أين خرجت الرسالة؟ ──────────────────────────────────────────────
# العدّاد كان رقماً مجرّداً لا يُفسَّر: تقرير الرسائل لا يعرض إلا الغياب
# والتأخر (٦ مواضع إرسال من ٥٠)، فيرى المدير «أُرسل ١٣٧» وفي التقرير ١٣
# ولا سبيل لمعرفة أين ذهب الباقي. نحصي الآن لكل مصدرٍ نصيبَه.
#
# الرموز **لاتينية** عمداً: وسيط التأنيث يُعيد كتابة نصّ الصفحات في
# مدارس البنات، فأي مفتاح عربي يعبر JSON ثم يُقارَن في الجافاسكربت
# ينكسر هناك وحده. التسميات العربية تُكتب في مصدر الصفحة لا هنا.
_SRC_BY_MODULE = {
    "counselor_tab":     "counselor",
    "teacher_forms_tab": "teacher_form",
    "bus_routes":        "bus",
    "bus_scheduler":     "bus",
    "schedule_sender":   "class_links",
    "schedule_tab":      "class_links",
    "links_tab":         "class_links",
    "users_tab":         "credentials",
    "poller":            "biometric",
}
_SRC_BY_FUNC = {
    "safe_send_absence_alert":     "absence",
    "send_absence_alert":          "absence",
    "web_send_absence_messages":   "absence",
    "_tard_msg_send_selected":     "tardiness",
    "do_send":                     "tardiness",
    "web_send_tardiness_messages": "tardiness",
    "send_tardiness_link_to_all":  "tardiness_link",
    "send_alert_for_student":      "smart_alert",
    "send_daily_report_to_admin":  "daily_report",
    "send_permission_request":     "permission",
    "check_and_award_certificate": "certificate",
    "run_weekly_rewards":          "reward",
    "api_send_portal_link":        "portal_link",
    "_send_circular_wa_alerts":    "circular",
    "web_create_referral":         "referral",
    "web_update_referral":         "referral",
    "_save_deputy_action":         "referral",
    "_notify_deputy_referral":     "referral",
    "_send_referral_to_principal": "referral",
    "_test_send":                  "test",
}
# وحدات لا تُحسب مصدراً — نتخطّاها بحثاً عن المُستدعي الحقيقي
_SRC_SKIP = ("wa_limits", "whatsapp_service")


def detect_source() -> str:
    """يستنتج مصدر الرسالة من مكدّس الاستدعاء — بلا تعديل أي موضع إرسال."""
    try:
        f = sys._getframe(1)
        for _ in range(12):
            if f is None:
                break
            mod = os.path.splitext(os.path.basename(
                f.f_code.co_filename or ""))[0]
            if mod not in _SRC_SKIP:
                fn = f.f_code.co_name
                return (_SRC_BY_MODULE.get(mod)
                        or _SRC_BY_FUNC.get(fn)
                        or "other")
            f = f.f_back
    except Exception:
        pass
    return "other"


# ── من الطاقم ومن وليّ أمر؟ ──────────────────────────────────────────
# القرار من **رقم المستقبِل** لا من الدالة المُرسِلة. مصادر كثيرة تخدم
# الطرفين حسب الإعداد (الإشعارات الذكية، الموجه، الحافلات)، فنسبتها إلى
# دفترٍ بعينه بحسب الشيفرة تُخطئ نصف الوقت. الرقم لا يُخطئ.
_STAFF_KEYS = ("principal_phone", "alert_admin_phone",
               "counselor1_phone", "counselor2_phone")
_staff_cache = {"sig": None, "nums": frozenset()}


def _norm(phone) -> str:
    """يوحّد صيغة الرقم — ٠٥xxxxxxxx و٥xxxxxxxx و٩٦٦٥xxxxxxx سواء."""
    d = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(d) == 10 and d.startswith("05"):
        return "966" + d[1:]
    if len(d) == 9 and d.startswith("5"):
        return "966" + d
    return d


def _staff_numbers() -> frozenset:
    """
    أرقام الطاقم من teachers.json ومن أرقام الإدارة في الإعدادات.

    تُقرأ الملفات **مباشرةً** ولا تُستدعى `load_teachers` إطلاقاً: تلك
    تفتح نافذة حوار حين لا تجد الملف، ونحن نُستدعى من خيط الخادم —
    فتتجمّد الخدمة كلها بانتظار نقرةٍ لا يراها أحد.
    """
    from constants import CONFIG_JSON, TEACHERS_JSON
    try:
        sig = tuple(os.path.getmtime(p) if os.path.exists(p) else 0
                    for p in (TEACHERS_JSON, CONFIG_JSON))
    except Exception:
        sig = None
    if sig is not None and sig == _staff_cache["sig"]:
        return _staff_cache["nums"]

    nums = set()
    try:
        with open(TEACHERS_JSON, encoding="utf-8") as f:
            raw = json.load(f)
        # الملف قد يكون قائمة مجرّدة أو {"teachers": [...]} — كلاهما وُجد
        rows = raw.get("teachers", []) if isinstance(raw, dict) else raw
        for t in rows or []:
            if not isinstance(t, dict):
                continue
            n = _norm(t.get("رقم الجوال") or t.get("phone") or "")
            if n:
                nums.add(n)
    except Exception:
        pass
    try:
        with open(CONFIG_JSON, encoding="utf-8") as f:
            cfg = json.load(f)
        for k in _STAFF_KEYS:
            n = _norm(cfg.get(k) or "")
            if n:
                nums.add(n)
    except Exception:
        pass

    _staff_cache["sig"] = sig
    _staff_cache["nums"] = frozenset(nums)
    return _staff_cache["nums"]


def audience_for(phone) -> str:
    """‏STAFF لرقمٍ في دليل المدرسة، وإلا PARENT (الافتراض الأكثر تحفّظاً)."""
    try:
        return STAFF if _norm(phone) in _staff_numbers() else PARENT
    except Exception:
        return PARENT


# ── دفتر الأرقام المعروفة ────────────────────────────────────────────
# يُخزَّن **بصمة** الرقم لا الرقم: هذا الملف يُرسَل أحياناً للدعم الفني
# عند استقصاء عطل، ولا يصحّ أن يحمل أرقام أولياء الأمور خارج الجهاز.
_contacts_lock = threading.Lock()
_contacts = None          # {بصمة: آخر تاريخ مراسلة}


def _fp(phone) -> str:
    """بصمة قصيرة للرقم — للعدّ لا للتعرّف."""
    import hashlib
    return hashlib.sha256(("darb:" + _norm(phone)).encode()).hexdigest()[:16]


def _seed_from_history() -> dict:
    """
    يبني الدفتر الأول من سجلّ الرسائل الحقيقي للمدرسة.

    بدونه كانت المدرسة العاملة منذ أشهر تبدأ بدفترٍ فارغ فتُعامَل أرقام
    أولياء أمورها كأنها جديدة كلها في اليوم الأول بعد التحديث. لا يمنع
    ذلك شيئاً (سقف الجديد = السقف القديم نفسه) لكنه يؤخّر الفائدة يومين.

    يُقرأ بـ sqlite3 مباشرةً لا عبر `database` — لا استيراد ثقيل ولا
    دورة، وقراءة فقط، وأي عطب يسقط إلى دفتر فارغ بلا ضجيج.
    """
    out = {}
    try:
        import sqlite3
        from constants import DB_PATH
        if not os.path.exists(DB_PATH):
            return out
        con = sqlite3.connect(DB_PATH, timeout=3)
        try:
            rows = con.execute(
                "SELECT DISTINCT phone, MAX(date) FROM messages_log "
                "WHERE status='Success' AND phone<>'' GROUP BY phone").fetchall()
        finally:
            con.close()
        for ph, d in rows:
            if ph:
                out[_fp(ph)] = str(d or _today())[:10]
    except Exception:
        pass
    return out


def _load_contacts() -> dict:
    global _contacts
    if _contacts is not None:
        return _contacts
    data = None
    try:
        if os.path.exists(CONTACTS_FILE):
            with open(CONTACTS_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("seen"), dict):
                data = d["seen"]
    except Exception:
        data = None
    if data is None:                       # أول تشغيل بعد التحديث
        data = _seed_from_history()
        _contacts = data
        # لا يُكتب دفترٌ فارغ: قد تكون القاعدة كانت مقفلة لحظة القراءة
        # (نسخة احتياطية تعمل مثلاً) فنُثبّت فراغاً كاذباً إلى الأبد.
        # تركُه بلا ملف يعيد المحاولة عند التشغيل التالي، ولا ضرر في
        # الأثناء: سقف الأرقام الجديدة هو السقف القديم نفسه.
        if data:
            _save_contacts()
        return _contacts
    _contacts = data
    return _contacts


def _save_contacts():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = CONTACTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"seen": _contacts or {}}, f, indent=0)
        os.replace(tmp, CONTACTS_FILE)
    except Exception as e:
        print(f"[WA-LIMITS] تعذّر حفظ دفتر الأرقام: {e}")


def _prune_contacts():
    """يحذف الأرقام التي مضى على آخر مراسلة لها أكثر من المدة."""
    if not _contacts:
        return False
    cut = (datetime.date.today()
           - datetime.timedelta(days=_CONTACT_TTL_DAYS)).isoformat()
    dead = [k for k, v in _contacts.items() if str(v or "") < cut]
    for k in dead:
        _contacts.pop(k, None)
    return bool(dead)


def is_known(phone) -> bool:
    """هل سبق أن وصلت رسالةٌ **ناجحة** إلى هذا الرقم؟"""
    try:
        with _contacts_lock:
            return _fp(phone) in _load_contacts()
    except Exception:
        return False


def mark_known(phone):
    """
    يُسجّل الرقم معروفاً — **بعد نجاح الإرسال وحده**.

    التسجيل عند المحاولة كان يعني أن دفعةً فاشلة تُعلّم أربعمئة رقم
    «معروفة» بلا أن يصل منها شيء، فتسقط الحماية كلها في محاولة واحدة.
    """
    try:
        fp = _fp(phone)
        with _contacts_lock:
            c = _load_contacts()
            today = _today()
            if c.get(fp) == today:
                return                      # لا كتابة بلا تغيير
            c[fp] = today
            _prune_contacts()
            _save_contacts()
    except Exception as e:
        print(f"[WA-LIMITS] تعذّر تسجيل الرقم: {e}")


def _today() -> str:
    return datetime.date.today().isoformat()


def _load() -> dict:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def _save(d: dict):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"[WA-LIMITS] تعذّر الحفظ: {e}")


def _entry(state: dict, port) -> dict:
    key = str(port)
    e = state.get(key)
    if not isinstance(e, dict):
        e = {"first_seen": _today(), "date": _today(), "sent": 0, "total": 0}
        state[key] = e
    if e.get("date") != _today():          # يوم جديد ⇒ تصفير العدّاد
        e["date"] = _today()
        e["sent"] = 0
        e["sent_staff"] = 0
        e["new_fps"] = []
        e["by_source"] = {}
        e["refunded"] = 0
    e.setdefault("first_seen", _today())
    e.setdefault("total", 0)
    # ‏`sent` تبقى دفتر أولياء الأمور باسمها القديم — الملفات القائمة على
    # أجهزة المدارس تحمله، وتغيير الاسم يُصفّر عدّاد يومهم عند التحديث
    e.setdefault("sent", 0)
    e.setdefault("sent_staff", 0)
    # بصمات الأرقام الجديدة اليوم — قائمةٌ لا عدد، فرسالتان لنفس الرقم
    # الجديد (غياب ثم تأخر) شخصٌ واحد لا رقمان
    if not isinstance(e.get("new_fps"), list):
        e["new_fps"] = []
    if not isinstance(e.get("by_source"), dict):
        e["by_source"] = {}
    e.setdefault("refunded", 0)
    return e


def _limits(age: int) -> tuple:
    """(سقف الأرقام الجديدة, سقف الطاقم, سقف الأرقام المعروفة)."""
    lim = _MAX_DAILY
    for days, l in _WARMUP:
        if age < days:
            lim = l
            break
    slim = _MAX_STAFF_DAILY
    for days, l in _STAFF_WARMUP:
        if age < days:
            slim = l
            break
    # سقف المعروف لا ينزل تحت سقف الجديد أبداً — وإلا صار النموذج أضيق
    # من سابقه على رقمٍ في الإحماء، وهو ما تعهّدنا بألا يحدث
    return lim, slim, max(_MAX_KNOWN_DAILY, lim)


def _age_days(e: dict) -> int:
    try:
        d0 = datetime.date.fromisoformat(e["first_seen"])
        return (datetime.date.today() - d0).days
    except Exception:
        return 0


def daily_limit(port=3000) -> int:
    """السقف اليومي الحالي لهذا الرقم حسب عمره."""
    with _LOCK:
        st = _load()
        e = _entry(st, port)
        age = _age_days(e)
    for days, lim in _WARMUP:
        if age < days:
            return lim
    return _MAX_DAILY


def status(port=3000) -> dict:
    """حالة الرقم: الأرقام الجديدة (القيد الحقيقي)، والمعروفة، والطاقم."""
    with _LOCK:
        st = _load()
        e = _entry(st, port)
        age = _age_days(e)
        sent = int(e.get("sent", 0))
        sent_staff = int(e.get("sent_staff", 0))
        new_n = len(e.get("new_fps") or [])
        by_src = dict(e.get("by_source") or {})
        total = int(e.get("total", 0))
        refunded = int(e.get("refunded", 0))
    lim, slim, klim = _limits(age)
    try:
        with _contacts_lock:
            known_total = len(_load_contacts())
    except Exception:
        known_total = 0
    return {"port": str(port),
            # ‏sent_today مجموع رسائل أولياء الأمور اليوم (جديد + معروف)
            "sent_today": sent, "limit": klim, "remaining": max(0, klim - sent),
            # القيد الحقيقي: كم رقماً **جديداً** رُوسل اليوم
            "new_today": new_n, "new_limit": lim,
            "new_remaining": max(0, lim - new_n),
            "known_contacts": known_total,
            "staff_today": sent_staff, "staff_limit": slim,
            "staff_remaining": max(0, slim - sent_staff),
            "age_days": age, "warming_up": age < _WARMUP[-1][0],
            "total": total, "by_source": by_src, "refunded": refunded,
            "max_daily": _MAX_DAILY, "max_staff_daily": _MAX_STAFF_DAILY,
            "max_known_daily": _MAX_KNOWN_DAILY}


def try_consume(port=3000, source=None, phone=None, audience=None):
    """
    يحجز رسالة واحدة من الدفتر الذي يخصّ مستقبِلها.

    يُرجع `_Grant` وهو `(مسموح, سبب)` والدفترُ في `.audience`.
    لا ينام إطلاقاً — النوم داخل دالة الإرسال يجمّد خيط الخادم،
    والاستدعاء يأتي من سياق async أحياناً.

    الحجز **قبل** الإرسال مقصود: لو حُسب بعده لسبقت الرسالةُ العدّادَ
    وتجاوزنا السقف. لكن ما لا يخرج من الجهاز يُردّ بـ`refund` — انظرها.
    """
    src = source or detect_source()
    aud = audience or audience_for(phone)
    fp = _fp(phone) if phone else ""
    known = bool(fp) and is_known(phone)
    with _LOCK:
        st = _load()
        e = _entry(st, port)
        age = _age_days(e)
        lim, slim, klim = _limits(age)

        if aud == STAFF:
            sent = int(e.get("sent_staff", 0))
            if sent >= slim:
                return _Grant(
                    False, f"بلغت الحد اليومي {slim} رسالة لطاقم المدرسة "
                           f"من هذا الرقم. أكمل غداً.", aud)
            e["sent_staff"] = sent + 1
            ledger = STAFF
        else:
            sent = int(e.get("sent", 0))
            if sent >= klim:
                return _Grant(
                    False, f"بلغت الحد اليومي {klim} رسالة لأولياء الأمور "
                           f"من هذا الرقم. أكمل غداً.", aud)
            fps = e["new_fps"]
            # رقمٌ رُوسل اليوم بالفعل ليس «جديداً» مرةً أخرى — رسالة الغياب
            # ورسالة التأخر لولي الأمر نفسه شخصٌ واحد لا رقمان
            if known or not fp or fp in fps:
                ledger = KNOWN
            else:
                if len(fps) >= lim:
                    extra = (" (الرقم في فترة الإحماء — السقف يرتفع تدريجياً)"
                             if age < _WARMUP[-1][0] else "")
                    return _Grant(
                        False,
                        f"بلغت الحد اليومي {lim} رقماً جديداً من هذا الرقم"
                        f"{extra}. الرسائل للأرقام التي سبق التواصل معها "
                        f"لا تزال تعمل — أكمل الجديدة غداً.", aud)
                fps.append(fp)
                ledger = NEW
            e["sent"] = sent + 1
        e["total"] = int(e.get("total", 0)) + 1
        bs = e["by_source"]
        bs[src] = int(bs.get(src, 0)) + 1
        _save(st)
    return _Grant(True, "", ledger)


def refund(port=3000, source=None, audience=None, phone=None):
    """
    يُعيد خانةً حُجزت لرسالة **لم تخرج من الجهاز قطعاً**.

    سببُ وجودها: الحجز يسبق الإرسال، وكان الفشل يبتلع الخانة إلى الأبد.
    فمدرسةٌ واتسابها غير متصل تستهلك سقف اليوم كاملاً على محاولات فاشلة
    لم يصل منها حرف — ثم تُمنع الرسائل الحقيقية بعد عودة الاتصال.

    تُستدعى **فقط** حين يجزم الخادم بعدم الإرسال (٤٠٠/٤٠٤/٥٠٠/٥٠٣ أو
    تعذّر الاتصال بخادم Node). لا تُستدعى عند انتهاء المهلة: الطلب قد
    يكون في الطريق وقد وصل، والتقدير الزائد أهون من تجميد الرقم.

    يُمرَّر `audience` الذي أرجعه `try_consume` — لا يُعاد استنتاجه، فقد
    يتغيّر دليل الطاقم بين الحجز والردّ فتُخصم الخانة من الدفتر الخطأ.
    """
    src = source or detect_source()
    aud = audience or audience_for(phone)
    with _LOCK:
        st = _load()
        e = _entry(st, port)
        key = "sent_staff" if aud == STAFF else "sent"
        e[key] = max(0, int(e.get(key, 0)) - 1)
        # رقمٌ حُجز كـ«جديد» ثم لم تخرج رسالته لم يُراسَل أصلاً — تُعاد
        # بصمته من قائمة اليوم وإلا احترق نصيبٌ من الأرقام الجديدة بلا رسالة
        if aud == NEW and phone:
            try:
                e["new_fps"].remove(_fp(phone))
            except (ValueError, KeyError, TypeError):
                pass
        e["total"] = max(0, int(e.get("total", 0)) - 1)
        e["refunded"] = int(e.get("refunded", 0)) + 1
        bs = e["by_source"]
        if src in bs:
            bs[src] = int(bs.get(src, 0)) - 1
            if bs[src] <= 0:
                bs.pop(src, None)
        _save(st)


def next_delay(port=3000) -> float:
    """
    الثواني المقترحة قبل الرسالة التالية — تتصاعد مع طول الدفعة.

    الدفعة الطويلة المتسارعة هي ما يلفت كاشف الإزعاج، لا الرسالة
    المفردة. يستدعيها المُرسِل بين رسالتين.
    """
    s = status(port)
    # الدفتران معاً: التباعد يخصّ **الدفقة الخارجة من الرقم**، ولا يعنيه
    # مَن يستقبلها. حساب دفتر الأهالي وحده كان يُسرّع الإرسال بعد يومٍ
    # ثقيل على الطاقم وهو أخطر ما يكون.
    n = s["sent_today"] + s["staff_today"]
    if n and n % _PAUSE_EVERY == 0:
        return random.uniform(*_PAUSE_DELAY)
    if n >= _SLOW_AFTER:
        return random.uniform(*_SLOW_DELAY)
    return random.uniform(*_BASE_DELAY)


def reset(port=None):
    """تصفير يدوي — للاختبار أو بعد رفع الحظر."""
    with _LOCK:
        st = _load()
        if port is None:
            st = {}
        else:
            st.pop(str(port), None)
        _save(st)
