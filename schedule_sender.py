# -*- coding: utf-8 -*-
"""
schedule_sender.py — الإرسال الآلي لروابط الحصص (نسخة الخادم).

يكافئ «بدء/إيقاف الإرسال الآلي» في تبويب جدولة الروابط المكتبي، لكنه
يعمل في عملية الخادم بلا Tkinter: لكل حصةٍ من جدول اليوم يُضبط
`threading.Timer` يرسل — عند وقت الحصة — رسالةَ واتساب للمعلم المكلّف
فيها روابط تسجيل غياب فصوله (مُوقّعة بـclass_link_token).

الحالة عامّة على مستوى الوحدة (مرسلٌ واحد للخادم)، محميّة بقفل.
"""
import datetime
import threading

_lock = threading.Lock()
_timers = []
_running = False
_started_day = None
_scheduled = []          # [{period, time}] المجدولة فعلاً (المتبقّية اليوم)
_log = []                # آخر رسائل السجل

DAY_NAMES = {0: "الأحد", 1: "الاثنين", 2: "الثلاثاء", 3: "الأربعاء", 4: "الخميس"}
DEFAULT_TIMES = ["07:00", "07:50", "08:40", "09:50", "10:40", "11:30", "12:20"]


def _now():
    tz = datetime.timezone(datetime.timedelta(hours=3))
    return datetime.datetime.now(datetime.timezone.utc).astimezone(tz)\
        .replace(tzinfo=None)


def _logmsg(m):
    _log.append("[%s] %s" % (_now().strftime("%H:%M:%S"), m))
    del _log[:-60]   # نُبقي آخر ٦٠ سطراً


def _base_url():
    from constants import public_base_url
    return public_base_url()   # يحلّ النطاق العام وقت التشغيل من كل المصادر


def status():
    return {"running": _running, "day": DAY_NAMES.get(_started_day),
            "scheduled": list(_scheduled), "log": list(_log)}


def start():
    """يبدأ الإرسال لجدول اليوم. يُرجع {ok, ...} أو {ok:False, error}."""
    global _running, _started_day, _scheduled
    with _lock:
        if _running:
            return {"ok": False, "error": "المرسل الآلي يعمل بالفعل"}

        now = _now()
        dow = (now.weekday() + 1) % 7        # الأحد=0 .. الخميس=4، الجمعة=5، السبت=6
        if dow > 4:
            return {"ok": False, "error": "اليوم عطلة نهاية أسبوع — لا إرسال"}

        from alerts_service import load_schedule
        from config_manager import load_config
        schedule = load_schedule(dow)
        if not schedule:
            return {"ok": False,
                    "error": "جدول اليوم (%s) فارغ — لا شيء لإرساله"
                             % DAY_NAMES.get(dow)}

        times = load_config().get("period_times", DEFAULT_TIMES)
        base = _base_url()
        _scheduled = []
        skipped_past = 0
        for period in range(1, 8):
            ts = times[period - 1] if period - 1 < len(times) else ""
            try:
                h, m = map(int, str(ts).split(":"))
            except Exception:
                continue
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            delay = (target - now).total_seconds()
            if delay < 0:
                skipped_past += 1
                continue
            t = threading.Timer(delay, _send_period, args=[period, schedule, base])
            t.daemon = True
            _timers.append(t)
            t.start()
            _scheduled.append({"period": period, "time": ts})

        if not _scheduled:
            return {"ok": False,
                    "error": "كل حصص اليوم فات وقتها (%d) — لن يُرسَل شيء"
                             % skipped_past}

        _running = True
        _started_day = dow
        _logmsg("بدأ الإرسال لجدول %s — جُدولت %d حصة%s"
                % (DAY_NAMES.get(dow), len(_scheduled),
                   (" (فات %d)" % skipped_past) if skipped_past else ""))
        return {"ok": True, "scheduled": _scheduled,
                "day": DAY_NAMES.get(dow)}


def stop():
    global _running
    with _lock:
        for t in _timers:
            try:
                t.cancel()
            except Exception:
                pass
        _timers.clear()
        _scheduled.clear()
        _running = False
        _logmsg("أُوقف الإرسال الآلي")
    return {"ok": True}


def _send_period(period, schedule, base):
    """يُرسل روابط حصةٍ واحدة لكل معلم مكلّف — يُستدعى من المؤقّت."""
    global _scheduled
    try:
        from database import load_students, load_teachers
        from whatsapp_service import send_whatsapp_message
        import security
        _logmsg("الحصة %d: حان وقتها، جارٍ الإرسال..." % period)
        by_id = load_students().get("by_id", {})
        teachers = {t.get("اسم المعلم", ""): t
                    for t in load_teachers().get("teachers", [])}

        to_notify = {}
        for (cid, p), tname in schedule.items():
            if p == period and tname:
                ci = by_id.get(cid)
                if ci:
                    to_notify.setdefault(tname, []).append(ci)

        if not to_notify:
            _logmsg("الحصة %d: لا معلمين مجدولين" % period)
        for tname, classes in to_notify.items():
            td = teachers.get(tname) or {}
            phone = (td.get("رقم الجوال") or "").strip()
            if not phone:
                _logmsg("الحصة %d: '%s' بلا رقم جوال — تُخطّى" % (period, tname))
                continue
            links = "\n".join(
                "- فصل: %s\n  الرابط: %s/c/%s?k=%s"
                % (c["name"], base, c["id"], security.class_link_token(str(c["id"])))
                for c in classes)
            msg = ("السلام عليكم أ. %s،\n"
                   "إليك روابط تسجيل الغياب للحصة %d:\n\n%s\n\n"
                   "مع تحيات إدارة المدرسة." % (tname, period, links))
            ok, m = send_whatsapp_message(phone, msg)
            _logmsg(("✅ أُرسل للحصة %d إلى '%s'" % (period, tname)) if ok
                    else ("❌ فشل لـ'%s': %s" % (tname, m)))
    except Exception as e:
        _logmsg("خطأ في إرسال الحصة %d: %s" % (period, e))
    finally:
        # أزِل هذه الحصة من المتبقّي؛ إن فرغ الكل فقد انتهى اليوم
        _scheduled[:] = [s for s in _scheduled if s.get("period") != period]
