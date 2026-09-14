# -*- coding: utf-8 -*-
"""
attendance_blend.py — الخلطة الذكية: حالة حضور موحّدة لكل طالب كل يوم،
من ثلاثة مصادر: جهاز البصمة، روابط المعلمين، الإدخال اليدوي.

المشكلة التي يحلّها: المصادر لا تتصالح. «الحاضر» كان = الإجمالي − الغائب،
فمن لم يُسجَّل يظهر حاضراً ولو لم يحضر. والبصمة تُغذّي التأخر ولا تمسّ
الغياب. فطالبٌ بصم عند البوابة ثم سجّله معلم غائباً يظهر «غائب» رغم أنه
في المبنى (هروب لا غياب).

هذا المحرّك يقرأ كل المصادر وينتج حالةً واحدة لكل طالب، مع وسم مصدرها.
لا يكتب شيئاً — قراءة وتصالح فقط، فلا يُفسد التسجيل القائم.

دور البصمة:
  • "supplement" (مساعد): من لم يبصم لا يُحسب غائباً — الغياب يحتاج معلماً
    أو إدخالاً. البصمة تؤكّد الحضور ووقت الوصول فقط. **وهذا وضع النظام
    دائماً**: هو ما تراه لوحة المراقبة والتقارير والإشعارات بلا استثناء.
  • "primary" (أساسي): البصمة إلزامية — من لم يبصم ولم يُعذَر = غائب.
    **عرضٌ مؤقّت** لا يُطلب إلا صراحةً بمعامل `role` من صفحة الحضور
    الموحّد، ولا يُحفَظ في الإعدادات ولا يُغيّر أرقام بقية النظام.

قاعدة التعارض (بصم + معلم غائب): «هروب/جزئي» + تنبيه.
"""
import datetime

# قيم الحالة الموحّدة
PRESENT = "حاضر"
LATE = "متأخر"
ABSENT = "غائب"
ESCAPE = "هروب"       # حضر ثم غاب عن حصة (تعارض البصمة والمعلم)

# مصادر
SRC_DEVICE = "بصمة"
SRC_TEACHER = "معلم"
SRC_MANUAL = "يدوي"
SRC_DEFAULT = "افتراضي"
SRC_NOPUNCH = "لم يبصم"
SRC_COMMITTED = "بصمة (معتمَد)"

# وسمٌ في `absences.teacher_id` لسجلّات كتبها «اعتماد غياب من لم يبصم».
# وجوده يتيح شيئين: تمييزها في العرض عن غياب سجّله معلم، وسحبها وحدها
# عند التراجع بلا أن تُمسّ سجلّات المعلمين إطلاقاً.
# مصدره `constants` — تقرؤه وحداتٌ أخرى، وتعريفه هنا كان يُنشئ دورة.
from constants import BIOMETRIC_TEACHER_ID as BIO_TEACHER_ID
BIO_TEACHER_NAME = "اعتماد الإدارة من البصمة"


def _riyadh_today():
    tz = datetime.timezone(datetime.timedelta(hours=3))
    return datetime.datetime.now(datetime.timezone.utc).astimezone(tz)\
        .date().isoformat()


def _minutes_late(arrival_local, start_str, grace):
    """دقائق التأخر من وقت الوصول مقابل بداية الدوام + السماح."""
    try:
        t_arr = datetime.datetime.fromisoformat(
            arrival_local.replace("Z", "")).strftime("%H:%M")
        a = datetime.datetime.strptime(t_arr, "%H:%M")
        s = datetime.datetime.strptime(start_str[:5], "%H:%M")
        return max(int((a - s).total_seconds() / 60) - int(grace or 0), 0)
    except Exception:
        return 0


def _punch_arrivals(date_str):
    """{student_id: أبكر وقت بصمة} — للطلاب المطابَقين اليوم."""
    from database import query_biometric_punches
    out = {}
    for r in query_biometric_punches(date_filter=date_str, limit=5000):
        sid = str(r.get("student_id") or "").strip()
        if not sid or not r.get("matched"):
            continue
        local = r.get("punch_local") or ""
        if sid not in out or (local and local < out[sid]):
            out[sid] = local
    return out


def biometric_in_use(days=14):
    """
    هل للمدرسة جهاز بصمة يعمل فعلاً؟

    لا يكفي `biometric_enabled` — ذلك **مفتاح السحب التلقائي**، ومدرسةٌ
    تسحب بصماتها يدوياً تتركه مطفأً وبصماتها تصل. فنقبل الدليل الأقوى:
    بصماتٌ مطابَقة فعلاً خلال المدة الأخيرة.
    """
    from config_manager import load_config
    if load_config().get("biometric_enabled"):
        return True
    try:
        import datetime as _dt
        from database import query_biometric_punches
        cut = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
        for r in query_biometric_punches(limit=500) or []:
            if not r.get("matched"):
                continue
            d = str(r.get("punch_local") or r.get("date") or "")[:10]
            if d and d >= cut:
                return True
    except Exception:
        pass
    return False


def reconcile_daily_attendance(date_str=None, role=None):
    """
    يُرجع حالة موحّدة لكل طالب غير مستثنى.

    role: يتجاوز الإعداد إن مُرّر ("supplement"|"primary").
    يُرجع dict:
      date, role, totals{present,late,absent,escape,total},
      students[{id,name,class_id,class_name,status,source,minutes,alert}],
      alerts[...]   ← حالات تحتاج انتباه (تعارض، لم يبصم في الوضع الأساسي)
    """
    from database import (load_students, get_exempted_students,
                          query_absences, query_tardiness)
    from config_manager import load_config

    date_str = date_str or _riyadh_today()
    cfg = load_config()
    # ‏«المساعد» هو وضع النظام دائماً، ولا يُقرأ من الإعدادات إطلاقاً.
    # «الأساسي» عرضٌ مؤقّت لا يُطلب إلا صراحةً بـrole من صفحة الحضور
    # الموحّد. سبب ذلك أن هذه الدالة تغذّي `blend_metrics` ومن ورائه
    # لوحة المراقبة والتقارير والإشعارات: فدورٌ محفوظ بـ«أساسي» يقلب
    # أرقام النظام كلّه، ويُعلّم كل من لم يبصم غائباً في كل مكان — ولو
    # نُسي مرّةً بقي. الافتراض الآمن يبقى افتراضاً ولا يُحفَظ ضدّه شيء.
    role = role if role in ("supplement", "primary") else "supplement"
    start = cfg.get("school_start_time", "07:00")
    grace = int(cfg.get("biometric_grace_min", 0) or 0)

    exempt = {str(e["student_id"]) for e in get_exempted_students()}
    _abs_rows = query_absences(date_filter=date_str)
    absent_ids = {str(r["student_id"]) for r in _abs_rows}
    # غيابٌ اعتمدته الإدارة من البصمة — يبقى موسوماً بمصدره بعد الحفظ،
    # وإلا ظهر «معلم» فأوهم أن معلماً سجّله.
    committed_ids = {str(r["student_id"]) for r in _abs_rows
                     if str(r.get("teacher_id") or "") == BIO_TEACHER_ID}
    tardy_ids = {str(r["student_id"])
                 for r in query_tardiness(date_filter=date_str)}
    arrivals = _punch_arrivals(date_str)

    # حارس حاسم: الوضع «الأساسي» (لم يبصم = غائب) بلا أي بصمة سيُعلّم كل
    # طلاب المدرسة غائبين. فبلا دليل على الجهاز نفرض «المساعد» دائماً —
    # لا غياب يُفترَض من عدم بصمٍ لا وجود له.
    #
    # كان الشرط `biometric_enabled` وحده، وهو **مفتاح السحب التلقائي كل
    # ١٠ ثوانٍ** لا إقرارٌ بوجود جهاز: مدرسةٌ وصلت جهازها وسحبت بصماتها
    # يدوياً (`run_once` لا يفحص المفتاح) كانت ترى متأخريها من البصمة
    # ويُرفض عليها الوضع الأساسي — والزرّ يرتدّ بلا سبب ظاهر.
    # الدليل الصحيح هو البصمات نفسها في ذلك اليوم.
    if not cfg.get("biometric_enabled") and not arrivals:
        role = "supplement"

    students, alerts = [], []
    tot = {"present": 0, "late": 0, "absent": 0, "escape": 0, "total": 0,
           "nopunch": 0,      # nopunch: غائبون سببهم عدم البصم (الأساسي)
           "committed": 0}    # committed: غيابٌ من البصمة اعتمدته الإدارة

    for c in load_students().get("list", []):
        cid, cname = c.get("id"), c.get("name", "")
        for s in c.get("students", []):
            sid = str(s.get("id"))
            if sid in exempt:
                continue
            tot["total"] += 1
            punched = sid in arrivals
            teacher_absent = sid in absent_ids
            minutes = 0

            if punched and teacher_absent:
                status, source = ESCAPE, "%s + %s" % (SRC_DEVICE, SRC_TEACHER)
                alerts.append({"student_id": sid, "name": s.get("name", ""),
                               "class_name": cname, "kind": "escape",
                               "text": "بصم عند البوابة لكن سُجّل غائباً في حصة — هروب؟"})
            elif punched:
                minutes = _minutes_late(arrivals[sid], start, grace)
                status = LATE if minutes > 0 else PRESENT
                source = SRC_DEVICE
            elif teacher_absent:
                status = ABSENT
                source = (SRC_COMMITTED if sid in committed_ids
                          else SRC_TEACHER)
            elif sid in tardy_ids:
                status, source = LATE, SRC_TEACHER
            else:
                # لم يبصم، ولا سجل غياب/تأخر
                if role == "primary":
                    # الوضع الأساسي: لم يبصم = غائب. هذا هو الغائبون أنفسهم،
                    # ويظهرون في الجدول — فلا نُغرق لوحة التنبيهات بمئاتهم.
                    # التنبيه محجوز للتعارض الحقيقي (الهروب). لكن نبقي وسم
                    # المصدر «لم يبصم» ليُميَّز في الواجهة عن غياب سجّله معلم.
                    status, source = ABSENT, SRC_NOPUNCH
                else:
                    status, source = PRESENT, SRC_DEFAULT

            if status == PRESENT:
                tot["present"] += 1
            elif status == LATE:
                tot["late"] += 1
            elif status == ABSENT:
                tot["absent"] += 1
                if source == SRC_NOPUNCH:
                    tot["nopunch"] += 1
                elif source == SRC_COMMITTED:
                    tot["committed"] += 1
            elif status == ESCAPE:
                tot["escape"] += 1

            students.append({
                "id": sid, "name": s.get("name", ""),
                "class_id": cid, "class_name": cname,
                "status": status, "source": source,
                "minutes": minutes,
                "alert": status == ESCAPE})
    return {"date": date_str, "role": role, "totals": tot,
            "students": students, "alerts": alerts}


def blend_metrics(date_str=None, role=None):
    """
    يُنتج شكل compute_today_metrics نفسه (totals + by_class) من الخلطة،
    ليصير مصدرَ لوحة المراقبة والتقارير — مع **حفظ عقد** present/absent
    القائم (present = الإجمالي − الغائب، فيشمل المتأخر والهارب لأنهما
    حضرا) وإضافة late/escape/nopunch للعرض الأغنى.

    بلا جهاز بصمة مُفعّل، الأرقام مطابقةٌ للحساب القديم تماماً: الغائب =
    من له سجل غياب، والحاضر = الباقي (الحارس في reconcile يفرض المساعد).
    """
    r = reconcile_daily_attendance(date_str, role=role)
    tot = r["totals"]
    total = tot["total"]
    absent = tot["absent"]

    by_class = {}
    for s in r["students"]:
        cid = s["class_id"]
        b = by_class.setdefault(cid, {"class_id": cid,
                                      "class_name": s["class_name"],
                                      "total": 0, "absent": 0,
                                      "late": 0, "escape": 0})
        b["total"] += 1
        if s["status"] == ABSENT:
            b["absent"] += 1
        elif s["status"] == LATE:
            b["late"] += 1
        elif s["status"] == ESCAPE:
            b["escape"] += 1

    by_list = sorted(by_class.values(), key=lambda x: x["class_id"])
    for b in by_list:
        b["present"] = max(b["total"] - b["absent"], 0)

    return {
        "date": r["date"], "role": r["role"],
        "totals": {
            "students": total,
            "absent": absent,
            "present": max(total - absent, 0),
            "late": tot["late"],
            "escape": tot["escape"],
            "nopunch": tot["nopunch"],
        },
        "by_class": by_list,
        "alerts": r["alerts"],
    }
