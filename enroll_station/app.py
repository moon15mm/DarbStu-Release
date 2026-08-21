# -*- coding: utf-8 -*-
"""
app.py — خادم أداة التسجيل المستقلّة (بلا مصادقة، محليّ فقط).

برنامج صغير على لابتوب، يوصَل بجهاز البصمة بسلك شبكة مباشر. مهمّته
الوحيدة: تسجيل بصمات الطلاب. لا سيرفر ولا ترخيص ولا نفق — فقط:
  • ضبط الشبكة بين اللابتوب والجهاز وفحص الاتصال.
  • سحب الطلاب وأرقامهم (من ملف roster.json أو من رابط النظام).
  • الطابور الموجَّه: اسم، زر، إصبع، التالي.
  • حفظ «من سُجّل» (enrolled.json) ليستورده النظام.

يشارك طبقة الجهاز `biometric/` و `enroll_station/netsetup.py` — لا تكرار.
"""
import datetime
import io
import json
import os
import sys
import urllib.request

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

# جذر المشروع في المسار — لمشاركة biometric و netsetup
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from enroll_station import netsetup as N   # noqa: E402

DATA_DIR = os.path.join(_HERE, "data")
ROSTER_FILE = os.path.join(DATA_DIR, "roster.json")
ENROLLED_FILE = os.path.join(DATA_DIR, "enrolled.json")
CONFIG_FILE = os.path.join(DATA_DIR, "station.json")

app = FastAPI()


def _cfg():
    try:
        return json.load(io.open(CONFIG_FILE, encoding="utf-8"))
    except Exception:
        return {"device_ip": "192.168.1.201", "port": 4370, "comm_key": 0,
                "protocol": "zk", "system_url": "", "system_token": ""}


def _save_cfg(c):
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(c, io.open(CONFIG_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def _device(cfg=None):
    from biometric import make_device
    c = cfg or _cfg()
    return make_device({"protocol": c.get("protocol", "zk"),
                        "ip": c.get("device_ip", ""),
                        "port": int(c.get("port") or 4370),
                        "comm_key": int(c.get("comm_key") or 0),
                        "device_id": "station"})


def _load_roster():
    try:
        return json.load(io.open(ROSTER_FILE, encoding="utf-8"))
    except Exception:
        return {"students": []}


def _load_enrolled():
    try:
        return json.load(io.open(ENROLLED_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _save_enrolled(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(d, io.open(ENROLLED_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


# ── الشبكة ────────────────────────────────────────────────────────
@app.get("/api/net")
def net_status():
    c = _cfg()
    return JSONResponse(N.diagnose(c.get("device_ip", "192.168.1.201")))


@app.post("/api/net/scan")
def net_scan():
    # بحث سريع على المنفذ 4370 في شبكة اللابتوب المباشرة
    import socket
    import threading
    me = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        me = s.getsockname()[0]
        s.close()
    except Exception:
        me = "192.168.1.100"
    base = me.rsplit(".", 1)[0]
    found = []
    lock = threading.Lock()

    def check(i):
        ip = "%s.%d" % (base, i)
        sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sk.settimeout(0.6)
        try:
            sk.connect((ip, 4370))
            with lock:
                found.append(ip)
        except Exception:
            pass
        finally:
            sk.close()

    ts = [threading.Thread(target=check, args=(i,)) for i in range(1, 255)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return JSONResponse({"ok": True, "found": found, "network": base})


@app.post("/api/net/setip")
async def net_setip(request: Request):
    d = await request.json()
    ok, msg = N.set_static_ip(d.get("adapter", ""), d.get("ip", ""),
                              d.get("mask", "255.255.255.0"))
    return JSONResponse({"ok": ok, "msg": msg})


@app.post("/api/net/dhcp")
async def net_dhcp(request: Request):
    d = await request.json()
    ok, msg = N.restore_dhcp(d.get("adapter", ""))
    return JSONResponse({"ok": ok, "msg": msg})


@app.post("/api/test")
async def test_device(request: Request):
    d = await request.json()
    c = _cfg()
    if "device_ip" in d:
        c["device_ip"] = d["device_ip"]
    if "comm_key" in d:
        c["comm_key"] = int(d.get("comm_key") or 0)
    if "protocol" in d:
        c["protocol"] = d["protocol"]
    _save_cfg(c)
    try:
        info = _device(c).test_connection()
        return JSONResponse({"ok": True, "info": info})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ── الطلاب ────────────────────────────────────────────────────────
@app.get("/api/roster")
def roster():
    r = _load_roster()
    en = _load_enrolled()
    studs = r.get("students", [])
    # نجمع بالفصول مع الحفاظ على ترتيب ظهورها في الملف
    order = []
    groups = {}
    total = done = 0
    for s in studs:
        cn = s.get("class_name", "") or "بلا فصل"
        is_en = str(s.get("academic_no")) in en
        total += 1
        done += 1 if is_en else 0
        if cn not in groups:
            groups[cn] = []
            order.append(cn)
        groups[cn].append({"academic_no": s.get("academic_no"),
                           "name": s.get("name", ""),
                           "student_id": s.get("student_id", ""),
                           "enrolled": is_en})
    classes = [{"name": cn, "students": groups[cn],
                "done": sum(1 for x in groups[cn] if x["enrolled"]),
                "total": len(groups[cn])} for cn in order]
    return JSONResponse({"ok": True, "classes": classes,
                         "total": total, "done": done})


@app.post("/api/roster/pull")
async def roster_pull(request: Request):
    """يسحب الطلاب وأرقامهم من النظام مباشرةً (لو كان اللابتوب على النت)."""
    d = await request.json()
    c = _cfg()
    url = (d.get("system_url") or c.get("system_url") or "").rstrip("/")
    token = d.get("system_token") or c.get("system_token") or ""
    if not url:
        return JSONResponse({"ok": False, "error": "لا رابط للنظام"})
    c["system_url"] = url
    c["system_token"] = token
    _save_cfg(c)
    try:
        req = urllib.request.Request(url + "/web/api/biometric/roster")
        if token:
            req.add_header("Cookie", "darb_token=" + token)
        data = json.loads(urllib.request.urlopen(req, timeout=25).read())
        if not data.get("ok"):
            return JSONResponse({"ok": False, "error": "رفض النظام"})
        os.makedirs(DATA_DIR, exist_ok=True)
        json.dump({"students": data.get("students", [])},
                  io.open(ROSTER_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        return JSONResponse({"ok": True, "count": data.get("count", 0)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/enroll")
async def enroll(request: Request):
    """
    يبدأ الالتقاط على الجهاز **وينتظر اكتماله** (يضع الطالب إصبعه)، ولا
    يُعلّم الطالب مسجّلاً إلا إذا التقط الجهاز البصمة فعلاً. الانتظار
    يجري في خيط منفصل كي لا يُجمّد الخادم.
    """
    import asyncio
    d = await request.json()
    academic = str(d.get("academic_no", "")).strip()
    name = d.get("name", "")
    sid = str(d.get("student_id", "")).strip()
    if not academic:
        return JSONResponse({"ok": False, "error": "لا رقم أكاديمي"})

    def _capture():
        return _device().enroll_and_wait(academic, name, 0, timeout=25)

    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _capture)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})

    if not res.get("ok"):
        # لم يلتقط الجهاز — لا نُعلّمه مسجّلاً
        return JSONResponse({"ok": False,
                             "error": res.get("error", "لم يكتمل الالتقاط")})

    en = _load_enrolled()
    en[academic] = {"name": name, "student_id": sid,
                    "at": datetime.datetime.utcnow().isoformat()}
    _save_enrolled(en)
    return JSONResponse({"ok": True, "captured": True})


@app.get("/api/enrolled")
def enrolled():
    en = _load_enrolled()
    return JSONResponse({"ok": True, "count": len(en), "enrolled": en})


@app.get("/", response_class=HTMLResponse)
def home():
    from enroll_station.page import PAGE
    return HTMLResponse(PAGE)
