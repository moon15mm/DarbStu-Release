# -*- coding: utf-8 -*-
"""
api/biometric_routes.py — ربط جهاز البصمة وإدارته.

  GET  /web/biometric                          صفحة التحكّم (مصادَقة)
  GET  /web/api/biometric/status               حالة الأجهزة والخيط وعدّادات اليوم
  GET  /web/api/biometric/config               الإعدادات الحالية
  POST /web/api/biometric/config               حفظ الإعدادات
  POST /web/api/biometric/test                 فحص اتصال جهاز {ip, comm_key}
  POST /web/api/biometric/scan                 البحث عن أجهزة في الشبكة
  GET  /web/api/biometric/punches              البصمات (سجلّ حيّ)
  POST /web/api/biometric/run                  دورة سحب/معالجة فورية (زر «الآن»)
  GET  /web/api/biometric/enrollments          جدول الربط اليدوي
  POST /web/api/biometric/enroll               ربط رقم جهاز بطالب
  POST /web/api/biometric/unenroll             حذف ربط
  POST /web/api/biometric/mock-seed            حقن بصمات تجريبية (وضع التطوير)

كل الكتابة تمرّ بالمصادقة. القراءة الحيّة للبصمات كذلك — فقد تحمل أسماء
طلاب. أداة الاختبار (mock-seed) محجوبة إلا في وضع التطوير.
"""
import json
import socket
import threading
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from constants import now_riyadh_date, debug_on, local_ip
from config_manager import load_config, save_config
from database import (query_biometric_punches, get_biometric_daily_summary,
                      get_biometric_enrollments, set_biometric_enrollment,
                      delete_biometric_enrollment, get_student_map,
                      load_students, mark_fp_enrolled, unmark_fp_enrolled,
                      get_fp_enrolled_ids, assign_academic_numbers,
                      get_academic_map, sync_fp_enrollments_from_device)

router = APIRouter()


def _auth(request: Request) -> bool:
    from api.web_routes import _get_current_user
    return bool(_get_current_user(request))


@router.get("/web/biometric", response_class=HTMLResponse)
async def biometric_page(request: Request):
    from api.web_routes import _get_current_user
    if not _get_current_user(request):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/web/login")
    return HTMLResponse(
        content=_PAGE,
        headers={"Content-Security-Policy":
                 "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:; "
                 "script-src * 'unsafe-inline' 'unsafe-eval'; "
                 "style-src * 'unsafe-inline';"})


@router.get("/web/biometric/enroll", response_class=HTMLResponse)
async def biometric_enroll_page(request: Request):
    from api.web_routes import _get_current_user
    if not _get_current_user(request):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/web/login")
    return HTMLResponse(
        content=_ENROLL_PAGE,
        headers={"Content-Security-Policy":
                 "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:; "
                 "script-src * 'unsafe-inline' 'unsafe-eval'; "
                 "style-src * 'unsafe-inline';"})


def _unauth():
    return JSONResponse({"ok": False, "error": "غير مصرّح"}, status_code=401)


# ── الحالة ───────────────────────────────────────────────────────
@router.get("/web/api/biometric/status", response_class=JSONResponse)
async def bio_status(request: Request):
    if not _auth(request):
        return _unauth()
    from biometric import poller
    cfg = load_config()
    today = now_riyadh_date()
    return JSONResponse({
        "ok": True,
        "enabled": bool(cfg.get("biometric_enabled")),
        "mode": cfg.get("biometric_mode", "tardiness"),
        "device_count": len(cfg.get("biometric_devices") or []),
        "poller": poller.status(),
        "summary": get_biometric_daily_summary(today),
        "date": today,
    })


# ── الإعدادات ─────────────────────────────────────────────────────
@router.get("/web/api/biometric/config", response_class=JSONResponse)
async def bio_get_config(request: Request):
    if not _auth(request):
        return _unauth()
    cfg = load_config()
    return JSONResponse({
        "ok": True,
        "enabled": bool(cfg.get("biometric_enabled")),
        "mode": cfg.get("biometric_mode", "tardiness"),
        "grace_min": int(cfg.get("biometric_grace_min", 0)),
        "notify_parent": bool(cfg.get("biometric_notify_parent", True)),
        "school_start_time": cfg.get("school_start_time", "07:00"),
        "devices": cfg.get("biometric_devices") or [],
    })


@router.post("/web/api/biometric/config", response_class=JSONResponse)
async def bio_save_config(request: Request):
    if not _auth(request):
        return _unauth()
    try:
        d = await request.json()
        cfg = load_config()
        if "enabled" in d:
            cfg["biometric_enabled"] = bool(d["enabled"])
        if "mode" in d:
            cfg["biometric_mode"] = (
                "attendance" if d["mode"] == "attendance" else "tardiness")
        if "grace_min" in d:
            cfg["biometric_grace_min"] = max(0, int(d.get("grace_min") or 0))
        if "notify_parent" in d:
            cfg["biometric_notify_parent"] = bool(d["notify_parent"])
        if "devices" in d and isinstance(d["devices"], list):
            clean = []
            for dev in d["devices"]:
                clean.append({
                    "device_id": str(dev.get("device_id") or "").strip()
                    or (dev.get("ip") or "gate"),
                    "protocol": dev.get("protocol", "zk"),
                    "ip": str(dev.get("ip") or "").strip(),
                    "port": int(dev.get("port") or 4370),
                    "comm_key": int(dev.get("comm_key") or 0),
                    "enabled": bool(dev.get("enabled", True)),
                })
            cfg["biometric_devices"] = clean
        save_config(cfg)

        # شغّل الخيط أو أوقفه حسب التفعيل — فوراً، بلا انتظار إعادة تشغيل
        from biometric import poller
        if cfg.get("biometric_enabled"):
            poller.start()
        else:
            poller.stop()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── فحص اتصال جهاز ────────────────────────────────────────────────
@router.post("/web/api/biometric/test", response_class=JSONResponse)
async def bio_test(request: Request):
    if not _auth(request):
        return _unauth()
    try:
        d = await request.json()
        from biometric import make_device
        dev = make_device({
            "protocol": d.get("protocol", "zk"),
            "ip": d.get("ip", ""),
            "port": int(d.get("port") or 4370),
            "comm_key": int(d.get("comm_key") or 0),
            "device_id": d.get("device_id", "test"),
        })
        info = dev.test_connection()
        return JSONResponse({"ok": True, "info": info})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ── البحث في الشبكة ───────────────────────────────────────────────
@router.post("/web/api/biometric/scan", response_class=JSONResponse)
async def bio_scan(request: Request):
    if not _auth(request):
        return _unauth()
    try:
        me = local_ip()
        base = me.rsplit(".", 1)[0]
        found = []
        lock = threading.Lock()

        def check(i):
            ip = "%s.%d" % (base, i)
            sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sk.settimeout(0.8)
            try:
                sk.connect((ip, 4370))
                with lock:
                    found.append(ip)
            except Exception:
                pass
            finally:
                sk.close()

        ts = [threading.Thread(target=check, args=(i,))
              for i in range(1, 255)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return JSONResponse({"ok": True, "found": sorted(
            found, key=lambda x: int(x.rsplit(".", 1)[1])), "network": base})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── السجلّ الحيّ ──────────────────────────────────────────────────
@router.get("/web/api/biometric/punches", response_class=JSONResponse)
async def bio_punches(request: Request, date: str = ""):
    if not _auth(request):
        return _unauth()
    rows = query_biometric_punches(date_filter=date or now_riyadh_date(),
                                   limit=200)
    return JSONResponse({"ok": True, "rows": rows})


@router.post("/web/api/biometric/run", response_class=JSONResponse)
async def bio_run(request: Request):
    if not _auth(request):
        return _unauth()
    try:
        from biometric import poller
        new, stat = poller.run_once()
        return JSONResponse({"ok": True, "new": new, "stat": stat})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── الربط اليدوي ──────────────────────────────────────────────────
@router.get("/web/api/biometric/enrollments", response_class=JSONResponse)
async def bio_enrollments(request: Request):
    if not _auth(request):
        return _unauth()
    en = get_biometric_enrollments()
    return JSONResponse({"ok": True, "rows": list(en.values())})


@router.post("/web/api/biometric/enroll", response_class=JSONResponse)
async def bio_enroll(request: Request):
    if not _auth(request):
        return _unauth()
    try:
        d = await request.json()
        uid = str(d.get("device_uid", "")).strip()
        sid = str(d.get("student_id", "")).strip()
        if not uid or not sid:
            return JSONResponse({"ok": False, "error": "رقم الجهاز والطالب مطلوبان"})
        smap = get_student_map()
        info = smap.get(sid, {})
        set_biometric_enrollment(uid, sid, info.get("name", ""),
                                 info.get("class_name", ""))
        return JSONResponse({"ok": True, "matched": bool(info)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/web/api/biometric/unenroll", response_class=JSONResponse)
async def bio_unenroll(request: Request):
    if not _auth(request):
        return _unauth()
    try:
        d = await request.json()
        delete_biometric_enrollment(str(d.get("device_uid", "")).strip())
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── توليد الأرقام الأكاديمية ──────────────────────────────────────
@router.post("/web/api/biometric/generate-numbers", response_class=JSONResponse)
async def bio_generate_numbers(request: Request):
    """
    يولّد رقماً أكاديمياً مبنياً على السنة الميلادية (≤٩ خانات) لكل طالب
    لا يملكه — يبقى ثابتاً معه حتى التخرج. idempotent: لا يمسّ رقماً قائماً.
    """
    if not _auth(request):
        return _unauth()
    try:
        res = assign_academic_numbers(force=False)
        return JSONResponse({"ok": True, **res})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── التسجيل الحيّ: طلاب بالفصول + أمر الالتقاط ────────────────────
@router.get("/web/api/biometric/students", response_class=JSONResponse)
async def bio_students(request: Request):
    """طلاب المدرسة مجمّعين بالفصول، مع الرقم الأكاديمي وعلامة التسجيل."""
    if not _auth(request):
        return _unauth()
    enrolled = get_fp_enrolled_ids()
    store = load_students()
    classes = []
    total = done = no_num = 0
    for c in store.get("list", []):
        studs = []
        for s in c.get("students", []):
            sid = str(s.get("id"))
            an = str(s.get("academic_no") or "").strip()
            is_en = sid in enrolled
            total += 1
            done += 1 if is_en else 0
            no_num += 0 if an else 1
            studs.append({"id": sid, "name": s.get("name", ""),
                          "academic_no": an, "enrolled": is_en})
        classes.append({"id": c.get("id"), "name": c.get("name", ""),
                        "students": studs,
                        "done": sum(1 for x in studs if x["enrolled"]),
                        "total": len(studs)})
    return JSONResponse({"ok": True, "classes": classes,
                         "total": total, "done": done,
                         "without_number": no_num})


# ── ملف الطلاب للأداة الخارجية (تسحب الاسم والرقم) ────────────────
@router.get("/web/api/biometric/roster", response_class=JSONResponse)
async def bio_roster(request: Request):
    """
    قائمة مسطّحة: الرقم الأكاديمي + الاسم + الفصل — لأداة التسجيل على
    اللابتوب. تكتب الأداة الرقم الأكاديمي في الجهاز مع كل بصمة.
    """
    if not _auth(request):
        return _unauth()
    store = load_students()
    rows = []
    for c in store.get("list", []):
        for s in c.get("students", []):
            an = str(s.get("academic_no") or "").strip()
            if not an:
                continue
            rows.append({"academic_no": an, "name": s.get("name", ""),
                         "class_name": c.get("name", ""),
                         "student_id": str(s.get("id"))})
    return JSONResponse({"ok": True, "count": len(rows), "students": rows})


@router.post("/web/api/biometric/enroll-live", response_class=JSONResponse)
async def bio_enroll_live(request: Request):
    """
    يأمر الجهاز بالتقاط بصمة طالب. **الرقم المكتوب في الجهاز هو الرقم
    الأكاديمي القصير** (رقم الهوية ١٠ خانات لا يقبله جهاز ٩). فتُطابَق
    البصمة لاحقاً عبر خريطة الرقم الأكاديمي.
    """
    if not _auth(request):
        return _unauth()
    try:
        d = await request.json()
        sid = str(d.get("student_id", "")).strip()      # رقم الهوية (للعلامة)
        academic = str(d.get("academic_no", "")).strip()  # ما يُكتب في الجهاز
        name = d.get("student_name", "")
        finger = int(d.get("finger") or 0)
        if not academic:
            return JSONResponse(
                {"ok": False,
                 "error": "لا رقم أكاديمي — ولّد الأرقام أولاً"})

        cfg = load_config()
        devices = [x for x in (cfg.get("biometric_devices") or [])
                   if x.get("enabled", True)]
        if not devices:
            # في وضع التطوير نتيح تجربة الصفحة بمحاكٍ بلا عتاد
            if debug_on():
                devices = [{"protocol": "mock", "device_id": "mock"}]
            else:
                return JSONResponse(
                    {"ok": False,
                     "error": "لا يوجد جهاز مُفعّل — أضِفه واحفظه أولاً"})

        from biometric import make_device
        from biometric.zk_device import transliterate_arabic_name
        from biometric.poller import poller_lock
        dev = make_device(devices[0])
        # الرقم الأكاديمي هو رقم المستخدم في الجهاز، والاسم يظهر على شاشته (إنجليزي)
        name_en = transliterate_arabic_name(name) if name else academic
        with poller_lock:
            res = dev.enroll_student(academic, name, finger)
        if res.get("ok"):
            # العلامة على رقم الهوية (مصدر الحقيقة للطالب)، والجهاز يحمل
            # الرقم الأكاديمي — الربط بينهما في خريطة get_academic_map.
            mark_fp_enrolled(sid or academic,
                             devices[0].get("device_id", ""), finger)
            res["name_en"] = res.get("name_on_device") or name_en
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/web/api/biometric/unenroll-fp", response_class=JSONResponse)
async def bio_unenroll_fp(request: Request):
    if not _auth(request):
        return _unauth()
    try:
        d = await request.json()
        unmark_fp_enrolled(str(d.get("student_id", "")).strip())
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/web/api/biometric/sync-device", response_class=JSONResponse)
async def bio_sync_device(request: Request):
    """
    يتصل بجهاز البصمة ويسحب قائمة المستخدمين وقوالب البصمة المسجلة فعلياً
    ويُطابقها مع الطلاب في النظام ويُحدّث قاعدة البيانات مباشرة.
    """
    if not _auth(request):
        return _unauth()
    try:
        cfg = load_config()
        devices = [x for x in (cfg.get("biometric_devices") or [])
                   if x.get("enabled", True)]
        if not devices:
            if debug_on():
                devices = [{"protocol": "mock", "device_id": "mock"}]
            else:
                return JSONResponse(
                    {"ok": False,
                     "error": "لا يوجد جهاز مُفعّل — أضِفه واحفظه أولاً"})

        from biometric import make_device
        dev = make_device(devices[0])
        device_id = devices[0].get("device_id", "")

        if hasattr(dev, "get_users_and_fingerprints"):
            users_map, fp_user_ids = dev.get_users_and_fingerprints()
        else:
            users_map, fp_user_ids = {}, set()

        synced_count = sync_fp_enrollments_from_device(fp_user_ids, device_id=device_id)

        return JSONResponse({
            "ok": True,
            "device_users_count": len(users_map),
            "device_fp_count": len(fp_user_ids),
            "synced_count": synced_count
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/web/api/biometric/bulk-upload", response_class=JSONResponse)
async def bio_bulk_upload(request: Request):
    """
    يرفع جميع الطلاب المسجلين (أرقامهم الأكاديمية + أسماءهم بالإنجليزي)
    إلى جهاز البصمة دفعة واحدة ليكونوا جاهزين للتبصيم السريع.
    """
    if not _auth(request):
        return _unauth()
    try:
        cfg = load_config()
        devices = [x for x in (cfg.get("biometric_devices") or [])
                   if x.get("enabled", True)]
        if not devices:
            return JSONResponse(
                {"ok": False, "error": "لا يوجد جهاز مُفعّل — أضِفه واحفظه أولاً"})

        store = load_students()
        students_to_upload = []
        for c in store.get("list", []):
            for s in c.get("students", []):
                an = str(s.get("academic_no") or "").strip()
                if an:
                    students_to_upload.append({
                        "academic_no": an,
                        "name": s.get("name", "")
                    })

        if not students_to_upload:
            return JSONResponse(
                {"ok": False, "error": "لا يوجد طلاب لديهم أرقام أكاديمية — ولّد الأرقام أولاً"})

        from biometric import make_device
        dev = make_device(devices[0])

        if hasattr(dev, "bulk_upload_students"):
            success_count, fail_count = dev.bulk_upload_students(students_to_upload)
        else:
            success_count, fail_count = len(students_to_upload), 0

        return JSONResponse({
            "ok": True,
            "total": len(students_to_upload),
            "success": success_count,
            "failed": fail_count
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── أداة اختبار (وضع التطوير فقط) ─────────────────────────────────
@router.post("/web/api/biometric/mock-seed", response_class=JSONResponse)
async def bio_mock_seed(request: Request):
    if not _auth(request):
        return _unauth()
    if not debug_on():
        return JSONResponse({"ok": False, "error": "متاح في وضع التطوير فقط"},
                            status_code=404)
    try:
        d = await request.json()
        from biometric.mock_device import MockDevice
        from database import (insert_biometric_punch, get_biometric_enrollments,
                              get_student_map)
        import datetime
        mock = MockDevice({"device_id": "mock"})
        count = mock.seed_from_students(
            count=int(d.get("count") or 8),
            base_time=d.get("time") or "07:12")
        enr = get_biometric_enrollments()
        smap = get_student_map()
        stored = 0
        for p in mock.read_punches():
            uid = p["uid"]
            matched = (uid in enr) or (uid in smap)
            sid = uid if uid in smap else (
                enr[uid]["student_id"] if uid in enr else "")
            ld = datetime.datetime.fromisoformat(
                p["punch_local"]).date().isoformat()
            if insert_biometric_punch("mock", uid, p["punch_utc"],
                                      p["punch_local"], ld, sid,
                                      1 if matched else 0):
                stored += 1
        return JSONResponse({"ok": True, "seeded": count, "stored": stored})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ══════════════════════════════════════════════════════════════════
#  صفحة التحكّم — HTML مستقلّ بلا اعتماديات خارجية
# ══════════════════════════════════════════════════════════════════
_PAGE = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ربط جهاز البصمة — درب الطلاب</title>
<style>
  :root{--navy:#0C2E56;--navy2:#123C6E;--blue:#1565C0;--org:#F07A16;
    --ok:#16a34a;--warn:#d97706;--err:#dc2626;--mu:#5D7391;--line:#E2EAF4;--bg:#F5F8FC;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:Tahoma,Arial,sans-serif;background:var(--bg);color:#12233B;padding:22px;}
  a{color:var(--blue);text-decoration:none}
  .top{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap;gap:10px}
  h1{font-size:22px;color:var(--navy)}
  h1 small{display:block;font-size:13px;color:var(--mu);font-weight:normal;margin-top:4px}
  .back{font-size:13px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}
  @media(max-width:900px){.grid{grid-template-columns:1fr}}
  .card{background:#fff;border:1px solid var(--line);border-radius:13px;padding:16px 17px;margin-bottom:16px}
  .card h2{font-size:16px;color:var(--navy);margin-bottom:4px}
  .card p.d{font-size:12.5px;color:var(--mu);margin-bottom:12px}
  .row{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-bottom:9px}
  label{font-size:13px;color:#33475F;min-width:96px}
  input,select{font-family:inherit;font-size:14px;padding:8px 10px;border:1px solid #cfd9e6;border-radius:8px;background:#fff}
  input[type=text],input[type=number]{width:150px}
  .btn{font-family:inherit;font-size:14px;font-weight:700;border:none;border-radius:8px;padding:9px 18px;cursor:pointer;color:#fff;background:var(--blue)}
  .btn.g{background:var(--navy)}
  .btn.o{background:var(--org)}
  .btn.sm{padding:6px 12px;font-size:12.5px}
  .btn.gh{background:#eef3fb;color:var(--navy)}
  .btn:disabled{opacity:.5;cursor:default}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:6px}
  .kpi{background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:10px 6px;text-align:center}
  .kpi u{display:block;font-size:22px;font-weight:700;text-decoration:none}
  .kpi span{font-size:11px;color:var(--mu)}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-inline-start:6px;vertical-align:middle}
  .dot.on{background:var(--ok)}.dot.off{background:#94a3b8}.dot.er{background:var(--err)}
  table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:8px}
  th{background:var(--navy);color:#fff;padding:7px 6px;font-weight:700}
  td{padding:6px;border-top:1px solid #EDF2F8;text-align:center}
  tr:nth-child(even) td{background:#FAFCFE}
  .pill{display:inline-block;padding:2px 9px;border-radius:20px;font-size:10.5px;font-weight:700}
  .pill.t{background:#FFF0DE;color:#B8620B}.pill.p{background:#E4F6EA;color:#1B7C3D}
  .pill.n{background:#FDE7E7;color:#C0392B}.pill.x{background:#E8F0FB;color:#1565C0}
  .msg{font-size:12.5px;padding:8px 11px;border-radius:8px;margin-top:8px;display:none}
  .msg.ok{background:#E4F6EA;color:#1B7C3D;display:block}
  .msg.er{background:#FDE7E7;color:#C0392B;display:block}
  .devbox{border:1px solid var(--line);border-radius:10px;padding:11px;margin-bottom:10px;background:#FbFdff}
  .muted{color:var(--mu);font-size:12px}
  .switch{display:flex;align-items:center;gap:8px}
</style></head><body>
<div class="top">
  <h1>ربط جهاز البصمة عند البوابة<small>الطالب يبصم عند دخوله، فيُسجَّل تأخره ويصل إشعار وليّ الأمر تلقائياً</small></h1>
  <div style="display:flex;gap:10px;align-items:center">
    <a class="btn o sm" href="/web/biometric/enroll" style="text-decoration:none">👆 تسجيل بصمات الطلاب</a>
    <a class="back" href="/web/dashboard">← الرجوع للوحة</a>
  </div>
</div>

<div class="card">
  <div class="kpis">
    <div class="kpi"><u id="k-punch" style="color:#1565C0">—</u><span>بصمات اليوم</span></div>
    <div class="kpi"><u id="k-tardy" style="color:#B8620B">—</u><span>تأخر</span></div>
    <div class="kpi"><u id="k-present" style="color:#1B7C3D">—</u><span>حاضر بالوقت</span></div>
    <div class="kpi"><u id="k-unmatched" style="color:#C0392B">—</u><span>بلا مطابقة</span></div>
  </div>
  <div class="row" style="margin-top:10px">
    <span id="poll-dot" class="dot off"></span>
    <span id="poll-txt" class="muted">الخيط: —</span>
    <span style="flex:1"></span>
    <button class="btn o sm" onclick="runNow()">↻ سحب ومعالجة الآن</button>
  </div>
  <div id="dev-status" class="muted" style="margin-top:6px"></div>
</div>

<div class="grid">
  <div>
    <div class="card">
      <h2>الإعدادات</h2>
      <p class="d">وقت بداية الدوام يُقرأ من إعدادات المدرسة. أي بصمة بعده (زائد دقائق السماح) تُحتسب تأخراً.</p>
      <div class="row"><label>تفعيل الربط</label>
        <div class="switch"><input type="checkbox" id="c-enabled"><span class="muted">تشغيل السحب التلقائي كل ١٠ ثوانٍ</span></div></div>
      <div class="row"><label>الوضع</label>
        <select id="c-mode">
          <option value="tardiness">تسجيل المتأخرين فقط</option>
          <option value="attendance">تسجيل الحضور كاملاً</option>
        </select></div>
      <div class="row"><label>دقائق السماح</label>
        <input type="number" id="c-grace" min="0" value="0" style="width:80px">
        <span class="muted">تُضاف لوقت بداية الدوام قبل احتساب التأخر</span></div>
      <div class="row"><label>إشعار وليّ الأمر</label>
        <div class="switch"><input type="checkbox" id="c-notify" checked><span class="muted">إرسال واتساب فور تسجيل التأخر</span></div></div>
      <div class="row"><label>بداية الدوام</label><span id="c-start" class="muted">—</span></div>
      <button class="btn g" onclick="saveConfig()">حفظ الإعدادات</button>
      <div id="cfg-msg" class="msg"></div>
    </div>

    <div class="card">
      <h2>الأجهزة</h2>
      <p class="d">جهاز البصمة يجلس على شبكة المدرسة. أدخِل عنوانه أو ابحث عنه، ثم افحص الاتصال قبل الحفظ.</p>
      <button class="btn gh sm" onclick="scan()">🔍 بحث في الشبكة</button>
      <span id="scan-msg" class="muted"></span>
      <div id="devlist" style="margin-top:11px"></div>
      <button class="btn gh sm" onclick="addDevice()">+ إضافة جهاز يدوياً</button>
    </div>
  </div>

  <div>
    <div class="card">
      <h2>الربط اليدوي <span class="muted" style="font-weight:normal">(اختياري)</span></h2>
      <p class="d">الأصل أن يُسجَّل الطالب في الجهاز برقمه الأكاديمي، فيُطابَق تلقائياً. استعمل هذا الجدول فقط إن كان الجهاز يُرقّم تسلسلياً (١،٢،٣).</p>
      <div class="row">
        <input type="text" id="en-uid" placeholder="رقم الجهاز">
        <input type="text" id="en-sid" placeholder="رقم الطالب">
        <button class="btn sm" onclick="enroll()">ربط</button>
      </div>
      <div id="en-msg" class="msg"></div>
      <div id="entable"></div>
    </div>

    <div class="card">
      <h2>السجلّ الحيّ — بصمات اليوم</h2>
      <p class="d">آخر البصمات كما وردت من الجهاز، ونتيجة معالجتها.</p>
      <div id="devonly" style="display:none;margin-bottom:8px">
        <button class="btn gh sm" onclick="mockSeed()">🧪 حقن بصمات تجريبية</button>
        <span class="muted">وضع التطوير — يولّد بصمات من طلاب المدرسة</span>
      </div>
      <div id="punches"><p class="muted">—</p></div>
    </div>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
async function api(path,opts){
  const r=await fetch(path,opts||{});
  if(r.status===401){location.href='/web/login';return null;}
  return r.json();
}
let DEVICES=[];

async function loadStatus(){
  const d=await api('/web/api/biometric/status'); if(!d||!d.ok)return;
  const s=d.summary||{};
  $('k-punch').textContent=s.punches||0;
  $('k-tardy').textContent=s.tardy||0;
  $('k-present').textContent=s.present||0;
  $('k-unmatched').textContent=s.unmatched||0;
  const p=d.poller||{};
  const dot=$('poll-dot'), txt=$('poll-txt');
  if(!d.enabled){dot.className='dot off';txt.textContent='الخيط: متوقف (الربط غير مفعّل)';}
  else if(p.last_error){dot.className='dot er';txt.textContent='الخيط: خطأ — '+p.last_error;}
  else{dot.className='dot on';txt.textContent='الخيط: يعمل'+(p.last_run?' · آخر دورة '+p.last_run.slice(11,19):'');}
  const ds=(p.devices||[]).map(x=>x.ok?('✅ '+x.device_id+(x.new?(' +'+x.new):'')):('❌ '+x.device_id+' — '+x.error)).join('  ·  ');
  $('dev-status').textContent=ds;
}
async function loadConfig(){
  const d=await api('/web/api/biometric/config'); if(!d||!d.ok)return;
  $('c-enabled').checked=d.enabled;
  $('c-mode').value=d.mode;
  $('c-grace').value=d.grace_min;
  $('c-notify').checked=d.notify_parent;
  $('c-start').textContent=d.school_start_time;
  DEVICES=d.devices||[]; renderDevices();
}
function renderDevices(){
  const box=$('devlist');
  if(!DEVICES.length){box.innerHTML='<p class="muted">لا أجهزة بعد.</p>';return;}
  box.innerHTML=DEVICES.map((v,i)=>`<div class="devbox">
    <div class="row"><label>المعرّف</label><input type="text" value="${v.device_id||''}" onchange="upd(${i},'device_id',this.value)" style="width:110px">
      <label style="min-width:40px">IP</label><input type="text" value="${v.ip||''}" onchange="upd(${i},'ip',this.value)"></div>
    <div class="row"><label>المنفذ</label><input type="number" value="${v.port||4370}" onchange="upd(${i},'port',this.value)" style="width:80px">
      <label style="min-width:70px">رمز الاتصال</label><input type="number" value="${v.comm_key||0}" onchange="upd(${i},'comm_key',this.value)" style="width:80px"></div>
    <div class="row">
      <label>مفعّل</label><input type="checkbox" ${v.enabled!==false?'checked':''} onchange="upd(${i},'enabled',this.checked)">
      <span style="flex:1"></span>
      <button class="btn gh sm" onclick="testDev(${i})">فحص الاتصال</button>
      <button class="btn gh sm" onclick="delDev(${i})" style="color:#c0392b">حذف</button>
    </div>
    <div class="muted" id="dt-${i}"></div>
  </div>`).join('');
}
function upd(i,k,v){DEVICES[i][k]=(k==='port'||k==='comm_key')?parseInt(v||0):v;}
function addDevice(){DEVICES.push({device_id:'gate'+(DEVICES.length+1),protocol:'zk',ip:'',port:4370,comm_key:0,enabled:true});renderDevices();}
function delDev(i){DEVICES.splice(i,1);renderDevices();}
async function testDev(i){
  const el=$('dt-'+i); el.textContent='جارٍ الفحص...';
  const d=await api('/web/api/biometric/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(DEVICES[i])});
  if(d&&d.ok){const n=d.info||{};el.textContent='✅ '+(n.name||'جهاز')+' · '+(n.serial||'')+' · '+(n.firmware||'');}
  else{el.textContent='❌ '+((d&&d.error)||'تعذّر الاتصال');}
}
async function saveConfig(){
  const body={enabled:$('c-enabled').checked,mode:$('c-mode').value,
    grace_min:parseInt($('c-grace').value||0),notify_parent:$('c-notify').checked,devices:DEVICES};
  const d=await api('/web/api/biometric/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const m=$('cfg-msg');
  if(d&&d.ok){m.className='msg ok';m.textContent='تم الحفظ.';loadStatus();}
  else{m.className='msg er';m.textContent='تعذّر الحفظ: '+((d&&d.error)||'');}
}
async function scan(){
  $('scan-msg').textContent='جارٍ البحث في الشبكة...';
  const d=await api('/web/api/biometric/scan',{method:'POST'});
  if(!d||!d.ok){$('scan-msg').textContent='تعذّر البحث';return;}
  if(!d.found.length){$('scan-msg').textContent='لم يُعثر على جهاز على المنفذ 4370';return;}
  $('scan-msg').textContent='وُجد: '+d.found.join('، ');
  d.found.forEach(ip=>{if(!DEVICES.some(v=>v.ip===ip))DEVICES.push({device_id:'gate'+(DEVICES.length+1),protocol:'zk',ip:ip,port:4370,comm_key:0,enabled:true});});
  renderDevices();
}
async function runNow(){
  const d=await api('/web/api/biometric/run',{method:'POST'});
  if(d&&d.ok){await loadStatus();await loadPunches();}
}
async function loadEnroll(){
  const d=await api('/web/api/biometric/enrollments'); if(!d||!d.ok)return;
  const box=$('entable');
  if(!d.rows.length){box.innerHTML='';return;}
  box.innerHTML='<table><tr><th>رقم الجهاز</th><th>الطالب</th><th>الفصل</th><th></th></tr>'+
    d.rows.map(r=>`<tr><td>${r.device_uid}</td><td>${r.student_name||r.student_id}</td><td>${r.class_name||'-'}</td>
    <td><button class="btn gh sm" onclick="unenroll('${r.device_uid}')">حذف</button></td></tr>`).join('')+'</table>';
}
async function enroll(){
  const uid=$('en-uid').value.trim(),sid=$('en-sid').value.trim();
  const d=await api('/web/api/biometric/enroll',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_uid:uid,student_id:sid})});
  const m=$('en-msg');
  if(d&&d.ok){m.className='msg ok';m.textContent=d.matched?'تم الربط.':'تم الربط — تنبيه: لا يوجد طالب بهذا الرقم.';$('en-uid').value='';$('en-sid').value='';loadEnroll();}
  else{m.className='msg er';m.textContent=(d&&d.error)||'تعذّر';}
}
async function unenroll(uid){
  await api('/web/api/biometric/unenroll',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_uid:uid})});
  loadEnroll();
}
async function loadPunches(){
  const d=await api('/web/api/biometric/punches'); if(!d||!d.ok)return;
  const box=$('punches');
  if(!d.rows.length){box.innerHTML='<p class="muted">لا بصمات اليوم بعد.</p>';return;}
  const cls={'حاضر':'p','مكرر':'x','مستثنى':'x','لا مطابقة':'n'};
  box.innerHTML='<table><tr><th>الوقت</th><th>رقم الجهاز</th><th>الطالب</th><th>النتيجة</th></tr>'+
    d.rows.map(r=>{let o=r.outcome||'—';let c=o.indexOf('تأخر')===0?'t':(cls[o]||'x');
      let t=(r.punch_local||'').slice(11,19);
      return `<tr><td>${t}</td><td>${r.device_uid}</td><td>${r.student_id||'—'}</td><td><span class="pill ${c}">${o}</span></td></tr>`;}).join('')+'</table>';
}
async function mockSeed(){
  const d=await api('/web/api/biometric/mock-seed',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:8,time:'07:12'})});
  if(d&&d.ok){await runNow();}
}
async function refreshAll(){await loadStatus();await loadPunches();await loadEnroll();}
window.onload=async function(){
  await loadConfig();await refreshAll();
  const t=await api('/web/api/biometric/mock-seed',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:0})});
  if(t&&(t.ok!==false||(t.error&&t.error.indexOf('التطوير')<0)))$('devonly').style.display='block';
  setInterval(loadStatus,8000);
};
</script>
</body></html>"""


# ── صفحة الويب لتسجيل البصمات الحية ──────────────────────────────
_ENROLL_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>تسجيل بصمات الطلاب</title>
<style>
  :root{--navy:#0C2E56;--org:#FF6F00;--bg:#F8FAFC;--card:#fff;--mu:#64748b;--blue:#1565C0;--g:#16A34A}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:Segoe UI,Tahoma,Arial,sans-serif;background:var(--bg);color:#1E293B;padding:24px 30px}
  .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:12px}
  .top h1{font-size:22px;color:var(--navy);font-weight:800}
  .top h1 small{display:block;font-size:13px;color:var(--mu);font-weight:400;margin-top:2px}
  .top a{color:var(--navy);text-decoration:none;font-weight:700;font-size:14px}
  .bar{display:flex;gap:12px;align-items:center;background:var(--card);padding:14px 18px;border-radius:12px;border:1px solid #E2E8F0;margin-bottom:20px;flex-wrap:wrap}
  .search{padding:8px 14px;border:1px solid #CBD5E1;border-radius:8px;font-size:13.5px;min-width:260px}
  .prog{flex:1;min-width:200px;display:flex;flex-direction:column;gap:4px}
  .track{background:#E2E8F0;height:8px;border-radius:4px;overflow:hidden}
  .fill{background:var(--g);height:100%;width:0;transition:width .3s}
  .lbl{font-size:12px;color:var(--mu);font-weight:600}
  .cls{background:var(--card);border:1px solid #E2E8F0;border-radius:12px;margin-bottom:14px;overflow:hidden}
  .clshead{background:#F1F5F9;padding:12px 18px;display:flex;justify-content:space-between;align-items:center;cursor:pointer;user-select:none}
  .clshead b{color:var(--navy);font-size:15px}
  .clshead .c{font-size:13px;color:var(--mu);font-weight:600}
  .clsbody{padding:10px 18px;display:none}
  .clsbody.open{display:block}
  .stu{display:flex;align-items:center;gap:14px;padding:9px 0;border-bottom:1px solid #F1F5F9}
  .stu:last-child{border-bottom:none}
  .stu .nm{flex:1;font-size:14px;font-weight:600}
  .stu .id{font-size:12px;color:var(--mu);margin-right:8px}
  .st{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11.5px;font-weight:700}
  .st.en{background:#E4F6EA;color:#1B7C3D}
  .st.no{background:#F1F5F9;color:#64748b}
  .btn{font-family:inherit;font-size:13px;font-weight:700;border:none;border-radius:8px;padding:8px 15px;cursor:pointer;color:#fff;background:var(--blue);display:inline-flex;align-items:center;gap:6px}
  .btn.g{background:var(--g)}.btn.gh{background:#eef3fb;color:var(--navy)}.btn.o{background:var(--org)}
  .btn.sm{padding:4px 10px;font-size:12px}
  .btn:disabled{opacity:.5;cursor:not-allowed}
  .modal{position:fixed;inset:0;background:rgba(12,46,86,.6);display:none;align-items:center;justify-content:center;z-index:999}
  .modal.show{display:flex}
  .box{background:#fff;border-radius:16px;padding:24px 28px;text-align:center;max-width:440px;width:92%;box-shadow:0 20px 25px -5px rgba(0,0,0,.2)}
  .box .ic{font-size:48px;margin-bottom:10px}
  .box h3{font-size:18px;color:var(--navy);margin-bottom:6px}
  .box p{font-size:14px;color:#33475F;line-height:1.6;margin-bottom:14px}
  .box .who{font-weight:700;color:var(--org)}
  .box .btns{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}
  .pulse{display:inline-block;width:20px;height:20px;border-radius:50%;background:var(--org);animation:p 1s infinite}
  @keyframes p{0%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(1.4)}100%{opacity:1;transform:scale(1)}}
  .muted{color:var(--mu);font-size:12.5px}
  @media print {
    body{background:#fff;padding:0}
    .top button, .top a, .bar, .btn, .modal{display:none !important}
    .clsbody{display:block !important}
    .cls{border:none;border-bottom:2px solid #000;break-inside:avoid}
  }
</style></head><body>
<div class="top">
  <h1>تسجيل بصمات الطلاب<small>اختر الطالب واضغط «سجّل بصمة» — يدخل الجهاز وضع الالتقاط، فيضع الطالب إصبعه</small></h1>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <button class="btn gh" id="bulkbtn" onclick="bulkUploadToDevice()" title="رفع أسماء وأرقام جميع طلاب المدرسة لجهاز البصمة مسبقاً">📤 رفع الأسماء للجهاز</button>
    <button class="btn gh" id="syncbtn" onclick="syncFromDevice()" title="مزامنة حية من جهاز البصمة للتعرف على الطلاب المسجلين فعلياً ومعالجة أي تعارض">🔄 مزامنة من الجهاز</button>
    <button class="btn gh" onclick="genNumbers()" title="يولّد رقماً أكاديمياً قصيراً لمن لا يملكه — آمن للتكرار">🔢 <span id="genlbl">الأرقام الأكاديمية</span></button>
    <button class="btn gh" onclick="window.print()" title="طباعة كشف مسير التبصيم للفصول">🖨️ طباعة الكشوف</button>
    <a href="/web/biometric">← إعدادات الجهاز</a>
  </div>
</div>

<div class="bar">
  <div class="prog">
    <div class="track"><div class="fill" id="pfill"></div></div>
    <div class="lbl" id="plbl">—</div>
  </div>
  <input class="search" id="search" placeholder="🔍 ابحث باسم الطالب" oninput="filter()">
  <label class="muted"><input type="checkbox" id="hideEn" onchange="filter()"> إخفاء المسجّلين</label>
</div>

<div class="bar" id="numbar" style="display:none;background:#FFF7ED;border-color:#FED7AA">
  <span style="flex:1;font-size:13px;color:#9A3412"><b id="nonum">0</b> طالباً بلا رقم أكاديمي — رقم الهوية (١٠ خانات) لا يقبله الجهاز (٩). ولّد أرقاماً قصيرة مُهيكلة بالفصل أولاً.</span>
  <button class="btn o" onclick="genNumbers()">توليد الأرقام الأكاديمية</button>
</div>

<div id="list"><p class="muted">جارٍ التحميل...</p></div>

<div class="modal" id="modal">
  <div class="box">
    <div id="m-badge" style="background:#E0F2FE;color:#0369A1;font-size:12px;font-weight:bold;padding:4px 12px;border-radius:12px;display:inline-block;margin-bottom:10px">طالب</div>
    <div class="ic" id="m-ic">👆</div>
    <h3 id="m-title">ضع إصبع الطالب على الجهاز</h3>
    <p id="m-body">الطالب: <span class="who" id="m-who"></span></p>

    <div id="m-next-box" style="display:none;background:#F8FAFC;border:1px dashed #CBD5E1;border-radius:10px;padding:8px 12px;margin-bottom:16px;text-align:right;font-size:13px;color:#475569">
      ⏭️ <b>التالي في الطابور:</b> <span id="m-next-name" style="color:#0F172A;font-weight:bold"></span>
    </div>

    <div class="btns" id="m-btns">
      <button class="btn g" id="m-btn-done" onclick="nextInQueue(false)" style="min-width:140px">✅ تمّ والتالي (Enter ↵)</button>
      <button class="btn gh" onclick="nextInQueue(true)" title="تخطي هذا الطالب والانتقال للذي يليه">⏭️ تخطي</button>
      <button class="btn gh" onclick="stopQueue()" style="color:#DC2626">🛑 إغلاق (Esc)</button>
    </div>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
async function api(path,opts){
  try {
    const r=await fetch(path,opts||{});
    if(r.status===401){location.href='/web/login';return null;}
    return await r.json();
  } catch(e) {
    return {ok:false, error:String(e)};
  }
}

let DATA={classes:[],total:0,done:0};
let QUEUE=[], QUEUE_INDEX=0, QUEUE_CLASS_NAME='', IS_BUSY=false;

async function load(){
  const d=await api('/web/api/biometric/students');
  if(!d||!d.ok) return;
  DATA=d;
  render();
  updateProg();
  const nn=d.without_number||0;
  $('numbar').style.display=nn?'flex':'none';
  $('nonum').textContent=nn;
  $('genlbl').textContent = nn ? ('توليد الأرقام ('+nn+' بلا رقم)')
                               : ('الأرقام جاهزة ('+d.total+')');
}

async function bulkUploadToDevice(){
  if(!confirm('هل تريد رفع جميع أسماء وأرقام طلاب المدرسة إلى جهاز البصمة مسبقاً؟\\n\\nستتم تهيئة الجهاز بكل الطلاب وتسهيل تسجيل البصمات.')) return;
  const btn=$('bulkbtn');
  const old=btn.innerHTML;
  btn.disabled=true;
  btn.innerHTML='⏳ جارٍ الرفع للجهاز...';
  try{
    const d=await api('/web/api/biometric/bulk-upload',{method:'POST'});
    if(d&&d.ok){
      alert('✅ تم رفع '+d.success+' طالب بنجاح إلى جهاز البصمة!\\n• الإجمالي: '+d.total+'\\n• الناجح: '+d.success+'\\n• المتعثر: '+(d.failed||0));
    }else{
      alert('❌ تعذّر الرفع للجهاز: '+((d&&d.error)||'تحقق من اتصال الجهاز'));
    }
  }catch(e){
    alert('❌ خطأ: '+e);
  }finally{
    btn.disabled=false;
    btn.innerHTML=old;
  }
}

async function syncFromDevice(){
  const btn=$('syncbtn');
  const old=btn.innerHTML;
  btn.disabled=true;
  btn.innerHTML='⏳ جارٍ فحص الجهاز ومزامنته...';
  try{
    const d=await api('/web/api/biometric/sync-device',{method:'POST'});
    if(d&&d.ok){
      await load();
      alert('✅ تمت المزامنة الحية مع جهاز البصمة بنجاح!\\n\\n'
            + '• إجمالي المستخدمين على الجهاز: ' + (d.device_users_count || 0) + '\\n'
            + '• البصمات المسجلة فعلياً في الجهاز: ' + (d.device_fp_count || 0) + '\\n'
            + '• الطلاب الذين تم مطابقتهم وتحديث حالتهم: ' + (d.synced_count || 0));
    }else{
      alert('❌ تعذّرت المزامنة: '+((d&&d.error)||'تأكد من تشغيل الجهاز واتصاله بالشبكة.'));
    }
  }catch(e){
    alert('❌ خطأ أثناء المزامنة: '+e);
  }finally{
    btn.disabled=false;
    btn.innerHTML=old;
  }
}

async function genNumbers(){
  const d=await api('/web/api/biometric/generate-numbers',{method:'POST'});
  if(d&&d.ok){
    await load();
    alert(d.assigned ? ('تم توليد '+d.assigned+' رقماً جديداً.')
                     : 'كل الطلاب لديهم أرقام بالفعل — لا جديد.');
  } else { alert('تعذّر التوليد: '+((d&&d.error)||'')); }
}

function updateProg(){
  const pct=DATA.total?Math.round(DATA.done/DATA.total*100):0;
  $('pfill').style.width=pct+'%';
  $('plbl').textContent='سُجّل '+DATA.done+' من '+DATA.total+' طالب ('+pct+'%)';
}

function render(){
  const q=$('search').value.trim(), hide=$('hideEn').checked;
  const box=$('list');
  let html='';
  if(!DATA.classes || !DATA.classes.length){
    box.innerHTML='<p class="muted">لا توجد فصول أو طلاب مسجلين.</p>';
    return;
  }
  DATA.classes.forEach((c,ci)=>{
    let studs=(c.students||[]).filter(s=>(!q||(s.name||'').includes(q))&&(!hide||!s.enrolled));
    if(!studs.length) return;
    html += '<div class="cls"><div class="clshead" onclick="tog(' + ci + ')">'
          + '<b>' + escapeHtml(c.name) + '</b>'
          + '<div style="display:flex;align-items:center;gap:10px">'
          + '<button class="btn sm gh" onclick="event.stopPropagation(); startClassEnroll(' + ci + ')" title="بدء تسجيل طلاب هذا الفصل تلقائياً">⚡ تسجيل الفصل سريعاً</button>'
          + '<span class="c">' + c.done + '/' + c.total + ' مسجّل</span>'
          + '</div></div>'
          + '<div class="clsbody ' + (q?'open':'') + '" id="cb-' + ci + '">';

    (c.students||[]).forEach((s,si)=>{
      if((q && !(s.name||'').includes(q)) || (hide && s.enrolled)) return;
      const an = s.academic_no || '';
      html += '<div class="stu">'
            + '<span class="st ' + (s.enrolled?'en':'no') + '">' + (s.enrolled?'مسجّل':'—') + '</span>'
            + '<span class="nm">' + escapeHtml(s.name) + ' <span class="id">' + (an?('رقم '+escapeHtml(an)):'(بلا رقم)') + '</span></span>';
      if(!an){
        html += '<button class="btn gh" disabled title="ولّد الأرقام أولاً">بلا رقم</button>';
      } else if(s.enrolled){
        html += '<button class="btn gh" onclick="enrollStudentByIndices(' + ci + ',' + si + ')">إعادة</button>';
      } else {
        html += '<button class="btn" onclick="enrollStudentByIndices(' + ci + ',' + si + ')">سجّل بصمة</button>';
      }
      html += '</div>';
    });
    html += '</div></div>';
  });
  box.innerHTML=html||'<p class="muted">لا نتائج مطابقة للبحث.</p>';
}

function escapeHtml(str){
  if(!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}

function tog(ci){
  const el=$('cb-'+ci);
  if(el) el.classList.toggle('open');
}

function filter(){render();}

function startClassEnroll(ci){
  const c=DATA.classes[ci];
  if(!c||!c.students||!c.students.length) return;
  const el=$('cb-'+ci);
  if(el) el.classList.add('open');
  QUEUE = c.students.filter(s => !s.enrolled && s.academic_no);
  if(!QUEUE.length){
    alert('✅ جميع طلاب فصل ('+c.name+') مسجلين بالفعل!');
    return;
  }
  QUEUE_INDEX = 0;
  QUEUE_CLASS_NAME = c.name;
  runQueueStudent();
}

function enrollStudentByIndices(ci, si){
  const c = DATA.classes[ci];
  if(!c || !c.students || !c.students[si]) return;
  const s = c.students[si];
  QUEUE = [{id: s.id, academic_no: s.academic_no, name: s.name, enrolled: s.enrolled}];
  QUEUE_INDEX = 0;
  QUEUE_CLASS_NAME = c.name || '';
  runQueueStudent();
}

async function runQueueStudent(){
  if(QUEUE_INDEX >= QUEUE.length){
    $('modal').classList.remove('show');
    await load();
    if(QUEUE.length > 1){
      alert('🎉 تم الانتهاء من تسجيل طلاب ' + QUEUE_CLASS_NAME + '!');
    }
    return;
  }

  const s = QUEUE[QUEUE_INDEX];
  const nextS = (QUEUE_INDEX + 1 < QUEUE.length) ? QUEUE[QUEUE_INDEX + 1] : null;

  $('m-badge').textContent = (QUEUE.length > 1)
    ? ('طالب (' + (QUEUE_INDEX + 1) + ' من ' + QUEUE.length + ') — ' + QUEUE_CLASS_NAME)
    : ('تسجيل طالب — ' + QUEUE_CLASS_NAME);

  $('m-who').textContent = s.name + ' — رقم ' + s.academic_no;
  $('m-ic').innerHTML = '<span class="pulse"></span>';
  $('m-title').textContent = '👆 ضع إصبع الطالب على الجهاز الآن';
  $('m-body').innerHTML = 'الطالب: <span class="who">' + escapeHtml(s.name) + ' — رقم ' + escapeHtml(s.academic_no) + '</span><br><span style="color:#2563EB">جارٍ الاتصال بالجهاز والالتقاط (3 مرات)...</span>';

  if(nextS){
    $('m-next-box').style.display = 'block';
    $('m-next-name').textContent = nextS.name + ' (رقم ' + nextS.academic_no + ')';
  } else {
    $('m-next-box').style.display = 'none';
  }

  $('modal').classList.add('show');
  IS_BUSY = true;

  try {
    await new Promise(r => setTimeout(r, 200));

    const d = await api('/web/api/biometric/enroll-live', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        student_id: s.id,
        academic_no: s.academic_no,
        student_name: s.name
      })
    });

    if(d && d.ok){
      $('m-ic').textContent = '✅';
      $('m-title').textContent = 'تم تسجيل البصمة بنجاح!';
      const nameEn = d.name_en ? (' <span style="color:#1565C0;font-size:12px">(' + escapeHtml(d.name_en) + ')</span>') : '';
      $('m-body').innerHTML = 'الطالب: <span class="who">' + escapeHtml(s.name) + '</span>' + nameEn + '<br><b style="color:#16A34A">اضغط Enter ↵ أو «تمّ والتالي» للبدء مع الطالب القادم.</b>';
    } else {
      $('m-ic').textContent = '⚠️';
      $('m-title').textContent = 'تعذّر بدء الالتقاط';
      $('m-body').textContent = (d && d.error) || 'خطأ في الاتصال بالجهاز';
    }
  } catch(err) {
    $('m-ic').textContent = '⚠️';
    $('m-title').textContent = 'خطأ';
    $('m-body').textContent = String(err);
  } finally {
    IS_BUSY = false;
  }
}

async function nextInQueue(skip){
  if(IS_BUSY) return;

  if(!skip && QUEUE[QUEUE_INDEX]){
    const currId = QUEUE[QUEUE_INDEX].id;
    DATA.classes.forEach(c => {
      (c.students||[]).forEach(st => {
        if(st.id === currId){
          st.enrolled = true;
        }
      });
      c.done = (c.students||[]).filter(st => st.enrolled).length;
    });
    DATA.done = DATA.classes.reduce((sum, c) => sum + c.done, 0);
    render();
    updateProg();
  }

  QUEUE_INDEX++;

  if(QUEUE_INDEX < QUEUE.length){
    runQueueStudent();
  } else {
    $('modal').classList.remove('show');
    await load();
    if(QUEUE.length > 1){
      alert('🎉 تم الانتهاء من تسجيل طلاب ' + QUEUE_CLASS_NAME + '!');
    }
  }
}

function stopQueue(){
  $('modal').classList.remove('show');
  QUEUE = [];
  QUEUE_INDEX = 0;
  load();
}

document.addEventListener('keydown', (e)=>{
  if($('modal').classList.contains('show')){
    if(e.key === 'Enter' || e.key === ' '){
      e.preventDefault();
      if(!IS_BUSY){
        nextInQueue(false);
      }
    } else if(e.key === 'Escape'){
      e.preventDefault();
      stopQueue();
    }
  }
});

window.onload=load;
</script>
</body></html>"""
