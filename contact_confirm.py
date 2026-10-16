# -*- coding: utf-8 -*-
"""
contact_confirm.py — رسالة «تأكيد رقم ولي الأمر» لكل أولياء أمور المدرسة.

لماذا: أقوى حماية لرقم المدرسة من تجميد واتساب ليست في الكود، بل أن يحفظ
أولياء الأمور الرقم في جهاتهم (انظر wa_limits). كانت تُطلب يدوياً عبر
مجموعات المدرسة؛ هنا يرسلها النظام: رسالة لكل رقم تطلب الرد وحفظ الرقم.

ما يحكم الحملة:
  • رسالة واحدة لكل رقم — وليّ أمر أكثر من طالب تصله رسالة بأسمائهم.
  • تمرّ بـ send_whatsapp_message فتخضع لسقوف wa_limits كلها.
  • رسائل الغياب أولى: الأرقام الجديدة لا تُراسَل قبل NEW_FROM_HOUR، ويُترك
    من رصيدها اليومي جزءٌ (RESERVE_SHARE) لا تمسّه الحملة. السقف مشترك،
    ورسالة تأكيدٍ تُسقط رسالة غياب خسارةٌ لا تُعوَّض.
  • تعمل في الخلفية على الخادم، نهاراً فقط، وتكمل في اليوم التالي وحدها.
  • تتخطّى رقماً عليه طلب معلّق في بوت الواتساب (استئذان أو عذر) حتى يُغلق:
    ردّه «نعم» أو «تمام» كان سيُحتسب موافقةً على خروج الطالب.
  • لا تراسل أولياء أمور المستثنَين والمنقولين، كبقية رسائل النظام.

ما لا تفعله: لا تقرأ ردود أولياء الأمور. الردود تصل جوال المدرسة، وقراءتها
آلياً تحتاج تعديل server.js الذي لا يصله التحديث.

الحالة في `data/contact_confirm.json`، ومفاتيحها **بصمة** الرقم لا الرقم.
"""
import datetime
import json
import os
import threading

from constants import DATA_DIR

STATE_FILE = os.path.join(DATA_DIR, "contact_confirm.json")
SOURCE = "contact_confirm"

SEND_HOURS = (7, 20)        # لا رسائل لأولياء الأمور ليلاً
NEW_FROM_HOUR = 10          # الأرقام الجديدة بعد مرور رسائل الغياب الصباحية
RESUME_AT = (7, 30)         # موعد المتابعة صباح اليوم التالي
RESERVE_SHARE = 0.3         # من رصيد الأرقام الجديدة اليومي يبقى لرسائل الغياب
RESERVE_MIN = 10
PENDING_DEFER_MIN = 120     # رقمٌ عليه طلب معلّق يُعاد فحصه بعد ساعتين
RETRY_DEFER_MIN = 30        # فشل عابر في الخادم يُعاد بعد نصف ساعة
MAX_TRIES = 3
SERVER_WAIT_S = 120
MAX_WAIT_S = 300            # أطول نوم متصل — ليُلاحَظ الإيقاف وتغيّر الحال
RESUME_DELAY_S = 90         # بعد إقلاع الخادم تُستأنف الحملة الجارية

_lock = threading.RLock()
_thread = None
_wake = threading.Event()


# ── الوقت ────────────────────────────────────────────────────────────
def _now():
    """توقيت الرياض — ساعات الإرسال تُقاس به لا بساعة الجهاز."""
    from constants import TZ_OFFSET
    return (datetime.datetime.now(datetime.timezone.utc)
            .astimezone(datetime.timezone(TZ_OFFSET)).replace(tzinfo=None))


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


def _parse(s):
    try:
        return datetime.datetime.fromisoformat(str(s)) if s else None
    except ValueError:
        return None


def _next_morning(now):
    d = now.date() + datetime.timedelta(days=1)
    return datetime.datetime(d.year, d.month, d.day, *RESUME_AT)


def _next_window_start(now):
    start = now.replace(hour=SEND_HOURS[0], minute=0, second=0, microsecond=0)
    return start if now < start else _next_morning(now)


# ── الحالة ───────────────────────────────────────────────────────────
def _blank():
    return {"status": "idle", "items": {}, "defer": {}, "tries": {}}


def _load_state():
    with _lock:
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            return _blank()
        except (OSError, ValueError):
            # ملفٌ تالف لا يُعامَل كحملة جديدة: استئنافها يعيد الإرسال لمن
            # وصلتهم الرسالة. تبقى موقوفة حتى يقرّر المدير.
            st = _blank()
            st["status"] = "stopped"
            st["reason"] = ("تعذّرت قراءة سجلّ الحملة — أُوقفت حتى لا تتكرّر "
                            "الرسائل. ابدأ من جديد إن أردت.")
            return st
        if not isinstance(d, dict):
            return _blank()
        for k in ("items", "defer", "tries"):
            if not isinstance(d.get(k), dict):
                d[k] = {}
        d.setdefault("status", "idle")
        return d


def _save_state(st):
    with _lock:
        st["updated_at"] = _iso(_now())
        os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)


def _wait(st, until, reason, now):
    st["wait_until"] = _iso(until)
    st["reason"] = reason
    return max(1.0, min(float(MAX_WAIT_S), (until - now).total_seconds()))


# ── المستقبِلون والرسالة ─────────────────────────────────────────────
def _excluded_ids():
    """المستثنَون (ظروف خاصة) والمنقولون — لا تصلهم رسائل النظام."""
    out = set()
    try:
        from database import get_db
        con = get_db()
        try:
            for tbl in ("exempted_students", "transferred_students"):
                try:
                    out |= {str(r[0]) for r in con.execute(
                        "SELECT student_id FROM " + tbl).fetchall()}
                except Exception:
                    pass
        finally:
            con.close()
    except Exception:
        pass
    return out


def build_recipients():
    """
    رقمٌ واحد لكل وليّ أمر مهما تعدّد أبناؤه.
    يُرجع (القائمة، وعدد من لم يُضمَّن وسببه).
    """
    import wa_limits
    from database import load_students
    excluded = _excluded_ids()
    by_phone = {}
    skipped = {"no_phone": 0, "invalid": 0, "excluded": 0}
    for c in (load_students() or {}).get("list") or []:
        for s in c.get("students") or []:
            sid = str(s.get("id") or "")
            if sid in excluded:
                skipped["excluded"] += 1
                continue
            raw = str(s.get("phone") or "").strip()
            if not raw:
                skipped["no_phone"] += 1
                continue
            ph = wa_limits._norm(raw)
            # ما يقبله send_whatsapp_message — غيره يُرفض هناك بلا رسالة
            if not (len(ph) == 12 and ph.startswith("966")):
                skipped["invalid"] += 1
                continue
            rec = by_phone.get(ph)
            if rec is None:
                rec = by_phone[ph] = {"phone": ph, "fp": wa_limits._fp(ph),
                                      "students": []}
            rec["students"].append({
                "id": sid, "name": str(s.get("name") or "").strip(),
                "class_id": str(c.get("id") or ""),
                "class_name": str(c.get("name") or "")})
    return list(by_phone.values()), skipped


def render_message(rec) -> str:
    from config_manager import load_config, get_terms
    cfg = load_config() or {}
    t = get_terms() or {}
    girls = str(cfg.get("school_gender") or "") == "girls"
    names = [s["name"] for s in rec.get("students") or [] if s.get("name")] or ["—"]
    many = len(names) > 1
    guardian = t.get("guardian") or ("ولية أمر الطالبة" if girls else "ولي أمر الطالب")
    if many:
        guardian = guardian.replace(t.get("student") or "الطالب",
                                    t.get("students") or "الطلاب")
    child = ("بناتكم" if girls else "أبنائكم") if many else (t.get("son") or "ابنكم")
    school = str(cfg.get("school_name") or "").strip()
    if not school or school == "اسم المدرسة":
        school = "المدرسة"
    return (
        "السلام عليكم ورحمة الله وبركاته\n"
        + guardian + ": " + "، ".join(names) + "\n\n"
        + "هذا هو رقم " + school + " الرسمي للتواصل معكم بخصوص " + child
        + ": الغياب والتأخر والاستئذان والتعاميم.\n\n"
        + "نرجو الرد على هذه الرسالة بكلمة «تم» لتأكيد أن هذا الرقم هو رقم "
        + guardian + ".\n\n"
        + "ملاحظة مهمة: احفظوا هذا الرقم في جهات الاتصال لديكم ليصلكم كل ما يخص "
        + child + " دون انقطاع."
    )


def reserve_for(new_limit) -> int:
    """ما يبقى من رصيد الأرقام الجديدة اليومي لرسائل الغياب."""
    return max(RESERVE_MIN, int(round((new_limit or 0) * RESERVE_SHARE)))


# ── خادم الواتساب ────────────────────────────────────────────────────
def _port():
    try:
        from whatsapp_service import get_wa_servers
        return int((get_wa_servers() or [{}])[0].get("port", 3000))
    except Exception:
        return 3000


def _get_json(port, path):
    import requests
    r = requests.get("http://127.0.0.1:%d%s" % (port, path), timeout=3)
    return r.json() if r.status_code == 200 else None


def _server_ready(port) -> bool:
    try:
        d = _get_json(port, "/status") or {}
        return bool(d.get("is_ready", d.get("ready")))
    except Exception:
        return False


def _pending_tails(port):
    """
    آخر ٩ أرقام لكل وليّ أمر عليه طلب معلّق في بوت الواتساب، أو None إن
    تعذّرت القراءة. المطابقة بالذيل كما يطابق الخادم نفسه (findPending).
    """
    try:
        d = _get_json(port, "/pending-excuses")
        if d is None:
            return None
        return {str(k)[-9:] for k in (d.get("pending") or {})}
    except Exception:
        return None


def _send(phone, text):
    from whatsapp_service import send_whatsapp_message
    # بلا student_data عمداً: معها يُسجَّل الرقم «منتظِراً» في البوت، فيُقرأ
    # ردّ «تم» عذراً أو ردّ «نعم» موافقةً على استئذان
    return send_whatsapp_message(phone, text)


def _log(rec, ok, detail):
    """سجلّ الرسائل — عطبٌ فيه لا يوقف الحملة."""
    try:
        from alerts_service import log_message_status
        from constants import now_riyadh_date
        studs = rec.get("students") or [{}]
        names = "، ".join(s["name"] for s in studs if s.get("name"))
        s0 = studs[0]
        log_message_status(now_riyadh_date(), s0.get("id", ""), names,
                           s0.get("class_id", ""), s0.get("class_name", ""),
                           rec["phone"], "Success" if ok else "Failed",
                           SOURCE, SOURCE, detail=str(detail or "")[:300])
    except Exception as e:
        print("[CONTACT-CONFIRM] تعذّر تسجيل الرسالة: %s" % e)


def _classify(msg):
    m = str(msg or "")
    if "غير مسجّل" in m or "غير مسجل" in m:
        return "failed", "الرقم ليس على واتساب"
    if "بلغت الحد اليومي" in m:
        return "cap", m
    if "تنسيق رقم الجوال" in m or "غير صالح" in m:
        return "failed", "رقم الجوال غير صالح"
    if "مهلة" in m:
        # لا إعادة: قد تكون وصلت، ورسالتان لوليّ الأمر نفسه إزعاج
        return "unsure", "انتهت المهلة — قد تكون الرسالة وصلت"
    return "retry", m


# ── خطوة الإرسال ─────────────────────────────────────────────────────
def _step(st, now=None):
    """
    خطوة واحدة: ترسل رسالة واحدة أو تقرّر الانتظار.
    تُعدّل `st` ولا تحفظه، وتُرجع الثواني قبل الخطوة التالية.
    """
    import wa_limits
    now = now or _now()
    until = _parse(st.get("wait_until"))
    if until and now < until:
        return max(1.0, min(float(MAX_WAIT_S), (until - now).total_seconds()))
    st["wait_until"] = ""

    if not (SEND_HOURS[0] <= now.hour < SEND_HOURS[1]):
        return _wait(st, _next_window_start(now),
                     "خارج ساعات الإرسال — تُكمل الحملة صباحاً", now)

    recips, _ = build_recipients()
    items, defer, tries = st["items"], st["defer"], st["tries"]
    todo = [r for r in recips if r["fp"] not in items]
    if not todo:
        st["status"] = "done"
        st["reason"] = "اكتملت الحملة"
        st["finished_at"] = _iso(now)
        return 0

    ready = []
    for r in todo:
        d = _parse(defer.get(r["fp"]))
        if not (d and now < d):
            ready.append(r)
    if not ready:
        earliest = min(_parse(defer[r["fp"]]) for r in todo)
        return _wait(st, earliest, "بانتظار أرقام عليها طلبات معلّقة في بوت "
                                   "الواتساب أو أعطال عابرة", now)

    port = _port()
    if not _server_ready(port):
        st["reason"] = "خادم الواتساب غير متصل — تُكمل الحملة حين يعود"
        return SERVER_WAIT_S

    # المعروفون أولاً: لا يستهلكون من رصيد الأرقام الجديدة شيئاً
    known = {r["fp"]: wa_limits.is_known(r["phone"]) for r in ready}
    ready.sort(key=lambda r: 0 if known[r["fp"]] else 1)
    r = ready[0]
    fp = r["fp"]

    if not known[fp]:
        if now.hour < NEW_FROM_HOUR:
            at = now.replace(hour=NEW_FROM_HOUR, minute=0, second=0, microsecond=0)
            return _wait(st, at, "الأرقام الجديدة تُراسَل بعد الساعة %d صباحاً "
                                 "حتى تمرّ رسائل الغياب أولاً" % NEW_FROM_HOUR, now)
        s = wa_limits.status(port)
        if s.get("new_remaining", 0) <= reserve_for(s.get("new_limit", 0)):
            return _wait(st, _next_morning(now),
                         "بلغت الحملة حصّتها اليوم من الأرقام الجديدة، وبقي "
                         "الرصيد لرسائل الغياب — تُكمل غداً", now)

    pend = _pending_tails(port)
    if pend is None:
        st["reason"] = "تعذّر فحص الطلبات المعلّقة في بوت الواتساب — يُعاد بعد قليل"
        return SERVER_WAIT_S
    if r["phone"][-9:] in pend:
        defer[fp] = _iso(now + datetime.timedelta(minutes=PENDING_DEFER_MIN))
        return 1

    ok, msg = _send(r["phone"], render_message(r))
    if ok:
        items[fp] = {"st": "sent", "at": _iso(now)}
        defer.pop(fp, None)
        tries.pop(fp, None)
        st["reason"] = ""
        _log(r, True, msg)
        return wa_limits.next_delay(port)

    kind, why = _classify(msg)
    if kind == "cap":
        return _wait(st, _next_morning(now), why, now)
    if kind == "retry":
        n = int(tries.get(fp, 0)) + 1
        tries[fp] = n
        if n < MAX_TRIES:
            defer[fp] = _iso(now + datetime.timedelta(minutes=RETRY_DEFER_MIN))
            st["reason"] = why
            return SERVER_WAIT_S
        kind, why = "failed", "تعذّر بعد %d محاولات: %s" % (n, why)
    items[fp] = {"st": kind, "at": _iso(now), "why": why}
    defer.pop(fp, None)
    tries.pop(fp, None)
    _log(r, False, why)
    return wa_limits.next_delay(port)


def _commit(st) -> bool:
    """
    يحفظ نتيجة الخطوة. إن أُوقفت الحملة أثناءها حُفظ التقدّم وبقيت حالة
    المستخدم — وإلا محا حفظُ الخطوة إيقافَه فاستمرّت الرسائل.
    """
    with _lock:
        cur = _load_state()
        if cur.get("status") != "running":
            for k in ("items", "defer", "tries"):
                cur[k] = st.get(k) or {}
            _save_state(cur)
            return False
        _save_state(st)
        return st.get("status") == "running"


def _worker():
    global _thread
    try:
        while True:
            st = _load_state()
            if st.get("status") != "running":
                return
            try:
                delay = _step(st)
            except Exception as e:
                print("[CONTACT-CONFIRM] خطأ في خطوة الإرسال: %s" % e)
                st["reason"] = "خطأ داخلي — يُعاد بعد قليل: %s" % e
                delay = SERVER_WAIT_S
            if not _commit(st):
                return
            if delay > 0:
                _wake.wait(delay)
                _wake.clear()
    finally:
        with _lock:
            if _thread is threading.current_thread():
                _thread = None


def _alive():
    t = _thread
    return bool(t and t.is_alive())


def _ensure_thread():
    global _thread
    with _lock:
        if _alive():
            return
        _wake.clear()
        _thread = threading.Thread(target=_worker, name="contact-confirm",
                                   daemon=True)
        _thread.start()


# ── الواجهة ──────────────────────────────────────────────────────────
def start(by="") -> dict:
    with _lock:
        st = _load_state()
        if st.get("status") != "running":
            if not st.get("started_at"):
                st["started_at"] = _iso(_now())
            st["started_by"] = by or st.get("started_by", "")
            st["status"] = "running"
            st["wait_until"] = ""
            st["reason"] = ""
            _save_state(st)
    _ensure_thread()
    _wake.set()
    return summary()


def stop() -> dict:
    with _lock:
        st = _load_state()
        if st.get("status") == "running":
            st["status"] = "stopped"
            st["wait_until"] = ""
            st["reason"] = "أُوقفت يدوياً"
            _save_state(st)
    _wake.set()
    return summary()


def reset():
    """يمحو التقدّم — الإرسال التالي يبدأ من أول رقم، حتى لمن وصلته الرسالة."""
    with _lock:
        if _load_state().get("status") == "running" or _alive():
            return False, "أوقف الحملة أولاً"
        try:
            os.remove(STATE_FILE)
        except FileNotFoundError:
            pass
    return True, ""


def resume_if_active():
    """بعد إعادة تشغيل البرنامج تُستأنف الحملة الجارية من حيث وقفت."""
    try:
        if _load_state().get("status") == "running":
            _ensure_thread()
    except Exception as e:
        print("[CONTACT-CONFIRM] تعذّر الاستئناف: %s" % e)


def schedule_resume(delay=RESUME_DELAY_S):
    t = threading.Timer(delay, resume_if_active)
    t.daemon = True
    t.start()


def summary() -> dict:
    st = _load_state()
    if st.get("status") == "running" and not _alive():
        _ensure_thread()                 # بعد إعادة تشغيلٍ لم يحن فيها الاستئناف
    now = _now()
    try:
        recips, skipped = build_recipients()
    except Exception as e:
        print("[CONTACT-CONFIRM] تعذّر قراءة كشف الطلاب: %s" % e)
        recips, skipped = [], {"no_phone": 0, "invalid": 0, "excluded": 0}

    items, defer = st["items"], st["defer"]
    counts = {"sent": 0, "failed": 0, "unsure": 0}
    failed = []
    remaining = deferred = 0
    for r in recips:
        it = items.get(r["fp"])
        if it:
            k = it.get("st")
            if k in counts:
                counts[k] += 1
            if k in ("failed", "unsure") and len(failed) < 100:
                failed.append({
                    "names": "، ".join(s["name"] for s in r["students"] if s.get("name")),
                    "class": r["students"][0].get("class_name", ""),
                    "why": it.get("why", "")})
            continue
        remaining += 1
        d = _parse(defer.get(r["fp"]))
        if d and now < d:
            deferred += 1

    port = _port()
    cap = {}
    try:
        import wa_limits
        s = wa_limits.status(port)
        cap = {"new_remaining": s.get("new_remaining"),
               "new_limit": s.get("new_limit"),
               "reserve": reserve_for(s.get("new_limit", 0)),
               "warming_up": bool(s.get("warming_up"))}
    except Exception:
        pass

    sample = recips[0] if recips else {"phone": "", "students": [{"name": "اسم الطالب"}]}
    try:
        preview = render_message(sample)
    except Exception as e:
        preview = ""
        print("[CONTACT-CONFIRM] تعذّر تجهيز نص الرسالة: %s" % e)

    wait_until = st.get("wait_until") or ""
    w = _parse(wait_until)
    if not (w and now < w):
        wait_until = ""
    return {
        "status": st.get("status", "idle"), "alive": _alive(),
        "wait_until": wait_until, "reason": st.get("reason", "") or "",
        "started_at": st.get("started_at", "") or "",
        "started_by": st.get("started_by", "") or "",
        "finished_at": st.get("finished_at", "") or "",
        "total": len(recips),
        "students": sum(len(r["students"]) for r in recips),
        "remaining": remaining, "deferred": deferred,
        "sent": counts["sent"], "failed": counts["failed"],
        "unsure": counts["unsure"], "failed_list": failed,
        "skipped": skipped, "capacity": cap,
        "server_ready": _server_ready(port),
        "hours": {"from": SEND_HOURS[0], "to": SEND_HOURS[1],
                  "new_from": NEW_FROM_HOUR},
        "preview": preview,
    }
