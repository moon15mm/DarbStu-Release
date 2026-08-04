# -*- coding: utf-8 -*-
"""
constants.py — كل الثوابت والمتغيرات العامة المشتركة
"""
import os, sys, datetime, socket, threading

# ── Lazy imports globals ──────────────────────────────────────────
HtmlFrame         = None
DateEntry         = None
Figure            = None
FigureCanvasTkAgg = None
matplotlib        = None
arabic_reshaper   = None
get_display       = None

def _ensure_matplotlib():
    global matplotlib, Figure, FigureCanvasTkAgg, arabic_reshaper, get_display
    if matplotlib is not None:
        return
    import matplotlib as _mpl
    from matplotlib.figure import Figure as _Fig
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as _FCA
    _mpl.rcParams['font.family'] = ['Tahoma', 'Arial', 'DejaVu Sans']
    _mpl.rcParams['axes.unicode_minus'] = False
    matplotlib = _mpl; Figure = _Fig; FigureCanvasTkAgg = _FCA
    try:
        import arabic_reshaper as _ar
        from bidi.algorithm import get_display as _gd
        arabic_reshaper = _ar; get_display = _gd
    except ImportError:
        pass

def _ensure_tkinterweb():
    global HtmlFrame
    if HtmlFrame is not None:
        return
    from tkinterweb import HtmlFrame as _HF
    HtmlFrame = _HF

def _ensure_tkcalendar():
    global DateEntry
    if DateEntry is not None:
        return
    from tkcalendar import DateEntry as _DE
    DateEntry = _DE

# عند التشغيل كـ EXE مجمّع → مجلد الـ EXE، وإلا مجلد السكريبت
BASE_DIR            = (os.path.dirname(sys.executable)
                       if getattr(sys, 'frozen', False)
                       else os.path.dirname(os.path.abspath(__file__)))

PORT           = int(os.environ.get('ABSENTEE_PORT', '8000'))

# ── قراءة الدومين من config.json عند الاستيراد ────────────────
def _read_saved_domain() -> str:
    """يقرأ cloudflare_domain مباشرة من config.json بدون config_manager."""
    try:
        import json as _j
        _p = os.path.join(BASE_DIR, 'data', 'config.json')
        if os.path.exists(_p):
            return _j.load(open(_p, 'r', encoding='utf-8')).get('cloudflare_domain', '')
    except Exception:
        pass
    return ''

_saved_domain     = _read_saved_domain()
STATIC_DOMAIN     = f'https://{_saved_domain}' if _saved_domain else ''
CLOUDFLARE_DOMAIN = _saved_domain
MY_STATIC_DOMAIN  = _saved_domain
ngrok = None

APP_TITLE           = 'تسجيل غياب الطلاب'
APP_VERSION         = '3.6.11'
UPDATE_URL          = 'https://raw.githubusercontent.com/moon15mm/DarbStu-Release/main/version.json'
UPDATE_DOWNLOAD_URL = 'https://github.com/moon15mm/DarbStu-Release/archive/refs/heads/main.zip'

# ─── قناة التحديث الموقَّعة ────────────────────────────────────
# البيان يُوقَّع بمفتاح Ed25519 خاص لا يغادر خادم darbstu.com، ويُتحقق
# منه هنا قبل كتابة أي ملف. من يملك المستودع على GitHub لا يستطيع
# حقن كود، لأنه لا يملك المفتاح. المفتاح العام آمن أن يكون علنياً.
UPDATE_MANIFEST_URL = 'https://darbstu.com/update/manifest.json'
UPDATE_PUBKEY       = 'JU3zbYeDT60ZZ/nXcNxO2PD6oIjmU7r0+o9TBXPbdLs='
DB_PATH             = os.path.join(BASE_DIR, 'absences.db')
DATA_DIR            = os.path.join(BASE_DIR, 'data')
STUDENTS_JSON       = os.path.join(DATA_DIR, 'students.json')
USERS_JSON          = os.path.join(DATA_DIR, 'users.json')
TARDINESS_JSON      = os.path.join(DATA_DIR, 'tardiness.db')
BACKUP_DIR            = os.path.join(DATA_DIR, 'backups')
INBOX_ATTACHMENTS_DIR = os.path.join(DATA_DIR, 'inbox_attachments')
SCHOOL_REPORTS_DIR    = os.path.join(DATA_DIR, 'school_reports')
TEACHERS_JSON         = os.path.join(DATA_DIR, 'teachers.json')
CONFIG_JSON         = os.path.join(DATA_DIR, 'config.json')
HOST                = '127.0.0.1'
TZ_OFFSET           = datetime.timedelta(hours=3)
STUDENTS_STORE      = None
WHATS_PATH          = os.path.join(BASE_DIR, 'my-whatsapp-server')

ROLES = {
    'admin':   {'label': 'مدير',       'tabs': 'all',    'color': '#7c3aed'},
    'deputy':  {'label': 'وكيل',       'tabs': 'most',   'color': '#1d4ed8'},
    'staff':   {'label': 'إداري',      'tabs': 'most',   'color': '#2563eb'},
    'counselor': {'label': 'موجه طلابي', 'tabs': 'most', 'color': '#059669'},
    'activity_leader': {'label': 'رائد نشاط', 'tabs': 'limited', 'color': '#d97706'},
    'teacher': {'label': 'معلم',       'tabs': 'limited','color': '#065f46'},
    'lab':     {'label': 'محضر',       'tabs': 'limited','color': '#0891b2'},
    'guard':   {'label': 'حارس',       'tabs': 'view',   'color': '#92400e'},
}

ROLE_TABS = {
    'admin':   None,
    'deputy':  ['لوحة المراقبة','المراقبة الحية','روابط الفصول','تسجيل الغياب','تسجيل التأخر',
                'طلب استئذان','سجل الغياب','سجل التأخر','الأعذار','الاستئذان','إدارة الغياب',
                'الموجّه الطلابي','استلام تحويلات','التقارير / الطباعة','تقرير الفصل','تقرير الإدارة',
                'تحليل طالب','أكثر الطلاب غياباً','الإشعارات الذكية','إرسال رسائل الغياب',
                'إرسال رسائل التأخر','روابط بوابة أولياء الأمور','التعاميم والنشرات','قصص المدرسة','تعزيز الحضور الأسبوعي',
                'لوحة الصدارة (النقاط)','إدارة الطلاب','إضافة طالب','إدارة الفصول','إدارة الجوالات',
                'الطلاب المستثنون','نشر النتائج','تصدير نور','زيارات أولياء الأمور','هروب واستئذان',
                'تقارير المدرسة','إدارة الباصات'],
    'staff':   ['لوحة المراقبة','المراقبة الحية','روابط الفصول','تسجيل الغياب','تسجيل التأخر',
                'طلب استئذان','سجل الغياب','سجل التأخر','الأعذار','الاستئذان','التعاميم والنشرات',
                'إدارة الطلاب','إضافة طالب','إدارة الجوالات','الطلاب المستثنون','قصص المدرسة',
                'لوحة الصدارة (النقاط)', 'تحليل طالب','زيارات أولياء الأمور'],
    'counselor': ['لوحة المراقبة','المراقبة الحية','روابط الفصول','سجل الغياب','سجل التأخر','الأعذار',
                  'الموجّه الطلابي','تحليل طالب','أكثر الطلاب غياباً','الإشعارات الذكية',
                  'التعاميم والنشرات','قصص المدرسة','تعزيز الحضور الأسبوعي','لوحة الصدارة (النقاط)',
                  'زيارات أولياء الأمور','تقارير المدرسة'],
    'activity_leader': ['لوحة المراقبة','التعاميم والنشرات','قصص المدرسة','لوحة الصدارة (النقاط)',
                        'تحليل طالب','نماذج المعلم','تقارير المدرسة'],
    'teacher': ['لوحة المراقبة','تحويل طالب','نماذج المعلم','تحليل النتائج','التعاميم والنشرات',
                'لوحة الصدارة (النقاط)', 'تحليل طالب','تقارير المدرسة'],
    'lab':     ['لوحة المراقبة','نماذج المعلم','التعاميم والنشرات', 'لوحة الصدارة (النقاط)', 'تحليل طالب'],
    'guard':   ['لوحة المراقبة','تسجيل التأخر','المراقبة الحية', 'لوحة الصدارة (النقاط)', 'تحليل طالب'],
}

CURRENT_USER = {'username': '', 'role': 'admin', 'label': 'مدير'}

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)

def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(0)
        s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]
    except Exception: ip = "127.0.0.1"
    finally:
        try: s.close()
        except: pass
    return ip

def now_riyadh_date():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    ry_now = utc_now.astimezone(datetime.timezone(TZ_OFFSET))
    return ry_now.date().isoformat()

def navbar_html(base_url: str) -> str:
    return f'''\n<div style="background-color: #007bff; padding: 12px; text-align: center;">
        <a href="{base_url}/mobile"
           style="color: white; text-decoration: none; font-weight: bold; font-size: 18px; display: inline-block; padding: 8px 16px; border-radius: 6px; background-color: #0056b3;">
            🏠 الصفحة الرئيسية
        </a>
    </div>
    '''

def debug_on() -> bool:
    return os.environ.get("ABSENTEE_DEBUG", "0") == "1"
