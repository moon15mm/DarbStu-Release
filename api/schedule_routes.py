# -*- coding: utf-8 -*-
"""
api/schedule_routes.py — تبويب «جدولة الروابط» في الويب.

يكافئ تبويب سطح المكتب: اختيار اليوم، شبكة الحصص×الفصول (معلم لكل خلية)،
توقيت الحصص ووقت بداية الدوام، الحفظ والمسح، والإرسال الآلي (بدء/إيقاف)
عبر schedule_sender في الخادم.

  GET  /web/schedule                        الصفحة (admin)
  GET  /web/api/schedule/data?dow=          بيانات يومٍ كاملة
  POST /web/api/schedule/save-day           حفظ الجدول + التواقيت
  POST /web/api/schedule/clear              مسح جدول اليوم
  POST /web/api/schedule/sender/start|stop  الإرسال الآلي
  GET  /web/api/schedule/sender/status      حالة الإرسال والسجل
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config_manager import load_config, save_config
from database import load_students, load_teachers
from alerts_service import load_schedule, save_schedule

router = APIRouter()

_DEFAULT_TIMES = ["07:00", "07:50", "08:40", "09:50", "10:40", "11:30", "12:20"]


def _admin(request: Request):
    from api.web_routes import _get_current_user
    u = _get_current_user(request)
    return u if (u and u.get("role") == "admin") else None


def _unauth():
    return JSONResponse({"ok": False, "error": "غير مصرّح (مدير فقط)"},
                        status_code=401)


@router.get("/web/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request):
    if not _admin(request):
        return RedirectResponse("/web/login")
    return HTMLResponse(
        content=_PAGE,
        headers={"Content-Security-Policy":
                 "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:; "
                 "script-src * 'unsafe-inline' 'unsafe-eval'; "
                 "style-src * 'unsafe-inline';"})


@router.get("/web/api/schedule/data", response_class=JSONResponse)
async def schedule_data(request: Request, dow: int = 0):
    if not _admin(request):
        return _unauth()
    import schedule_sender
    classes = sorted(load_students().get("list", []), key=lambda c: c["id"])
    teachers = [t.get("اسم المعلم", "")
                for t in load_teachers().get("teachers", [])
                if t.get("اسم المعلم")]
    raw = load_schedule(dow)                       # {(cid, period): teacher}
    sched = {"%s,%s" % (k[0], k[1]): v for k, v in raw.items()}
    cfg = load_config()
    return JSONResponse({
        "ok": True, "dow": dow,
        "classes": [{"id": c["id"], "name": c["name"]} for c in classes],
        "teachers": teachers,
        "schedule": sched,
        "period_times": cfg.get("period_times", _DEFAULT_TIMES),
        "school_start_time": cfg.get("school_start_time", "07:00"),
        "sender": schedule_sender.status(),
    })


@router.post("/web/api/schedule/save-day", response_class=JSONResponse)
async def schedule_save_day(request: Request):
    if not _admin(request):
        return _unauth()
    try:
        d = await request.json()
        dow = int(d.get("day_of_week"))
        save_schedule(dow, d.get("schedule") or [])
        cfg = load_config()
        pt = d.get("period_times")
        if isinstance(pt, list) and pt:
            cfg["period_times"] = [str(x).strip() for x in pt]
        sst = d.get("school_start_time")
        if sst:
            cfg["school_start_time"] = str(sst).strip()
        save_config(cfg)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/web/api/schedule/clear", response_class=JSONResponse)
async def schedule_clear(request: Request):
    if not _admin(request):
        return _unauth()
    try:
        d = await request.json()
        save_schedule(int(d.get("day_of_week")), [])   # قائمة فارغة = مسح
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/web/api/schedule/sender/start", response_class=JSONResponse)
async def sender_start(request: Request):
    if not _admin(request):
        return _unauth()
    import schedule_sender
    return JSONResponse(schedule_sender.start())


@router.post("/web/api/schedule/sender/stop", response_class=JSONResponse)
async def sender_stop(request: Request):
    if not _admin(request):
        return _unauth()
    import schedule_sender
    return JSONResponse(schedule_sender.stop())


@router.get("/web/api/schedule/sender/status", response_class=JSONResponse)
async def sender_status(request: Request):
    if not _admin(request):
        return _unauth()
    import schedule_sender
    return JSONResponse({"ok": True, "sender": schedule_sender.status()})


_PAGE = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>جدولة الروابط — درب الطلاب</title>
<style>
  :root{--navy:#0C2E56;--blue:#1565C0;--org:#F07A16;--ok:#16a34a;
    --warn:#d97706;--err:#dc2626;--mu:#5D7391;--line:#E2EAF4;--bg:#F5F8FC;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:Tahoma,Arial,sans-serif;background:var(--bg);color:#12233B;padding:20px;}
  a{color:var(--blue);text-decoration:none}
  .top{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:10px}
  h1{font-size:21px;color:var(--navy)}
  h1 small{display:block;font-size:12.5px;color:var(--mu);font-weight:normal;margin-top:4px}
  .card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:14px}
  .row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
  label{font-size:13px;color:#33475F}
  input[type=time],input[type=text]{font-family:inherit;font-size:13px;padding:6px 8px;border:1px solid #cfd9e6;border-radius:7px;background:#fff;width:92px}
  select{font-family:inherit;font-size:12.5px;padding:5px 6px;border:1px solid #cfd9e6;border-radius:7px;background:#fff;max-width:170px}
  .btn{font-family:inherit;font-size:13.5px;font-weight:700;border:none;border-radius:8px;padding:8px 16px;cursor:pointer;color:#fff;background:var(--blue)}
  .btn.g{background:var(--navy)}.btn.o{background:var(--org)}.btn.ok{background:var(--ok)}
  .btn.err{background:var(--err)}.btn.gh{background:#eef3fb;color:var(--navy)}
  .btn.sm{padding:6px 12px;font-size:12.5px}
  .btn:disabled{opacity:.5;cursor:default}
  .days{display:flex;gap:0;border:1px solid var(--line);border-radius:9px;overflow:hidden}
  .days button{font-family:inherit;font-size:13px;font-weight:700;border:none;padding:8px 16px;cursor:pointer;background:#fff;color:var(--mu)}
  .days button.on{background:var(--navy);color:#fff}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{background:var(--navy);color:#fff;padding:7px 5px;font-weight:700;position:sticky;top:0}
  td{padding:5px;border:1px solid #EDF2F8;text-align:center}
  td.p{background:#EEF3FB;font-weight:800;color:var(--navy);white-space:nowrap}
  .tblwrap{overflow:auto;max-height:60vh;border:1px solid var(--line);border-radius:10px}
  .muted{color:var(--mu);font-size:12px}
  .msg{font-size:12.5px;padding:7px 11px;border-radius:8px;margin-top:8px;display:none}
  .msg.ok{background:#E4F6EA;color:#1B7C3D;display:block}.msg.er{background:#FDE7E7;color:#C0392B;display:block}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-inline-start:6px;vertical-align:middle}
  .dot.on{background:var(--ok)}.dot.off{background:#94a3b8}
  .log{background:#0C1E33;color:#CFE3FF;font-family:Consolas,monospace;font-size:11.5px;border-radius:9px;padding:10px;height:150px;overflow:auto;direction:ltr;text-align:right;white-space:pre-wrap}
</style></head><body>
<div class="top">
  <h1>جدولة الروابط<small>لكل حصة: المعلم المكلّف بكل فصل — والإرسال الآلي يرسل رابط تسجيل الغياب في وقت الحصة</small></h1>
  <a class="btn gh sm" href="/web/dashboard">← الرجوع للوحة</a>
</div>

<div class="card">
  <div class="row" style="justify-content:space-between">
    <div class="row">
      <label>اليوم</label>
      <div class="days" id="days"></div>
    </div>
    <div class="row">
      <label>بداية الدوام</label>
      <input type="time" id="start" value="07:00">
      <span class="muted">تُستخدم لحساب التأخر</span>
    </div>
  </div>
  <div class="row" style="margin-top:11px">
    <button class="btn ok" onclick="save()">💾 حفظ الجدول والتواقيت</button>
    <button class="btn gh sm" onclick="load()">🔄 تحديث</button>
    <button class="btn err sm" onclick="clearDay()">🗑️ مسح جدول اليوم</button>
    <span style="flex:1"></span>
    <span id="run-dot" class="dot off"></span>
    <span id="run-txt" class="muted">الإرسال الآلي: متوقّف</span>
    <button class="btn o sm" id="btn-start" onclick="startSender()">🚀 بدء الإرسال (لليوم)</button>
    <button class="btn err sm" id="btn-stop" onclick="stopSender()" disabled>🛑 إيقاف</button>
  </div>
  <div id="msg" class="msg"></div>
</div>

<div class="card">
  <div class="tblwrap"><div id="tbl" class="muted" style="padding:16px">…</div></div>
  <div class="muted" style="margin-top:6px">خلية فارغة = لا معلم لهذه الحصة/الفصل. عمود الوقت يضبط توقيت كل حصة.</div>
</div>

<div class="card">
  <div class="row" style="justify-content:space-between"><b style="color:var(--navy)">سجل الإرسال الآلي</b>
    <span class="muted" id="sched-info"></span></div>
  <div class="log" id="log">—</div>
</div>

<script>
var DOW=0, DATA=null, DAYS=["الأحد","الاثنين","الثلاثاء","الأربعاء","الخميس"];
function el(id){return document.getElementById(id);}
function toast(t,ok){var m=el('msg');m.textContent=t;m.className='msg '+(ok?'ok':'er');setTimeout(function(){m.className='msg';},3500);}
(function(){
  var h='';
  for(var i=0;i<5;i++) h+='<button data-d="'+i+'" onclick="setDay('+i+')">'+DAYS[i]+'</button>';
  el('days').innerHTML=h;
})();
function setDay(d){DOW=d;document.querySelectorAll('#days button').forEach(function(b){b.className=(+b.dataset.d===d)?'on':'';});load();}
function load(){
  fetch('/web/api/schedule/data?dow='+DOW).then(function(r){return r.json()}).then(function(j){
    if(!j.ok){el('tbl').textContent='تعذّر التحميل';return;}
    DATA=j; el('start').value=j.school_start_time||'07:00';
    renderGrid(); renderSender(j.sender);
  }).catch(function(){el('tbl').textContent='تعذّر الاتصال';});
}
function renderGrid(){
  var cls=DATA.classes, times=DATA.period_times||[], sched=DATA.schedule||{};
  var topt='<option value="">—</option>';
  DATA.teachers.forEach(function(t){topt+='<option value="'+t.replace(/"/g,'&quot;')+'">'+t+'</option>';});
  var h='<table><thead><tr><th>الحصة</th><th>الوقت</th>';
  cls.forEach(function(c){h+='<th>'+c.name+'</th>';});
  h+='</tr></thead><tbody>';
  for(var p=1;p<=7;p++){
    var tv=times[p-1]||'';
    h+='<tr><td class="p">الحصة '+p+'</td><td><input type="time" data-pt="'+p+'" value="'+tv+'" style="width:82px"></td>';
    cls.forEach(function(c){
      var cur=sched[c.id+','+p]||'';
      h+='<td><select data-cid="'+c.id+'" data-p="'+p+'">'+topt+'</select></td>';
    });
    h+='</tr>';
  }
  h+='</tbody></table>';
  el('tbl').innerHTML=h;
  // اضبط قيم القوائم
  document.querySelectorAll('#tbl select').forEach(function(s){
    s.value=sched[s.dataset.cid+','+s.dataset.p]||'';
  });
}
function collect(){
  var schedule=[];
  document.querySelectorAll('#tbl select').forEach(function(s){
    if(s.value) schedule.push({class_id:s.dataset.cid,period:parseInt(s.dataset.p),teacher_name:s.value});
  });
  var times=[];
  for(var p=1;p<=7;p++){var i=document.querySelector('[data-pt="'+p+'"]');times.push(i?i.value:'');}
  return {day_of_week:DOW,schedule:schedule,period_times:times,school_start_time:el('start').value};
}
function save(){
  fetch('/web/api/schedule/save-day',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collect())})
   .then(function(r){return r.json()}).then(function(j){toast(j.ok?'تم حفظ جدول '+DAYS[DOW]+' والتواقيت':'خطأ: '+(j.error||''),j.ok);});
}
function clearDay(){
  if(!confirm('مسح جدول يوم '+DAYS[DOW]+' كاملاً؟')) return;
  fetch('/web/api/schedule/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({day_of_week:DOW})})
   .then(function(r){return r.json()}).then(function(j){if(j.ok){toast('مُسح جدول '+DAYS[DOW],true);load();}else toast('خطأ','');});
}
function startSender(){
  fetch('/web/api/schedule/sender/start',{method:'POST'}).then(function(r){return r.json()}).then(function(j){
    if(j.ok){toast('بدأ الإرسال — '+(j.scheduled?j.scheduled.length:0)+' حصة مجدولة',true);}
    else toast(j.error||'تعذّر البدء','');
    pollStatus();
  });
}
function stopSender(){
  fetch('/web/api/schedule/sender/stop',{method:'POST'}).then(function(r){return r.json()}).then(function(){toast('أُوقف الإرسال',true);pollStatus();});
}
function renderSender(s){
  if(!s) return;
  el('run-dot').className='dot '+(s.running?'on':'off');
  el('run-txt').textContent='الإرسال الآلي: '+(s.running?('يعمل — '+(s.day||'')):'متوقّف');
  el('btn-start').disabled=!!s.running; el('btn-stop').disabled=!s.running;
  el('log').textContent=(s.log&&s.log.length)?s.log.join('\n'):'—';
  el('log').scrollTop=el('log').scrollHeight;
  el('sched-info').textContent=(s.scheduled&&s.scheduled.length)?('متبقٍّ: '+s.scheduled.map(function(x){return 'ح'+x.period+' '+x.time;}).join('، ')):'';
}
function pollStatus(){
  fetch('/web/api/schedule/sender/status').then(function(r){return r.json()}).then(function(j){if(j.ok)renderSender(j.sender);}).catch(function(){});
}
// إقلاع
setDay(0);
setInterval(pollStatus, 7000);
</script>
</body></html>"""
