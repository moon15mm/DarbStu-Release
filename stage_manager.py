# -*- coding: utf-8 -*-
"""
stage_manager.py — مدرسة بمرحلتين على جهاز واحد (متوسط + ثانوي)

الفكرة: كيان تعليمي واحد يضم مدرستين. برنامج واحد، تحديث واحد، جلسة
واتساب واحدة — وبيانات معزولة تماماً لكل مرحلة:

    BASE_DIR/
      stages.json                     ← تعريف المراحل (خارج العزل)
      my-whatsapp-server/             ← مشترك: جلسة واتساب واحدة
      stages/<id>/  data/  absences.db  .darb_tunnel*   ← معزول لكل مرحلة

العزل يقع في مكان واحد: constants.py يحسب DB_PATH و DATA_DIR من مجلد
المرحلة النشطة. فتنعزل الجداول الأربعون والطلاب والمعلمون والمستخدمون
والإعدادات والنسخ الاحتياطية — بلا لمس مئات مواضع الاستدعاء.

⚠️ الضمان الذي لا يُكسر:
    لا stages.json  ⟸  المسارات مطابقة لما كانت حرفاً بحرف.
    كل مدرسة قائمة بمرحلة واحدة لا تتأثر بشيء مما هنا.

⚠️ لا يستورد هذا الملف أي وحدة من المشروع — يُستدعى من main.py قبل
   استيراد constants، تماماً كـ provisioning.py.
"""
import os
import re
import sys
import json

BASE_DIR = (os.path.dirname(sys.executable)
            if getattr(sys, 'frozen', False)
            else os.path.dirname(os.path.abspath(__file__)))

STAGES_FILE = os.path.join(BASE_DIR, 'stages.json')
STAGES_ROOT = os.path.join(BASE_DIR, 'stages')

ENV_VAR = 'DARB_STAGE'

# معرّف المرحلة يصير اسم مجلد — نحصره في محارف آمنة حتى لا يُبنى مسار
# خارج stages/ من ملف إعدادات محرَّر يدوياً.
_SAFE_ID = re.compile(r'^[a-z0-9_-]{1,32}$')


# ══════════════════════════════════════════════════════════════════
#  قراءة التعريف
# ══════════════════════════════════════════════════════════════════
def load_stages() -> list:
    """
    قائمة المراحل من stages.json، أو [] لمدرسة عادية.

    [] تعني «مدرسة بمرحلة واحدة» — وهي الحالة الافتراضية لكل التنصيبات
    القائمة. لا تُرجع هذه الدالة شيئاً يغيّر سلوكها أبداً.
    """
    try:
        with open(STAGES_FILE, encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return []

    items = raw.get('stages') if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []

    out, seen = [], set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        sid = str(it.get('id', '')).strip().lower()
        if not _SAFE_ID.match(sid) or sid in seen:
            continue
        seen.add(sid)
        out.append({
            'id':          sid,
            'name':        str(it.get('name', '') or sid),
            'school_name': str(it.get('school_name', '') or ''),
            'port':        int(it.get('port') or (8000 + i)),
        })
    return out


def get_stage(sid: str) -> dict:
    for s in load_stages():
        if s['id'] == sid:
            return s
    return {}


def stage_dir(sid: str) -> str:
    """مجلد بيانات المرحلة. سلسلة فارغة لمعرّف غير صالح."""
    sid = str(sid or '').strip().lower()
    if not _SAFE_ID.match(sid):
        return ''
    return os.path.join(STAGES_ROOT, sid)


def active_stage() -> str:
    """المرحلة النشطة في هذه العملية (بعد resolve_stage)."""
    return os.environ.get(ENV_VAR, '').strip().lower()


# ══════════════════════════════════════════════════════════════════
#  اختيار المرحلة
# ══════════════════════════════════════════════════════════════════
def _stage_from_argv(argv=None) -> str:
    """--stage=thanawi  أو  --stage thanawi"""
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, a in enumerate(argv):
        if a.startswith('--stage='):
            return a.split('=', 1)[1].strip().lower()
        if a == '--stage' and i + 1 < len(argv):
            return argv[i + 1].strip().lower()
    return ''


def apply_stage(sid: str) -> str:
    """يثبّت المرحلة لهذه العملية ويُنشئ مجلداتها. يُرجع المجلد."""
    d = stage_dir(sid)
    if not d:
        raise ValueError('معرّف مرحلة غير صالح: %r' % sid)
    os.makedirs(os.path.join(d, 'data'), exist_ok=True)
    os.environ[ENV_VAR] = sid
    return d


def resolve_stage(pick=True) -> str:
    """
    يحدّد مرحلة هذه العملية ويثبّتها في البيئة.

    يُرجع '' لمدرسة بمرحلة واحدة — وعندها لا يُلمس شيء، وتبقى المسارات
    كما كانت. الترتيب: البيئة، ثم سطر الأوامر، ثم شاشة الاختيار.

    مرحلة واحدة معرَّفة في الملف تُعتمد بلا سؤال: لا معنى لشاشة اختيار
    بخيار واحد.
    """
    stages = load_stages()
    if not stages:
        return ''

    ids = {s['id'] for s in stages}

    sid = active_stage()
    if sid in ids:
        apply_stage(sid)
        return sid

    sid = _stage_from_argv()
    if sid in ids:
        apply_stage(sid)
        return sid

    if len(stages) == 1:
        apply_stage(stages[0]['id'])
        return stages[0]['id']

    if not pick:
        return ''

    sid = pick_stage_window(stages)
    if not sid:
        return ''          # المستخدم أغلق الشاشة — على المُنادي أن يخرج
    apply_stage(sid)
    return sid


def pick_stage_window(stages: list) -> str:
    """
    شاشة اختيار المرحلة. تُرجع المعرّف، أو '' إن أُغلقت.

    tkinter وحده — لا استيراد من المشروع، فهي تعمل قبل كل شيء.
    """
    import tkinter as tk

    chosen = {'id': ''}
    root = tk.Tk()
    root.title('درب الطلاب — اختر المرحلة')
    root.configure(bg='#0C2E56')
    root.resizable(False, False)

    W, H = 560, 150 + 78 * len(stages)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry('%dx%d+%d+%d' % (W, H, (sw - W) // 2, (sh - H) // 3))

    tk.Label(root, text='اختر المرحلة', bg='#0C2E56', fg='white',
             font=('Segoe UI', 19, 'bold')).pack(pady=(26, 4))
    tk.Label(root, text='لكل مرحلة بياناتها ورابطها المستقلّان تماماً',
             bg='#0C2E56', fg='#9DB8DA', font=('Segoe UI', 10)).pack(pady=(0, 18))

    box = tk.Frame(root, bg='#0C2E56')
    box.pack(fill='both', expand=True, padx=34)

    def choose(sid):
        chosen['id'] = sid
        root.destroy()

    for s in stages:
        card = tk.Frame(box, bg='#12406F', cursor='hand2',
                        highlightthickness=1, highlightbackground='#1E5793')
        card.pack(fill='x', pady=6)

        title = s['name']
        sub = s['school_name'] or ('المنفذ %d' % s['port'])

        lt = tk.Label(card, text=title, bg='#12406F', fg='white',
                      font=('Segoe UI', 14, 'bold'), anchor='e')
        lt.pack(fill='x', padx=18, pady=(11, 0))
        ls = tk.Label(card, text=sub, bg='#12406F', fg='#9DB8DA',
                      font=('Segoe UI', 9), anchor='e')
        ls.pack(fill='x', padx=18, pady=(0, 11))

        # الضغط على أي جزء من البطاقة يختار — لا على النص وحده
        for w in (card, lt, ls):
            w.bind('<Button-1>', lambda e, i=s['id']: choose(i))
            w.bind('<Enter>', lambda e, c=card: c.configure(bg='#1A5490'))
            w.bind('<Leave>', lambda e, c=card: c.configure(bg='#12406F'))
        for w in (lt, ls):
            w.bind('<Enter>', lambda e, c=card, x=w: (c.configure(bg='#1A5490'),
                                                      x.configure(bg='#1A5490')))
            w.bind('<Leave>', lambda e, c=card, x=w: (c.configure(bg='#12406F'),
                                                      x.configure(bg='#12406F')))

    tk.Label(root, text='يمكن تشغيل المرحلتين معاً — افتح البرنامج مرة لكل مرحلة',
             bg='#0C2E56', fg='#6B8CB5', font=('Segoe UI', 8)).pack(pady=(12, 14))

    root.attributes('-topmost', True)
    root.after(200, lambda: root.attributes('-topmost', False))
    root.mainloop()
    return chosen['id']


# ══════════════════════════════════════════════════════════════════
#  هوية القفل
# ══════════════════════════════════════════════════════════════════
def lock_suffix() -> str:
    """
    لاحقة اسم مُزامِن النسخة الواحدة.

    مدرسة بمرحلة واحدة تُرجع '' فيبقى اسم المُزامِن كما هو حرفياً —
    شرطٌ حتى لا يتغيّر سلوك أي تنصيب قائم. ومرحلتان في نفس المجلد
    تحتاجان اسمين مختلفين، وإلا منعت الأولى الثانية من الفتح.
    """
    sid = active_stage()
    return ('_' + sid) if sid else ''
