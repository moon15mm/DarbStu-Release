import os, sys, socket
import tkinter as tk
from tkinter import messagebox

# ─── freeze_support أولاً — قبل أي شيء آخر ───────────────────────
# على ويندوز تُنشئ multiprocessing عملياتها الفرعية بإعادة تنفيذ هذا
# الملف من أوّله. فإن لم تُستدعَ هنا، مرّت العملية الفرعية على قفل
# النسخة الواحدة أسفله، فوجدت قفل أبيها، فعرضت «البرنامج يعمل بالفعل»
# وأنهت نفسها — بينما المستخدم لم يفتح إلا نسخة واحدة.
# كانت تُستدعى في نهاية الملف داخل __main__، وهذا متأخّر جداً:
# العملية الفرعية لا تصل إلى هناك أصلاً.
if sys.platform == 'win32':
    try:
        import multiprocessing
        multiprocessing.freeze_support()
    except Exception:
        pass

# ─── منع ازدواجية التطبيق ────────────────────────────────────────
# كان القفل يحجز منفذاً ثابتاً (59124) ويعتبر أي فشل في الحجز «نسخة
# تعمل». وهذا يُنتج إنذاراً كاذباً يمنع تشغيل البرنامج نهائياً كلما:
#   • حجز تطبيق آخر المنفذ نفسه
#   • وقع المنفذ في نطاق تحجزه ويندوز لـ Hyper-V أو WSL أو Docker
#     (netsh int ipv4 show excludedportrange) — يختلف من جهاز لآخر
#   • بقي سوكيت عالقاً بعد إنهاء غير نظيف
# المستخدم يرى «أغلق النسخة المفتوحة» ولا يجد نسخةً يُغلقها.
#
# المُزامِن المُسمّى هو الآلية الصحيحة في ويندوز: فريد لتطبيقنا، ويحرّره
# النظام تلقائياً عند موت العملية مهما كانت طريقة الإنهاء.

def _live_sibling_pids():
    """
    PIDs لعمليات أخرى تعمل من نفس ملف البرنامج ونفس المجلد.

    المُزامِن وحده لا يكفي دليلاً. هو يقول «مقبض بهذا الاسم مفتوح في
    مكان ما» — وقد يكون في جلسة مستخدم آخر، أو في عملية معلّقة، أو في
    عملية فرعية تُعيد تنفيذ الملف. أما وجود عملية حيّة من نفس المجلد
    فأمرٌ يُرى بالعين ولا يحتمل التأويل: نفس المجلد = نفس قاعدة البيانات
    = تعارض حقيقي. ومجلد آخر = مدرسة أخرى = لا شأن لنا به.
    """
    if not getattr(sys, 'frozen', False):
        return []                      # وضع التطوير — لا فحص
    try:
        import ctypes
        from ctypes import wintypes

        me = os.path.normcase(os.path.abspath(sys.executable))
        my_dir = os.path.dirname(me)
        my_name = os.path.basename(me)
        my_pid = os.getpid()

        class ENTRY(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD),
                        ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD),
                        ("szExeFile", wintypes.WCHAR * 260)]

        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        snap = k32.CreateToolhelp32Snapshot(2, 0)   # TH32CS_SNAPPROCESS
        if snap == -1:
            return []

        found = []
        e = ENTRY()
        e.dwSize = ctypes.sizeof(ENTRY)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            pid = e.th32ProcessID
            if pid != my_pid and e.szExeFile.lower() == my_name.lower():
                # PROCESS_QUERY_LIMITED_INFORMATION — يعمل بلا صلاحيات مدير
                h = k32.OpenProcess(0x1000, False, pid)
                if h:
                    buf = ctypes.create_unicode_buffer(32768)
                    n = wintypes.DWORD(32768)
                    if k32.QueryFullProcessImageNameW(h, 0, buf,
                                                      ctypes.byref(n)):
                        p = os.path.normcase(os.path.abspath(buf.value))
                        if os.path.dirname(p) == my_dir:
                            found.append(pid)
                    k32.CloseHandle(h)
                # تعذّر فتح العملية (جلسة مستخدم آخر مثلاً): لا نحتسبها.
                # منعُ المستخدم بناءً على شيء لم نتحقّق منه هو بالضبط
                # العطل الذي نُصلحه.
            ok = k32.Process32NextW(snap, ctypes.byref(e))
        k32.CloseHandle(snap)
        return found
    except Exception:
        return []


def ensure_single_instance():
    """
    يُرجع مقبض القفل، ولا يمنع التشغيل إلا بدليل قاطع.

    القاعدة: لا نُغلق الباب في وجه المستخدم إلا إذا رأينا عمليةً حيّة
    من نفس المجلد. المُزامِن يكسر تسابُق التشغيل المتزامن فقط.
    """
    handle = None
    running = False

    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            ERROR_ALREADY_EXISTS = 183
            k32 = ctypes.WinDLL('kernel32', use_last_error=True)
            k32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL,
                                         wintypes.LPCWSTR]
            k32.CreateMutexW.restype = wintypes.HANDLE
            handle = k32.CreateMutexW(None, False, 'Global\\DarbStu_SingleInstance')
            running = (ctypes.get_last_error() == ERROR_ALREADY_EXISTS)
        except Exception:
            # تعذّر المُزامِن — لا نمنع التشغيل بسببه
            return None
    else:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', 59124))
            return s
        except socket.error:
            running = True

    if not running:
        return handle

    # المُزامِن قال «موجود». نتحقّق: هل ثمّة عملية حقيقية فعلاً؟
    pids = _live_sibling_pids()
    if not pids:
        # قفل بلا عملية: بقايا، أو جلسة أخرى، أو عملية فرعية. نُكمل.
        return handle

    root_tmp = tk.Tk()
    root_tmp.withdraw()
    messagebox.showwarning(
        "البرنامج يعمل بالفعل",
        "هناك نسخة من البرنامج تعمل الآن (رقم العملية: %s).\n\n"
        "قد تكون مخفية — جرّب الضغط على  Ctrl + Alt + S  لإظهارها.\n\n"
        "وإن لم تظهر: افتح إدارة المهام (Ctrl+Shift+Esc) وابحث عن\n"
        "DarbStu.exe  ثم أنهِ المهمة، وأعد التشغيل."
        % "، ".join(str(p) for p in pids))
    root_tmp.destroy()
    sys.exit(0)


def _close_splash(root=None):
    """
    يُغلق شاشة البدء التي يعرضها مُحمّل PyInstaller.

    تُستدعى عند جاهزية النافذة، وعند أي خروج أو انهيار — فشاشة عالقة
    بلا نافذة خلفها أسوأ من لا شاشة: يظنّ المستخدم أن البرنامج معلَّق.
    آمنة للاستدعاء أكثر من مرة، وفي وضع التطوير حيث لا وجود لـpyi_splash.
    """
    if root is not None:
        try:
            root.update()      # ارسم النافذة أولاً حتى لا تُخلّف فراغاً
        except Exception:
            pass
    try:
        import pyi_splash
        if pyi_splash.is_alive():
            pyi_splash.close()
    except Exception:
        pass


_app_lock = ensure_single_instance()
# ─────────────────────────────────────────────────────────────

# ─── تجاوز الملفات المدمجة في EXE (تفعيل التحديثات الخارجية) ────────
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

# ملفات .py السائبة بجانب البرنامج تسبق الكود المجمّد داخل الـ EXE — وهذا
# مقصود ليعمل التحديث التلقائي. لكن بعد تثبيت نسخة جديدة فوق نسخة قديمة تبقى
# ملفات النسخة القديمة فتُظلّل الجديدة ويتعطّل البرنامج بخطأ ImportError.
# لذا: لا نُفعّلها إلا إذا كانت أحدث من الـ EXE نفسه.
_use_loose = True
if getattr(sys, 'frozen', False):
    try:
        _probe = os.path.join(_BASE, 'constants.py')
        if os.path.exists(_probe):
            if os.path.getmtime(_probe) < os.path.getmtime(sys.executable) - 5:
                _use_loose = False
                print("[BOOT] ملفات كود قديمة بجانب البرنامج — تُتجاهل، "
                      "ويُستخدم الكود المدمج في النسخة الحالية")
    except Exception:
        pass

if _use_loose and _BASE not in sys.path:
    sys.path.insert(0, _BASE)
# ──────────────────────────────────────────────────────────────────

# ─── معالج الإعداد الأولي ─────────────────────────────────────────
# يجب أن يعمل قبل أي استيراد لـ constants أو api حتى تقرأ الثوابت
# (STATIC_DOMAIN, CLOUDFLARE_DOMAIN) الدومين المحفوظ من أول استيراد.
def _early_setup():
    # ملف التجهيز يُطبَّق دائماً — حتى لو اكتمل الإعداد سابقاً.
    # هذا يغطي حالة ترقية جهاز قديم: الإعداد مكتمل ولا شاشة تظهر، لكن
    # الجهاز يحتاج بيانات النفق. لو تُرك التطبيق داخل شاشة الإعداد وحدها
    # لتُجوهل provision.json على كل جهاز مثبَّت مسبقاً.
    try:
        import provisioning
        provisioning.apply_provision_file()
    except Exception as _e:
        print(f"[SETUP] تعذّر تطبيق ملف التجهيز: {_e}")

    _flag = os.path.join(_BASE, 'data', '.setup_done')
    if os.path.exists(_flag):
        return True
    _r = tk.Tk(); _r.withdraw()
    from setup_wizard import SetupWizard
    w = SetupWizard(_r)
    _r.wait_window(w.win)
    _r.destroy()
    return w.completed

if not _early_setup():
    sys.exit(0)
# ──────────────────────────────────────────────────────────────────

# ─── الاستيرادات الثقيلة (بعد الإعداد — constants يقرأ الدومين الصحيح) ───
import threading, time, datetime, sqlite3
from constants import (PORT, DB_PATH, DATA_DIR, CLOUDFLARE_DOMAIN,
                       MY_STATIC_DOMAIN, BASE_DIR, APP_VERSION,
                       CURRENT_USER, now_riyadh_date, ensure_dirs)
from config_manager import load_config, invalidate_config_cache
from database import get_db, init_db, load_students
from tunnel_manager import start_cloudflare_tunnel, stop_cloudflare_tunnel
from updater import check_for_updates
from license_manager import (check_license, LicenseClient,
                              check_license_on_startup, ActivationWindow)
from api.app import app, register_routers
from gui.login_window import LoginWindow
from gui.app_gui import AppGUI
from alerts_service import (schedule_daily_alerts, schedule_daily_report,
                             send_daily_report_to_admin, schedule_weekly_rewards)
from database import schedule_auto_backup
from api.mobile_routes import _schedule_tardiness_sender
from report_builder import export_to_noor_excel

import multiprocessing
import uvicorn
import asyncio
import atexit
from ttkthemes import ThemedTk
import traceback

# ─── إصلاح asyncio لـ PyInstaller على Windows (ضروري لعمل uvicorn) ──────────
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ─── ملف السجلات لالتقاط الأخطاء الصامتة ────────────────────────────────────
_LOG_FILE = os.path.join(
    (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
     else os.path.dirname(os.path.abspath(__file__))),
    'error.log'
)

def _write_log(msg: str):
    try:
        with open(_LOG_FILE, 'a', encoding='utf-8') as _f:
            _f.write(f"[{datetime.datetime.now()}] {msg}\n{'='*60}\n")
    except Exception:
        pass

def _force_cleanup_at_exit():
    """يُنفَّذ دائماً عند أي خروج (X زر / كراش / Task Manager طبيعي)"""
    import subprocess
    try:
        # النفق يُغلق عبر tunnel_manager (atexit) — لا نقتل ssh.exe عموماً
        # لأن ذلك يقطع جلسات SSH الأخرى للمستخدم.
        from tunnel_manager import stop_cloudflare_tunnel as _stop_t
        _stop_t()
    except Exception:
        pass

atexit.register(_force_cleanup_at_exit)


def _cleanup_environment():
    """تنظيف بيئة العمل عند البدء — يوقف أي عمليات قديمة تتعارض"""
    import subprocess, os
    _nw = dict(creationflags=subprocess.CREATE_NO_WINDOW) if sys.platform == 'win32' else {}

    # الأنفاق المعلّقة يعالجها tunnel_manager بمطابقة منفذ المدرسة وحده
    try:
        pass
        print("[CLEANUP] ✅ جاهز")
    except Exception:
        pass

    # أوقف أي uvicorn/python قديم يحجز المنفذ
    try:
        result = subprocess.check_output(
            ["netstat", "-ano"], encoding="utf-8", errors="replace", **_nw)
        for line in result.splitlines():
            if f":{PORT}" in line and "LISTENING" in line:
                parts = line.split()
                pid = parts[-1] if parts else None
                if pid and pid != str(os.getpid()):
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True, **_nw)
                    print(f"[CLEANUP] ✅ تم تحرير المنفذ {PORT} (PID={pid})")
                    time.sleep(1)
    except Exception:
        pass


def _is_already_running():
    """
    فحص ثانٍ للازدواجية — أُبطل عمداً.

    كان يحجز المنفذ PORT+50 (٨٠٥٠) وله عيب القفل الأول نفسه: أي شيء
    يحجز المنفذ يمنع تشغيل البرنامج بإنذار كاذب. والقفل الحقيقي صار
    مُزامِناً مُسمّى يُنفَّذ عند الاستيراد قبل الوصول إلى هنا، فلا حاجة
    لفحص ثانٍ يُكرّر الخطر نفسه.
    """
    return False, None

def _register_global_hotkey(root):
    """تسجيل اختصار لوحة مفاتيح عالمي (Ctrl+Alt+S و Ctrl+Shift+S) لإظهار/إخفاء البرنامج."""
    if sys.platform != 'win32': return
    import ctypes
    import ctypes.wintypes
    
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    VK_S = 0x53 
    HOTKEY_ID_1 = 1234
    HOTKEY_ID_2 = 1235
    
    user32 = ctypes.windll.user32

    def _toggle_visibility():
        try:
            # التحقق من الحالة الحالية
            is_hidden = root.state() == 'withdrawn' or root.state() == 'iconic' or not root.winfo_viewable()
            
            if is_hidden:
                print("[HOTKEY] >> إظهار النافذة")
                root.deiconify()
                root.state('zoomed')
                root.attributes("-topmost", True)
                root.lift()
                # إزالة topmost بعد فترة قصيرة للسماح بالتفاعل الطبيعي
                root.after(200, lambda: root.attributes("-topmost", False))
                root.focus_force()
            else:
                print("[HOTKEY] >> إخفاء النافذة")
                root.withdraw()
        except Exception as e:
            print(f"[HOTKEY-UI-ERROR] {e}")

    def _listen():
        # تسجيل اختصارين لضمان العمل في بيئات مختلفة
        # 1. Ctrl + Alt + S
        res1 = user32.RegisterHotKey(None, HOTKEY_ID_1, MOD_ALT | MOD_CONTROL, VK_S)
        # 2. Ctrl + Shift + S
        res2 = user32.RegisterHotKey(None, HOTKEY_ID_2, MOD_CONTROL | MOD_SHIFT, VK_S)
        
        if not res1 and not res2:
            print("[HOTKEY] ❌ تعذر تسجيل أي اختصار (ربما هي مستخدمة في برامج أخرى)")
            return
        
        print("[HOTKEY] ✅ الاختصارات مفعلة:")
        print("   - Ctrl + Alt + S")
        print("   - Ctrl + Shift + S")
        
        try:
            msg = ctypes.wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == 0x0312: # WM_HOTKEY
                    if msg.wParam in (HOTKEY_ID_1, HOTKEY_ID_2):
                        root.after(0, _toggle_visibility)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID_1)
            user32.UnregisterHotKey(None, HOTKEY_ID_2)

    threading.Thread(target=_listen, daemon=True).start()

def main():
    # --- START: CLOUDFLARE TUNNEL CONFIGURATION ---
    MY_STATIC_DOMAIN = CLOUDFLARE_DOMAIN  # يُقرأ من constants.py — يُعدَّل حسب المدرسة
    # --- END: CLOUDFLARE TUNNEL CONFIGURATION ---

    # منع تعدد النسخ
    already_running, _lock = _is_already_running()
    if already_running:
        # محاولة تنبيه المستخدم (قد يكون البرنامج مخفياً)
        temp_root = tk.Tk(); temp_root.withdraw()
        messagebox.showwarning("تنبيه", "البرنامج يعمل بالفعل في الخلفية.\nاستخدم (Ctrl + Alt + S) لإظهاره.")
        temp_root.destroy()
        sys.exit(0)

    _cleanup_environment()

    ensure_dirs(); init_db()

    # ═══ ترقية: إنشاء جدول behavioral_contracts إن لم يكن موجوداً ══
    try:
        _con2 = get_db(); _cur2 = _con2.cursor()
        _cur2.execute("""
            CREATE TABLE IF NOT EXISTS behavioral_contracts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT NOT NULL,
                student_id   TEXT NOT NULL,
                student_name TEXT NOT NULL,
                class_name   TEXT NOT NULL,
                subject      TEXT,
                period_from  TEXT,
                period_to    TEXT,
                notes        TEXT,
                created_at   TEXT NOT NULL
            )""")
        _con2.commit(); _con2.close()
        print("[MIGRATE] ✅ جدول العقود السلوكية جاهز")
    except Exception as _e2:
        print("[MIGRATE] خطأ في جدول العقود السلوكية:", _e2)
    # ═══════════════════════════════════════════════════════════════

    # ═══ ترقية إجبارية لجدول tardiness ═══════════════════════════
    # تُنفَّذ دائماً بغض النظر عن حالة init_db
    try:
        _con = get_db()
        _cur = _con.cursor()
        # اقرأ تعريف الجدول الحالي
        _cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tardiness'")
        _row = _cur.fetchone()
        if _row:
            _sql = _row[0] or ""
            # إذا الـ UNIQUE يشمل class_id → يمنع التسجيل → أعد البناء
            if "class_id" in _sql and "UNIQUE" in _sql:
                print("[MIGRATE] جارٍ إصلاح جدول tardiness...")
                _cur.execute("DROP TABLE IF EXISTS _tard_bak") # تنظيف في حال وجود محاولة سابقة فاشلة
                _cur.execute("ALTER TABLE tardiness RENAME TO _tard_bak")
                _cur.execute("""CREATE TABLE tardiness (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    date         TEXT NOT NULL,
                    class_id     TEXT NOT NULL DEFAULT '',
                    class_name   TEXT NOT NULL DEFAULT '',
                    student_id   TEXT NOT NULL,
                    student_name TEXT NOT NULL,
                    teacher_name TEXT,
                    period       INTEGER,
                    minutes_late INTEGER DEFAULT 0,
                    created_at   TEXT NOT NULL,
                    UNIQUE(date, student_id)
                )""")
                # انقل البيانات القديمة
                _cols = [r[1] for r in _cur.execute("PRAGMA table_info(_tard_bak)")]
                _sel  = ", ".join(
                    "COALESCE({}, {})".format(c, "''" if c in ("class_id","class_name") else
                                              "0"  if c == "minutes_late" else "NULL")
                    if c in ("class_id","class_name","minutes_late") else c
                    for c in _cols
                )
                _cur.execute(
                    "INSERT OR IGNORE INTO tardiness ({}) SELECT {} FROM _tard_bak".format(
                        ", ".join(_cols), _sel))
                _cur.execute("DROP TABLE _tard_bak")
                _con.commit()
                print("[MIGRATE] ✅ تم إصلاح جدول tardiness — يمكنك الآن تسجيل التأخر")
            else:
                # أضف الأعمدة الناقصة فقط
                _existing = {r[1] for r in _cur.execute("PRAGMA table_info(tardiness)")}
                for _col, _dfn in [("teacher_name","TEXT"),("period","INTEGER"),
                                    ("minutes_late","INTEGER DEFAULT 0")]:
                    if _col not in _existing:
                        _cur.execute("ALTER TABLE tardiness ADD COLUMN {} {}".format(_col, _dfn))
                _con.commit()
        _con.close()
    except Exception as _e:
        print("[MIGRATE] خطأ في الترقية:", _e)
    # ═══════════════════════════════════════════════════════════════
    # ─── تشغيل السيرفر مع error logging ─────────────────────────────
    _server_error = [None]

    def _run_server():
        try:
            if sys.stdout is None:
                sys.stdout = open(_LOG_FILE, 'a', encoding='utf-8', errors='replace')
            if sys.stderr is None:
                sys.stderr = open(_LOG_FILE, 'a', encoding='utf-8', errors='replace')
            if sys.platform == 'win32':
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="warning")
            server = uvicorn.Server(config)
            loop.run_until_complete(server.serve())
        except Exception as _srv_e:
            _server_error[0] = str(_srv_e)
            _write_log(f"[SERVER-FATAL] {_srv_e}\n{traceback.format_exc()}")
            print(f"[SERVER] ❌ فشل تشغيل السيرفر: {_srv_e}")

    def _start_server_thread():
        t = threading.Thread(target=_run_server, daemon=True, name="uvicorn")
        t.start()
        return t

    server_thread = _start_server_thread()

    # ─── Watchdog للسيرفر: يعيد تشغيل uvicorn إذا توقف ──────────
    def _server_watchdog():
        import socket as _ws
        while True:
            time.sleep(30)
            # فحص بسيط: هل المنفذ يستجيب؟
            try:
                _s = _ws.socket(_ws.AF_INET, _ws.SOCK_STREAM)
                _s.settimeout(2)
                _s.connect(('127.0.0.1', PORT))
                _s.close()
            except Exception:
                _write_log("[SERVER-WATCHDOG] المنفذ لا يستجيب — جارٍ إعادة تشغيل uvicorn")
                print("[SERVER-WATCHDOG] ⚠️ السيرفر لا يستجيب — إعادة تشغيل...")
                time.sleep(3)
                _start_server_thread()
                time.sleep(10)  # انتظر قبل الفحص التالي

    threading.Thread(target=_server_watchdog, daemon=True, name="srv-watchdog").start()

    # انتظر حتى يصبح السيرفر جاهزاً (حد أقصى 8 ثوانٍ بدلاً من 1 ثانية ثابتة)
    import socket as _test_sock
    _srv_ready = False
    for _attempt in range(16):
        time.sleep(0.5)
        if _server_error[0]:
            print(f"[SERVER] ❌ السيرفر فشل عند المحاولة {_attempt}: {_server_error[0]}")
            break
        try:
            _s = _test_sock.socket(_test_sock.AF_INET, _test_sock.SOCK_STREAM)
            _s.settimeout(0.3)
            _s.connect(('127.0.0.1', PORT))
            _s.close()
            _srv_ready = True
            print(f"[SERVER] ✅ جاهز على المنفذ {PORT} (بعد {(_attempt+1)*0.5:.1f}ث)")
            break
        except Exception:
            pass
    if not _srv_ready and not _server_error[0]:
        print(f"[SERVER] ⚠️ السيرفر لم يستجب في 8 ثوانٍ — قد يكون المنفذ {PORT} محجوزاً")

    public_url = None

    # ─── Cloudflare Tunnel ───────────────────────────────────────
    _cfg = load_config()
    if _cfg.get("cloud_mode") and _cfg.get("cloud_url"):
        # جهاز عميل — الرابط العام هو عنوان السيرفر الرئيسي، لا نشغّل نفقاً محلياً
        public_url = _cfg["cloud_url"].rstrip("/")
        print(f"[CLIENT] 🌐 الرابط العام من السيرفر: {public_url}")
    else:
        public_url = start_cloudflare_tunnel(PORT, MY_STATIC_DOMAIN)
        if public_url:
            print(f"\n{'='*60}")
            print(f"  ✅ الرابط العام: {public_url}")
            print(f"{'='*60}\n")
            from config_manager import save_config
            _c = load_config()
            _c["cloud_url_internal"] = public_url
            save_config(_c)
        else:
            print(f"\n[CLOUDFLARE] يعمل محلياً فقط — http://localhost:{PORT}\n")
    root = ThemedTk(theme="arc"); root.set_theme("arc")

    # ─── التقط كل استثناء Tkinter صامت وأظهره ─────────────────────────────
    def _tk_exc_hook(exc_type, exc_val, exc_tb):
        tb_str = ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
        _write_log(tb_str)
        messagebox.showerror(
            "خطأ غير متوقع",
            f"{exc_val}\n\nالتفاصيل محفوظة في:\n{_LOG_FILE}"
        )
    root.report_callback_exception = _tk_exc_hook

    def on_closing():
        try:
            stop_cloudflare_tunnel()
        except Exception: pass
        try:
            import subprocess as _sp
            from tunnel_manager import stop_cloudflare_tunnel as _stop_t2
            _stop_t2()
            print("[CLEANUP] ✅ النفق أُوقف عند الإغلاق")
        except Exception: pass
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_closing)

    def launch_main_app():
        """يُشغَّل بعد تسجيل الدخول الناجح."""
        try:
            # امسح نافذة تسجيل الدخول وابن التطبيق الرئيسي
            for w in root.winfo_children():
                w.destroy()
            # ← إصلاح: أعد تفعيل تغيير الحجم الذي أوقفه LoginWindow
            root.resizable(True, True)
            root.geometry("1280x800")
            root.update()
            root.state("zoomed")   # تكبير كامل عند البدء
            gui = AppGUI(root, public_url)
            # تسجيل اختصار الإظهار/الإخفاء العالمي
            _register_global_hotkey(root)
            root.update()
        except Exception as _e:
            tb_str = traceback.format_exc()
            _write_log(tb_str)
            # أظهر آخر 4 أسطر من الـ traceback (الأكثر فائدة)
            tb_lines = tb_str.strip().splitlines()
            tb_short = '\n'.join(tb_lines[-6:]) if len(tb_lines) > 6 else tb_str
            messagebox.showerror(
                "خطأ في تشغيل البرنامج",
                f"{tb_short}\n\n(الملف الكامل: {_LOG_FILE})"
            )
            return
        # جدول النسخ الاحتياطية التلقائية
        schedule_auto_backup(root, interval_hours=4)
        # جدول إرسال رابط التأخر تلقائياً عند بداية الدوام
        _schedule_tardiness_sender(root)
        # جدول التقرير اليومي للإدارة
        schedule_daily_report(root)
        # جدول الإشعارات الذكية اليومية
        schedule_daily_alerts(root, run_hour=load_config().get("alert_run_hour", 14))
        # جدول روابط الباصات التلقائية
        from bus_scheduler import schedule_bus_checkin
        schedule_bus_checkin(root)
        # جدول تعزيز الحضور الأسبوعي
        schedule_weekly_rewards(root)
        # جدولة التحديث التلقائي
        from updater import schedule_auto_update
        # ترحيل: إذا كانت الساعة لا تزال على القيمة القديمة (3) غيّرها لمنتصف الليل (0)
        _ucfg = load_config()
        if _ucfg.get("auto_update_hour", 0) == 3:
            from config_manager import save_config
            _ucfg["auto_update_hour"] = 0
            save_config(_ucfg)
        schedule_auto_update(root)
        # جدول تصدير نور التلقائي
        def _noor_auto_check():
            now = datetime.datetime.now()
            if now.weekday() not in {6,0,1,2,3}: # الأحد-الخميس
                root.after(3_600_000, _noor_auto_check); return
            cfg = load_config()
            if cfg.get("noor_auto_export") and now.hour == cfg.get("noor_export_hour",13) and now.minute < 5:
                date_str = now_riyadh_date()
                save_dir = cfg.get("noor_save_dir", DATA_DIR)
                fname = os.path.join(save_dir, "noor_{}.xlsx".format(date_str))
                try:
                    export_to_noor_excel(date_str, fname)
                    print("[NOOR] ✅ تم التصدير التلقائي:", fname)
                except Exception as e:
                    print("[NOOR] ❌ فشل التصدير:", e)
                root.after(3_600_000, _noor_auto_check)
            else:
                root.after(300_000, _noor_auto_check)
        root.after(60_000, _noor_auto_check)

    # ─── فحص الترخيص (يُتجاوز لأجهزة العميل السحابي) ──────────
    _cfg = load_config()
    if _cfg.get("cloud_mode", False):
        # جهاز عميل مربوط بسيرفر خارجي — لا يحتاج ترخيص
        LoginWindow(root, on_success=launch_main_app)
    else:
        lic_ok, lic_msg, lic_info, lic_client = check_license_on_startup(root)
        if not lic_ok:
            def _after_activation():
                _ok, _msg, _info, _ = check_license_on_startup(root)
                if _ok:
                    LoginWindow(root, on_success=launch_main_app)
                else:
                    messagebox.showerror("خطأ في الترخيص", _msg)
                    root.destroy()
                    sys.exit(1)
            ActivationWindow(root, msg=lic_msg, on_success=_after_activation)
        else:
            LoginWindow(root, on_success=launch_main_app)

    # ── أغلق شاشة البدء الآن، وقد صارت النافذة جاهزة فعلاً ──
    # لا قبل ذلك: إغلاقها مبكراً يُعيد المستخدم إلى شاشة فارغة في آخر
    # ثانية، وهو ما كانت الشاشة موجودة لمنعه أصلاً.
    _close_splash(root)

    root.mainloop()

if __name__ == "__main__":
    multiprocessing.freeze_support()   # ضروري لـ PyInstaller على Windows
    try: main()
    except SystemExit:
        _close_splash()
    except Exception as e:
        # شاشة البدء «دائماً في المقدمة» — لو بقيت مفتوحة لحجبت رسالة
        # الخطأ نفسها، فيرى المستخدم شاشة تحميل أبدية بلا سبب ظاهر.
        _close_splash()
        tb_str = traceback.format_exc()
        _write_log(tb_str)
        try:
            import tkinter as _tk
            _r = _tk.Tk(); _r.withdraw()
            from tkinter import messagebox as _mb
            _mb.showerror("خطأ فادح", f"{e}\n\nالتفاصيل في:\n{_LOG_FILE}")
            _r.destroy()
        except Exception:
            pass
        try: stop_cloudflare_tunnel()
        except: pass
