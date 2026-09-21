# -*- coding: utf-8 -*-
"""
staff_accounts.py — توليد حسابات الطاقم من ملف نور.

كان المنطق داخل `gui/tabs/users_tab.py` وحده، فلا تبلغه واجهة الويب —
ومن يدير النظام عن بُعد لا يفتح البرنامج المكتبي أصلاً. نُقل هنا ليستعمله
الاثنان من مصدرٍ واحد: نسختان متطابقتان اليوم تفترقان غداً عند أول تعديل.

القواعد التي لا تتغيّر:
  • **اسم المستخدم = رقم الهوية**، وإلا الجوال. لا يُولَّد اسمٌ اصطناعي:
    المعلم يعرف هويته ويتذكّرها، والاسم المخترَع يُنسى.
  • **لا يُمَسّ حسابٌ قائم أبداً.** التوليد يُضيف الناقص فقط — فتشغيله
    مرّتين لا يُبدّل كلمة مرور أحد ولا يُلغي صلاحياته.
  • **لا إرسال هنا.** التوليد شيء وإبلاغ المعلمين شيء آخر؛ دمجُهما يعني
    أن كل تجربة تُرسل رسائل واتساب لا رجعة فيها.
"""
import random

# الوظيفة في ملف نور ← الدور في النظام. الترتيب مقصود: «موجه صحي» قبل
# «موجه» وإلا ابتلعت الثانيةُ الأولى.
JOB_ROLE = (
    ("موجه صحي", "health"),
    ("موجه",     "counselor"),
    ("اداري",    "staff"),
    ("إداري",    "staff"),
)

# تبويبات المعلم مقصورة عمداً وأضيق من ROLE_TABS['teacher'] — تُترك كما
# هي حتى لا يتغيّر ما يراه المعلمون في المدارس القائمة.
TEACHER_TABS = ["لوحة المراقبة", "تحليل النتائج", "تحويل طالب",
                "نماذج المعلم", "خطابات الاستفسار", "التعاميم والنشرات"]


def role_for_job(job: str) -> str:
    """يستنتج الدور من نصّ الوظيفة كما ورد في نور."""
    j = " ".join(str(job or "").split())
    for key, role in JOB_ROLE:
        if key in j:
            return role
    return "teacher"


def generate_staff_accounts() -> dict:
    """
    يُنشئ حساباً لكل عضو طاقم بلا حساب. يُرجع تقريراً بما جرى.

    {ok, created, skipped, per_role, no_staff}
    """
    from constants import ROLE_TABS
    from database import (load_teachers, create_user, get_all_users,
                          save_user_allowed_tabs)

    try:
        staff = (load_teachers() or {}).get("teachers", []) or []
    except Exception as e:
        return {"ok": False, "msg": "تعذّرت قراءة ملف الطاقم: %s" % e}

    if not staff:
        return {"ok": False, "no_staff": True,
                "msg": "لا يوجد طاقم — استورد ملف نور أولاً."}

    existing = {u["username"] for u in (get_all_users() or [])}
    created = skipped = 0
    per_role = {}

    for t in staff:
        name = (t.get("اسم المعلم") or t.get("full_name") or "").strip()
        phone = (t.get("رقم الجوال") or "").strip()
        civ = (t.get("رقم الهوية") or "").strip()
        username = civ or phone
        if not username or not name:
            skipped += 1
            continue
        if username in existing:      # حسابٌ قائم لا يُمَسّ
            skipped += 1
            continue

        role = role_for_job(t.get("الوظيفة", ""))
        password = str(random.randint(100000, 999999))
        try:
            ok, _msg = create_user(username, password, role, name)
        except Exception:
            ok = False
        if not ok:
            skipped += 1
            continue

        tabs = (TEACHER_TABS if role == "teacher"
                else list(ROLE_TABS.get(role) or TEACHER_TABS))
        try:
            save_user_allowed_tabs(username, tabs)
        except Exception:
            pass
        existing.add(username)
        per_role[role] = per_role.get(role, 0) + 1
        created += 1

    return {"ok": True, "created": created, "skipped": skipped,
            "per_role": per_role}
