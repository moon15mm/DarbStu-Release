# -*- coding: utf-8 -*-
"""
license_manager.py — نظام الترخيص والاشتراك
"""
import os, json, base64, datetime, hashlib, threading, requests, sys
from typing import List, Dict, Any, Optional
import hashlib as _hl, hmac as _hm, uuid as _uuid, platform as _plat
import tkinter as tk
from tkinter import ttk, messagebox
from constants import BASE_DIR, APP_VERSION, ROLES, CURRENT_USER
from database import get_db

# ═══════════════════════════════════════════════════════════════
# نظام الترخيص والاشتراك
# ═══════════════════════════════════════════════════════════════
# نظام واحد فقط: LicenseClient (Google Sheet + Apps Script) المعرَّف أدناه.
# الدوال هنا واجهات توافق للنداءات القديمة (app_gui / results_tab) وكلها
# تمرّ عبر LicenseClient حتى لا يكتب نظامان في .darb_license بصيغتين
# متعارضتين — كان ذلك يمحو تفعيل المدرسة ويقفل البرنامج عليها.
import hashlib as _hl, uuid as _uuid, platform as _plat


def _machine_fingerprint() -> str:
    """بصمة الجهاز: MAC + اسم الجهاز. صيغة واحدة يستخدمها كل الملف."""
    try:
        raw = "{}-{}-darb".format(_uuid.getnode(), _plat.node())
        return _hl.sha256(raw.encode()).hexdigest()[:32]
    except Exception:
        return _hl.sha256(b"fallback").hexdigest()[:32]


def _machine_id_is_reliable() -> bool:
    """
    False إذا تعذّر على بايثون قراءة عنوان MAC الحقيقي.

    في تلك الحالة يولّد uuid.getnode() عنواناً عشوائياً يتغيّر كل تشغيل
    (ويضبط بت البثّ المتعدد). ربط الترخيص ببصمة كهذه يقفل البرنامج على
    مدرسة دفعت، لذا نتخطى فحص الجهاز عند اكتشافها.
    """
    try:
        return not ((_uuid.getnode() >> 40) & 0x01)
    except Exception:
        return False


def _get_machine_id() -> str:
    """اسم قديم مُستورَد في app_gui — أُبقي للتوافق."""
    return _machine_fingerprint()


def check_license() -> dict:
    """
    حالة الترخيص بصيغة القاموس القديمة.
    يُرجع: {"valid": bool, "days_left": int, "school": str, "msg": str}
    """
    ok, msg, info = LicenseClient().check()
    return {
        "valid":     ok,
        "days_left": int(info.get("days_left", 0) or 0),
        "school":    info.get("school_name", ""),
        "msg":       "" if ok else msg,
    }


def activate_license(license_key: str, school_name: str = "") -> tuple:
    """
    تفعيل موحَّد — يمرّ عبر LicenseClient (تحقق من الشيت ثم حذف المفتاح).
    يُرجع: (True, "رسالة") أو (False, "خطأ")
    """
    ok, msg, _info = LicenseClient().activate(license_key, school_name)
    return ok, msg


def try_renew_license():
    """أُبقيت للتوافق — التفعيل في نظام الشيت دائم ولا يحتاج تجديداً دورياً."""
    return


class LicenseWindow:
    """شاشة التفعيل وانتهاء الاشتراك."""

    def __init__(self, root: tk.Tk, status: dict, on_success=None):
        self.root       = root
        self.status     = status
        self.on_success = on_success
        self._build(root)

    def _build(self, root):
        win = tk.Toplevel(root)
        win.title("ترخيص DarbStu")
        win.geometry("480x380")
        win.resizable(False, False)
        win.transient(root)
        win.grab_set()
        win.protocol("WM_DELETE_WINDOW", root.destroy)  # إغلاق = خروج من البرنامج

        # خلفية
        bg = tk.Frame(win, bg="#1565C0")
        bg.pack(fill="both", expand=True)

        tk.Label(bg, text="🔐 DarbStu",
                 bg="#1565C0", fg="white",
                 font=("Tahoma",18,"bold")).pack(pady=(28,4))
        tk.Label(bg, text="نظام إدارة الغياب والتأخر",
                 bg="#1565C0", fg="#90CAF9",
                 font=("Tahoma",11)).pack(pady=(0,20))

        # بطاقة بيضاء
        card = tk.Frame(bg, bg="white", padx=28, pady=24)
        card.pack(fill="x", padx=24)

        # رسالة الحالة
        msg = self.status.get("msg","")
        days_left = self.status.get("days_left",0)

        if not self.status.get("valid"):
            tk.Label(card, text="⛔ " + msg,
                     bg="white", fg="#C62828",
                     font=("Tahoma",11,"bold"),
                     wraplength=380).pack(pady=(0,16))
        else:
            tk.Label(card, text="⚠️ متبقي {} يوم فقط على انتهاء الاشتراك".format(days_left),
                     bg="white", fg="#E65100",
                     font=("Tahoma",11,"bold")).pack(pady=(0,16))

        tk.Label(card, text="أدخل مفتاح الترخيص:",
                 bg="white", fg="#374151",
                 font=("Tahoma",10)).pack(anchor="e")

        self.key_var = tk.StringVar()
        key_entry = ttk.Entry(card, textvariable=self.key_var,
                              width=32, justify="center",
                              font=("Tahoma",11))
        key_entry.pack(pady=6, ipady=4)
        key_entry.focus()

        self.status_lbl = tk.Label(card, text="",
                                    bg="white", font=("Tahoma",9))
        self.status_lbl.pack(pady=(0,8))

        btn = tk.Button(card,
            text="✅ تفعيل البرنامج",
            bg="#1565C0", fg="white",
            font=("Tahoma",11,"bold"),
            relief="flat", padx=20, pady=8, cursor="hand2",
            command=self._activate)
        btn.pack()

        # رابط تواصل
        tk.Label(bg,
            text="للاشتراك والتجديد: تواصل مع مزوّد البرنامج",
            bg="#1565C0", fg="#90CAF9",
            font=("Tahoma",9)).pack(pady=14)

        self.win = win
        key_entry.bind("<Return>", lambda e: self._activate())

    def _activate(self):
        key = self.key_var.get().strip()
        if not key:
            self.status_lbl.config(text="أدخل المفتاح أولاً", fg="#C62828")
            return
        self.status_lbl.config(text="⏳ جارٍ التفعيل...", fg="#1565C0")
        self.win.update_idletasks()

        import threading as _th
        def _run():
            ok, msg = activate_license(key)
            def _done():
                if ok:
                    self.status_lbl.config(text="✅ " + msg, fg="#2E7D32")
                    self.win.after(1200, self._on_activated)
                else:
                    self.status_lbl.config(text="❌ " + msg, fg="#C62828")
            self.win.after(0, _done)
        _th.Thread(target=_run, daemon=True).start()

    def _on_activated(self):
        self.win.destroy()
        if self.on_success:
            self.on_success()


# ═══════════════════════════════════════════════════════════════
# رموز تفعيل بوابة النتائج — أحادية الاستخدام
# ═══════════════════════════════════════════════════════════════

import secrets as _secrets
import string  as _string

def generate_tokens(count: int = 1, note: str = "") -> List[str]:
    """يولّد رموز تفعيل عشوائية ويحفظها في DB."""
    CHARS = _string.ascii_uppercase + _string.digits
    # استبعد الأحرف المتشابهة بصرياً
    CHARS = CHARS.replace("0","").replace("O","").replace("I","").replace("1","")
    tokens = []
    con = get_db(); cur = con.cursor()
    for _ in range(count):
        while True:
            # صيغة XXXX-XXXX
            raw   = "".join(_secrets.choice(CHARS) for _ in range(8))
            token = raw[:4] + "-" + raw[4:]
            # تأكد من عدم التكرار
            cur.execute("SELECT id FROM result_tokens WHERE token=?", (token,))
            if not cur.fetchone():
                break
        cur.execute("""INSERT INTO result_tokens (token, created_at, note)
                       VALUES (?,?,?)""",
                    (token, datetime.datetime.utcnow().isoformat(), note))
        tokens.append(token)
    con.commit(); con.close()
    return tokens

def consume_token(token: str) -> bool:
    """
    يتحقق من صحة الرمز ويحذفه فوراً.
    يُرجع True إذا كان صحيحاً، False إذا لم يُوجد أو استُخدم.
    """
    token = token.strip().upper()
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM result_tokens WHERE token=?", (token,))
    deleted = cur.rowcount
    con.commit(); con.close()
    return deleted > 0

def get_tokens_count() -> int:
    """عدد الرموز المتبقية."""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM result_tokens")
    count = cur.fetchone()[0]
    con.close()
    return count

def get_all_tokens() -> List[Dict]:
    """يُرجع كل الرموز المتبقية."""
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM result_tokens ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

def delete_all_tokens():
    """يحذف كل الرموز (إعادة ضبط)."""
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM result_tokens")
    con.commit(); con.close()


# ═══════════════════════════════════════════════════════════════
# نظام الترخيص — شاشة التفعيل
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# نظام الترخيص — مضمّن مباشرة
# ═══════════════════════════════════════════════════════════════

import os, json, base64, datetime, ssl
import urllib.request, urllib.error

# ═══════════════════════════════════════════════════════════════
#  نظام التراخيص — تذاكر موقّعة من سيرفر DarbStu
# ═══════════════════════════════════════════════════════════════
# البرنامج يطلب "تذكرة ترخيص" من السيرفر ويتحقق من توقيعها بالمفتاح
# العام أدناه. المفتاح الخاص لا يغادر السيرفر إطلاقاً، فلا يستطيع أحد
# تزوير ترخيص حتى لو ملك الكود المصدري كاملاً.
#
# (النظام القديم كان يعتمد على Google Sheet — حُذف الشيت في أغسطس 2026
#  فتوقّف التفعيل كلياً. ولم يعد للنظام أي اعتماد خارجي.)

LICENSE_API   = os.environ.get("DARBSTU_LICENSE_API", "https://darbstu.com/license")

# المفتاح العام لخادم التراخيص (Ed25519, base64) — آمن أن يكون علنياً
LICENSE_PUBKEY = "IPPBJM2OB1Xf1hirk7hH6V8t5CytLliqQhQi5ro8VDc="

LICENSE_FILE   = os.path.join(BASE_DIR, ".darb_license")
TRIAL_FILE     = os.path.join(BASE_DIR, ".darb_trial")
TRIAL_DAYS     = 14

# يعمل البرنامج بلا إنترنت بآخر تذكرة صالحة لهذه المدة قبل أن يطالب بالاتصال
OFFLINE_GRACE_DAYS = 14


def _ssl_ctx():
    """سياق TLS يتحقق من الشهادة — الـ EXE المجمّد لا يرث مخزن شهادات ويندوز."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _verify_ticket(ticket: dict) -> bool:
    """يتحقق من توقيع Ed25519 على التذكرة."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        lic = ticket["license"]
        sig = base64.b64decode(ticket["signature"])
        raw = json.dumps(lic, sort_keys=True, separators=(",", ":")).encode()
        pk = Ed25519PublicKey.from_public_bytes(base64.b64decode(LICENSE_PUBKEY))
        pk.verify(sig, raw)
        return True
    except Exception:
        return False


def _school_id() -> str:
    """معرّف المدرسة من ملف التجهيز الذي أعدّه المزوّد."""
    try:
        import provisioning
        return provisioning.get_tunnel_settings().get("school_id", "")
    except Exception:
        return ""


class LicenseClient:
    """
    واجهة الترخيص. أسماء الدوال محفوظة كما كانت حتى لا تتغيّر بقية الملفات.
    """

    def __init__(self):
        self._cache = self._load_cache()

    # ── معرّف الجهاز ──────────────────────────────────────────
    def _machine_id(self) -> str:
        return _machine_fingerprint()

    # ── كاش محلي ──────────────────────────────────────────────
    def _load_cache(self) -> dict:
        """
        يقرأ الترخيص المحفوظ **بعد التحقق من توقيعه**.

        بدون هذا التحقق يستطيع من يعمل بلا إنترنت أن يفتح الملف ويكتب
        تاريخ انتهاء بعيداً فيحصل على ترخيص دائم. لذلك لا نثق بالحقول
        العلوية إطلاقاً، بل نأخذ القيم من التذكرة الموقّعة وحدها.
        """
        try:
            if not os.path.exists(LICENSE_FILE):
                return {}
            with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            ticket = data.get("ticket")
            if not isinstance(ticket, dict) or not _verify_ticket(ticket):
                print("[LICENSE] ⚠️ ملف الترخيص غير موقّع أو مُعدَّل — يُتجاهل")
                return {}

            lic = ticket.get("license", {})
            data["school_id"]   = lic.get("school_id", "")
            data["school_name"] = lic.get("school_name", "")
            data["status"]      = lic.get("status", "")
            data["expiry"]      = lic.get("expiry", "")
            data["issued"]      = lic.get("issued", "")
            return data
        except Exception:
            return {}

    def _save_cache(self, data: dict):
        try:
            with open(LICENSE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                os.chmod(LICENSE_FILE, 0o600)
            except Exception:
                pass
        except Exception as e:
            print("[LICENSE] تحذير: لم يُحفظ ملف الترخيص:", e)

    # ── جلب تذكرة من السيرفر ──────────────────────────────────
    def fetch(self, timeout: int = 12) -> tuple:
        """
        يجلب تذكرة موقّعة ويحفظها. يُرجع (نجح, رسالة).
        الفشل هنا ليس خطأً قاتلاً — يُستخدم آخر تذكرة محفوظة.
        """
        sid = _school_id()
        if not sid:
            return False, "لم يُجهَّز هذا الجهاز بعد"
        try:
            url = f"{LICENSE_API}/{sid}"
            req = urllib.request.Request(url, headers={"User-Agent": "DarbStu"})
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
                ticket = json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            return False, f"تعذّر الاتصال بخادم التراخيص: {e.reason}"
        except Exception as e:
            return False, f"رد غير صالح من خادم التراخيص: {e}"

        if not _verify_ticket(ticket):
            return False, "تذكرة الترخيص غير موقّعة بشكل صحيح — تواصل مع الدعم"

        lic = ticket["license"]
        if lic.get("school_id") != sid:
            return False, "التذكرة لمدرسة أخرى"

        self._cache = {
            "school_id":   lic.get("school_id", ""),
            "school_name": lic.get("school_name", ""),
            "status":      lic.get("status", ""),
            "expiry":      lic.get("expiry", ""),
            "issued":      lic.get("issued", ""),
            "ticket":      ticket,
            "fetched_at":  datetime.date.today().isoformat(),
            "machine_id":  self._machine_id(),
        }
        self._save_cache(self._cache)
        return True, "تم تحديث الترخيص"

    # ── الحالة ────────────────────────────────────────────────
    def is_activated(self) -> bool:
        return self._days_left() is not None and self._days_left() >= 0

    def _days_left(self):
        exp = self._cache.get("expiry", "")
        if not exp:
            return None
        try:
            return (datetime.date.fromisoformat(exp) - datetime.date.today()).days
        except Exception:
            return None

    def _get_trial(self) -> dict:
        """ينشئ أو يقرأ فترة التجربة المجانية."""
        try:
            if os.path.exists(TRIAL_FILE):
                with open(TRIAL_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"start": datetime.datetime.utcnow().isoformat()}
                with open(TRIAL_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f)
            start = datetime.datetime.fromisoformat(data["start"])
            elapsed = (datetime.datetime.utcnow() - start).days
            left = max(0, TRIAL_DAYS - elapsed)
            return {"valid": left > 0, "days_left": left}
        except Exception:
            return {"valid": True, "days_left": TRIAL_DAYS}

    def check(self) -> tuple:
        """
        يُرجع (صالح, رسالة, معلومات).
        يحدّث التذكرة من السيرفر إن أمكن، ويعمل بلا إنترنت ضمن مهلة السماح.
        """
        # حدّث بصمت (لا يفشل الفحص إن انقطع الإنترنت)
        if _school_id():
            self.fetch()

        # الترخيص مربوط بالجهاز الذي فُعِّل عليه
        saved_mid = self._cache.get("machine_id", "")
        if (saved_mid and _machine_id_is_reliable()
                and saved_mid != self._machine_id()):
            return False, ("هذا الترخيص مُفعَّل على جهاز آخر.\n"
                           "للنقل إلى جهاز جديد تواصل مع الدعم."), {}

        status = self._cache.get("status", "")
        days   = self._days_left()
        school = self._cache.get("school_name", "") or self._cache.get("school_id", "")

        if status == "suspended":
            return False, "الاشتراك موقوف — تواصل مع الدعم", {}

        if days is not None and days >= 0:
            # تحقّق من قِدم آخر تذكرة (يمنع تجميد الجهاز بلا إنترنت للأبد)
            try:
                fetched = datetime.date.fromisoformat(self._cache.get("fetched_at", ""))
                offline = (datetime.date.today() - fetched).days
            except Exception:
                offline = 0
            if offline > OFFLINE_GRACE_DAYS:
                return False, (f"تعذّر التحقق من الاشتراك منذ {offline} يوماً.\n"
                               "وصّل الجهاز بالإنترنت ليُحدَّث الترخيص."), {}
            info = dict(self._cache); info["days_left"] = days
            return True, f"✅ الاشتراك فعّال — متبقٍ {days} يوم" + (f" ({school})" if school else ""), info

        if days is not None and days < 0:
            return False, (f"انتهى الاشتراك قبل {-days} يوم.\n"
                           "جدّد الاشتراك لمواصلة استخدام البرنامج."), {}

        # لا ترخيص بعد ⇒ فترة التجربة
        trial = self._get_trial()
        if trial["valid"]:
            return True, "⏳ فترة التجربة — متبقي {} يوم".format(trial["days_left"]), \
                   {"trial": True, "days_left": trial["days_left"]}

        return False, ("انتهت فترة التجربة ({} أيام).\n"
                       "تواصل مع مزوّد النظام لتفعيل الاشتراك.").format(TRIAL_DAYS), {}

    def activate(self, license_key: str = "", school_name: str = "") -> tuple:
        """
        لم يعد التفعيل يتم بمفتاح — يفعّله المزوّد من لوحة الإدارة.
        هذا الزر يعيد الفحص من السيرفر بعد أن يفعّله المزوّد.
        """
        ok, msg = self.fetch()
        if not ok:
            return False, msg, {}
        valid, m, info = self.check()
        return valid, m, info

    # ── معلومات ───────────────────────────────────────────────
    def plan(self) -> str:
        return self._cache.get("plan", "basic")

    def max_students(self) -> int:
        return int(self._cache.get("max_students", 0) or 0)

    def expiry(self) -> str:
        return self._cache.get("expiry", "")


def check_license_on_startup(root=None) -> tuple:
    """يفحص الترخيص من الملف المحلي — بدون إنترنت بعد التفعيل."""
    try:
        client = LicenseClient()
        ok, msg, info = client.check()
        return ok, msg, info, client
    except Exception as e:
        return False, "خطأ في الترخيص: {}".format(e), {}, None


class ActivationWindow:
    """
    شاشة حالة الاشتراك — تظهر عند انتهاء التجربة أو انتهاء الاشتراك.

    لم تعد تطلب مفتاح ترخيص: المزوّد يفعّل الاشتراك من لوحة الإدارة،
    والمدرسة تضغط «تحقّق من الاشتراك» فيُجلب من السيرفر مباشرة.
    """

    _NAVY = "#1a3a5c"
    _BLUE = "#1565C0"

    def __init__(self, root, msg="", on_success=None):
        self.root       = root
        self.on_success = on_success

        self.win = tk.Toplevel(root)
        self.win.title("اشتراك DarbStu")
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.lift()
        self.win.focus_force()
        self.win.attributes("-topmost", True)

        W, H = 500, 420
        self.win.update_idletasks()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"{W}x{H}+{(sw-W)//2}+{max(0,(sh-H)//2)}")
        # إغلاق النافذة = إغلاق البرنامج (لا يعمل بلا اشتراك)
        self.win.protocol("WM_DELETE_WINDOW", root.destroy)

        # ── رأس ──────────────────────────────────────────────
        hdr = tk.Frame(self.win, bg=self._NAVY, height=76)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🔐  اشتراك DarbStu", bg=self._NAVY, fg="white",
                 font=("Tahoma", 15, "bold")).pack(pady=(16, 0))
        tk.Label(hdr, text="نظام إدارة الغياب والتأخر",
                 bg=self._NAVY, fg="#90CAF9",
                 font=("Tahoma", 9)).pack()

        body = tk.Frame(self.win, bg="white", padx=26, pady=18)
        body.pack(fill="both", expand=True)

        # ── سبب التوقّف ───────────────────────────────────────
        tk.Label(body, text="⛔  " + (msg or "الاشتراك غير مفعّل"),
                 bg="white", fg="#C62828", font=("Tahoma", 11, "bold"),
                 wraplength=430, justify="right").pack(pady=(0, 14))

        # ── هوية المدرسة (تفيد الدعم) ─────────────────────────
        sid = _school_id()
        if sid:
            box = tk.Frame(body, bg="#e8f0fe", padx=12, pady=8)
            box.pack(fill="x", pady=(0, 12))
            tk.Label(box, text="معرّف مدرستك", bg="#e8f0fe", fg="#37474f",
                     font=("Tahoma", 8), anchor="e").pack(fill="x")
            tk.Label(box, text=sid, bg="#e8f0fe", fg="#0d47a1",
                     font=("Consolas", 13, "bold"), anchor="e").pack(fill="x")
        else:
            tk.Label(body,
                     text="⚠️  لم يُجهَّز هذا الجهاز بعد.\n"
                          "تواصل مع مزوّد النظام لتجهيزه.",
                     bg="white", fg="#E65100", font=("Tahoma", 10),
                     justify="right").pack(pady=(0, 12))

        tk.Label(body,
                 text="بعد أن يفعّل المزوّد اشتراكك، اضغط الزر أدناه.",
                 bg="white", fg="#546e7a", font=("Tahoma", 9),
                 wraplength=430, justify="right").pack(pady=(0, 8))

        self.status_lbl = tk.Label(body, text="", bg="white",
                                   font=("Tahoma", 9), wraplength=430,
                                   justify="right")
        self.status_lbl.pack(pady=(0, 10))

        row = tk.Frame(body, bg="white")
        row.pack()
        self.btn = tk.Button(row, text="  🔄  تحقّق من الاشتراك  ",
                             bg=self._BLUE, fg="white",
                             font=("Tahoma", 11, "bold"),
                             relief="flat", padx=18, pady=9, cursor="hand2",
                             command=self._recheck)
        self.btn.pack(side="right", padx=4)

        # لو وُضع ملف التجهيز في مجلد خاطئ، يختاره المستخدم يدوياً
        tk.Button(row, text="  📂  ملف التجهيز  ",
                  bg="#546e7a", fg="white", font=("Tahoma", 10),
                  relief="flat", padx=14, pady=9, cursor="hand2",
                  command=self._pick_provision).pack(side="right", padx=4)

        tk.Label(body, text="للاشتراك والتجديد تواصل مع مزوّد النظام",
                 bg="white", fg="#90a4ae", font=("Tahoma", 8)).pack(pady=(14, 0))

        self.win.bind("<Return>", lambda e: self._recheck())

    # ── اختيار ملف التجهيز يدوياً ─────────────────────────────
    def _pick_provision(self):
        """
        يسمح باختيار provision.json من أي مكان ثم يطبّقه.
        يعالج الحالة الشائعة: وضعه في مجلد اختصارات قائمة ابدأ بدل
        مجلد البرنامج (كلاهما اسمه DarbStu تحت AppData).
        """
        from tkinter import filedialog
        import shutil
        path = filedialog.askopenfilename(
            parent=self.win, title="اختر ملف تجهيز المدرسة",
            filetypes=[("ملف التجهيز", "*.json"), ("كل الملفات", "*.*")])
        if not path:
            return
        try:
            import provisioning
            dest = os.path.join(provisioning.BASE_DIR, "provision.json")
            if os.path.abspath(path) != os.path.abspath(dest):
                shutil.copyfile(path, dest)
            info = provisioning.apply_provision_file()
        except Exception as e:
            self.status_lbl.config(text=f"❌  تعذّر تطبيق الملف: {e}", fg="#C62828")
            return

        if not info:
            self.status_lbl.config(
                text="❌  الملف غير صالح أو ناقص — تأكد أنه ملف التجهيز الصحيح",
                fg="#C62828")
            return

        self.status_lbl.config(
            text=f"✅  جُهِّز الجهاز: {info.get('domain','')} — جارٍ التحقق...",
            fg="#2E7D32")
        self.win.after(600, self._recheck)

    # ── إعادة الفحص من السيرفر ────────────────────────────────
    def _recheck(self):
        self.btn.config(state="disabled")
        self.status_lbl.config(text="⏳  جارٍ التحقق من السيرفر...", fg=self._BLUE)
        self.win.update_idletasks()

        def _run():
            try:
                client = LicenseClient()
                ok, msg, _info = client.check()
            except Exception as e:
                ok, msg = False, f"تعذّر التحقق: {e}"

            def _done():
                if ok:
                    self.status_lbl.config(text="✅  " + msg.replace("\n", " "),
                                           fg="#2E7D32")
                    self.win.after(1200, self._activated)
                else:
                    self.status_lbl.config(text="❌  " + msg.replace("\n", " "),
                                           fg="#C62828")
                    self.btn.config(state="normal")
            self.win.after(0, _done)

        threading.Thread(target=_run, daemon=True).start()

    def _activated(self):
        try:
            self.win.grab_release()
            self.win.destroy()
        except Exception:
            pass
        if self.on_success:
            self.on_success()
