# -*- coding: utf-8 -*-
"""
api/attendance_routes.py — الحضور الموحّد (الخلطة الذكية).

يعرض حالةً واحدة لكل طالب مدموجةً من ثلاثة مصادر: جهاز البصمة، روابط
المعلمين، الإدخال اليدوي — مع وسم مصدر كل حالة، ولوحة تنبيهات للتعارض.
المنطق كلّه في attendance_blend.reconcile_daily_attendance (قراءة فقط).

  GET  /web/attendance                    الصفحة (مصادَقة)
  GET  /web/api/attendance/blend          الحالة الموحّدة {date, role}
  POST /web/api/attendance/role           حفظ دور البصمة (مساعد/أساسي)
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from constants import now_riyadh_date
from config_manager import load_config, save_config

router = APIRouter()

_VALID_ROLES = ("supplement", "primary")


def _auth(request: Request) -> bool:
    from api.web_routes import _get_current_user
    return bool(_get_current_user(request))


def _unauth():
    return JSONResponse({"ok": False, "error": "غير مصرّح"}, status_code=401)


@router.get("/web/attendance", response_class=HTMLResponse)
async def attendance_page(request: Request):
    if not _auth(request):
        return RedirectResponse("/web/login")
    return HTMLResponse(
        content=_PAGE,
        headers={"Content-Security-Policy":
                 "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:; "
                 "script-src * 'unsafe-inline' 'unsafe-eval'; "
                 "style-src * 'unsafe-inline';"})


@router.get("/web/api/attendance/blend", response_class=JSONResponse)
async def attendance_blend(request: Request, date: str = "", role: str = ""):
    if not _auth(request):
        return _unauth()
    from attendance_blend import reconcile_daily_attendance
    date = date or now_riyadh_date()
    role = role if role in _VALID_ROLES else None
    try:
        res = reconcile_daily_attendance(date, role=role)
        res["ok"] = True
        # الدور الفعّال المحفوظ (لإظهار المفتاح بحالته الصحيحة)
        res["saved_role"] = load_config().get(
            "biometric_attendance_role", "supplement")
        return JSONResponse(res)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/web/api/attendance/role", response_class=JSONResponse)
async def attendance_set_role(request: Request):
    if not _auth(request):
        return _unauth()
    try:
        d = await request.json()
        role = d.get("role")
        if role not in _VALID_ROLES:
            return JSONResponse({"ok": False, "error": "دور غير صالح"},
                                status_code=400)
        cfg = load_config()
        cfg["biometric_attendance_role"] = role
        save_config(cfg)
        return JSONResponse({"ok": True, "role": role})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


_PAGE = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>الحضور الموحّد — درب الطلاب</title>
<style>
  :root{--navy:#0C2E56;--navy2:#123C6E;--blue:#1565C0;--org:#F07A16;
    --ok:#16a34a;--warn:#d97706;--err:#dc2626;--purp:#7C3AED;
    --mu:#5D7391;--line:#E2EAF4;--bg:#F5F8FC;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:Tahoma,Arial,sans-serif;background:var(--bg);color:#12233B;padding:22px;}
  a{color:var(--blue);text-decoration:none}
  .top{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:10px}
  h1{font-size:22px;color:var(--navy)}
  h1 small{display:block;font-size:13px;color:var(--mu);font-weight:normal;margin-top:4px}
  .back{font-size:13px}
  .card{background:#fff;border:1px solid var(--line);border-radius:13px;padding:16px 17px;margin-bottom:16px}
  .card h2{font-size:16px;color:var(--navy);margin-bottom:4px}
  .card p.d{font-size:12.5px;color:var(--mu);margin-bottom:12px}
  .row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
  input,select{font-family:inherit;font-size:14px;padding:8px 10px;border:1px solid #cfd9e6;border-radius:8px;background:#fff}
  .btn{font-family:inherit;font-size:14px;font-weight:700;border:none;border-radius:8px;padding:9px 18px;cursor:pointer;color:#fff;background:var(--blue)}
  .btn.o{background:var(--org)}.btn.gh{background:#eef3fb;color:var(--navy)}
  .btn.sm{padding:6px 12px;font-size:12.5px}
  .btn:disabled{opacity:.5;cursor:default}
  .kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
  @media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}}
  .kpi{background:var(--bg);border:1px solid var(--line);border-radius:11px;padding:13px 8px;text-align:center}
  .kpi u{display:block;font-size:26px;font-weight:800;text-decoration:none}
  .kpi span{font-size:11.5px;color:var(--mu)}
  .kpi.hl{border-color:var(--purp);background:#F6F1FE}
  /* مفتاح الدور */
  .roles{display:flex;gap:0;border:1px solid var(--line);border-radius:10px;overflow:hidden}
  .roles button{font-family:inherit;font-size:13px;font-weight:700;border:none;padding:9px 15px;cursor:pointer;background:#fff;color:var(--mu)}
  .roles button.on{background:var(--navy);color:#fff}
  .rolehint{font-size:12px;color:var(--mu);margin-top:7px;line-height:1.7}
  /* شارات */
  .pill{display:inline-block;padding:3px 11px;border-radius:20px;font-size:11px;font-weight:800}
  .pill.p{background:#E4F6EA;color:#1B7C3D}.pill.t{background:#FFF0DE;color:#B8620B}
  .pill.n{background:#FDE7E7;color:#C0392B}.pill.h{background:#F0E9FE;color:#6D28D9}
  .src{display:inline-block;padding:2px 8px;border-radius:6px;font-size:10px;font-weight:700;color:#fff}
  .src.dev{background:var(--blue)}.src.tea{background:var(--navy)}
  .src.man{background:#64748b}.src.def{background:#94a3b8}.src.no{background:#e0736b}
  table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
  th{background:var(--navy);color:#fff;padding:7px 6px;font-weight:700}
  td{padding:6px;border-top:1px solid #EDF2F8;text-align:center}
  tr:nth-child(even) td{background:#FAFCFE}
  .clshdr td{background:#EEF3FB!important;color:var(--navy);font-weight:800;text-align:right;padding:7px 12px}
  .muted{color:var(--mu);font-size:12px}
  .alert{background:#FBF3FF;border:1px solid #E4D3FB;border-radius:10px;padding:11px 13px;margin-bottom:9px;font-size:13px}
  .alert b{color:var(--purp)}
  .legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--mu);margin-top:10px}
  .legend span{display:inline-flex;align-items:center;gap:5px}
  .filters{display:flex;gap:7px;flex-wrap:wrap;margin:4px 0 2px}
  .filters button{font-family:inherit;font-size:12px;border:1px solid var(--line);background:#fff;color:var(--mu);border-radius:20px;padding:5px 13px;cursor:pointer}
  .filters button.on{background:var(--blue);color:#fff;border-color:var(--blue)}
  .spin{color:var(--mu);font-size:13px;padding:16px;text-align:center}
</style></head><body>
<div class="top">
  <h1>الحضور الموحّد <small>حالةٌ واحدة لكل طالب، مدموجةٌ ذكيّاً من جهاز البصمة وروابط المعلمين والإدخال اليدوي</small></h1>
  <a class="back" href="/web/dashboard">← الرجوع للوحة</a>
</div>

<div class="card">
  <div class="row" style="justify-content:space-between">
    <div class="row">
      <label class="muted">اليوم</label>
      <input type="date" id="date">
      <button class="btn gh sm" onclick="load()">↻ تحديث</button>
    </div>
    <div>
      <div class="roles">
        <button id="r-sup" onclick="setRole('supplement')">البصمة مساعدة</button>
        <button id="r-pri" onclick="setRole('primary')">البصمة أساسية</button>
      </div>
    </div>
  </div>
  <div class="rolehint" id="rolehint"></div>
</div>

<div class="card">
  <div class="kpis">
    <div class="kpi"><u id="k-present" style="color:#1B7C3D">—</u><span>حاضر</span></div>
    <div class="kpi"><u id="k-late" style="color:#B8620B">—</u><span>متأخر</span></div>
    <div class="kpi"><u id="k-absent" style="color:#C0392B">—</u><span>غائب</span></div>
    <div class="kpi hl"><u id="k-escape" style="color:#6D28D9">—</u><span>هروب (تعارض)</span></div>
    <div class="kpi"><u id="k-total" style="color:#0C2E56">—</u><span>إجمالي (غير المستثنين)</span></div>
  </div>
  <div class="legend">
    <span><span class="src dev">بصمة</span> الجهاز عند البوابة</span>
    <span><span class="src tea">معلم</span> رابط الفصل</span>
    <span><span class="src man">يدوي</span> إدخال الإدارة</span>
    <span><span class="src def">افتراضي</span> لا سجل (يُفترض حاضراً)</span>
    <span><span class="src no">لم يبصم</span> غياب سببه عدم البصم</span>
  </div>
</div>

<div id="alerts"></div>

<div class="card">
  <div class="row" style="justify-content:space-between">
    <h2>تفصيل الطلاب</h2>
    <input id="search" placeholder="بحث بالاسم…" oninput="render()" style="width:180px">
  </div>
  <div class="filters" id="filters">
    <button data-f="all" class="on" onclick="setFilter('all')">الكل</button>
    <button data-f="حاضر" onclick="setFilter('حاضر')">حاضر</button>
    <button data-f="متأخر" onclick="setFilter('متأخر')">متأخر</button>
    <button data-f="غائب" onclick="setFilter('غائب')">غائب</button>
    <button data-f="هروب" onclick="setFilter('هروب')">هروب</button>
  </div>
  <div id="tblwrap"><div class="spin">…</div></div>
</div>

<script>
var DATA=null, ROLE='supplement', FILTER='all';
var HINTS={
  supplement:'<b>مساعد:</b> من لم يبصم لا يُحسب غائباً — قد يكون نسي البصم أو الجهاز معطّل. الغياب يحتاج سجل معلم أو إدخالاً يدوياً. البصمة تؤكّد الحضور ووقت الوصول فقط.',
  primary:'<b>أساسي:</b> البصمة إلزامية — كل من لم يبصم ولم يُعذَر يُحسب غائباً. يتطلّب أن يبصم الجميع فعلاً كل يوم، وإلا ظهر حاضرون كغائبين.'
};
function fmtRoleBtns(){
  document.getElementById('r-sup').className = ROLE=='supplement'?'on':'';
  document.getElementById('r-pri').className = ROLE=='primary'?'on':'';
  var h=HINTS[ROLE];
  if(ROLE=='primary' && DATA && DATA.totals.nopunch)
    h+=' <b style="color:#C0392B">('+DATA.totals.nopunch+' منهم غيابهم لأنهم لم يبصموا)</b>';
  document.getElementById('rolehint').innerHTML=h;
}
function setRole(r){
  ROLE=r; fmtRoleBtns();
  fetch('/web/api/attendance/role',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({role:r})});
  load();
}
function setFilter(f){
  FILTER=f;
  document.querySelectorAll('#filters button').forEach(function(b){
    b.className = b.dataset.f==f?'on':''; });
  render();
}
function srcClass(s){
  if(s.indexOf('بصمة')>=0 && s.indexOf('معلم')>=0) return 'dev';
  if(s=='بصمة') return 'dev'; if(s=='معلم') return 'tea';
  if(s=='يدوي') return 'man'; if(s=='لم يبصم') return 'no'; return 'def';
}
function pillClass(st){
  return st=='حاضر'?'p':st=='متأخر'?'t':st=='غائب'?'n':'h';
}
function load(){
  var d=document.getElementById('date').value;
  document.getElementById('tblwrap').innerHTML='<div class="spin">جارٍ الحساب…</div>';
  fetch('/web/api/attendance/blend?date='+encodeURIComponent(d)+'&role='+ROLE)
    .then(function(r){return r.json()})
    .then(function(j){
      if(!j.ok){document.getElementById('tblwrap').innerHTML='<div class="spin">خطأ: '+(j.error||'')+'</div>';return;}
      DATA=j; ROLE=j.role;
      document.getElementById('k-present').textContent=j.totals.present;
      document.getElementById('k-late').textContent=j.totals.late;
      document.getElementById('k-absent').textContent=j.totals.absent;
      document.getElementById('k-escape').textContent=j.totals.escape;
      document.getElementById('k-total').textContent=j.totals.total;
      fmtRoleBtns(); renderAlerts(); render();
    })
    .catch(function(e){document.getElementById('tblwrap').innerHTML='<div class="spin">تعذّر الاتصال</div>';});
}
function renderAlerts(){
  var box=document.getElementById('alerts'); box.innerHTML='';
  if(!DATA.alerts||!DATA.alerts.length) return;
  var html='<div class="card"><h2>تنبيهات تحتاج مراجعة <span class="muted">('+DATA.alerts.length+')</span></h2>';
  html+='<p class="d">طلابٌ بصموا عند البوابة (حاضرون في المبنى) لكن سجّلهم معلمٌ غائبين في حصة — الأرجح «هروب» لا غياباً كاملاً.</p>';
  DATA.alerts.forEach(function(a){
    html+='<div class="alert"><b>'+a.name+'</b> — '+a.class_name+'<br>'+a.text+'</div>';
  });
  html+='</div>'; box.innerHTML=html;
}
function render(){
  if(!DATA) return;
  var q=(document.getElementById('search').value||'').trim();
  var rows=DATA.students.filter(function(s){
    if(FILTER!='all' && s.status!=FILTER) return false;
    if(q && s.name.indexOf(q)<0) return false;
    return true;
  });
  if(!rows.length){document.getElementById('tblwrap').innerHTML='<div class="spin">لا نتائج</div>';return;}
  // تجميع بالفصل
  var byc={}, order=[];
  rows.forEach(function(s){ if(!byc[s.class_id]){byc[s.class_id]=[];order.push(s);} byc[s.class_id].push(s);});
  var seen={}, classes=[];
  DATA.students.forEach(function(s){ if(!seen[s.class_id]&&byc[s.class_id]){seen[s.class_id]=1;classes.push({id:s.class_id,name:s.class_name});}});
  var h='<table><thead><tr><th>#</th><th>الطالب</th><th>الحالة</th><th>المصدر</th><th>دقائق التأخر</th></tr></thead><tbody>';
  classes.forEach(function(c){
    var list=byc[c.id]; if(!list) return;
    h+='<tr class="clshdr"><td colspan="5">'+c.name+' <span class="muted">('+list.length+')</span></td></tr>';
    list.forEach(function(s,i){
      h+='<tr><td>'+(i+1)+'</td><td style="text-align:right;padding-right:12px">'+s.name+'</td>'
        +'<td><span class="pill '+pillClass(s.status)+'">'+s.status+'</span></td>'
        +'<td><span class="src '+srcClass(s.source)+'">'+s.source+'</span></td>'
        +'<td>'+(s.minutes>0?s.minutes:'—')+'</td></tr>';
    });
  });
  h+='</tbody></table>';
  document.getElementById('tblwrap').innerHTML=h;
}
// إقلاع
(function(){
  var t=new Date(); t.setMinutes(t.getMinutes()-t.getTimezoneOffset());
  document.getElementById('date').value=t.toISOString().slice(0,10);
  // اجلب الدور المحفوظ ثم حمّل
  fetch('/web/api/attendance/blend?date='+document.getElementById('date').value)
    .then(function(r){return r.json()}).then(function(j){
      if(j.ok){ROLE=j.saved_role||j.role||'supplement';} fmtRoleBtns(); load();
    }).catch(function(){fmtRoleBtns();load();});
})();
</script>
</body></html>"""
