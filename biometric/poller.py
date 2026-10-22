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

# آخر عدد سجلات رأيناه على كل جهاز. في الذاكرة عمداً: بعد إعادة التشغيل
# تُنزَّل الدورة الأولى كاملةً ثم يسري التسريع — ولا خطر في ذلك، بخلاف
# حفظه فيصير مصدرَ حقيقةٍ ثانياً قد يُفوّت بصمات لو انحرف.
_seen_records = {}

# ── تقدّم السحب — تقرؤه الواجهة أثناء العملية ────────────────────────
# السحب طلبٌ واحد يحجب حتى ينتهي، وقد يطول (اتصالٌ بكل جهاز ثم قراءة
# سجلّه). فبلا هذا لا تعرف الواجهة إلا «انتهى» — فتبدو متجمّدة.
# قاموسٌ بسيط يُقرأ بلا قفل: الكتابة ذرّية في بايثون، وقراءةُ قيمةٍ
# قديمة بجزء من الثانية لا تضرّ شريط تقدّم.
_progress = {"running": False, "pct": 0, "stage": "", "detail": "",
             "idx": 0, "total": 0, "started": None, "finished": None}


def get_progress() -> dict:
    return dict(_progress)


# ── العلامة المائية: كم يوماً نُعيد عرضه احتياطاً ───────────────────
# سحبُ ما بعد «آخر بصمة خزّنّاها» وحده يترك ثغرتين تُضيّعان يوماً كاملاً
# بلا أي أثر:
#   ① **ساعة الجهاز تنحرف.** بصمةٌ واحدة بتاريخٍ مستقبلي ترفع العلامة
#      إلى ذلك التاريخ، فتُهمَل كل بصمةٍ حقيقية بعدها **إلى الأبد**.
#   ② إخفاقٌ عابر في إدخال بصمةٍ وسط دفعة يرفع العلامة فوقها فلا تعود.
# والإعادة آمنة تماماً: `UNIQUE(device_id, device_uid, punch_utc)` يرفض
# المكرر، فإعادة العرض لا تُنتج سجلاً زائداً ولا إشعاراً مكرراً.
_WATERMARK_BACKTRACK_DAYS = 3


def _safe_watermark(after_utc):
    """يُرجع علامةً يُوثق بها: تُهمَل المستقبلية، ويُطرح هامش أيام."""
    if not after_utc:
        return None
    try:
        dt = datetime.datetime.fromisoformat(
            str(after_utc).replace("Z", "").strip())
    except Exception:
        return None
    now = datetime.datetime.utcnow()
    if dt > now:
        # علامةٌ من المستقبل = ساعة جهازٍ منحرفة. تُهمَل كلياً فيُعاد
        # فحص السجلّ من أوله — والمكرر يرفضه القيد.
        print("[BIO] علامة مائية مستقبلية (%s) — أُهملت" % after_utc)
        return None
    return (dt - datetime.timedelta(days=_WATERMARK_BACKTRACK_DAYS)
            ).isoformat(timespec="seconds")


def _prog(pct=None, stage=None, detail=None, idx=None, total=None):
    if pct is not None:
        _progress["pct"] = max(0, min(100, int(pct)))
    if stage is not None:
        _progress["stage"] = stage
    if detail is not None:
        _progress["detail"] = detail
    if idx is not None:
        _progress["idx"] = idx
    if total is not None:
        _progress["total"] = total
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
    # كل فرع يُرجع الشكل نفسه: (رقم الطالب، الاسم، اسم الفصل، معرّف الفصل).
    # المُستدعي يفكّ أربعة — فأي فرعٍ بثلاث قيم يُسقط المزامنة كلها.
    if uid in enrollments:
        e = enrollments[uid]
        # سجلّ الربط اليدوي لا يحمل معرّف الفصل — فيُؤخَذ من كشف الطلاب
        cid = e.get("class_id", "") or \
            (student_map.get(str(e["student_id"])) or {}).get("class_id", "")
        return (e["student_id"], e.get("student_name", ""),
                e.get("class_name", ""), cid or "")
    if uid in academic_map:
        a = academic_map[uid]
        return (a["student_id"], a.get("name", ""),
                a.get("class_name", ""), a.get("class_id", "") or "")
    if uid in student_map:
        s = student_map[uid]
        return (uid, s.get("name", ""),
                s.get("class_name", ""), s.get("class_id", "") or "")
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

        sid, sname, cname, ccid = matched
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

        if minutes_late <= 0:
            # حضر في الوقت — لا تأخر. نعلّمه حاضراً ولا نُشعر.
            #
            # كان الشرط مقيَّداً بـ`mode == "tardiness"`، فمدرسةٌ في وضع
            # «attendance» يُكتب لها سجلّ تأخر **بصفر دقيقة لكل من بصم**.
            # فظهر في اللوحة أن كل الحاضرين متأخرون (٣٢٠ بدل ٧٤)، وكاد
            # يُرسَل لأولياء أمورهم جميعاً إشعارُ «تأخر ٠ دقيقة».
            #
            # وحضورُ الطالب مسجَّل أصلاً في جدول البصمات، ومنه تقرؤه
            # الخلطة — فلا حاجة لسجلّ تأخر كاذب ليُعرف أنه حضر.
            mark_punch_processed(p["id"], "حاضر", student_id=sid, matched=1)
            stat["present"] += 1
            continue

        minutes_late = max(minutes_late, 0)
        # ‏`class_id` كان يُكتب فارغاً، فلا يُطابقه ترشيحٌ بفصل أو صفّ
        # في التقارير — وتظهر المرحلة بطالبةٍ واحدة. صار يُكتب من كشف
        # الطلاب، ومن لا فصل له يبقى فارغاً كما كان.
        ok = insert_tardiness(
            p["date"] or _today_local(), ccid or "", cname, sid, sname,
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
                _notify_parent(phone, sname, local, minutes_late, sid=sid,
                               cname=cname, cid=ccid or "",
                               date_str=p["date"] or _today_local())

    return stat


def _notify_parent(phone, name, local_dt, minutes_late, sid="", cname="", cid="",
                   date_str=""):
    """
    إشعار واتساب فوري لولي الأمر — بلا إسقاط المعالجة إن فشل الإرسال.

    يمرّ بقاعدة «رسالة تأخر واحدة في اليوم» ويُسجَّل في سجلّ الرسائل: كان
    يخرج بلا تسجيل، ثم تُرسَل رسالة التأخر يدوياً فتصل وليَّ الأمر رسالتان،
    ولا يظهر في التقرير إلا واحدة.
    """
    try:
        t = local_dt.strftime("%I:%M")
        msg = ("تنبيه حضور\n"
               "الطالب: %s\n"
               "سجّل دخوله الساعة %s متأخّراً %d دقيقة." %
               (name, t, minutes_late))
        if sid:
            from alerts_service import send_daily_message
            send_daily_message("tardiness", date_str or _today_local(), sid, name,
                               cid, cname, phone, msg, template_used="biometric",
                               source="biometric")
        else:
            from whatsapp_service import send_whatsapp_message
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

    _active = [d for d in devices if d.get("enabled", True)]
    _prog(total=len(_active), idx=0)
    for _i, dcfg in enumerate(_active, 1):
        did = str(dcfg.get("device_id") or dcfg.get("ip") or "dev")
        entry = {"device_id": did, "ok": False, "new": 0, "error": ""}
        # ٨٠٪ من الشريط للأجهزة، والباقي للمعالجة
        _prog(pct=int((_i - 1) * 80.0 / max(1, len(_active))),
              stage="يتصل بالجهاز", detail=did, idx=_i)
        try:
            dev = make_device(dcfg)
            after = _safe_watermark(get_last_punch_utc(did))
            # المرحلة تُعلَن **قبل** القراءة لا بعدها: القراءة هي الجزء
            # الطويل، وإعلانُها بعد انتهائها يصف ما فرغ لا ما يجري.
            _prog(stage="يقرأ سجلّ الجهاز", detail=did)
            # عدّ آخر دورة: إن لم يتغيّر فلا تنزيل للسجلّ كاملاً
            try:
                punches = dev.read_punches(
                    after_utc=after, known_records=_seen_records.get(did))
            except TypeError:
                # محاكٍ أو جهاز لا يعرف المعامل الجديد
                punches = dev.read_punches(after_utc=after)
            cnt = getattr(dev, "last_counts", None) or {}
            if cnt:
                _seen_records[did] = cnt.get("records")
                entry["records"] = cnt.get("records")
                entry["users"] = cnt.get("users")
                entry["fingers"] = cnt.get("fingers")
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
        _prog(pct=int(_i * 80.0 / max(1, len(_active))),
              detail="%s — %s" % (did, ("جديد %d" % entry["new"]) if entry["ok"]
                                  else "تعذّر الاتصال"))
        dev_status.append(entry)

    _last_status["devices"] = dev_status
    return new_total


def run_once(cfg=None):
    """دورة واحدة كاملة: سحب ثم معالجة. تُرجع (عدد_جديد, إحصاء)."""
    with poller_lock:
        from config_manager import load_config
        _progress.update({"running": True, "pct": 0, "stage": "يبدأ",
                          "detail": "", "idx": 0, "total": 0,
                          "started": _now_local().isoformat(timespec="seconds"),
                          "finished": None})
        try:
            cfg = cfg or load_config()
            new = _pull_devices(cfg)
            _prog(pct=85, stage="يطابق البصمات بالطلاب", detail="")
            stat = process_pending(cfg)
            _prog(pct=100, stage="اكتمل",
                  detail="%d بصمة جديدة" % new if new else "لا جديد")
            _last_status["last_run"] = _now_local().isoformat(timespec="seconds")
            return new, stat
        finally:
            # الشريط يُغلق مهما كان المآل — وإلا بقي «يعمل» إلى الأبد
            _progress["running"] = False
            _progress["finished"] = _now_local().isoformat(timespec="seconds")


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
