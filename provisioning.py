# -*- coding: utf-8 -*-
"""
provisioning.py — تجهيز جهاز المدرسة قبل التسليم

النموذج: المزوّد (لا المدرسة) يجهّز كل شيء.

  ١. على السيرفر:  darbstu-add-school alnoor
     يُنتج ملف provision-alnoor.json فيه مفتاح المدرسة ومنفذها ونطاقها.
  ٢. المزوّد ينسخه باسم provision.json بجانب DarbStu.exe قبل التسليم.
  ٣. عند أول تشغيل يُقرأ، يُكتب المفتاح بصلاحيات مقيّدة، ثم **يُحذف الملف**
     حتى لا يبقى المفتاح الخاص نصاً صريحاً على قرص المدرسة.

المدرسة لا ترى شيئاً من هذا ولا تُسأل عن أي إعداد.

⚠️ لا يستورد هذا الملف أي وحدة من المشروع — يُستدعى من setup_wizard
   قبل الاستيرادات الثقيلة.
"""
import os
import sys
import json
import subprocess

BASE_DIR = (os.path.dirname(sys.executable)
            if getattr(sys, 'frozen', False)
            else os.path.dirname(os.path.abspath(__file__)))

DATA_DIR    = os.path.join(BASE_DIR, 'data')
CONFIG_JSON = os.path.join(DATA_DIR, 'config.json')

_PROVISION_NAMES = ('provision.json', 'darbstu-provision.json')

# ملفات النفق — خارج data حتى لا يخدمها الخادم بأي حال
TUNNEL_FILE      = os.path.join(BASE_DIR, '.darb_tunnel.json')
KEY_FILE         = os.path.join(BASE_DIR, '.darb_tunnel_key')
KNOWN_HOSTS_FILE = os.path.join(BASE_DIR, '.darb_known_hosts')

_NO_WINDOW = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else {}


# ══════════════════════════════════════════════════════════════════
#  صلاحيات ملف المفتاح
# ══════════════════════════════════════════════════════════════════
def _lock_down(path: str):
    """
    يقصر صلاحيات الملف على مالكه.

    ssh.exe على ويندوز يرفض المفاتيح التي يمكن لمستخدمين آخرين قراءتها
    ويطبع 'UNPROTECTED PRIVATE KEY FILE' ثم يفشل، لذا نزيل الوراثة
    ونمنح المستخدم الحالي وحده صلاحية كاملة.
    """
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    if os.name != 'nt':
        return
    try:
        user = os.environ.get('USERNAME') or os.environ.get('USER') or ''
        if not user:
            return
        subprocess.run(['icacls', path, '/inheritance:r'],
                       capture_output=True, **_NO_WINDOW)
        subprocess.run(['icacls', path, '/grant:r', f'{user}:F'],
                       capture_output=True, **_NO_WINDOW)
    except Exception as e:
        print(f"[PROVISION] تعذّر ضبط صلاحيات {os.path.basename(path)}: {e}")


# ══════════════════════════════════════════════════════════════════
#  قراءة الحالة
# ══════════════════════════════════════════════════════════════════
def _search_dirs():
    """
    أماكن البحث عن ملف التجهيز.

    الأصل أن يوضع بجانب DarbStu.exe، لكن مجلد اختصارات قائمة ابدأ يحمل
    الاسم نفسه (Roaming\\...\\Start Menu\\Programs\\DarbStu) فيقع فيه الالتباس
    كثيراً. نبحث في الأماكن الشائعة كلها بدل أن يفشل التجهيز بصمت.
    """
    dirs = [BASE_DIR, DATA_DIR]
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    for d in (
        os.path.join(home, "Desktop"),
        os.path.join(home, "Downloads"),
        os.path.join(appdata, "Microsoft", "Windows",
                     "Start Menu", "Programs", "DarbStu") if appdata else "",
    ):
        if d:
            dirs.append(d)
    return dirs


def _find_provision_file() -> str:
    for d in _search_dirs():
        for n in _PROVISION_NAMES:
            try:
                p = os.path.join(d, n)
                if os.path.isfile(p):
                    return p
            except Exception:
                continue
    return ''


def is_provisioned() -> bool:
    """هل جُهِّز هذا الجهاز؟ (بيانات النفق والمفتاح موجودان)"""
    return os.path.isfile(TUNNEL_FILE) and os.path.isfile(KEY_FILE)


def get_tunnel_settings() -> dict:
    try:
        with open(TUNNEL_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def get_public_domain() -> str:
    """النطاق الكامل للمدرسة، مثل alnoor.darbstu.com"""
    return get_tunnel_settings().get('domain', '')


# ══════════════════════════════════════════════════════════════════
#  تطبيق ملف التجهيز
# ══════════════════════════════════════════════════════════════════
def apply_provision_file() -> dict:
    """
    يقرأ ملف التجهيز إن وُجد، يكتب المفتاح وبصمة السيرفر والإعدادات،
    ثم يحذف الملف. يُرجع بيانات النفق أو {} إن لم يوجد ملف.
    """
    path = _find_provision_file()
    if not path:
        return {}

    try:
        with open(path, encoding='utf-8') as f:
            p = json.load(f)
    except Exception as e:
        print(f"[PROVISION] ملف التجهيز تالف: {e}")
        return {}

    required = ('school_id', 'subdomain', 'server', 'ssh_port',
                'remote_port', 'ssh_user', 'private_key')
    missing = [k for k in required if not p.get(k)]
    if missing:
        print(f"[PROVISION] ملف التجهيز ناقص: {', '.join(missing)}")
        return {}

    domain = p.get('domain') or f"{p['subdomain']}.darbstu.com"

    # ── المفتاح الخاص ─────────────────────────────────────────────
    try:
        key = p['private_key']
        if not key.endswith('\n'):
            key += '\n'
        with open(KEY_FILE, 'w', encoding='utf-8', newline='\n') as f:
            f.write(key)
        _lock_down(KEY_FILE)
    except Exception as e:
        print(f"[PROVISION] تعذّر حفظ المفتاح: {e}")
        return {}

    # ── بصمة السيرفر — تمنع اعتراض الاتصال (MITM) ────────────────
    host_key = (p.get('host_key') or '').strip()
    if host_key:
        try:
            with open(KNOWN_HOSTS_FILE, 'w', encoding='utf-8', newline='\n') as f:
                f.write(host_key + '\n')
        except Exception as e:
            print(f"[PROVISION] تعذّر حفظ بصمة السيرفر: {e}")

    tunnel = {
        'school_id':   p['school_id'],
        'subdomain':   p['subdomain'],
        'domain':      domain,
        'public_url':  f"https://{domain}",
        'server':      p['server'],
        'ssh_port':    int(p['ssh_port']),
        'ssh_user':    p['ssh_user'],
        'remote_port': int(p['remote_port']),
        'key_file':    KEY_FILE,
        'known_hosts': KNOWN_HOSTS_FILE if host_key else '',
    }

    try:
        with open(TUNNEL_FILE, 'w', encoding='utf-8') as f:
            json.dump(tunnel, f, ensure_ascii=False, indent=2)
        _lock_down(TUNNEL_FILE)
    except Exception as e:
        print(f"[PROVISION] تعذّر حفظ بيانات النفق: {e}")
        return {}

    # النطاق يُخزَّن في المفتاح القديم نفسه، فيقرأه constants.STATIC_DOMAIN
    # وتعمل روابط QR وبوابة أولياء الأمور بلا أي تعديل في بقية الكود.
    _merge_config({
        'cloudflare_domain': domain,
        'school_name': p.get('school_name') or _existing('school_name'),
    })

    # حذف ملف التجهيز — لا يبقى المفتاح الخاص نصاً صريحاً
    try:
        os.remove(path)
        print(f"[PROVISION] ✅ جُهِّز الجهاز: {domain}  (حُذف ملف التجهيز)")
    except Exception:
        print(f"[PROVISION] ✅ جُهِّز الجهاز: {domain}\n"
              f"[PROVISION] ⚠️ تعذّر حذف {path} — احذفه يدوياً")

    return tunnel


def _existing(key: str):
    try:
        with open(CONFIG_JSON, encoding='utf-8') as f:
            return json.load(f).get(key, '')
    except Exception:
        return ''


def _merge_config(updates: dict):
    """يدمج قيماً في config.json دون المساس ببقية الإعدادات."""
    cfg = {}
    try:
        if os.path.exists(CONFIG_JSON):
            with open(CONFIG_JSON, encoding='utf-8') as f:
                cfg = json.load(f)
    except Exception:
        cfg = {}
    for k, v in updates.items():
        if v:
            cfg[k] = v
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_JSON, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
