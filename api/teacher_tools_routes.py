# -*- coding: utf-8 -*-
"""
api/teacher_tools_routes.py — مسارات «دفتر المتابعة» في أدوات المعلم.

المنطق كله في teacher_tools.py؛ هذه الوحدة تتحقق من الهوية والملكية فقط
ثم تُمرّر. كل مسار يمرّ بـ_guard: المعلّم لا يرى إلا دفاتره، والمدير
والوكيل يريان الجميع.

  GET  /web/api/tt/setup                 مرحلة المدرسة ومستوياتها ومواد مقترحة
  POST /web/api/tt/setup/apply           إنشاء دفتر لكل (فصل × مادة)
  POST /web/api/tt/settings              عدد الفترات وعلامة إتمام التجهيز
  GET  /web/api/tt/subjects              مواد المعلّم + قائمة الفصول
  POST /web/api/tt/subject/create        إسناد مادة
  POST /web/api/tt/subject/delete        حذف مادة بكل ما تحتها
  POST /web/api/tt/subject/options       مصدر درجة الحضور ودرجتا الحضور والسلوك
  GET  /web/api/tt/gradebook             الدفتر كاملاً لفترة
  POST /web/api/tt/component/save        إضافة/تعديل مكوّن
  POST /web/api/tt/component/delete      حذف مكوّن
  GET  /web/api/tt/component/budget      المتبقي من درجة المكوّن
  POST /web/api/tt/assessment/add        إضافة تقييم
  POST /web/api/tt/assessment/delete     حذف تقييم
  POST /web/api/tt/mark                  رصد خلية
  POST /web/api/tt/attendance-mark       رصد درجة الحضور يدوياً
  POST /web/api/tt/behavior/add          تسجيل مخالفة سلوكية
  GET  /web/api/tt/behavior/list          مخالفات طالب
  POST /web/api/tt/behavior/delete       حذف مخالفة
  POST /web/api/tt/award-full            منح الجميع الدرجة الكاملة
  GET  /web/api/tt/student               ملف طالب في المادة
  GET  /web/api/tt/print                 ورقة الطباعة بترويسة المدرسة
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, HTMLResponse

from config_manager import load_config, logo_img_tag_from_config
from database import load_students, get_user_info, authenticate
import teacher_tools as tt

router = APIRouter()

_ALLOWED_ROLES = ("admin", "deputy", "teacher")


def _user(request: Request):
    from api.web_routes import _get_current_user   # دائري: web_routes يستورد هذا
    u = _get_current_user(request)
    if not u or u.get("role") not in _ALLOWED_ROLES:
        return None
    return u


def _unauth():
    return JSONResponse({"ok": False, "msg": "غير مصرّح"}, status_code=401)


def _forbidden():
    return JSONResponse({"ok": False, "msg": "هذا الدفتر ليس لك"}, status_code=403)


def _guard(request: Request, subject_id):
    """يُرجع (المستخدم، ردّ الخطأ). أحدهما None دائماً."""
    u = _user(request)
    if not u:
        return None, _unauth()
    try:
        subject_id = int(subject_id)
    except (TypeError, ValueError):
        return None, JSONResponse({"ok": False, "msg": "مادة غير صالحة"}, status_code=400)
    if not tt.owns_subject(subject_id, u.get("sub", ""), u.get("role", "")):
        return None, _forbidden()
    return u, None


def _comp_subject(comp_id):
    """المادة التي ينتمي إليها مكوّن — للتحقق من الملكية قبل التعديل."""
    con = tt.get_db(); cur = con.cursor()
    cur.execute("SELECT subject_id FROM tt_components WHERE id=?", (comp_id,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None


def _asmt_subject(asmt_id):
    con = tt.get_db(); cur = con.cursor()
    cur.execute("SELECT c.subject_id FROM tt_assessments a "
                "JOIN tt_components c ON c.id=a.component_id WHERE a.id=?", (asmt_id,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None


# ══════════════════════════════════════════════════════════════
#  المواد
# ══════════════════════════════════════════════════════════════
@router.get("/web/api/tt/subjects", response_class=JSONResponse)
async def tt_subjects(request: Request):
    u = _user(request)
    if not u:
        return _unauth()
    classes = [{"id": c["id"], "name": c["name"]}
               for c in load_students().get("list", [])]
    return JSONResponse({"ok": True,
                         "subjects": tt.list_subjects(u.get("sub", "")),
                         "classes": classes})


@router.post("/web/api/tt/subject/create", response_class=JSONResponse)
async def tt_subject_create(request: Request):
    u = _user(request)
    if not u:
        return _unauth()
    d = await request.json()
    return JSONResponse(tt.create_subject(u.get("sub", ""),
                                          d.get("class_id", ""),
                                          d.get("subject", "")))


@router.post("/web/api/tt/subject/delete", response_class=JSONResponse)
async def tt_subject_delete(request: Request):
    u = _user(request)
    if not u:
        return _unauth()
    d = await request.json()
    return JSONResponse(tt.delete_subject(d.get("subject_id"), u.get("sub", "")))


# ══════════════════════════════════════════════════════════════
#  الدفتر
# ══════════════════════════════════════════════════════════════
@router.get("/web/api/tt/gradebook", response_class=JSONResponse)
async def tt_gradebook(request: Request, subject_id: int = 0, period: int = 1):
    u, err = _guard(request, subject_id)
    if err:
        return err
    return JSONResponse(tt.get_gradebook(int(subject_id), int(period or 1)))


@router.get("/web/api/tt/student", response_class=JSONResponse)
async def tt_student(request: Request, subject_id: int = 0,
                     student_id: str = "", period: int = 1):
    u, err = _guard(request, subject_id)
    if err:
        return err
    gb = tt.get_gradebook(int(subject_id), int(period or 1))
    if not gb.get("ok"):
        return JSONResponse(gb)
    row = next((s for s in gb["students"] if s["id"] == str(student_id)), None)
    if not row:
        return JSONResponse({"ok": False, "msg": "الطالب غير موجود في هذا الفصل"})
    return JSONResponse({"ok": True, "student": row,
                         "components": gb["components"],
                         "subject": gb["subject"]})


# ══════════════════════════════════════════════════════════════
#  المكوّنات
# ══════════════════════════════════════════════════════════════
@router.post("/web/api/tt/component/save", response_class=JSONResponse)
async def tt_component_save(request: Request):
    d = await request.json()
    comp_id = d.get("comp_id")
    subject_id = _comp_subject(comp_id) if comp_id else d.get("subject_id")
    u, err = _guard(request, subject_id)
    if err:
        return err
    return JSONResponse(tt.save_component(
        int(subject_id), int(d.get("period") or 1), d.get("name", ""),
        d.get("max_score"), d.get("category", "perf"),
        d.get("grade_mode", "bool"), comp_id))


@router.post("/web/api/tt/component/delete", response_class=JSONResponse)
async def tt_component_delete(request: Request):
    d = await request.json()
    comp_id = d.get("comp_id")
    u, err = _guard(request, _comp_subject(comp_id))
    if err:
        return err
    return JSONResponse(tt.delete_component(comp_id))


@router.get("/web/api/tt/component/budget", response_class=JSONResponse)
async def tt_component_budget(request: Request, comp_id: int = 0):
    u, err = _guard(request, _comp_subject(comp_id))
    if err:
        return err
    return JSONResponse(tt.remaining_budget(comp_id))


# ══════════════════════════════════════════════════════════════
#  التقييمات والرصد
# ══════════════════════════════════════════════════════════════
@router.post("/web/api/tt/assessment/add", response_class=JSONResponse)
async def tt_assessment_add(request: Request):
    d = await request.json()
    comp_id = d.get("comp_id")
    u, err = _guard(request, _comp_subject(comp_id))
    if err:
        return err
    return JSONResponse(tt.add_assessment(comp_id, d.get("title", ""),
                                          d.get("max_score"),
                                          d.get("due_date", "")))


@router.post("/web/api/tt/assessment/delete", response_class=JSONResponse)
async def tt_assessment_delete(request: Request):
    d = await request.json()
    asmt_id = d.get("asmt_id")
    u, err = _guard(request, _asmt_subject(asmt_id))
    if err:
        return err
    return JSONResponse(tt.delete_assessment(asmt_id))


@router.post("/web/api/tt/mark", response_class=JSONResponse)
async def tt_mark(request: Request):
    d = await request.json()
    asmt_id = d.get("asmt_id")
    u, err = _guard(request, _asmt_subject(asmt_id))
    if err:
        return err
    return JSONResponse(tt.set_mark(asmt_id, d.get("student_id", ""),
                                    d.get("value"), u.get("sub", "")))


# ══════════════════════════════════════════════════════════════
#  معالج التجهيز
# ══════════════════════════════════════════════════════════════
@router.get("/web/api/tt/setup", response_class=JSONResponse)
async def tt_setup(request: Request):
    u = _user(request)
    if not u:
        return _unauth()
    return JSONResponse(tt.get_setup(u.get("sub", "")))


@router.post("/web/api/tt/setup/apply", response_class=JSONResponse)
async def tt_setup_apply(request: Request):
    u = _user(request)
    if not u:
        return _unauth()
    d = await request.json()
    return JSONResponse(tt.apply_setup(u.get("sub", ""), d.get("classes"),
                                       d.get("subjects"), d.get("periods") or 2))


@router.post("/web/api/tt/settings", response_class=JSONResponse)
async def tt_settings(request: Request):
    u = _user(request)
    if not u:
        return _unauth()
    d = await request.json()
    return JSONResponse(tt.save_settings(u.get("sub", ""), d.get("periods"),
                                         d.get("setup_done")))


# ══════════════════════════════════════════════════════════════
#  خيارات المادة: الحضور والسلوك
# ══════════════════════════════════════════════════════════════
@router.post("/web/api/tt/subject/options", response_class=JSONResponse)
async def tt_subject_options(request: Request):
    d = await request.json()
    u, err = _guard(request, d.get("subject_id"))
    if err:
        return err
    return JSONResponse(tt.save_subject_options(
        int(d["subject_id"]), d.get("attendance_mode", "system"),
        d.get("attendance_max"), d.get("behavior_max")))


@router.post("/web/api/tt/attendance-mark", response_class=JSONResponse)
async def tt_attendance_mark(request: Request):
    d = await request.json()
    u, err = _guard(request, d.get("subject_id"))
    if err:
        return err
    return JSONResponse(tt.set_attendance_mark(
        int(d["subject_id"]), int(d.get("period") or 1),
        d.get("student_id", ""), d.get("value"), u.get("sub", "")))


@router.post("/web/api/tt/behavior/add", response_class=JSONResponse)
async def tt_behavior_add(request: Request):
    d = await request.json()
    u, err = _guard(request, d.get("subject_id"))
    if err:
        return err
    return JSONResponse(tt.add_behavior(
        int(d["subject_id"]), int(d.get("period") or 1), d.get("student_id", ""),
        d.get("kind", ""), d.get("note", ""), d.get("deduct"), u.get("sub", "")))


@router.get("/web/api/tt/behavior/list", response_class=JSONResponse)
async def tt_behavior_list(request: Request, subject_id: int = 0,
                           student_id: str = "", period: int = 1):
    u, err = _guard(request, subject_id)
    if err:
        return err
    return JSONResponse({"ok": True,
                         "rows": tt.list_behavior(subject_id, period, student_id),
                         "kinds": tt.BEHAVIOR_KINDS})


@router.post("/web/api/tt/behavior/delete", response_class=JSONResponse)
async def tt_behavior_delete(request: Request):
    d = await request.json()
    u, err = _guard(request, d.get("subject_id"))
    if err:
        return err
    return JSONResponse(tt.delete_behavior(d.get("behavior_id")))


@router.post("/web/api/tt/award-full", response_class=JSONResponse)
async def tt_award_full(request: Request):
    d = await request.json()
    asmt_id = d.get("asmt_id")
    subject_id = _asmt_subject(asmt_id)
    u, err = _guard(request, subject_id)
    if err:
        return err
    con = tt.get_db(); cur = con.cursor()
    cur.execute("SELECT class_id FROM tt_subjects WHERE id=?", (subject_id,))
    row = cur.fetchone()
    con.close()
    if not row:
        return JSONResponse({"ok": False, "msg": "المادة غير موجودة"})
    return JSONResponse(tt.award_full(asmt_id, row[0], u.get("sub", "")))


# ══════════════════════════════════════════════════════════════
#  الطلاب والتحليل
# ══════════════════════════════════════════════════════════════
@router.get("/web/api/tt/analyze", response_class=JSONResponse)
async def tt_analyze(request: Request, subject_id: int = 0, period: int = 1):
    u, err = _guard(request, subject_id)
    if err:
        return err
    return JSONResponse(tt.analyze_class(int(subject_id), int(period or 1)))


@router.get("/web/api/tt/student-across", response_class=JSONResponse)
async def tt_student_across(request: Request, student_id: str = ""):
    """
    ملخّص الطالب في كل مواده. لا يمرّ بـowns_subject عمداً: صفحة تحليل
    الطالب تخصّ الطالب لا المادة، ويراها المدير والوكيل والمعلّم.
    """
    u = _user(request)
    if not u:
        return _unauth()
    if not student_id:
        return JSONResponse({"ok": False, "msg": "رقم الطالب مطلوب"})
    return JSONResponse(tt.student_across_subjects(student_id))


# ══════════════════════════════════════════════════════════════
#  التراجع والتصفير والنسخ
# ══════════════════════════════════════════════════════════════
@router.post("/web/api/tt/undo-award", response_class=JSONResponse)
async def tt_undo_award(request: Request):
    d = await request.json()
    asmt_id = d.get("asmt_id")
    u, err = _guard(request, _asmt_subject(asmt_id))
    if err:
        return err
    return JSONResponse(tt.undo_award(asmt_id, u.get("sub", "")))


@router.post("/web/api/tt/reset", response_class=JSONResponse)
async def tt_reset(request: Request):
    """
    تصفير أرقام الدفتر. محميٌّ بكلمة مرور المستخدم نفسه: الجلسة تبقى
    مفتوحةً على جهازٍ في غرفة المعلمين، وهذه العملية لا رجعة فيها.
    """
    d = await request.json()
    u, err = _guard(request, d.get("subject_id"))
    if err:
        return err

    pwd = d.get("password") or ""
    if not pwd:
        return JSONResponse({"ok": False, "msg": "كلمة المرور مطلوبة"})
    if not authenticate(u.get("sub", ""), pwd):
        return JSONResponse({"ok": False, "msg": "كلمة المرور غير صحيحة"})

    period = d.get("period")
    if d.get("scope") == "all":
        period = None
    elif period is not None:
        period = int(period)
    return JSONResponse(tt.reset_marks(int(d["subject_id"]), period))


@router.post("/web/api/tt/components/copy", response_class=JSONResponse)
async def tt_components_copy(request: Request):
    d = await request.json()
    u, err = _guard(request, d.get("from_subject_id"))
    if err:
        return err
    return JSONResponse(tt.copy_components(
        int(d["from_subject_id"]), int(d.get("period") or 1),
        d.get("targets"), u.get("sub", ""),
        bool(d.get("with_assessments", True)), bool(d.get("replace")),
        bool(d.get("with_options"))))


# ══════════════════════════════════════════════════════════════
#  ورقة الطباعة
# ══════════════════════════════════════════════════════════════
_PRINT_CSS = """
@page { size: A4 landscape; margin: 10mm; }
* { box-sizing: border-box; }
body { font-family: Tajawal, 'Segoe UI', Arial, sans-serif; direction: rtl;
       margin: 0; color: #1E293B; }
.hdr { display: flex; align-items: center; justify-content: space-between;
       border-bottom: 3px solid #1565C0; padding-bottom: 8px; margin-bottom: 4px; }
.hdr .side { width: 30%; font-size: 12px; line-height: 1.7; font-weight: 600; }
.hdr .mid { text-align: center; flex: 1; }
.hdr .mid b { font-size: 17px; color: #0D47A1; display: block; }
.hdr .mid span { font-size: 12px; color: #475569; }
.meta { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center;
        margin: 8px 0 10px; }
.meta div { background: #EFF6FF; border: 1px solid #BFDBFE; color: #0D47A1;
            border-radius: 999px; padding: 3px 14px; font-size: 12px; font-weight: 600; }
table { border-collapse: collapse; width: 100%; font-size: 10.5px; }
th, td { border: 1px solid #94A3B8; padding: 3px 4px; text-align: center; }
thead th { background: #1565C0; color: #fff; font-weight: 700; }
thead tr.sub th { background: #0D47A1; font-weight: 500; font-size: 9.5px; }
td.nm { text-align: right; font-weight: 600; white-space: nowrap; padding-right: 6px; }
tbody tr:nth-child(even) td { background: #F6F9FC; }
.ok { color: #166534; font-weight: 700; }
.no { color: #B91C1C; font-weight: 700; }
.na { color: #CBD5E1; }
td.sc { background: #F1F5F9; font-weight: 700; }
td.tot { background: #EFF6FF; font-weight: 900; color: #0D47A1; }
td.low { background: #FEF2F2; color: #B91C1C; }
.sign { display: flex; justify-content: space-between; margin-top: 26px;
        font-size: 12px; font-weight: 600; }
.sign div { text-align: center; width: 30%; }
.sign .line { margin-top: 30px; border-top: 1px dotted #64748B; padding-top: 4px;
              color: #475569; font-weight: 500; }
.foot { margin-top: 10px; font-size: 9px; color: #94A3B8; text-align: center; }
@media print { .noprint { display: none; } }
.noprint { text-align: center; margin: 10px 0; }
.noprint button { background: #1565C0; color: #fff; border: none; padding: 8px 22px;
                  border-radius: 8px; font-size: 14px; cursor: pointer;
                  font-family: inherit; }
"""


def _esc(s):
    return (str(s if s is not None else "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _fmt(v):
    if v is None:
        return "—"
    f = float(v)
    return str(int(f)) if abs(f - int(f)) < 1e-9 else ("%.2f" % f).rstrip("0").rstrip(".")


@router.get("/web/api/tt/print", response_class=HTMLResponse)
async def tt_print(request: Request, subject_id: int = 0, period: int = 1):
    """ورقة الدفتر جاهزةً للطباعة — بترويسة المدرسة وتوقيع المعلّم."""
    u, err = _guard(request, subject_id)
    if err:
        return HTMLResponse("<h3 style='font-family:sans-serif;direction:rtl'>"
                            "غير مصرّح</h3>", status_code=403)
    gb = tt.get_gradebook(int(subject_id), int(period or 1))
    if not gb.get("ok"):
        return HTMLResponse("<h3 style='direction:rtl'>%s</h3>"
                            % _esc(gb.get("msg", "خطأ")), status_code=404)

    cfg = load_config()
    info = get_user_info(u.get("sub", "")) or {}
    teacher = info.get("full_name") or u.get("full_name") or u.get("sub", "")

    classes = {c["id"]: c["name"] for c in load_students().get("list", [])}
    cls_name = classes.get(gb["subject"]["class_id"], gb["subject"]["class_id"])
    comps = gb["components"]
    a_max, b_max = gb["att_max"], gb["beh_max"]

    # رأسان: مجموعات المكوّنات ثم أرقام التقييمات تحتها
    h1 = ['<th rowspan="2" class="nm">الطالب</th>']
    h2 = []
    for c in comps:
        n = len(c["assessments"]) + 1
        h1.append('<th colspan="%d">%s<br><span style="font-weight:400">'
                  'من %s</span></th>' % (n, _esc(c["name"]), _fmt(c["max_score"])))
        for i, _a in enumerate(c["assessments"]):
            h2.append("<th>%d</th>" % (i + 1))
        h2.append("<th>الدرجة</th>")
    if a_max > 0:
        h1.append('<th rowspan="2">الحضور<br><span style="font-weight:400">'
                  'من %s</span></th>' % _fmt(a_max))
    if b_max > 0:
        h1.append('<th rowspan="2">السلوك<br><span style="font-weight:400">'
                  'من %s</span></th>' % _fmt(b_max))
    h1.append('<th rowspan="2">المجموع<br><span style="font-weight:400">'
              'من ١٠٠</span></th>')

    body = []
    for s in gb["students"]:
        tds = ['<td class="nm">%s</td>' % _esc(s["name"])]
        for c in comps:
            for a in c["assessments"]:
                v = s["marks"].get(str(a["id"]))
                if v is None:
                    tds.append('<td class="na">–</td>')
                elif c["grade_mode"] == "bool":
                    tds.append('<td class="%s">%s</td>'
                               % ("ok" if v >= 1 else "no", "✓" if v >= 1 else "✗"))
                else:
                    tds.append("<td>%s</td>" % _fmt(v))
            tds.append('<td class="sc">%s</td>'
                       % _fmt(s["components"].get(str(c["id"]))))
        if a_max > 0:
            tds.append("<td>%s</td>" % _fmt(s.get("att_score")))
        if b_max > 0:
            tds.append("<td>%s</td>" % _fmt(s.get("beh_score")))
        low = s["total"] is not None and s["total"] < 60
        tds.append('<td class="tot%s">%s</td>'
                   % (" low" if low else "", _fmt(s["total"])))
        body.append("<tr>%s</tr>" % "".join(tds))

    principal_title = cfg.get("principal_title") or "مدير المدرسة"
    html = (
        '<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8">'
        '<title>دفتر المتابعة — ' + _esc(gb["subject"]["subject"]) + '</title>'
        '<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;'
        '500;700;900&display=swap" rel="stylesheet">'
        '<style>' + _PRINT_CSS + '</style></head><body>'
        '<div class="noprint"><button onclick="window.print()">🖨️ طباعة</button></div>'
        '<div class="hdr">'
        '<div class="side">المملكة العربية السعودية<br>وزارة التعليم<br>'
        + _esc(cfg.get("education_region", "")) + '</div>'
        '<div class="mid">' + logo_img_tag_from_config(cfg)
        + '<b>' + _esc(cfg.get("school_name", "")) + '</b>'
        '<span>سجل متابعة الطالب</span></div>'
        '<div class="side" style="text-align:left">العام الدراسي '
        + _esc(cfg.get("school_year", "١٤٤٧هـ")) + '<br>'
        + _esc(tt.get_school_stage()) + '</div>'
        '</div>'
        '<div class="meta">'
        '<div>المادة: ' + _esc(gb["subject"]["subject"]) + '</div>'
        '<div>الفصل: ' + _esc(cls_name) + '</div>'
        '<div>الفترة: ' + str(gb["period"]) + '</div>'
        '<div>المعلم: ' + _esc(teacher) + '</div>'
        '<div>عدد الطلاب: ' + str(len(gb["students"])) + '</div>'
        '</div>'
        '<table><thead><tr>' + "".join(h1) + '</tr>'
        '<tr class="sub">' + "".join(h2) + '</tr></thead>'
        '<tbody>' + "".join(body) + '</tbody></table>'
        '<div class="sign">'
        '<div>معلم المادة<div class="line">' + _esc(teacher) + '</div></div>'
        '<div>&nbsp;</div>'
        '<div>' + _esc(principal_title) + '<div class="line">'
        + _esc(cfg.get("principal_name", "")) + '</div></div>'
        '</div>'
        '<div class="foot">✓ أُنجز · ✗ لم يُنجز · – لم يُرصد بعد '
        '(لا يدخل في الحساب) — صدرت من DarbStu</div>'
        '</body></html>')
    return HTMLResponse(html)
