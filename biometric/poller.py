# -*- coding: utf-8 -*-
"""
poller.py — يسحب البصمات، يطابقها بالطلاب، يشتقّ التأخر، يُشعر.

خيط واحد يعمل في الخلفية داخل البرنامج. في كل دورة:
  ١. يسأل كل جهاز مُفعّل عن البصمات بعد آخر ما خزّنّاه.
  ٢. يخزّن الخام (قيد UNIQUE يمتصّ التداخل والتكرار).
  ٣. يعالج غير المعالَج: يطابق رقم الجهاز بالطالب، يحسب التأخر،
     يسجّله عبر insert_tardiness، ويُشعر ولي الأمر إن طُلب.

كل شيء مغلّف بـtry: جهازٌ مفصول أو خطأ شبكةٍ لا يُسقط الخيط، بل يُسجَّل
ويُعاد المحاولة في الدورة التالية. والخيط لا يبدأ إلا إن فُعّلت الميزة.

المطابقة على مرحلتين: جدول الربط اليدوي أولاً (للأجهزة ذات الترقيم
التسلسلي)، ثم رقم الطالب مباشرةً (حين يُسجَّل في الجهاز برقمه الأكاديمي).
"""
import datetime
import threading
import time

_RIYADH = datetime.timedelta(hours=3)
_thread = None
_stop = threading.Event()
poller_lock = threading.Lock()
_last_status = {"running": False, "last_run": None, "last_error": "",
                "devices": []}


def _now_local():
    return datetime.datetime.utcnow() + _RIYADH


def _today_local():
    return _now_local().date().isoformat()


def _match_student(uid, enrollments, academic_map, student_map):
    """
    رقم جهاز ← بيانات طالب، أو None. الأولوية:
      ١. الربط اليدوي (تجاوز صريح).
      ٢. الرقم الأكاديمي المُهيكل (الطريق المعتاد — رقم الهوية ١٠ خانات
         لا يُكتب في جهاز ٩ خانات، فالجهاز يحمل الرقم الأكاديمي القصير).
      ٣. رقم الطالب المباشر (توافق خلفي مع بيانات قديمة/تجريبية قصيرة).
    """
    uid = str(uid)
    if uid in enrollments:
        e = enrollments[uid]
        return e["student_id"], e.get("student_name", ""), \
            e.get("class_name", "")
    if uid in academic_map:
        a = academic_map[uid]
        return a["student_id"], a.get("name", ""), a.get("class_name", "")
    if uid in student_map:
        s = student_map[uid]
        return uid, s.get("name", ""), s.get("class_name", "")
    return None


def _student_phone(student_id):
    """جوال ولي أمر الطالب من ملف الطلاب — لإشعار التأخر."""
    try:
        from database import load_students
        for c in load_students().get("list", []):
            for s in c.get("students", []):
                if str(s.get("id")) == str(student_id):
                    return (s.get("phone") or "").strip()
    except Exception:
        pass
    return ""


def process_pending(cfg=None):
    """
    يعالج البصمات غير المعالَجة دفعةً واحدة. مفصولة عن السحب كي تُستدعى
    مستقلّةً في الاختبار (نحقن بصمات ثم نعالج ونتحقّق).
    يُرجع إحصاءً: {tardy, present, unmatched, exempted}.
    """
    from config_manager import load_config
    from database import (get_unprocessed_punches, mark_punch_processed,
                          get_biometric_enrollments, get_student_map,
                          get_academic_map, is_student_exempted,
                          insert_tardiness)
    cfg = cfg or load_config()

    mode = cfg.get("biometric_mode", "tardiness")   # 'tardiness' | 'attendance'
    grace = int(cfg.get("biometric_grace_min", 0))
    start_str = cfg.get("school_start_time", "07:00")
    notify = bool(cfg.get("biometric_notify_parent", True))

    try:
        start_t = datetime.datetime.strptime(start_str[:5], "%H:%M")
    except Exception:
        start_t = datetime.datetime.strptime("07:00", "%H:%M")

    enrollments = get_biometric_enrollments()
    academic_map = get_academic_map()
    student_map = get_student_map()

    stat = {"tardy": 0, "present": 0, "unmatched": 0, "exempted": 0,
            "duplicate": 0}

    for p in get_unprocessed_punches():
        uid = p["device_uid"]
        matched = _match_student(uid, enrollments, academic_map, student_map)
        if not matched:
            mark_punch_processed(p["id"], "لا مطابقة", matched=0)
            stat["unmatched"] += 1
            continue

        sid, sname, cname = matched
        if is_student_exempted(sid):
            mark_punch_processed(p["id"], "مستثنى", student_id=sid, matched=1)
            stat["exempted"] += 1
            continue

        # وقت البصمة المحلّي — منه نحسب التأخر
        try:
            local = datetime.datetime.fromisoformat(
                (p.get("punch_local") or "").replace("Z", ""))
        except Exception:
            local = _now_local()

        reg_t = datetime.datetime.strptime(local.strftime("%H:%M"), "%H:%M")
        minutes_late = int((reg_t - start_t).total_seconds() / 60) - grace

        if mode == "tardiness" and minutes_late <= 0:
            # حضر في الوقت — لا تأخر. نعلّمه حاضراً ولا نُشعر.
            mark_punch_processed(p["id"], "حاضر", student_id=sid, matched=1)
            stat["present"] += 1
            continue

        minutes_late = max(minutes_late, 0)
        ok = insert_tardiness(
            p["date"] or _today_local(), "", cname, sid, sname,
            "بوابة البصمة", 0, minutes_late)
        if not ok:
            # UNIQUE(date, student_id): سُجّل تأخره سلفاً اليوم — تكرار طبيعي
            mark_punch_processed(p["id"], "مكرر", student_id=sid, matched=1)
            stat["duplicate"] += 1
            continue

        outcome = "تأخر %d د" % minutes_late
        mark_punch_processed(p["id"], outcome, student_id=sid, matched=1)
        stat["tardy"] += 1

        if notify:
            phone = _student_phone(sid)
            if phone:
                _notify_parent(phone, sname, local, minutes_late)

    return stat


def _notify_parent(phone, name, local_dt, minutes_late):
    """إشعار واتساب فوري لولي الأمر — بلا إسقاط المعالجة إن فشل الإرسال."""
    try:
        from whatsapp_service import send_whatsapp_message
        t = local_dt.strftime("%I:%M")
        msg = ("تنبيه حضور\n"
               "الطالب: %s\n"
               "سجّل دخوله الساعة %s متأخّراً %d دقيقة." %
               (name, t, minutes_late))
        send_whatsapp_message(phone, msg)
    except Exception:
        pass


def _pull_devices(cfg):
    """يسحب من كل جهاز مُفعّل ويخزّن الخام. يُرجع عدد الجديد."""
    from database import (insert_biometric_punch, get_last_punch_utc,
                          get_biometric_enrollments, get_student_map,
                          get_academic_map)
    from biometric import make_device

    devices = cfg.get("biometric_devices") or []
    enrollments = get_biometric_enrollments()
    academic_map = get_academic_map()
    student_map = get_student_map()
    new_total = 0
    dev_status = []

    for dcfg in devices:
        if not dcfg.get("enabled", True):
            continue
        did = str(dcfg.get("device_id") or dcfg.get("ip") or "dev")
        entry = {"device_id": did, "ok": False, "new": 0, "error": ""}
        try:
            dev = make_device(dcfg)
            after = get_last_punch_utc(did)
            punches = dev.read_punches(after_utc=after)
            for p in punches:
                uid = p["uid"]
                sid = ""
                if uid in enrollments:
                    sid = enrollments[uid]["student_id"]
                elif uid in academic_map:
                    sid = academic_map[uid]["student_id"]
                elif uid in student_map:
                    sid = uid
                matched = bool(sid)
                try:
                    local_date = datetime.datetime.fromisoformat(
                        p["punch_local"]).date().isoformat()
                except Exception:
                    local_date = _today_local()
                rid = insert_biometric_punch(
                    did, uid, p["punch_utc"], p["punch_local"],
                    local_date, sid, 1 if matched else 0)
                if rid:
                    entry["new"] += 1
                    new_total += 1
            entry["ok"] = True
        except Exception as e:
            entry["error"] = str(e)
        dev_status.append(entry)

    _last_status["devices"] = dev_status
    return new_total


def run_once(cfg=None):
    """دورة واحدة كاملة: سحب ثم معالجة. تُرجع (عدد_جديد, إحصاء)."""
    with poller_lock:
        from config_manager import load_config
        cfg = cfg or load_config()
        new = _pull_devices(cfg)
        stat = process_pending(cfg)
        _last_status["last_run"] = _now_local().isoformat(timespec="seconds")
        return new, stat


def _loop(interval):
    while not _stop.is_set():
        try:
            from config_manager import load_config
            cfg = load_config()
            if cfg.get("biometric_enabled"):
                run_once(cfg)
                _last_status["last_error"] = ""
        except Exception as e:
            _last_status["last_error"] = str(e)
        _stop.wait(interval)


def start(interval=10):
    """يبدأ الخيط مرة واحدة. آمن للاستدعاء المتكرر."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _last_status["running"] = True
    _thread = threading.Thread(target=_loop, args=(interval,), daemon=True)
    _thread.start()


def stop():
    _stop.set()
    _last_status["running"] = False


def status():
    return dict(_last_status)
