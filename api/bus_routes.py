# -*- coding: utf-8 -*-
"""
api/bus_routes.py — نظام إدارة الباصات
  GET  /bus/checkin/{token}                  صفحة السائق (بدون تسجيل دخول)
  POST /bus/checkin/{token}/record           تسجيل حالة طالب (AJAX)
  GET  /web/api/buses                        قائمة الباصات
  POST /web/api/buses                        إضافة باص
  PUT  /web/api/buses/{bus_id}               تعديل باص
  DELETE /web/api/buses/{bus_id}             حذف باص
  POST /web/api/buses/{bus_id}/students      تعيين طلاب
  GET  /web/api/buses/{bus_id}/students      طلاب الباص
  POST /web/api/buses/send-checkin           إرسال رابط للسائق عبر واتساب
  GET  /web/api/buses/trips                  ملخص رحلات اليوم
  GET  /web/api/buses/trip/{trip_id}         تفاصيل رحلة
"""
import datetime
import threading
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from constants import STATIC_DOMAIN, now_riyadh_date
from database import (
    get_all_buses, get_bus, create_bus, update_bus, delete_bus,
    assign_students_to_bus, get_students_in_bus,
    get_or_create_bus_trip, get_bus_trip_by_token,
    get_bus_trip_attendance, record_bus_attendance,
    mark_bus_trip_sent, mark_driver_ready, get_bus_trips_summary,
    load_students, is_school_day,
    add_holiday, remove_holiday, get_holidays, get_db,
)
from whatsapp_service import send_whatsapp_message

router = APIRouter()

# ─── helpers ──────────────────────────────────────────────────────

def _auth(request: Request) -> bool:
    from api.web_routes import _get_current_user
    return bool(_get_current_user(request))

def _today() -> str:
    return now_riyadh_date()

_TRIP_LABELS = {"morning": "الذهاب", "afternoon": "العودة"}

# ══════════════════════════════════════════════════════════════════
#  صفحة السائق (بدون تسجيل دخول — مؤمّنة بالتوكن)
# ══════════════════════════════════════════════════════════════════

@router.get("/bus/checkin/{token}", response_class=HTMLResponse)
async def bus_driver_page(token: str):
    trip = get_bus_trip_by_token(token)
    if not trip:
        return HTMLResponse(_error_page("الرابط غير صحيح أو منتهي الصلاحية"), status_code=404)

    students    = get_bus_trip_attendance(trip["id"])
    boarded     = sum(1 for s in students if s["status"] == "boarded")
    not_boarded = sum(1 for s in students if s["status"] == "not_boarded")
    pending     = sum(1 for s in students if s["status"] == "pending")
    total       = len(students)
    trip_label  = _TRIP_LABELS.get(trip["trip_type"], trip["trip_type"])
    is_afternoon = trip["trip_type"] == "afternoon"
    already_ready = bool(trip.get("driver_ready_at"))

    # ─── بناء قائمة الطلاب ──────────────────────────────────────
    rows_html = ""
    for s in students:
        st = s["status"]
        boarded_cls     = "btn-active-yes" if st == "boarded"     else "btn-yes"
        not_boarded_cls = "btn-active-no"  if st == "not_boarded" else "btn-no"
        rows_html += f"""
        <div class="student-row" id="row-{s['student_id']}">
          <div class="student-info">
            <span class="student-name">{s['student_name']}</span>
            <span class="student-class">{s['class_name']}</span>
          </div>
          <div class="btns">
            <button class="{boarded_cls}"
                    onclick="record('{s['student_id']}','boarded',this)">✅ صعد</button>
            <button class="{not_boarded_cls}"
                    onclick="record('{s['student_id']}','not_boarded',this)">❌ لم يصعد</button>
          </div>
        </div>"""

    # ─── كارد الجاهزية (رحلة الظهر فقط) ─────────────────────────
    if is_afternoon:
        if already_ready:
            ready_time = trip["driver_ready_at"][11:16] if trip["driver_ready_at"] else ""
            ready_section = f"""
        <div class="ready-card ready-done">
          <div class="ready-icon">✅</div>
          <div class="ready-text">
            <strong>تم إبلاغ الإدارة</strong>
            <span>أُرسل الإشعار في الساعة {ready_time}</span>
          </div>
        </div>"""
        else:
            ready_section = f"""
        <div class="ready-card" id="ready-card">
          <div class="ready-icon">🚌</div>
          <div class="ready-text">
            <strong>وصلت إلى المدرسة؟</strong>
            <span>اضغط الزر لإبلاغ الإدارة بجاهزية الباص</span>
          </div>
          <button class="btn-ready" id="btn-ready" onclick="notifyReady()">
            أنا جاهز — أرسل للإدارة
          </button>
        </div>"""
    else:
        ready_section = ""

    progress_pct = f"{(boarded + not_boarded) / total * 100:.1f}" if total else "0"

    html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>تسجيل ركوب الباص — {trip['bus_name']}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Tahoma, Arial, sans-serif; background: #f0f4f8; color: #1a202c; direction: rtl; }}

  .header {{
    background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
    color: #fff; padding: 16px 20px; text-align: center;
  }}
  .header h1 {{ font-size: 1.3rem; margin-bottom: 4px; }}
  .header .sub {{ font-size: 0.85rem; opacity: 0.85; }}

  /* ── كارد الجاهزية ── */
  .ready-card {{
    margin: 12px 12px 0;
    background: #fff;
    border: 2px solid #f59e0b;
    border-radius: 14px;
    padding: 14px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
    box-shadow: 0 2px 8px rgba(245,158,11,0.15);
  }}
  .ready-card.ready-done {{
    border-color: #16a34a;
    background: #f0fdf4;
    box-shadow: 0 2px 8px rgba(22,163,74,0.12);
  }}
  .ready-icon {{ font-size: 2rem; line-height: 1; flex-shrink: 0; }}
  .ready-text {{ flex: 1; display: flex; flex-direction: column; gap: 2px; }}
  .ready-text strong {{ font-size: 1rem; color: #92400e; }}
  .ready-card.ready-done .ready-text strong {{ color: #166534; }}
  .ready-text span {{ font-size: 0.8rem; color: #64748b; }}
  .btn-ready {{
    background: #f59e0b; color: #fff;
    border: none; border-radius: 10px;
    padding: 10px 16px; font-size: 0.85rem;
    font-family: Tahoma, Arial, sans-serif;
    font-weight: bold; cursor: pointer;
    white-space: nowrap; flex-shrink: 0;
    box-shadow: 0 2px 8px rgba(245,158,11,0.4);
    transition: all 0.2s;
  }}
  .btn-ready:active {{ transform: scale(0.95); }}
  .btn-ready:disabled {{ background: #d1d5db; color: #9ca3af; box-shadow: none; cursor: default; }}

  /* ── إحصائيات ── */
  .stats-bar {{
    display: flex; justify-content: center; gap: 12px;
    background: #fff; padding: 12px 16px;
    border-bottom: 1px solid #e2e8f0; margin-top: 12px;
  }}
  .stat {{ text-align: center; }}
  .stat-num {{ font-size: 1.4rem; font-weight: bold; }}
  .stat-lbl {{ font-size: 0.7rem; color: #64748b; }}
  .stat-yes .stat-num {{ color: #16a34a; }}
  .stat-no  .stat-num {{ color: #dc2626; }}
  .stat-pen .stat-num {{ color: #d97706; }}
  .stat-tot .stat-num {{ color: #2563eb; }}

  .progress-bar {{ height: 6px; background: #e2e8f0; }}
  .progress-fill {{
    height: 100%; background: #16a34a;
    transition: width 0.4s ease;
    width: {progress_pct}%;
  }}

  .list {{ padding: 12px; display: flex; flex-direction: column; gap: 10px; }}

  .student-row {{
    background: #fff; border-radius: 12px; padding: 12px 14px;
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08); transition: background 0.2s;
  }}
  .student-row.done-yes {{ background: #f0fdf4; border-right: 4px solid #16a34a; }}
  .student-row.done-no  {{ background: #fef2f2; border-right: 4px solid #dc2626; }}

  .student-info {{ display: flex; flex-direction: column; gap: 2px; }}
  .student-name {{ font-size: 1rem; font-weight: bold; }}
  .student-class {{ font-size: 0.75rem; color: #64748b; }}

  .btns {{ display: flex; gap: 8px; }}
  button {{
    border: none; border-radius: 8px; padding: 8px 14px;
    font-family: Tahoma, Arial, sans-serif; font-size: 0.85rem;
    cursor: pointer; font-weight: bold; transition: all 0.15s; min-width: 80px;
  }}
  .btn-yes        {{ background: #dcfce7; color: #166534; }}
  .btn-no         {{ background: #fee2e2; color: #991b1b; }}
  .btn-active-yes {{ background: #16a34a; color: #fff; box-shadow: 0 2px 6px rgba(22,163,74,0.4); }}
  .btn-active-no  {{ background: #dc2626; color: #fff; box-shadow: 0 2px 6px rgba(220,38,38,0.4); }}
  button:active {{ transform: scale(0.95); }}

  .done-banner {{
    display: none; text-align: center; padding: 16px;
    background: #f0fdf4; color: #166534; font-size: 1rem;
    border-top: 2px solid #16a34a; font-weight: bold;
  }}
  .toast {{
    position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
    background: #1e3a5f; color: #fff; padding: 10px 20px;
    border-radius: 24px; font-size: 0.9rem; opacity: 0;
    transition: opacity 0.3s; pointer-events: none; white-space: nowrap; z-index: 1000;
  }}
  .toast.show {{ opacity: 1; }}
</style>
</head>
<body>

<div class="header">
  <h1>🚌 {trip['bus_name']}</h1>
  <div class="sub">رحلة {trip_label} &nbsp;|&nbsp; {trip['date']} &nbsp;|&nbsp; السائق: {trip['driver_name']}</div>
</div>

{ready_section}

<div class="stats-bar">
  <div class="stat stat-tot">
    <div class="stat-num" id="cnt-total">{total}</div>
    <div class="stat-lbl">إجمالي</div>
  </div>
  <div class="stat stat-yes">
    <div class="stat-num" id="cnt-yes">{boarded}</div>
    <div class="stat-lbl">صعد</div>
  </div>
  <div class="stat stat-no">
    <div class="stat-num" id="cnt-no">{not_boarded}</div>
    <div class="stat-lbl">لم يصعد</div>
  </div>
  <div class="stat stat-pen">
    <div class="stat-num" id="cnt-pen">{pending}</div>
    <div class="stat-lbl">لم يُسجَّل</div>
  </div>
</div>
<div class="progress-bar"><div class="progress-fill" id="progress"></div></div>

<div class="list">{rows_html}</div>
<div class="done-banner" id="done-banner">✅ تم تسجيل جميع الطلاب — شكراً</div>
<div class="toast" id="toast"></div>

<script>
const TOKEN = "{token}";
let counts = {{ boarded: {boarded}, not_boarded: {not_boarded}, pending: {pending}, total: {total} }};

function notifyReady() {{
  const btn = document.getElementById('btn-ready');
  btn.disabled = true;
  btn.textContent = 'جارٍ الإرسال...';
  fetch('/bus/checkin/' + TOKEN + '/ready', {{ method: 'POST' }})
    .then(r => r.json())
    .then(data => {{
      if (data.ok) {{
        const card = document.getElementById('ready-card');
        card.className = 'ready-card ready-done';
        card.innerHTML = `
          <div class="ready-icon">✅</div>
          <div class="ready-text">
            <strong>تم إبلاغ الإدارة</strong>
            <span>تم إرسال الإشعار للإدارة بنجاح</span>
          </div>`;
        showToast('تم إبلاغ الإدارة بجاهزية الباص ✅');
      }} else {{
        btn.disabled = false;
        btn.textContent = 'أنا جاهز — أرسل للإدارة';
        showToast('تعذّر الإرسال، حاول مجدداً');
      }}
    }})
    .catch(() => {{
      btn.disabled = false;
      btn.textContent = 'أنا جاهز — أرسل للإدارة';
      showToast('تعذّر الاتصال، تحقق من الإنترنت');
    }});
}}

function record(studentId, status) {{
  fetch('/bus/checkin/' + TOKEN + '/record', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ student_id: studentId, status: status }})
  }})
  .then(r => r.json())
  .then(data => {{
    if (!data.ok) {{ showToast('حدث خطأ، حاول مجدداً'); return; }}
    updateRow(studentId, status);
  }})
  .catch(() => showToast('تعذّر الاتصال، تحقق من الإنترنت'));
}}

function updateRow(studentId, newStatus) {{
  const row = document.getElementById('row-' + studentId);
  const btns = row.querySelectorAll('button');
  const prev = row.dataset.status || 'pending';

  if (prev === 'boarded')          counts.boarded--;
  else if (prev === 'not_boarded') counts.not_boarded--;
  else                             counts.pending--;

  if (newStatus === 'boarded')          counts.boarded++;
  else if (newStatus === 'not_boarded') counts.not_boarded++;

  row.dataset.status = newStatus;
  row.className = 'student-row ' + (newStatus === 'boarded' ? 'done-yes' : 'done-no');
  btns[0].className = newStatus === 'boarded'     ? 'btn-active-yes' : 'btn-yes';
  btns[1].className = newStatus === 'not_boarded' ? 'btn-active-no'  : 'btn-no';

  document.getElementById('cnt-yes').textContent = counts.boarded;
  document.getElementById('cnt-no').textContent  = counts.not_boarded;
  document.getElementById('cnt-pen').textContent = counts.pending;
  document.getElementById('progress').style.width =
    (( counts.boarded + counts.not_boarded) / counts.total * 100) + '%';

  if (counts.pending === 0) document.getElementById('done-banner').style.display = 'block';
  showToast(newStatus === 'boarded' ? 'صعد ✅' : 'لم يصعد ❌');
}}

function showToast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2200);
}}

document.querySelectorAll('.student-row').forEach(row => {{
  const yes = row.querySelector('.btn-active-yes');
  const no  = row.querySelector('.btn-active-no');
  if (yes)      {{ row.classList.add('done-yes'); row.dataset.status = 'boarded'; }}
  else if (no)  {{ row.classList.add('done-no');  row.dataset.status = 'not_boarded'; }}
  else          row.dataset.status = 'pending';
}});

if (counts.pending === 0) document.getElementById('done-banner').style.display = 'block';
</script>
</body>
</html>"""
    return HTMLResponse(html)


def _notify_parent_boarded(trip: dict, student_id: str):
    """يرسل رسالة واتساب لولي الأمر عند صعود الطالب/ة للباص — إذا كان الإشعار مفعّلاً."""
    try:
        from config_manager import load_config as _lc
        if not _lc().get("bus_notify_parent", True):
            return
        store = load_students()
        student = store.get("by_id", {}).get(str(student_id))
        if not student:
            return
        phone = student.get("phone", "").strip()
        if not phone:
            return
        name       = student.get("name", student_id)
        bus_name   = trip.get("bus_name", "")
        trip_date  = trip.get("date", "")
        now_time   = datetime.datetime.now().strftime("%H:%M")

        if trip.get("trip_type") == "morning":
            msg = (
                f"🚌 إشعار الباص المدرسي\n\n"
                f"✅ صعد {name} إلى الباص\n\n"
                f"الباص: {bus_name}\n"
                f"التاريخ: {trip_date}\n"
                f"الوقت: {now_time}"
            )
        else:
            msg = (
                f"🚌 إشعار الباص المدرسي\n\n"
                f"✅ ركب {name} الباص في طريق العودة\n\n"
                f"الباص: {bus_name}\n"
                f"التاريخ: {trip_date}\n"
                f"الوقت: {now_time}"
            )
        send_whatsapp_message(phone, msg)
    except Exception:
        pass


@router.post("/bus/checkin/{token}/record")
async def bus_record_attendance(token: str, request: Request):
    trip = get_bus_trip_by_token(token)
    if not trip:
        return JSONResponse({"ok": False, "msg": "invalid token"}, status_code=404)
    body = await request.json()
    student_id = str(body.get("student_id", ""))
    status     = body.get("status", "")
    if status not in ("boarded", "not_boarded"):
        return JSONResponse({"ok": False, "msg": "invalid status"}, status_code=400)
    ok = record_bus_attendance(trip["id"], student_id, status)

    if ok and status == "boarded":
        # إرسال إشعار لولي الأمر في خيط خلفي
        threading.Thread(
            target=_notify_parent_boarded,
            args=(trip, student_id),
            daemon=True
        ).start()

    return JSONResponse({"ok": ok})


@router.post("/bus/checkin/{token}/ready")
async def bus_driver_ready(token: str):
    """السائق يُبلغ الإدارة بأنه وصل وجاهز لاستلام الطلاب."""
    trip = get_bus_trip_by_token(token)
    if not trip:
        return JSONResponse({"ok": False, "msg": "invalid token"}, status_code=404)

    mark_driver_ready(trip["id"])

    # إرسال واتساب للإدارة
    from config_manager import load_config
    cfg         = load_config()
    admin_phone = cfg.get("alert_admin_phone", "").strip()

    now_time = datetime.datetime.now().strftime("%H:%M")
    msg = (
        f"🚌 إشعار جاهزية الباص\n\n"
        f"الباص: {trip['bus_name']}\n"
        f"السائق: {trip['driver_name']}\n"
        f"التاريخ: {trip['date']}\n"
        f"الوقت: {now_time}\n\n"
        f"✅ السائق وصل وجاهز لاستلام الطلاب من المدرسة"
    )

    notified = False
    if admin_phone:
        ok, _ = send_whatsapp_message(admin_phone, msg)
        notified = ok

    return JSONResponse({"ok": True, "notified": notified})


# ══════════════════════════════════════════════════════════════════
#  مسارات الإدارة (تتطلب تسجيل دخول)
# ══════════════════════════════════════════════════════════════════

@router.get("/web/api/buses")
async def api_get_buses(request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    return JSONResponse({"ok": True, "buses": get_all_buses()})


@router.post("/web/api/buses")
async def api_create_bus(request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    body = await request.json()
    name   = body.get("name", "").strip()
    driver = body.get("driver_name", "").strip()
    phone  = body.get("driver_phone", "").strip()
    route  = body.get("route", "").strip()
    if not name or not driver or not phone:
        return JSONResponse({"ok": False, "msg": "البيانات ناقصة"}, status_code=400)
    bus_id = create_bus(name, driver, phone, route)
    return JSONResponse({"ok": True, "bus_id": bus_id})


@router.put("/web/api/buses/{bus_id}")
async def api_update_bus(bus_id: int, request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    body = await request.json()
    ok = update_bus(bus_id,
                    body.get("name", ""),
                    body.get("driver_name", ""),
                    body.get("driver_phone", ""),
                    body.get("route", ""))
    return JSONResponse({"ok": ok})


@router.delete("/web/api/buses/{bus_id}")
async def api_delete_bus(bus_id: int, request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    ok = delete_bus(bus_id)
    return JSONResponse({"ok": ok})


@router.get("/web/api/buses/{bus_id}/students")
async def api_get_bus_students(bus_id: int, request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    ids = get_students_in_bus(bus_id)
    return JSONResponse({"ok": True, "student_ids": ids})


@router.post("/web/api/buses/{bus_id}/students")
async def api_assign_students(bus_id: int, request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    body = await request.json()
    ids = body.get("student_ids", [])
    assign_students_to_bus(bus_id, [str(i) for i in ids])
    return JSONResponse({"ok": True, "count": len(ids)})


@router.post("/web/api/buses/send-checkin")
async def api_send_checkin(request: Request):
    """يُنشئ رحلة اليوم ويُرسل رابط التأكيد للسائق عبر واتساب."""
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    body       = await request.json()
    bus_id     = int(body.get("bus_id", 0))
    trip_type  = body.get("trip_type", "morning")
    date_str   = body.get("date", _today())

    bus = get_bus(bus_id)
    if not bus:
        return JSONResponse({"ok": False, "msg": "الباص غير موجود"}, status_code=404)

    student_ids = get_students_in_bus(bus_id)
    if not student_ids:
        return JSONResponse({"ok": False, "msg": "لا يوجد طلاب مسجلون في هذا الباص"}, status_code=400)

    trip = get_or_create_bus_trip(bus_id, date_str, trip_type)
    token = trip["token"]

    from config_manager import load_config
    cfg = load_config()
    _fwd_host  = request.headers.get("x-forwarded-host", "")
    _fwd_proto = request.headers.get("x-forwarded-proto", "https")
    if cfg.get("public_url", "").strip():
        base_url = cfg["public_url"].rstrip("/")
    elif _fwd_host and "localhost" not in _fwd_host and "127.0.0.1" not in _fwd_host:
        base_url = f"{_fwd_proto}://{_fwd_host}"
    else:
        base_url = str(request.base_url).rstrip("/")
    checkin_url = f"{base_url}/bus/checkin/{token}"

    trip_label = _TRIP_LABELS.get(trip_type, trip_type)
    msg = (
        f"🚌 مدرسة الدرب الثانوية\n"
        f"رسالة تسجيل حضور الطلاب في الباص\n\n"
        f"الباص: {bus['name']}\n"
        f"رحلة: {trip_label}\n"
        f"التاريخ: {date_str}\n\n"
        f"افتح الرابط التالي لتسجيل صعود الطلاب:\n"
        f"{checkin_url}"
    )

    success, status_msg = send_whatsapp_message(bus["driver_phone"], msg)
    if success:
        mark_bus_trip_sent(trip["id"])

    return JSONResponse({
        "ok":     success,
        "msg":    status_msg,
        "url":    checkin_url,
        "trip_id": trip["id"],
    })


@router.get("/web/api/buses/trips")
async def api_trips_summary(request: Request, date: str = ""):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    d = date or _today()
    return JSONResponse({"ok": True, "date": d, "trips": get_bus_trips_summary(d)})


@router.get("/web/api/buses/trip/{trip_id}")
async def api_trip_detail(trip_id: int, request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    rows = get_bus_trip_attendance(trip_id)
    return JSONResponse({"ok": True, "attendance": rows})


# ── عرض يومي شامل (كل الباصات مع حالة رحلاتها) ──────────────────
@router.get("/web/api/buses/daily-view")
async def api_buses_daily_view(request: Request, date: str = ""):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    import sqlite3 as _sq3
    d = date or _today()
    buses = get_all_buses()
    result = []
    for bus in buses:
        student_ids = get_students_in_bus(bus["id"])
        entry = {**bus, "student_count": len(student_ids), "morning": None, "afternoon": None}
        # جلب رحلات الباص لهذا اليوم
        con = get_db(); con.row_factory = _sq3.Row; cur = con.cursor()
        cur.execute("""SELECT bt.*,
               COUNT(ba.id) as total,
               SUM(CASE WHEN ba.status='boarded'     THEN 1 ELSE 0 END) as boarded,
               SUM(CASE WHEN ba.status='not_boarded' THEN 1 ELSE 0 END) as not_boarded,
               SUM(CASE WHEN ba.status='pending'     THEN 1 ELSE 0 END) as pending
               FROM bus_trips bt
               LEFT JOIN bus_attendance ba ON ba.trip_id=bt.id
               WHERE bt.bus_id=? AND bt.date=?
               GROUP BY bt.id""", (bus["id"], d))
        for row in cur.fetchall():
            r = dict(row)
            r["exists"] = True
            entry[r["trip_type"]] = r
        con.close()
        result.append(entry)
    return JSONResponse({"ok": True, "date": d,
                         "is_school_day": is_school_day(d),
                         "buses": result})


# ── الإجازات ──────────────────────────────────────────────────────
@router.get("/web/api/buses/holidays")
async def api_get_holidays(request: Request, year: str = ""):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    return JSONResponse({"ok": True, "holidays": get_holidays(year or None)})


@router.post("/web/api/buses/holidays")
async def api_add_holiday(request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    body  = await request.json()
    date  = body.get("date", "").strip()
    label = body.get("label", "").strip()
    if not date:
        return JSONResponse({"ok": False, "msg": "التاريخ مطلوب"}, status_code=400)
    ok = add_holiday(date, label)
    return JSONResponse({"ok": ok, "msg": "" if ok else "هذا التاريخ مسجّل مسبقاً"})


@router.delete("/web/api/buses/holidays/{holiday_id}")
async def api_remove_holiday(holiday_id: int, request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    remove_holiday(holiday_id)
    return JSONResponse({"ok": True})


# ── إعدادات الجدولة ───────────────────────────────────────────────
@router.get("/web/api/buses/schedule-config")
async def api_get_bus_schedule(request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    from config_manager import load_config
    cfg = load_config()
    return JSONResponse({"ok": True,
                         "enabled":        cfg.get("bus_schedule_enabled",  False),
                         "morning_time":   cfg.get("bus_morning_time",      "06:30"),
                         "afternoon_time": cfg.get("bus_afternoon_time",    "12:30"),
                         "notify_parent":  cfg.get("bus_notify_parent",     True)})


@router.post("/web/api/buses/schedule-config")
async def api_save_bus_schedule(request: Request):
    if not _auth(request):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=401)
    body = await request.json()
    from config_manager import load_config, save_config
    cfg = load_config()
    cfg["bus_schedule_enabled"] = bool(body.get("enabled",       False))
    cfg["bus_morning_time"]     = body.get("morning_time",        "06:30")
    cfg["bus_afternoon_time"]   = body.get("afternoon_time",      "12:30")
    cfg["bus_notify_parent"]    = bool(body.get("notify_parent",  True))
    save_config(cfg)
    return JSONResponse({"ok": True})


# ─── صفحة خطأ ─────────────────────────────────────────────────────
def _error_page(msg: str) -> str:
    return f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>خطأ</title>
<style>body{{font-family:Tahoma;display:flex;align-items:center;justify-content:center;
height:100vh;background:#fef2f2;color:#991b1b;text-align:center;padding:20px}}</style>
</head><body><div><h2>⚠️ {msg}</h2></div></body></html>"""
