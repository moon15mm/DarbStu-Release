# -*- coding: utf-8 -*-
"""
monitor_service.py — لقطة شاملة لحالة النظام كله.

لوحة المراقبة كانت تعرض الغياب وحده، فكان المدير يفتح ستّ شاشات ليعرف
هل النظام بخير: هل الواتساب متصل؟ هل البوت يردّ؟ هل بقي في السقف رصيد؟
متى آخر نسخة احتياطية؟ كم تحويلاً ينتظر؟

كل ذلك يُجمع هنا في استدعاء واحد. وكل قسم مغلَّف بـ try مستقل: إن سقط
جزء (خادم واتساب مطفأ مثلاً) تظهر بقية اللوحة بدل أن تسقط كلها.
"""
import datetime
import os
import sqlite3


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _dur_ar(m) -> str:
    """دقائق ← نصّ عربي مقروء: «٤٠ دقيقة» / «ساعتان و١٥ دقيقة»."""
    m = int(m or 0)
    if m < 60:
        return "%d دقيقة" % m
    h, r = divmod(m, 60)
    hs = "ساعة" if h == 1 else ("ساعتين" if h == 2 else "%d ساعات" % h)
    return hs if not r else "%s و%d دقيقة" % (hs, r)


def _today() -> str:
    tz = datetime.timezone(datetime.timedelta(hours=3))
    return datetime.datetime.now(datetime.timezone.utc).astimezone(tz)\
        .date().isoformat()


# ══════════════════════════════════════════════════════════════
#  الأقسام
# ══════════════════════════════════════════════════════════════

def _today_block(date_str):
    from report_builder import compute_today_metrics
    from database import query_tardiness, query_excuses
    m = compute_today_metrics(date_str)
    t = dict(m.get("totals") or {})
    t["tardiness"] = len(_safe(lambda: query_tardiness(date_filter=date_str), []) or [])
    t["excused"] = len(_safe(lambda: query_excuses(date_filter=date_str), []) or [])
    # بطاقة «الاستئذان» في اللوحة تقرأ t.permissions، والمفتاح لم يكن
    # يُبنى أصلاً — فكانت تعرض صفراً في كل يوم مهما بلغ عدد الطلبات.
    from alerts_service import query_permissions
    t["permissions"] = len(
        _safe(lambda: query_permissions(date_filter=date_str), []) or [])
    students = int(t.get("students") or 0)
    absent = int(t.get("absent") or 0)
    t["attendance_pct"] = round((students - absent) / students * 100, 1) if students else 0.0
    return {"totals": t, "by_class": m.get("by_class") or []}


def _trend_block(days=7):
    """غياب آخر أيام دراسية — للرسم البياني الصغير."""
    from constants import DB_PATH
    out = []
    con = sqlite3.connect(DB_PATH)
    try:
        tz = datetime.timezone(datetime.timedelta(hours=3))
        d0 = datetime.datetime.now(datetime.timezone.utc).astimezone(tz).date()
        back = 0
        while len(out) < days and back < days * 3:
            d = d0 - datetime.timedelta(days=back)
            back += 1
            if d.weekday() in (4, 5):          # الجمعة والسبت
                continue
            n = con.execute("SELECT COUNT(DISTINCT student_id) FROM absences "
                            "WHERE date=?", (d.isoformat(),)).fetchone()[0]
            out.append({"date": d.isoformat(),
                        "label": ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس",
                                  "الجمعة", "السبت", "الأحد"][d.weekday()],
                        "absent": int(n)})
    finally:
        con.close()
    out.reverse()
    return out


def _live_block(date_str):
    """أي فصل سُجّل في أي حصة — ومن لم يُسجّل بعد."""
    from database import load_students
    from constants import DB_PATH
    classes = load_students().get("list") or []
    total = len(classes)
    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute("SELECT DISTINCT class_id, period FROM absences "
                           "WHERE date=?", (date_str,)).fetchall()
    finally:
        con.close()
    done = {}
    for cid, p in rows:
        done.setdefault(int(p or 0), set()).add(str(cid))

    periods = []
    for p in range(1, 8):
        d = done.get(p, set())
        missing = [c.get("name") for c in classes if str(c.get("id")) not in d]
        periods.append({"period": p, "done": len(d), "total": total,
                        "missing": missing[:12],
                        "missing_count": len(missing)})
    return {"periods": periods, "classes_total": total}


def _whatsapp_block():
    out = {"connected": False, "reply_bot": None, "pending": None,
           "sent_today": 0, "limit": 0, "remaining": 0, "age_days": 0,
           "warming_up": False}
    try:
        import wa_limits
        st = wa_limits.status()
        out.update({"sent_today": st.get("sent_today", 0),
                    "limit": st.get("limit", 0),
                    "remaining": st.get("remaining", 0),
                    "age_days": st.get("age_days", 0),
                    "warming_up": bool(st.get("warming_up"))})
    except Exception:
        pass
    try:
        import json as _j
        import urllib.request as _ur
        from config_manager import load_config
        port = int(load_config().get("whatsapp_port", 3000) or 3000)
        with _ur.urlopen("http://127.0.0.1:%d/status" % port, timeout=2) as r:
            d = _j.loads(r.read().decode())
        out["connected"] = bool(d.get("ready"))
        out["reply_bot"] = d.get("bot_enabled")
        out["pending"] = d.get("pending")
    except Exception:
        out["connected"] = False
    return out


def _tasks_block():
    from config_manager import BOT_FLAGS, PARENT_FLAGS, bots_status
    AR = {"absence_bot_enabled": "رسائل الغياب",
          "permission_bot_enabled": "الاستئذان",
          "alert_enabled": "الإشعارات الذكية",
          "daily_report_enabled": "التقرير اليومي",
          "tardiness_auto_send_enabled": "رابط التأخر",
          "weekly_reward_enabled": "التعزيز الأسبوعي"}
    st = bots_status()
    flags = st.get("flags") or {}
    items = []
    for f in BOT_FLAGS:
        items.append({"key": f, "name": AR.get(f, f),
                      "on": bool(flags.get(f)),
                      "audience": "ولي أمر" if f in PARENT_FLAGS else "الإدارة"})
    return {"master": bool(st.get("master")), "items": items}


def _data_block():
    from database import load_students, load_teachers, get_all_users, get_backup_list
    from constants import DB_PATH
    classes = _safe(lambda: load_students().get("list") or [], [])
    teachers = _safe(lambda: (load_teachers().get("teachers") or []), [])
    users = _safe(lambda: get_all_users() or [], [])
    backups = _safe(lambda: get_backup_list() or [], [])

    last, age = None, None
    if backups:
        last = backups[0].get("created_at") or backups[0].get("filename")
        try:
            d = str(backups[0].get("created_at"))[:10]
            age = (datetime.date.today()
                   - datetime.date.fromisoformat(d)).days
        except Exception:
            age = None
    size_mb = _safe(lambda: round(os.path.getsize(DB_PATH) / 1048576, 1), 0)
    return {"classes": len(classes),
            "students": sum(len(c.get("students") or []) for c in classes),
            "teachers": len(teachers), "users": len(users),
            "db_mb": size_mb, "backups": len(backups),
            "last_backup": last, "backup_age_days": age}


def _oldest_pending_wait(con, date_str):
    """كم دقيقة انتظر أقدمُ طلب استئذان اليوم — صفر إن لا شيء ينتظر.

    الاستئذان يُطلب والطالب واقف عند الباب، فالمهمّ ليس عدد الطلبات بل
    كم صار لأقدمها. created_at يُكتب بـ utcnow في insert_permission.
    """
    try:
        row = con.execute(
            "SELECT MIN(created_at) FROM permissions WHERE date=? AND "
            "status NOT IN ('موافق','مرفوض')", (date_str,)).fetchone()
        if not row or not row[0]:
            return 0
        t = datetime.datetime.fromisoformat(str(row[0]).replace("Z", ""))
        m = int((datetime.datetime.utcnow() - t).total_seconds() // 60)
    except Exception:
        return 0
    # ساعة سالبة أو تتجاوز اليوم = ساعة جهاز مغلوطة، لا انتظار حقيقي
    return m if 0 < m <= 1440 else 0


def _workflow_block(date_str):
    """ما ينتظر إجراءً من الإدارة."""
    from constants import DB_PATH
    con = sqlite3.connect(DB_PATH)

    def q(sql, args=()):
        try:
            return int(con.execute(sql, args).fetchone()[0])
        except Exception:
            return 0

    try:
        return {
            # الاستئذان طلبُ خروجٍ فوري: صلاحيته ساعات لا أيام — بخلاف
            # العذر الذي يُقبل بعد أيام. عدّ المعلّق من كل التواريخ كان
            # يقول «٧ بانتظار الرد» وأقدمها من ١٧ يوماً، بينما بطاقة
            # الاستئذان في الشاشة نفسها تقول ٠. رقمان لشيء واحد.
            "pending_permissions": q(
                "SELECT COUNT(*) FROM permissions WHERE date=? AND "
                "status NOT IN ('موافق','مرفوض')", (date_str,)),
            "pending_wait_min": _oldest_pending_wait(con, date_str),
            # طلبات أيامٍ مضت لم تُحسم: لم يخرج الطالب ولم يعد للأمر معنى.
            # تُعرض سطراً في التفاصيل ولا تُنبّه — ولا تُحذف، فهي سجلّ.
            "stale_permissions": q(
                "SELECT COUNT(*) FROM permissions WHERE date<? AND "
                "status NOT IN ('موافق','مرفوض')", (date_str,)),
            "open_referrals": q(
                "SELECT COUNT(*) FROM student_referrals WHERE "
                "IFNULL(status,'') NOT IN ('مغلق','منتهي')"),
            "counselor_open": q(
                "SELECT COUNT(*) FROM counselor_referrals WHERE "
                "IFNULL(status,'') NOT IN ('مغلق','منتهي')"),
            "visits_today": q("SELECT COUNT(*) FROM parent_visits WHERE date=?",
                              (date_str,)),
            "unread_reports": q(
                "SELECT COUNT(*) FROM teacher_reports WHERE IFNULL(is_read,0)=0"),
            "sessions_week": q(
                "SELECT COUNT(*) FROM counselor_sessions WHERE date>=?",
                ((datetime.date.today() - datetime.timedelta(days=7)).isoformat(),)),
        }
    finally:
        con.close()


def _system_block():
    from constants import APP_VERSION, PORT
    from config_manager import load_config
    cfg = _safe(load_config, {}) or {}
    lic = _safe(lambda: __import__("license_manager").check_license(), {}) or {}
    return {"version": APP_VERSION,
            "school": cfg.get("school_name", ""),
            "stage": cfg.get("school_stage", ""),
            "gender": cfg.get("school_gender", "boys"),
            "domain": cfg.get("cloudflare_domain", "") or "",
            "port": PORT,
            "license_ok": bool(lic.get("valid", lic.get("ok", True))),
            "license_days": lic.get("days_left", lic.get("days", None)),
            "license_type": lic.get("type", lic.get("plan", ""))}


# ══════════════════════════════════════════════════════════════
#  التنبيهات — ما يحتاج انتباه المدير الآن
# ══════════════════════════════════════════════════════════════

def _alerts(snap):
    a = []
    wa = snap.get("whatsapp") or {}
    data = snap.get("data") or {}
    tasks = snap.get("tasks") or {}
    live = snap.get("live") or {}
    wf = snap.get("workflow") or {}
    sysb = snap.get("system") or {}

    if not wa.get("connected"):
        a.append({"level": "err", "text": "خادم الواتساب غير متصل — لن تخرج أي رسالة",
                  "tab": "whatsapp"})
    elif wa.get("reply_bot") is False:
        a.append({"level": "warn", "text": "بوت استقبال الأعذار موقوف — لن تُسجَّل ردود أولياء الأمور"})

    lim = wa.get("limit") or 0
    if lim and wa.get("remaining", 0) == 0:
        a.append({"level": "warn", "text": "بلغت السقف اليومي لرسائل الواتساب (%d) — يُستأنف غداً" % lim})
    elif lim and wa.get("remaining", 0) <= max(3, lim * 0.1):
        a.append({"level": "warn", "text": "بقي %d من سقف اليوم (%d)" % (wa.get("remaining", 0), lim)})

    if not tasks.get("master"):
        a.append({"level": "warn", "text": "الإرسال لأولياء الأمور موقوف بالمفتاح الرئيسي"})
    elif not any(i["on"] for i in tasks.get("items", [])):
        a.append({"level": "warn", "text": "كل المهام التلقائية مطفأة — لن تصل رسائل تلقائية"})

    age = data.get("backup_age_days")
    if data.get("backups", 0) == 0:
        a.append({"level": "err", "text": "لا توجد نسخة احتياطية إطلاقاً"})
    elif age is not None and age >= 14:
        a.append({"level": "warn", "text": "آخر نسخة احتياطية قبل %d يوماً" % age})

    if data.get("students", 0) == 0:
        a.append({"level": "err", "text": "لا يوجد طلاب — استورد ملف نور"})
    if data.get("teachers", 0) == 0:
        a.append({"level": "warn", "text": "لا يوجد معلمون — استورد ملف المعلمين من نور"})

    # حصص لم يُسجَّل فيها شيء إطلاقاً اليوم
    zero = [p["period"] for p in live.get("periods", []) if p["done"] == 0]
    if zero and len(zero) < 7:
        a.append({"level": "info",
                  "text": "لم يُسجَّل غياب في الحصص: " + "، ".join(str(x) for x in zero)})

    pend = wf.get("pending_permissions") or 0
    if pend:
        wait = wf.get("pending_wait_min") or 0
        # الطالب ينتظر عند الباب: نصف ساعة بلا ردّ ليست «معلومة» بل تقصير
        a.append({"level": "warn" if wait >= 30 else "info",
                  "text": ("%d طلب استئذان بانتظار الرد — أقدمها منذ %s"
                           % (pend, _dur_ar(wait))) if wait
                  else "%d طلب استئذان بانتظار الرد اليوم" % pend})
    if wf.get("unread_reports"):
        a.append({"level": "info", "text": "%d تقرير معلم لم يُقرأ"
                  % wf["unread_reports"]})

    days = sysb.get("license_days")
    if isinstance(days, int) and days <= 14:
        a.append({"level": "err" if days <= 3 else "warn",
                  "text": "الاشتراك ينتهي خلال %d يوم" % days})
    return a


# ══════════════════════════════════════════════════════════════

def build_snapshot(date_str: str = "") -> dict:
    """اللقطة الكاملة. لا ترفع استثناءً — كل قسم معزول."""
    d = date_str or _today()
    snap = {"ok": True, "date": d,
            "generated_at": datetime.datetime.now().strftime("%H:%M:%S")}
    snap["today"] = _safe(lambda: _today_block(d), {"totals": {}, "by_class": []})
    snap["trend"] = _safe(lambda: _trend_block(), [])
    snap["live"] = _safe(lambda: _live_block(d), {"periods": [], "classes_total": 0})
    snap["whatsapp"] = _safe(_whatsapp_block, {})
    snap["tasks"] = _safe(_tasks_block, {"master": True, "items": []})
    snap["data"] = _safe(_data_block, {})
    snap["workflow"] = _safe(lambda: _workflow_block(d), {})
    snap["system"] = _safe(_system_block, {})
    snap["alerts"] = _safe(lambda: _alerts(snap), [])
    return snap
