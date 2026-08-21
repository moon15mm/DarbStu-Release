# -*- coding: utf-8 -*-
"""
netsetup.py — ضبط الوصلة المباشرة بين اللابتوب وجهاز البصمة.

السيناريو: سلك شبكة يصل اللابتوب بالجهاز رأساً — بلا راوتر ولا شبكة
مدرسة. كي يتحدّثا، يجب أن يكونا في الشبكة الفرعية نفسها. جهاز البصمة
له IP ثابت (مصنعياً غالباً 192.168.1.201)، فنضبط منفذ اللابتوب على
عنوان مجاور (192.168.1.100) بلا بوّابة.

هذا الملف:
  • يكتشف منافذ الشبكة السلكية في اللابتوب (قراءة، بلا صلاحيات).
  • يحسب عنواناً مناسباً للّابتوب من عنوان الجهاز.
  • يبني أمر netsh لضبط العنوان (تطبيقه يحتاج صلاحية مدير).
  • يفحص الوصلة: هل الجهاز يردّ على المنفذ 4370.
  • يعيد المنفذ إلى DHCP عند الانتهاء.

القراءة والفحص بلا صلاحيات. التغيير الفعلي للعنوان يحتاج مدير — والأداة
تكتشف ذلك وترشد، ولا تلمس شبكتك إلا بضغطة صريحة منك.
"""
import ctypes
import re
import socket
import subprocess
import sys

DEVICE_PORT = 4370
DEFAULT_DEVICE_IP = "192.168.1.201"   # افتراضي مصنعي شائع لأجهزة ZK

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _run(args, timeout=15):
    """يشغّل أمراً ويُرجع (رمز الخروج، الخرج). بلا نافذة سوداء."""
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=_NO_WINDOW)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return -1, str(e)


def is_admin():
    """هل نعمل بصلاحية مدير؟ (تغيير IP يحتاجها)."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def list_adapters():
    """
    منافذ الشبكة وحالتها وعناوينها — قراءة فقط.
    يُرجع [{name, status, ip, mask, dhcp}].
    نعتمد netsh لأنه موجود في كل ويندوز بلا PowerShell.
    """
    code, out = _run(["netsh", "-c", "interface", "ipv4",
                      "show", "config"])
    if code != 0:
        return []
    blocks = re.split(r"\r?\n\r?\n", out)
    adapters = []
    for b in blocks:
        m = re.search(r'"([^"]+)"', b)
        if not m:
            m = re.search(r"[Cc]onfiguration for interface\s+\"?([^\"\n]+)\"?",
                          b)
        if not m:
            continue
        name = m.group(1).strip()
        ipm = re.search(r"IP\s*Address:\s*([\d.]+)", b) or \
            re.search(r"عنوان\s*IP.*?:\s*([\d.]+)", b)
        maskm = re.search(r"(?:Subnet Prefix|mask).*?\(mask\s+([\d.]+)\)", b) or \
            re.search(r"[Mm]ask\s+([\d.]+)", b)
        dhcp = bool(re.search(r"DHCP\s+enabled:\s*Yes", b, re.I) or
                    re.search(r"DHCP.*?نعم", b))
        adapters.append({
            "name": name,
            "ip": ipm.group(1) if ipm else "",
            "mask": maskm.group(1) if maskm else "",
            "dhcp": dhcp,
        })
    return adapters


def ethernet_adapters():
    """يرشّح المنافذ السلكية المرجّحة (يستبعد Wi-Fi و Loopback و VPN)."""
    out = []
    for a in list_adapters():
        n = a["name"].lower()
        if any(x in n for x in ("wi-fi", "wifi", "wireless", "loopback",
                                "bluetooth", "vethernet", "vmware", "virtual",
                                "لاسلك", "vpn", "tailscale", "radmin")):
            continue
        out.append(a)
    return out


def suggest_laptop_ip(device_ip=DEFAULT_DEVICE_IP):
    """
    يقترح عنواناً للّابتوب في شبكة الجهاز الفرعية: نفس أول ثلاث خانات،
    وخانة أخيرة مختلفة عن الجهاز (نختار .100، أو .200 إن كان الجهاز .100).
    """
    try:
        a, b, c, d = device_ip.split(".")
        last = 100 if d != "100" else 200
        return "%s.%s.%s.%d" % (a, b, c, last), "255.255.255.0"
    except Exception:
        return "192.168.1.100", "255.255.255.0"


def build_static_cmd(adapter, ip, mask="255.255.255.0"):
    """أمر ضبط العنوان الثابت (بلا بوّابة — وصلة مباشرة)."""
    return ["netsh", "interface", "ipv4", "set", "address",
            'name=%s' % adapter, "static", ip, mask]


def set_static_ip(adapter, ip, mask="255.255.255.0"):
    """
    يضبط العنوان الثابت فعلاً. يحتاج مدير. يُرجع (نجح, رسالة).
    لا يُستدعى إلا بضغطة صريحة من المستخدم.
    """
    if not is_admin():
        return False, "يحتاج صلاحية مدير — أعد تشغيل الأداة كمسؤول."
    code, out = _run(build_static_cmd(adapter, ip, mask))
    if code == 0:
        return True, "ضُبط عنوان اللابتوب: %s" % ip
    return False, out.strip()[:200]


def restore_dhcp(adapter):
    """يعيد المنفذ إلى DHCP بعد انتهاء التسجيل."""
    if not is_admin():
        return False, "يحتاج صلاحية مدير."
    code, out = _run(["netsh", "interface", "ipv4", "set", "address",
                      'name=%s' % adapter, "dhcp"])
    if code == 0:
        return True, "أُعيد المنفذ إلى DHCP."
    return False, out.strip()[:200]


def test_device(ip, port=DEVICE_PORT, timeout=4):
    """
    يفحص الوصلة على مرحلتين: هل المنفذ 4370 مفتوح، ثم هل يتكلّم ZK.
    يُرجع {ok, stage, info|error}.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        s.close()
    except Exception as e:
        s.close()
        return {"ok": False, "stage": "port",
                "error": "المنفذ %d مغلق أو لا وصول — تحقّق من السلك "
                         "والعنوان: %s" % (port, e)}
    # المصافحة الكاملة عبر طبقة الجهاز
    try:
        from biometric.zk_device import ZKDevice
        info = ZKDevice({"ip": ip, "port": port}).test_connection()
        return {"ok": True, "stage": "zk", "info": info}
    except Exception as e:
        return {"ok": False, "stage": "handshake",
                "error": "المنفذ مفتوح لكن تعذّرت مصافحة ZK: %s" % e}


def can_reach(ip):
    """ping سريع — للتحقق أن العنوان في المدى قبل فحص المنفذ."""
    code, _ = _run(["ping", "-n", "1", "-w", "1000", ip], timeout=6)
    return code == 0


def diagnose(device_ip=DEFAULT_DEVICE_IP):
    """
    تشخيص شامل بخطوة واحدة: المنافذ، والصلاحية، وحالة الوصلة، والاقتراح.
    يقود واجهة الأداة ورسائلها.
    """
    eth = ethernet_adapters()
    ip, mask = suggest_laptop_ip(device_ip)
    on_subnet = any(a["ip"].rsplit(".", 1)[0] == device_ip.rsplit(".", 1)[0]
                    for a in eth if a["ip"])
    return {
        "admin": is_admin(),
        "ethernet": eth,
        "device_ip": device_ip,
        "suggested_ip": ip,
        "suggested_mask": mask,
        "already_on_subnet": on_subnet,
        "reachable": can_reach(device_ip) if on_subnet else False,
    }
