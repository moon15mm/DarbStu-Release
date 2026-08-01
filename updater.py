# -*- coding: utf-8 -*-
"""
updater.py — نظام التحديث التلقائي (متعدد الملفات)
يحمّل حزمة ZIP من GitHub ويستبدل ملفات الكود فقط،
دون المساس بمجلد data أو my-whatsapp-server أو أي بيانات مستخدم.
"""
import os, sys, io, zipfile, shutil, threading, subprocess, ssl
import base64, hashlib, hmac, json
import urllib.request
import tkinter as tk
from tkinter import ttk
import constants
from constants import APP_VERSION, BASE_DIR


def _build_ssl_context():
    """
    سياق TLS يتحقق من الشهادات فعلياً.

    التحديث ينزّل ملفات .py ثم يُنفِّذها بعد إعادة التشغيل، فتعطيل التحقق
    يعني أن اعتراض الاتصال = تنفيذ كود عن بُعد على أجهزة كل المدارس.
    الـ EXE المجمّد لا يرث مخزن شهادات النظام، لذا نستخدم حزمة certifi
    التي يجمعها PyInstaller مع requests.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        # مخزن النظام — يعمل عند التشغيل من المصدر
        return ssl.create_default_context()


_SSL_CTX = _build_ssl_context()

# لا رابط احتياطي هنا عمداً. كان `_ZIP_FALLBACK` يسحب من GitHub بلا
# توقيع كلما نقص حقل في البيان — أي أن كل الحماية تسقط بحذف سطر من
# ملف JSON على استضافة يملكها غيرنا. مصدر الحزمة اليوم يأتي من البيان
# الموقَّع وحده، وغيابه يعني رفض التحديث لا اللجوء إلى مصدر أضعف.

# المسارات المحمية — لن تُلمس أثناء التحديث
_PROTECTED = {
    "data", "my-whatsapp-server", "my-whatsapp-server/",
    "__pycache__", ".git", ".github",
    "Output", "build", "dist",
}

# ملفات جذر المشروع المحمية (أسرار التثبيت وبيانات الترخيص)
_PROTECTED_ROOT_FILES = {
    ".darb_license",
    ".darb_trial",
    ".darb_keys.json",    # أسرار JWT والباصات — فريدة لكل جهاز
    ".darb_init_admin",
    "license.dat",        # الاسم الفعلي لملف الترخيص (license_manager.LICENSE_FILE)
}

# الامتدادات التي يجب تحديثها
_UPDATE_EXTS = {".py", ".txt", ".json", ".iss", ".bat", ".spec", ".ico", ".html"}

# ملفات JSON التي يجب تجاهلها (بيانات مستخدم)
_SKIP_FILES = {
    "data/config.json",
    "data/students.json",
    "data/users.json",
    "data/teachers.json",
}


def _get_installed_version() -> str:
    """
    يقرأ الإصدار الفعلي من version.json المحلي إن وُجد،
    لأن الـ EXE يحتوي APP_VERSION مجمّداً ولا يتحدث بعد التحديث.
    """
    try:
        import json as _j
        vfile = os.path.join(BASE_DIR, "version.json")
        if os.path.exists(vfile):
            with open(vfile, "r", encoding="utf-8") as f:
                local_ver = _j.load(f).get("version", APP_VERSION)
            def _v(v):
                try: return tuple(int(x) for x in str(v).split("."))
                except: return (0,)
            if _v(local_ver) >= _v(APP_VERSION):
                return local_ver
    except Exception:
        pass
    return APP_VERSION


# ═══════════════════════════════════════════════════════════════
#  القناة الموقَّعة
# ═══════════════════════════════════════════════════════════════
# التحديث يكتب ملفات .py تُنفَّذ فوراً — أي أنه قناة تنفيذ كود عن بُعد.
# بلا توقيع، يكفي أن يملك أحدهم المستودع ليُشغّل ما يشاء على كل جهاز
# مدرسة. التوقيع ينقل الثقة من «من يملك الاستضافة» إلى «من يملك
# المفتاح الخاص» — وهو لا يغادر خادم darbstu.com.


class UpdateRejected(Exception):
    """رُفض التحديث لسبب أمني — لا يُكتب أي ملف."""


def _verify_manifest(obj: dict) -> dict:
    """
    يتحقق من توقيع Ed25519 على البيان ويُرجع محتواه.
    أي خلل — مفتاح ناقص، توقيع فاسد، حقل مفقود — يرفع استثناءً.
    """
    pubkey = (getattr(constants, "UPDATE_PUBKEY", "") or "").strip()
    if not pubkey:
        raise UpdateRejected("لم يُضبط مفتاح التحقق — التحديث التلقائي معطّل")

    if not isinstance(obj, dict) or "update" not in obj or "signature" not in obj:
        raise UpdateRejected("البيان لا يحمل توقيعاً")

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    payload = obj["update"]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    try:
        pk = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey))
        pk.verify(base64.b64decode(obj["signature"]), raw)
    except Exception:
        raise UpdateRejected("التوقيع غير صالح — قد تكون الحزمة مُبدَّلة")

    for field in ("version", "download_url", "sha256"):
        if not payload.get(field):
            raise UpdateRejected(f"البيان ناقص: {field}")
    if not str(payload["download_url"]).lower().startswith("https://"):
        raise UpdateRejected("رابط التحميل ليس https")
    return payload


def _fetch_signed_manifest(timeout=10) -> dict:
    """يجلب البيان الموقَّع من خادم المزوّد ويتحقق منه."""
    url = getattr(constants, "UPDATE_MANIFEST_URL", "") or ""
    if not url:
        raise UpdateRejected("لم يُضبط عنوان البيان")
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=_SSL_CTX) as r:
            data = json.loads(r.read().decode("utf-8"))
    except UpdateRejected:
        raise
    except Exception as e:
        raise UpdateRejected(f"تعذّر جلب البيان: {e}")
    return _verify_manifest(data)


def _check_signed(silent=True):
    """
    يُرجع (payload, هل يوجد أحدث) أو يرفع UpdateRejected.
    الرفض يعني: لا يُلمس ملف واحد.
    """
    payload = _fetch_signed_manifest()
    latest = payload["version"]

    def _v(v):
        return tuple(int(x) for x in str(v).split("."))

    return payload, _v(latest) > _v(_get_installed_version())


def check_for_updates(root_widget=None, silent=True):
    """
    يتحقق من وجود إصدار جديد على GitHub.
    silent=True : يُخطر فقط عند وجود تحديث.
    silent=False: يُظهر النتيجة دائماً.
    """
    def _check():
        try:
            payload, newer = _check_signed(silent)
            if newer:
                if root_widget:
                    root_widget.after(0, lambda: _show_update_dialog(
                        payload["version"], payload.get("notes", ""), payload))
            else:
                if not silent and root_widget:
                    root_widget.after(0, _show_no_update_dialog)
        except Exception as e:
            print(f"[UPDATE] رُفض/تعذّر: {e}")
            if not silent and root_widget:
                root_widget.after(0, lambda: _show_error_dialog(str(e)))

    threading.Thread(target=_check, daemon=True).start()


def _auto_update(latest, dl_url, win=None, status_lbl=None, btn=None):
    """
    يحمّل حزمة ZIP للمشروع، يستخرج ملفات الكود فقط،
    ثم يعيد تشغيل التطبيق تلقائياً.
    """
    import json as _j, time

    def _ui(text, color="#1565C0"):
        print(f"[UPDATE] {text}")
        if status_lbl:
            try:
                status_lbl.config(text=text, foreground=color)
                if win: win.update_idletasks()
            except Exception:
                pass

    try:
        if btn: btn.config(state="disabled")

        # ١. تحديد رابط التحميل
        # dl_url صار البيان الموقَّع كاملاً — لا رابطاً مجرّداً
        if not isinstance(dl_url, dict):
            raise UpdateRejected("تحديث غير موقَّع — رُفض")
        manifest = dl_url
        url = manifest["download_url"]

        _ui("⬇️  جارٍ تحميل التحديث...")

        # ٢. تحميل ملف ZIP
        with urllib.request.urlopen(url, timeout=90, context=_SSL_CTX) as resp:
            zip_bytes = resp.read()

        # ٣. البصمة قبل أي كتابة. البيان موقَّع، فالبصمة داخله موثوقة،
        #    وأي عبث بالحزمة على الاستضافة يظهر هنا ويُوقف كل شيء.
        _ui("🔐  جارٍ التحقق من التوقيع...")
        actual = hashlib.sha256(zip_bytes).hexdigest()
        expected = str(manifest["sha256"]).lower().strip()
        if not hmac.compare_digest(actual, expected):
            raise UpdateRejected("بصمة الحزمة لا تطابق البيان — أُوقف التحديث")
        size = manifest.get("size")
        if size and int(size) != len(zip_bytes):
            raise UpdateRejected("حجم الحزمة لا يطابق البيان")

        _ui("📦  جارٍ تثبيت الملفات...")

        # ٣. استخراج الملفات من ZIP
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            prefix = ""
            if names:
                top = names[0].split("/")[0]
                if all(n.startswith(top + "/") or n == top + "/" for n in names[:5]):
                    prefix = top + "/"

            updated = 0
            skipped = 0
            for item in names:
                rel = item[len(prefix):] if prefix and item.startswith(prefix) else item
                if not rel or rel.endswith("/"): continue
                top_dir = rel.split("/")[0]
                if top_dir in _PROTECTED:
                    skipped += 1; continue
                if rel in _SKIP_FILES:
                    skipped += 1; continue
                if rel in _PROTECTED_ROOT_FILES:
                    skipped += 1; continue
                ext = os.path.splitext(rel)[1].lower()
                if ext not in _UPDATE_EXTS:
                    skipped += 1; continue

                dest = os.path.join(BASE_DIR, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(item) as src:
                    content = src.read()
                with open(dest, "wb") as dst:
                    dst.write(content)
                updated += 1

        _ui(f"✅  تم تحديث {updated} ملف — سيُعاد التشغيل...", "green")
        time.sleep(2)

        # ٤. إعادة التشغيل — نستخدم batch script حتى لا يتعارض القفل
        if getattr(sys, 'frozen', False):
            exe = sys.executable
        else:
            exe = os.path.join(BASE_DIR, "main.py")

        if sys.platform == "win32":
            # نكتب ملف bat مؤقت يأخذ 4 ثوان للتأكد أن العملية القديمة أغلقت تماماً
            restart_bat = os.path.join(BASE_DIR, "_darb_restart.bat")
            with open(restart_bat, "w", encoding="utf-8") as _f:
                _f.write(f'@echo off\ntimeout /t 4 /nobreak > nul\nstart "" "{exe}"\ndel "%~f0"\n')
            subprocess.Popen(
                [restart_bat],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                cwd=BASE_DIR,
                shell=True
            )
        else:
            time.sleep(4)
            subprocess.Popen([sys.executable, exe], cwd=BASE_DIR)

        if win:
            try: win.destroy()
            except: pass

        try:
            import tkinter as _tk
            if _tk._default_root:
                _tk._default_root.quit()
        except:
            pass
        os._exit(0)

    except Exception as e:
        _ui(f"❌  فشل التحديث: {e}", "red")
        if btn: btn.config(state="normal")


def perform_silent_update(root_widget, latest, notes, dl_url):
    """تحديث صامت تماماً — تنزيل وتثبيت وإعادة تشغيل بدون أي نافذة."""
    threading.Thread(
        target=_auto_update,
        args=(latest, dl_url, None, None, None),
        daemon=True
    ).start()


def trigger_immediate_update():
    """
    يُنفَّذ من الـ API (بدون واجهة رسومية) — يتحقق من GitHub ويُحدِّث فوراً إن وُجد إصدار جديد.
    يُرجع (True, latest_version) عند نجاح التحديث، أو (False, reason) عند الفشل.
    """
    try:
        payload, newer = _check_signed()
        latest = payload["version"]
        current = _get_installed_version()

        if not newer:
            return False, f"الإصدار الحالي ({current}) هو الأحدث — لا يوجد تحديث"

        print(f"[IMMEDIATE-UPDATE] 🚀 بدء التحديث الفوري {current} → {latest}")
        # يعمل في thread مستقل — البرنامج سيُعاد تشغيله بعد التحديث
        threading.Thread(target=_auto_update, args=(latest, payload, None, None, None),
                         daemon=True).start()
        return True, latest

    except UpdateRejected as e:
        print(f"[IMMEDIATE-UPDATE] ⛔ {e}")
        return False, str(e)
    except Exception as e:
        return False, str(e)


def schedule_auto_update(root_widget):
    """جدولة فحص التحديثات التلقائي يومياً في ساعة محددة (بدقة متناهية)."""
    import datetime

    def _run_update_check():
        """ينفذ فحص التحديث الآن ثم يجدول الفحص التالي."""
        from config_manager import load_config
        cfg = load_config()
        if not cfg.get("auto_update_enabled", False):
            _schedule_next()
            return
        try:
            # هذا المسار يُثبّت بلا سؤال المستخدم، فهو الأولى بالتحقق.
            payload, newer = _check_signed()
            if newer:
                latest = payload["version"]
                print(f"[AUTO-UPDATE] إصدار جديد موقَّع {latest} — جارٍ التثبيت...")
                root_widget.after(0, lambda: perform_silent_update(
                    root_widget, latest, payload.get("notes", ""), payload))
                return  # البرنامج سيُعاد تشغيله — لا نجدول مرة أخرى
            print(f"[AUTO-UPDATE] الإصدار محدّث ({_get_installed_version()})")
        except UpdateRejected as e:
            print(f"[AUTO-UPDATE] ⛔ رُفض التحديث: {e}")
        except Exception as e:
            print(f"[AUTO-UPDATE-ERROR] {e}")
        _schedule_next()

    def _schedule_next():
        """يحسب الوقت المتبقي حتى الساعة المستهدفة ويجدوله بدقة."""
        from config_manager import load_config
        cfg = load_config()
        target_hour = cfg.get("auto_update_hour", 0)  # الافتراضي: منتصف الليل (00:00)
        now = datetime.datetime.now()
        target = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        delay_ms = int((target - now).total_seconds() * 1000)
        print(f"[AUTO-UPDATE] الفحص التالي: {target.strftime('%Y-%m-%d %H:%M')} (بعد {delay_ms/3600000:.1f} ساعة)")
        root_widget.after(delay_ms, _run_update_check)

    # ابدأ الجدولة بعد دقيقتين من التشغيل
    root_widget.after(120_000, _schedule_next)


def _show_update_dialog(latest, notes, dl_url):
    """نافذة الإشعار بوجود تحديث مع زر تحديث تلقائي."""
    win = tk.Toplevel()
    win.title("🎉 يوجد تحديث جديد")
    win.geometry("480x320")
    win.resizable(False, False)
    win.grab_set()
    win.lift()
    win.attributes("-topmost", True)

    hdr = tk.Frame(win, bg="#1565C0", height=60)
    hdr.pack(fill="x"); hdr.pack_propagate(False)
    tk.Label(hdr, text="🎉  يوجد إصدار جديد من DarbStu",
             bg="#1565C0", fg="white",
             font=("Tahoma", 12, "bold")).pack(expand=True)

    body = ttk.Frame(win, padding=20); body.pack(fill="both", expand=True)

    ttk.Label(body, text=f"الإصدار الحالي:  {_get_installed_version()}",
              font=("Tahoma", 10), foreground="#666").pack(anchor="e")
    ttk.Label(body, text=f"الإصدار الجديد:  {latest}",
              font=("Tahoma", 11, "bold"), foreground="#1565C0").pack(anchor="e", pady=(2, 8))

    if notes:
        ttk.Label(body, text="ما الجديد:", font=("Tahoma", 9, "bold")).pack(anchor="e")
        ttk.Label(body, text=notes, font=("Tahoma", 9),
                  foreground="#333", wraplength=420, justify="right").pack(anchor="e", pady=(0, 10))

    status_lbl = ttk.Label(body, text="", font=("Tahoma", 9))
    status_lbl.pack(anchor="e", pady=(0, 8))

    btn_row = ttk.Frame(body); btn_row.pack(fill="x")

    auto_btn = tk.Button(btn_row, text="⚡  تحديث تلقائي (موصى به)",
                         bg="#1565C0", fg="white",
                         font=("Tahoma", 10, "bold"),
                         relief="flat", cursor="hand2", pady=8)
    auto_btn.pack(side="right", padx=4)
    auto_btn.config(command=lambda: threading.Thread(
        target=_auto_update,
        args=(latest, dl_url, win, status_lbl, auto_btn),
        daemon=True).start())

    ttk.Button(btn_row, text="لاحقاً", command=win.destroy).pack(side="right", padx=4)


def _show_no_update_dialog():
    from tkinter import messagebox
    messagebox.showinfo("التحديث", f"✅  أنت تستخدم أحدث إصدار ({_get_installed_version()})")


def _show_error_dialog(err):
    from tkinter import messagebox
    messagebox.showwarning("التحديث", "تعذّر التحقق من التحديثات:\n" + err)
