# -*- coding: utf-8 -*-
"""
teacher_tools.py — دفتر المتابعة الصفّي (تبويب أدوات المعلم)

يُدير توزيع الدرجات ورصد التقييمات لكل (معلّم، فصل، مادة). المنطق كله هنا
لا في المسارات، حتى يصلح السطحَ نفسه للويب والجوال معاً.

قاعدتان تحكمان الحساب:
  • «لم يُرصد» ليس صفراً. غياب السطر في tt_marks يعني أن المعلّم لم يصل
    إليه بعد، فيخرج من البسط والمقام معاً. لولا ذلك لظهر كل طالب راسباً
    في أول أسبوع من الفصل.
  • درجة المكوّن سقفٌ صلب في وضع «درجات»: مجموع تقييماته لا يتجاوز
    max_score، ويُرفض ما زاد عند الإضافة لا عند العرض.

الحضور لا يُرصد هنا. يُقرأ من سجل DarbStu القائم عبر query_absences —
فالمدرسة تُحضِّر مرة واحدة، لا مرة لكل مادة.
"""
import datetime
import json
import sqlite3

from database import (get_db, load_students, query_absences,
                      get_exempted_students, get_school_stage,
                      stage_level_count, stage_level_name,
                      _stage_ordinal_digit)


# ── وضع التصحيح وتصنيف التقييم ───────────────────────────────────
MODE_BOOL = "bool"     # صح/خطأ — عدد التقييمات مفتوح
MODE_SCORE = "score"   # درجات — كل تقييم يقتطع من درجة المكوّن

CAT_PERF = "perf"      # المهام الأدائية والمشاركة
CAT_EXAM = "exam"      # تقويمات شفهية وتحريرية

CATEGORY_LABELS = {
    CAT_PERF: "المهام الأدائية والمشاركة",
    CAT_EXAM: "تقويمات شفهية وتحريرية",
}

# مواد مقترحة في المعالج، لكل مرحلة موادها. اقتراحٌ لا حصر — للمعلّم أن
# يكتب ما ليس في القائمة.
STAGE_SUBJECTS = {
    "ابتدائي": ["القرآن الكريم", "الدراسات الإسلامية", "لغتي", "الرياضيات",
                "العلوم", "الدراسات الاجتماعية", "اللغة الإنجليزية",
                "التربية الفنية", "التربية البدنية", "المهارات الرقمية"],
    "متوسط": ["القرآن الكريم", "الدراسات الإسلامية", "لغتي الخالدة",
              "الرياضيات", "العلوم", "الدراسات الاجتماعية",
              "اللغة الإنجليزية", "التربية الفنية", "التربية البدنية",
              "المهارات الرقمية"],
    "ثانوي": ["القرآن الكريم", "الدراسات الإسلامية", "اللغة العربية",
              "الرياضيات", "الفيزياء", "الكيمياء", "الأحياء",
              "اللغة الإنجليزية", "الدراسات الاجتماعية", "التفكير الناقد",
              "التربية الصحية", "المهارات الرقمية"],
}

# أنواع المخالفات السلوكية وحسمُها الافتراضي من درجة السلوك
BEHAVIOR_KINDS = [
    {"kind": "تأخر عن الحصة", "icon": "fa-clock", "deduct": 1},
    {"kind": "عدم إحضار الكتاب", "icon": "fa-book", "deduct": 1},
    {"kind": "إخلال بالنظام", "icon": "fa-triangle-exclamation", "deduct": 2},
    {"kind": "عدم أداء الواجب", "icon": "fa-file-circle-xmark", "deduct": 1},
    {"kind": "استخدام الجوال", "icon": "fa-mobile-screen", "deduct": 2},
]

# توزيعٌ ابتدائي يُنشأ مع المادة حتى لا يواجه المعلّم دفتراً فارغاً.
# النسب مجموعها ٦٠٪ — أعمال السنة، والأربعون الباقية للاختبار النهائي.
DEFAULT_COMPONENTS = [
    ("واجبات",                  10, CAT_PERF,  MODE_BOOL),
    ("تطبيقات وأنشطة صفية",     10, CAT_PERF,  MODE_BOOL),
    ("بحوث ومشروعات وتقارير",   10, CAT_PERF,  MODE_BOOL),
    ("المشاركة والتفاعل",       10, CAT_PERF,  MODE_BOOL),
    ("تقويمات شفهية وتحريرية",  20, CAT_EXAM,  MODE_SCORE),
]


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ══════════════════════════════════════════════════════════════
#  تجهيز الدفتر — المعالج الأول
# ══════════════════════════════════════════════════════════════
_NOOR_LEVEL = {"1314": "1", "1416": "2", "1516": "3"}


def _level_digit(cid: str, cname: str) -> str:
    """رقم مستوى الفصل من اسمه أو من ترميز نور في معرّفه."""
    d = _stage_ordinal_digit(cname or "")
    if d:
        return d
    head = str(cid or "").split("-")[0].strip()
    if head in _NOOR_LEVEL:
        return _NOOR_LEVEL[head]
    if head.isdigit() and 1 <= int(head) <= 6:
        return str(int(head))
    return ""


def get_settings(teacher: str) -> dict:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT periods, setup_done FROM tt_settings WHERE teacher=?",
                (teacher,))
    row = cur.fetchone()
    con.close()
    if not row:
        return {"periods": 2, "setup_done": 0}
    return {"periods": int(row[0] or 2), "setup_done": int(row[1] or 0)}


def save_settings(teacher: str, periods=None, setup_done=None) -> dict:
    cur_s = get_settings(teacher)
    p = int(periods) if periods else cur_s["periods"]
    p = max(1, min(6, p))
    d = int(setup_done) if setup_done is not None else cur_s["setup_done"]
    con = get_db(); cur = con.cursor()
    cur.execute(
        "INSERT INTO tt_settings (teacher, periods, setup_done, created_at) "
        "VALUES (?,?,?,?) ON CONFLICT(teacher) DO UPDATE SET "
        "periods=excluded.periods, setup_done=excluded.setup_done",
        (teacher, p, d, _now()))
    con.commit(); con.close()
    return {"ok": True, "periods": p, "setup_done": d}


def get_setup(teacher: str) -> dict:
    """
    ما يحتاجه المعالج: مرحلة المدرسة، ومستوياتها بفصولها، ومواد مقترحة.

    الصفوف تُشتق من مفتاح school_stage، فمعلّم الثانوي لا يُعرض عليه
    «أول متوسط» أصلاً. وما لا يُعرف مستواه يُجمع تحت «فصول أخرى» بدل
    أن يسقط صامتاً — مدارس كثيرة تسمّي فصولها بما لا يُحلَّل.
    """
    stage = get_school_stage()
    n = stage_level_count(stage)
    buckets = [{"digit": str(d), "name": stage_level_name(str(d), stage),
                "classes": []} for d in range(1, n + 1)]
    index = {b["digit"]: b for b in buckets}
    other = {"digit": "", "name": "فصول أخرى", "classes": []}

    for c in load_students().get("list", []):
        item = {"id": c.get("id"), "name": c.get("name", ""),
                "count": len(c.get("students", []))}
        b = index.get(_level_digit(c.get("id", ""), c.get("name", "")))
        (b or other)["classes"].append(item)

    levels = [b for b in buckets if b["classes"]]
    if other["classes"]:
        levels.append(other)

    mine = list_subjects(teacher)
    st = get_settings(teacher)
    return {"ok": True, "stage": stage, "levels": levels,
            "suggested": STAGE_SUBJECTS.get(stage, STAGE_SUBJECTS["ثانوي"]),
            "periods": st["periods"], "setup_done": st["setup_done"],
            "existing": [{"class_id": s["class_id"], "subject": s["subject"]}
                         for s in mine],
            "has_subjects": bool(mine)}


def apply_setup(teacher: str, class_ids, subjects, periods=2) -> dict:
    """يُنشئ دفتراً لكل (فصل × مادة). الموجود سلفاً يُتجاوَز بلا خطأ."""
    class_ids = [str(c).strip() for c in (class_ids or []) if str(c).strip()]
    subjects = [str(s).strip() for s in (subjects or []) if str(s).strip()]
    if not class_ids:
        return {"ok": False, "msg": "اختر فصلاً واحداً على الأقل"}
    if not subjects:
        return {"ok": False, "msg": "اختر مادةً واحدة على الأقل"}

    created = 0
    for cid in class_ids:
        for subj in subjects:
            if create_subject(teacher, cid, subj).get("ok"):
                created += 1
    save_settings(teacher, periods=periods, setup_done=1)
    return {"ok": True, "created": created,
            "skipped": len(class_ids) * len(subjects) - created}


# ══════════════════════════════════════════════════════════════
#  المواد المسندة
# ══════════════════════════════════════════════════════════════
def list_subjects(teacher: str) -> list:
    """مواد المعلّم مرتّبةً، مع اسم الفصل المعروض."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM tt_subjects WHERE teacher=? "
                "ORDER BY class_id, subject", (teacher,))
    rows = _rows(cur)
    con.close()

    names = {c["id"]: c["name"] for c in load_students().get("list", [])}
    for r in rows:
        r["class_name"] = names.get(r["class_id"], r["class_id"])
    return rows


def create_subject(teacher: str, class_id: str, subject: str) -> dict:
    """يُنشئ مادةً ويزرع فيها التوزيع الابتدائي للفترة الأولى."""
    subject = (subject or "").strip()
    class_id = (class_id or "").strip()
    if not subject or not class_id:
        return {"ok": False, "msg": "الفصل والمادة مطلوبان"}

    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO tt_subjects (teacher, class_id, subject, created_at) "
                    "VALUES (?,?,?,?)", (teacher, class_id, subject, _now()))
        sid = cur.lastrowid
    except sqlite3.IntegrityError:
        con.close()
        return {"ok": False, "msg": "هذه المادة مسندة لك في هذا الفصل بالفعل"}

    for i, (name, mx, cat, mode) in enumerate(DEFAULT_COMPONENTS):
        cur.execute(
            "INSERT INTO tt_components "
            "(subject_id, period, name, max_score, category, grade_mode, sort_order, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (sid, 1, name, mx, cat, mode, i, _now()))

    con.commit(); con.close()
    return {"ok": True, "id": sid}


def delete_subject(subject_id: int, teacher: str) -> dict:
    """يحذف المادة وكل ما تحتها. مقيَّدٌ بصاحبها حتى لا يحذف معلّمٌ دفتر غيره."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM tt_subjects WHERE id=? AND teacher=?",
                (subject_id, teacher))
    if not cur.fetchone():
        con.close()
        return {"ok": False, "msg": "المادة غير موجودة"}

    cur.execute("SELECT id FROM tt_components WHERE subject_id=?", (subject_id,))
    comp_ids = [r[0] for r in cur.fetchall()]
    for cid in comp_ids:
        _delete_component_rows(cur, cid)
    cur.execute("DELETE FROM tt_subjects WHERE id=?", (subject_id,))
    con.commit(); con.close()
    return {"ok": True}


def owns_subject(subject_id: int, teacher: str, role: str = "") -> bool:
    """المعلّم يرى دفتره وحده؛ المدير والوكيل يريان كل الدفاتر."""
    if role in ("admin", "deputy"):
        return True
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT 1 FROM tt_subjects WHERE id=? AND teacher=?",
                (subject_id, teacher))
    ok = cur.fetchone() is not None
    con.close()
    return ok


# ══════════════════════════════════════════════════════════════
#  المكوّنات — توزيع الدرجات
# ══════════════════════════════════════════════════════════════
def get_components(subject_id: int, period: int = 1) -> list:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM tt_components WHERE subject_id=? AND period=? "
                "ORDER BY sort_order, id", (subject_id, period))
    rows = _rows(cur)
    con.close()
    return rows


def save_component(subject_id: int, period: int, name: str, max_score,
                   category: str, grade_mode: str, comp_id=None) -> dict:
    name = (name or "").strip()
    if not name:
        return {"ok": False, "msg": "اسم المكوّن مطلوب"}
    try:
        max_score = float(max_score)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "درجة المكوّن يجب أن تكون رقماً"}
    if max_score <= 0:
        return {"ok": False, "msg": "درجة المكوّن يجب أن تكون أكبر من صفر"}
    if category not in (CAT_PERF, CAT_EXAM):
        category = CAT_PERF
    if grade_mode not in (MODE_BOOL, MODE_SCORE):
        grade_mode = MODE_BOOL

    con = get_db(); cur = con.cursor()
    if comp_id:
        # خفضُ درجة المكوّن تحت ما وُزّع فعلاً يجعل المجموع مستحيلاً،
        # فيُمنع بدل أن يُصحَّح لاحقاً على حساب الطلاب.
        cur.execute("SELECT COALESCE(SUM(max_score),0) FROM tt_assessments "
                    "WHERE component_id=?", (comp_id,))
        allocated = cur.fetchone()[0] or 0
        cur.execute("SELECT grade_mode FROM tt_components WHERE id=?", (comp_id,))
        row = cur.fetchone()
        cur_mode = row[0] if row else grade_mode
        if cur_mode == MODE_SCORE and max_score < allocated:
            con.close()
            return {"ok": False,
                    "msg": "الدرجة الموزّعة على التقييمات الحالية %g — "
                           "لا يمكن خفض المكوّن دونها" % allocated}
        cur.execute("UPDATE tt_components SET name=?, max_score=?, category=?, "
                    "grade_mode=? WHERE id=?",
                    (name, max_score, category, grade_mode, comp_id))
        new_id = comp_id
    else:
        cur.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM tt_components "
                    "WHERE subject_id=? AND period=?", (subject_id, period))
        order = cur.fetchone()[0] or 0
        cur.execute(
            "INSERT INTO tt_components "
            "(subject_id, period, name, max_score, category, grade_mode, sort_order, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (subject_id, period, name, max_score, category, grade_mode, order, _now()))
        new_id = cur.lastrowid
    con.commit(); con.close()
    return {"ok": True, "id": new_id}


def _delete_component_rows(cur, comp_id: int):
    cur.execute("SELECT id FROM tt_assessments WHERE component_id=?", (comp_id,))
    for (aid,) in cur.fetchall():
        cur.execute("DELETE FROM tt_marks WHERE assessment_id=?", (aid,))
    cur.execute("DELETE FROM tt_assessments WHERE component_id=?", (comp_id,))
    cur.execute("DELETE FROM tt_components WHERE id=?", (comp_id,))


def delete_component(comp_id: int) -> dict:
    con = get_db(); cur = con.cursor()
    _delete_component_rows(cur, comp_id)
    con.commit(); con.close()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════
#  التقييمات
# ══════════════════════════════════════════════════════════════
def remaining_budget(comp_id: int) -> dict:
    """الدرجة المتبقية للتوزيع في مكوّن «درجات»."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT max_score, grade_mode FROM tt_components WHERE id=?", (comp_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return {"ok": False, "msg": "المكوّن غير موجود"}
    max_score, mode = float(row[0]), row[1]
    cur.execute("SELECT COALESCE(SUM(max_score),0) FROM tt_assessments "
                "WHERE component_id=?", (comp_id,))
    used = float(cur.fetchone()[0] or 0)
    con.close()
    return {"ok": True, "mode": mode, "max": max_score,
            "used": used, "remaining": max(0.0, max_score - used)}


def add_assessment(comp_id: int, title: str = "", max_score=None,
                   due_date: str = "") -> dict:
    """
    يُضيف تقييماً. في وضع «درجات» يُرفض ما يتجاوز المتبقي — السقف حاجزٌ
    لا تحذير، وإلا خرج مجموع الطالب عن درجة المكوّن.
    """
    info = remaining_budget(comp_id)
    if not info.get("ok"):
        return info

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT name FROM tt_components WHERE id=?", (comp_id,))
    comp_name = (cur.fetchone() or [""])[0]
    cur.execute("SELECT COUNT(*), COALESCE(MAX(sort_order),-1)+1 "
                "FROM tt_assessments WHERE component_id=?", (comp_id,))
    count, order = cur.fetchone()

    title = (title or "").strip() or "%s (%d)" % (comp_name, count + 1)

    if info["mode"] == MODE_SCORE:
        if info["remaining"] <= 0:
            con.close()
            return {"ok": False, "full": True,
                    "msg": "لا توجد درجات متبقية في مكوّن «%s»" % comp_name}
        try:
            max_score = float(max_score)
        except (TypeError, ValueError):
            con.close()
            return {"ok": False, "msg": "درجة التقييم مطلوبة"}
        if max_score <= 0:
            con.close()
            return {"ok": False, "msg": "درجة التقييم يجب أن تكون أكبر من صفر"}
        if max_score > info["remaining"] + 1e-9:
            con.close()
            return {"ok": False,
                    "msg": "المتبقي للمكوّن %g فقط" % info["remaining"]}
    else:
        max_score = 0

    cur.execute("INSERT INTO tt_assessments "
                "(component_id, title, max_score, due_date, sort_order, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (comp_id, title, max_score, due_date or "", order, _now()))
    aid = cur.lastrowid
    con.commit(); con.close()
    return {"ok": True, "id": aid, "title": title}


def delete_assessment(asmt_id: int) -> dict:
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM tt_marks WHERE assessment_id=?", (asmt_id,))
    cur.execute("DELETE FROM tt_assessments WHERE id=?", (asmt_id,))
    con.commit(); con.close()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════
#  الرصد
# ══════════════════════════════════════════════════════════════
def set_mark(asmt_id: int, student_id: str, value, by: str = "") -> dict:
    """
    يرصد درجة. value=None يمسح الرصد ويعيد الخلية إلى «لم يُرصد» —
    وهي الحالة التي يحتاجها المعلّم حين يرصد بالخطأ.
    """
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT c.grade_mode, a.max_score FROM tt_assessments a "
                "JOIN tt_components c ON c.id=a.component_id WHERE a.id=?", (asmt_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return {"ok": False, "msg": "التقييم غير موجود"}
    mode, a_max = row[0], float(row[1] or 0)

    if value is None or value == "":
        cur.execute("DELETE FROM tt_marks WHERE assessment_id=? AND student_id=?",
                    (asmt_id, str(student_id)))
        con.commit(); con.close()
        return {"ok": True, "value": None}

    try:
        value = float(value)
    except (TypeError, ValueError):
        con.close()
        return {"ok": False, "msg": "قيمة غير صالحة"}

    if mode == MODE_BOOL:
        value = 1.0 if value >= 1 else 0.0
    else:
        if value < 0:
            value = 0.0
        if a_max and value > a_max:
            con.close()
            return {"ok": False, "msg": "الدرجة تتجاوز درجة التقييم (%g)" % a_max}

    cur.execute(
        "INSERT INTO tt_marks (assessment_id, student_id, value, updated_by, updated_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(assessment_id, student_id) DO UPDATE SET "
        "value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (asmt_id, str(student_id), value, by, _now()))
    con.commit(); con.close()
    return {"ok": True, "value": value}


def award_full(asmt_id: int, class_id: str, by: str = "") -> dict:
    """
    يمنح جميع طلاب الفصل الدرجة الكاملة في تقييم.

    يلتقط الحال قبل الكتابة: المنح يطمس رصداً سابقاً، والضغطة على العمود
    الخطأ كانت تُفقد عمل حصةٍ كاملة بلا رجعة.
    """
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT c.grade_mode, a.max_score FROM tt_assessments a "
                "JOIN tt_components c ON c.id=a.component_id WHERE a.id=?", (asmt_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return {"ok": False, "msg": "التقييم غير موجود"}
    full = 1.0 if row[0] == MODE_BOOL else float(row[1] or 0)

    ids = [str(s["id"]) for s in _class_students(class_id)]
    cur.execute("SELECT student_id, value FROM tt_marks WHERE assessment_id=?",
                (asmt_id,))
    before = {str(r[0]): r[1] for r in cur.fetchall()}
    snapshot = {sid: before.get(sid) for sid in ids}   # None = لم يكن مرصوداً

    now = _now()
    cur.execute("INSERT INTO tt_award_undo (assessment_id, payload, created_by, created_at) "
                "VALUES (?,?,?,?) ON CONFLICT(assessment_id) DO UPDATE SET "
                "payload=excluded.payload, created_by=excluded.created_by, "
                "created_at=excluded.created_at",
                (asmt_id, json.dumps(snapshot), by, now))
    cur.executemany(
        "INSERT INTO tt_marks (assessment_id, student_id, value, updated_by, updated_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(assessment_id, student_id) DO UPDATE SET "
        "value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        [(asmt_id, sid, full, by, now) for sid in ids])
    con.commit(); con.close()
    changed = sum(1 for sid in ids if snapshot.get(sid) != full)
    return {"ok": True, "count": len(ids), "overwritten": changed}


def undo_award(asmt_id: int, by: str = "") -> dict:
    """يُرجع التقييم إلى ما كان عليه قبل آخر «منح الجميع». يُستهلك مرةً."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT payload FROM tt_award_undo WHERE assessment_id=?", (asmt_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return {"ok": False, "msg": "لا يوجد منحٌ جماعي يمكن التراجع عنه"}
    snapshot = json.loads(row[0])
    now = _now()
    restored = 0
    for sid, val in snapshot.items():
        if val is None:
            cur.execute("DELETE FROM tt_marks WHERE assessment_id=? AND student_id=?",
                        (asmt_id, sid))
        else:
            cur.execute(
                "INSERT INTO tt_marks (assessment_id, student_id, value, updated_by, updated_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(assessment_id, student_id) DO UPDATE SET "
                "value=excluded.value, updated_by=excluded.updated_by, "
                "updated_at=excluded.updated_at",
                (asmt_id, sid, val, by, now))
        restored += 1
    cur.execute("DELETE FROM tt_award_undo WHERE assessment_id=?", (asmt_id,))
    con.commit(); con.close()
    return {"ok": True, "restored": restored}


def undoable_awards(subject_id: int, period: int) -> list:
    """معرّفات التقييمات التي لها لقطة تراجع — لإظهار الزر في مكانه فقط."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT u.assessment_id FROM tt_award_undo u "
                "JOIN tt_assessments a ON a.id=u.assessment_id "
                "JOIN tt_components c ON c.id=a.component_id "
                "WHERE c.subject_id=? AND c.period=?", (subject_id, period))
    ids = [r[0] for r in cur.fetchall()]
    con.close()
    return ids


# ══════════════════════════════════════════════════════════════
#  التصفير ونسخ التوزيع
# ══════════════════════════════════════════════════════════════
def reset_marks(subject_id: int, period=None) -> dict:
    """
    يمسح الأرقام ويُبقي البنية: المكوّنات والتقييمات تبقى، والمرصود يزول.
    period=None يعني كل الفترات.
    """
    con = get_db(); cur = con.cursor()
    if period is None:
        cur.execute("SELECT id FROM tt_components WHERE subject_id=?", (subject_id,))
    else:
        cur.execute("SELECT id FROM tt_components WHERE subject_id=? AND period=?",
                    (subject_id, period))
    comp_ids = [r[0] for r in cur.fetchall()]
    marks = 0
    if comp_ids:
        ph = ",".join("?" * len(comp_ids))
        cur.execute("SELECT id FROM tt_assessments WHERE component_id IN (%s)" % ph,
                    comp_ids)
        aids = [r[0] for r in cur.fetchall()]
        if aids:
            aph = ",".join("?" * len(aids))
            cur.execute("SELECT COUNT(*) FROM tt_marks WHERE assessment_id IN (%s)" % aph,
                        aids)
            marks = cur.fetchone()[0] or 0
            cur.execute("DELETE FROM tt_marks WHERE assessment_id IN (%s)" % aph, aids)
            cur.execute("DELETE FROM tt_award_undo WHERE assessment_id IN (%s)" % aph, aids)

    if period is None:
        cur.execute("DELETE FROM tt_attendance_marks WHERE subject_id=?", (subject_id,))
        cur.execute("DELETE FROM tt_behavior WHERE subject_id=?", (subject_id,))
    else:
        cur.execute("DELETE FROM tt_attendance_marks WHERE subject_id=? AND period=?",
                    (subject_id, period))
        cur.execute("DELETE FROM tt_behavior WHERE subject_id=? AND period=?",
                    (subject_id, period))
    con.commit(); con.close()
    return {"ok": True, "marks": marks}


def copy_components(from_subject_id: int, period: int, targets, teacher: str,
                    with_assessments: bool = True, replace: bool = False,
                    with_options: bool = False) -> dict:
    """
    ينسخ توزيع الدرجات إلى مواد المعلّم الأخرى.

    ما يُتخطّى هو المادة التي **رُصدت فيها درجات**، لا التي لها بنية.
    كانت القاعدة «تخطَّ ما له مكوّنات» فلا تنسخ شيئاً أبداً: كل مادة
    تُنشأ ومعها المكوّنات الافتراضية الخمسة، فكل هدفٍ «له توزيع».
    البنية الفارغة لا تُفقد شيئاً باستبدالها؛ الدرجات هي ما يُحمى.

    سقفا درجتَي الحضور والسلوك لا ينتقلان إلا بـwith_options صريح: المادة
    الجديدة قد لا تُرصد فيها هذه الدرجات أصلاً، وانتقالُها ضمناً يجعل
    الهدف يبدو مرصوداً — عمود سلوكٍ كاملٌ للجميع وحضورٌ محسوبٌ فوراً.
    والرصد نفسه (المخالفات ودرجات الحضور اليدوية) لا يُنسخ أبداً.
    """
    targets = [int(t) for t in (targets or [])]
    if not targets:
        return {"ok": False, "msg": "اختر مادةً واحدة على الأقل"}

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM tt_components WHERE subject_id=? AND period=? "
                "ORDER BY sort_order, id", (from_subject_id, period))
    src = _rows(cur)
    if not src:
        con.close()
        return {"ok": False, "msg": "لا يوجد توزيعٌ في هذه الفترة لنسخه"}

    asmts = {}
    if with_assessments:
        for c in src:
            cur.execute("SELECT title, max_score, sort_order FROM tt_assessments "
                        "WHERE component_id=? ORDER BY sort_order, id", (c["id"],))
            asmts[c["id"]] = cur.fetchall()

    cur.execute("SELECT attendance_mode, attendance_max, behavior_max "
                "FROM tt_subjects WHERE id=?", (from_subject_id,))
    opts = cur.fetchone()

    # المِلكية تُتحقَّق هنا لا في المسار: النسخ يكتب في عدة مواد دفعةً واحدة
    cur.execute("SELECT id FROM tt_subjects WHERE teacher=?", (teacher,))
    mine = {r[0] for r in cur.fetchall()}

    copied, skipped, denied = [], [], []
    now = _now()
    for tid in targets:
        if tid == from_subject_id:
            continue
        if tid not in mine:
            denied.append(tid); continue

        cur.execute("SELECT COUNT(*) FROM tt_marks m "
                    "JOIN tt_assessments a ON a.id=m.assessment_id "
                    "JOIN tt_components c ON c.id=a.component_id "
                    "WHERE c.subject_id=? AND c.period=?", (tid, period))
        if cur.fetchone()[0] and not replace:
            skipped.append(tid); continue

        cur.execute("SELECT id FROM tt_components WHERE subject_id=? AND period=?",
                    (tid, period))
        for cid in [r[0] for r in cur.fetchall()]:
            _delete_component_rows(cur, cid)

        for c in src:
            cur.execute(
                "INSERT INTO tt_components (subject_id, period, name, max_score, "
                "category, grade_mode, sort_order, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (tid, period, c["name"], c["max_score"], c["category"],
                 c["grade_mode"], c["sort_order"], now))
            new_cid = cur.lastrowid
            for title, mx, order in asmts.get(c["id"], []):
                cur.execute(
                    "INSERT INTO tt_assessments (component_id, title, max_score, "
                    "due_date, sort_order, created_at) VALUES (?,?,?,?,?,?)",
                    (new_cid, title, mx, "", order, now))
        if with_options and opts:
            cur.execute("UPDATE tt_subjects SET attendance_mode=?, attendance_max=?, "
                        "behavior_max=? WHERE id=?",
                        (opts[0], opts[1], opts[2], tid))
        copied.append(tid)
    con.commit(); con.close()
    return {"ok": True, "copied": len(copied), "skipped": len(skipped),
            "denied": len(denied), "components": len(src),
            "assessments": sum(len(v) for v in asmts.values())}


# ══════════════════════════════════════════════════════════════
#  خيارات المادة: الحضور والسلوك
# ══════════════════════════════════════════════════════════════
def save_subject_options(subject_id: int, attendance_mode: str,
                         attendance_max, behavior_max) -> dict:
    if attendance_mode not in ("system", "manual"):
        attendance_mode = "system"
    try:
        a_max = max(0.0, float(attendance_max or 0))
        b_max = max(0.0, float(behavior_max or 0))
    except (TypeError, ValueError):
        return {"ok": False, "msg": "الدرجات يجب أن تكون أرقاماً"}
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE tt_subjects SET attendance_mode=?, attendance_max=?, "
                "behavior_max=? WHERE id=?",
                (attendance_mode, a_max, b_max, subject_id))
    con.commit(); con.close()
    return {"ok": True}


def set_attendance_mark(subject_id: int, period: int, student_id: str,
                        value, by: str = "") -> dict:
    """رصد درجة الحضور يدوياً — لا يُقبل إلا في وضع manual."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT attendance_mode, attendance_max FROM tt_subjects WHERE id=?",
                (subject_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return {"ok": False, "msg": "المادة غير موجودة"}
    mode, a_max = row[0], float(row[1] or 0)
    if mode != "manual":
        con.close()
        return {"ok": False, "msg": "درجة الحضور محسوبة من النظام — "
                                    "غيّر المصدر إلى «يدوي» أولاً"}
    if value is None or value == "":
        cur.execute("DELETE FROM tt_attendance_marks WHERE subject_id=? AND "
                    "period=? AND student_id=?", (subject_id, period, str(student_id)))
        con.commit(); con.close()
        return {"ok": True, "value": None}
    try:
        value = float(value)
    except (TypeError, ValueError):
        con.close()
        return {"ok": False, "msg": "قيمة غير صالحة"}
    if value < 0:
        value = 0.0
    if a_max and value > a_max:
        con.close()
        return {"ok": False, "msg": "الدرجة تتجاوز درجة الحضور (%g)" % a_max}
    cur.execute(
        "INSERT INTO tt_attendance_marks "
        "(subject_id, period, student_id, value, updated_by, updated_at) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(subject_id, period, student_id) "
        "DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, "
        "updated_at=excluded.updated_at",
        (subject_id, period, str(student_id), value, by, _now()))
    con.commit(); con.close()
    return {"ok": True, "value": value}


def behavior_budget(subject_id: int, period: int, student_id: str) -> dict:
    """ما بقي من درجة السلوك لهذا الطالب بعد ما حُسم منه."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT behavior_max FROM tt_subjects WHERE id=?", (subject_id,))
    row = cur.fetchone()
    b_max = float(row[0] or 0) if row else 0.0
    cur.execute("SELECT COALESCE(SUM(deduct),0) FROM tt_behavior "
                "WHERE subject_id=? AND period=? AND student_id=?",
                (subject_id, period, str(student_id)))
    used = float(cur.fetchone()[0] or 0)
    con.close()
    return {"max": b_max, "used": used, "remaining": max(0.0, b_max - used)}


def add_behavior(subject_id: int, period: int, student_id: str, kind: str,
                 note: str = "", deduct=None, by: str = "") -> dict:
    """
    يُسجّل مخالفة. الحسم مقيَّدٌ بالمتبقي من درجة السلوك عند الكتابة لا عند
    العرض: خمس مخالفات بمجموع ٩ كانت تُخزَّن كاملةً على درجةٍ سقفها ٥،
    فيظهر صفرٌ مقيَّد بينما المخزون يقول غير ذلك — ويختل أي تقرير يجمع
    الحسومات. والمخالفة تُسجَّل دائماً ولو نفدت الدرجة: السجل السلوكي
    وثيقةٌ للمرشد وولي الأمر، لا مجرّد رصيدِ درجات.
    """
    kind = (kind or "").strip()
    if not kind:
        return {"ok": False, "msg": "نوع المخالفة مطلوب"}
    if deduct is None:
        deduct = next((k["deduct"] for k in BEHAVIOR_KINDS
                       if k["kind"] == kind), 1)
    try:
        requested = max(0.0, float(deduct))
    except (TypeError, ValueError):
        requested = 1.0

    budget = behavior_budget(subject_id, period, student_id)
    applied = min(requested, budget["remaining"])

    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO tt_behavior (subject_id, period, student_id, kind, "
                "note, deduct, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (subject_id, period, str(student_id), kind, (note or "").strip(),
                 applied, by, _now()))
    bid = cur.lastrowid
    con.commit(); con.close()
    return {"ok": True, "id": bid, "deduct": applied,
            "requested": requested, "capped": applied < requested,
            "remaining": max(0.0, budget["remaining"] - applied),
            "max": budget["max"]}


def list_behavior(subject_id: int, period: int, student_id: str) -> list:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM tt_behavior WHERE subject_id=? AND period=? "
                "AND student_id=? ORDER BY created_at DESC",
                (subject_id, period, str(student_id)))
    rows = _rows(cur)
    con.close()
    return rows


def delete_behavior(behavior_id: int) -> dict:
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM tt_behavior WHERE id=?", (behavior_id,))
    con.commit(); con.close()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════
#  الدفتر المجمَّع
# ══════════════════════════════════════════════════════════════
def _class_students(class_id: str) -> list:
    """طلاب الفصل بعد استبعاد المستثنين — استبعادُهم قرارُ المدرسة لا المعلّم."""
    try:
        exempted = {str(e["student_id"]) for e in get_exempted_students()}
    except Exception:
        exempted = set()
    for c in load_students().get("list", []):
        if c["id"] == class_id:
            return [s for s in c.get("students", [])
                    if str(s.get("id")) not in exempted]
    return []


def _component_score(mode: str, marks: list, asmts: list, comp_max: float):
    """
    يُرجع (المحصَّل، السقف الفعلي). «لم يُرصد» خارج الحساب في الوضعين،
    فالطالب يُقاس بما رُصد له لا بما لم يصل إليه المعلّم بعد.
    """
    graded = [(a, marks[a["id"]]) for a in asmts
              if marks.get(a["id"]) is not None]
    if not graded:
        return None, 0.0
    if mode == MODE_BOOL:
        ratio = sum(v for _, v in graded) / float(len(graded))
        return ratio * comp_max, comp_max
    earned = sum(v for _, v in graded)
    ceiling = sum(float(a["max_score"] or 0) for a, _ in graded)
    return earned, ceiling


def get_gradebook(subject_id: int, period: int = 1) -> dict:
    """كل ما تحتاجه الشبكة في نداء واحد: مكوّنات، تقييمات، رصد، مجاميع."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT * FROM tt_subjects WHERE id=?", (subject_id,))
    subj = _rows(cur)
    if not subj:
        con.close()
        return {"ok": False, "msg": "المادة غير موجودة"}
    subj = subj[0]

    cur.execute("SELECT * FROM tt_components WHERE subject_id=? AND period=? "
                "ORDER BY sort_order, id", (subject_id, period))
    comps = _rows(cur)

    comp_ids = [c["id"] for c in comps]
    asmts_by_comp = {cid: [] for cid in comp_ids}
    marks = {}
    if comp_ids:
        ph = ",".join("?" * len(comp_ids))
        cur.execute("SELECT * FROM tt_assessments WHERE component_id IN (%s) "
                    "ORDER BY sort_order, id" % ph, comp_ids)
        for a in _rows(cur):
            asmts_by_comp[a["component_id"]].append(a)

        cur.execute(
            "SELECT m.assessment_id, m.student_id, m.value FROM tt_marks m "
            "JOIN tt_assessments a ON a.id=m.assessment_id "
            "WHERE a.component_id IN (%s)" % ph, comp_ids)
        for aid, sid, val in cur.fetchall():
            marks.setdefault(str(sid), {})[aid] = val

    cur.execute("SELECT student_id, value FROM tt_attendance_marks "
                "WHERE subject_id=? AND period=?", (subject_id, period))
    att_manual = {str(r[0]): r[1] for r in cur.fetchall()}

    cur.execute("SELECT student_id, COUNT(*), COALESCE(SUM(deduct),0) "
                "FROM tt_behavior WHERE subject_id=? AND period=? "
                "GROUP BY student_id", (subject_id, period))
    beh = {str(r[0]): {"count": r[1], "deduct": float(r[2] or 0)}
           for r in cur.fetchall()}
    con.close()

    students = _class_students(subj["class_id"])
    absence_pct = _attendance_pct(subj["class_id"], students)

    a_mode = subj.get("attendance_mode") or "system"
    a_max = float(subj.get("attendance_max") or 0)
    b_max = float(subj.get("behavior_max") or 0)

    rows = []
    for s in students:
        sid = str(s["id"])
        smarks = marks.get(sid, {})
        cells, earned_sum, ceiling_sum = {}, 0.0, 0.0
        graded_any = False
        for c in comps:
            score, ceiling = _component_score(
                c["grade_mode"], smarks, asmts_by_comp[c["id"]], float(c["max_score"]))
            cells[c["id"]] = score
            if score is not None:
                graded_any = True
                earned_sum += score
                ceiling_sum += ceiling

        # درجة الحضور: محسوبة من نسبة الحضور، أو مرصودة يدوياً. الوضع
        # اليدوي غير المرصود يخرج من الحساب كأي خلية لم تُرصد.
        pct = absence_pct.get(sid)
        a_score = None
        if a_max > 0:
            if a_mode == "manual":
                a_score = att_manual.get(sid)
            elif pct is not None:
                a_score = round(pct / 100.0 * a_max, 2)
            if a_score is not None:
                earned_sum += a_score
                ceiling_sum += a_max

        # درجة السلوك: تبدأ كاملة ويُحسم منها. لا تخرج من الحساب أبداً —
        # من لا مخالفة له يستحق الدرجة كاملةً لا «لم يُرصد».
        b_info = beh.get(sid, {"count": 0, "deduct": 0.0})
        b_score = None
        if b_max > 0:
            b_score = max(0.0, b_max - b_info["deduct"])
            earned_sum += b_score
            ceiling_sum += b_max

        # المجموع لا يُبنى على الحضور والسلوك وحدهما. دفترٌ لم يُرصد فيه
        # تقييمٌ واحد كان يُظهر ١٠٠ لكل طالب (حضورٌ كامل + سلوكٌ كامل)،
        # فيبدو مرصوداً وهو فارغ — وهو ما ظنّه ماهر نسخاً للدرجات.
        total = (round(earned_sum / ceiling_sum * 100, 1)
                 if (graded_any and ceiling_sum) else None)
        rows.append({
            "id": sid,
            "name": s.get("name", ""),
            "marks": {str(k): v for k, v in smarks.items()},
            "components": {str(k): (round(v, 2) if v is not None else None)
                           for k, v in cells.items()},
            "total": total,
            "attendance": pct,
            "att_score": a_score,
            "behavior": b_info["count"],
            "beh_score": b_score,
        })

    for c in comps:
        c["assessments"] = asmts_by_comp[c["id"]]
        c["allocated"] = sum(float(a["max_score"] or 0) for a in asmts_by_comp[c["id"]])

    return {"ok": True, "subject": subj, "period": period,
            "components": comps, "students": rows,
            "att_mode": a_mode, "att_max": a_max, "beh_max": b_max,
            "behavior_kinds": BEHAVIOR_KINDS,
            "undoable": undoable_awards(subject_id, period)}


# ══════════════════════════════════════════════════════════════
#  التحليل والتصنيف واقتراح المعالجة
# ══════════════════════════════════════════════════════════════
# التصنيف على المحصَّل من المرصود لا من الدرجة الكاملة — الطالب يُقاس
# بما رُصد له، وإلا بدا الجميع متعثّرين في أول الفصل.
TIERS = [
    (90, "متفوّق",     "#166534", "#DCFCE7"),
    (80, "متمكّن",     "#1D4ED8", "#DBEAFE"),
    (70, "متوسط",      "#92400E", "#FEF3C7"),
    (60, "يحتاج دعماً", "#C2410C", "#FFEDD5"),
    (0,  "متعثّر",      "#991B1B", "#FEE2E2"),
]

# حدودٌ تُطلق الأعلام. مضبوطة على ما يُلاحظه المعلّم فعلاً لا على أرقام
# نظرية: ٧٥٪ حضور = يوم غياب أسبوعياً، ومخالفتان في فترة نمطٌ لا حادثة.
ATT_WARN = 75.0
BEH_WARN = 2
WEAK_GAP = 15.0      # تأخّر المكوّن عن معدّل الطالب نفسه
SWING_SD = 30.0      # انحراف التقييمات — تذبذب لا مستوى ثابت
TREND_GAP = 12.0     # فرق النصف الأخير عن الأول


def _tier(pct):
    if pct is None:
        return {"name": "لم يُرصد", "color": "#64748B", "bg": "#F1F5F9", "rank": 99}
    for i, (floor, name, color, bg) in enumerate(TIERS):
        if pct >= floor:
            return {"name": name, "color": color, "bg": bg, "rank": i}
    return {"name": TIERS[-1][1], "color": TIERS[-1][2], "bg": TIERS[-1][3], "rank": 4}


def _ratios(smarks, comps, asmts_by_comp):
    """نسبة كل تقييم مرصود (٠–١) مرتّبةً زمنياً — أساس التذبذب والاتجاه."""
    out = []
    for c in comps:
        for a in asmts_by_comp.get(c["id"], []):
            v = smarks.get(str(a["id"]))
            if v is None:
                continue
            if c["grade_mode"] == MODE_BOOL:
                out.append((a["id"], float(v)))
            else:
                mx = float(a["max_score"] or 0)
                if mx > 0:
                    out.append((a["id"], max(0.0, min(1.0, float(v) / mx))))
    out.sort(key=lambda x: x[0])
    return [r for _, r in out]


def _stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5


def analyze_class(subject_id: int, period: int = 1) -> dict:
    """يحلّل كل طلاب المادة من مدخلات الدفتر، ويقترح معالجةً لكل حالة."""
    gb = get_gradebook(subject_id, period)
    if not gb.get("ok"):
        return gb

    comps = gb["components"]
    asmts_by_comp = {c["id"]: c.get("assessments", []) for c in comps}
    total_cells = sum(len(v) for v in asmts_by_comp.values())

    rows = []
    for s in gb["students"]:
        pct = s["total"]
        tier = _tier(pct)
        ratios = _ratios(s["marks"], comps, asmts_by_comp)
        flags, actions = [], []

        # مكوّنٌ يتخلّف عن معدّل الطالب نفسه — ضعفٌ في مهارة لا في مستوى
        own = []
        for c in comps:
            v = s["components"].get(str(c["id"]))
            if v is not None and float(c["max_score"]):
                own.append((c["name"], v / float(c["max_score"]) * 100))
        avg_own = (sum(p for _, p in own) / len(own)) if own else None
        weak = [n for n, p in own if avg_own is not None and p <= avg_own - WEAK_GAP]
        for n in weak:
            flags.append("ضعف في «%s» دون مستواه المعتاد" % n)
            actions.append("تكليفٌ علاجي مركَّز في «%s» ومتابعةُ إنجازه" % n)

        # الحضور من سجل المدرسة لا من رصد المعلّم
        att = s.get("attendance")
        if att is not None and att < ATT_WARN:
            flags.append("حضور %g٪ — الغياب يُفسّر جزءاً من التحصيل" % att)
            actions.append("تحويلٌ للموجّه الطلابي وخطةُ متابعة حضور مع ولي الأمر")

        beh = s.get("behavior") or 0
        if beh >= BEH_WARN:
            flags.append("%d مخالفات سلوكية في الفترة" % beh)
            actions.append("جلسة إرشادية وعقدٌ سلوكي مع إشعار ولي الأمر")

        if len(ratios) >= 4 and _stdev([r * 100 for r in ratios]) >= SWING_SD:
            flags.append("أداء متذبذب لا مستوى ثابت")
            actions.append("تقييمات قصيرة متقاربة لتثبيت المستوى وكشف سببه")

        trend = None
        if len(ratios) >= 4:
            half = len(ratios) // 2
            first = sum(ratios[:half]) / half * 100
            last = sum(ratios[half:]) / (len(ratios) - half) * 100
            if last - first >= TREND_GAP:
                trend = "تحسّن"
                flags.append("تحسّنٌ واضح في التقييمات الأخيرة")
                actions.append("تعزيزٌ وإشعارُ ولي الأمر بالتحسّن لتثبيته")
            elif first - last >= TREND_GAP:
                trend = "تراجع"
                flags.append("تراجعٌ في التقييمات الأخيرة")
                actions.append("مقابلةُ الطالب لمعرفة سبب التراجع قبل تفاقمه")
            else:
                trend = "ثابت"

        if tier["rank"] >= 3 and pct is not None:
            actions.append("خطة علاجية فردية وحصص تقوية، وإبلاغ ولي الأمر")
        if tier["rank"] == 0 and not flags:
            actions.append("تكليفٌ إثرائي يرفع سقف التحدي")

        graded = len(ratios)
        if total_cells and graded == 0:
            flags.append("لم يُرصد له شيء في هذه الفترة")

        rows.append({
            "id": s["id"], "name": s["name"], "total": pct,
            "tier": tier["name"], "tier_color": tier["color"],
            "tier_bg": tier["bg"], "tier_rank": tier["rank"],
            "attendance": att, "behavior": beh,
            "graded": graded, "cells": total_cells,
            "coverage": (round(graded / total_cells * 100) if total_cells else 0),
            "trend": trend, "weak": weak,
            "flags": flags,
            # المكرّر يُحذف مع حفظ الترتيب: علّتان قد تقترحان الشيء نفسه
            "actions": list(dict.fromkeys(actions)),
        })

    summary = {}
    for r in rows:
        summary[r["tier"]] = summary.get(r["tier"], 0) + 1
    ranked = sorted([r for r in rows if r["total"] is not None],
                    key=lambda r: -r["total"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    graded_rows = [r for r in rows if r["total"] is not None]
    return {"ok": True, "subject": gb["subject"], "period": period,
            "students": rows, "summary": summary,
            "class_avg": (round(sum(r["total"] for r in graded_rows) /
                                len(graded_rows), 1) if graded_rows else None),
            "needs_help": sum(1 for r in rows if r["tier_rank"] >= 3),
            "tiers": [t[1] for t in TIERS]}


def analyze_student(subject_id: int, period: int, student_id: str) -> dict:
    res = analyze_class(subject_id, period)
    if not res.get("ok"):
        return res
    row = next((r for r in res["students"] if r["id"] == str(student_id)), None)
    if not row:
        return {"ok": False, "msg": "الطالب غير موجود في هذا الفصل"}
    return {"ok": True, "student": row, "subject": res["subject"],
            "class_avg": res["class_avg"], "period": period}


def student_across_subjects(student_id: str) -> dict:
    """
    ملخّص الطالب في كل مواده — لصفحة تحليل الطالب ولبوابة ولي الأمر.

    يعبر حدود المعلّم عمداً: ولي الأمر وإدارة المدرسة يريان الطالب كاملاً
    لا مادةً واحدة. ولذلك لا يمرّ هذا بـowns_subject.
    """
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id, class_id, subject, teacher FROM tt_subjects")
    subs = [{"id": r[0], "class_id": r[1], "subject": r[2], "teacher": r[3]}
            for r in cur.fetchall()]
    con.close()

    sid = str(student_id)
    cls = None
    for c in load_students().get("list", []):
        if any(str(s.get("id")) == sid for s in c.get("students", [])):
            cls = c["id"]
            break
    if cls is None:
        return {"ok": False, "msg": "الطالب غير موجود"}

    out = []
    for sub in subs:
        if sub["class_id"] != cls:
            continue
        for period in (1, 2, 3, 4, 5, 6):
            res = analyze_student(sub["id"], period, sid)
            if not res.get("ok"):
                continue
            row = res["student"]
            if row["graded"] == 0:
                continue
            out.append({
                "subject": sub["subject"], "teacher": sub["teacher"],
                "period": period, "total": row["total"], "tier": row["tier"],
                "tier_color": row["tier_color"], "tier_bg": row["tier_bg"],
                "attendance": row["attendance"], "behavior": row["behavior"],
                "coverage": row["coverage"], "trend": row["trend"],
                "flags": row["flags"], "actions": row["actions"],
                "class_avg": res["class_avg"],
            })
    graded = [o["total"] for o in out if o["total"] is not None]
    return {"ok": True, "student_id": sid, "rows": out,
            "average": (round(sum(graded) / len(graded), 1) if graded else None),
            "subjects": len({o["subject"] for o in out})}


def _attendance_pct(class_id: str, students: list) -> dict:
    """
    نسبة حضور كل طالب من سجل DarbStu نفسه — لا رصد جديد.
    تُقرأ عبر query_absences لا بـSQL مباشر، لأن المدرسة قد تكون في الوضع
    السحابي فتأتي السجلات من السيرفر لا من الملف المحلي.
    """
    try:
        recs = query_absences(class_id_filter=class_id)
    except Exception:
        return {}
    days = {r.get("date") for r in recs if r.get("date")}
    total_days = len(days)
    if not total_days:
        return {str(s["id"]): 100.0 for s in students}

    absent = {}
    for r in recs:
        sid = str(r.get("student_id", ""))
        absent[sid] = absent.get(sid, 0) + 1
    return {str(s["id"]): round((total_days - absent.get(str(s["id"]), 0))
                                / float(total_days) * 100, 1)
            for s in students}
