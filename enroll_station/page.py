# -*- coding: utf-8 -*-
"""صفحة أداة التسجيل — قسمان: ضبط الشبكة، وتسجيل البصمات."""

PAGE = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>أداة تسجيل بصمات الطلاب — درب الطلاب</title>
<style>
  :root{--navy:#0C2E56;--blue:#1565C0;--org:#F07A16;--ok:#16a34a;
    --warn:#d97706;--err:#dc2626;--mu:#5D7391;--line:#E2EAF4;--bg:#F5F8FC;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:Tahoma,Arial,sans-serif;background:var(--bg);color:#12233B;padding:20px;max-width:1000px;margin:auto}
  h1{font-size:21px;color:var(--navy);margin-bottom:3px}
  h1 small{display:block;font-size:12.5px;color:var(--mu);font-weight:normal;margin-top:3px}
  .tabs{display:flex;gap:8px;margin:16px 0}
  .tab{padding:9px 20px;border-radius:9px 9px 0 0;cursor:pointer;font-weight:700;font-size:14px;background:#e7eef7;color:var(--navy)}
  .tab.on{background:#fff;border:1px solid var(--line);border-bottom:none;color:var(--blue)}
  .card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}
  .card h2{font-size:15px;color:var(--navy);margin-bottom:4px}
  .card p.d{font-size:12px;color:var(--mu);margin-bottom:11px}
  .row{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-bottom:9px}
  label{font-size:13px;color:#33475F;min-width:90px}
  input,select{font-family:inherit;font-size:14px;padding:8px 10px;border:1px solid #cfd9e6;border-radius:8px}
  input[type=text],input[type=number]{width:150px}
  .btn{font-family:inherit;font-size:13.5px;font-weight:700;border:none;border-radius:8px;padding:8px 16px;cursor:pointer;color:#fff;background:var(--blue)}
  .btn.g{background:var(--navy)}.btn.o{background:var(--org)}.btn.gh{background:#eef3fb;color:var(--navy)}
  .btn:disabled{opacity:.5;cursor:default}
  .st{font-size:12px;font-weight:700;padding:3px 9px;border-radius:20px}
  .st.ok{background:#E4F6EA;color:#1B7C3D}.st.er{background:#FDE7E7;color:#C0392B}.st.wa{background:#FFF0DE;color:#B8620B}
  .hide{display:none}
  .cls{border:1px solid var(--line);border-radius:10px;margin-bottom:9px;overflow:hidden}
  .clshead{padding:10px 13px;background:#F7FAFE;cursor:pointer;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}
  .clshead b{color:var(--navy);font-size:14.5px}.clshead .c{font-size:12px;color:var(--mu)}
  .clsbody{display:none}.clsbody.open{display:block}
  .stu{display:flex;align-items:center;gap:11px;padding:9px 13px;border-top:1px solid #F1F5F9}
  .stu:first-child{border-top:none}
  .stu .nm{flex:1;font-size:14px}.stu .id{font-size:12px;color:var(--mu);direction:ltr}
  .prog{height:9px;background:#EDF2F8;border-radius:6px;overflow:hidden;margin-bottom:5px}
  .prog i{display:block;height:100%;background:linear-gradient(90deg,var(--ok),#4ade80);width:0}
  .muted{color:var(--mu);font-size:12px}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{background:var(--navy);color:#fff;padding:6px}
  td{padding:6px;border-top:1px solid #EDF2F8;text-align:center}
  .modal{position:fixed;inset:0;background:rgba(12,46,86,.55);display:none;align-items:center;justify-content:center}
  .modal.show{display:flex}
  .box{background:#fff;border-radius:16px;padding:24px 28px;text-align:center;max-width:360px}
  .box .ic{font-size:46px;margin-bottom:8px}
  .box h3{font-size:18px;color:var(--navy);margin-bottom:7px}
  .box p{font-size:13.5px;color:#33475F;line-height:1.7;margin-bottom:16px}
  .who{font-weight:700;color:var(--org)}
  .pulse{display:inline-block;width:15px;height:15px;border-radius:50%;background:var(--org);animation:p 1s infinite}
  @keyframes p{0%{opacity:1}50%{opacity:.4}100%{opacity:1}}
</style></head><body>
<h1>أداة تسجيل بصمات الطلاب<small>لابتوب موصول بجهاز البصمة بسلك مباشر — تسجيل فقط، بلا نظام كامل</small></h1>

<div class="tabs">
  <div class="tab on" id="t-net" onclick="show('net')">① ضبط الشبكة والاتصال</div>
  <div class="tab" id="t-enr" onclick="show('enr')">② تسجيل البصمات</div>
</div>

<!-- ═══ قسم الشبكة ═══ -->
<div id="s-net">
  <div class="card">
    <h2>حالة اللابتوب</h2>
    <div id="net-status" class="muted">جارٍ الفحص...</div>
  </div>
  <div class="card">
    <h2>الوصلة المباشرة بالجهاز</h2>
    <p class="d">جهاز البصمة له عنوان ثابت (افتراضياً 192.168.1.201). نضبط منفذ اللابتوب على عنوان مجاور بلا بوّابة، ثم نفحص.</p>
    <div class="row"><label>عنوان الجهاز</label><input type="text" id="dev-ip" value="192.168.1.201">
      <button class="btn gh" onclick="scan()">🔍 بحث في الشبكة</button><span id="scan-m" class="muted"></span></div>
    <div class="row"><label>منفذ اللابتوب</label><select id="adapter"></select>
      <input type="text" id="lap-ip" style="width:130px"><span class="muted">سيُضبط بلا بوّابة</span></div>
    <div class="row">
      <button class="btn g" onclick="setIp()">ضبط عنوان اللابتوب</button>
      <button class="btn o" onclick="testDev()">فحص الاتصال بالجهاز</button>
      <button class="btn gh" onclick="dhcp()">إعادة DHCP (بعد الانتهاء)</button>
    </div>
    <div id="net-msg" class="muted" style="margin-top:6px"></div>
  </div>
</div>

<!-- ═══ قسم التسجيل ═══ -->
<div id="s-enr" class="hide">
  <div class="card">
    <h2>سحب الطلاب</h2>
    <p class="d">من ملف roster.json (مُصدَّر من النظام على فلاشة)، أو من رابط النظام مباشرةً إن كان اللابتوب على الإنترنت.</p>
    <div class="row">
      <button class="btn gh" onclick="loadRoster()">تحميل من الملف</button>
      <span class="muted">|</span>
      <input type="text" id="sys-url" placeholder="رابط النظام" style="width:200px">
      <input type="text" id="sys-tok" placeholder="الرمز (اختياري)" style="width:150px">
      <button class="btn gh" onclick="pull()">سحب من النظام</button>
    </div>
    <div id="roster-m" class="muted" style="margin-top:6px"></div>
  </div>
  <div class="card">
    <div class="prog"><i id="pf"></i></div>
    <div class="row"><span id="pl" class="muted">—</span><span style="flex:1"></span>
      <input type="text" id="q" placeholder="🔍 بحث باسم الطالب" style="width:170px" oninput="renderStu()">
      <label class="muted"><input type="checkbox" id="hideEn" onchange="renderStu()"> إخفاء المسجّلين</label>
      <button class="btn gh" onclick="exportEnrolled()">💾 حفظ المسجّلين</button></div>
    <div id="stu-list"></div>
  </div>
</div>

<div id="toast" style="position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--navy);color:#fff;padding:10px 22px;border-radius:24px;font-size:14px;font-weight:700;display:none;box-shadow:0 6px 20px rgba(0,0,0,.25);z-index:20"></div>

<div class="modal" id="modal"><div class="box">
  <div class="ic" id="m-ic">👆</div>
  <h3 id="m-t">ضع إصبع الطالب على الجهاز</h3>
  <p id="m-b"></p>
  <div id="m-btns" style="display:none"><button class="btn gh" onclick="closeModal()">إغلاق</button></div>
</div></div>

<script>
const $=i=>document.getElementById(i);
async function j(p,o){const r=await fetch(p,o||{});return r.json();}
function show(t){['net','enr'].forEach(x=>{$('s-'+x).classList.toggle('hide',x!==t);$('t-'+x).classList.toggle('on',x===t);});}

// ── الشبكة ──
async function loadNet(){
  const d=await j('/api/net');
  let h='<div class="row"><span class="st '+(d.admin?'ok':'wa')+'">'+(d.admin?'صلاحية مدير ✅':'بلا صلاحية مدير')+'</span>';
  h+='<span class="muted"> — ضبط العنوان يحتاج تشغيل الأداة كمسؤول</span></div>';
  h+='<div class="muted">منافذ سلكية: '+(d.ethernet.length||0)+'</div>';
  $('net-status').innerHTML=h;
  const sel=$('adapter');sel.innerHTML=d.ethernet.map(a=>'<option>'+a.name+'</option>').join('')||'<option>Ethernet</option>';
  $('lap-ip').value=d.suggested_ip;
}
async function scan(){$('scan-m').textContent='جارٍ البحث...';
  const d=await j('/api/net/scan',{method:'POST'});
  $('scan-m').textContent=d.found.length?('وُجد: '+d.found.join('، ')):('لا جهاز على 4370 في '+d.network+'.x');
  if(d.found.length)$('dev-ip').value=d.found[0];}
async function setIp(){const d=await j('/api/net/setip',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({adapter:$('adapter').value,ip:$('lap-ip').value})});
  $('net-msg').textContent=(d.ok?'✅ ':'⚠️ ')+d.msg;}
async function dhcp(){const d=await j('/api/net/dhcp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({adapter:$('adapter').value})});
  $('net-msg').textContent=(d.ok?'✅ ':'⚠️ ')+d.msg;}
async function testDev(){$('net-msg').textContent='جارٍ فحص الاتصال...';
  const d=await j('/api/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_ip:$('dev-ip').value})});
  if(d.ok){const n=d.info||{};$('net-msg').innerHTML='<span class="st ok">متصل ✅</span> '+(n.name||'')+' · '+(n.serial||'')+' · '+(n.firmware||'');}
  else $('net-msg').innerHTML='<span class="st er">فشل</span> '+(d.error||'');}

// ── التسجيل (مجمّع بالفصول، ضغطة واحدة) ──
let CLS=[],EN=0,TOT=0,OPEN={};
async function loadRoster(){const d=await j('/api/roster');
  if(!d.ok){$('roster-m').textContent='تعذّر';return;}
  CLS=d.classes||[];TOT=d.total;EN=d.done;
  $('roster-m').textContent='حُمّل '+TOT+' طالب في '+CLS.length+' فصل ('+EN+' مسجّل)';
  renderStu();prog();}
async function pull(){$('roster-m').textContent='جارٍ السحب من النظام...';
  const d=await j('/api/roster/pull',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({system_url:$('sys-url').value,system_token:$('sys-tok').value})});
  if(d.ok){$('roster-m').textContent='سُحب '+d.count+' طالب';loadRoster();}
  else $('roster-m').textContent='تعذّر: '+(d.error||'');}
function prog(){const p=TOT?Math.round(EN/TOT*100):0;$('pf').style.width=p+'%';$('pl').textContent='سُجّل '+EN+' من '+TOT+' ('+p+'%)';}
function toast(t){const e=$('toast');e.textContent=t;e.style.display='block';clearTimeout(window._tt);window._tt=setTimeout(()=>e.style.display='none',1400);}
function renderStu(){const q=$('q').value.trim(),hide=$('hideEn').checked;
  let h='';
  CLS.forEach((c,ci)=>{
    let studs=c.students.filter(s=>(!q||(s.name||'').includes(q))&&(!hide||!s.enrolled));
    if(!studs.length)return;
    const op=(q||OPEN[ci])?'open':'';
    h+=`<div class="cls"><div class="clshead" onclick="tog(${ci})">
      <b>${c.name}</b><span class="c">${c.done}/${c.total} مسجّل</span></div>
      <div class="clsbody ${op}" id="cb-${ci}">`;
    studs.forEach(s=>{const nm=(s.name||'').replace(/'/g,'');
      h+=`<div class="stu">
        <span class="st ${s.enrolled?'ok':'wa'}">${s.enrolled?'مسجّل':'—'}</span>
        <span class="nm">${s.name} <span class="id">رقم ${s.academic_no}</span></span>
        ${s.enrolled
          ? `<button class="btn gh" title="لو كانت البصمة غير واضحة" onclick="enroll('${s.academic_no}','${nm}','${s.student_id||''}',true)">🔄 إعادة البصمة</button>`
          : `<button class="btn" onclick="enroll('${s.academic_no}','${nm}','${s.student_id||''}',false)">سجّل بصمة</button>`}
      </div>`;});
    h+='</div></div>';});
  $('stu-list').innerHTML=h||'<p class="muted">حمّل الطلاب أولاً، أو لا نتائج للبحث.</p>';}
function tog(ci){OPEN[ci]=!OPEN[ci];$('cb-'+ci).classList.toggle('open');}
// يُرسل الأمر للجهاز وينتظر التقاطه فعلاً — لا يُعلّم مسجّلاً إلا بنجاح.
function closeModal(){$('modal').classList.remove('show');}
async function enroll(an,nm,sid,again){
  $('m-ic').innerHTML='<span class="pulse"></span>';
  $('m-t').textContent='ضع إصبع الطالب على الجهاز';
  $('m-b').innerHTML='<span class="who">'+nm+' — رقم '+an+'</span><br>الجهاز في وضع الالتقاط... يضع الطالب إصبعه حتى يكتمل.';
  $('m-btns').style.display='none';
  $('modal').classList.add('show');
  let d;
  try{ d=await j('/api/enroll',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({academic_no:an,name:nm,student_id:sid})}); }
  catch(e){ d={ok:false,error:'تعذّر الاتصال بالأداة'}; }
  if(d&&d.ok){
    // نجح الالتقاط فعلاً — الآن نُعلّمه
    CLS.forEach(c=>c.students.forEach(s=>{if(s.academic_no==an && !s.enrolled){s.enrolled=true;c.done++;EN++;}}));
    renderStu();prog();closeModal();
    toast((again?'أُعيدت بصمة ':'سُجّلت بصمة ')+nm);
  }else{
    $('m-ic').textContent='⚠️';
    $('m-t').textContent='لم يكتمل الالتقاط';
    $('m-b').innerHTML='<span class="who">'+nm+'</span><br>'+((d&&d.error)||'حاول مرة أخرى')+'<br><span class="muted">لم يُعلَّم مسجّلاً.</span>';
    $('m-btns').style.display='block';
  }
}
async function exportEnrolled(){const d=await j('/api/enrolled');
  toast('حُفظ '+d.count+' طالب في enrolled.json');}

show('net');loadNet();loadRoster();
</script>
</body></html>"""
