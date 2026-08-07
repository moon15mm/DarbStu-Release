# -*- coding: utf-8 -*-
"""
api/misc_routes.py — مسارات متنوعة: النتائج، ولي الأمر، البوت، الرسائل الجماعية
"""
import datetime, json, base64, os, io
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from constants import (DB_PATH, DATA_DIR, HOST, PORT, now_riyadh_date,
                       STATIC_DOMAIN, CURRENT_USER, debug_on)
from config_manager import load_config, get_terms, render_message
from database import (get_db, load_students, query_absences,
                      insert_excuse, query_excuses, student_has_excuse)
from whatsapp_service import send_whatsapp_message
from pdf_generator import (_render_pdf_page_as_png, _render_page_pillow,
                            get_student_result, save_results_to_db, parse_results_pdf,
                            results_portal_html, student_result_html)
from report_builder import parent_portal_html
from alerts_service import (log_message_status, query_permissions,
                             insert_permission, update_permission_status,
                             save_schedule, load_schedule)

router = APIRouter()

# ─── إعدادات CORS للامتداد ────────────────────────────────────
_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
}

# ─── جلب الإعدادات تلقائياً للامتداد ─────────────────────────
@router.get("/web/api/extension-setup", response_class=JSONResponse)
async def extension_setup(request: Request):
    """
    يُعيد رابط السيرفر ورمز الأمان للامتداد — بدون مصادقة.
    مقيّد بالجهاز المحلي فقط (localhost / 127.0.0.1).
    """
    client_host = request.client.host if request.client else ""
    # cloudflared يتصل بالتطبيق من 127.0.0.1، فلا يكفي فحص عنوان العميل وحده:
    # أي طلب مُمرَّر عبر وسيط يحمل ترويسات إعادة التوجيه، ووجودها يعني أن
    # الطلب قادم من خارج الجهاز حتى لو بدا محلياً.
    forwarded = any(request.headers.get(h) for h in
                    ("x-forwarded-for", "x-real-ip", "cf-connecting-ip",
                     "cf-ray", "forwarded"))
    if forwarded or client_host not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse(
            {"ok": False, "error": "متاح من الجهاز المحلي فقط"},
            status_code=403,
            headers={"Access-Control-Allow-Origin": "*"},
        )
    cfg        = load_config()
    cloud_url  = cfg.get("cloud_url", "").strip().rstrip("/")
    token      = cfg.get("cloud_token", "").strip()
    server_url = cloud_url or f"http://{request.headers.get('host', 'localhost:8000')}"
    return JSONResponse(
        {"ok": True, "server_url": server_url, "token": token},
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ─── صفحة محاكاة نور (للاختبار المحلي فقط) ──────────────────

def _build_test_groups() -> list:
    """
    يُعيد قائمة مجموعات الغياب للاختبار:
    - أولاً: يجرب غياب اليوم الفعلي من قاعدة البيانات
    - ثانياً (إن لم يوجد): يأخذ أول طالبين من أول 3 فصول
    """
    today = datetime.date.today().isoformat()
    try:
        rows = query_absences(date_filter=today)
    except Exception:
        rows = []

    if rows:
        by_class: dict = {}
        for r in rows:
            cname = r.get("class_name") or r.get("class_id") or "غير محدد"
            by_class.setdefault(cname, []).append({
                "student_id":   str(r.get("student_id", "")),
                "student_name": r.get("student_name", ""),
            })
        return [{"class_name": c, "students": s} for c, s in by_class.items()]

    try:
        store   = load_students()
        classes = store.get("list", [])
    except Exception:
        classes = []

    groups = []
    for cls in classes[:3]:
        sts = cls.get("students", [])[:2]
        if sts:
            groups.append({
                "class_name": cls.get("name", "فصل"),
                "students": [
                    {"student_id": str(s.get("id", "")), "student_name": s.get("name", "")}
                    for s in sts
                ],
            })
    return groups


def _load_mock_students() -> list:
    try:
        store  = load_students()
        result = []
        for cls in store.get("list", []):
            cls_name = cls.get("name", "")
            for s in cls.get("students", []):
                result.append({
                    "id":         str(s.get("id", "")),
                    "name":       s.get("name", ""),
                    "class_name": cls_name,
                })
        return result
    except Exception:
        return []


def _build_noor_mock_html() -> str:
    today_str    = datetime.date.today().strftime("%d/%m/%Y")
    all_students = _load_mock_students()
    if not all_students:
        all_students = [{"id": "0000000001", "name": "مثال — لم تُستورد بيانات الطلاب بعد", "class_name": "—"}]
    js_all = json.dumps(all_students, ensure_ascii=False)

    html_top = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>محاكاة نور — ManageAttendance [اختبار محلي]</title>
<style>
*{box-sizing:border-box}
body{font-family:Tahoma,Arial;font-size:13px;background:#f5f5f5;direction:rtl;margin:0}
.top-bar{background:#007b6e;color:white;padding:8px 16px;font-size:14px;font-weight:bold;display:flex;align-items:center;gap:12px}
.mock-badge{background:#ff9800;color:white;font-size:11px;padding:3px 10px;border-radius:12px;font-weight:bold}
.container{display:flex;gap:0;min-height:calc(100vh - 40px)}
.noor-side{flex:1;padding:16px}
.log-side{width:340px;background:#1e1e1e;color:#d4d4d4;font-family:Consolas,monospace;font-size:12px;padding:12px;overflow-y:auto;max-height:calc(100vh - 40px)}
.log-side h3{color:#4fc3f7;margin:0 0 10px;font-size:13px}
.log-entry{padding:3px 0;border-bottom:1px solid #333;line-height:1.5}
.log-ok{color:#81c784}.log-err{color:#ef5350}.log-inf{color:#fff176}.log-act{color:#4fc3f7}
.form-table{width:100%;border-collapse:collapse;background:white;border:1px solid #ccc;margin-bottom:12px}
.form-table td{padding:7px 10px;border:1px solid #e0e0e0;vertical-align:middle}
.form-table .lbl{background:#f9f9f9;color:#333;white-space:nowrap;text-align:right;width:140px}
.form-table .lbl.req::after{content:" *";color:red}
select,input[type=text]{padding:5px 8px;border:1px solid #ccc;border-radius:3px;font-family:Tahoma;font-size:12px;width:100%}
.btn-search{background:#007b6e;color:white;border:none;padding:8px 24px;cursor:pointer;font-family:Tahoma;font-size:13px;border-radius:3px}
.btn-back{background:#666;color:white;border:none;padding:8px 18px;cursor:pointer;font-family:Tahoma;font-size:13px;border-radius:3px;margin-right:8px}
.btn-save{background:#1565C0;color:white;border:none;padding:8px 24px;cursor:pointer;font-family:Tahoma;font-size:13px;border-radius:3px}
.results-section{display:none}
.results-table{width:100%;border-collapse:collapse;background:white;border:1px solid #ccc}
.results-table th{background:#007b6e;color:white;padding:8px;text-align:center;font-size:12px;border:1px solid #006358}
.results-table td{padding:6px 8px;border:1px solid #e0e0e0;text-align:center}
.results-table tr:hover{background:#f0fff8}
.save-row{margin-top:12px;text-align:center;padding:8px;background:white;border:1px solid #ccc}
.page-title{font-size:16px;font-weight:bold;color:#007b6e;margin-bottom:12px;padding:8px 12px;background:white;border-right:4px solid #007b6e}
.result-summary{background:#e8f5e9;border:1px solid #a5d6a7;padding:8px 12px;border-radius:4px;margin-bottom:8px;font-size:12px;color:#2e7d32;display:none}
.db-note{background:#fff3e0;border:1px solid #ffcc80;padding:6px 12px;font-size:11px;color:#e65100;margin-bottom:8px;border-radius:3px}
</style></head><body>
<div class="top-bar">
  <span>&#127978; نور — محاكاة نظام إدخال السلوك والمواظبة</span>
  <span class="mock-badge">&#129514; بيئة اختبار محلية</span>
</div>
<div class="container">
<div class="noor-side">
  <div class="page-title">إدخال السلوك والمواظبة</div>
  <table class="form-table" id="search-form">
    <tr>
      <td class="lbl req">النظام الدراسي</td>
      <td><select id="sel-system"><option>ليلي</option><option>نهاري</option></select></td>
      <td class="lbl req">نوع الحسم</td>
      <td><select id="sel-hosm"><option value="">-- اختر --</option><option>المواظبة</option><option>السلوك</option></select></td>
    </tr>
    <tr><td class="lbl">إدارة التعليم</td><td colspan="3" style="color:#555">الإدارة العامة للتعليم</td></tr>
    <tr><td class="lbl">المدرسة</td><td colspan="3" style="color:#555">المدرسة</td></tr>
    <tr>
      <td class="lbl req">نوع الغياب</td>
      <td><select id="sel-abstype"><option value="">-- اختر --</option><option>يوم كامل</option><option>حصة</option></select></td>
      <td></td><td></td>
    </tr>
    <tr>
      <td class="lbl req">التاريخ</td>
      <td colspan="3">
        <input type="text" id="date-h" value="21/11/1447" style="width:130px;margin-left:8px">
        <input type="text" id="date-m" value="DATE_PLACEHOLDER" style="width:130px">
      </td>
    </tr>
    <tr>
      <td class="lbl req">الصف</td>
      <td><select id="sel-grade" onchange="onGradeChange()">
        <option value="">-- اختر --</option>
        <option>الثاني الثانوي</option><option>الثالث الثانوي</option><option>الأول الثانوي</option>
      </select></td>
      <td></td><td></td>
    </tr>
    <tr>
      <td class="lbl">القسم</td>
      <td><select id="sel-track" onchange="onTrackChange()">
        <option value="">-- اختر --</option>
        <option>مسار إدارة الأعمال</option><option>مسار العلوم</option><option>مسار الآداب</option>
      </select></td>
      <td class="lbl">الطلاب</td>
      <td><select id="sel-students"><option>-- الكل --</option></select></td>
    </tr>
    <tr>
      <td class="lbl">الفصل</td>
      <td><select id="sel-room">
        <option>-- الكل --</option><option>1</option><option>2</option><option>3</option>
      </select></td>
      <td></td><td></td>
    </tr>
    <tr>
      <td colspan="4" style="text-align:center;padding:12px;background:#fafafa">
        <input type="submit" value="ابحث" class="btn-search" id="btn-search" onclick="doSearch();return false;">
        <input type="button" value="عودة" class="btn-back">
      </td>
    </tr>
  </table>
  <div class="results-section" id="results-section">
    <div class="db-note">&#128273; البيانات محمّلة من قاعدة DarbStu — عدد الطلاب الكلي: <b id="total-count">0</b></div>
    <div class="result-summary" id="result-summary"></div>
    <div style="font-size:11px;color:#c00;margin-bottom:6px">&#9668; لتسجيل مخالفة ضع علامة على يمين اسم الطالب، ثم اختر نوع المخالفة</div>
    <table class="results-table" id="results-table">
      <thead><tr>
        <th style="width:40px"><input type="checkbox" id="chk-all" onchange="toggleAll(this)"></th>
        <th>اسم الطالب</th><th>الفصل (DarbStu)</th><th>نوع المخالفة</th>
      </tr></thead>
      <tbody id="results-body"></tbody>
    </table>
    <div class="save-row">
      <input type="submit" value="حفظ" class="btn-save" id="btn-save" onclick="doSave();return false;">
      <input type="button" value="عودة" class="btn-back" style="margin-right:8px">
    </div>
  </div>
</div>
<div class="log-side">
  <h3>&#128225; سجل تصرفات الامتداد</h3>
  <div id="ext-log"><div class="log-entry log-inf">&#9203; في انتظار بدء الامتداد...</div></div>
  <div style="margin-top:12px;padding-top:8px;border-top:1px solid #444">
    <div style="color:#aaa;font-size:11px">إحصاء:</div>
    <div id="stats" style="color:#81c784;font-size:12px;margin-top:4px">—</div>
  </div>
  <button onclick="document.getElementById('ext-log').innerHTML='';statsSaved=0;"
    style="margin-top:10px;width:100%;padding:5px;background:#333;color:#aaa;border:1px solid #555;cursor:pointer;font-size:11px">
    &#128465; مسح السجل
  </button>
</div>
</div>
<script>
const STUDENTS_ALL = JS_ALL_PLACEHOLDER;
document.getElementById("total-count").textContent = STUDENTS_ALL.length;
let statsSaved = 0;
function onGradeChange(){addLog("act","الصف → "+document.getElementById("sel-grade").value);}
function onTrackChange(){addLog("act","القسم → "+document.getElementById("sel-track").value);}
function doSearch(){
  const grade=document.getElementById("sel-grade").value;
  const track=document.getElementById("sel-track").value;
  const room=document.getElementById("sel-room").value;
  addLog("inf","ضغط «ابحث» — الصف: "+grade+" | القسم: "+track+" | الفصل: "+room);
  renderResults(STUDENTS_ALL);
  document.getElementById("results-section").style.display="block";
  addLog("ok","ظهرت نتائج البحث: "+STUDENTS_ALL.length+" طالب");
}
function renderResults(students){
  const tbody=document.getElementById("results-body");
  tbody.innerHTML="";
  const vOpts='<option value="">-- اختر --</option><option>الغياب بعذر</option><option>الغياب بدون عذر مقبول</option><option>الغياب بعذر مقبول عبر منصة مدرستي</option><option>الغياب بدون عذر مقبول عبر منصة مدرستي</option>';
  students.forEach(s=>{
    const tr=document.createElement("tr");
    tr.dataset.sid=s.id;
    tr.innerHTML=
      '<td><input type="checkbox" class="student-chk" data-sid="'+s.id+'" onchange="onChkChange(this)"></td>'+
      '<td class="student-name" style="color:#0d6e3f;font-weight:bold;text-align:right">'+s.name+'</td>'+
      '<td style="color:#555;font-size:11px">'+s.class_name+'</td>'+
      '<td><select class="violation-sel" data-sid="'+s.id+'" onchange="onSelChange(this)">'+vOpts+'</select></td>';
    tbody.appendChild(tr);
  });
}
function toggleAll(chk){document.querySelectorAll(".student-chk").forEach(c=>c.checked=chk.checked);}
function onChkChange(chk){
  const name=chk.closest("tr").querySelector(".student-name").textContent;
  if(chk.checked){chk.closest("tr").style.background="#e8f5e9";addLog("ok","✓ تحديد: "+name);}
  else addLog("inf","☐ إلغاء: "+name);
  updateStats();
}
function onSelChange(sel){
  const name=sel.closest("tr").querySelector(".student-name").textContent;
  addLog("act","نوع المخالفة ["+name+"] → "+sel.value);
}
function doSave(){
  const checked=document.querySelectorAll(".student-chk:checked");
  const withType=Array.from(checked).filter(c=>{const s=c.closest("tr").querySelector(".violation-sel");return s&&s.value;});
  statsSaved+=withType.length;
  addLog("ok","💾 ضغط «حفظ» — "+withType.length+" سجل");
  const summary=document.getElementById("result-summary");
  summary.style.display="block";
  summary.innerHTML="✅ تم الحفظ: "+withType.length+" طالب ("+withType.map(c=>c.closest("tr").querySelector(".student-name").textContent).join("، ")+")";
  checked.forEach(c=>{ c.checked=false; c.closest("tr").style.background=""; });
  document.getElementById("chk-all").checked=false;
  updateStats();
}
function updateStats(){
  const n=document.querySelectorAll(".student-chk:checked").length;
  document.getElementById("stats").innerHTML="محدّد: "+n+" طالب<br>محفوظ (إجمالي): "+statsSaved+" طالب";
}
function addLog(type,text){
  const log=document.getElementById("ext-log");
  const div=document.createElement("div");
  div.className="log-entry log-"+type;
  const t=new Date().toLocaleTimeString("ar-SA",{hour12:false});
  div.textContent="["+t+"] "+text;
  log.appendChild(div);
  log.scrollTop=log.scrollHeight;
}
const _orig=EventTarget.prototype.dispatchEvent;
EventTarget.prototype.dispatchEvent=function(ev){
  if(["change","click"].includes(ev.type)){
    if(this.tagName==="SELECT") addLog("act","dispatchEvent→SELECT["+this.id+"]="+(this.value||"?"));
    if(this.tagName==="INPUT"&&this.type==="checkbox") addLog("act","dispatchEvent→CHK["+this.dataset.sid+"]="+this.checked);
  }
  return _orig.call(this,ev);
};
</script></body></html>"""

    return (html_top
            .replace("DATE_PLACEHOLDER",   today_str)
            .replace("JS_ALL_PLACEHOLDER", js_all))


@router.options("/web/api/noor-absence-test")
async def noor_test_preflight():
    return Response(status_code=204, headers=_CORS_HEADERS)

@router.get("/web/api/noor-absence-test", response_class=JSONResponse)
async def noor_absence_test():
    """
    بيانات غياب للاختبار — بلا مصادقة ومع CORS مفتوح للجميع.

    كانت تُرجع أسماء غائبي اليوم لأي زائر على الإنترنت. صارت محجوبة إلا
    في وضع التطوير (ABSENTEE_DEBUG=1) — تبقى أداة اختبار ولا تُشحن مفتوحة.
    """
    if not debug_on():
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    today  = datetime.date.today().isoformat()
    groups = _build_test_groups()
    return JSONResponse(
        {"ok": True, "date": today, "total": sum(len(g["students"]) for g in groups),
         "groups": groups, "_test": True},
        headers=_CORS_HEADERS,
    )

@router.get("/noor-mock", response_class=HTMLResponse)
async def noor_mock_page():
    """صفحة HTML تُحاكي واجهة نور — للاختبار المحلي فقط."""
    if not debug_on():
        return HTMLResponse(content="Not Found", status_code=404)
    return HTMLResponse(content=_build_noor_mock_html())


@router.get("/health")
async def health_check():
    """مسار اختبار صحة الاتصال بالسيرفر."""
    return {
        "status": "ok",
        "timestamp": datetime.datetime.now().isoformat(),
        "version": "1.0.0"
    }


@router.post("/web/api/admin/trigger-update")
async def trigger_update_now(request: Request):
    """تحديث فوري للسيرفر — للمدير فقط — يُنزِّل آخر إصدار ويُعيد التشغيل."""
    from api.web_routes import _get_current_user
    user = _get_current_user(request)
    if not user or user.get("role") != "admin":
        return JSONResponse({"ok": False, "msg": "غير مصرح — للمدير فقط"}, status_code=403)
    try:
        from updater import trigger_immediate_update
        ok, msg = trigger_immediate_update()
        return JSONResponse({"ok": ok, "msg": msg})
    except Exception as e:
        return JSONResponse({"ok": False, "msg": str(e)})
