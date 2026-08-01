# -*- coding: utf-8 -*-
"""
api/mobile_routes.py — مسارات الواجهة المتنقلة والفصول الدراسية
"""
import datetime, json, base64, os, re, io, socket, sqlite3, subprocess, threading
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from constants import (DB_PATH, DATA_DIR, TEACHERS_JSON, HOST, PORT, TZ_OFFSET,
                       STATIC_DOMAIN, STUDENTS_STORE, BASE_DIR,
                       now_riyadh_date, local_ip, navbar_html, debug_on,
                       CURRENT_USER, ROLES)
from config_manager import load_config, get_terms, logo_img_tag_from_config, ar
from database import (get_db, load_students, load_teachers,
                      insert_absences, query_absences,
                      query_tardiness, insert_tardiness, delete_tardiness,
                      compute_tardiness_metrics, insert_excuse, query_excuses,
                      delete_excuse, student_has_excuse,
                      norm_token, normalize_legacy_class_id,
                      section_label_from_value, display_name_from_legacy,
                      level_name_from_value, _apply_class_name_fix,
                      import_students_from_excel_sheet2_format)
from whatsapp_service import send_whatsapp_message, send_whatsapp_pdf
from report_builder import (generate_report_html, generate_daily_report,
                             generate_monitor_table_html, get_live_monitor_status,
                             get_live_monitor_status as _get_monitor, parent_portal_html)
from alerts_service import (log_message_status, query_today_messages,
                             load_schedule, save_schedule,
                             query_permissions, insert_permission,
                             update_permission_status, delete_permission)
from pdf_generator import (results_portal_html, student_result_html, get_student_result, _render_pdf_page_as_png)

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
#  حماية المسارات الإدارية من الوصول الخارجي
# ═══════════════════════════════════════════════════════════════════
# بوابة الجوال مصمَّمة للعمل بلا تسجيل دخول داخل شبكة المدرسة (روابط QR
# للمعلمين والحارس). لكن نفق Cloudflare يكشف نفس المسارات للإنترنت، ومنها
# حذف طالب أو فصل وإرسال رسائل جماعية. لذلك: من داخل الشبكة يبقى كل شيء
# كما هو، ومن خارجها تتطلب هذه المسارات جلسة دخول صالحة.

_PRIVATE_PREFIXES = ("127.", "10.", "192.168.", "169.254.", "::1", "localhost")


def _is_private_host(host: str) -> bool:
    if not host:
        return False
    if host.startswith(_PRIVATE_PREFIXES):
        return True
    # النطاق الخاص 172.16.0.0 – 172.31.255.255
    parts = host.split(".")
    if len(parts) == 4 and parts[0] == "172":
        try:
            return 16 <= int(parts[1]) <= 31
        except ValueError:
            return False
    return False


def _is_external(request: Request) -> bool:
    """هل وصل الطلب من خارج شبكة المدرسة (عبر النفق)؟"""
    if any(request.headers.get(h) for h in
           ("x-forwarded-for", "x-real-ip", "cf-connecting-ip",
            "cf-ray", "forwarded")):
        return True
    return not _is_private_host(request.client.host if request.client else "")


def _deny_external(request: Request):
    """يُرجع رد رفض إذا كان الطلب خارجياً وبلا جلسة دخول، وإلا None."""
    if not _is_external(request):
        return None
    from api.web_routes import _get_current_user
    if _get_current_user(request):
        return None
    return JSONResponse(
        {"detail": "هذا الإجراء يتطلب تسجيل الدخول عند الوصول من خارج شبكة المدرسة"},
        status_code=401,
    )


@router.get("/manage-students", response_class=HTMLResponse)
def manage_students_web_page(request: Request):
    _denied = _deny_external(request)
    if _denied:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/web/login")
    base_url = STATIC_DOMAIN if STATIC_DOMAIN and not debug_on() else f"http://{local_ip()}:{PORT}"
    nav = navbar_html(base_url)
    store = load_students()
    student_options = ""
    for c in store["list"]:
        for s in c["students"]:
            student_options += f'<option value="{s["id"]}">{s["name"]} ({c["name"]})</option>'
    class_options = "".join(f'<option value="{c["id"]}">{c["name"]} ({len(c["students"])} طالب)</option>' for c in store["list"])
    return f"""\n<!DOCTYPE html>\n<html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>إدارة الطلاب والفصول</title>
        <style>
            body {{ font-family: 'Cairo', sans-serif; background: #f8f9fa; padding: 20px; }}
            .container {{ max-width: 600px; margin: auto; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
            h2 {{ text-align: center; margin-bottom: 25px; color: #2c3e50; }}
            .section {{ margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid #eee; }}
            label {{ display: block; margin: 12px 0 6px; font-weight: bold; color: #34495e; }}
            select, button {{ width: 100%; padding: 12px; font-size: 16px; border-radius: 8px; }}
            select {{ border: 1px solid #ddd; margin-bottom: 15px; }}
            button {{ background: #e74c3c; color: white; font-weight: bold; cursor: pointer; }}
            button:disabled {{ background: #95a5a6; cursor: not-allowed; }}
            #status {{ margin-top: 20px; padding: 12px; border-radius: 8px; text-align: center; font-weight: bold; display: none; }}
            .success {{ background: #d4edda; color: #155724; }}
            .error {{ background: #f8d7da; color: #721c24; }}
        </style>
        <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap" rel="stylesheet">
    </head>
    <body>
        <div class="container">
            <h2>🗑️ إدارة الطلاب والفصول</h2>

            <div class="section">
                <h3>حذف طالب</h3>
                <label>اختر الطالب للحذف:</label>
                <select id="student_id">
                    <option value="">— اختر طالبًا —</option>
                    {student_options}
                </select>
                <button onclick="deleteStudent()">حذف الطالب المحدد</button>
            </div>

            <div class="section">
                <h3>حذف فصل</h3>
                <label>اختر الفصل للحذف (سيتم حذف جميع طلابه):</label>
                <select id="class_id">
                    <option value="">— اختر فصلًا —</option>
                    {class_options}
                </select>
                <button onclick="deleteClass()">حذف الفصل المحدد</button>
            </div>

            <div id="status"></div>
        </div>

        <script>
            async function deleteStudent() {{
                const studentId = document.getElementById('student_id').value;
                if (!studentId) {{ alert('الرجاء اختيار طالب.'); return; }}
                if (!confirm('هل أنت متأكد من حذف هذا الطالب؟ لا يمكن التراجع.')) return;

                const status = document.getElementById('status');
                status.style.display = 'block';
                status.className = '';
                status.textContent = 'جاري الحذف...';

                try {{
                    const res = await fetch('/api/delete-student', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ student_id: studentId }})
                    }});
                    const data = await res.json();
                    if (res.ok) {{
                        status.className = 'success';
                        status.textContent = '✅ تم حذف الطالب بنجاح!';
                        document.getElementById('student_id').value = '';
                    }} else {{
                        throw new Error(data.detail || 'فشل الحذف');
                    }}
                }} catch (err) {{
                    status.className = 'error';
                    status.textContent = '❌ ' + err.message;
                }}
            }}

            async function deleteClass() {{
                const classId = document.getElementById('class_id').value;
                if (!classId) {{ alert('الرجاء اختيار فصل.'); return; }}
                if (!confirm('تحذير: سيتم حذف الفصل وجميع طلابه! هل أنت متأكد؟')) return;

                const status = document.getElementById('status');
                status.style.display = 'block';
                status.className = '';
                status.textContent = 'جاري الحذف...';

                try {{
                    const res = await fetch('/api/delete-class', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ class_id: classId }})
                    }});
                    const data = await res.json();
                    if (res.ok) {{
                        status.className = 'success';
                        status.textContent = '✅ تم حذف الفصل بنجاح!';
                        document.getElementById('class_id').value = '';
                    }} else {{
                        throw new Error(data.detail || 'فشل الحذف');
                    }}
                }} catch (err) {{
                    status.className = 'error';
                    status.textContent = '❌ ' + err.message;
                }}
            }}
        </script>
    </body>
    </html>
    """


@router.post("/api/delete-student", response_class=JSONResponse)
async def api_delete_student(request: Request):
    _denied = _deny_external(request)
    if _denied: return _denied
    data = await request.json()
    student_id = data.get("student_id", "").strip()
    if not student_id:
        return JSONResponse({"detail": "الرقم الأكاديمي مطلوب."}, status_code=400)

    store = load_students(force_reload=True)
    classes = store.get("list", [])
    found = False
    for c in classes:
        for i, s in enumerate(c.get("students", [])):
            if s.get("id") == student_id:
                del c["students"][i]
                found = True
                break
        if found:
            break

    if not found:
        return JSONResponse({"detail": "الطالب غير موجود."}, status_code=404)

    try:
        with open(STUDENTS_JSON, "w", encoding="utf-8") as f:
            json.dump({"classes": classes}, f, ensure_ascii=False, indent=2)
        global STUDENTS_STORE
        STUDENTS_STORE = None
        load_students(force_reload=True)
        return JSONResponse({"message": "تم حذف الطالب بنجاح"})
    except Exception as e:
        return JSONResponse({"detail": f"فشل الحفظ: {str(e)}"}, status_code=500)


@router.post("/api/delete-class", response_class=JSONResponse)
async def api_delete_class(request: Request):
    _denied = _deny_external(request)
    if _denied: return _denied
    data = await request.json()
    class_id = data.get("class_id", "").strip()
    if not class_id:
        return JSONResponse({"detail": "معرف الفصل مطلوب."}, status_code=400)

    store = load_students(force_reload=True)
    classes = store.get("list", [])
    new_classes = [c for c in classes if c.get("id") != class_id]

    if len(new_classes) == len(classes):
        return JSONResponse({"detail": "الفصل غير موجود."}, status_code=404)

    try:
        with open(STUDENTS_JSON, "w", encoding="utf-8") as f:
            json.dump({"classes": new_classes}, f, ensure_ascii=False, indent=2)
        global STUDENTS_STORE
        STUDENTS_STORE = None
        load_students(force_reload=True)
        return JSONResponse({"message": "تم حذف الفصل بنجاح"})
    except Exception as e:
        return JSONResponse({"detail": f"فشل الحفظ: {str(e)}"}, status_code=500)

def live_monitor_html_page() -> str:
    base_url = STATIC_DOMAIN if STATIC_DOMAIN and not debug_on() else f"http://{local_ip()}:{PORT}"
    nav = navbar_html(base_url)
    style_css = """
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background-color: #f4f7f6; margin: 0; padding: 10px; }
        .container { max-width: 1400px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 15px; color: #333; }
        #last-update { text-align: center; color: #888; margin-bottom: 10px; }
    """
    return f"""\n<!DOCTYPE html>\n<html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>لوحة المراقبة الحية</title>
        <style>{style_css}</style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>لوحة المراقبة الحية لتسجيل الغياب</h2></div>
            <div id="last-update">جارٍ التحميل...</div>
            <div id="monitor-content">جارٍ التحميل...</div>
        </div>
        <script>
            async function updateMonitor() {{
                try {{
                    const res = await fetch('/api/live_status');
                    const data = await res.json();
                    const now = new Date().toLocaleTimeString('ar-SA');
                    document.getElementById('last-update').innerText = 'آخر تحديث: ' + now;
                    
                    let html = '<table style="width:100%; border-collapse:collapse; table-layout:fixed;">';
                    if (data.length === 0) {{
                        html += '<tr><td>لا توجد بيانات</td></tr>';
                    }} else {{
                        html += '<thead><tr><th style="background:#e9ecef; padding:10px;">الحصة</th>';
                        for (const cls of data[0].classes) {{
                            html += `<th style="background:#e9ecef; padding:10px;">${{cls.class_name}}</th>`;
                        }}
                        html += '</tr></thead><tbody>';
                        for (const period of data) {{
                            html += `<tr><td style="font-weight:bold; width:100px;">الحصة ${{period.period}}</td>`;
                            for (const cls of period.classes) {{
                                const icon = cls.status === 'done' ? '✔' : '✖';
                                const bgColor = cls.status === 'done' ? '#f0fdf4' : '#fff1f2';
                                const color = cls.status === 'done' ? '#166534' : '#9f1239';
                                html += `
                                    <td style="height:80px; padding:8px; text-align:center; background:${{bgColor}}; border:1px solid #ddd;">
                                        <div style="font-size:20px; color:${{color}};">${{icon}}</div>
                                        <div style="font-weight:bold; color:${{color}};">${{cls.teacher_name}}</div>
                                    </td>`;
                            }}
                            html += '</tr>';
                        }}
                        html += '</tbody>';
                    }}
                    html += '</table>';
                    document.getElementById('monitor-content').innerHTML = html;
                }} catch (e) {{
                    document.getElementById('monitor-content').innerHTML = '<p style="color:red;">خطأ في التحديث</p>';
                }}
            }}
            updateMonitor();
            setInterval(updateMonitor, 15000);
        </script>
    </body>
    </html>
    """
    
def class_html(class_id: str, class_name: str,
               students: List[Dict[str,str]],
               teachers: List[Dict[str,str]]) -> str:
    """صفحة تسجيل الغياب للمعلم — تصميم PWA محسّن."""
    import json as _json

    today        = now_riyadh_date()
    cfg          = load_config()
    school       = cfg.get("school_name", "المدرسة")
    period_times = cfg.get("period_times",
        ["07:00","07:50","08:40","09:50","10:40","11:30","12:20"])
    base_url     = (STATIC_DOMAIN if STATIC_DOMAIN and not debug_on()
                    else "http://{}:{}".format(local_ip(), PORT))

    tch_opts = '<option value="">— المعلم —</option>' + "".join(
        '<option value="{n}">{n}</option>'.format(n=t.get("اسم المعلم",""))
        for t in teachers)

    period_opts = '<option value="">— الحصة —</option>' + "".join(
        '<option value="{i}">الحصة {i} — {t}</option>'.format(
            i=i, t=period_times[i-1] if i-1 < len(period_times) else "")
        for i in range(1, 8))

    students_json = _json.dumps(
        [{"id": s.get("id",""), "name": s.get("name","")} for s in students],
        ensure_ascii=False)

    total = len(students)

    # HTML مع .format() بدلاً من f-string لتجنب تضارب {{}}
    html = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="theme-color" content="#1565C0">
<link rel="manifest" href="/manifest.json">
<title>__CLASS_NAME__ — __SCHOOL__</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap');
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{
  --primary:#1565C0; --primary-d:#0D47A1;
  --danger:#C62828;  --success:#2E7D32;
  --bg:#F5F7FA; --surface:#fff;
  --text:#1a1a2e; --text2:#5A6A7E; --border:#DDE3EA;
}
html,body{height:100%;font-family:'Cairo',sans-serif;background:var(--bg);
          direction:rtl;color:var(--text);overscroll-behavior:none}
.hdr{position:sticky;top:0;z-index:100;background:var(--primary);
     color:#fff;padding:0;box-shadow:0 2px 8px rgba(0,0,0,.2)}
.hdr-top{display:flex;align-items:center;justify-content:space-between;padding:12px 16px 6px}
.hdr-title{font-size:17px;font-weight:900;line-height:1.2}
.hdr-sub{font-size:11px;opacity:.8;margin-top:2px}
.hdr-stats{text-align:left;font-size:11px;opacity:.85}
.hdr-stats b{font-size:18px;font-weight:900;display:block}
.ctrl-bar{background:var(--primary-d);padding:8px 12px;display:flex;gap:8px;align-items:center}
.ctrl-bar select{flex:1;padding:10px;font-family:'Cairo',sans-serif;font-size:14px;
                 border:none;border-radius:8px;background:#fff;color:var(--text);direction:rtl}
.ctrl-bar input[type=date]{padding:10px;font-family:'Cairo',sans-serif;font-size:14px;
    border:none;border-radius:8px;background:#fff;color:var(--text);width:140px}
.quick-row{display:flex;gap:8px;padding:10px 12px;background:#fff;border-bottom:1px solid var(--border)}
.q-btn{flex:1;padding:9px;font-family:'Cairo',sans-serif;font-size:13px;font-weight:700;
       border:1.5px solid var(--border);border-radius:8px;background:#F5F7FA;cursor:pointer}
.q-btn.sel-all{border-color:var(--danger);color:var(--danger)}
.q-btn.clr-all{border-color:var(--success);color:var(--success)}
.search-wrap{padding:8px 12px;background:#fff;border-bottom:1px solid var(--border)}
.search-inp{width:100%;padding:10px 14px;border:1.5px solid var(--border);
            border-radius:10px;font-family:'Cairo',sans-serif;font-size:14px;
            direction:rtl;background:var(--bg)}
.search-inp:focus{outline:none;border-color:var(--primary)}
.stu-list{padding:10px 12px;display:flex;flex-direction:column;gap:7px;padding-bottom:100px}
.stu-btn{width:100%;display:flex;align-items:center;justify-content:space-between;
         padding:14px 16px;font-family:'Cairo',sans-serif;font-size:16px;font-weight:700;
         border:2px solid var(--border);border-radius:12px;background:var(--surface);
         color:var(--text);cursor:pointer;transition:all .15s;text-align:right;line-height:1.3}
.stu-btn .stu-num{font-size:11px;color:var(--text2);margin-top:2px;font-weight:400}
.stu-btn .stu-badge{font-size:22px;min-width:30px;text-align:center}
.stu-btn.absent{background:var(--danger);color:#fff;border-color:#B71C1C}
.stu-btn:active{transform:scale(.98)}
.submit-wrap{position:fixed;bottom:0;right:0;left:0;padding:12px 16px;
             background:#fff;border-top:1px solid var(--border);box-shadow:0 -4px 16px rgba(0,0,0,.08)}
.submit-btn{width:100%;padding:16px;font-family:'Cairo',sans-serif;font-size:17px;font-weight:900;
            border:none;border-radius:12px;background:var(--success);color:#fff;cursor:pointer}
.submit-btn:disabled{background:#B0BEC5;cursor:not-allowed}
.counter-bar{display:flex;gap:10px;padding:6px 12px;background:#fff;
             border-bottom:1px solid var(--border);font-size:12px;font-weight:700}
.cnt-present{color:var(--success)}.cnt-absent{color:var(--danger)}
#toast{position:fixed;bottom:90px;left:50%;transform:translateX(-50%);
       background:#1a1a2e;color:#fff;padding:10px 22px;border-radius:20px;
       font-size:14px;opacity:0;transition:opacity .3s;pointer-events:none;z-index:999}
#toast.show{opacity:1}
#toast.ok{background:var(--success)}
#toast.err{background:var(--danger)}
#done-overlay{display:none;position:fixed;inset:0;background:var(--success);
              color:#fff;z-index:9999;flex-direction:column;
              align-items:center;justify-content:center;gap:16px}
.done-icon{font-size:80px}.done-text{font-size:22px;font-weight:900;text-align:center}
.done-sub{font-size:15px;opacity:.85;text-align:center}
.done-btn{margin-top:16px;padding:14px 32px;font-family:'Cairo',sans-serif;
    font-size:16px;font-weight:700;border:2px solid #fff;border-radius:12px;
    background:transparent;color:#fff;cursor:pointer}
</style>
</head>
<body>
<div class="hdr">
  <div class="hdr-top">
    <div>
      <div class="hdr-title">__CLASS_NAME__</div>
      <div class="hdr-sub">__SCHOOL__ — __TODAY__</div>
    </div>
    <div style="display:flex;align-items:center;gap:10px">
      <div class="hdr-stats"><b id="absent-cnt">0</b> غائب</div>
      <button id="notif-btn" onclick="requestNotifPermission()"
        style="background:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.4);
               color:#fff;padding:6px 10px;border-radius:8px;font-size:13px;
               font-family:Cairo,sans-serif;cursor:pointer;display:none">
        🔔 تفعيل الإشعارات
      </button>
      <button id="install-btn" onclick="installApp()"
        style="background:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.4);
               color:#fff;padding:6px 10px;border-radius:8px;font-size:13px;
               font-family:Cairo,sans-serif;cursor:pointer;display:none">
        📲 تثبيت التطبيق
      </button>
    </div>
  </div>
  <div id="period-alert" style="display:none;background:rgba(255,255,255,.15);
       padding:8px 16px;border-radius:8px;margin-top:8px;font-size:13px;
       text-align:center;font-weight:700">
    🔔 <span id="period-alert-text"></span>
  </div>
</div>
<div class="ctrl-bar">
  __TCH_OPTS_SEL__
  __PERIOD_OPTS_SEL__
  <input type="date" id="date-inp" value="__TODAY__">
</div>
<div class="quick-row">
  <button class="q-btn sel-all" onclick="selectAll()">تحديد الكل غائب</button>
  <button class="q-btn clr-all" onclick="clearAll()">إلغاء التحديد</button>
</div>
<div class="search-wrap">
  <input class="search-inp" id="search" placeholder="بحث باسم الطالب..." oninput="filterStudents(this.value)">
</div>
<div class="counter-bar">
  <span class="cnt-present">حاضر: <span id="cnt-p">__TOTAL__</span></span>
  <span>|</span>
  <span class="cnt-absent">غائب: <span id="cnt-a">0</span></span>
  <span>|</span>
  <span>الإجمالي: __TOTAL__</span>
</div>
<div class="stu-list" id="stu-list"></div>
<div class="submit-wrap">
  <button class="submit-btn" id="submit-btn" onclick="submitAbsences()" disabled>
    اختر المعلم والحصة أولاً
  </button>
</div>
<div id="toast"></div>
<div id="done-overlay">
  <div class="done-icon">&#x2705;</div>
  <div class="done-text" id="done-text">تم التسجيل بنجاح</div>
  <div class="done-sub" id="done-sub"></div>
  <button class="done-btn" onclick="resetPage()">تسجيل حصة جديدة</button>
</div>
<script>
const BASE="__BASE_URL__",CLASS_ID="__CLASS_ID__",TOTAL=__TOTAL__,STUDENTS=__STUDENTS_JSON__;
const absent=new Set();
function buildList(q=""){
  const ul=document.getElementById('stu-list'); ul.innerHTML='';
  const qq=q.trim().toLowerCase();
  STUDENTS.forEach(s=>{
    if(qq&&!s.name.toLowerCase().includes(qq))return;
    const b=document.createElement('button');
    b.className='stu-btn'+(absent.has(s.id)?' absent':'');
    b.onclick=()=>toggleStudent(s.id,b);
    b.innerHTML='<div><div>'+s.name+'</div><div class="stu-num">'+s.id+'</div></div>'
               +'<div class="stu-badge">'+(absent.has(s.id)?'&#x1F534;':'&#x1F7E2;')+'</div>';
    ul.appendChild(b);
  });
}
function toggleStudent(id,btn){
  if(absent.has(id)){absent.delete(id);btn.className='stu-btn';btn.querySelector('.stu-badge').innerHTML='&#x1F7E2;';}
  else{absent.add(id);btn.className='stu-btn absent';btn.querySelector('.stu-badge').innerHTML='&#x1F534;';}
  updateCounter();
}
function updateCounter(){
  const a=absent.size,p=TOTAL-a;
  document.getElementById('cnt-a').textContent=a;
  document.getElementById('cnt-p').textContent=p;
  document.getElementById('absent-cnt').textContent=a;
  const btn=document.getElementById('submit-btn');
  const ready=document.getElementById('teacher-sel').value&&document.getElementById('period-sel').value;
  btn.disabled=!ready;
  btn.textContent=ready?(a>0?'تسجيل '+a+' غائب':'تسجيل (لا غياب)'):'اختر المعلم والحصة أولاً';
}
function checkReady(){updateCounter();}
function selectAll(){STUDENTS.forEach(s=>absent.add(s.id));buildList(document.getElementById('search').value);updateCounter();}
function clearAll(){absent.clear();buildList(document.getElementById('search').value);updateCounter();}
function filterStudents(q){buildList(q);}
function toast(msg,type,ms=2500){
  const t=document.getElementById('toast');
  t.textContent=msg;t.className='show '+(type||'');
  setTimeout(()=>t.className='',ms);
}
async function submitAbsences(){
  const teacher=document.getElementById('teacher-sel').value;
  const period=document.getElementById('period-sel').value;
  const date=document.getElementById('date-inp').value;
  const btn=document.getElementById('submit-btn');
  if(!teacher||!period){toast('اختر المعلم والحصة','err');return;}
  btn.disabled=true;btn.textContent='جارٍ التسجيل...';
  const absentList=STUDENTS.filter(s=>absent.has(s.id));
  try{
    const r=await fetch(BASE+'/api/submit/'+CLASS_ID,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({date,students:absentList,teacher_name:teacher,period:parseInt(period)})
    });
    const d=await r.json();
    if(r.ok){
      document.getElementById('done-text').textContent='تم التسجيل بنجاح';
      document.getElementById('done-sub').textContent=
        absentList.length>0?('غائب: '+absentList.length+' | حاضر: '+(TOTAL-absentList.length)):'لا يوجد غياب';
      document.getElementById('done-overlay').style.display='flex';
    }else{
      toast('فشل: '+JSON.stringify(d),'err',4000);
      btn.disabled=false;btn.textContent='إعادة المحاولة';
    }
  }catch(e){
    toast('خطأ في الاتصال','err',4000);
    btn.disabled=false;btn.textContent='إعادة المحاولة';
  }
}
function resetPage(){
  absent.clear();
  document.getElementById('done-overlay').style.display='none';
  document.getElementById('teacher-sel').value='';
  document.getElementById('period-sel').value='';
  document.getElementById('search').value='';
  buildList();updateCounter();
}
if('serviceWorker' in navigator){
  navigator.serviceWorker.register('/service-worker.js')
    .catch(e=>console.warn('[SW]',e));
}
if(Notification&&Notification.permission==='default'){
  Notification.requestPermission();
}
buildList();updateCounter();
</script>
</body></html>"""

    # استبدل placeholders بالقيم الحقيقية
    html = html.replace("__CLASS_NAME__", class_name)
    html = html.replace("__SCHOOL__",     school)
    html = html.replace("__TODAY__",      today)
    html = html.replace("__BASE_URL__",   base_url)
    html = html.replace("__CLASS_ID__",   class_id)
    html = html.replace("__TOTAL__",      str(total))
    html = html.replace("__STUDENTS_JSON__", students_json)
    html = html.replace("__TCH_OPTS_SEL__",
        '<select id="teacher-sel" onchange="checkReady()">' + tch_opts + '</select>')
    html = html.replace("__PERIOD_OPTS_SEL__",
        '<select id="period-sel" onchange="checkReady()">' + period_opts + '</select>')
    return html


@router.get("/c/{class_id:path}", response_class=HTMLResponse)
def get_class_page(class_id: str):
    """صفحة تسجيل الغياب لفصل محدد."""
    try:
        # فك تشفير URL (مثل %D8%A3 → أ) لدعم المعرّفات التي تحتوي على حروف عربية
        from urllib.parse import unquote
        class_id = unquote(class_id)

        store = load_students()
        cls = store["by_id"].get(class_id)

        # محاولة fallback: البحث بدون حساسية الحالة أو مطابقة جزئية
        if not cls:
            for key, val in store["by_id"].items():
                if str(key).strip() == str(class_id).strip():
                    cls = val
                    class_id = key
                    break

        if not cls:
            # عرض قائمة الفصول المتاحة لتسهيل التشخيص
            available = ", ".join(str(k) for k in store["by_id"].keys())
            return HTMLResponse(
                content=(
                    "<div style='text-align:center;font-family:Cairo,Arial;direction:rtl;padding:30px'>"
                    f"<h2 style='color:red'>الفصل غير موجود: <code>{class_id}</code></h2>"
                    f"<p style='color:#555'>الفصول المتاحة: {available}</p>"
                    "</div>"
                ),
                status_code=404
            )
        try:
            if os.path.exists(TEACHERS_JSON):
                with open(TEACHERS_JSON, "r", encoding="utf-8-sig") as f:
                    teachers_data = json.load(f)
            else:
                teachers_data = {"teachers": []}
        except Exception as e:
            print(f"[ERROR Loading Teachers in get_class_page] {e}")
            teachers_data = {"teachers": []}
        teachers_list = teachers_data.get("teachers", []) if isinstance(teachers_data, dict) else []
        return HTMLResponse(content=class_html(class_id, cls["name"], cls["students"], teachers_list))
    except Exception as e:
        import traceback
        print(f"[ERROR /c/{class_id}] {e}\n{traceback.format_exc()}")
        return HTMLResponse(content=f"<h2 style='color:red;font-family:Arial'>خطأ: {e}</h2>", status_code=500)

@router.post("/api/submit/{class_id:path}")
async def api_submit(class_id: str, req: Request):
    from urllib.parse import unquote
    class_id = unquote(class_id)
    payload = await req.json()
    date_str, students, teacher_name, period = payload.get("date"), payload.get("students", []), payload.get("teacher_name"), payload.get("period")
    if not isinstance(students, list) or not teacher_name: return JSONResponse({"detail": "بيانات غير مكتملة."}, status_code=400)
    store = load_students(); cls = store["by_id"].get(class_id)
    if not cls:
        for key, val in store["by_id"].items():
            if str(key).strip() == str(class_id).strip():
                cls = val; class_id = key; break
    if not cls: return JSONResponse({"detail": "class_id غير صحيح."}, status_code=404)
    valid_ids = set(s["id"] for s in cls["students"])
    filtered = [s for s in students if s.get("id") in valid_ids]
    result = insert_absences(date_str, class_id, cls["name"], filtered, None, teacher_name, period)
    return JSONResponse(result)

# ═══════════════════════════════════════════════════════════════
# صفحات التأخر — /tardiness و /tardiness/{class_id}
# ═══════════════════════════════════════════════════════════════

def _calc_late_minutes(register_time_str: str, cfg: dict) -> int:
    """يحسب دقائق التأخر من وقت التسجيل - وقت بداية الدوام."""
    try:
        start_str = cfg.get("school_start_time", "07:00")
        fmt = "%H:%M"
        t_reg   = datetime.datetime.strptime(register_time_str[:5], fmt)
        t_start = datetime.datetime.strptime(start_str[:5], fmt)
        diff = int((t_reg - t_start).total_seconds() / 60)
        return max(diff, 0)
    except Exception:
        return 0

def get_tardiness_recipients():
    """يُرجع قائمة مستلمي رابط التأخر من الإعدادات."""
    cfg = load_config()
    return cfg.get("tardiness_recipients", [])

def save_tardiness_recipients(recipients):
    """يحفظ قائمة المستلمين في الإعدادات."""
    cfg = load_config()
    cfg["tardiness_recipients"] = recipients
    with open(CONFIG_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def send_tardiness_link_to_all():
    """
    يُرسل رابط التأخر (كل المدرسة) لجميع المستلمين المسجّلين.
    يُرجع: (عدد_النجاح, عدد_الفشل, تفاصيل)
    """
    cfg        = load_config()
    base       = (STATIC_DOMAIN if STATIC_DOMAIN and not debug_on()
                  else "http://{}:{}".format(local_ip(), PORT))
    url        = "{}/tardiness".format(base)
    recipients = get_tardiness_recipients()
    today      = now_riyadh_date()
    start_time = cfg.get("school_start_time", "07:00")

    if not recipients:
        return 0, 0, ["لا يوجد مستلمون مسجّلون"]

    msg = (
        f"⏱ رابط تسجيل التأخر\n"
        f"📅 {today}  |  🕐 بداية الدوام: {start_time}\n"
        "يرجى تسجيل المتأخرين من خلال الرابط:\n"
        f"{url}"
    )

    sent, failed, details = 0, 0, []
    for r in recipients:
        phone = r.get("phone", "")
        name  = r.get("name", "")
        if not phone:
            details.append(f"⚠️ {name}: لا يوجد رقم جوال")
            failed += 1
            continue
        ok, status = send_whatsapp_message(phone, msg)
        _dl = max(1, load_config().get("tard_msg_delay_sec", 8))
        time.sleep(_dl)  # تأخير بين الرسائل لتجنب حظر الواتساب
        if ok:
            sent += 1
            details.append(f"✅ {name}")
        else:
            failed += 1
            details.append(f"❌ {name}: {status}")

    return sent, failed, details


def _schedule_tardiness_sender(root_widget):
    """
    يجدول إرسال رابط التأخر تلقائياً في الوقت المحدد (من الإعدادات) كل يوم عمل.
    يُستدعى مرة واحدة عند بدء البرنامج.
    """
    WORK_DAYS = {6, 0, 1, 2, 3}  # الأحد-الخميس

    def check_and_send():
        now = datetime.datetime.now()
        if now.weekday() not in WORK_DAYS:
            root_widget.after(60_000, check_and_send)
            return
        cfg = load_config()
        # استخدم الوقت المخصص إن كان مفعّلاً، وإلا وقت بداية الدوام
        if cfg.get("tardiness_auto_send_enabled", True):
            send_time = cfg.get("tardiness_auto_send_time") or cfg.get("school_start_time", "07:00")
        else:
            root_widget.after(60_000, check_and_send)
            return
        try:
            h, m   = map(int, send_time.split(":"))
            target  = now.replace(hour=h, minute=m, second=0, microsecond=0)
            diff_s  = (target - now).total_seconds()
            if -90 <= diff_s <= 90:
                print(f"[TARDINESS-SCHED] ⏰ حان وقت الإرسال ({send_time}) — جارٍ الإرسال...")
                threading.Thread(target=send_tardiness_link_to_all, daemon=True).start()
                root_widget.after(300_000, check_and_send)
                return
        except Exception as e:
            print(f"[TARDINESS-SCHED] خطأ: {e}")
        root_widget.after(60_000, check_and_send)

    root_widget.after(30_000, check_and_send)


def _tardiness_page_html(students_list, title, back_url, base_url_str):
    """HTML مشترك لصفحة التأخر (فصل أو كل المدرسة)."""
    cfg        = load_config()
    start_time = cfg.get("school_start_time", "07:00")
    today      = now_riyadh_date()
    now_time   = datetime.datetime.now().strftime("%H:%M")

    # بناء قائمة الطلاب مرتبة أبجدياً
    students_sorted = sorted(students_list, key=lambda s: s.get("name", ""))

    rows_html = ""
    # بناء قاموس بيانات الطلاب كـ JSON لتجنب مشاكل الأحرف الخاصة
    import json as _json
    students_data_js = _json.dumps(
        {s.get("id",""): {"name": s.get("name",""), "cls": s.get("class_name","")}
         for s in students_sorted},
        ensure_ascii=False
    )

    for s in students_sorted:
        sid   = s.get("id","")
        sname = s.get("name","")
        scls  = s.get("class_name","")
        rows_html += """
        <div class="stu-row" id="row-{sid}">
          <div class="stu-info">
            <div class="stu-name">{sname}</div>
            <div class="stu-meta">{scls}</div>
          </div>
          <div class="stu-actions">
            <div class="stu-status" id="status-{sid}"></div>
            <button class="btn-late" onclick="addLate('{sid}')"
                    id="btn-add-{sid}">
              &#x23F1; تسجيل تأخر
            </button>
            <button class="btn-del" onclick="delLate('{sid}')"
                    id="btn-del-{sid}" style="display:none">
              &#x1F5D1; حذف
            </button>
          </div>
        </div>""".format(sid=sid, sname=sname, scls=scls)

    return f"""<!DOCTYPE html>\n<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>{title}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap');
*{{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}}
body{{font-family:'Cairo',sans-serif;background:#F5F7FA;direction:rtl;color:#1a1a2e}}
.header{{background:linear-gradient(135deg,#1565C0,#1976D2);color:#fff;padding:16px 20px;
          position:sticky;top:0;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,.2)}}
.header h2{{font-size:18px;font-weight:700}}
.header-sub{{font-size:12px;opacity:.85;margin-top:3px;display:flex;gap:16px;flex-wrap:wrap}}
.stats-bar{{display:flex;gap:10px;padding:12px 16px;background:#fff;
             border-bottom:1px solid #E0E7EF;flex-wrap:wrap}}
.stat{{background:#F0F4F8;border-radius:8px;padding:8px 14px;text-align:center;flex:1;min-width:100px}}
.stat-num{{font-size:22px;font-weight:900;color:#1565C0}}
.stat-lbl{{font-size:11px;color:#5A6A7E;margin-top:2px}}
.search-bar{{padding:12px 16px;background:#fff;border-bottom:1px solid #E0E7EF}}
.search-input{{width:100%;padding:10px 14px;border:1.5px solid #DDE3EA;border-radius:10px;
               font-family:'Cairo',sans-serif;font-size:14px;direction:rtl;background:#F5F7FA}}
.search-input:focus{{outline:none;border-color:#1565C0}}
.list{{padding:10px 12px;display:flex;flex-direction:column;gap:10px;padding-bottom:80px}}
.stu-row{{background:#fff;border-radius:14px;padding:18px 20px;
           display:flex;justify-content:space-between;align-items:center;gap:12px;
           box-shadow:0 2px 8px rgba(0,0,0,.08);transition:all .2s;min-height:76px}}
.stu-row.late-done{{border-right:5px solid #E65100;background:#FFF8E1}}
.stu-row.late-deleted{{border-right:4px solid #C62828;opacity:.6}}
.stu-info{{flex:1;min-width:0}}
.stu-name{{font-size:18px;font-weight:700;line-height:1.4;word-break:break-word}}
.stu-meta{{font-size:14px;color:#5A6A7E;margin-top:4px;font-weight:600}}
.stu-actions{{display:flex;flex-direction:column;gap:8px;align-items:flex-end;flex-shrink:0}}
.stu-status{{font-size:13px;font-weight:700;color:#E65100;direction:ltr;text-align:left}}
.btn-late{{background:#E65100;color:#fff;border:none;padding:13px 22px;
            border-radius:10px;font-family:'Cairo',sans-serif;font-size:15px;
            font-weight:700;cursor:pointer;white-space:nowrap;transition:all .18s;
            min-width:140px;text-align:center}}
.btn-late:active{{background:#BF360C;transform:scale(.97)}}
.btn-late:disabled{{background:#B0BEC5;cursor:not-allowed}}
.btn-del{{background:#FFEBEE;color:#C62828;border:1px solid #EF9A9A;
           padding:10px 16px;border-radius:10px;font-family:'Cairo',sans-serif;
           font-size:14px;font-weight:700;cursor:pointer;transition:all .18s}}
.btn-del:active{{background:#FFCDD2}}
.back-btn{{position:fixed;bottom:16px;right:16px;background:#1565C0;color:#fff;
            border:none;padding:12px 20px;border-radius:12px;font-family:'Cairo',sans-serif;
            font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 4px 12px rgba(21,101,192,.4)}}
#toast{{position:fixed;bottom:70px;left:50%;transform:translateX(-50%);
        background:#333;color:#fff;padding:10px 22px;border-radius:20px;
        font-size:13px;opacity:0;transition:opacity .3s;pointer-events:none;
        z-index:999;white-space:nowrap}}
#toast.show{{opacity:1}}
.empty{{text-align:center;padding:40px;color:#9E9E9E;font-size:15px}}
</style>
</head>
<body>
<div class="header">
  <h2>⏱ {title}</h2>
  <div class="header-sub">
    <span>📅 {today}</span>
    <span>🕐 بداية الدوام: {start_time}</span>
    <span id="current-time">⏰ {now_time}</span>
  </div>
</div>

<div class="stats-bar">
  <div class="stat"><div class="stat-num" id="stat-total">{len(students_sorted)}</div><div class="stat-lbl">إجمالي الطلاب</div></div>
  <div class="stat"><div class="stat-num" id="stat-late" style="color:#E65100">0</div><div class="stat-lbl">متأخرون</div></div>
  <div class="stat"><div class="stat-num" id="stat-avg" style="color:#C62828">—</div><div class="stat-lbl">متوسط التأخر</div></div>
</div>

<div class="search-bar">
  <input class="search-input" id="search" placeholder="🔍 بحث باسم الطالب..."
         oninput="filterStudents(this.value)">
</div>

<div class="list" id="list">{rows_html}</div>

<button class="back-btn" onclick="location.href='{back_url}'">← رجوع</button>
<div id="toast"></div>

<script>
const BASE  = "{base_url_str}";
const TODAY = "{today}";
const START = "{start_time}";
const STUDENTS = {students_data_js};
const lateRecords = {{}};  // sid -> {{id, time, minutes}}

function toast(msg, ok=true){{
  const t=document.getElementById('toast');
  t.textContent=msg; t.className='show';
  t.style.background=ok?'#2E7D32':'#C62828';
  setTimeout(()=>t.className='',2500);
}}

function updateStats(){{
  const cnt = Object.keys(lateRecords).length;
  document.getElementById('stat-late').textContent = cnt;
  if(cnt===0){{document.getElementById('stat-avg').textContent='—';return;}}
  const avg = Math.round(Object.values(lateRecords).reduce((s,r)=>s+r.minutes,0)/cnt);
  document.getElementById('stat-avg').textContent = avg+' د';
}}

function setCurrentTime(){{
  const now=new Date();
  const hh=String(now.getHours()).padStart(2,'0');
  const mm=String(now.getMinutes()).padStart(2,'0');
  document.getElementById('current-time').textContent='⏰ '+hh+':'+mm;
}}
setCurrentTime(); setInterval(setCurrentTime, 30000);

async function addLate(sid){{
  const stu  = STUDENTS[sid] || {{}};
  const sname= stu.name || sid;
  const scls = stu.cls  || '';
  const btn  = document.getElementById('btn-add-'+sid);
  btn.disabled=true; btn.textContent='⏳ جارٍ التسجيل...';

  const now=new Date();
  const hh=String(now.getHours()).padStart(2,'0');
  const mm=String(now.getMinutes()).padStart(2,'0');
  const registerTime=hh+':'+mm;

  try{{
    const r=await fetch(BASE+'/api/tardiness/add',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{
        date:TODAY, student_id:sid,
        student_name:sname, class_name:scls,
        register_time:registerTime
      }})
    }});
    const d=await r.json();
    if(d.ok){{
      lateRecords[sid]={{id:d.record_id, time:registerTime, minutes:d.minutes_late}};
      const row=document.getElementById('row-'+sid);
      row.classList.add('late-done');
      document.getElementById('status-'+sid).textContent=
        '⏱ '+registerTime+' ('+d.minutes_late+' دقيقة)';
      document.getElementById('btn-del-'+sid).style.display='inline-block';
      btn.textContent='✅ مسجّل';
      updateStats();
      toast('تم تسجيل تأخر '+sname+' ('+d.minutes_late+' دقيقة)');
    }}else{{
      toast(d.msg||'حدث خطأ',false);
      btn.disabled=false; btn.textContent='⏱ تسجيل تأخر';
    }}
  }}catch(e){{
    toast('خطأ في الاتصال: '+e,false);
    btn.disabled=false; btn.textContent='⏱ تسجيل تأخر';
  }}
}}

async function delLate(sid){{
  const rec=lateRecords[sid];
  if(!rec)return;
  if(!confirm('هل تريد حذف تأخر هذا الطالب؟'))return;
  const r=await fetch(BASE+'/api/tardiness/delete/'+rec.id,{{method:'DELETE'}});
  const d=await r.json();
  if(d.ok){{
    delete lateRecords[sid];
    const row=document.getElementById('row-'+sid);
    row.classList.remove('late-done');
    document.getElementById('status-'+sid).textContent='';
    document.getElementById('btn-del-'+sid).style.display='none';
    const btn=document.getElementById('btn-add-'+sid);
    btn.disabled=false; btn.textContent='⏱ تسجيل تأخر';
    updateStats();
    toast('تم حذف السجل');
  }}
}}

function filterStudents(q){{
  q=q.trim().toLowerCase();
  document.querySelectorAll('.stu-row').forEach(row=>{{
    const name=row.querySelector('.stu-name').textContent.toLowerCase();
    row.style.display=(!q||name.includes(q))?'flex':'none';
  }});
}}

// تحميل سجلات اليوم الحالية
async function loadToday(){{
  try{{
    const r=await fetch(BASE+'/api/tardiness/today');
    const d=await r.json();
    d.records.forEach(rec=>{{
      const sid=rec.student_id;
      lateRecords[sid]={{id:rec.id,time:rec.register_time||'',minutes:rec.minutes_late}};
      const row=document.getElementById('row-'+sid);
      if(!row)return;
      row.classList.add('late-done');
      document.getElementById('status-'+sid).textContent=
        '⏱ '+(rec.register_time||'')+'('+rec.minutes_late+' دقيقة)';
      const btn=document.getElementById('btn-add-'+sid);
      btn.textContent='✅ مسجّل'; btn.disabled=true;
      document.getElementById('btn-del-'+sid).style.display='inline-block';
    }});
    updateStats();
  }}catch(e){{console.warn('loadToday error:',e);}}
}}
loadToday();
</script>
</body></html>"""


@router.get("/tardiness", response_class=HTMLResponse)
def tardiness_all_page():
    """صفحة التأخر — جميع طلاب المدرسة مرتبين أبجدياً."""
    store   = load_students()
    base    = STATIC_DOMAIN if STATIC_DOMAIN and not debug_on() else f"http://{local_ip()}:{PORT}"
    all_stu = []
    for cls in store["list"]:
        for s in cls["students"]:
            all_stu.append({**s, "class_name": cls["name"]})
    html = _tardiness_page_html(
        students_list=all_stu,
        title="تسجيل التأخر — جميع الطلاب",
        back_url=f"{base}/mobile",
        base_url_str=base
    )
    return HTMLResponse(html)


@router.get("/tardiness/{class_id}", response_class=HTMLResponse)
def tardiness_class_page(class_id: str):
    """صفحة التأخر — طلاب فصل محدد."""
    store = load_students()
    cls   = store["by_id"].get(class_id)
    if not cls:
        return HTMLResponse("<h3>الفصل غير موجود</h3>", status_code=404)
    base  = STATIC_DOMAIN if STATIC_DOMAIN and not debug_on() else f"http://{local_ip()}:{PORT}"
    students = [{**s, "class_name": cls["name"]} for s in cls["students"]]
    html = _tardiness_page_html(
        students_list=students,
        title=f"تسجيل التأخر — {cls['name']}",
        back_url=f"{base}/mobile",
        base_url_str=base
    )
    return HTMLResponse(html)


@router.post("/api/tardiness/add")
async def api_tardiness_add(req: Request):
    """يُسجّل تأخر طالب ويحسب الدقائق تلقائياً."""
    data = await req.json()
    cfg  = load_config()

    student_id   = data.get("student_id","")
    student_name = data.get("student_name","")
    class_name   = data.get("class_name","")
    date_str     = data.get("date", now_riyadh_date())
    register_time= data.get("register_time", datetime.datetime.now().strftime("%H:%M"))

    # احسب الدقائق
    minutes_late = _calc_late_minutes(register_time, cfg)

    # ابحث عن class_id
    store    = load_students()
    class_id = ""
    for cls in store["list"]:
        if cls["name"] == class_name:
            class_id = cls["id"]
            break

    # أدخل في قاعدة البيانات مع حفظ وقت التسجيل
    # نستخدم INSERT OR IGNORE ثم UPDATE لتجنب مشكلة UNIQUE القديمة
    try:
        created_at = datetime.datetime.utcnow().isoformat()
        con = get_db(); cur = con.cursor()

        # تحقق أولاً: هل الطالب مسجّل اليوم بالفعل؟
        cur.execute("SELECT id FROM tardiness WHERE date=? AND student_id=?",
                    (date_str, student_id))
        existing = cur.fetchone()
        if existing:
            con.close()
            return JSONResponse({"ok": False, "msg": "الطالب مسجّل مسبقاً لهذا اليوم"})

        cur.execute("""INSERT INTO tardiness
            (date,class_id,class_name,student_id,student_name,
             teacher_name,period,minutes_late,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (date_str, class_id, class_name, student_id, student_name,
             "", None, minutes_late, created_at))
        record_id = cur.lastrowid
        con.commit(); con.close()
        return JSONResponse({
            "ok": True,
            "record_id": record_id,
            "minutes_late": minutes_late,
            "register_time": register_time
        })
    except sqlite3.IntegrityError as e:
        return JSONResponse({"ok": False, "msg": "الطالب مسجّل مسبقاً"})
    except Exception as e:
        return JSONResponse({"ok": False, "msg": str(e)}, status_code=500)


@router.delete("/api/tardiness/delete/{record_id}")
def api_tardiness_delete(record_id: int, request: Request):
    """يحذف سجل تأخر."""
    _denied = _deny_external(request)
    if _denied: return _denied
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("DELETE FROM tardiness WHERE id=?", (record_id,))
        con.commit(); con.close()
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "msg": str(e)}, status_code=500)


@router.get("/api/tardiness/today")
def api_tardiness_today(date: str = ""):
    """يُرجع سجلات التأخر لليوم مع وقت التسجيل."""
    date_str = date or now_riyadh_date()
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    # نستخدم created_at لاستخراج وقت التسجيل الفعلي
    cur.execute("""SELECT id, student_id, student_name, class_name,
                          minutes_late,
                          substr(created_at,12,5) as register_time
                   FROM tardiness WHERE date=?
                   ORDER BY class_name, student_name""", (date_str,))
    rows = [dict(r) for r in cur.fetchall()]; con.close()
    return {"records": rows, "count": len(rows)}


# ═══════════════════════════════════════════════════════════════
# NEW: PWA Mobile Portal
# ═══════════════════════════════════════════════════════════════

def mobile_portal_html() -> str:
    """Generates the main HTML for the PWA mobile portal with ALL services."""
    return """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>بوابة الغياب</title>
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#007bff">
        <link rel="apple-touch-icon" href="https://i.imgur.com/2h2h4vY.png">
        <style>
            :root {
                --primary-color: #007bff;
                --secondary-color: #6c757d;
                --bg-color: #f8f9fa;
                --card-bg: #ffffff;
                --text-color: #333;
                --success-color: #28a745;
                --warning-color: #ffc107;
                --danger-color: #dc3545;
            }
            body {
                font-family: 'Cairo', sans-serif;
                background-color: var(--bg-color);
                margin: 0;
                color: var(--text-color);
            }
            .header {
                background-color: var(--primary-color);
                color: white;
                padding: 20px;
                text-align: center;
                border-bottom-left-radius: 15px;
                border-bottom-right-radius: 15px;
            }
            .header h1 { margin: 0; font-size: 24px; }
            .header p { margin: 5px 0 0; opacity: 0.9; }
            .main-container { padding: 15px; }
            .card {
                background: var(--card-bg);
                border-radius: 12px;
                padding: 15px;
                margin-bottom: 15px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            }
            .card h2 {
                margin-top: 0;
                margin-bottom: 15px;
                font-size: 18px;
                border-bottom: 2px solid var(--primary-color);
                padding-bottom: 10px;
            }
            .grid-menu {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
                gap: 15px;
            }
            .menu-item {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 15px;
                background-color: #f1f3f5;
                border-radius: 10px;
                text-decoration: none;
                color: var(--text-color);
                font-weight: bold;
                text-align: center;
                transition: transform 0.2s;
            }
            .menu-item:hover { transform: translateY(-5px); }
            .menu-item .icon { font-size: 36px; }
            .live-monitor-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
                gap: 10px;
            }
            .monitor-cell {
                padding: 10px;
                border-radius: 8px;
                text-align: center;
            }
            .monitor-cell.done { background-color: #e9f7ef; color: var(--success-color); }
            .monitor-cell.pending { background-color: #fdf2f2; color: var(--danger-color); }
            .monitor-cell .period { font-weight: bold; }
            .monitor-cell .class-name { font-size: 14px; }
            #last-update { text-align: center; font-size: 12px; color: var(--secondary-color); margin-top: 10px; }
            #install-prompt {
                display: none;
                position: fixed;
                bottom: 0;
                left: 0;
                right: 0;
                background: #333;
                color: white;
                padding: 15px;
                text-align: center;
            }
            #install-prompt button {
                background: var(--primary-color);
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 5px;
                margin-right: 10px;
            }
        </style>
        <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap" rel="stylesheet">
    </head>
    <body>
        <div class="header">
            <h1 id="school-name">بوابة الغياب المدرسية</h1>
            <p>أهلاً بك</p>
        </div>
        <div class="main-container">
            <div class="card">
                <h2>الخدمات الكاملة</h2>
                <div class="grid-menu" id="main-menu">
                    <!-- سيتم ملؤها تلقائيًا -->
                </div>
            </div>
            <div class="card">
                <h2>لوحة المراقبة الحية</h2>
                <div class="live-monitor-grid" id="live-monitor">
                    <p>جاري تحميل البيانات...</p>
                </div>
                <p id="last-update"></p>
            </div>
        </div>
        <div id="install-prompt">
            <button id="install-btn">تثبيت التطبيق</button>
            <button id="dismiss-btn">لاحقًا</button>
        </div>
        <script>
            const schoolNameEl = document.getElementById('school-name');
            const mainMenuEl = document.getElementById('main-menu');
            const liveMonitorEl = document.getElementById('live-monitor');
            const lastUpdateEl = document.getElementById('last-update');

            async function fetchDataAndRender() {
                try {
                    const res = await fetch('/api/mobile-portal-data');
                    const data = await res.json();
                    schoolNameEl.textContent = data.school_name || 'بوابة الغياب';

                    // عرض جميع الخدمات (القديمة + الجديدة)
                    const allServices = [
                        { title: "تسجيل الغياب", url: data.class_links_page_url, icon: "📝" },
                        { title: "إرسال رسائل الغياب", url: data.send_messages_url, icon: "✉️" },
                        { title: "تعديل جدول الحصص", url: data.schedule_edit_url, icon: "🗓️" },
                        { title: "إضافة طالب جديد", url: data.add_student_url, icon: "➕" },
                        { title: "إدارة الطلاب والفصول", url: data.manage_students_url, icon: "🗑️" },
                        { title: "لوحة المراقبة", url: data.monitor_url, icon: "👁️" }
                    ];

                    let menuHtml = '';
                    allServices.forEach(item => {
                        menuHtml += `<a href="${{item.url}}" class="menu-item"><span class="icon">${{item.icon}}</span><span>${{item.title}}</span></a>`;
                    });
                    mainMenuEl.innerHTML = menuHtml;

                    // تحديث لوحة المراقبة
                    let monitorHtml = '';
                    if (data.live_status && data.live_status.length > 0) {
                        const now = new Date();
                        const currentHour = now.getHours();
                        let currentPeriod = 1;
                        if(currentHour >= 8) currentPeriod = 2;
                        if(currentHour >= 9) currentPeriod = 3;
                        if(currentHour >= 10) currentPeriod = 4;
                        if(currentHour >= 11) currentPeriod = 5;
                        if(currentHour >= 12) currentPeriod = 6;
                        if(currentHour >= 13) currentPeriod = 7;
                        const periodData = data.live_status.find(p => p.period === currentPeriod) || data.live_status[0];
                        monitorHtml += `<h3>الحصة ${{periodData.period}}</h3>`;
                        periodData.classes.forEach(c => {
                            monitorHtml += `
                                <div class="monitor-cell ${{c.status}}">
                                    <div class="class-name">${{c.class_name}}</div>
                                    <div class="status-icon">${{c.status === 'done' ? '✔️ تم' : '❌ بانتظار'}}</div>
                                </div>
                            `;
                        });
                        lastUpdateEl.textContent = 'آخر تحديث: ' + new Date().toLocaleTimeString();
                    } else {
                        monitorHtml = '<p>لا توجد بيانات مراقبة حاليًا.</p>';
                    }
                    liveMonitorEl.innerHTML = monitorHtml;
                } catch (e) {
                    liveMonitorEl.innerHTML = '<p>فشل تحميل البيانات. حاول التحديث.</p>';
                    console.error(e);
                }
            }

            // --- PWA Install Prompt ---
            let deferredPrompt;
            const installPrompt = document.getElementById('install-prompt');
            const installBtn = document.getElementById('install-btn');
            const dismissBtn = document.getElementById('dismiss-btn');
            window.addEventListener('beforeinstallprompt', (e) => {
                e.preventDefault();
                deferredPrompt = e;
                installPrompt.style.display = 'block';
            });
            installBtn.addEventListener('click', async () => {
                if (deferredPrompt) {
                    deferredPrompt.prompt();
                    await deferredPrompt.userChoice;
                    deferredPrompt = null;
                    installPrompt.style.display = 'none';
                }
            });
            dismissBtn.addEventListener('click', () => {
                installPrompt.style.display = 'none';
            });

            // --- Service Worker ---
            if ('serviceWorker' in navigator) {
                navigator.serviceWorker.register('/service-worker.js').catch(err => {
                    console.error('Service worker registration failed:', err);
                });
            }

            fetchDataAndRender();
            setInterval(fetchDataAndRender, 30000);
        </script>
    </body>
    </html>
    """

@router.get("/mobile", response_class=HTMLResponse)
def get_mobile_portal_page():
    return HTMLResponse(content=mobile_portal_html())


@router.get("/api/today-schedule")
def api_today_schedule():
    """يُرجع جدول اليوم الحالي مع أوقات الحصص."""
    import datetime as _dt
    now     = _dt.datetime.now()
    # تحويل Python weekday إلى يوم سعودي (0=الأحد)
    dow = (now.weekday() + 1) % 7   # Sun=0..Thu=4
    cfg = load_config()
    period_times = cfg.get("period_times",
        ["07:00","07:50","08:40","09:50","10:40","11:30","12:20"])
    schedule = load_schedule(dow)   # {(class_id, period): teacher}

    periods = []
    for i, pt in enumerate(period_times, 1):
        periods.append({"period": i, "time": pt})

    return JSONResponse({
        "day_of_week": dow,
        "current_time": now.strftime("%H:%M"),
        "period_times": period_times,
        "periods": periods,
    })

@router.get("/manifest.json")
def get_manifest():
    cfg = load_config()
    school_name = cfg.get("school_name", "نظام الغياب")
    return {
        "name": school_name,
        "short_name": "الغياب",
        "description": "نظام إدارة غياب الطلاب",
        "start_url": "/mobile",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#1565C0",
        "theme_color": "#1565C0",
        "lang": "ar",
        "dir": "rtl",
        "categories": ["education"],
        "icons": [
            { "src": "https://i.imgur.com/2h2h4vY.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable" },
            { "src": "https://i.imgur.com/gL6hS8q.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" }
        ],
        "screenshots": [],
        "shortcuts": [
            { "name": "تسجيل الغياب", "url": "/classes-list", "description": "فتح قائمة الفصول" },
            { "name": "التأخر", "url": "/tardiness", "description": "تسجيل التأخر" },
            { "name": "المراقبة", "url": "/monitor", "description": "مراقبة حية" }
        ]
    }

@router.get("/service-worker.js", response_class=Response)
def get_service_worker():
    js_content = """
// ─── Service Worker — DarbStu PWA v3 ────────────────────────
const CACHE = 'darb-v3';
const OFFLINE_URLS = ['/mobile', '/classes-list', '/tardiness'];

self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE).then(c => c.addAll(OFFLINE_URLS))
        .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', e => {
    if (e.request.method !== 'GET') return;
    e.respondWith(
        fetch(e.request)
            .then(resp => {
                const clone = resp.clone();
                caches.open(CACHE).then(c => c.put(e.request, clone));
                return resp;
            })
            .catch(() => caches.match(e.request))
    );
});

// ─── إشعارات Push ───────────────────────────────────────────
self.addEventListener('push', e => {
    let data = {};
    try { data = e.data.json(); } catch { data = { title: 'DarbStu', body: e.data.text() }; }
    e.waitUntil(
        self.registration.showNotification(data.title || 'DarbStu', {
            body:    data.body    || '',
            icon:    data.icon    || '/icon-192.png',
            badge:   '/icon-192.png',
            tag:     data.tag     || 'darb-notif',
            data:    data.url     || '/mobile',
            dir:     'rtl',
            lang:    'ar',
            vibrate: [200, 100, 200],
            requireInteraction: true
        })
    );
});

self.addEventListener('notificationclick', e => {
    e.notification.close();
    const url = e.notification.data || '/mobile';
    e.waitUntil(
        clients.matchAll({ type: 'window' }).then(ws => {
            for (const w of ws) {
                if (w.url.includes(url) && 'focus' in w) return w.focus();
            }
            if (clients.openWindow) return clients.openWindow(url);
        })
    );
});
"""
    return Response(content=js_content, media_type="application/javascript")

@router.get("/api/mobile-portal-data", response_class=JSONResponse)
def get_mobile_portal_data():
    cfg = load_config()
    base_url = STATIC_DOMAIN if STATIC_DOMAIN and not debug_on() else f"http://{local_ip()}:{PORT}"
    return {
        "school_name": cfg.get("school_name"),
        "live_status": get_live_monitor_status(now_riyadh_date()),
        "class_links_page_url": f"{base_url}/classes-list",
        "tardiness_url": f"{base_url}/tardiness",
        "send_messages_url": f"{base_url}/send-messages",
        "schedule_edit_url": f"{base_url}/schedule/edit",
        "tardiness_all_url": f"{base_url}/tardiness",
        "add_student_url": f"{base_url}/add-student-mobile",
        "manage_students_url": f"{base_url}/manage-students",
        "monitor_url": f"{base_url}/monitor"
    }

@router.get("/classes-list", response_class=HTMLResponse)
def get_classes_list_page():
    base_url = STATIC_DOMAIN if STATIC_DOMAIN and not debug_on() else f"http://{local_ip()}:{PORT}"
    nav = navbar_html(base_url)
    """A simple HTML page that lists all classes with links to their absence forms."""
    store = load_students()
    base_url = STATIC_DOMAIN if STATIC_DOMAIN and not debug_on() else f"http://{local_ip( )}:{PORT}"
    
    links_html = ""
    for c in sorted(store["list"], key=lambda x: x['id']):
        links_html += (
            '<div class="class-item">'
            '<a class="class-link" href="{base}/c/{cid}">{name} — غياب</a>'
            '<a class="class-link tard-link" href="{base}/tardiness/{cid}">{name} — تأخر</a>'
            '</div>'
        ).format(base=base_url, cid=c["id"], name=c["name"])

    return HTMLResponse(content=f"""\n<!DOCTYPE html>\n<html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>قائمة الفصول</title>
        <style>
            body {{ font-family: 'Cairo', sans-serif; background-color: #f8f9fa; margin: 0; padding: 15px; }}
            h1 {{ text-align: center; color: #333; }}
            .list-container {{ display: flex; flex-direction: column; gap: 10px; }}
            .class-link {{
                display: block;
                padding: 20px;
                background-color: #fff;
                border-radius: 10px;
                text-decoration: none;
                color: #007bff;
                font-weight: bold;
                font-size: 18px;
                text-align: center;
                box-shadow: 0 2px 8px rgba(0,0,0,0.07);
                transition: transform 0.2s;
            }}
            .class-link:hover {{ transform: scale(1.02); }}
        </style>
        <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap" rel="stylesheet">
    </head>
    <body>
        <h1>اختر الفصل لتسجيل الغياب</h1>
        <div class="list-container">
            {links_html}
        </div>
    </body>
    </html>
    """ )

# ===================== END PWA Mobile Portal =====================

# ===================== NEW: Mobile Send Messages =====================

def send_messages_html() -> str:
    base_url = STATIC_DOMAIN if STATIC_DOMAIN and not debug_on() else f"http://{local_ip()}:{PORT}"
    nav = navbar_html(base_url)
    """Generates the HTML page for sending absence messages from mobile."""
    return """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>إرسال رسائل الغياب</title>
        <style>
            body { font-family: 'Cairo', sans-serif; background-color: #f8f9fa; margin: 0; padding: 15px; }
            .container { max-width: 800px; margin: 0 auto; }
            h1 { text-align: center; color: #333; }
            .controls { display: flex; justify-content: space-between; align-items: center; padding: 10px; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.07); margin-bottom: 15px; }
            .controls button { background-color: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-family: 'Cairo'; }
            #send-btn { background-color: #28a745; }
            .student-list { list-style: none; padding: 0; }
            .student-item { display: flex; align-items: center; background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.07); }
            .student-item input[type='checkbox'] { width: 20px; height: 20px; margin-left: 15px; }
            .student-info { flex-grow: 1; }
            .student-info .name { font-weight: bold; }
            .student-info .class { font-size: 14px; color: #6c757d; }
            .status { padding: 5px 10px; border-radius: 15px; font-size: 12px; color: white; }
            .status.ready { background-color: #6c757d; }
            .status.sent { background-color: #28a745; }
            .status.failed { background-color: #dc3545; }
            #status-log { margin-top: 15px; font-size: 14px; text-align: center; }
        </style>
        <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap" rel="stylesheet">
    </head>
    <body>
        <div class="container">
            <h1>إرسال رسائل غياب اليوم</h1>
            <div class="controls">
                <button id="select-all-btn">تحديد الكل</button>
                <button id="send-btn">🚀 إرسال للمحددين</button>
            </div>
            <ul id="student-list-container" class="student-list">
                <!-- Students will be loaded here -->
            </ul>
            <div id="status-log">جاهز</div>
        </div>

        <script>
            const studentListContainer = document.getElementById('student-list-container' );
            const statusLog = document.getElementById('status-log');
            const sendBtn = document.getElementById('send-btn');
            const selectAllBtn = document.getElementById('select-all-btn');
            let isAllSelected = true;

            async function fetchAbsentStudents() {
                try {
                    statusLog.textContent = 'جاري تحميل قائمة الغياب...';
                    const res = await fetch('/api/absent-students-for-messaging');
                    const students = await res.json();
                    
                    if (students.length === 0) {
                        studentListContainer.innerHTML = '<p style="text-align:center;">لا يوجد طلاب غائبون اليوم.</p>';
                        statusLog.textContent = '';
                        return;
                    }

                    let studentsHtml = '';
                    students.forEach(s => {
                        studentsHtml += `
                            <li class="student-item" id="student-${{s.student_id}}">
                                <input type="checkbox" value="${{s.student_id}}" checked>
                                <div class="student-info">
                                    <div class="name">${{s.student_name}}</div>
                                    <div class="class">${{s.class_name}} | ${{s.phone || 'لا يوجد رقم'}}</div>
                                </div>
                                <div class="status ready">جاهز</div>
                            </li>
                        `;
                    });
                    studentListContainer.innerHTML = studentsHtml;
                    statusLog.textContent = `تم تحميل ${{students.length}} طالب.`;
                } catch (e) {
                    statusLog.textContent = 'فشل تحميل البيانات.';
                }
            }

            sendBtn.addEventListener('click', async () => {
                const selectedIds = Array.from(document.querySelectorAll("input[type='checkbox']:checked")).map(cb => cb.value);
                if (selectedIds.length === 0) {
                    alert('الرجاء تحديد طالب واحد على الأقل.');
                    return;
                }

                sendBtn.disabled = true;
                statusLog.textContent = `جاري إرسال ${{selectedIds.length}} رسالة...`;

                try {
                    const res = await fetch('/api/send-bulk-messages', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ student_ids: selectedIds })
                    });
                    const results = await res.json();
                    
                    results.forEach(result => {
                        const studentLi = document.getElementById(`student-${{result.student_id}}`);
                        if (studentLi) {
                            const statusDiv = studentLi.querySelector('.status');
                            statusDiv.textContent = result.success ? 'تم الإرسال' : 'فشل';
                            statusDiv.className = `status ${{result.success ? 'sent' : 'failed'}}`;
                        }
                    });
                    const successCount = results.filter(r => r.success).length;
                    const failedCount = results.length - successCount;
                    statusLog.textContent = `اكتمل: نجح ${{successCount}}، فشل ${{failedCount}}.`;

                } catch (e) {
                    statusLog.textContent = 'حدث خطأ فادح أثناء الإرسال.';
                } finally {
                    sendBtn.disabled = false;
                }
            });

            selectAllBtn.addEventListener('click', () => {
                const checkboxes = document.querySelectorAll("input[type='checkbox']");
                checkboxes.forEach(cb => cb.checked = !isAllSelected);
                isAllSelected = !isAllSelected;
                selectAllBtn.textContent = isAllSelected ? 'إلغاء تحديد الكل' : 'تحديد الكل';
            });

            fetchAbsentStudents();
        </script>
    </body>
    </html>
    """

@router.get("/send-messages", response_class=HTMLResponse)
def get_send_messages_page(request: Request):
    if _deny_external(request):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/web/login")
    return HTMLResponse(content=send_messages_html())

@router.get("/api/absent-students-for-messaging", response_class=JSONResponse)
def get_absent_students_for_messaging_api(request: Request):
    """Returns a list of unique absent students for the current day."""
    _denied = _deny_external(request)
    if _denied: return _denied
    today = now_riyadh_date()
    absent_groups = build_absent_groups(today)
    
    students_list = []
    for class_id, data in absent_groups.items():
        for student in data["students"]:
            students_list.append({
                "student_id": student["id"],
                "student_name": student["name"],
                "class_name": data["class_name"],
                "phone": student.get("phone")
            })
    return JSONResponse(content=sorted(students_list, key=lambda x: (x['class_name'], x['student_name'])))

@router.get("/monitor", response_class=HTMLResponse)
def get_monitor_page(request: Request):
    if _deny_external(request):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/web/login")
    return HTMLResponse(content=live_monitor_html_page())

@router.get("/api/live_status", response_class=JSONResponse)
def get_status_api(request: Request):
    _denied = _deny_external(request)
    if _denied: return _denied
    today = now_riyadh_date()
    status_data = get_live_monitor_status(today)
    return JSONResponse(content=status_data)

def schedule_editor_html() -> str:
    base_url = STATIC_DOMAIN if STATIC_DOMAIN and not debug_on() else f"http://{local_ip()}:{PORT}"
    nav = navbar_html(base_url)
    style_css = """
        body { font-family: 'Cairo', 'Segoe UI', sans-serif; background-color: #f5f5f5; margin: 0; padding: 20px; }
        .container { max-width: 1600px; margin: 0 auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { text-align: center; color: #333; }
        .controls { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding: 10px; background: #f9f9f9; border-radius: 6px; }
        .day-selector button { font-size: 16px; padding: 10px 15px; margin: 0 5px; border: 1px solid #ccc; background: #fff; border-radius: 6px; cursor: pointer; transition: all 0.2s; }
        .day-selector button.active { background-color: #007bff; color: white; border-color: #007bff; }
        #save-btn { font-size: 16px; padding: 10px 20px; border: none; background-color: #28a745; color: white; border-radius: 6px; cursor: pointer; }
        #save-btn:hover { background-color: #218838; }
        #status { font-weight: bold; }
        .table-container { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: center; min-width: 150px; }
        th { background-color: #f2f2f2; font-weight: bold; }
        td select { width: 100%; padding: 5px; border-radius: 4px; border: 1px solid #ccc; }
    """
    return f"""\n<!DOCTYPE html>\n<html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>تعديل جدول الحصص</title>
        <style>{style_css}</style>
        <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap" rel="stylesheet">
    </head>
    <body>
        {nav}
        <div class="container">
            <h1>تعديل جدول الحصص المدرسي</h1>
            <div class="controls">
                <div class="day-selector">
                    <button data-day="0" class="active">الأحد</button>
                    <button data-day="1">الاثنين</button>
                    <button data-day="2">الثلاثاء</button>
                    <button data-day="3">الأربعاء</button>
                    <button data-day="4">الخميس</button>
                </div>
                <div>
                    <span id="status"></span>
                    <button id="save-btn">💾 حفظ الجدول الحالي</button>
                </div>
            </div>
            <div class="table-container">
                <table id="schedule-table">
                    <thead></thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>
        <script>
            let currentDay = 0;
            let teacherOptions = '';
            const statusEl = document.getElementById('status');
            const saveBtn = document.getElementById('save-btn');
            const dayButtons = document.querySelectorAll('.day-selector button');

            async function fetchAndRenderSchedule(day) {{
                try {{
                    statusEl.textContent = 'جاري التحميل...';
                    const res = await fetch(`/api/schedule-data/${{day}}`);
                    if (!res.ok) throw new Error('Failed to fetch data');
                    const data = await res.json();

                    if (!teacherOptions) {{
                        teacherOptions = '<option value="">— فارغ —</option>';
                        data.teachers.forEach(t => {{
                            teacherOptions += `<option value="${{t['اسم المعلم']}}">${{t['اسم المعلم']}}</option>`;
                        }});
                    }}

                    const tableHead = document.querySelector('#schedule-table thead');
                    const tableBody = document.querySelector('#schedule-table tbody');

                    let headerHtml = '<tr><th>الحصة</th>';
                    data.classes.forEach(c => {{ headerHtml += `<th>${{c.name}}</th>`; }});
                    headerHtml += '</tr>';
                    tableHead.innerHTML = headerHtml;

                    let bodyHtml = '';
                    for (let period = 1; period <= 7; period++) {{
                        bodyHtml += `<tr><td>الحصة ${{period}}</td>`;
                        data.classes.forEach(c => {{
                            bodyHtml += `<td><select data-class-id="${{c.id}}" data-period="${{period}}">${{teacherOptions}}</select></td>`;
                        }});
                        bodyHtml += '</tr>';
                    }}
                    tableBody.innerHTML = bodyHtml;

                    tableBody.querySelectorAll('select').forEach(select => {{
                        const classId = select.dataset.classId;
                        const period = select.dataset.period;
                        select.value = data.schedule[`${{classId}},${{period}}`] || '';
                    }});
                    statusEl.textContent = 'تم التحميل.';
                }} catch (error) {{
                    statusEl.textContent = 'خطأ في تحميل البيانات.';
                }}
            }}

            saveBtn.addEventListener('click', async () => {{
                const scheduleData = [];
                document.querySelectorAll('#schedule-table tbody select').forEach(select => {{
                    if (select.value) {{
                        scheduleData.push({{
                            class_id: select.dataset.classId,
                            period: parseInt(select.dataset.period),
                            teacher_name: select.value
                        }});
                    }}
                }});
                try {{
                    statusEl.textContent = 'جاري الحفظ...';
                    const res = await fetch('/api/save-schedule', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ day_of_week: currentDay, schedule_data: scheduleData }})
                    }});
                    if (!res.ok) throw new Error('Failed to save');
                    statusEl.textContent = 'تم الحفظ بنجاح!';
                }} catch (error) {{
                    statusEl.textContent = 'خطأ في الحفظ.';
                }}
            }});

            dayButtons.forEach(btn => {{
                btn.addEventListener('click', () => {{
                    currentDay = parseInt(btn.dataset.day);
                    dayButtons.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    fetchAndRenderSchedule(currentDay);
                }});
            }});

            fetchAndRenderSchedule(currentDay);
        </script>
    </body>
    </html>
    """

@router.get("/schedule/edit", response_class=HTMLResponse)
def get_schedule_edit_page(request: Request):
    if _deny_external(request):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/web/login")
    return HTMLResponse(content=schedule_editor_html())

@router.get("/api/schedule-data/{day_of_week}", response_class=JSONResponse)
def get_schedule_data_api(day_of_week: int):
    classes = sorted(load_students()["list"], key=lambda c: c['id'])
    teachers = load_teachers().get("teachers", [])
    schedule_raw = load_schedule(day_of_week)
    schedule = {f"{k[0]},{k[1]}": v for k, v in schedule_raw.items()}
    return {"classes": classes, "teachers": teachers, "schedule": schedule}

@router.post("/api/save-schedule", response_class=JSONResponse)
async def save_schedule_api(request: Request):
    _denied = _deny_external(request)
    if _denied: return _denied
    data = await request.json()
    day_of_week = data.get("day_of_week")
    schedule_data = data.get("schedule_data")
    if day_of_week is None or schedule_data is None:
        return JSONResponse(content={"error": "Missing data"}, status_code=400)
    try:
        save_schedule(day_of_week, schedule_data)
        return {"message": "تم الحفظ بنجاح"}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@router.post("/api/bot/excuse")
async def api_bot_excuse(req: Request):
    """يستقبل العذر من بوت الواتساب ويحفظه في قاعدة البيانات."""
    try:
        data = await req.json()
        student_id   = data.get("student_id", "")
        student_name = data.get("student_name", "")
        class_id     = data.get("class_id", "")
        class_name   = data.get("class_name", "")
        date_str     = data.get("date", now_riyadh_date())
        reason       = data.get("reason", "")
        parent_phone = data.get("parent_phone", "")

        if not student_id or not student_name:
            return JSONResponse({"ok": False, "error": "بيانات ناقصة"}, status_code=400)

        if student_has_excuse(student_id, date_str):
            return JSONResponse({"ok": True, "note": "العذر مسجّل مسبقاً"})

        insert_excuse(date_str, student_id, student_name,
                      class_id, class_name, reason,
                      source="whatsapp", approved_by=parent_phone)

        print(f"[BOT] ✅ عذر محفوظ: {student_name} — {date_str} — {reason}")
        return JSONResponse({"ok": True})
    except Exception as e:
        print(f"[BOT] ❌ خطأ في حفظ العذر: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/api/bot/permission")
async def api_bot_permission(req: Request):
    """يستقبل موافقة/رفض ولي الأمر على طلب الاستئذان من البوت."""
    try:
        data          = await req.json()
        permission_id = int(data.get("permission_id", 0))
        status        = data.get("status", "")
        parent_phone  = data.get("parent_phone", "")

        if not permission_id or status not in (PERM_APPROVED, PERM_REJECTED):
            return JSONResponse({"ok": False, "error": "بيانات غير صحيحة"}, status_code=400)

        exit_time = datetime.datetime.now().strftime("%H:%M") \
                    if status == PERM_APPROVED else None
        update_permission_status(permission_id, status, exit_time)

        print(f"[BOT-PERM] ✅ استئذان #{permission_id} — {status} — {parent_phone}")
        return JSONResponse({"ok": True, "msg": "تم تحديث حالة الاستئذان"})
    except Exception as e:
        print(f"[BOT-PERM] ❌ خطأ: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/parent/{student_id}", response_class=HTMLResponse)
async def parent_portal_page(student_id: str):
    """لوحة ولي الأمر — رابط شخصي لكل طالب."""
    try:
        return HTMLResponse(content=parent_portal_html(student_id))
    except Exception as e:
        return HTMLResponse(content="<h2>خطأ: {}</h2>".format(e), status_code=500)

@router.get("/results", response_class=HTMLResponse)
async def results_portal():
    """بوابة النتائج — صفحة البحث برقم الهوية."""
    return HTMLResponse(content=results_portal_html())

def _is_excellent_student(pdf_path: str, page_no: int) -> bool:
    """يتحقق إذا كان الطالب ممتازاً في جميع مواده."""
    import re as _re
    try:
        import pdfplumber
        with pdfplumber.open(os.path.abspath(pdf_path)) as pdf:
            text = pdf.pages[page_no].extract_text() or ""
        grades = _re.findall(
            r'\b(Excellent \+|Excellent|Very Good \+|Very Good|Good \+|Good|'
            r'Satisfactory \+|Satisfactory|Pass|Weak|Fail)\b', text)
        # فلتر الكلمات من الترويسة
        subject_grades = [g for g in grades if g in [
            "Excellent +","Excellent","Very Good +","Very Good",
            "Good +","Good","Satisfactory +","Satisfactory","Pass","Weak","Fail"]]
        if not subject_grades:
            return False
        return all("Excellent" in g for g in subject_grades)
    except Exception:
        return False


@router.get("/results/{identity_no}", response_class=HTMLResponse)
async def student_result_page(identity_no: str):
    """صفحة نتيجة طالب — تعرض صورة الشهادة + رسالة تهنئة للممتازين."""
    try:
        result = get_student_result(identity_no)
        if not result:
            return HTMLResponse(
                content="<h2 style='font-family:Arial;text-align:center;padding:40px;color:#c00'>رقم الهوية غير موجود في قاعدة البيانات</h2>",
                status_code=404)
        cfg = load_config()
        school = cfg.get("school_name", "المدرسة")

        # تحقق من تقدير الطالب
        pdf_path = result.get("pdf_path", "")
        page_no  = int(result.get("page_no", 0))
        is_excellent = (
            os.path.exists(pdf_path) and
            _is_excellent_student(pdf_path, page_no)
        )

        student_name = result.get("student_name", "")

        congrats_html = ""
        if is_excellent:
            congrats_html = f"""\n<div style="
    background: linear-gradient(135deg, #1B5E20, #2E7D32);
    color: #fff;
    border-radius: 12px;
    padding: 28px 24px;
    margin: 16px auto;
    max-width: 900px;
    text-align: center;
    font-family: Arial, sans-serif;
    box-shadow: 0 6px 24px rgba(46,125,50,0.35);
    direction: rtl;
">
  <div style="font-size: 48px; margin-bottom: 10px;">🏆</div>
  <h2 style="font-size: 22px; margin-bottom: 12px; font-weight: 900;">
    تهانينا يا {student_name} 🌟
  </h2>
  <p style="font-size: 16px; line-height: 2; margin-bottom: 14px;">
    يسعد إدارة <strong>{school}</strong> أن تُهنئكم على هذا التفوق الرائع
    وتُقدّر جهودكم المتميزة في جميع المواد الدراسية.
  </p>
  <p style="font-size: 15px; line-height: 2; margin-bottom: 14px;">
    كما يمتد الشكر والتقدير إلى <strong>أسرة الطالب الكريمة</strong>
    على دعمهم المتواصل ومساندتهم التي كانت سبباً في هذا التميز والنجاح المشرّف.
  </p>
  <p style="font-size: 15px; line-height: 2;">
    ✨ نتمنى لك مزيداً من التفوق والنجاح والتألق في مسيرتك العلمية ✨
  </p>
  <div style="margin-top:18px; padding-top:14px; border-top:1px solid rgba(255,255,255,0.3); font-size:13px; opacity:0.85;">
    إدارة {school}
  </div>
</div>"""

        html = f"""<!DOCTYPE html>\n<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=5">
<title>نتيجة {student_name} — {school}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Arial,sans-serif;background:#f0f4f8;min-height:100vh;padding:20px}}
.card{{background:#fff;border-radius:12px;max-width:900px;margin:0 auto;box-shadow:0 4px 20px rgba(0,0,0,.12);overflow:hidden}}
.hdr{{background:#1A237E;color:#fff;padding:16px 20px;text-align:center}}
.hdr h2{{font-size:18px;margin-bottom:4px}}
.hdr p{{font-size:13px;opacity:.85}}
.cert-img{{width:100%;display:block}}
.footer{{text-align:center;padding:12px;color:#666;font-size:12px}}
</style>
</head>
<body>
{congrats_html}
<div class="card">
  <div class="hdr">
    <h2>🎓 شهادة نتيجة الطالب</h2>
    <p>{school}</p>
  </div>
  <img class="cert-img" src="/api/results-image/{identity_no}" alt="شهادة الطالب" />
  <div class="footer">هذه الشهادة خاصة بالطالب — رقم الهوية: {identity_no}</div>
</div>
</body>
</html>"""
        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(content=f"<h2>خطأ: {e}</h2>", status_code=500)

@router.get("/api/results-image/{identity_no}")
async def student_result_image(identity_no: str):
    """يرجع صورة JPEG لصفحة الشهادة من ملف PDF مباشرة."""
    try:
        result = get_student_result(identity_no)
        if not result:
            return Response(content=b"", status_code=404)
        pdf_path = result.get("pdf_path", "")
        page_no  = int(result.get("page_no", 0))
        
        # Fallback: إذا لم يوجد الملف في المسار المخزن، ابحث عنه في مجلد النتائج الافتراضي
        if not pdf_path or not os.path.exists(pdf_path):
            year = result.get("school_year", "")
            alt_path = os.path.join(DATA_DIR, "results", f"results_{year}.pdf")
            if os.path.exists(alt_path):
                pdf_path = alt_path
            else:
                # محاولة أخرى بالاسم الافتراضي
                alt_path2 = os.path.join(DATA_DIR, "results", "results_current.pdf")
                if os.path.exists(alt_path2):
                    pdf_path = alt_path2

        if not pdf_path or not os.path.exists(pdf_path):
            return Response(content=b"", status_code=404,
                            media_type="text/plain")
                            
        img_bytes = _render_pdf_page_as_png(pdf_path, page_no, dpi=150)
        return Response(content=img_bytes, media_type="image/jpeg")
    except Exception as e:
        print(f"[RESULTS IMAGE] خطأ: {e}")
        return Response(content=b"", status_code=500)

@router.get("/api/results/{identity_no}", response_class=JSONResponse)
async def api_check_result(identity_no: str):
    """يتحقق من وجود نتيجة لرقم هوية معين."""
    identity_no = identity_no.strip()
    result = get_student_result(identity_no)
    
    return JSONResponse({
        "ok": result is not None
    })

@router.post("/api/send-bulk-messages", response_class=JSONResponse)
async def send_bulk_messages_api(request: Request):
    """Receives a list of student IDs and sends them absence alerts."""
    _denied = _deny_external(request)
    if _denied: return _denied
    data = await request.json()
    student_ids = data.get("student_ids", [])
    today = now_riyadh_date()
    
    absent_groups = build_absent_groups(today)
    all_absent_students = {}
    for class_id, class_data in absent_groups.items():
        for student in class_data["students"]:
            all_absent_students[student["id"]] = {**student, "class_name": class_data["class_name"]}

    results = []
    for sid in student_ids:
        student_details = all_absent_students.get(sid)
        if not student_details:
            results.append({"student_id": sid, "success": False, "message": "Student not found in today's absence list."})
            continue

        success, message = send_absence_alert(
            student_id=sid,
            student_name=student_details["name"],
            class_name=student_details["class_name"],
            date_str=today
        )
        results.append({"student_id": sid, "success": success, "message": message})
        
        try:
            log_message_status(
                date_str=today, student_id=sid, student_name=student_details["name"],
                class_id=student_details.get("class_id", ""), class_name=student_details["class_name"],
                phone=student_details.get("phone", ""), status=message, template_used=get_message_template()
            )
        except Exception as e:
            print(f"Error logging message status for {sid}: {e}")

    return JSONResponse(content=results)

# ===================== END Mobile Send Messages =====================

# ===================== تشغيل واتساب سيرفر =====================
def start_whatsapp_server():
    try:
        if not os.path.isdir(WHATS_PATH):
            messagebox.showerror("خطأ", f"المجلد غير موجود:\n{WHATS_PATH}")
            return
        from whatsapp_service import start_whatsapp_server
        start_whatsapp_server()
        messagebox.showinfo("تم", "تم فتح نافذة الواتساب سيرفر.\nامسح رمز الـ QR من النافذة الجديدة.")
    except Exception as e:
        messagebox.showerror("خطأ", f"تعذّر تشغيل السيرفر:\n{e}")

