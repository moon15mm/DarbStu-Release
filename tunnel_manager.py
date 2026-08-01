# -*- coding: utf-8 -*-
"""
tunnel_manager.py — نفق SSH عكسي إلى سيرفر DarbStu

يحلّ محل cloudflare_tunnel.py بنفس أسماء الدوال بالضبط، فلا يحتاج
main.py ولا app_gui.py تعديلاً في الاستدعاء (وهذا مهم لأن main.py
مجمَّد داخل الـ EXE ولا تصله التحديثات التلقائية).

لماذا SSH لا frp:
  frpc.exe تحجبه برامج الحماية (لمايكروسوفت توقيع HackTool:Win32/FRP)
  لأن عصابات الفدية تستخدمه. أما ssh.exe فمدمج في ويندوز 10/11 وموقّع
  من Microsoft، فلا يمكن حجبه ولا يحتاج استثناءات على جهاز المدرسة.

بيانات الاتصال تأتي من ملف التجهيز الذي يُعدّه المزوّد — انظر provisioning.py
"""
import os
import sys
import subprocess
import threading
import time
import atexit

_ssh_process      = None
_saved_port       = None
_saved_domain     = None
_watchdog_on      = False
_status_cb        = None

_BASE_DIR = (os.path.dirname(sys.executable)
             if getattr(sys, 'frozen', False)
             else os.path.dirname(os.path.abspath(__file__)))

_NO_WINDOW = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else {}


# ══════════════════════════════════════════════════════════════════
#  حالة النفق (نفس واجهة cloudflare_tunnel)
# ══════════════════════════════════════════════════════════════════
def set_tunnel_status_callback(cb):
    """يسجّل دالة يُستدعى بها عند تغيّر حالة النفق."""
    global _status_cb
    _status_cb = cb


def _notify(is_alive: bool):
    if _status_cb:
        try:
            _status_cb(is_alive)
        except Exception:
            pass


def _watchdog_loop():
    """يراقب النفق ويعيد تشغيله عند الانقطاع."""
    global _ssh_process, _watchdog_on
    while _watchdog_on:
        time.sleep(60)
        if not _watchdog_on:
            break
        alive = _ssh_process and _ssh_process.poll() is None
        if not alive:
            print("[TUNNEL] ⚠️ النفق متوقف — جارٍ إعادة التشغيل...")
            _notify(False)
            if _saved_port:
                start_cloudflare_tunnel(_saved_port, _saved_domain)
        else:
            _notify(True)


def _start_watchdog():
    global _watchdog_on
    if _watchdog_on:
        return
    _watchdog_on = True
    threading.Thread(target=_watchdog_loop, daemon=True, name="tunnel-watchdog").start()
    print("[TUNNEL] ✅ بدأ المراقبة")


# ══════════════════════════════════════════════════════════════════
#  العثور على ssh
# ══════════════════════════════════════════════════════════════════
def find_cloudflared_executable():
    """
    يبحث عن ssh.exe. الاسم القديم مُبقى للتوافق مع cloud_tab.py
    الذي يستورده بهذا الاسم.

    الترتيب: نسخة ويندوز المدمجة أولاً، ثم النسخة المرفقة مع البرنامج.
    المرفقة (Win32-OpenSSH الموقّعة من Microsoft) تضمن عمل النفق حتى على
    الأجهزة التي أُزيل منها عميل OpenSSH — بلا صلاحيات مدير ولا إنترنت.
    """
    import shutil
    candidates = [
        r"C:\Windows\System32\OpenSSH\ssh.exe",
        r"C:\Program Files\OpenSSH\ssh.exe",
        os.path.join(_BASE_DIR, "openssh", "ssh.exe"),   # المرفقة معنا
        r"C:\Program Files\Git\usr\bin\ssh.exe",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return shutil.which("ssh")


def ssh_source() -> str:
    """من أين يأتي ssh — للعرض في تبويب الربط السحابي والتشخيص."""
    p = find_cloudflared_executable() or ""
    if not p:
        return "غير موجود"
    if p.lower().startswith(r"c:\windows"):
        return "عميل ويندوز المدمج"
    if _BASE_DIR.lower() in p.lower():
        return "النسخة المرفقة مع البرنامج"
    return p


find_ssh_executable = find_cloudflared_executable   # اسم أوضح


def _kill_stale_tunnels(remote_port: int):
    """
    ينهي أي نفق قديم معلّق من تشغيل سابق انهار.

    نُطابق سطر الأوامر على منفذنا وحدنا — قتل كل ssh.exe كان سيقطع
    جلسات SSH الأخرى للمستخدم، وهو ضرر لا مبرر له.
    """
    if os.name != 'nt':
        return
    try:
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='ssh.exe'\" | "
            f"Where-Object {{ $_.CommandLine -like '*127.0.0.1:{remote_port}:*' }} | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, timeout=25, **_NO_WINDOW)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
#  تشغيل / إيقاف النفق
# ══════════════════════════════════════════════════════════════════
def start_cloudflare_tunnel(port: int, domain: str = ""):
    """
    يفتح النفق العكسي ويعيد رابط المدرسة العام، أو None عند الفشل.
    الاسم مُبقى كما هو لأن main.py المجمَّد يستدعيه بهذا الاسم.
    """
    global _ssh_process, _saved_port, _saved_domain
    _saved_port   = port
    _saved_domain = domain

    from provisioning import get_tunnel_settings, is_provisioned

    if not is_provisioned():
        print("[TUNNEL] ⚠️ لم يُجهَّز هذا الجهاز — يعمل محلياً وعلى الشبكة فقط")
        return None

    s = get_tunnel_settings()
    ssh = find_cloudflared_executable()
    if not ssh:
        print("[TUNNEL] ⚠️ تعذّر العثور على ssh.exe — يعمل محلياً وعلى الشبكة فقط")
        return None

    key_file = s.get('key_file', '')
    if not os.path.isfile(key_file):
        print("[TUNNEL] ⚠️ ملف المفتاح مفقود — أعد التجهيز")
        return None

    cmd = [
        ssh, "-N", "-T",
        "-o", "BatchMode=yes",
        "-o", "ExitOnForwardFailure=yes",     # يخرج فوراً إن رُفض حجز المنفذ
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=20",
        "-i", key_file,
        "-p", str(s['ssh_port']),
        "-R", f"127.0.0.1:{s['remote_port']}:127.0.0.1:{int(port)}",
        f"{s['ssh_user']}@{s['server']}",
    ]

    # تثبيت بصمة السيرفر يمنع اعتراض الاتصال
    kh = s.get('known_hosts', '')
    if kh and os.path.isfile(kh):
        cmd[2:2] = ["-o", "StrictHostKeyChecking=yes",
                    "-o", f"UserKnownHostsFile={kh}"]
    else:
        cmd[2:2] = ["-o", "StrictHostKeyChecking=accept-new"]

    public_url = s.get('public_url', '')

    # نفق معلّق من تشغيل سابق يحجز المنفذ ويمنع الاتصال الجديد
    _kill_stale_tunnels(int(s['remote_port']))

    try:
        _ssh_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_NO_WINDOW
        )
    except Exception as e:
        print(f"[TUNNEL] ❌ تعذّر تشغيل ssh: {e}")
        return None

    # ssh -N لا يطبع شيئاً عند النجاح، والأخطاء تظهر فوراً ثم يخرج.
    # لذا ننتظر قليلاً ونحكم ببقاء العملية حيّة.
    errors = []

    def _drain():
        try:
            for ln in _ssh_process.stdout:
                ln = ln.rstrip()
                if ln:
                    print(f"[TUNNEL] {ln}")
                    errors.append(ln)
        except Exception:
            pass

    threading.Thread(target=_drain, daemon=True).start()

    # ssh يخرج فوراً عند أي فشل (مفتاح مرفوض، منفذ محجوز، شبكة).
    # البقاء حيّاً ٧ ثوانٍ يعني أن النفق قائم.
    start_t = time.time()
    while time.time() - start_t < 7:
        if _ssh_process.poll() is not None:
            reason = " | ".join(errors[-3:]) or "سبب غير معروف"
            print(f"[TUNNEL] ❌ فشل فتح النفق: {reason}")
            return None
        time.sleep(0.5)

    print(f"[TUNNEL] ✅ النفق يعمل: {public_url}")
    _notify(True)
    _start_watchdog()
    return public_url


def stop_cloudflare_tunnel():
    """يوقف النفق والمراقبة."""
    global _ssh_process, _watchdog_on
    _watchdog_on = False
    if _ssh_process:
        try:
            _ssh_process.terminate()
            _ssh_process = None
            print("[TUNNEL] 🛑 تم إيقاف النفق")
        except Exception as e:
            print(f"[TUNNEL] خطأ عند الإيقاف: {e}")


def _atexit_kill_tunnel():
    """يضمن إغلاق النفق عند أي خروج، حتى غير الطبيعي."""
    global _ssh_process, _watchdog_on
    _watchdog_on = False
    try:
        if _ssh_process and _ssh_process.poll() is None:
            _ssh_process.terminate()
    except Exception:
        pass


atexit.register(_atexit_kill_tunnel)
