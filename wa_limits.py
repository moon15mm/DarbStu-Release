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
_MAX_DAILY = 150          # بعد أسبوعين

# تباعد الرسائل — يتصاعد كلما طالت الدفعة داخل اليوم نفسه
_BASE_DELAY = (8, 16)     # ثوانٍ
_SLOW_AFTER = 25          # بعد هذا العدد يبطؤ
_SLOW_DELAY = (20, 35)
_PAUSE_EVERY = 40         # كل هذا العدد وقفة أطول
_PAUSE_DELAY = (90, 150)


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
    e.setdefault("first_seen", _today())
    e.setdefault("total", 0)
    return e


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
    """حالة الرقم: المرسَل اليوم، السقف، المتبقي، عمر الرقم."""
    with _LOCK:
        st = _load()
        e = _entry(st, port)
        age = _age_days(e)
        sent = int(e.get("sent", 0))
    lim = _MAX_DAILY
    for days, l in _WARMUP:
        if age < days:
            lim = l
            break
    return {"port": str(port), "sent_today": sent, "limit": lim,
            "remaining": max(0, lim - sent), "age_days": age,
            "warming_up": age < _WARMUP[-1][0], "total": int(e.get("total", 0))}


def try_consume(port=3000):
    """
    يحجز رسالة واحدة من رصيد اليوم.

    يُرجع (مسموح, سبب). لا ينام إطلاقاً — النوم داخل دالة الإرسال
    يجمّد خيط الخادم، والاستدعاء يأتي من سياق async أحياناً.
    """
    with _LOCK:
        st = _load()
        e = _entry(st, port)
        age = _age_days(e)
        lim = _MAX_DAILY
        for days, l in _WARMUP:
            if age < days:
                lim = l
                break
        sent = int(e.get("sent", 0))
        if sent >= lim:
            extra = (" (الرقم في فترة الإحماء — السقف يرتفع تدريجياً)"
                     if age < _WARMUP[-1][0] else "")
            return False, (f"بلغت الحد اليومي {lim} رسالة لهذا الرقم{extra}. "
                           f"أكمل غداً أو استخدم رقماً آخر.")
        e["sent"] = sent + 1
        e["total"] = int(e.get("total", 0)) + 1
        _save(st)
    return True, ""


def next_delay(port=3000) -> float:
    """
    الثواني المقترحة قبل الرسالة التالية — تتصاعد مع طول الدفعة.

    الدفعة الطويلة المتسارعة هي ما يلفت كاشف الإزعاج، لا الرسالة
    المفردة. يستدعيها المُرسِل بين رسالتين.
    """
    s = status(port)
    n = s["sent_today"]
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
