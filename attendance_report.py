# -*- coding: utf-8 -*-
"""
attendance_report.py — تقرير الرصد: غيابٌ وتأخرٌ ودقائقه بين تاريخين.

لماذا وحدة مستقلة: تقارير `report_builder` كلها **غيابٌ وحده**، ووكيل
شؤون الطلاب يرصد الاثنين معاً — من غاب خمساً ومن تأخر عشراً ومن أهدر
ساعتين من الحصة الأولى. وجمعُهما في استعلامٍ واحد يُظهر ما لا يُظهره
التقريران منفصلين: الطالب الذي لا يبلغ عتبة الغياب ولا عتبة التأخر لكنه
يبلغ مجموعهما.

وحدةٌ جديدة لا إضافةٌ إلى `report_builder`: ذاك بلغ ٨٠٠ سطر، والجديد
يحتاج اختباراً مستقلاً — انظر `tools/test_attendance_report.py`.

مصادر البيانات (كلاهما في `absences.db`):
  • `absences`  — فريدٌ بـ(تاريخ، فصل، طالب)  ⇒ العدّ «أيام غياب»
  • `tardiness` — فريدٌ بـ(تاريخ، طالب) و`minutes_late` ⇒ «أيام تأخر»
  • `excuses`   — للاستبعاد الاختياري
  • `exempted_students` — يُستبعَد دائماً (مستثنى من الرصد أصلاً)
"""
import calendar
import datetime
import sqlite3

from constants import DB_PATH

# ── الأسبوع الدراسي السعودي: الأحد → الخميس ──────────────────────────
# ‏Python يبدأ الأسبوع بالاثنين (weekday(): الاثنين=0 … الأحد=6)، فحساب
# «هذا الأسبوع» بالافتراضي يضع الأحد في الأسبوع الماضي — ويوم الأحد
# أثقل أيام الغياب، فتسقط ذروةُ الأسبوع من تقريره.
_SUNDAY = 6

GROUPS = ("student", "class", "day")
SORTS = ("absence", "tardy", "minutes", "total", "name")


def _con():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ══════════════════════════════════════════════════════════════════
#  المدى الزمني
# ══════════════════════════════════════════════════════════════════
def resolve_range(preset="month", start=None, end=None, today=None):
    """
    يحوّل اختصاراً زمنياً إلى (من، إلى) بصيغة YYYY-MM-DD.

    المنطق هنا لا في الواجهة: الواجهة تُحسب بتوقيت جهاز المستعرِض، وقد
    يكون مضبوطاً خطأً أو في منطقة أخرى، فيختلف «اليوم» عن يوم المدرسة.
    """
    t = today or datetime.date.today()
    if isinstance(t, str):
        t = datetime.date.fromisoformat(t)

    if preset == "custom":
        s = start or t.isoformat()
        e = end or t.isoformat()
        if s > e:                       # مقلوبان ⇒ نصحّح بدل أن نُرجع فراغاً
            s, e = e, s
        return s, e
    if preset == "today":
        return t.isoformat(), t.isoformat()
    if preset == "yesterday":
        y = t - datetime.timedelta(days=1)
        return y.isoformat(), y.isoformat()
    if preset == "week":
        back = (t.weekday() - _SUNDAY) % 7
        s = t - datetime.timedelta(days=back)
        return s.isoformat(), t.isoformat()
    if preset == "last_week":
        back = (t.weekday() - _SUNDAY) % 7
        this_sun = t - datetime.timedelta(days=back)
        s = this_sun - datetime.timedelta(days=7)
        return s.isoformat(), (this_sun - datetime.timedelta(days=1)).isoformat()
    if preset == "last_month":
        first = t.replace(day=1)
        prev_end = first - datetime.timedelta(days=1)
        return prev_end.replace(day=1).isoformat(), prev_end.isoformat()
    if preset == "term":
        # الفصل الدراسي تقريباً: من أول أغسطس إن كنا في النصف الثاني من
        # السنة، وإلا من أول يناير. تقريبٌ مقصود — لا تقويم رسمي في
        # النظام، والوكيل يضبط المدى يدوياً إن أراد الدقة.
        s = t.replace(month=8, day=1) if t.month >= 8 else t.replace(month=1, day=1)
        return s.isoformat(), t.isoformat()
    # الافتراضي: هذا الشهر
    return t.replace(day=1).isoformat(), t.isoformat()


def _days_label(start, end):
    s = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    return (e - s).days + 1


# ══════════════════════════════════════════════════════════════════
#  التقرير
# ══════════════════════════════════════════════════════════════════
def build_report(start, end, include_absence=True, include_tardy=True,
                 class_id=None, group_by="student", min_absence=0,
                 min_tardy=0, min_minutes=0, exclude_excused=False,
                 sort="absence", limit=0, roster=None):
    """
    يبني التقرير المجمَّع. يُرجع قاموساً جاهزاً للعرض أو الطباعة.

    `min_*` عتباتٌ **تُطبَّق بعد الجمع**: «أرني من غاب ٥ أيام فأكثر» هو
    سؤال الوكيل الأول، وتصفيتُه في الواجهة تعني نقل آلاف الصفوف ليُرمى
    أكثرها.
    """
    if group_by not in GROUPS:
        group_by = "student"
    if sort not in SORTS:
        sort = "absence"
    if not include_absence and not include_tardy:
        include_absence = include_tardy = True      # لا تقرير بلا مصدر

    con = _con()
    try:
        cur = con.cursor()

        # المستثنون: خارج الرصد أصلاً، فلا يُحسبون ولا يُعرضون
        exempt = {str(r[0]) for r in
                  cur.execute("SELECT student_id FROM exempted_students")}

        where_cls = " AND class_id=?" if class_id else ""
        p_cls = [class_id] if class_id else []

        # ── الغياب ────────────────────────────────────────────
        absences = []
        if include_absence:
            q = ("SELECT date, student_id, student_name, class_id, class_name "
                 "FROM absences WHERE date BETWEEN ? AND ?" + where_cls)
            absences = [dict(r) for r in
                        cur.execute(q, [start, end] + p_cls)]

        # ── الأعذار (للاستبعاد) ───────────────────────────────
        excused = set()
        if exclude_excused:
            q = "SELECT date, student_id FROM excuses WHERE date BETWEEN ? AND ?"
            excused = {(r["date"], str(r["student_id"]))
                       for r in cur.execute(q, [start, end])}

        # ── التأخر ────────────────────────────────────────────
        tardies = []
        if include_tardy:
            q = ("SELECT date, student_id, student_name, class_id, class_name,"
                 " COALESCE(minutes_late,0) AS mins "
                 "FROM tardiness WHERE date BETWEEN ? AND ?" + where_cls)
            tardies = [dict(r) for r in
                       cur.execute(q, [start, end] + p_cls)]

        # أيام الدراسة الفعلية: التواريخ التي سُجّل فيها شيء. أدقّ من
        # عدّ أيام التقويم — العطل والإجازات لا سجلّ فيها.
        school_days = len({a["date"] for a in absences} |
                          {t["date"] for t in tardies})
    finally:
        con.close()

    # ── التجميع ───────────────────────────────────────────────
    agg = {}

    def _slot(key, name, cls):
        if key not in agg:
            agg[key] = {"key": key, "name": name, "class_name": cls,
                        "absence": 0, "tardy": 0, "minutes": 0,
                        "excused": 0, "dates_abs": [], "dates_tardy": []}
        return agg[key]

    def _keyof(row):
        if group_by == "class":
            return (row.get("class_id") or "—",
                    row.get("class_name") or "—", "")
        if group_by == "day":
            return (row["date"], row["date"], "")
        sid = str(row.get("student_id") or "")
        return (sid, row.get("student_name") or sid,
                row.get("class_name") or "")

    for a in absences:
        sid = str(a.get("student_id") or "")
        if sid in exempt:
            continue
        k, nm, cls = _keyof(a)
        s = _slot(k, nm, cls)
        if exclude_excused and (a["date"], sid) in excused:
            s["excused"] += 1
            continue
        s["absence"] += 1
        s["dates_abs"].append(a["date"])

    for t in tardies:
        sid = str(t.get("student_id") or "")
        if sid in exempt:
            continue
        k, nm, cls = _keyof(t)
        s = _slot(k, nm, cls)
        s["tardy"] += 1
        s["minutes"] += int(t.get("mins") or 0)
        s["dates_tardy"].append(t["date"])

    rows = list(agg.values())

    # ── العتبات ───────────────────────────────────────────────
    # تُطبَّق معاً لا بالتناوب: من طلب «غياب ≥٥ وتأخر ≥٣» يريد من جمعهما
    if min_absence:
        rows = [r for r in rows if r["absence"] >= min_absence]
    if min_tardy:
        rows = [r for r in rows if r["tardy"] >= min_tardy]
    if min_minutes:
        rows = [r for r in rows if r["minutes"] >= min_minutes]

    # ── النسبة: المقام يختلف باختلاف التجميع ──────────────────
    # القسمة على أيام الدراسة وحدها صحيحةٌ للطالب فقط. وتطبيقها على
    # الفصل أعطى **٢٥٣٪** في تجربة الديمو — ورقمٌ كهذا يُفقد الثقة
    # بالتقرير كله لا بعموده وحده.
    #   طالب → أيام الدراسة          (كم يوماً من أيامه غابه)
    #   فصل  → أيام الدراسة × عدده   (كم حصةَ حضورٍ ضاعت من الفصل)
    #   يوم  → عدد طلاب المدرسة      (كم نسبة الغائبين ذلك اليوم)
    # وبلا كشفٍ للطلاب لا مقام للفصل واليوم، فتُحذف النسبة ولا تُلفَّق.
    roster = roster or {}
    r_total = int(roster.get("total") or 0)
    r_by_class = roster.get("by_class") or {}

    for r in rows:
        r["total"] = r["absence"] + r["tardy"]
        if group_by == "student":
            denom = school_days
        elif group_by == "class":
            denom = school_days * int(r_by_class.get(r["key"], 0) or 0)
        else:
            denom = r_total
        r["pct"] = round(r["absence"] * 100.0 / denom, 1) if denom > 0 else None
        r["last_absence"] = max(r["dates_abs"]) if r["dates_abs"] else ""
        r["last_tardy"] = max(r["dates_tardy"]) if r["dates_tardy"] else ""
        r["avg_minutes"] = round(r["minutes"] / r["tardy"], 1) if r["tardy"] else 0.0
        r.pop("dates_abs", None)
        r.pop("dates_tardy", None)

    if sort == "name":
        rows.sort(key=lambda r: r["name"])
    elif group_by == "day":
        rows.sort(key=lambda r: r["key"])        # الأيام بترتيبها دائماً
    else:
        rows.sort(key=lambda r: (-r.get(sort, 0), r["name"]))

    if limit and limit > 0:
        rows = rows[:limit]

    return {
        "ok": True,
        "from": start, "to": end,
        "span_days": _days_label(start, end),
        "school_days": school_days,
        "group_by": group_by, "sort": sort,
        "include_absence": include_absence, "include_tardy": include_tardy,
        "exclude_excused": exclude_excused,
        # نسبةٌ بلا مقام لا تُعرض: عمودٌ من الشُّرَط أسوأ من غيابه
        "has_pct": any(r.get("pct") is not None for r in rows),
        "filters": {"class_id": class_id or "", "min_absence": min_absence,
                    "min_tardy": min_tardy, "min_minutes": min_minutes},
        "totals": {
            "rows": len(rows),
            "absence": sum(r["absence"] for r in rows),
            "tardy": sum(r["tardy"] for r in rows),
            "minutes": sum(r["minutes"] for r in rows),
            "excused": sum(r["excused"] for r in rows),
        },
        "rows": rows,
    }


# ══════════════════════════════════════════════════════════════════
#  المنضبطون
# ══════════════════════════════════════════════════════════════════
def build_good_standing(start, end, students, check_absence=True,
                        check_tardy=True, max_absence=0, max_tardy=0,
                        excused_ok=True, class_id=None, sort="name",
                        limit=0):
    """
    الطلاب الذين لم يغيبوا ولم يتأخروا في المدى (أو ضمن هامشٍ مسموح).

    ⚠️ **لا يُستخرج هذا بقلب تقرير الرصد.** الرصد يقرأ جدولَي الغياب
    والتأخر، ومن لم يغب قط **لا سجلّ له فيهما إطلاقاً** — فقلبُ قائمته
    يُسقط أنضباط الطلاب جميعاً. المصدر هنا هو **الكشف**، والجدولان
    يُستعملان للاستبعاد لا للإدراج.

    `excused_ok`: الغياب بعذرٍ لا يكسر الانضباط. مفعَّلٌ افتراضياً —
    من مرض بإذن المدرسة لا يُعاقَب بحرمانه من قائمة التكريم.

    `max_*`: هامشٌ يختاره الوكيل. صفرٌ = الانضباط التام، وهو الافتراض؛
    لكن «لا غياب إطلاقاً» قد يُفرّغ القائمة في مدرسة كبيرة فيُسمح برفعه.
    """
    if not check_absence and not check_tardy:
        check_absence = check_tardy = True

    con = _con()
    try:
        cur = con.cursor()
        exempt = {str(r[0]) for r in
                  cur.execute("SELECT student_id FROM exempted_students")}

        excused = set()
        if excused_ok:
            excused = {(r["date"], str(r["student_id"])) for r in cur.execute(
                "SELECT date, student_id FROM excuses WHERE date BETWEEN ? AND ?",
                [start, end])}

        abs_rows = [dict(r) for r in cur.execute(
            "SELECT date, student_id FROM absences WHERE date BETWEEN ? AND ?",
            [start, end])]
        tdy_rows = [dict(r) for r in cur.execute(
            "SELECT student_id, COALESCE(minutes_late,0) AS mins "
            "FROM tardiness WHERE date BETWEEN ? AND ?", [start, end])]

        school_days = len({a["date"] for a in abs_rows}) or len(
            {r["date"] for r in cur.execute(
                "SELECT DISTINCT date FROM tardiness WHERE date BETWEEN ? AND ?",
                [start, end])})
    finally:
        con.close()

    n_abs, n_exc, n_tdy, n_min = {}, {}, {}, {}
    for a in abs_rows:
        sid = str(a["student_id"])
        if excused_ok and (a["date"], sid) in excused:
            n_exc[sid] = n_exc.get(sid, 0) + 1
        else:
            n_abs[sid] = n_abs.get(sid, 0) + 1
    for t in tdy_rows:
        sid = str(t["student_id"])
        n_tdy[sid] = n_tdy.get(sid, 0) + 1
        n_min[sid] = n_min.get(sid, 0) + int(t.get("mins") or 0)

    rows, scanned = [], 0
    for s in students or []:
        sid = str(s.get("id") or "")
        if not sid or sid in exempt:
            continue
        if class_id and s.get("class_id") != class_id:
            continue
        scanned += 1
        a, t = n_abs.get(sid, 0), n_tdy.get(sid, 0)
        if check_absence and a > max_absence:
            continue
        if check_tardy and t > max_tardy:
            continue
        rows.append({
            "key": sid, "name": s.get("name") or sid,
            "class_name": s.get("class_name") or "",
            "absence": a, "tardy": t,
            "minutes": n_min.get(sid, 0), "excused": n_exc.get(sid, 0),
            "total": a + t, "pct": None,
            "perfect": (a == 0 and t == 0),
        })

    if sort == "class":
        rows.sort(key=lambda r: (r["class_name"], r["name"]))
    elif sort == "clean":
        rows.sort(key=lambda r: (r["total"], r["minutes"], r["name"]))
    else:
        rows.sort(key=lambda r: r["name"])
    if limit and limit > 0:
        rows = rows[:limit]

    return {
        "ok": True, "kind": "good",
        "from": start, "to": end,
        "span_days": _days_label(start, end),
        "school_days": school_days,
        "group_by": "student", "sort": sort,
        "include_absence": check_absence, "include_tardy": check_tardy,
        "exclude_excused": False, "has_pct": False,
        "excused_ok": excused_ok,
        "filters": {"class_id": class_id or "", "max_absence": max_absence,
                    "max_tardy": max_tardy},
        "totals": {
            "rows": len(rows), "scanned": scanned,
            "perfect": sum(1 for r in rows if r["perfect"]),
            "absence": sum(r["absence"] for r in rows),
            "tardy": sum(r["tardy"] for r in rows),
            "minutes": sum(r["minutes"] for r in rows),
            "excused": sum(r["excused"] for r in rows),
        },
        "rows": rows,
    }


# ══════════════════════════════════════════════════════════════════
#  العرض: الطباعة والتصدير
# ══════════════════════════════════════════════════════════════════
_GROUP_AR = {"student": "الطالب", "class": "الفصل", "day": "اليوم"}


def _esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _fmt_minutes(m):
    """٩٥ دقيقة ⇒ «١ س ٣٥ د» — الوكيل يقرأ الساعات لا الدقائق الخام."""
    m = int(m or 0)
    if m < 60:
        return "%d د" % m
    return "%d س %d د" % (m // 60, m % 60)


def columns(rep):
    """أعمدة التقرير حسب ما اختير — ومصدرٌ واحد للطباعة والتصدير معاً."""
    if rep.get("kind") == "good":
        # قائمة تكريم: تُقرأ بأسماء الطلاب لا بأرقام غيابهم، فالأعمدة
        # الرقمية تظهر **فقط** حين يُسمح بهامش — وإلا كانت أصفاراً تملأ
        # الورقة بلا معنى
        cols = [("#", "idx"), ("الطالب", "name"), ("الفصل", "class_name")]
        f = rep.get("filters", {})
        if rep["include_absence"] and f.get("max_absence"):
            cols.append(("أيام الغياب", "absence"))
        if rep["include_tardy"] and f.get("max_tardy"):
            cols += [("أيام التأخر", "tardy"), ("مجموع الدقائق", "minutes")]
        if rep.get("excused_ok"):
            cols.append(("غياب بعذر", "excused"))
        return cols

    cols = [("#", "idx"), (_GROUP_AR.get(rep["group_by"], "البند"), "name")]
    if rep["group_by"] == "student":
        cols.append(("الفصل", "class_name"))
    if rep["include_absence"]:
        cols.append(("أيام الغياب", "absence"))
        if rep.get("has_pct", True):
            cols.append(("النسبة %", "pct"))
        if rep["exclude_excused"]:
            cols.append(("بعذر", "excused"))
        if rep["group_by"] != "day":
            cols.append(("آخر غياب", "last_absence"))
    if rep["include_tardy"]:
        cols += [("أيام التأخر", "tardy"), ("مجموع الدقائق", "minutes"),
                 ("متوسط الدقائق", "avg_minutes")]
        if rep["group_by"] != "day":
            cols.append(("آخر تأخر", "last_tardy"))
    if rep["include_absence"] and rep["include_tardy"]:
        cols.append(("المجموع", "total"))
    return cols


def _cell(row, key, idx):
    if key == "idx":
        return str(idx)
    v = row.get(key, "")
    if key == "minutes":
        return _fmt_minutes(v)
    if key == "pct":
        # صفٌّ بلا مقام وسط صفوفٍ لها مقام (فصلٌ ليس في الكشف مثلاً):
        # «0.0%» كذبٌ صريح، والشَّرطة تقول «لا أعرف»
        return "—" if v is None else "%.1f%%" % v
    return _esc(v)


def build_print_html(rep, school_name="", title=""):
    """صفحة A4 جاهزة للطباعة. لا خطوط من الإنترنت: مدارس كثيرة بلا
    اتصالٍ سريع، واستيراد خطٍّ بعيد يؤخّر الطباعة بلا فائدة."""
    cols = columns(rep)
    head = "".join("<th>%s</th>" % _esc(h) for h, _ in cols)

    body = []
    for i, r in enumerate(rep["rows"], 1):
        tds = "".join("<td>%s</td>" % _cell(r, k, i) for _, k in cols)
        body.append("<tr>%s</tr>" % tds)
    if not body:
        body.append('<tr><td colspan="%d" class="empty">لا توجد سجلات '
                    'مطابقة لهذه الخيارات</td></tr>' % len(cols))

    f = rep["filters"]
    conds = []
    if f.get("min_absence"):
        conds.append("غياب ≥ %d" % f["min_absence"])
    if f.get("min_tardy"):
        conds.append("تأخر ≥ %d" % f["min_tardy"])
    if f.get("min_minutes"):
        conds.append("دقائق ≥ %d" % f["min_minutes"])
    if rep["exclude_excused"]:
        conds.append("بلا الغياب بعذر")
    if rep.get("kind") == "good":
        conds = []
        if rep["include_absence"]:
            conds.append("غياب لا يتجاوز %d" % f.get("max_absence", 0))
        if rep["include_tardy"]:
            conds.append("تأخر لا يتجاوز %d" % f.get("max_tardy", 0))
        if rep.get("excused_ok"):
            conds.append("الغياب بعذر لا يكسر الانضباط")
    cond_html = ("<div class='cond'>عوامل التصفية: %s</div>"
                 % _esc(" · ".join(conds))) if conds else ""

    cards = []
    if rep.get("kind") == "good":
        t = rep["totals"]
        cards.append(("عدد المنضبطين", t["rows"]))
        cards.append(("منهم بلا غياب ولا تأخر", t.get("perfect", 0)))
        if t.get("scanned"):
            cards.append(("من أصل", t["scanned"]))
            cards.append(("النسبة",
                          "%.0f%%" % (t["rows"] * 100.0 / t["scanned"])))
        cards.append(("أيام الدراسة في المدى", rep["school_days"]))
    else:
        if rep["include_absence"]:
            cards.append(("إجمالي أيام الغياب", rep["totals"]["absence"]))
        if rep["include_tardy"]:
            cards.append(("إجمالي أيام التأخر", rep["totals"]["tardy"]))
            cards.append(("مجموع دقائق التأخر",
                          _fmt_minutes(rep["totals"]["minutes"])))
        cards.append(("أيام الدراسة في المدى", rep["school_days"]))
        cards.append((_GROUP_AR.get(rep["group_by"], "بنود"),
                      rep["totals"]["rows"]))
    cards_html = "".join(
        "<div class='card'><div class='cv'>%s</div><div class='cl'>%s</div></div>"
        % (_esc(v), _esc(l)) for l, v in cards)

    printed = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>%(title)s</title><style>
  @page { size: A4 landscape; margin: 10mm; }
  *{box-sizing:border-box}
  body{font-family:"Segoe UI","Tahoma",Arial,sans-serif;margin:0;color:#111;
       background:#f5f6f7;font-size:12px}
  .page{background:#fff;padding:14mm;margin:8mm auto;max-width:277mm;
        box-shadow:0 0 6px rgba(0,0,0,.12)}
  .hd{display:flex;justify-content:space-between;align-items:flex-end;
      border-bottom:2px solid #15616d;padding-bottom:8px}
  .hd h1{margin:0;font-size:19px}
  .hd .sch{font-size:13px;color:#444;font-weight:600}
  .meta{margin:10px 0 4px;font-size:12px;color:#444}
  .cond{margin:4px 0 10px;font-size:12px;color:#8a4b12}
  .cards{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
  .card{flex:1;min-width:110px;border:1px solid #d9e2db;border-radius:7px;
        padding:8px 10px;text-align:center;background:#fafbfa}
  .cv{font-size:18px;font-weight:700;color:#15616d}
  .cl{font-size:11px;color:#5d6b63;margin-top:2px}
  table{width:100%%;border-collapse:collapse;margin-top:6px}
  th,td{border:1px solid #cfd8d3;padding:5px 6px;text-align:center}
  th{background:#15616d;color:#fff;font-size:11px;font-weight:600}
  tbody tr:nth-child(even){background:#f7f9f8}
  td:nth-child(2){text-align:right}
  .empty{padding:22px;color:#777}
  .ft{margin-top:14px;padding-top:8px;border-top:1px solid #d9e2db;
      display:flex;justify-content:space-between;font-size:11px;color:#5d6b63}
  @media print{ body{background:#fff} .page{box-shadow:none;margin:0;
       padding:0;max-width:none} thead{display:table-header-group} }
</style></head><body><div class="page">
  <div class="hd"><h1>%(title)s</h1><div class="sch">%(school)s</div></div>
  <div class="meta">المدة: من <b>%(frm)s</b> إلى <b>%(to)s</b> ·
       التجميع حسب <b>%(grp)s</b></div>
  %(cond)s
  <div class="cards">%(cards)s</div>
  <table><thead><tr>%(head)s</tr></thead><tbody>%(body)s</tbody></table>
  <div class="ft"><span>طُبع في %(printed)s</span>
       <span>درب الطالب — darbstu.com</span></div>
</div></body></html>""" % {
        "title": _esc(title or "تقرير الغياب والتأخر"),
        "school": _esc(school_name or "المدرسة"),
        "frm": _esc(rep["from"]), "to": _esc(rep["to"]),
        "grp": _esc(_GROUP_AR.get(rep["group_by"], "")),
        "cond": cond_html, "cards": cards_html,
        "head": head, "body": "".join(body), "printed": printed,
    }


def build_rows_for_export(rep):
    """صفوفٌ مسطّحة للتصدير — نفس أعمدة الطباعة حرفاً، فلا يختلف الملف
    عن الورقة ويشكّ الوكيل في أيّهما الصحيح."""
    cols = columns(rep)
    out = [[h for h, _ in cols]]
    for i, r in enumerate(rep["rows"], 1):
        row = []
        for _, k in cols:
            if k == "idx":
                row.append(i)
            elif k in ("absence", "tardy", "minutes", "total", "excused"):
                row.append(int(r.get(k) or 0))      # أرقاماً لا نصّاً
            elif k in ("pct", "avg_minutes"):
                row.append(float(r.get(k) or 0))
            else:
                row.append(r.get(k, ""))
        out.append(row)
    return out
