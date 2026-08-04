import os, sqlite3, datetime, hashlib, json, zipfile, csv, re, socket, sys # TEST
import tkinter as tk
from tkinter import messagebox, filedialog


def _safe_write_json(path: str, data) -> None:
    """كتابة آمنة لملف JSON: يكتب في ملف مؤقت ثم يُعيد التسمية لمنع تلف البيانات."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# ─── منع ازدواجية التطبيق ───
# تم نقل القفل إلى main.py لمنع التداخل عند استدعاء قاعدة البيانات
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
try:
    import pandas as pd
except ImportError:
    pd = None
from typing import List, Dict, Any, Optional
from constants import (DB_PATH, DATA_DIR, BACKUP_DIR, STUDENTS_JSON,
                       TEACHERS_JSON, CONFIG_JSON, ROLE_TABS,
                       INBOX_ATTACHMENTS_DIR, SCHOOL_REPORTS_DIR,
                       ensure_dirs)
import constants
from config_manager import load_config
import requests
import security as _sec

# ─── حالة التشغيل (سيرفر أم عميل) ───────────────────────────
# نستخدم متغير بيئة لضمان ثبات القيمة عبر جميع العمليات (Processes)
def is_server_side():
    return os.environ.get("DARB_SERVER_MODE") == "1"
# ────────────────────────────────────────────────────────────

class CloudDBClient:
    """عميل للتواصل مع السيرفر السحابي بدلاً من قاعدة البيانات المحلية."""
    def __init__(self):
        cfg = load_config()
        self.url = cfg.get("cloud_url", "").rstrip("/")
        self.token = cfg.get("cloud_token", "")
        self.enabled = cfg.get("cloud_mode", False)

    def is_active(self):
        # تم إلغاء قيد os.environ["DARB_SERVER_MODE"] للسماح للأجهزة العميلة بسحب البيانات
        # حتى لو كانت تشغل سيرفر محلياً للأجهزة المتنقلة الخاصة بها.
        return self.enabled and self.url

    def _get_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, endpoint, params=None):
        try:
            resp = requests.get(f"{self.url}{endpoint}", params=params, headers=self._get_headers(), timeout=10)
            if resp.status_code != 200:
                print(f"[CLOUD-GET-ERROR] {endpoint} -> Status {resp.status_code}: {resp.text[:200]}")
            return resp.json() if resp.status_code == 200 else {"ok": False, "msg": f"Error {resp.status_code}"}
        except Exception as e:
            print(f"[CLOUD-GET-EXCEPTION] {endpoint} -> {e}")
            return {"ok": False, "msg": str(e)}

    def post(self, endpoint, json_data):
        try:
            resp = requests.post(f"{self.url}{endpoint}", json=json_data, headers=self._get_headers(), timeout=10)
            if resp.status_code != 200:
                print(f"[CLOUD-POST-ERROR] {endpoint} -> Status {resp.status_code}: {resp.text[:200]}")
            return resp.json() if resp.status_code == 200 else {"ok": False, "msg": f"Error {resp.status_code}"}
        except Exception as e:
            print(f"[CLOUD-POST-EXCEPTION] {endpoint} -> {e}")
            return {"ok": False, "msg": str(e)}

    def delete(self, endpoint, params=None):
        try:
            resp = requests.delete(f"{self.url}{endpoint}", params=params, headers=self._get_headers(), timeout=10)
            if resp.status_code != 200:
                print(f"[CLOUD-DELETE-ERROR] {endpoint} -> Status {resp.status_code}: {resp.text[:200]}")
            return resp.json() if resp.status_code == 200 else {"ok": False, "msg": f"Error {resp.status_code}"}
        except Exception as e:
            print(f"[CLOUD-DELETE-EXCEPTION] {endpoint} -> {e}")
            return {"ok": False, "msg": str(e)}

    def put(self, endpoint, json_data):
        try:
            resp = requests.put(f"{self.url}{endpoint}", json=json_data, headers=self._get_headers(), timeout=10)
            if resp.status_code != 200:
                print(f"[CLOUD-PUT-ERROR] {endpoint} -> Status {resp.status_code}: {resp.text[:200]}")
            return resp.json() if resp.status_code == 200 else {"ok": False, "msg": f"Error {resp.status_code}"}
        except Exception as e:
            print(f"[CLOUD-PUT-EXCEPTION] {endpoint} -> {e}")
            return {"ok": False, "msg": str(e)}

    def patch(self, endpoint, json_data):
        try:
            resp = requests.patch(f"{self.url}{endpoint}", json=json_data, headers=self._get_headers(), timeout=10)
            if resp.status_code != 200:
                print(f"[CLOUD-PATCH-ERROR] {endpoint} -> Status {resp.status_code}: {resp.text[:200]}")
            return resp.json() if resp.status_code == 200 else {"ok": False, "msg": f"Error {resp.status_code}"}
        except Exception as e:
            print(f"[CLOUD-PATCH-EXCEPTION] {endpoint} -> {e}")
            return {"ok": False, "msg": str(e)}

_cloud_client = CloudDBClient()

def get_cloud_client():
    global _cloud_client
    return _cloud_client

def refresh_cloud_client():
    global _cloud_client
    _cloud_client = CloudDBClient()

def is_client_mode():
    """يتحقق إذا كان الجهاز يعمل كعميل (ليس سيرفر) — يُستخدم لمنع الحذف من أجهزة العميل."""
    try:
        from config_manager import load_config
        cfg = load_config()
        return cfg.get("cloud_mode", False) and cfg.get("cloud_url", "")
    except Exception:
        return False

def get_db():
    """يُنشئ اتصال DB مع إعدادات مُحسَّنة."""
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=10000")
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("PRAGMA mmap_size=134217728")  # 128 MB memory-mapped I/O
    # ٣ ثوانٍ كانت قصيرة جداً: تسجيل الغياب كان يفشل بـ "database is locked"
    # إذا صادف نسخة احتياطية أو مهمة مجدولة تكتب في نفس اللحظة — وهذه
    # الوظيفة الأساسية للبرنامج فلا يُقبل فشلها.
    con.execute("PRAGMA busy_timeout=20000")
    return con

def init_db():
    con = get_db(); cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS absences (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, class_id TEXT NOT NULL,
        class_name TEXT NOT NULL, student_id TEXT NOT NULL, student_name TEXT NOT NULL,
        teacher_id TEXT, teacher_name TEXT, period INTEGER, created_at TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_absences_date ON absences(date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_absences_class ON absences(class_id)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_absence ON absences(date, class_id, student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_absences_date_period_class ON absences(date, period, class_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_absences_student_name ON absences(student_name)")

    # ─── جدول سجل الرسائل ───────────────────────────────────
    cur.execute("""CREATE TABLE IF NOT EXISTS message_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        student_id  TEXT NOT NULL,
        student_name TEXT NOT NULL,
        class_id    TEXT NOT NULL DEFAULT '',
        class_name  TEXT NOT NULL DEFAULT '',
        phone       TEXT,
        status      TEXT,
        template_used TEXT,
        created_at  TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_message_log_date ON message_log(date)")

    # --- جدول شهادات التميز ---
    cur.execute("""CREATE TABLE IF NOT EXISTS certificates_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        student_name TEXT NOT NULL,
        level INTEGER NOT NULL,
        sent_at TEXT NOT NULL
    )""")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_cert ON certificates_log(student_id, level)")

    # --- جدول قصص المدرسة ---
    cur.execute("""CREATE TABLE IF NOT EXISTS school_stories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        image_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_active INTEGER DEFAULT 1
    )""")

    # ─── جدول التأخر ────────────────────────────────────────────
    # الـ UNIQUE الصحيح: تاريخ + طالب فقط (تأخر الدوام مرة واحدة في اليوم)
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tardiness'")
    tardiness_exists = cur.fetchone() is not None

    if tardiness_exists:
        # إذا وُجدت tardiness_old → ترقية سابقة توقفت في المنتصف، أكملها أولاً
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tardiness_old'")
        if cur.fetchone():
            try:
                cur.execute("""INSERT OR IGNORE INTO tardiness
                    (id,date,class_id,class_name,student_id,student_name,
                     teacher_name,period,minutes_late,created_at)
                    SELECT id,date,
                           COALESCE(class_id,''),COALESCE(class_name,''),
                           student_id,student_name,
                           teacher_name,period,COALESCE(minutes_late,0),created_at
                    FROM tardiness_old""")
            except Exception:
                pass
            cur.execute("DROP TABLE tardiness_old")
            print("[DB] تم تنظيف tardiness_old من ترقية سابقة غير مكتملة")

        # افحص هل الـ UNIQUE الحالي هو (date, student_id) الصحيح
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tardiness'")
        current_sql = (cur.fetchone() or ("",))[0] or ""
        import re as _re
        m = _re.search(r'UNIQUE\s*\(([^)]+)\)', current_sql, _re.IGNORECASE)
        current_unique = m.group(1).replace(' ', '').lower() if m else ""
        need_rebuild = current_unique not in ("date,student_id", "")

        if need_rebuild:
            cur.execute("ALTER TABLE tardiness RENAME TO tardiness_old")
            cur.execute("""
            CREATE TABLE tardiness (
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
            try:
                cur.execute("""INSERT OR IGNORE INTO tardiness
                    (id,date,class_id,class_name,student_id,student_name,
                     teacher_name,period,minutes_late,created_at)
                    SELECT id,date,
                           COALESCE(class_id,''),COALESCE(class_name,''),
                           student_id,student_name,
                           teacher_name,period,COALESCE(minutes_late,0),created_at
                    FROM tardiness_old""")
            except Exception:
                pass
            cur.execute("DROP TABLE tardiness_old")
            print("[DB] تم ترقية جدول tardiness — الـ UNIQUE الجديد: date+student_id")
        else:
            # أضف أعمدة ناقصة فقط
            existing_cols = {row[1] for row in cur.execute("PRAGMA table_info(tardiness)")}
            for col, dfn in [("teacher_name","TEXT"), ("period","INTEGER"),
                             ("minutes_late","INTEGER DEFAULT 0")]:
                if col not in existing_cols:
                    try:
                        cur.execute("ALTER TABLE tardiness ADD COLUMN {} {}".format(col, dfn))
                    except Exception:
                        pass
    else:
        cur.execute("""
        CREATE TABLE tardiness (
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tard_date    ON tardiness(date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tard_student ON tardiness(student_id)")

    # ─── جدول الأعذار ───────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS excuses (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        date         TEXT NOT NULL,
        student_id   TEXT NOT NULL,
        student_name TEXT NOT NULL,
        class_id     TEXT NOT NULL,
        class_name   TEXT NOT NULL,
        reason       TEXT NOT NULL,
        source       TEXT NOT NULL DEFAULT 'admin',
        approved_by  TEXT,
        created_at   TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_excuse_date    ON excuses(date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_excuse_student ON excuses(student_id)")

    # ─── جدول المستخدمين ────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        username     TEXT NOT NULL UNIQUE,
        password     TEXT NOT NULL,
        role         TEXT NOT NULL DEFAULT 'teacher',
        full_name    TEXT,
        active       INTEGER NOT NULL DEFAULT 1,
        allowed_tabs TEXT,
        created_at   TEXT NOT NULL
    )""")
    # ترقية: أضف الأعمدة الناقصة في جدول users
    _u_cols = {r[1] for r in cur.execute("PRAGMA table_info(users)")}
    if "allowed_tabs" not in _u_cols:
        cur.execute("ALTER TABLE users ADD COLUMN allowed_tabs TEXT")
    if "phone" not in _u_cols:
        cur.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
    if "last_login" not in _u_cols:
        cur.execute("ALTER TABLE users ADD COLUMN last_login TEXT")
    # مستخدم مدير افتراضي إذا لم يوجد
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        # كلمة المرور التي اختارها المدير في شاشة الإعداد الأولي إن وُجدت،
        # وإلا الافتراضية القديمة (يُنبَّه المستخدم لتغييرها عند الدخول).
        default_pw = _sec.consume_initial_admin_password() or _sec.hash_password("admin123")
        cur.execute(
            "INSERT INTO users (username,password,role,full_name,active,created_at) VALUES (?,?,?,?,?,?)",
            ("admin", default_pw, "admin", "المدير", 1, datetime.datetime.utcnow().isoformat())
        )

    # ─── جدول سجل النسخ الاحتياطية ─────────────────────────────
    # ─── جدول نتائج الطلاب ──────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS student_results (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        identity_no  TEXT NOT NULL,
        student_name TEXT NOT NULL,
        section      TEXT,
        school_year  TEXT,
        page_no      INTEGER NOT NULL DEFAULT 0,
        pdf_path     TEXT NOT NULL DEFAULT '',
        gpa          TEXT,
        class_rank   TEXT,
        section_rank TEXT,
        excused_abs  TEXT,
        unexcused_abs TEXT,
        subjects_json TEXT,
        uploaded_at  TEXT NOT NULL
    )""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS
        idx_results_identity ON student_results(identity_no, school_year)""")

    # ─── جدول رموز تفعيل النتائج ─────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS result_tokens (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        token      TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        note       TEXT
    )""")

    # ─── جدول الاستئذان ─────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS permissions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        date         TEXT NOT NULL,
        student_id   TEXT NOT NULL,
        student_name TEXT NOT NULL,
        class_id     TEXT NOT NULL DEFAULT '',
        class_name   TEXT NOT NULL DEFAULT '',
        parent_phone TEXT NOT NULL DEFAULT '',
        reason       TEXT,
        approved_by  TEXT,
        status       TEXT NOT NULL DEFAULT 'انتظار',
        msg_sent_at  TEXT,
        approved_at  TEXT,
        created_at   TEXT NOT NULL
    )""")
    _pcols = {r[1] for r in cur.execute("PRAGMA table_info(permissions)")}
    for _col,_dfn in [("parent_phone","TEXT NOT NULL DEFAULT ''"),
                       ("msg_sent_at","TEXT"),("approved_at","TEXT")]:
        if _col not in _pcols:
            try: cur.execute("ALTER TABLE permissions ADD COLUMN {} {}".format(_col,_dfn))
            except: pass
    cur.execute("CREATE INDEX IF NOT EXISTS idx_perm_date ON permissions(date)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS backup_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        filename   TEXT NOT NULL,
        size_kb    INTEGER,
        created_at TEXT NOT NULL
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        student_id TEXT NOT NULL,
        student_name TEXT NOT NULL,
        class_id TEXT NOT NULL,
        class_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        status TEXT NOT NULL,
        template_used TEXT,
        message_type TEXT NOT NULL DEFAULT 'absence',
        created_at TEXT NOT NULL
    )""")
    # ترقية: أضف message_type إذا لم يكن موجوداً
    _ml_cols = {r[1] for r in cur.execute("PRAGMA table_info(messages_log)")}
    if "message_type" not in _ml_cols:
        cur.execute("ALTER TABLE messages_log ADD COLUMN message_type TEXT NOT NULL DEFAULT 'absence'")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_log_date ON messages_log(date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_log_student ON messages_log(student_id)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedule (
        day_of_week INTEGER NOT NULL, -- 0=Sunday, 1=Monday, ..., 4=Thursday
        class_id TEXT NOT NULL,
        period INTEGER NOT NULL,
        teacher_name TEXT,
        PRIMARY KEY (day_of_week, class_id, period)
    )""")

    # ─── جداول الموجّه الطلابي ───────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS counselor_sessions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        date         TEXT NOT NULL,
        student_id   TEXT NOT NULL,
        student_name TEXT NOT NULL,
        class_name   TEXT NOT NULL,
        reason       TEXT,
        notes        TEXT,
        action_taken TEXT,
        created_at   TEXT NOT NULL
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS counselor_alerts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        date         TEXT NOT NULL,
        student_id   TEXT NOT NULL,
        student_name TEXT NOT NULL,
        type         TEXT NOT NULL,
        method       TEXT NOT NULL,
        status       TEXT,
        created_at   TEXT NOT NULL
    )""")

    # ─── جدول زيارات أولياء الأمور ──────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS parent_visits (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        date          TEXT NOT NULL,
        visit_time    TEXT NOT NULL,
        student_id    TEXT NOT NULL,
        student_name  TEXT NOT NULL,
        class_name    TEXT NOT NULL,
        guardian_name TEXT,
        visit_reason  TEXT NOT NULL,
        received_by   TEXT NOT NULL,
        visit_result  TEXT NOT NULL,
        notes         TEXT,
        created_by    TEXT,
        created_at    TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_parent_visits_date ON parent_visits(date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_parent_visits_student ON parent_visits(student_id)")

    # ─── جدول العقود السلوكية ───────────────────────────────────
    cur.execute("""
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

    # ─── جدول تحويلات الموجّه (المحوّلون من وكيل شؤون الطلاب) ────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS counselor_referrals (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        date         TEXT NOT NULL,
        student_id   TEXT NOT NULL,
        student_name TEXT NOT NULL,
        class_name   TEXT NOT NULL,
        referral_type TEXT NOT NULL DEFAULT 'غياب',
        absence_count INTEGER DEFAULT 0,
        tardiness_count INTEGER DEFAULT 0,
        notes        TEXT,
        referred_by  TEXT DEFAULT 'وكيل شؤون الطلاب',
        status       TEXT DEFAULT 'جديد',
        created_at   TEXT NOT NULL
    )""")

    # ─── جدول خطابات الاستفسار الأكاديمي ────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS academic_inquiries (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        date             TEXT NOT NULL,
        counselor_name   TEXT NOT NULL,
        teacher_username TEXT NOT NULL,
        teacher_name     TEXT NOT NULL,
        class_name       TEXT NOT NULL,
        subject          TEXT NOT NULL,
        student_name     TEXT NOT NULL,
        teacher_reply_date TEXT,
        teacher_reply_reasons TEXT,
        teacher_reply_evidence TEXT,
        status           TEXT DEFAULT 'جديد',
        inquiry_type     TEXT DEFAULT 'تدني ملحوظ',
        created_at       TEXT NOT NULL
    )""")
    try:
        cur.execute("ALTER TABLE academic_inquiries ADD COLUMN inquiry_type TEXT DEFAULT 'تدني ملحوظ'")
    except: pass

    # ─── جدول تحويلات الطلاب من المعلم ───────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS student_referrals (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        ref_date             TEXT NOT NULL,
        student_id           TEXT DEFAULT '',
        student_name         TEXT NOT NULL,
        class_id             TEXT DEFAULT '',
        class_name           TEXT NOT NULL,
        subject              TEXT DEFAULT '',
        period               TEXT DEFAULT '',
        session_time         TEXT DEFAULT '',
        session_ampm         TEXT DEFAULT 'ص',
        violation_type       TEXT DEFAULT 'سلوكية',
        violation            TEXT DEFAULT '',
        problem_causes       TEXT DEFAULT '',
        repeat_count         TEXT DEFAULT 'الأول',
        teacher_action1      TEXT DEFAULT '',
        teacher_action2      TEXT DEFAULT '',
        teacher_action3      TEXT DEFAULT '',
        teacher_action4      TEXT DEFAULT '',
        teacher_action5      TEXT DEFAULT '',
        teacher_name         TEXT NOT NULL,
        teacher_username     TEXT DEFAULT '',
        teacher_date         TEXT DEFAULT '',
        status               TEXT DEFAULT 'pending',
        deputy_meeting_date  TEXT DEFAULT '',
        deputy_meeting_period TEXT DEFAULT '',
        deputy_action1       TEXT DEFAULT '',
        deputy_action2       TEXT DEFAULT '',
        deputy_action3       TEXT DEFAULT '',
        deputy_action4       TEXT DEFAULT '',
        deputy_name          TEXT DEFAULT '',
        deputy_date          TEXT DEFAULT '',
        deputy_referred_date TEXT DEFAULT '',
        counselor_meeting_date TEXT DEFAULT '',
        counselor_meeting_period TEXT DEFAULT '',
        counselor_action1    TEXT DEFAULT '',
        counselor_action2    TEXT DEFAULT '',
        counselor_action3    TEXT DEFAULT '',
        counselor_action4    TEXT DEFAULT '',
        counselor_name       TEXT DEFAULT '',
        counselor_date       TEXT DEFAULT '',
        counselor_referred_back_date TEXT DEFAULT '',
        created_at           TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_referrals_teacher ON student_referrals(teacher_username)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_referrals_status  ON student_referrals(status)")

    # ─── جدول التعاميم الرسمية ────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS circulars (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        date             TEXT NOT NULL,
        title            TEXT NOT NULL,
        content          TEXT,
        attachment_path  TEXT,
        created_by       TEXT NOT NULL,
        target_role      TEXT DEFAULT 'all',
        created_at       TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_circulars_date ON circulars(date)")

    # ─── جدول قراءة التعاميم ─────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS circular_reads (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        circular_id      INTEGER NOT NULL,
        username         TEXT NOT NULL,
        read_at          TEXT NOT NULL,
        UNIQUE(circular_id, username)
    )""")

    # ─── جدول تقارير المعلمين ────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS teacher_reports (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        form_type      TEXT NOT NULL,
        title          TEXT NOT NULL,
        submitted_by   TEXT NOT NULL,
        submitted_name TEXT NOT NULL,
        submitted_at   TEXT NOT NULL,
        pdf_data       BLOB NOT NULL,
        is_read        INTEGER DEFAULT 0
    )""")

    # ─── جدول ملاحظات الطالب الإدارية ───────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS student_notes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id  TEXT NOT NULL,
        note        TEXT NOT NULL,
        author      TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_snotes_student ON student_notes(student_id)")

    migrate_circulars_permission(cur)
    _migrate_add_tab(cur, 'زيارات أولياء الأمور',
                     ('admin', 'deputy', 'staff', 'counselor'))
    _migrate_add_tab(cur, 'روابط بوابة أولياء الأمور',
                     ('admin', 'deputy', 'staff', 'counselor'))

    cur.execute("""
    CREATE TABLE IF NOT EXISTS exempted_students (
        student_id   TEXT PRIMARY KEY,
        student_name TEXT NOT NULL,
        class_name   TEXT,
        reason       TEXT,
        created_at   TEXT NOT NULL
    )""")

    # ─── جدول نقاط التميز (جديد) ──────────────────────────────────
    cur.execute("""CREATE TABLE IF NOT EXISTS student_points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        points INTEGER NOT NULL,
        reason TEXT,
        author_id TEXT,
        author_name TEXT,
        date TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    # Migration: إضافة أعمدة المؤلف إذا لم تكن موجودة
    try: cur.execute("ALTER TABLE student_points ADD COLUMN author_id TEXT")
    except: pass
    try: cur.execute("ALTER TABLE student_points ADD COLUMN author_name TEXT")
    except: pass
    cur.execute("CREATE INDEX IF NOT EXISTS idx_points_student ON student_points(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_points_date ON student_points(date)")

    # ─── جدول توكنات بوابة ولي الأمر (جديد) ──────────────────────
    # ─── جدول زيادات رصيد المعلمين (جديد) ──────────────────────────
    cur.execute("""CREATE TABLE IF NOT EXISTS teacher_points_adjustments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        month TEXT NOT NULL,
        extra_points INTEGER NOT NULL,
        reason TEXT,
        created_at TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tpa_user_month ON teacher_points_adjustments(username, month)")

    # ─── جدول التحويلات السلوكية (جديد) ───────────────────────────
    cur.execute("""CREATE TABLE IF NOT EXISTS behavioral_referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        student_name TEXT NOT NULL,
        class_name TEXT NOT NULL,
        violation TEXT NOT NULL,
        date TEXT NOT NULL,
        teacher_id TEXT,
        teacher_name TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL
    )""")

    # ─── جداول التعاميم ───────────────────────────────────────────
    cur.execute("""CREATE TABLE IF NOT EXISTS circulars (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        attachment_path TEXT,
        date TEXT NOT NULL,
        target_roles TEXT DEFAULT 'all',
        read_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS circular_reads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        circular_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        read_at TEXT NOT NULL,
        UNIQUE(circular_id, username)
    )""")
    # Migration: إضافة أعمدة ناقصة في جداول التعاميم
    try: cur.execute("ALTER TABLE circulars ADD COLUMN target_roles TEXT DEFAULT 'all'")
    except: pass
    try: cur.execute("ALTER TABLE circulars ADD COLUMN read_count INTEGER DEFAULT 0")
    except: pass
    try: cur.execute("ALTER TABLE circulars ADD COLUMN created_by TEXT DEFAULT 'الإدارة'")
    except: pass

    cur.execute("""CREATE TABLE IF NOT EXISTS parent_portal_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL UNIQUE,
        token TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )""")

    # ─── جدول الطلاب المنقولين (لإخفائهم من التقارير) ──────────────
    cur.execute("""CREATE TABLE IF NOT EXISTS transferred_students (
        student_id    TEXT PRIMARY KEY,
        student_name  TEXT,
        transferred_at TEXT NOT NULL
    )""")

    # ─── جدول تصنيف الغياب الجزئي (هارب/مستأذن) ─────────────────
    cur.execute("""CREATE TABLE IF NOT EXISTS partial_absence_status (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        student_id  TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'غير محدد',
        notes       TEXT DEFAULT '',
        updated_at  TEXT NOT NULL,
        UNIQUE(date, student_id)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS inbox_messages (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user        TEXT NOT NULL,
        to_user          TEXT NOT NULL,
        subject          TEXT NOT NULL DEFAULT '',
        body             TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        is_read          INTEGER NOT NULL DEFAULT 0,
        read_at          TEXT,
        deleted_by_sender   INTEGER NOT NULL DEFAULT 0,
        deleted_by_receiver INTEGER NOT NULL DEFAULT 0,
        attachment_path  TEXT,
        attachment_name  TEXT,
        attachment_size  INTEGER
    )""")
    # ترقية: أضف أعمدة المرفقات إذا لم تكن موجودة
    _ib_cols = {r[1] for r in cur.execute("PRAGMA table_info(inbox_messages)")}
    for _col, _def in [("attachment_path","TEXT"), ("attachment_name","TEXT"), ("attachment_size","INTEGER")]:
        if _col not in _ib_cols:
            cur.execute(f"ALTER TABLE inbox_messages ADD COLUMN {_col} {_def}")

    cur.execute("""CREATE TABLE IF NOT EXISTS school_reports (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        category     TEXT NOT NULL,
        title        TEXT NOT NULL,
        description  TEXT NOT NULL DEFAULT '',
        report_date  TEXT NOT NULL DEFAULT '',
        file_path    TEXT NOT NULL,
        file_name    TEXT NOT NULL,
        file_size    INTEGER NOT NULL DEFAULT 0,
        uploaded_by  TEXT NOT NULL DEFAULT '',
        uploaded_at  TEXT NOT NULL
    )""")

    # ─── جدول الإجازات الرسمية ────────────────────────────────────
    cur.execute("""CREATE TABLE IF NOT EXISTS holidays (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        date       TEXT NOT NULL UNIQUE,
        label      TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""")

    # ─── جداول إدارة الباصات ──────────────────────────────────────
    cur.execute("""CREATE TABLE IF NOT EXISTS buses (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT NOT NULL,
        driver_name  TEXT NOT NULL,
        driver_phone TEXT NOT NULL,
        route        TEXT DEFAULT '',
        active       INTEGER NOT NULL DEFAULT 1,
        created_at   TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS student_buses (
        student_id   TEXT NOT NULL PRIMARY KEY,
        bus_id       INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS bus_trips (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        bus_id          INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
        date            TEXT NOT NULL,
        trip_type       TEXT NOT NULL DEFAULT 'morning',
        token           TEXT NOT NULL UNIQUE,
        sent_at         TEXT,
        driver_ready_at TEXT,
        created_at      TEXT NOT NULL,
        UNIQUE(bus_id, date, trip_type)
    )""")
    try: cur.execute("ALTER TABLE bus_trips ADD COLUMN driver_ready_at TEXT")
    except: pass
    cur.execute("""CREATE TABLE IF NOT EXISTS bus_attendance (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id      INTEGER NOT NULL REFERENCES bus_trips(id) ON DELETE CASCADE,
        student_id   TEXT NOT NULL,
        student_name TEXT NOT NULL,
        class_name   TEXT NOT NULL DEFAULT '',
        status       TEXT NOT NULL DEFAULT 'pending',
        recorded_at  TEXT,
        UNIQUE(trip_id, student_id)
    )""")

    con.commit(); con.close()

# --- Helper functions for Exempted Students ---
def add_exempted_student(student_id, student_name, class_name, reason=""):
    con = get_db(); cur = con.cursor()
    created_at = datetime.datetime.now().isoformat()
    cur.execute("""INSERT OR REPLACE INTO exempted_students 
                   (student_id, student_name, class_name, reason, created_at)
                   VALUES (?, ?, ?, ?, ?)""", 
                (student_id, student_name, class_name, reason, created_at))
    con.commit(); con.close()

def remove_exempted_student(student_id):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM exempted_students WHERE student_id = ?", (student_id,))
    con.commit(); con.close()

def get_exempted_students() -> List[Dict]:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM exempted_students ORDER BY student_name")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

# --- Transferred Students ---
def add_transferred_student(student_id: str, student_name: str = ""):
    """يُسجّل الطالب المنقول لإخفائه من التقارير."""
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT OR REPLACE INTO transferred_students (student_id, student_name, transferred_at)
                   VALUES (?, ?, ?)""",
                (str(student_id), student_name, datetime.datetime.now().isoformat()))
    con.commit(); con.close()

# --- Partial Absence Status ---
def get_partial_absences(date_str: str, min_period: int = 2) -> List[Dict]:
    """
    يُرجع الطلاب الذين:
      1. ليس لديهم غياب في الحصص الأولى (period <= min_period)
      2. لديهم غياب في حصص لاحقة (period > min_period)
      3. فصلهم سُجِّل فيه غياب في الحصص الأولى (أي المعلم أخذ الحضور فعلاً)
    الشرط 3 يمنع ظهور طلاب لم يأخذ معلمهم الحضور أصلاً.
    """
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("""
        WITH late_abs AS (
            SELECT student_id, student_name, class_id, class_name, period
            FROM absences
            WHERE date = ?
              AND period IS NOT NULL
              AND student_id NOT IN (
                  SELECT student_id FROM absences
                  WHERE date = ? AND period IS NOT NULL AND period <= ?
              )
        ),
        classes_checked_early AS (
            SELECT DISTINCT class_id
            FROM absences
            WHERE date = ? AND period IS NOT NULL AND period <= ?
        )
        SELECT
            la.student_id,
            MAX(la.student_name)  AS student_name,
            MAX(la.class_name)    AS class_name,
            MIN(la.period)        AS first_absent_period,
            MAX(la.period)        AS last_absent_period,
            GROUP_CONCAT(la.period ORDER BY la.period) AS absent_periods,
            COUNT(*)              AS absence_count,
            COALESCE(p.status, 'غير محدد') AS status,
            COALESCE(p.notes, '')           AS notes
        FROM late_abs la
        JOIN classes_checked_early cce ON cce.class_id = la.class_id
        LEFT JOIN partial_absence_status p
               ON p.date = ? AND p.student_id = la.student_id
        GROUP BY la.student_id
        ORDER BY MAX(la.class_name), MAX(la.student_name)
    """, (date_str, date_str, min_period, date_str, min_period, date_str))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

def set_partial_absence_status(date_str: str, student_id: str, status: str, notes: str = "") -> None:
    """يحفظ أو يُحدّث تصنيف الغياب الجزئي."""
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT INTO partial_absence_status (date, student_id, status, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(date, student_id) DO UPDATE SET
                       status=excluded.status,
                       notes=excluded.notes,
                       updated_at=excluded.updated_at""",
                (date_str, student_id, status, notes, datetime.datetime.now().isoformat()))
    con.commit(); con.close()

# --- Inbox Messages ---
def send_inbox_message(from_user: str, to_user: str, subject: str, body: str,
                       attachment_path: str = None, attachment_name: str = None, attachment_size: int = None):
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT INTO inbox_messages
                   (from_user,to_user,subject,body,created_at,attachment_path,attachment_name,attachment_size)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (from_user, to_user, subject, body, datetime.datetime.now().isoformat(),
                 attachment_path, attachment_name, attachment_size))
    con.commit(); con.close()

def get_inbox_messages(username: str) -> List[Dict]:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute("""SELECT * FROM inbox_messages
                          WHERE to_user=? AND deleted_by_receiver=0
                          ORDER BY created_at DESC""", (username,)).fetchall()
    con.close()
    return [dict(r) for r in rows]

def get_sent_messages(username: str) -> List[Dict]:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute("""SELECT * FROM inbox_messages
                          WHERE from_user=? AND deleted_by_sender=0
                          ORDER BY created_at DESC""", (username,)).fetchall()
    con.close()
    return [dict(r) for r in rows]

def get_inbox_unread_count(username: str) -> int:
    con = get_db(); cur = con.cursor()
    count = cur.execute("""SELECT COUNT(*) FROM inbox_messages
                           WHERE to_user=? AND is_read=0 AND deleted_by_receiver=0""",
                        (username,)).fetchone()[0]
    con.close()
    return count

def mark_inbox_message_read(msg_id: int, username: str):
    now = datetime.datetime.now().isoformat()
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE inbox_messages SET is_read=1, read_at=? WHERE id=? AND to_user=?",
                (now, msg_id, username))
    con.commit(); con.close()

def delete_inbox_message(msg_id: int, username: str):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT from_user, to_user FROM inbox_messages WHERE id=?", (msg_id,))
    row = cur.fetchone()
    if not row:
        con.close(); return
    if row[0] == username:
        cur.execute("UPDATE inbox_messages SET deleted_by_sender=1 WHERE id=?", (msg_id,))
    if row[1] == username:
        cur.execute("UPDATE inbox_messages SET deleted_by_receiver=1 WHERE id=?", (msg_id,))
    con.commit(); con.close()

# --- Student Points & Rewards ---
def add_student_points(student_id, points, reason="", date=None, author_id=None, author_name=None):
    if not date: date = datetime.date.today().isoformat()
    
    client = get_cloud_client()
    if client.is_active():
        client.post("/web/api/points/add", {
            "student_id": student_id, "points": points, "reason": reason,
            "author_id": author_id, "author_name": author_name
        })
        return

    # جلب اسم المانح تلقائياً إذا لم يرسل وكان المعرّف موجوداً
    if author_id and not author_name:
        try:
            con_u = get_db(); cur_u = con_u.cursor()
            cur_u.execute("SELECT full_name FROM users WHERE username = ?", (author_id,))
            row_u = cur_u.fetchone()
            if row_u and row_u[0]:
                author_name = row_u[0]
            else:
                author_name = author_id # كبديل أخير
            con_u.close()
        except: pass

    # التحقق من الرصيد (إذا كان المعلم هو من يمنح)
    if author_id and author_id != "admin":
        cfg = load_config()
        limit = cfg.get("monthly_points_limit", 100)
        balance = get_teacher_points_balance(author_id, date[:7])
        if balance + points > limit:
            raise ValueError(f"لقد تجاوزت الرصيد المسموح به لهذا الشهر (المتبقي: {limit - balance} نقطة)")

    con = get_db(); cur = con.cursor()
    created_at = datetime.datetime.now().isoformat()
    cur.execute("""INSERT INTO student_points (student_id, points, reason, author_id, author_name, date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""", 
                (student_id, points, reason, author_id, author_name, date, created_at))
    con.commit(); con.close()

def get_teacher_points_balance(author_id: str, month_str: str) -> int:
    """يُرجع إجمالي النقاط التي منحها المعلم في شهر معين (YYYY-MM)."""
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/teacher-balance", {"username": author_id, "month": month_str})
        return res.get("balance", 0)

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT SUM(points) FROM student_points WHERE author_id = ? AND date LIKE ?", (author_id, f"{month_str}%"))
    res = cur.fetchone()
    con.close()
    return res[0] if res and res[0] else 0

def get_student_total_points(student_id) -> int:
    """يُرجع مجموع نقاط الطالب — يدعم وضع السحاب."""
    try:
        client = get_cloud_client()
        if client.is_active():
            res = client.get(f"/web/api/student-analysis/{student_id}")
            return res.get("data", {}).get("total_points", 0)

        con = get_db(); cur = con.cursor()
        cur.execute("SELECT SUM(points) FROM student_points WHERE student_id = ?", (student_id,))
        res = cur.fetchone()
        con.close()
        return res[0] if res and res[0] else 0
    except Exception:
        return 0

def _get_teacher_names_map() -> Dict[str, str]:
    """مساعد لجلب خارطة بأسماء المعلمين من teachers.json."""
    try:
        from constants import DATA_DIR
        import json
        tf = os.path.join(DATA_DIR, "teachers.json")
        if os.path.exists(tf):
            with open(tf, encoding="utf-8") as f:
                data = json.load(f)
                return {t.get("رقم الهوية"): t.get("اسم المعلم") for t in data.get("teachers", []) if t.get("رقم الهوية")}
    except: pass
    return {}

def get_student_points_history(student_id) -> List[Dict]:
    client = get_cloud_client()
    if client.is_active():
        res = client.get(f"/web/api/student-analysis/{student_id}")
        return res.get("data", {}).get("points_history", [])

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    # جلب النقاط مع محاولة جلب الاسم من جدول المستخدمين إذا كان مفقوداً في سجل النقطة
    cur.execute("""
        SELECT p.*, 
               CASE 
                 WHEN p.author_name IS NOT NULL AND p.author_name != '' THEN p.author_name
                 WHEN u.full_name IS NOT NULL AND u.full_name != '' THEN u.full_name
                 WHEN p.author_id IS NOT NULL AND p.author_id != '' THEN p.author_id
                 ELSE 'مدير'
               END as resolved_author_name
        FROM student_points p
        LEFT JOIN users u ON p.author_id = u.username
        WHERE p.student_id = ?
        ORDER BY p.date DESC
    """, (student_id,))
    
    rows = []
    teacher_map = None
    
    for r in cur.fetchall():
        d = dict(r)
        auth_name = d.get("resolved_author_name")
        
        # إذا كان الاسم لا يزال عبارة عن رقم (ID)، نحاول البحث عنه في ملف المعلمين
        if auth_name and auth_name.isdigit() and len(auth_name) >= 9:
            if teacher_map is None:
                teacher_map = _get_teacher_names_map()
            if auth_name in teacher_map:
                auth_name = teacher_map[auth_name]
        
        d["author_name"] = auth_name or "مدير"
        rows.append(d)
        
    con.close()
    return rows

def get_admin_points_logs(limit=500) -> List[Dict]:
    """يُرجع كافة سجلات النقاط مرتبة بالأحدث مع معلومات الطالب والمعلم."""
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("""
        SELECT p.*, u.full_name as teacher_full_name
        FROM student_points p
        LEFT JOIN users u ON p.author_id = u.username
        ORDER BY p.created_at DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    
    stus = get_student_map()
    for r in rows:
        sid = r["student_id"]
        if sid in stus:
            r["student_name"] = stus[sid]["name"]
            r["class_name"] = stus[sid]["class_name"]
        else:
            r["student_name"] = "طالب غير موجود"
            r["class_name"] = "-"
        
        if not r.get("teacher_full_name"):
            r["teacher_full_name"] = r.get("author_name") or r.get("author_id") or "مدير"
            
    return rows

def delete_points_record(record_id: int):
    """يحذف سجل نقاط معين."""
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM student_points WHERE id = ?", (record_id,))
    con.commit(); con.close()

def get_teachers_points_usage(month_str: str) -> List[Dict]:
    """يُرجع قائمة بالمعلمين الذين منحوا نقاطاً في شهر معين مع إجمالي نقاطهم والزيادات الممنوحة لهم."""
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    # جلب قائمة المعلمين من جدول المستخدمين
    cur.execute("SELECT username, full_name, role FROM users WHERE role != 'admin' AND active = 1")
    users = [dict(r) for r in cur.fetchall()]
    
    # جلب الاستهلاك والزيادات لكل مستخدم
    results = []
    cfg = load_config()
    base_limit = cfg.get("monthly_points_limit", 100)
    
    for u in users:
        # النقاط المستخدمة
        cur.execute("SELECT SUM(points) FROM student_points WHERE author_id = ? AND date LIKE ?", (u["username"], f"{month_str}%"))
        res_used = cur.fetchone()
        used = res_used[0] if res_used and res_used[0] else 0
        
        # الزيادات الممنوحة
        cur.execute("SELECT SUM(extra_points) FROM teacher_points_adjustments WHERE username = ? AND month = ?", (u["username"], month_str))
        res_adj = cur.fetchone()
        extra = res_adj[0] if res_adj and res_adj[0] else 0
        
        total_limit = base_limit + extra
        
        results.append({
            "username": u["username"],
            "name": u["full_name"] or u["username"],
            "role": u["role"],
            "used": used,
            "extra": extra,
            "limit": total_limit,
            "remaining": max(0, total_limit - used)
        })
    
    con.close()
    return sorted(results, key=lambda x: x["used"], reverse=True)


def add_teacher_points_adjustment(username: str, points: int, reason: str, month_str: str = None):
    """يُضيف زيادة رصيد لمعلم محدد لشهر معين."""
    if not month_str:
        month_str = datetime.date.today().isoformat()[:7] # YYYY-MM
    
    con = get_db(); cur = con.cursor()
    created_at = datetime.datetime.now().isoformat()
    cur.execute("""INSERT INTO teacher_points_adjustments (username, month, extra_points, reason, created_at)
                   VALUES (?, ?, ?, ?, ?)""", (username, month_str, points, reason, created_at))
    con.commit(); con.close()


_student_map_cache = {"data": {}, "version": None}

def get_student_map():
    """يُرجع قاموساً للبحث السريع عن اسم الطالب وفصله عبر معرّفه."""
    global _student_map_cache
    store = load_students()
    
    # استخدام معرف الكائن (Object ID) للتحقق السريع جداً من التغيير في الذاكرة
    version = id(store)
    
    if _student_map_cache["version"] == version:
        return _student_map_cache["data"]
        
    m = {}
    for c in store.get("list", []):
        for s in c.get("students", []):
            m[s["id"]] = {"name": s["name"], "class_name": c["name"]}
    
    _student_map_cache = {"data": m, "version": version}
    return m

def get_points_leaderboard(limit=20) -> List[Dict]:
    """يُرجع قائمة الطلاب الحاصلين على أعلى نقاط، مع دمج بياناتهم من students.json."""
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/leaderboard", {"limit": limit})
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("""SELECT student_id, SUM(points) as total 
                   FROM student_points 
                   GROUP BY student_id 
                   ORDER BY total DESC LIMIT ?""", (limit,))
    point_rows = cur.fetchall()
    con.close()
    
    all_stus = get_student_map()
    
    results = []
    for r in point_rows:
        sid = r["student_id"]
        if sid in all_stus:
            results.append({
                "student_id": sid,
                "points": r["total"],
                "name": all_stus[sid]["name"],
                "class_name": all_stus[sid]["class_name"]
            })
    return results

def get_points_awarded_on_date(date_str) -> int:
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/points-summary", {"date": date_str})
        return res.get("total", 0)

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT SUM(points) FROM student_points WHERE date = ?", (date_str,))
    res = cur.fetchone()
    con.close()
    return res[0] if res and res[0] else 0

# --- Counselor Referrals ---
def get_unread_referrals_count() -> int:
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM student_referrals WHERE status='pending'")
        count = cur.fetchone()[0]
        con.close()
        return count
    except Exception:
        return 0

def get_unread_circulars_count(username: str, role: str) -> int:
    try:
        con = get_db(); cur = con.cursor()
        # التعاميم الموجهة لهذا الدور أو للكل والتي لم يقرأها المستخدم بعد
        query = """
            SELECT COUNT(*) FROM circulars 
            WHERE (target_role = 'all' OR target_role = ?) 
            AND id NOT IN (SELECT circular_id FROM circular_reads WHERE username = ?)
        """
        cur.execute(query, (role, username))
        count = cur.fetchone()[0]
        con.close()
        return count
    except Exception:
        return 0

# --- Student Portal Tokens ---
def get_or_create_portal_token(student_id) -> str:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT token FROM student_portal_tokens WHERE student_id = ?", (student_id,))
    row = cur.fetchone()
    if row:
        con.close()
        return row[0]
    
    # إنشاء توكن فريد جديد
    import secrets
    new_token = secrets.token_urlsafe(12)
    created_at = datetime.datetime.now().isoformat()
    try:
        cur.execute("INSERT INTO student_portal_tokens (student_id, token, created_at) VALUES (?, ?, ?)",
                    (student_id, new_token, created_at))
        con.commit()
    except sqlite3.IntegrityError:
        # في حال تكرار التوكن النادر جداً
        new_token = secrets.token_urlsafe(14)
        cur.execute("INSERT INTO student_portal_tokens (student_id, token, created_at) VALUES (?, ?, ?)",
                    (student_id, new_token, created_at))
        con.commit()
    con.close()
    return new_token

def get_student_id_by_portal_token(token) -> Optional[str]:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT student_id FROM student_portal_tokens WHERE token = ?", (token,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None

# --- School Stories ---
def add_school_story(title, image_path):
    con = get_db(); cur = con.cursor()
    created_at = datetime.datetime.now().isoformat()
    cur.execute("INSERT INTO school_stories (title, image_path, created_at) VALUES (?, ?, ?)",
                (title, image_path, created_at))
    con.commit(); con.close()

def get_active_stories():
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM school_stories WHERE is_active = 1 ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

def delete_school_story(story_id):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM school_stories WHERE id = ?", (story_id,))
    con.commit(); con.close()

# --- Certificates ---
def log_certificate_sent(student_id, student_name, level):
    con = get_db(); cur = con.cursor()
    sent_at = datetime.datetime.now().isoformat()
    cur.execute("INSERT INTO certificates_log (student_id, student_name, level, sent_at) VALUES (?, ?, ?, ?)",
                (student_id, student_name, level, sent_at))
    con.commit(); con.close()

def is_certificate_sent(student_id, level):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id FROM certificates_log WHERE student_id = ? AND level = ?", (student_id, level))
    row = cur.fetchone()
    con.close()
    return True if row else False

def get_certificates_sent_on_date(date_str) -> int:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM certificates_log WHERE substr(sent_at,1,10) = ?", (date_str,))
    res = cur.fetchone()
    con.close()
    return res[0] if res and res[0] else 0


def is_student_exempted(student_id) -> bool:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT 1 FROM exempted_students WHERE student_id = ?", (student_id,))
    exists = cur.fetchone() is not None
    con.close()
    return exists

def migrate_circulars_permission(cur):
    """تتأكد من تفعيل تبويب التعاميم لجميع المعلمين والوكلاء الذين لديهم صلاحيات مخصصة."""
    cur.execute("SELECT id, role, allowed_tabs FROM users WHERE allowed_tabs IS NOT NULL AND allowed_tabs != ''")
    rows = cur.fetchall()
    for rid, role, allowed_tabs_json in rows:
        try:
            tabs = json.loads(allowed_tabs_json)
            if isinstance(tabs, list) and "التعاميم والنشرات" not in tabs:
                tabs.append("التعاميم والنشرات")
                cur.execute("UPDATE users SET allowed_tabs=? WHERE id=?", (json.dumps(tabs, ensure_ascii=False), rid))
        except:
            pass


def _migrate_add_tab(cur, tab_name: str, roles: tuple):
    """يُضيف تبويباً جديداً لقوائم المستخدمين المؤهلين إذا لم يكن موجوداً."""
    cur.execute("SELECT id, role, allowed_tabs FROM users WHERE allowed_tabs IS NOT NULL AND allowed_tabs != ''")
    rows = cur.fetchall()
    for rid, role, allowed_tabs_json in rows:
        if role not in roles:
            continue
        try:
            tabs = json.loads(allowed_tabs_json)
            if isinstance(tabs, list) and tab_name not in tabs:
                tabs.append(tab_name)
                cur.execute("UPDATE users SET allowed_tabs=? WHERE id=?",
                            (json.dumps(tabs, ensure_ascii=False), rid))
        except:
            pass

def clear_yearly_data(reset_type='term'):
    """
    يحذف البيانات المتراكمة لتصفير البرنامج لبداية جديدة.
    reset_type: 'term' (نهاية فصل) أو 'year' (نهاية سنة)
    """
    con = get_db(); cur = con.cursor()
    
    # الجداول التي تُحذف في نهاية كل فصل (semester/term)
    term_tables = [
        "absences", "tardiness", "messages_log", "message_log",
        "excuses", "permissions", "student_referrals",
        "counselor_referrals", "academic_inquiries"
    ]
    
    # الجداول الإضافية التي تُحذف فقط في نهاية السنة
    year_only_tables = [
        "student_results", "result_tokens", "counselor_sessions",
        "behavioral_contracts", "circulars", "circular_reads",
        "counselor_alerts"
    ]
    
    tables_to_clear = term_tables
    if reset_type == 'year':
        tables_to_clear += year_only_tables
        
    for table in tables_to_clear:
        try:
            cur.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            # الجدول قد لا يكون موجوداً في نسخ قديمة
            pass
            
    con.commit(); con.close()
    return True




def insert_absences(date_str, class_id, class_name, students, teacher_id, teacher_name, period):
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/add-absence", {
            "date": date_str, "class_id": class_id, "class_name": class_name,
            "students": students, "period": period
        })
        return res if res.get("ok") else {"created": 0, "skipped": 0}

    # try/finally ضروري: لو فشل commit (قفل مثلاً) كان الاتصال يبقى مفتوحاً
    # حاملاً القفل، فتفشل كل الكتابات التالية تِباعاً.
    con = get_db()
    try:
        cur = con.cursor()

        # جلب الطلاب المستثنين لتجاهلهم
        cur.execute("SELECT student_id FROM exempted_students")
        exempted_ids = {r[0] for r in cur.fetchall()}

        created, skipped = 0, 0
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for s in students:
            if s["id"] in exempted_ids:
                skipped += 1
                continue
            try:
                cur.execute("""INSERT OR IGNORE INTO absences
                               (date,class_id,class_name,student_id,student_name,teacher_id,teacher_name,period,created_at)
                               VALUES (?,?,?,?,?,?,?,?,?)""",
                            (date_str, class_id, class_name, s["id"], s["name"], teacher_id, teacher_name, period, created_at))
                created += 1
            except sqlite3.IntegrityError:
                skipped += 1
        con.commit()
        return {"created": created, "skipped": skipped}
    finally:
        try:
            con.close()
        except Exception:
            pass

def delete_absence(rec_id):
    client = get_cloud_client()
    if client.is_active():
        client.delete(f"/web/api/absences/{rec_id}")
        return

    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM absences WHERE id=?", (rec_id,))
    con.commit(); con.close()

def query_absences(date_filter=None, class_id_filter=None, student_id=None, **kwargs):
    client = get_cloud_client()
    if client.is_active():
        params = {}
        if date_filter: params["date"] = date_filter
        elif "date_filter" in kwargs: params["date"] = kwargs["date_filter"]
        
        if student_id: params["student_id"] = student_id
        elif "student_id" in kwargs: params["student_id"] = kwargs["student_id"]
        
        if class_id_filter: params["class_id"] = class_id_filter
        elif "class_id_filter" in kwargs: params["class_id"] = kwargs["class_id_filter"]
        
        res = client.get("/web/api/absences", params=params)
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    q, p = "SELECT * FROM absences WHERE 1=1", []
    
    # Handle Positional or Keyword args
    d_f = date_filter or kwargs.get("date_filter")
    if d_f: q += " AND date=?"; p.append(d_f)
    
    s_id = student_id or kwargs.get("student_id")
    if s_id: q += " AND student_id=?"; p.append(s_id)
    
    c_id = class_id_filter or kwargs.get("class_id_filter")
    if c_id: q += " AND class_id=?"; p.append(c_id)
    cur.execute(q + " ORDER BY date DESC, class_id, student_name", p)
    rows = [dict(r) for r in cur.fetchall()]
    
    # تصفية المستثنين من النتائج (احتياطياً)
    cur.execute("SELECT student_id FROM exempted_students")
    exempted_ids = {r[0] for r in cur.fetchall()}
    con.close()
    
    rows = [r for r in rows if r["student_id"] not in exempted_ids]
    return rows

def norm_token(s: str) -> str:
    if s is None: return ""
    return str(s).strip()

def normalize_legacy_class_id(cid: str) -> str:
    if not cid: return cid
    m = re.match(r"^\s*(1314|1416|1516)\s*-\s*(.+)\s*$", str(cid))
    if not m: return cid
    lvl = {"1314": "1", "1416": "2", "1516": "3"}[m.group(1)]
    return f"{lvl}-{str(m.group(2)).strip()}"

# ═══════════════════════════════════════════════════════════════
#  مرحلة المدرسة — ابتدائي / متوسط / ثانوي
# ═══════════════════════════════════════════════════════════════
# كان النظام يفترض «ثانوي» في كل موضع، فأي مدرسة متوسطة أو ابتدائية
# تُستورد كانت تصبح فصولها كلها «أول ثانوي». نور يُصرّح بالمرحلة في
# ورقة School Info تحت «مرحلة المدرسة»، فصارت تُقرأ وتُحفظ.

_STAGE_LEVEL_COUNT = {"ابتدائي": 6, "متوسط": 3, "ثانوي": 3}
_STAGE_ORDINALS = {"1": "أول", "2": "ثاني", "3": "ثالث",
                   "4": "رابع", "5": "خامس", "6": "سادس"}
# ترميز نور لحقل «مرحلة المدرسة»
_STAGE_FROM_NOOR = {"1": "ابتدائي", "2": "متوسط", "3": "ثانوي"}


def get_school_stage() -> str:
    """مرحلة المدرسة الحالية. الافتراضي ثانوي حفاظاً على المدارس القائمة."""
    try:
        s = str(load_config().get("school_stage", "") or "").strip()
        if s in _STAGE_LEVEL_COUNT:
            return s
    except Exception:
        pass
    return "ثانوي"


def set_school_stage(stage: str) -> bool:
    """يثبّت المرحلة في الإعدادات (يُستدعى عند الاستيراد من نور)."""
    stage = str(stage or "").strip()
    if stage not in _STAGE_LEVEL_COUNT:
        return False
    try:
        from config_manager import load_config as _lc, save_config as _sc
        cfg = _lc()
        if cfg.get("school_stage") == stage:
            return False
        cfg["school_stage"] = stage
        _sc(cfg)
        try:
            from config_manager import invalidate_config_cache
            invalidate_config_cache()
        except Exception:
            pass
        print(f"[STAGE] مرحلة المدرسة: {stage}")
        return True
    except Exception as e:
        print(f"[STAGE] تعذّر حفظ المرحلة: {e}")
        return False


def stage_level_name(digit, stage: str = "") -> str:
    """'2' + متوسط  ->  'ثاني متوسط'."""
    stage = stage if stage in _STAGE_LEVEL_COUNT else get_school_stage()
    d = str(digit).strip()
    return f"{_STAGE_ORDINALS.get(d, d)} {stage}"


def stage_level_count(stage: str = "") -> int:
    stage = stage if stage in _STAGE_LEVEL_COUNT else get_school_stage()
    return _STAGE_LEVEL_COUNT.get(stage, 3)


def _stage_ordinal_digit(text: str) -> str:
    """يستخرج رقم المستوى من نص عربي مثل 'الخامس الابتدائي' -> '5'."""
    t = str(text or "")
    for d, word in _STAGE_ORDINALS.items():
        if word in t:
            return d
    # صيغ بديلة شائعة في مخرجات نور
    for alt, d in (("الاول", "1"), ("اول", "1"), ("أولى", "1"), ("اولى", "1"),
                   ("ثانيه", "2"), ("ثانية", "2"), ("ثالثه", "3"), ("ثالثة", "3"),
                   ("رابعه", "4"), ("رابعة", "4"), ("خامسه", "5"), ("خامسة", "5"),
                   ("سادسه", "6"), ("سادسة", "6")):
        if alt in t:
            return d
    return ""


def _stage_from_text(text: str) -> str:
    """يستنتج المرحلة من نص (اسم المدرسة أو قيمة الصف)."""
    t = str(text or "")
    for st in ("ابتدائي", "متوسط", "ثانوي"):
        if st in t:
            return st
    return ""


def section_label_from_value(v: str, level: str = "") -> str:
    """يحوّل رقم الفصل إلى حرف عربي مع دعم تسمية هندسة للثاني والثالث ثانوي."""
    x = norm_token(v)
    # تنظيف قيم العشرية مثل "1.0" → "1"
    if x.endswith(".0") and x[:-2].isdigit():
        x = x[:-2]
    # أرقام → حروف مع مراعاة المرحلة
    num_map = {"1":"أ","2":"ب","3":"ج","4":"د","5":"هـ","6":"و"}
    # للثاني والثالث ثانوي: الفصل 5 = هندسة
    num_map_eng = {"1":"أ","2":"ب","3":"ج","4":"د","5":"هندسة","6":"هندسة 2"}
    lvl = norm_token(level)
    # «هندسة» مسار ثانوي فقط — في المتوسط والابتدائي الفصل 5 هو «هـ»
    use_eng = (get_school_stage() == "ثانوي"
               and lvl in {"ثاني ثانوي", "ثالث ثانوي", "2", "3"})
    chosen_map = num_map_eng if use_eng else num_map
    if x in chosen_map: return chosen_map[x]
    # حروف لاتينية
    latin_map = {"A":"أ","B":"ب","C":"ج","D":"د","E":"هـ","F":"و"}
    return latin_map.get(x.upper(), x or "1")

def display_name_from_legacy(cid: str) -> str:
    if not cid: return ""
    m = re.match(r"^\s*(1314|1416|1516)\s*-\s*(.+)\s*$", str(cid))
    if not m: return ""
    level = stage_level_name({"1314": "1", "1416": "2", "1516": "3"}[m.group(1)])
    return f"{level} - فصل {section_label_from_value(m.group(2))}"

def level_name_from_value(v: str) -> str:
    x = norm_token(v)
    digits = "".join(ch for ch in x if ch.isdigit())
    # المرحلة المذكورة داخل النص نفسها أولى من مرحلة المدرسة المحفوظة
    stage = _stage_from_text(x) or get_school_stage()
    if digits in {"1314", "1416", "1516"}:
        return stage_level_name({"1314": "1", "1416": "2", "1516": "3"}[digits], stage)
    # ترتيب عربي مكتوب: «الخامس الابتدائي» ، «الثاني المتوسط»
    d = _stage_ordinal_digit(x)
    if d:
        return stage_level_name(d, stage)
    xl = x
    for junk in ("الصف", "مرحلة", "ابتدائي", "الابتدائي", "متوسط",
                 "المتوسط", "ثانوي", "الثانوي"):
        xl = xl.replace(junk, "")
    xl = xl.strip()
    arab_digits = {"١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6"}
    xl = arab_digits.get(xl, xl)
    if xl.isdigit() and 1 <= int(xl) <= stage_level_count(stage):
        return stage_level_name(xl, stage)
    return stage_level_name("1", stage)

def _read_excel_safe(xlsx_path: str):
    """
    يقرأ ملف Excel بطريقة آمنة تتجاوز مشاكل الـ styles.
    يجرب عدة محركات ويعود إلى القراءة المباشرة كـ ZIP إذا فشلت كلها.
    يُرجع: dict {sheet_name: [[row_values], ...]}
    """
    import zipfile, xml.etree.ElementTree as ET
    ext = os.path.splitext(xlsx_path)[1].lower()

    # ─── محاولة 1: xlrd للملفات القديمة .xls ─────────────────
    if ext == ".xls":
        try:
            xl = pd.ExcelFile(xlsx_path, engine="xlrd")
            result = {}
            for sname in xl.sheet_names:
                df = pd.read_excel(xlsx_path, sheet_name=sname, header=None, dtype=str, engine="xlrd")
                result[sname] = df.values.tolist()
            return result
        except Exception:
            pass

    # ─── محاولة 2: openpyxl العادي ────────────────────────────
    try:
        xl = pd.ExcelFile(xlsx_path, engine="openpyxl")
        result = {}
        for sname in xl.sheet_names:
            df = pd.read_excel(xlsx_path, sheet_name=sname, header=None, dtype=str, engine="openpyxl")
            result[sname] = df.values.tolist()
        return result
    except Exception:
        pass

    # ─── محاولة 3: قراءة مباشرة كـ ZIP (تتجاوز مشكلة styles) ─
    try:
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        with zipfile.ZipFile(xlsx_path) as z:
            # اقرأ Shared Strings
            strings = []
            if "xl/sharedStrings.xml" in z.namelist():
                ss_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in ss_root.findall(f"{{{ns}}}si"):
                    t = si.find(f"{{{ns}}}t")
                    if t is not None:
                        strings.append(t.text or "")
                    else:
                        parts = si.findall(f".//{{{ns}}}t")
                        strings.append("".join(p.text or "" for p in parts))

            # اقرأ أسماء الأوراق
            wb_root = ET.fromstring(z.read("xl/workbook.xml"))
            sheet_els = wb_root.findall(f".//{{{ns}}}sheet")
            # رسم العلاقات: rId → ملف الورقة
            rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
            rid_map = {r.get("Id"): r.get("Target")
                       for r in rels_root.findall(f"{{{rel_ns}}}Relationship")}

            result = {}
            for sel in sheet_els:
                sname = sel.get("name", "")
                rid   = sel.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
                target = rid_map.get(rid, "")
                if not target.startswith("xl/"):
                    target = "xl/" + target
                if target not in z.namelist():
                    continue

                ws_root = ET.fromstring(z.read(target))
                rows_els = ws_root.findall(f".//{{{ns}}}row")
                sheet_rows = []
                for row_el in rows_els:
                    cells = row_el.findall(f"{{{ns}}}c")
                    row_data = []
                    for c in cells:
                        t_attr = c.get("t", "")
                        v = c.find(f"{{{ns}}}v")
                        val = ""
                        if v is not None and v.text is not None:
                            val = v.text
                            if t_attr == "s":
                                try:
                                    val = strings[int(val)]
                                except Exception:
                                    val = ""
                        row_data.append(val)
                    sheet_rows.append(row_data)
                result[sname] = sheet_rows
        return result
    except Exception as e:
        raise ValueError(f"تعذّر قراءة الملف بأي طريقة: {e}")


# ═══════════════════════════════════════════════════════════════
#  ترميز صفوف نور — قابل للتعديل من المزوّد
# ═══════════════════════════════════════════════════════════════
# نور يُصدّر "رقم الصف" كرمز خام (1314، 1416، 1516، 1518 ...) يختلف
# بين المدارس والمسارات. بدل تثبيته في الكود، يُقرأ من ملف يمكن
# تعديله، وأي رمز جديد يُضاف إليه تلقائياً عند أول استيراد ليُراجَع.
NOOR_LEVELS_JSON = os.path.join(DATA_DIR, "noor_levels.json")

_DEFAULT_NOOR_LEVELS = {
    "1314": {"digit": "1", "name": "أول ثانوي"},
    "1416": {"digit": "2", "name": "ثاني ثانوي"},
    "1516": {"digit": "3", "name": "ثالث ثانوي"},
    # صفوف/فصول تُستبعد من الاستيراد — مثال: ["1518", "1416/2"]
    "_exclude": [],
}


def load_noor_levels() -> dict:
    """يقرأ ترميز الصفوف، ويُنشئ الملف بالقيم الافتراضية عند غيابه."""
    try:
        if os.path.exists(NOOR_LEVELS_JSON):
            with open(NOOR_LEVELS_JSON, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
    except Exception as e:
        print(f"[NOOR-LEVELS] تعذّرت القراءة: {e}")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        _safe_write_json(NOOR_LEVELS_JSON, _DEFAULT_NOOR_LEVELS)
    except Exception:
        pass
    return dict(_DEFAULT_NOOR_LEVELS)


def remember_noor_level(code: str, digit: str, name: str, needs_review: bool = False):
    """يضيف رمزاً جديداً للملف ليراه المزوّد ويصحّحه إن لزم."""
    try:
        levels = load_noor_levels()
        if code in levels:
            return
        levels[code] = {"digit": digit, "name": name, "auto": True}
        if needs_review:
            levels[code]["needs_review"] = True
        _safe_write_json(NOOR_LEVELS_JSON, levels)
        print(f"[NOOR-LEVELS] أُضيف الرمز {code} -> {name} في {NOOR_LEVELS_JSON}")
    except Exception as e:
        print(f"[NOOR-LEVELS] تعذّرت الإضافة: {e}")


def load_noor_excludes() -> set:
    """
    قائمة الصفوف/الفصول المستبعدة من الاستيراد (طلاب الانتساب مثلاً).

    تُكتب في data/noor_levels.json تحت المفتاح "_exclude" بأي من الصيغتين:
        "1518"      ← استبعاد رمز صف كامل
        "1416/2"    ← استبعاد فصل واحد داخل صف
    طلاب الانتساب لا يُعاملون معاملة المنتظمين، فوجودهم في الكشوف
    يشوّه نسب الغياب ويُرسل تنبيهات لا محل لها.
    """
    try:
        raw = load_noor_levels().get("_exclude", [])
        if isinstance(raw, str):
            raw = [raw]
        return {str(x).strip() for x in raw if str(x).strip()}
    except Exception:
        return set()


def is_noor_excluded(level_raw, section_raw, excludes: set) -> bool:
    """هل يقع هذا الطالب ضمن الصفوف/الفصول المستبعدة؟"""
    if not excludes:
        return False
    lvl = "".join(ch for ch in str(level_raw) if ch.isdigit())
    sec = str(section_raw).strip().split(".")[0]
    return bool(lvl) and (lvl in excludes or f"{lvl}/{sec}" in excludes)


def lookup_noor_level(raw: str):
    """يبحث عن الرمز في الترميز. يُرجع (digit, name) أو (None, None)."""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if not digits:
        return None, None
    e = load_noor_levels().get(digits)
    if digits != "_exclude" and isinstance(e, dict) and e.get("digit") and e.get("name"):
        return str(e["digit"]), str(e["name"])
    return None, None


# الرموز المجهولة التي صادفها الاستيراد الحالي — تُعرض للمزوّد في نهايته
_NOOR_UNKNOWN: dict = {}
_NOOR_WARNED: set = set()


def _noor_resolve(raw: str):
    """
    يُرجع (رقم المستوى، اسمه) لقيمة 'رقم الصف' كما يُصدّرها نور.

    ترتيب المصادر: نص صريح ← ملف الترميز ← الرموز المدمجة ← البادئة
    (للثانوي فقط) ← خانة مستقلة للمجهول.

    المجهول لا يُدمج في المستوى الأول كما كان يحدث: رمزان مجهولان
    مختلفان كانا يصيران فصلاً واحداً، فتُسجَّل غيابات طالب على فصل
    ليس فصله. صار لكل رمز مجهول مستوى خاص ظاهر يصحّحه المزوّد.
    """
    raw = str(raw).strip()
    stage = _stage_from_text(raw) or get_school_stage()
    digits = "".join(ch for ch in raw if ch.isdigit())

    # ① نص عربي صريح: «الأول الثانوي_السنة المشتركة» / «الخامس الابتدائي»
    d = _stage_ordinal_digit(raw)
    if d and int(d) <= stage_level_count(stage):
        return d, stage_level_name(d, stage)

    # ② ملف الترميز data/noor_levels.json — المصدر الذي يملكه المزوّد
    _d, _n = lookup_noor_level(raw)
    if _d and _n:
        # الملف الافتراضي ثانويّ. لو استوردته مدرسة متوسطة صارت فصولها
        # «أول ثانوي» بصمت، فنُصحّح الاسم لمرحلة المدرسة ونُنبّه.
        _mapped_stage = _stage_from_text(_n)
        if _mapped_stage and _mapped_stage != stage:
            fixed = stage_level_name(_d, stage)
            if digits not in _NOOR_WARNED:      # مرة لكل رمز لا لكل طالب
                _NOOR_WARNED.add(digits)
                print(f"[NOOR-IMPORT] ⚠️ الترميز يقول «{_n}» ومرحلة المدرسة"
                      f" {stage} — اعتُمد «{fixed}»؛ راجع ملف الترميز")
            return str(_d), fixed
        return str(_d), str(_n)

    # ③ الرموز الثانوية المدمجة — للثانوي وحده. تطبيقها على متوسطة
    #    كان يُسمّي فصولها «أول ثانوي» رغم أن المرحلة معروفة ومخالفة.
    if stage == "ثانوي" and digits in {"1314", "1416", "1516"}:
        d = {"1314": "1", "1416": "2", "1516": "3"}[digits]
        return d, stage_level_name(d, "ثانوي")

    # ④ بادئة رموز نور الثانوية: 13xx/14xx/15xx. صالحة للثانوي وحده —
    #    تطبيقها على متوسطة أو ابتدائية يخترع مستويات لا وجود لها.
    if stage == "ثانوي" and len(digits) == 4:
        pref = {"13": "1", "14": "2", "15": "3"}.get(digits[:2])
        if pref:
            nm = stage_level_name(pref, "ثانوي")
            print(f"[NOOR-IMPORT] رمز صف غير معروف ({digits}) — استُنتج {nm} من البادئة")
            remember_noor_level(digits, pref, nm)
            return pref, nm

    # ⑤ رقم مباشر ضمن مدى المرحلة
    if digits and 1 <= int(digits or 0) <= stage_level_count(stage) and len(digits) == 1:
        return digits, stage_level_name(digits, stage)

    # ⑥ مجهول — خانة مستقلة، لا دمج
    key = digits or raw or "?"
    if key not in _NOOR_UNKNOWN:
        slot = stage_level_count(stage) + len(_NOOR_UNKNOWN) + 1
        name = f"صف غير معرّف ({key})"
        _NOOR_UNKNOWN[key] = (str(slot), name)
        print(f"[NOOR-IMPORT] ⚠️ رمز صف مجهول ({key}) — وُضع في مستوى مستقل بانتظار الترميز")
        remember_noor_level(key, str(slot), name, needs_review=True)
    return _NOOR_UNKNOWN[key]


def _noor_level_name(raw: str) -> str:
    """اسم المستوى الموحّد لقيمة 'رقم الصف' من نور."""
    return _noor_resolve(raw)[1]


def _noor_level_digit(raw: str) -> str:
    """رقم المستوى المستخدم في معرّف الفصل."""
    return _noor_resolve(raw)[0]


def _noor_build_class_name(level_name: str, section_label: str) -> str:
    """يبني اسم الفصل مع المسار إذا كان موجوداً."""
    return f"{level_name} / {section_label}"


def _detect_school_stage(all_sheets: dict) -> str:
    """
    يستخرج مرحلة المدرسة من ورقة School Info في ملف نور ويحفظها.

    نور يكتب فيها صفّاً بعنوان «مرحلة المدرسة» وقيمته 1/2/3 أو نصّاً
    صريحاً، وقد يذكر المرحلة داخل «اسم المدرسة». بدونها كانت مدرسة
    متوسطة تُستورد فتصير فصولها كلها «أول ثانوي».
    """
    stage = ""
    try:
        for rows in all_sheets.values():
            for row in rows[:15]:
                cells = [str(c).strip() for c in row
                         if c is not None and str(c).strip().lower() not in ("nan", "none", "")]
                if not cells:
                    continue
                joined = " ".join(cells)
                if "مرحلة المدرسة" in joined:
                    for c in cells:
                        if "مرحلة" in c:
                            continue
                        v = c[:-2] if c.endswith(".0") and c[:-2].isdigit() else c
                        stage = _STAGE_FROM_NOOR.get(v, "") or _stage_from_text(v)
                        if stage:
                            break
                if not stage and "اسم المدرسة" in joined:
                    stage = _stage_from_text(joined)
                if stage:
                    break
            if stage:
                break
    except Exception as e:
        print(f"[STAGE] تعذّرت قراءة مرحلة المدرسة: {e}")

    if stage:
        set_school_stage(stage)
        return stage
    print(f"[STAGE] لم تُذكر المرحلة في الملف — يُعتمد المحفوظ: {get_school_stage()}")
    return get_school_stage()


def import_students_from_excel_sheet2_format(xlsx_path: str) -> Dict[str, Any]:
    """
    يستورد بيانات الطلاب من Excel — يدعم جميع الصيغ:

    الصيغة 1 (الكلاسيكية): أعمدة رقم الطالب، اسم الطالب، رقم الصف (رقم)، الفصل، رقم الجوال
    الصيغة 2 (نور الجديدة): الجوال، الفصل، رقم الصف (نص كامل)، اسم الطالب، رقم الطالب
    الصيغة 3 (ملفات bkp/قديمة): legacy IDs مثل 1314-1 لتمييز المستويات

    ⬅ مرن تلقائياً — لا يحتاج تدخل المستخدم.
    """
    # ─── قراءة الملف بطريقة آمنة ────────────────────────────────
    all_sheets = _read_excel_safe(xlsx_path)

    # ─── مرحلة المدرسة من ورقة School Info ──────────────────────
    # يجب أن تُقرأ قبل أي تسمية مستوى، لأن كل الأسماء تُبنى عليها.
    _NOOR_UNKNOWN.clear()
    _NOOR_WARNED.clear()
    _detect_school_stage(all_sheets)

    # ─── أسماء الأعمدة المعروفة ──────────────────────────────────
    # الأعمدة الإلزامية للبحث
    STUDENT_ID_COLS  = {"رقم الطالب", "رقم الهوية", "الرقم الأكاديمي", "رقم_الطالب"}
    STUDENT_NM_COLS  = {"اسم الطالب", "الاسم", "اسم_الطالب"}
    LEVEL_COLS       = {"رقم الصف", "المرحلة", "الصف", "رقم_الصف"}
    SECTION_COLS     = {"الفصل", "رقم الفصل", "رقم_الفصل"}
    PHONE_COLS       = {"رقم الجوال", "الجوال", "جوال", "رقم_الجوال", "phone"}

    BLANK = {"nan", "none", ""}

    def clean(v):
        s = str(v).strip() if v is not None else ""
        if s.endswith(".0") and s[:-2].isdigit():
            s = s[:-2]
        return s

    def find_col(cols_set, header_row):
        """يبحث عن أول عمود يطابق أيًا من الأسماء المعروفة."""
        for i, h in enumerate(header_row):
            if clean(h) in cols_set:
                return i
        return None

    def is_blank(v):
        return clean(v).lower() in BLANK

    # ─── ابحث عن الورقة والصف المناسبَين ────────────────────────
    found_sheet   = None
    found_hdr_idx = None
    found_rows    = None

    for sname, rows in all_sheets.items():
        for i, row in enumerate(rows[:30]):
            row_vals = {clean(v) for v in row if v is not None and clean(v)}
            # تحقق من وجود عمودَي الطالب على الأقل
            has_id   = bool(row_vals & STUDENT_ID_COLS)
            has_name = bool(row_vals & STUDENT_NM_COLS)
            if has_id and has_name:
                found_sheet   = sname
                found_hdr_idx = i
                found_rows    = rows
                break
        if found_sheet:
            break

    if not found_sheet:
        raise ValueError(
            "تعذّر اكتشاف بيانات الطلاب تلقائيًا.\n"
            "تأكد من وجود أعمدة مثل: رقم الطالب، اسم الطالب، رقم الصف\n"
            f"الملف يحتوي على الأوراق: {list(all_sheets.keys())}"
        )

    hdr = [clean(v) for v in found_rows[found_hdr_idx]]
    data_rows = found_rows[found_hdr_idx + 1:]

    # ─── تحديد فهارس الأعمدة ────────────────────────────────────
    idx_id      = find_col(STUDENT_ID_COLS, hdr)
    idx_name    = find_col(STUDENT_NM_COLS, hdr)
    idx_level   = find_col(LEVEL_COLS,      hdr)
    idx_section = find_col(SECTION_COLS,    hdr)
    idx_phone   = find_col(PHONE_COLS,      hdr)

    if idx_id is None or idx_name is None:
        raise ValueError(f"لم يُعثر على عمود رقم الطالب أو اسم الطالب. الأعمدة الموجودة: {hdr}")

    # ─── دوال مساعدة داخلية ─────────────────────────────────────
    def get_cell(row, idx):
        if idx is None or idx >= len(row):
            return ""
        return clean(row[idx])

    LETTERS = ["أ", "ب", "ج", "د", "هـ", "و", "ز", "ح", "ط", "ي"]
    # تحويل الحروف العربية إلى إنجليزية لاستخدامها في روابط URL
    AR_TO_EN_SECTION = {
        "أ": "A", "ب": "B", "ج": "C", "د": "D", "هـ": "E",
        "و": "F", "ز": "G", "ح": "H", "ط": "I", "ي": "J",
        "ه": "E",
        # أقسام خاصة
        "هندسة": "ENG", "هندسة 2": "ENG2",
        "علوم": "SCI", "علوم حاسب": "CS", "إدارة": "MGT",
        "أدبي": "LIT", "علمي": "SCI2", "شريعة": "ISL",
    }

    def make_safe_class_id(level_digit, section_label, track=""):
        """يبني class_id آمناً لروابط URL (إنجليزي فقط، بدون حروف عربية)."""
        import re as _re
        sec_en = AR_TO_EN_SECTION.get(section_label, None)
        if sec_en is None:
            # حاول تحويل حرف بحرف
            sec_en = "".join(AR_TO_EN_SECTION.get(ch, ch) for ch in section_label)
        # احذف أي حرف غير آمن (حروف عربية أو رموز)
        sec_en = _re.sub(r'[^A-Za-z0-9]', '', sec_en)
        if not sec_en:
            # آخر ملاذ: hash قصير
            import hashlib as _hs
            sec_en = _hs.md5(section_label.encode()).hexdigest()[:4].upper()
        if track:
            track_safe = _re.sub(r'[^A-Za-z0-9]', '', track)
            if not track_safe:
                import hashlib as _hs
                track_safe = _hs.md5(track.encode()).hexdigest()[:4].upper()
            return f"{level_digit}-{sec_en}-{track_safe}"
        return f"{level_digit}-{sec_en}"

    def sort_key(v):
        try:
            return (0, int(v))
        except ValueError:
            return (1, v)

    # ─── المرور الأول: جمع أرقام الفصول الفريدة لكل مجموعة ──────
    # المجموعة = (raw_level) — لنبني خريطة رقم→حرف بناءً على الرتبة الفعلية
    # مثال: ثاني ثانوي لديه [1,3,4,5,6] → أ,ب,ج,د,هـ (رقم 2 غائب فلا يُفقد حرف)
    from collections import defaultdict
    group_sections: Dict[str, list] = defaultdict(list)

    # الصفوف/الفصول المستبعدة (طلاب الانتساب مثلاً) — تُستبعد في المرورين
    # معاً، وإلا احتُسبت في ترتيب الحروف فأزاحت أسماء الفصول الحقيقية.
    _excludes = load_noor_excludes()
    _skipped  = 0

    for row in data_rows:
        if not row:
            continue
        s_id   = get_cell(row, idx_id)
        s_name = get_cell(row, idx_name)
        if is_blank(s_id) or is_blank(s_name):
            continue
        raw_lv  = get_cell(row, idx_level)   if idx_level   is not None else ""
        raw_sec = get_cell(row, idx_section) if idx_section is not None else ""
        if is_noor_excluded(raw_lv, raw_sec, _excludes):
            continue
        if raw_sec and raw_sec not in group_sections[raw_lv]:
            group_sections[raw_lv].append(raw_sec)

    # رتّب الأرقام تصاعدياً وعيّن حرفاً لكل رتبة
    # {level_raw: {section_raw: letter}}
    group_section_map: Dict[str, Dict[str, str]] = {}
    for lv_raw, secs in group_sections.items():
        sorted_secs = sorted(secs, key=sort_key)
        group_section_map[lv_raw] = {
            sec: (LETTERS[i] if i < len(LETTERS) else str(i + 1))
            for i, sec in enumerate(sorted_secs)
        }

    # ─── المرور الثاني: بناء الفصول ─────────────────────────────
    classes: Dict[str, Dict[str, Any]] = {}

    for row in data_rows:
        if not row:
            continue
        student_id   = get_cell(row, idx_id)
        student_name = get_cell(row, idx_name)
        if is_blank(student_id) or is_blank(student_name):
            continue

        raw_level   = get_cell(row, idx_level)   if idx_level   is not None else ""
        raw_section = get_cell(row, idx_section) if idx_section is not None else ""
        raw_phone   = get_cell(row, idx_phone)   if idx_phone   is not None else ""

        if is_noor_excluded(raw_level, raw_section, _excludes):
            _skipped += 1
            continue

        phone = _clean_phone_noor(raw_phone)

        if raw_level:
            level_name  = _noor_level_name(raw_level)
            level_digit = _noor_level_digit(raw_level)
        else:
            level_digit = "1"
            level_name  = stage_level_name("1")

        # ─── الحرف بناءً على الرتبة الفعلية داخل المجموعة ────────
        sec_map = group_section_map.get(raw_level, {})
        if raw_section and sec_map:
            section_label = sec_map.get(raw_section, raw_section)
        elif raw_section:
            section_label = section_label_from_value(raw_section, level_name)
        else:
            section_label = "أ"

        # ─── class_id و class_name ───────────────────────────────
        if raw_level and "_" in raw_level:
            parts = raw_level.split("_", 1)
            track = parts[1].strip() if len(parts) > 1 else ""
            if track:
                class_id   = make_safe_class_id(level_digit, section_label, track)
                class_name = f"{level_name} ({track}) / {section_label}"
            else:
                class_id   = make_safe_class_id(level_digit, section_label)
                class_name = f"{level_name} / {section_label}"
        else:
            class_id   = make_safe_class_id(level_digit, section_label)
            class_name = f"{level_name} / {section_label}"

        if class_id not in classes:
            classes[class_id] = {"id": class_id, "name": class_name, "students": []}
        classes[class_id]["students"].append({
            "id":    student_id,
            "name":  student_name,
            "phone": phone,
        })

    if not classes:
        raise ValueError("لم يُعثر على أي طلاب في الملف — تحقق من صحة البيانات.")

    # ─── تقرير الاستيراد ────────────────────────────────────────
    # النسخة المبنية بلا نافذة أوامر (console=False)، فأي print هنا
    # لا يراه أحد. التقرير يُعاد مع النتيجة لتعرضه الواجهة.
    _notes = []
    if _skipped:
        _notes.append(f"استُبعد {_skipped} طالباً "
                      f"(صفوف/فصول مستبعدة: {', '.join(sorted(_excludes))})")
    if _NOOR_UNKNOWN:
        _codes = "، ".join(sorted(_NOOR_UNKNOWN))
        _notes.append(
            f"رموز صفوف لم يعرفها النظام: {_codes}\n"
            f"وُضع كل رمز في مستوى مستقل باسم «صف غير معرّف».\n"
            f"صحّح أسماءها في:\n{NOOR_LEVELS_JSON}\n"
            f"أو أضفها إلى \"_exclude\" إن كانوا منتسبين، ثم أعد الاستيراد.")
    for _n in _notes:
        print("[NOOR-IMPORT] " + _n.replace("\n", " | "))

    data = {"classes": list(classes.values())}
    _safe_write_json(STUDENTS_JSON, data)

    # تفاصيل كل رمز مجهول (العدد والفصول) لتعرضها نافذة الترميز —
    # المزوّد يقرّر بناءً على أعداد حقيقية لا على رمز مجرّد.
    _unknown = {}
    for _code, (_slot, _nm) in _NOOR_UNKNOWN.items():
        _own = [c for c in data["classes"]
                if str(c.get("id", "")).split("-", 1)[0] == str(_slot)]
        _unknown[_code] = {
            "name": _nm,
            "count": sum(len(c.get("students") or []) for c in _own),
            "sections": [str(c.get("id", "")).split("-", 1)[-1] for c in _own],
        }

    # مفاتيح التقرير تُضاف بعد الحفظ حتى لا تدخل students.json
    return {**data,
            "_stage": get_school_stage(),
            "_skipped": _skipped,
            "_unknown_levels": _unknown,
            "_notes": _notes}


def set_noor_level_mapping(code: str, digit: str, name: str) -> bool:
    """يثبّت ترميز رمز صف من نور (يستبدل أي قيمة سابقة ويزيل علامة المراجعة)."""
    try:
        levels = load_noor_levels()
        levels[str(code)] = {"digit": str(digit), "name": str(name)}
        _safe_write_json(NOOR_LEVELS_JSON, levels)
        return True
    except Exception as e:
        print(f"[NOOR-LEVELS] تعذّر حفظ الترميز: {e}")
        return False


def set_noor_exclude(code: str, excluded: bool = True) -> bool:
    """يضيف/يزيل رمز صف أو فصل من قائمة الاستبعاد (الانتساب)."""
    try:
        levels = load_noor_levels()
        cur = levels.get("_exclude") or []
        if isinstance(cur, str):
            cur = [cur]
        cur = [str(x) for x in cur]
        code = str(code)
        if excluded and code not in cur:
            cur.append(code)
        elif not excluded and code in cur:
            cur.remove(code)
        levels["_exclude"] = cur
        # الرمز المستبعد لا يحتاج ترميز مستوى
        if excluded:
            levels.pop(code, None)
        _safe_write_json(NOOR_LEVELS_JSON, levels)
        return True
    except Exception as e:
        print(f"[NOOR-LEVELS] تعذّر حفظ الاستبعاد: {e}")
        return False


def noor_level_options(stage: str = "") -> list:
    """خيارات المستويات المتاحة لمرحلة المدرسة: [('1','أول متوسط'), ...]"""
    stage = stage if stage in _STAGE_LEVEL_COUNT else get_school_stage()
    return [(str(i), stage_level_name(str(i), stage))
            for i in range(1, stage_level_count(stage) + 1)]


def noor_import_report(result: dict) -> str:
    """نص جاهز للعرض في نافذة بعد الاستيراد — فارغ إن لم يكن ثمة ما يُقال."""
    try:
        notes = (result or {}).get("_notes") or []
        if not notes:
            return ""
        return "⚠️ ملاحظات على ملف نور\n\n" + "\n\n".join(notes)
    except Exception:
        return ""

# ═══════════════════════════════════════════════════════════════
# دوال المصادقة والمستخدمين
# ═══════════════════════════════════════════════════════════════
def hash_password(pw: str) -> str:
    """PBKDF2-SHA256 بملح عشوائي — انظر security.py."""
    return _sec.hash_password(pw)

def authenticate(username: str, password: str):
    """يتحقق من المستخدم — يُرجع dict المستخدم أو None."""
    client = get_cloud_client()
    if client.is_active():
        # في وضع السحاب، نستخدم الـ API للتحقق
        res = client.post("/web/api/login", {"username": username, "password": password})
        if res.get("ok"):
            # الـ API يُرجع role و name في المستوى الأول وليس داخل "user"
            role        = res.get("role", "admin")
            author_name = res.get("name", username)
            # احفظ المستخدم محلياً حتى تعمل get_user_allowed_tabs بشكل صحيح
            try:
                _con = get_db(); _cur = _con.cursor()
                _cur.execute("""
                    INSERT INTO users (username,password,role,full_name,active,created_at,allowed_tabs)
                    VALUES (?,?,?,?,1,?,?)
                    ON CONFLICT(username) DO UPDATE
                    SET role=excluded.role, full_name=excluded.full_name,
                        allowed_tabs=COALESCE(excluded.allowed_tabs, allowed_tabs)
                """, (username, "", role, author_name,
                      datetime.datetime.utcnow().isoformat(),
                      json.dumps(res.get("allowed_tabs")) if res.get("allowed_tabs") else None))
                _con.commit(); _con.close()
            except Exception as _e:
                print(f"[AUTH-CACHE] {_e}")
            return {"username": username, "role": role, "full_name": author_name}
        return None

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username=? AND active=1", (username,))
    row = cur.fetchone()
    if not row:
        con.close()
        return None
    stored = row["password"]
    if not _sec.verify_password(password, stored):
        con.close()
        return None

    # ترقية صامتة للتجزئة القديمة (SHA-256) إلى PBKDF2 عند أول دخول ناجح
    if _sec.needs_rehash(stored):
        try:
            cur.execute("UPDATE users SET password=? WHERE username=?",
                        (_sec.hash_password(password), username))
            con.commit()
        except Exception:
            pass

    # تحديث وقت آخر دخول
    try:
        cur.execute("UPDATE users SET last_login=? WHERE username=?",
                    (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), username))
        con.commit()
    except: pass

    user_dict = dict(row)
    user_dict.pop("password", None)   # لا تُمرَّر التجزئة خارج هذه الدالة
    # تنبيه الواجهة إذا كانت كلمة المرور ما زالت الافتراضية admin123
    user_dict["default_password"] = (password == "admin123")
    con.close()
    return user_dict

def get_user_info(username: str):
    """يُرجع معلومات المستخدم من لقاعدة البيانات."""
    # في وضع السحاب وغيره: نقرأ من قاعدة البيانات المحلية (مُحدَّثة عند تسجيل الدخول)
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT username, role, full_name, active FROM users WHERE username=?", (username,))
    row = cur.fetchone(); con.close()
    return dict(row) if row else None

def get_user_allowed_tabs(username: str):
    """يُرجع قائمة التبويبات المسموحة للمستخدم، أو None إذا كان admin."""
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT role, allowed_tabs FROM users WHERE username=?", (username,))
    row = cur.fetchone(); con.close()
    if not row:
        from constants import CURRENT_USER, ROLE_TABS as _RT
        role = CURRENT_USER.get("role", "teacher")
        if role == "admin": return None
        return _RT.get(role)
    if row["role"] == "admin": return None  # admin يرى كل شيء
    role_defaults = ROLE_TABS.get(row["role"]) or []
    if row["allowed_tabs"]:
        import json as _j
        try:
            stored = _j.loads(row["allowed_tabs"])
            # دمج التبويبات الجديدة من ROLE_TABS التي لم تكن موجودة وقت الحفظ
            merged = list(stored) + [t for t in role_defaults if t not in stored]
            return merged
        except:
            pass
    return role_defaults

def save_user_allowed_tabs(username: str, tabs: list):
    """يحفظ قائمة التبويبات المسموحة للمستخدم."""
    import json as _j
    client = get_cloud_client()
    if client.is_active():
         client.post("/web/api/users/allowed-tabs", {"username": username, "tabs": tabs})
         return

    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET allowed_tabs=? WHERE username=?",
                (_j.dumps(tabs, ensure_ascii=False), username))
    con.commit(); con.close()

def query_permissions(date_filter=None):
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/permissions", params={"date": date_filter})
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    q, params = "SELECT * FROM permissions WHERE 1=1", []
    if date_filter: q += " AND date=?"; params.append(date_filter)
    cur.execute(q + " ORDER BY created_at DESC", params)
    rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows

def get_all_users():
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/sync/users")
        if res.get("ok"):
            return res.get("users", [])

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT id,username,role,full_name,active,COALESCE(phone,'') as phone, last_login FROM users ORDER BY role,username")
    rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows


def save_user_phone(username: str, phone: str):
    """يحفظ رقم جوال المستخدم."""
    client = get_cloud_client()
    if client.is_active():
        client.post("/web/api/users/phone", {"username": username, "phone": phone})
        return

    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET phone=? WHERE username=?", (phone.strip(), username))
    con.commit(); con.close()

def create_user(username, password, role, full_name="", phone=""):
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/users/create", {
            "username": username, "password": password, "role": role, 
            "full_name": full_name, "phone": phone
        })
        return res.get("ok", False), res.get("msg", "Error")

    try:
        con = get_db(); cur = con.cursor()
        cur.execute(
            "INSERT INTO users (username,password,role,full_name,phone,active,created_at) VALUES (?,?,?,?,?,?,?)",
            (username, hash_password(password), role, full_name, phone, 1,
             datetime.datetime.utcnow().isoformat()))
        con.commit(); con.close(); return True, "تم إنشاء المستخدم"
    except sqlite3.IntegrityError:
        return False, "اسم المستخدم موجود مسبقاً"

def update_user_password(username, new_password):
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/users/update-password", {"username": username, "password": new_password})
        if not res.get("ok"):
            raise Exception(res.get("msg", "فشل تغيير كلمة المرور على السيرفر"))
        return

    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET password=? WHERE username=?",
                (hash_password(new_password), username))
    con.commit(); con.close()

def update_user(username, role, full_name="", phone=""):
    """تحديث بيانات المستخدم الأساسية."""
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/users/update", {
            "username": username, "role": role, "full_name": full_name, "phone": phone
        })
        return res.get("ok", False), res.get("msg", "Error")

    try:
        con = get_db(); cur = con.cursor()
        cur.execute(
            "UPDATE users SET role=?, full_name=?, phone=?, allowed_tabs=NULL WHERE username=?",
            (role, full_name, phone, username))
        con.commit(); con.close(); return True, "تم تحديث البيانات بنجاح"
    except Exception as e:
        return False, str(e)

def toggle_user_active(user_id, active):
    client = get_cloud_client()
    if client.is_active():
        client.post("/web/api/users/toggle-active", {"user_id": user_id, "active": active})
        return

    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE users SET active=? WHERE id=?", (active, user_id))
    con.commit(); con.close()

def delete_user(user_id):
    client = get_cloud_client()
    if client.is_active():
        client.delete(f"/web/api/users/{user_id}")
        return

    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM users WHERE id=? AND username!='admin'", (user_id,))
    con.commit(); con.close()

# ═══════════════════════════════════════════════════════════════
# دوال التأخر
# ═══════════════════════════════════════════════════════════════
def insert_tardiness(date_str, class_id, class_name, student_id,
                     student_name, teacher_name, period, minutes_late=0):
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/add-tardiness", {
            "date": date_str, "student_id": student_id, "student_name": student_name,
            "class_id": class_id, "class_name": class_name,
            "period": period, "minutes_late": minutes_late
        })
        return res.get("ok", False)

    if is_student_exempted(student_id):
        return False

    created_at = datetime.datetime.utcnow().isoformat()
    # كان except يلتقط IntegrityError وحدها، فخطأ القفل يخرج دون إغلاق
    # الاتصال — يتسرّب حاملاً القفل وتفشل الكتابات التالية كلها.
    con = get_db()
    try:
        cur = con.cursor()
        cur.execute("""INSERT OR IGNORE INTO tardiness
            (date,class_id,class_name,student_id,student_name,
             teacher_name,period,minutes_late,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (date_str,class_id,class_name,student_id,student_name,
             teacher_name,period,minutes_late,created_at))
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        try:
            con.close()
        except Exception:
            pass

def delete_tardiness(rec_id):
    client = get_cloud_client()
    if client.is_active():
        client.delete(f"/web/api/tardiness/{rec_id}")
        return

    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM tardiness WHERE id=?", (rec_id,))
    con.commit(); con.close()

def query_tardiness(date_filter=None, student_id=None, class_id=None):
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/tardiness", params={"date": date_filter, "student_id": student_id, "class_id": class_id})
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    q, p = "SELECT * FROM tardiness WHERE 1=1", []
    if date_filter: q += " AND date=?";   p.append(date_filter)
    if student_id:  q += " AND student_id=?"; p.append(student_id)
    if class_id:    q += " AND class_id=?";   p.append(class_id)
    cur.execute(q + " ORDER BY date DESC, created_at DESC", p)
    rows = [dict(r) for r in cur.fetchall()]
    
    # تصفية المستثنين
    cur.execute("SELECT student_id FROM exempted_students")
    exempted_ids = {r[0] for r in cur.fetchall()}
    con.close()
    
    rows = [r for r in rows if r["student_id"] not in exempted_ids]
    return rows

def compute_tardiness_metrics(date_str):
    rows = query_tardiness(date_filter=date_str)
    by_class = {}
    for r in rows:
        cid = r["class_id"]
        if cid not in by_class:
            by_class[cid] = {"class_name": r["class_name"], "count": 0, "total_minutes": 0}
        by_class[cid]["count"] += 1
        by_class[cid]["total_minutes"] += r.get("minutes_late", 0)
    return {"total": len(rows), "by_class": by_class, "rows": rows}

# ═══════════════════════════════════════════════════════════════
# دوال الأعذار
# ═══════════════════════════════════════════════════════════════
EXCUSE_REASONS = [
    "مرض", "وفاة في العائلة", "ظروف طارئة",
    "إجازة رسمية", "عذر طبي", "أخرى"
]

def insert_excuse(date_str, student_id, student_name, class_id,
                   class_name, reason, source="admin", approved_by=""):
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/add-excuse", {
            "date": date_str, "student_id": student_id, "student_name": student_name,
            "class_id": class_id, "class_name": class_name, "reason": reason
        })
        return res.get("ok", False)

    created_at = datetime.datetime.utcnow().isoformat()
    con = get_db(); cur = con.cursor()
    cur.execute("""INSERT OR IGNORE INTO excuses
        (date,student_id,student_name,class_id,class_name,
         reason,source,approved_by,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (date_str,student_id,student_name,class_id,class_name,
         reason,source,approved_by,created_at))
    con.commit(); con.close()

def delete_excuse(rec_id):
    client = get_cloud_client()
    if client.is_active():
        client.delete(f"/web/api/excuses/{rec_id}")
        return

    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM excuses WHERE id=?", (rec_id,))
    con.commit(); con.close()

def query_excuses(date_filter=None, student_id=None):
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/excuses", params={"date": date_filter, "student_id": student_id})
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    q, p = "SELECT * FROM excuses WHERE 1=1", []
    if date_filter: q += " AND date=?";   p.append(date_filter)
    if student_id:  q += " AND student_id=?"; p.append(student_id)
    cur.execute(q + " ORDER BY date DESC", p)
    rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows

def student_has_excuse(student_id, date_str):
    """هل للطالب عذر مقبول في هذا اليوم؟"""
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT 1 FROM excuses WHERE student_id=? AND date=? LIMIT 1",
                (student_id, date_str))
    found = cur.fetchone() is not None; con.close(); return found

# ═══════════════════════════════════════════════════════════════
# النسخ الاحتياطية
# ═══════════════════════════════════════════════════════════════
def create_backup(target_dir=None):
    """ينشئ نسخة احتياطية مضغوطة من DB + JSON."""
    if target_dir is None:
        target_dir = BACKUP_DIR
    os.makedirs(target_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(target_dir, f"backup_{ts}.zip")
    try:
        with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as zf:
            # قاعدة البيانات
            if os.path.exists(DB_PATH):
                zf.write(DB_PATH, os.path.basename(DB_PATH))
            # ملفات JSON
            for jf in [STUDENTS_JSON, TEACHERS_JSON, CONFIG_JSON]:
                if os.path.exists(jf):
                    zf.write(jf, os.path.basename(jf))
            # مجلد تقارير المدرسة
            if os.path.isdir(SCHOOL_REPORTS_DIR):
                for _fn in os.listdir(SCHOOL_REPORTS_DIR):
                    _fp = os.path.join(SCHOOL_REPORTS_DIR, _fn)
                    if os.path.isfile(_fp):
                        zf.write(_fp, os.path.join("school_reports", _fn))
            # مرفقات الرسائل الداخلية
            if os.path.isdir(INBOX_ATTACHMENTS_DIR):
                for _fn in os.listdir(INBOX_ATTACHMENTS_DIR):
                    _fp = os.path.join(INBOX_ATTACHMENTS_DIR, _fn)
                    if os.path.isfile(_fp):
                        zf.write(_fp, os.path.join("inbox_attachments", _fn))
        size_kb = os.path.getsize(filename) // 1024
        # سجّل في قاعدة البيانات
        con = get_db(); cur = con.cursor()
        cur.execute("INSERT INTO backup_log (filename,size_kb,created_at) VALUES (?,?,?)",
                    (filename, size_kb, datetime.datetime.utcnow().isoformat()))
        con.commit(); con.close()
        # احتفظ بآخر 30 نسخة فقط
        _cleanup_old_backups(target_dir, keep=60)
        return True, filename, size_kb
    except Exception as e:
        return False, str(e), 0

def _cleanup_old_backups(backup_dir, keep=30):
    files = sorted(
        [f for f in os.listdir(backup_dir) if f.startswith("backup_") and f.endswith(".zip")],
        reverse=True
    )
    for old in files[keep:]:
        try: os.remove(os.path.join(backup_dir, old))
        except Exception: pass

def get_backup_list():
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM backup_log ORDER BY created_at DESC LIMIT 50")
    rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows

def upload_backup_telegram(zip_path: str) -> bool:
    """يرفع ملف النسخة الاحتياطية إلى Telegram — يقرأ الإعدادات من config.json."""
    try:
        import requests as _req
        cfg = load_config()
        token   = cfg.get("telegram_backup_token", "").strip()
        chat_id = cfg.get("telegram_backup_chat", "").strip()
        if not token or not chat_id:
            return False
        url  = f"https://api.telegram.org/bot{token}/sendDocument"
        date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        caption  = f"🗄️ نسخة احتياطية تلقائية\n📅 {date_str}\n📦 {os.path.basename(zip_path)}"
        with open(zip_path, "rb") as f:
            r = _req.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (os.path.basename(zip_path), f, "application/zip")},
                timeout=120
            )
        if r.status_code == 200:
            print(f"[BACKUP-TG] ✅ تم الرفع إلى Telegram")
            return True
        print(f"[BACKUP-TG] ❌ فشل: {r.text[:200]}")
        return False
    except Exception as e:
        print(f"[BACKUP-TG] ❌ خطأ: {e}")
        return False

def schedule_auto_backup(root_widget, interval_hours=24):
    """يجدول نسخ احتياطي تلقائي كل X ساعة مع رفع خارجي إلى Telegram."""
    def do_backup():
        ok, path, size = create_backup()
        if ok:
            print(f"[BACKUP] ✅ نسخة احتياطية: {os.path.basename(path)} ({size} KB)")
            # رفع خارجي في خيط منفصل حتى لا يعطّل الواجهة
            import threading
            threading.Thread(
                target=upload_backup_telegram,
                args=(path,),
                daemon=True,
                name="backup-upload"
            ).start()
        else:
            print(f"[BACKUP] ❌ فشل: {path}")
        ms = interval_hours * 3600 * 1000
        root_widget.after(ms, do_backup)
    # أول نسخة بعد 5 دقائق من التشغيل
    root_widget.after(300 * 1000, do_backup)


def load_students(force_reload: bool = False) -> Dict[str, Any]:
    if constants.STUDENTS_STORE and not force_reload:
        return constants.STUDENTS_STORE
    
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/students")
        if res.get("ok"):
            classes = res.get("classes", [])
            constants.STUDENTS_STORE = {"list": classes, "by_id": {c["id"]: c for c in classes}}
            # حفظ في الملف المحلي فقط إذا كانت البيانات غير فارغة — يمنع محو الطلاب عند خطأ الخادم
            if classes:
                try:
                    ensure_dirs()
                    _safe_write_json(STUDENTS_JSON, {"classes": classes})
                except Exception as e:
                    print(f"[SYNC-STUDENTS-ERROR] {e}")
            return constants.STUDENTS_STORE

    ensure_dirs()
    if os.path.exists(STUDENTS_JSON):
        with open(STUDENTS_JSON, "r", encoding="utf-8") as f: data = json.load(f)
        classes = data.get("classes", [])
    else:
        # إذا لم يكن الملف موجوداً، لا تجبر المستخدم على الاستيراد إذا كان في وضع السحاب
        if client.is_active():
            return {"list": [], "by_id": {}}
            
        # ⚠️ لا تفتح أي نافذة حوار إلا من الخيط الرئيسي.
        # استدعاء tkinter من خيط الخادم (uvicorn) يُجمّد حلقة الأحداث كلها
        # فيتوقف الموقع بالكامل — وهذا يحدث لأي مدرسة جديدة لم تستورد
        # طلابها بعد بمجرد فتح لوحة التحكم من المتصفح.
        import threading as _th
        if _th.current_thread() is not _th.main_thread():
            print("[STUDENTS] ملف الطلاب غير موجود — لا استيراد من خيط خلفي")
            return {"list": [], "by_id": {}}

        try:
            from main import root as main_root
            parent = main_root
        except Exception:
            parent = None

        if parent:
            confirm = messagebox.askyesno("بيانات الطلاب مفقودة", 
                                         "ملف الطلاب غير موجود. هل تريد استيراد ملف Excel الآن؟", parent=parent)
        else:
            # إذا لم نجد النافذة الرئيسية، نكتفي بالعودة بقائمة فارغة
            return {"list": [], "by_id": {}}
            
        if not confirm:
            return {"list": [], "by_id": {}}
            
        path = filedialog.askopenfilename(title="اختر ملف Excel (طلاب)", filetypes=[("Excel files","*.xlsx *.xls")], parent=parent)
        if not path: 
            return {"list": [], "by_id": {}}
        data = import_students_from_excel_sheet2_format(path)
        classes = data.get("classes", [])
    constants.STUDENTS_STORE = {"list": classes, "by_id": {c["id"]: c for c in classes}}
    return constants.STUDENTS_STORE

def save_students(classes_list: List[Dict[str, Any]]) -> bool:
    """يحفظ قائمة الطلاب في الملف المحلي أو يرسلها للسيرفر السحابي إذا كان مفعلًا."""
    if not classes_list:
        print("[SAVE-STUDENTS] رُفض الحفظ: القائمة فارغة")
        return False

    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/update-students", {"classes": classes_list})
        if not res.get("ok"):
            print(f"[CLOUD-SYNC-ERROR] {res.get('msg')}")
            return False

    # دائماً احفظ محلياً أيضاً كنسخة احتياطية أو كمرجع أساسي في وضع السيرفر
    try:
        from constants import STUDENTS_JSON, ensure_dirs
        ensure_dirs()
        _safe_write_json(STUDENTS_JSON, {"classes": classes_list})
        # تحديث المخزن في الذاكرة
        constants.STUDENTS_STORE = {"list": classes_list, "by_id": {c["id"]: c for c in classes_list}}
        return True
    except Exception as e:
        print(f"[SAVE-STUDENTS-ERROR] {e}")
        return False

def _clean_phone_noor(raw) -> str:
    """يحوّل رقم الجوال من صيغة نور (966XXXXXXXXX) إلى (05XXXXXXXXX)."""
    import re as _re
    if not raw or str(raw).strip() in ("nan","None",""): return ""
    digits = _re.sub(r"\D", "", str(raw).split(".")[0])
    if digits.startswith("966") and len(digits) == 12: return "0" + digits[3:]
    if digits.startswith("9660") and len(digits) == 13: return "0" + digits[4:]
    if digits.startswith("05") and len(digits) == 10: return digits
    if digits.startswith("5") and len(digits) == 9: return "0" + digits
    return digits if len(digits) >= 9 else ""

def import_teachers_from_excel(xlsx_path: str) -> Dict[str, Any]:
    """
    يقرأ ملف Excel للمعلمين — يدعم:
    1. ملف نور (header مدفون، الاسم في عمود 19، الجوال في عمود 3)
    2. ملف عادي بأعمدة: اسم المعلم، رقم الجوال
    """
    NAME_HINTS  = ["اسم المعلم", "المعلم", "الاسم", "اسم الموظف"]
    PHONE_HINTS = ["رقم الجوال", "الجوال", "phone", "telephone"]
    
    ID_HINTS    = ["رقم الهوية", "رقم السجل", "السجل المدني", "الهوية"]
    
    xls = pd.ExcelFile(xlsx_path)
    target_df = None

    for sheet_name in xls.sheet_names:
        # اقرأ بدون header للبحث عن صف العناوين
        raw = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None, dtype=str)
        found_row = None
        for i, row in raw.iterrows():
            vals = [str(v).strip() for v in row.values]
            if any(h in v for h in NAME_HINTS for v in vals):
                found_row = i
                break
        if found_row is not None:
            target_df = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=found_row, dtype=str)
            target_df.columns = [str(c).strip() for c in target_df.columns]
            break

    if target_df is not None:
        # ملف بأعمدة واضحة
        name_col  = next((c for c in target_df.columns if any(h in c for h in NAME_HINTS)), None)
        phone_col = next((c for c in target_df.columns if any(h in c for h in PHONE_HINTS)), None)
        id_col    = next((c for c in target_df.columns if any(h in c for h in ID_HINTS)), None)
        if not name_col:
            raise ValueError("لم أجد عمود اسم المعلم في الملف.")
        teachers = []
        SKIP = {"nan","none","","اسم المعلم","اسم الموظف"}
        for _, row in target_df.iterrows():
            name = str(row.get(name_col,"")).strip()
            if name.lower() in SKIP or not name: continue
            phone_raw = str(row.get(phone_col,"")) if phone_col else ""
            id_raw = str(row.get(id_col,"")).strip() if id_col else ""
            if id_raw.endswith(".0"): id_raw = id_raw[:-2]
            teachers.append({"اسم المعلم": name, "رقم الجوال": _clean_phone_noor(phone_raw), "رقم الهوية": id_raw})
    else:
        # صيغة نور المعروفة: عمود 19 = الاسم، عمود 3 = الجوال، عمود 18 قد يكون السجل
        raw = pd.read_excel(xlsx_path, header=None, dtype=str)
        if raw.shape[1] < 20:
            raise ValueError("لم أتعرف على صيغة الملف. تأكد من أن يحتوي على أعمدة اسم المعلم ورقم الجوال.")
        teachers = []
        SKIP = {"nan","none","","اسم المعلم"}
        for _, row in raw.iterrows():
            name = str(row.iloc[19]).strip()
            if name.lower() in SKIP or not name: continue
            phone_raw = str(row.iloc[3])
            id_raw = str(row.iloc[18]).strip() if raw.shape[1] >= 19 else ""
            if id_raw.endswith(".0"): id_raw = id_raw[:-2]
            if not id_raw.isdigit() or len(id_raw) < 8: id_raw = ""
            teachers.append({"اسم المعلم": name, "رقم الجوال": _clean_phone_noor(phone_raw), "رقم الهوية": id_raw})

    if not teachers:
        raise ValueError("لم يُعثر على أي معلمين في الملف.")

    # أزل المكررات
    seen, unique = set(), []
    for t in teachers:
        n = t.get("اسم المعلم", "")
        if n and n not in seen:
            seen.add(n); unique.append(t)


    data = {"teachers": unique}
    with open(TEACHERS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data

def load_teachers() -> Dict[str, Any]:
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/teachers")
        if res.get("ok"):
            teachers = res.get("teachers", [])
            data = {"teachers": teachers}
            # حفظ في الملف المحلي للمزامنة
            try:
                ensure_dirs()
                with open(TEACHERS_JSON, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[SYNC-TEACHERS-ERROR] {e}")
            return data

    if os.path.exists(TEACHERS_JSON):
        with open(TEACHERS_JSON, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
        # الملف الافتراضي المشحون قائمة [] بينما بقية الكود يتوقع
        # {"teachers": [...]} — فكان /web/api/teachers يفشل بـ 500 على
        # كل تثبيت جديد. نقبل الصيغتين ونُرجع الصيغة القياسية دائماً.
        if isinstance(raw, list):
            return {"teachers": raw}
        if isinstance(raw, dict):
            raw.setdefault("teachers", [])
            return raw
        return {"teachers": []}
    else:
        if client.is_active():
            return {"teachers": []}
            
        # نفس سبب load_students: نافذة حوار من خيط الخادم تُجمّد الموقع.
        # وهنا أخطر — إنشاء tk.Tk() جديد من خيط خلفي يُسقط العملية.
        import threading as _th
        if _th.current_thread() is not _th.main_thread():
            print("[TEACHERS] ملف المعلمين غير موجود — لا استيراد من خيط خلفي")
            return {"teachers": []}

        root = tk.Tk(); root.withdraw()
        confirm = messagebox.askyesno("بيانات المعلمين مفقودة", 
                                     "ملف المعلمين غير موجود. هل تريد استيراد الملف الآن؟")
        if not confirm:
            return {"teachers": []}
            
        path = filedialog.askopenfilename(title="اختر ملف Excel (معلمون)", filetypes=[("Excel files","*.xlsx *.xls")])
        if not path: 
            return {"teachers": []}
        return import_teachers_from_excel(path)

def force_sync_cloud_data():
    """يجبر النظام على سحب البيانات من السحاب وحفظها محلياً."""
    try:
        load_students(force_reload=True)
        load_teachers()
        _sync_config_from_server()
        return True
    except Exception as e:
        print(f"[FORCE-SYNC-ERROR] {e}")
        return False

def _sync_config_from_server():
    """يسحب config.json من السيرفر ويدمج الإعدادات المهمة محلياً."""
    try:
        client = get_cloud_client()
        if not client or not client.is_active():
            return
        resp = client.get("/web/api/config")
        # الـ endpoint يُرجع الإعدادات مباشرة بدون مغلف ok/config
        remote = resp if isinstance(resp, dict) and "school_name" in resp else resp.get("config", {})
        if not remote:
            return
        from config_manager import load_config, save_config, invalidate_config_cache
        local = load_config()
        # المفاتيح التي يجب مزامنتها من السيرفر
        SYNC_KEYS = [
            "school_name", "school_gender",
            "tardiness_message_template", "message_template",
            "alert_absence_threshold", "alert_tardiness_threshold",
            "period_times", "school_start_time",
        ]
        changed = False
        for key in SYNC_KEYS:
            if key in remote and remote[key] != local.get(key):
                local[key] = remote[key]
                changed = True
        if changed:
            save_config(local)
            invalidate_config_cache()
            print("[CLOUD-SYNC] تم تحديث الإعدادات من السيرفر")
    except Exception as e:
        print(f"[CLOUD-SYNC-CONFIG-ERROR] {e}")

def _apply_class_name_fix(rows: List[Dict[str,Any]]) -> List[Dict[str,Any]]:
    if not rows: return rows
    store = load_students()
    by_id = store.get("by_id", {})
    for r in rows:
        old_cid = r.get("class_id", "")
        cid = normalize_legacy_class_id(old_cid)
        r["class_id"] = cid
        if cid in by_id: r["class_name"] = by_id[cid]["name"]
        elif (legacy_name := display_name_from_legacy(old_cid)): r["class_name"] = legacy_name
        else:
            parts = str(cid).split("-", 1)
            if len(parts) == 2 and parts[0] in _STAGE_ORDINALS:
                level = stage_level_name(parts[0])
                r["class_name"] = f"{level} - فصل {section_label_from_value(parts[1])}"
            else: r["class_name"] = r.get("class_name", old_cid)
    return rows


# ═══════════════════════════════════════════════════════════════
# تحويلات الطلاب — student_referrals CRUD
# ═══════════════════════════════════════════════════════════════
def create_student_referral(data: dict) -> int:
    """يُنشئ تحويل طالب جديد ويُعيد الـ id."""
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/referrals/create", data)
        return res.get("id", 0) if res.get("ok") else 0

    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("""
        INSERT INTO student_referrals
        (ref_date,student_id,student_name,class_id,class_name,
         subject,period,session_time,session_ampm,
         violation_type,violation,problem_causes,repeat_count,
         teacher_action1,teacher_action2,teacher_action3,teacher_action4,teacher_action5,
         teacher_name,teacher_username,teacher_date,status,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("ref_date",""), data.get("student_id",""), data.get("student_name",""),
        data.get("class_id",""), data.get("class_name",""),
        data.get("subject",""), data.get("period",""),
        data.get("session_time",""), data.get("session_ampm","ص"),
        data.get("violation_type","سلوكية"), data.get("violation",""),
        data.get("problem_causes",""), data.get("repeat_count","الأول"),
        data.get("teacher_action1",""), data.get("teacher_action2",""),
        data.get("teacher_action3",""), data.get("teacher_action4",""),
        data.get("teacher_action5",""), data.get("teacher_name",""),
        data.get("teacher_username",""), data.get("teacher_date",""),
        "pending", now
    ))
    ref_id = cur.lastrowid
    con.commit(); con.close()
    return ref_id

def get_referrals_for_teacher(teacher_username: str) -> list:
    """يُعيد كل تحويلات المعلم."""
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/referrals/teacher", params={"username": teacher_username})
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("""SELECT * FROM student_referrals
                   WHERE teacher_username=? ORDER BY created_at DESC""",
                (teacher_username,))
    rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows

def get_all_referrals(status_filter: str = None) -> list:
    """يُعيد كل التحويلات (للوكيل/المدير)."""
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/referrals/all", params={"status": status_filter})
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    if status_filter:
        cur.execute("SELECT * FROM student_referrals WHERE status=? ORDER BY created_at DESC",
                    (status_filter,))
    else:
        cur.execute("SELECT * FROM student_referrals ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows

def get_referral_by_id(ref_id: int) -> dict:
    """يُعيد تفاصيل تحويل واحد."""
    client = get_cloud_client()
    if client.is_active():
        res = client.get(f"/web/api/referrals/detail/{ref_id}")
        return res.get("row", {}) if res.get("ok") else {}

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM student_referrals WHERE id=?", (ref_id,))
    row = cur.fetchone(); con.close()
    return dict(row) if row else {}

def update_referral_deputy(ref_id: int, data: dict):
    """يحفظ إجراءات الوكيل على التحويل."""
    client = get_cloud_client()
    if client.is_active():
        data["id"] = ref_id
        client.post("/web/api/referrals/update-deputy", data)
        return

    con = get_db(); cur = con.cursor()
    new_status = data.get("status", "with_deputy")
    cur.execute("""UPDATE student_referrals SET
        status=?, deputy_meeting_date=?, deputy_meeting_period=?,
        deputy_action1=?, deputy_action2=?, deputy_action3=?, deputy_action4=?,
        deputy_name=?, deputy_date=?, deputy_referred_date=?
        WHERE id=?
    """, (
        new_status,
        data.get("deputy_meeting_date",""), data.get("deputy_meeting_period",""),
        data.get("deputy_action1",""), data.get("deputy_action2",""),
        data.get("deputy_action3",""), data.get("deputy_action4",""),
        data.get("deputy_name",""), data.get("deputy_date",""),
        data.get("deputy_referred_date",""), ref_id
    ))
    con.commit(); con.close()

def update_referral_counselor(ref_id: int, data: dict):
    """يحفظ إجراءات الموجه على التحويل."""
    client = get_cloud_client()
    if client.is_active():
        data["id"] = ref_id
        client.post("/web/api/referrals/update-counselor", data)
        return

    con = get_db(); cur = con.cursor()
    new_status = data.get("status", "with_counselor")
    cur.execute("""UPDATE student_referrals SET
        status=?, counselor_meeting_date=?, counselor_meeting_period=?,
        counselor_action1=?, counselor_action2=?, counselor_action3=?, counselor_action4=?,
        counselor_name=?, counselor_date=?, counselor_referred_back_date=?
        WHERE id=?
    """, (
        new_status,
        data.get("counselor_meeting_date",""), data.get("counselor_meeting_period",""),
        data.get("counselor_action1",""), data.get("counselor_action2",""),
        data.get("counselor_action3",""), data.get("counselor_action4",""),
        data.get("counselor_name",""), data.get("counselor_date",""),
        data.get("counselor_referred_back_date",""), ref_id
    ))
    con.commit(); con.close()

def close_referral(ref_id: int):
    """يُغلق التحويل (تم الحل)."""
    client = get_cloud_client()
    if client.is_active():
        client.post("/web/api/referrals/close", {"id": ref_id})
        return

    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE student_referrals SET status='resolved' WHERE id=?", (ref_id,))
    con.commit(); con.close()

def get_deputy_phones() -> list:
    """يُعيد أرقام جوالات المستخدمين ذوي دور وكيل."""
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/users/deputy-phones")
        return res.get("phones", []) if res.get("ok") else []

    con = get_db(); cur = con.cursor()
    cur.execute("SELECT phone FROM users WHERE role='deputy' AND active=1 AND phone!='' AND phone IS NOT NULL")
    phones = [r[0] for r in cur.fetchall()]; con.close(); return phones

def get_counselor_phones() -> list:
    """يُعيد أرقام جوالات الموجّهين من config.json."""
    try:
        from config_manager import load_config
        cfg = load_config()
        phones = []
        for key in ("counselor1_phone", "counselor2_phone"):
            p = cfg.get(key, "").strip()
            if p:
                phones.append(p)
        return phones
    except Exception:
        return []

# ═══════════════════════════════════════════════════════════════
# خطابات الاستفسار الأكاديمي (الموجه ← المعلم)
# ═══════════════════════════════════════════════════════════════
def create_academic_inquiry(data: dict) -> int:
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/create-academic-inquiry", data)
        return res.get("id", 0) if res.get("ok") else 0

    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("""
        INSERT INTO academic_inquiries
        (date, counselor_name, teacher_username, teacher_name,
         class_name, subject, student_name,
         teacher_reply_date, teacher_reply_reasons, teacher_reply_evidence,
         status, inquiry_type, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("date", ""), data.get("counselor_name", ""),
        data.get("teacher_username", ""), data.get("teacher_name", ""),
        data.get("class_name", ""), data.get("subject", ""),
        data.get("student_name", ""),
        "", "", "", "جديد", data.get("inquiry_type", "تدني ملحوظ"), now
    ))
    inq_id = cur.lastrowid
    con.commit(); con.close()
    return inq_id

def get_academic_inquiries(teacher_username: str = None) -> list:
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/academic-inquiries")
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    if teacher_username:
        cur.execute("SELECT * FROM academic_inquiries WHERE teacher_username=? ORDER BY created_at DESC", (teacher_username,))
    else:
        cur.execute("SELECT * FROM academic_inquiries ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows

def get_academic_inquiry(inq_id: int) -> dict:
    client = get_cloud_client()
    if client.is_active():
        res = client.get(f"/web/api/academic-inquiry/{inq_id}")
        return res.get("row", {}) if res.get("ok") else {}

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM academic_inquiries WHERE id=?", (inq_id,))
    row = cur.fetchone(); con.close(); return dict(row) if row else {}

def reply_academic_inquiry(inq_id: int, data: dict):
    client = get_cloud_client()
    if client.is_active():
        # نرسل الـ id مع البيانات
        data["id"] = inq_id
        client.post("/web/api/reply-academic-inquiry", data)
        return

    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("""
        UPDATE academic_inquiries
        SET teacher_reply_date=?, teacher_reply_reasons=?, teacher_reply_evidence=?, status=?, inquiry_type=?
        WHERE id=?
    """, (
        data.get("date", now.split("T")[0]),
        data.get("reasons", ""),
        data.get("evidence", ""),
        "تم الرد",
        data.get("inquiry_type", ""),
        inq_id
    ))
    con.commit(); con.close()


# ─── وظائف الموجه الطلابي المضافة للمزامنة ──────────────────────────

def insert_counselor_session(data: dict) -> int:
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/counselor/session/create", data)
        return res.get("id", 0) if res.get("ok") else 0

    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("""
        INSERT INTO counselor_sessions (date, student_id, student_name, class_name, reason, notes, action_taken, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("date", now.split("T")[0]),
        data.get("student_id"), data.get("student_name"),
        data.get("class_name"), data.get("reason"),
        data.get("notes"), data.get("action_taken"), now
    ))
    new_id = cur.lastrowid
    con.commit(); con.close()
    return new_id

def get_counselor_sessions(student_id: str = None) -> list:
    client = get_cloud_client()
    if client.is_active():
        params = {"student_id": student_id} if student_id else {}
        res = client.get("/web/api/counselor/sessions", params=params)
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    if student_id:
        cur.execute("SELECT * FROM counselor_sessions WHERE student_id=? ORDER BY date DESC, created_at DESC", (student_id,))
    else:
        cur.execute("SELECT * FROM counselor_sessions ORDER BY date DESC, created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows

def delete_counselor_session(sess_id: int):
    client = get_cloud_client()
    if client.is_active():
        client.delete(f"/web/api/counselor/session/{sess_id}")
        return

    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM counselor_sessions WHERE id=?", (sess_id,))
    con.commit(); con.close()

def insert_counselor_alert(data: dict) -> int:
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/counselor/alert/create", data)
        return res.get("id", 0) if res.get("ok") else 0

    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("""
        INSERT INTO counselor_alerts (date, student_id, student_name, type, method, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("date", now.split("T")[0]),
        data.get("student_id"), data.get("student_name"),
        data.get("type"), data.get("method"),
        data.get("status"), now
    ))
    new_id = cur.lastrowid
    con.commit(); con.close()
    return new_id

def get_counselor_alerts(student_id: str = None) -> list:
    client = get_cloud_client()
    if client.is_active():
        params = {"student_id": student_id} if student_id else {}
        res = client.get("/web/api/counselor/alerts", params=params)
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    if student_id:
        cur.execute("SELECT * FROM counselor_alerts WHERE student_id=? ORDER BY date DESC", (student_id,))
    else:
        cur.execute("SELECT * FROM counselor_alerts ORDER BY date DESC")
    rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows

def insert_behavioral_contract(data: dict) -> int:
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/counselor/contract/create", data)
        return res.get("id", 0) if res.get("ok") else 0

    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("""
        INSERT INTO behavioral_contracts
        (date, student_id, student_name, class_name, subject, period_from, period_to, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("date"), data.get("student_id"), data.get("student_name"),
        data.get("class_name"), data.get("subject"), data.get("period_from"),
        data.get("period_to"), data.get("notes"), now
    ))
    new_id = cur.lastrowid
    con.commit(); con.close()
    return new_id

def get_behavioral_contracts(student_id: str = None) -> list:
    client = get_cloud_client()
    if client.is_active():
        params = {"student_id": student_id} if student_id else {}
        res = client.get("/web/api/counselor/contracts", params=params)
        return res.get("rows", []) if res.get("ok") else []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    if student_id:
        cur.execute("SELECT * FROM behavioral_contracts WHERE student_id=? ORDER BY date DESC", (student_id,))
    else:
        cur.execute("SELECT * FROM behavioral_contracts ORDER BY date DESC, created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows

def delete_behavioral_contract(contract_id: int):
    client = get_cloud_client()
    if client.is_active():
        client.delete(f"/web/api/counselor/contract/{contract_id}")
        return

    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM behavioral_contracts WHERE id=?", (contract_id,))
    con.commit(); con.close()

# ===================== بناء التقارير HTML =====================

# ─── وظائف التعاميم الرسمية ──────────────────────────────────────────

def create_circular(data: Dict[str, Any]) -> int:
    """يُنشئ تعميماً جديداً بحرفية عالية."""
    client = get_cloud_client()
    if client.is_active():
        res = client.post("/web/api/circulars/create", data)
        return res.get("id", 0)

    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("""
        INSERT INTO circulars (date, title, content, attachment_path, created_by, target_role, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (data.get("date", now[:10]), data["title"], data.get("content", ""),
          data.get("attachment_path", ""), data["created_by"],
          data.get("target_role", "all"), now))
    new_id = cur.lastrowid
    con.commit(); con.close()
    return new_id

def get_circulars(username: str = None, role: str = None) -> List[Dict[str, Any]]:
    """يجلب التعاميم الموجهة للمستخدم، مع حالة القراءة بشكل صحيح وموحد."""
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/circulars/list")
        if res and isinstance(res, dict) and res.get("ok"):
            return res.get("rows", [])
        return []

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    # ضمان أن الدور في حالة صغيرة للمقارنة
    role = str(role).lower() if role else ""
    
    if role == "admin":
        # المدير يرى كل شيء مع عدد القراءات
        cur.execute("""
            SELECT c.*, 
                   (SELECT COUNT(*) FROM circular_reads r WHERE r.circular_id = c.id) as read_count,
                   1 as is_read
            FROM circulars c
            ORDER BY c.date DESC, c.id DESC
        """)
    else:
        # المستخدم العادي يرى الموجه له فقط (all أو دوره المحدد) + هل قرأه هو
        cur.execute("""
            SELECT c.*, 
                   (SELECT COUNT(*) FROM circular_reads r WHERE r.circular_id = c.id AND r.username = ?) as is_read
            FROM circulars c
            WHERE LOWER(c.target_role) = 'all' OR LOWER(c.target_role) = ?
            ORDER BY c.date DESC, c.id DESC
        """, (username, role))
    
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

def delete_circular(circular_id: int):
    """يحذف التعميم وسجلاته وملفه المرفق."""
    client = get_cloud_client()
    if client.is_active():
        client.delete(f"/web/api/circulars/{circular_id}")
        return

    con = get_db(); cur = con.cursor()
    # جلب مسار الملف قبل الحذف
    cur.execute("SELECT attachment_path FROM circulars WHERE id=?", (circular_id,))
    row = cur.fetchone()
    att_path = row[0] if row else ""
    
    # حذف سجلات القراءة والتعميم
    cur.execute("DELETE FROM circular_reads WHERE circular_id=?", (circular_id,))
    cur.execute("DELETE FROM circulars WHERE id=?", (circular_id,))
    con.commit(); con.close()
    
    # حذف الملف الفعلي إن وجد
    if att_path:
        full_path = os.path.join(DATA_DIR, att_path)
        if os.path.exists(full_path):
            try: os.remove(full_path)
            except: pass

def mark_circular_as_read(circular_id: int, username: str):
    """يسجل أن المستخدم قد قرأ التعميم."""
    client = get_cloud_client()
    if client.is_active():
        client.post("/web/api/circulars/mark-read", {"id": circular_id, "username": username})
        return

    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("INSERT OR IGNORE INTO circular_reads (circular_id, username, read_at) VALUES (?, ?, ?)",
                (circular_id, username, now))
    con.commit(); con.close()

def get_unread_circulars_count(username: str, role: str) -> int:
    """يحسب عدد التعاميم غير المقروءة الموجهة للمستخدم."""
    if role == "admin": return 0 # المدير لا يحتاج تنبيه لتعاميمه
    
    client = get_cloud_client()
    if client.is_active():
        res = client.get("/web/api/circulars/unread-count")
        return res.get("count", 0)

    con = get_db(); cur = con.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM circulars c
        WHERE (c.target_role = 'all' OR c.target_role = ?)
        AND NOT EXISTS (SELECT 1 FROM circular_reads r WHERE r.circular_id = c.id AND r.username = ?)
    """, (role, username))
    count = cur.fetchone()[0]
    con.close()
    return count

def get_student_analytics_data(student_id: str) -> Dict[str, Any]:
    """
    يجمع كافة البيانات التحليلية لطالب واحد من جميع الجداول.
    """
    con = get_db(); cur = con.cursor()
    data = {"absences": [], "tardiness": [], "referrals": [], "sessions": [], "results": None}

    # 1. جلب سجلات الغياب مرتبة حسب التاريخ
    cur.execute("SELECT date, period FROM absences WHERE student_id=? ORDER BY date ASC", (student_id,))
    data["absences"] = [{"date": r[0], "period": r[1]} for r in cur.fetchall()]

    # 2. جلب سجلات التأخر
    cur.execute("SELECT date, minutes_late, period FROM tardiness WHERE student_id=? ORDER BY date ASC", (student_id,))
    data["tardiness"] = [{"date": r[0], "minutes": r[1], "period": r[2]} for r in cur.fetchall()]

    # 3. جلب التحويلات السلوكية
    status_map = {
        "pending": "قيد الانتظار",
        "with_deputy": "لدى الوكيل",
        "with_counselor": "لدى الموجه الطلابي",
        "completed": "مكتمل",
        "accepted": "مقبول",
        "rejected": "مرفوض"
    }
    cur.execute("SELECT ref_date, violation_type, violation, status FROM student_referrals WHERE student_id=? ORDER BY ref_date DESC", (student_id,))
    data["referrals"] = []
    for r in cur.fetchall():
        st_ar = status_map.get(r[3], r[3])
        data["referrals"].append({"date": r[0], "type": r[1], "violation": r[2], "status": st_ar})

    # 4. جلسات التوجيه الطلابي
    cur.execute("SELECT date, reason, action_taken FROM counselor_sessions WHERE student_id=? ORDER BY date DESC", (student_id,))
    data["sessions"] = [{"date": r[0], "reason": r[1], "action": r[2]} for r in cur.fetchall()]

    # 5. آخر نتيجة دراسية
    cur.execute("SELECT gpa, class_rank, subjects_json, school_year, section_rank FROM student_results WHERE identity_no=? ORDER BY uploaded_at DESC LIMIT 1", (student_id,))
    row = cur.fetchone()
    if row:
        data["results"] = {
            "gpa":          row[0],
            "rank":         row[1],
            "subjects":     json.loads(row[2]) if row[2] else [],
            "year":         row[3],
            "section_rank": row[4],
        }


    # 6. تجميع البيانات المحسوبة للويب والرسوم البيانية
    from database import get_student_total_points, get_student_points_history
    data["total_points"] = get_student_total_points(student_id)
    data["points_history"] = [{"points": r["points"], "reason": r["reason"], "date": r["date"], 
                                "author_name": r.get("author_name", "مدير")} 
                               for r in get_student_points_history(student_id)]

    data["total_absences"] = len(data["absences"])
    data["total_tardiness"] = sum(r["minutes"] for r in data["tardiness"])
    data["behavior_referrals"] = len(data["referrals"])
    data["counselor_sessions"] = len(data["sessions"])
    
    gpa = "—"
    if data["results"] and data["results"].get("gpa"):
        gpa = f"{data['results']['gpa']}"
        if data["results"].get("rank"):
            gpa += f" (#{data['results']['rank']})"
    data["academic_results"] = gpa


    # الاحداث الأخيرة (دمج الكل وترتيبهم)

    # اتجاه الغياب (شهرياً)
    trend = {}
    for a in data["absences"]:
        m = a["date"][:7] # YYYY-MM
        trend[m] = trend.get(m, 0) + 1
    data["absence_trend"] = trend

    # الاحداث الأخيرة (دمج الكل وترتيبهم)
    status_map = {
        "pending": "قيد الانتظار",
        "with_deputy": "لدى الوكيل",
        "with_counselor": "لدى الموجه الطلابي",
        "completed": "مكتمل",
        "accepted": "مقبول",
        "rejected": "مرفوض"
    }

    events = []
    for r in data["absences"]:
        events.append({"date": r["date"], "type": "غياب", "details": f"الحصة: {r['period']}", "status": "مسجل"})
    for r in data["tardiness"]:
        events.append({"date": r["date"], "type": "تأخر", "details": f"تأخر {r['minutes']} دقيقة", "status": "مسجل"})
    for r in data["referrals"]:
        st = r["status"]
        st_ar = status_map.get(st, st) # الترجمة أو النص الأصلي إن لم يوجد
        events.append({"date": r["date"], "type": f"تحويل {r['type']}", "details": r["violation"], "status": st_ar})

    for r in data["sessions"]:
        events.append({"date": r["date"], "type": "جلسة إرشادية", "details": r["reason"], "status": "منتهية"})
    for r in data["points_history"]:
        auth = f" (بواسطة: {r['author_name']})" if r.get('author_name') else ""
        events.append({"date": r["date"], "type": "نقطة تميز", "details": f"{r['reason']}{auth}", "status": f"+{r['points']}"})
    
    events.sort(key=lambda x: x["date"], reverse=True)
    data["recent_events"] = events[:20]
    data["timeline"] = data["recent_events"] # للتوافق مع واجهة الويب

    # إجمالي أيام الدراسة الفعلية (أيام تم تسجيل غياب فيها لأي طالب)
    cur.execute("SELECT COUNT(DISTINCT date) FROM absences")
    row = cur.fetchone()
    data["total_school_days"] = max(row[0], 1) if row else 1

    # الأعذار المقبولة
    cur.execute("SELECT date FROM excuses WHERE student_id=?", (student_id,))
    excused_dates = {r[0] for r in cur.fetchall()}
    data["excused_count"]   = len(excused_dates)
    data["unexcused_count"] = max(0, len(data["absences"]) - len(excused_dates))

    # توزيع الغياب حسب يوم الأسبوع
    day_names = ["الاثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت","الأحد"]
    dow = {d: 0 for d in day_names}
    import datetime as _dt
    for a in data["absences"]:
        try:
            d = _dt.date.fromisoformat(a["date"])
            dow[day_names[d.weekday()]] += 1
        except: pass
    data["absence_by_dow"] = dow

    # الملاحظات الإدارية
    cur.execute("SELECT id, note, author, created_at FROM student_notes WHERE student_id=? ORDER BY created_at DESC", (student_id,))
    data["notes"] = [{"id": r[0], "note": r[1], "author": r[2], "created_at": r[3]} for r in cur.fetchall()]

    con.close()
    return data


def get_student_notes(student_id: str) -> list:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT id, note, author, created_at FROM student_notes WHERE student_id=? ORDER BY created_at DESC", (student_id,))
    rows = [{"id": r[0], "note": r[1], "author": r[2], "created_at": r[3]} for r in cur.fetchall()]
    con.close()
    return rows

def add_student_note(student_id: str, note: str, author: str) -> int:
    import datetime as _dt
    con = get_db(); cur = con.cursor()
    cur.execute("INSERT INTO student_notes (student_id, note, author, created_at) VALUES (?,?,?,?)",
                (student_id, note, author, _dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    new_id = cur.lastrowid
    con.commit(); con.close()
    return new_id

def delete_student_note(note_id: int):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM student_notes WHERE id=?", (note_id,))
    con.commit(); con.close()


def clear_student_results():
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM student_results")
    con.commit(); con.close()

# ─── CIRCULARS & NOTIFICATIONS ───────────────────────────────

def get_circulars(username: str = None, role: str = None):
    con = get_db(); cur = con.cursor()
    # التحقق من وجود الأعمدة لتجنب الأخطاء في حال لم يتم التحديث بعد
    cols = [r[1] for r in cur.execute("PRAGMA table_info(circulars)")]
    select_cols = ["id", "title", "content", "attachment_path", "date", "target_roles", "read_count"]
    if "created_by" in cols:
        select_cols.append("created_by")
    
    query = f"SELECT {','.join(select_cols)} FROM circulars ORDER BY id DESC"
    cur.execute(query)
    all_rows = cur.fetchall()
    
    # جلب قائمة التعاميم المقروءة لهذا المستخدم إذا وُجد
    read_ids = set()
    if username:
        cur.execute("SELECT circular_id FROM circular_reads WHERE username = ?", (username,))
        read_ids = {r[0] for r in cur.fetchall()}
        
    rows = []
    for r in all_rows:
        # خريطة الأعمدة
        res = {
            "id": r[0], "title": r[1], "content": r[2],
            "attachment_path": r[3], "date": r[4],
            "target_roles": r[5] or 'all',
            "read_count": r[6] or 0,
            "is_read": 1 if r[0] in read_ids else 0
        }
        if "created_by" in select_cols:
            res["created_by"] = r[select_cols.index("created_by")]
        else:
            res["created_by"] = "الإدارة"
            
        # التصفية حسب الدور
        target = res["target_roles"]
        if role and role != 'admin' and target != 'all':
            if role not in target:
                continue

        rows.append(res)
    con.close()
    return rows

def get_user_unread_circulars(username, all_circulars):
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT circular_id FROM circular_reads WHERE username = ?", (username,))
    read_ids = {r[0] for r in cur.fetchall()}
    con.close()
    
    unread = []
    for c in all_circulars:
        if c["id"] not in read_ids:
            unread.append(c)
    return unread

def get_unread_referrals_count():
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM behavioral_referrals WHERE status = 'pending'")
    row = cur.fetchone()
    con.close()
    return row[0] if row else 0

# ─── ADMIN POINTS MANAGEMENT FUNCTIONS ───

def get_admin_points_logs(limit=500):
    """
    سجل حركات النقاط مع اسم الطالب وفصله.

    كان يعمل JOIN مع جدول students_temp وهو غير موجود إطلاقاً — الطلاب
    يُخزَّنون في students.json لا في قاعدة البيانات — فكان المسار يفشل
    دائماً بخطأ 500. نجلب السجلات ثم نُثري الأسماء من ملف الطلاب.
    """
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("""
        SELECT * FROM student_points
        ORDER BY date DESC, id DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()

    # خريطة: رقم الطالب → (اسمه، اسم فصله)
    lookup = {}
    try:
        for c in load_students().get("list", []):
            cname = c.get("name", "")
            for s in c.get("students", []):
                lookup[str(s.get("id"))] = (s.get("name", ""), cname)
    except Exception as e:
        print(f"[POINTS-LOGS] تعذّر تحميل أسماء الطلاب: {e}")

    for r in rows:
        name, cname = lookup.get(str(r.get("student_id")), ("", ""))
        r.setdefault("student_name", name)
        r.setdefault("class_name", cname)
        if not r.get("student_name"):
            r["student_name"] = name or str(r.get("student_id", ""))
        if not r.get("class_name"):
            r["class_name"] = cname
    return rows

def get_teachers_points_usage(month_str):
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    # جلب كافة المعلمين والوكلاء
    cur.execute("SELECT username, full_name, role FROM users WHERE role IN ('teacher', 'deputy', 'activity_leader')")
    users = [dict(r) for r in cur.fetchall()]
    
    usage = []
    from config_manager import load_config
    base_limit = load_config().get("monthly_points_limit", 100)
    
    for u in users:
        # النقاط المستهلكة
        cur.execute("SELECT SUM(points) FROM student_points WHERE author_id = ? AND date LIKE ?", (u['username'], f"{month_str}%"))
        consumed = cur.fetchone()[0] or 0
        
        # الزيادات (الرصيد الإضافي)
        cur.execute("SELECT SUM(extra_points) FROM teacher_points_adjustments WHERE username = ? AND month = ?", (u['username'], month_str))
        extra = cur.fetchone()[0] or 0
        
        total_limit = base_limit + extra
        usage.append({
            "username": u['username'],
            "full_name": u['full_name'] or u['username'],
            "role": u['role'],
            "consumed": consumed,
            "extra": extra,
            "total_limit": total_limit,
            "remaining": max(0, total_limit - consumed)
        })
    con.close()
    return usage

def delete_points_record(record_id):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM student_points WHERE id = ?", (record_id,))
    con.commit(); con.close()

def adjust_teacher_balance(username, points, reason, month=None):
    if not month: month = datetime.date.today().isoformat()[:7]
    con = get_db(); cur = con.cursor()
    cur.execute("""
        INSERT INTO teacher_points_adjustments (username, month, extra_points, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (username, month, points, reason, datetime.datetime.now().isoformat()))
    con.commit(); con.close()


def get_unread_lab_submissions_count() -> int:
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM lab_doc_submissions WHERE is_read = 0")
        count = cur.fetchone()[0]
        con.close()
        return count
    except Exception:
        return 0


# ─── تقارير المعلمين ──────────────────────────────────────────

def save_teacher_report(form_type: str, title: str, submitted_by: str,
                        submitted_name: str, pdf_data: bytes) -> int:
    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("""
        INSERT INTO teacher_reports (form_type, title, submitted_by, submitted_name, submitted_at, pdf_data, is_read)
        VALUES (?, ?, ?, ?, ?, ?, 0)
    """, (form_type, title, submitted_by, submitted_name, now, pdf_data))
    report_id = cur.lastrowid
    con.commit(); con.close()
    return report_id

def get_teacher_reports() -> list:
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("""
            SELECT id, form_type, title, submitted_by, submitted_name, submitted_at, is_read
            FROM teacher_reports ORDER BY submitted_at DESC
        """)
        rows = [{"id": r[0], "form_type": r[1], "title": r[2],
                 "submitted_by": r[3], "submitted_name": r[4],
                 "submitted_at": r[5], "is_read": r[6]} for r in cur.fetchall()]
        con.close()
        return rows
    except Exception:
        return []

def get_teacher_report_pdf(report_id: int) -> bytes:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT pdf_data FROM teacher_reports WHERE id = ?", (report_id,))
    row = cur.fetchone()
    con.close()
    return bytes(row[0]) if row else b""

def mark_teacher_report_read(report_id: int):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE teacher_reports SET is_read = 1 WHERE id = ?", (report_id,))
    con.commit(); con.close()

def get_unread_teacher_reports_count() -> int:
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM teacher_reports WHERE is_read = 0")
        count = cur.fetchone()[0]
        con.close()
        return count
    except Exception:
        return 0

def delete_teacher_report(report_id: int):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM teacher_reports WHERE id = ?", (report_id,))
    con.commit(); con.close()


# ─── زيارات أولياء الأمور ─────────────────────────────────────

def insert_parent_visit(data: dict) -> int:
    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("""
        INSERT INTO parent_visits
            (date, visit_time, student_id, student_name, class_name,
             guardian_name, visit_reason, received_by, visit_result, notes,
             created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("date", now.split("T")[0]),
        data.get("visit_time", ""),
        data.get("student_id", ""),
        data.get("student_name", ""),
        data.get("class_name", ""),
        data.get("guardian_name", ""),
        data.get("visit_reason", ""),
        data.get("received_by", ""),
        data.get("visit_result", ""),
        data.get("notes", ""),
        data.get("created_by", ""),
        now,
    ))
    new_id = cur.lastrowid
    con.commit(); con.close()
    return new_id


def get_parent_visits(student_id: str = None, date_from: str = None,
                      date_to: str = None, limit: int = 300) -> list:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    q = "SELECT * FROM parent_visits WHERE 1=1"
    params = []
    if student_id:
        q += " AND student_id=?"; params.append(student_id)
    if date_from:
        q += " AND date>=?"; params.append(date_from)
    if date_to:
        q += " AND date<=?"; params.append(date_to)
    q += " ORDER BY date DESC, visit_time DESC LIMIT ?"
    params.append(limit)
    cur.execute(q, params)
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def delete_parent_visit(visit_id: int):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM parent_visits WHERE id=?", (visit_id,))
    con.commit(); con.close()


# ─── بوابة ولي الأمر — توكنات الوصول ────────────────────────────
import secrets as _secrets

def get_or_create_portal_token(student_id: str) -> str:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT token FROM parent_portal_tokens WHERE student_id=?", (student_id,))
    row = cur.fetchone()
    if row:
        con.close()
        return row[0]
    token = _secrets.token_urlsafe(24)
    now = datetime.datetime.now().isoformat()
    cur.execute("INSERT INTO parent_portal_tokens (student_id, token, created_at) VALUES (?,?,?)",
                (student_id, token, now))
    con.commit(); con.close()
    return token

def get_student_id_by_portal_token(token: str) -> Optional[str]:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT student_id FROM parent_portal_tokens WHERE token=?", (token,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None

# ══════════════════════════════════════════════════════════════════
#  الإجازات الرسمية
# ══════════════════════════════════════════════════════════════════

def add_holiday(date: str, label: str = "") -> bool:
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO holidays (date, label, created_at) VALUES (?,?,?)",
                    (date, label, datetime.datetime.now().isoformat()))
        con.commit(); con.close()
        return True
    except sqlite3.IntegrityError:
        con.close()
        return False

def remove_holiday(holiday_id: int):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM holidays WHERE id=?", (holiday_id,))
    con.commit(); con.close()

def get_holidays(year: str = None) -> List[Dict]:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    if year:
        cur.execute("SELECT * FROM holidays WHERE date LIKE ? ORDER BY date", (f"{year}%",))
    else:
        cur.execute("SELECT * FROM holidays ORDER BY date")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

def is_school_day(date_str: str) -> bool:
    """يعود بـ True إذا كان اليوم يوم دراسة (ليس جمعة/سبتاً ولا إجازة رسمية)."""
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        return False
    if d.weekday() in {4, 5}:  # الجمعة=4، السبت=5
        return False
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT 1 FROM holidays WHERE date=?", (date_str,))
    in_holiday = cur.fetchone() is not None
    con.close()
    return not in_holiday

# ══════════════════════════════════════════════════════════════════
#  إدارة الباصات
# ══════════════════════════════════════════════════════════════════
import hashlib as _bus_hashlib

def _bus_token(bus_id: int, date: str, trip_type: str) -> str:
    # السر فريد لكل تثبيت (security.get_secret) — الروابط مرتبطة بالتاريخ
    # فتتجدد يومياً تلقائياً، ولا يمكن توليدها من الكود المصدري.
    raw = f"{bus_id}:{date}:{trip_type}:{_sec.get_secret('bus')}"
    return _bus_hashlib.sha256(raw.encode()).hexdigest()[:24]

def get_all_buses() -> List[Dict]:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM buses WHERE active=1 ORDER BY name")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

def get_bus(bus_id: int) -> Optional[Dict]:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM buses WHERE id=?", (bus_id,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None

def create_bus(name: str, driver_name: str, driver_phone: str, route: str = "") -> int:
    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("INSERT INTO buses (name, driver_name, driver_phone, route, created_at) VALUES (?,?,?,?,?)",
                (name, driver_name, driver_phone, route, now))
    bus_id = cur.lastrowid
    con.commit(); con.close()
    return bus_id

def update_bus(bus_id: int, name: str, driver_name: str, driver_phone: str, route: str = "") -> bool:
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE buses SET name=?, driver_name=?, driver_phone=?, route=? WHERE id=?",
                (name, driver_name, driver_phone, route, bus_id))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok

def delete_bus(bus_id: int) -> bool:
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM buses WHERE id=?", (bus_id,))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok

def assign_students_to_bus(bus_id: int, student_ids: List[str]):
    con = get_db(); cur = con.cursor()
    cur.execute("DELETE FROM student_buses WHERE bus_id=?", (bus_id,))
    for sid in student_ids:
        cur.execute("INSERT OR REPLACE INTO student_buses (student_id, bus_id) VALUES (?,?)",
                    (str(sid), bus_id))
    con.commit(); con.close()

def get_students_in_bus(bus_id: int) -> List[str]:
    con = get_db(); cur = con.cursor()
    cur.execute("SELECT student_id FROM student_buses WHERE bus_id=?", (bus_id,))
    ids = [r[0] for r in cur.fetchall()]
    con.close()
    return ids

def get_or_create_bus_trip(bus_id: int, date: str, trip_type: str) -> Dict:
    token = _bus_token(bus_id, date, trip_type)
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM bus_trips WHERE bus_id=? AND date=? AND trip_type=?",
                (bus_id, date, trip_type))
    row = cur.fetchone()
    if row:
        con.close()
        return dict(row)
    now = datetime.datetime.now().isoformat()
    cur.execute("""INSERT INTO bus_trips (bus_id, date, trip_type, token, created_at)
                   VALUES (?,?,?,?,?)""", (bus_id, date, trip_type, token, now))
    trip_id = cur.lastrowid
    cur2 = con.cursor()
    cur2.execute("SELECT student_id FROM student_buses WHERE bus_id=?", (bus_id,))
    student_ids = [r[0] for r in cur2.fetchall()]
    students_store = load_students()
    by_id = {}
    for cls in students_store.get("list", []):
        for st in cls.get("students", []):
            by_id[str(st["id"])] = {"name": st.get("name", ""), "class": cls.get("name", "")}
    for sid in student_ids:
        info = by_id.get(str(sid), {})
        cur.execute("""INSERT OR IGNORE INTO bus_attendance
                       (trip_id, student_id, student_name, class_name, status)
                       VALUES (?,?,?,?,'pending')""",
                    (trip_id, sid, info.get("name", ""), info.get("class", "")))
    con.commit(); con.close()
    return {"id": trip_id, "bus_id": bus_id, "date": date, "trip_type": trip_type,
            "token": token, "sent_at": None, "created_at": now}

def get_bus_trip_by_token(token: str) -> Optional[Dict]:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("""SELECT bt.*, b.name as bus_name, b.driver_name
                   FROM bus_trips bt JOIN buses b ON b.id=bt.bus_id
                   WHERE bt.token=?""", (token,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None

def get_bus_trip_attendance(trip_id: int) -> List[Dict]:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM bus_attendance WHERE trip_id=? ORDER BY student_name", (trip_id,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

def record_bus_attendance(trip_id: int, student_id: str, status: str) -> bool:
    con = get_db(); cur = con.cursor()
    now = datetime.datetime.now().isoformat()
    cur.execute("""UPDATE bus_attendance SET status=?, recorded_at=?
                   WHERE trip_id=? AND student_id=?""",
                (status, now, trip_id, student_id))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok

def mark_bus_trip_sent(trip_id: int):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE bus_trips SET sent_at=? WHERE id=?",
                (datetime.datetime.now().isoformat(), trip_id))
    con.commit(); con.close()

def mark_driver_ready(trip_id: int):
    con = get_db(); cur = con.cursor()
    cur.execute("UPDATE bus_trips SET driver_ready_at=? WHERE id=?",
                (datetime.datetime.now().isoformat(), trip_id))
    con.commit(); con.close()

def get_bus_trips_summary(date: str) -> List[Dict]:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("""
        SELECT bt.*, b.name as bus_name, b.driver_name,
               COUNT(ba.id) as total_students,
               SUM(CASE WHEN ba.status='boarded' THEN 1 ELSE 0 END) as boarded,
               SUM(CASE WHEN ba.status='not_boarded' THEN 1 ELSE 0 END) as not_boarded
        FROM bus_trips bt
        JOIN buses b ON b.id=bt.bus_id
        LEFT JOIN bus_attendance ba ON ba.trip_id=bt.id
        WHERE bt.date=?
        GROUP BY bt.id
        ORDER BY b.name, bt.trip_type
    """, (date,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows



# ═══════════════════════════════════════════════════════════════
#  ترحيل الطلاب في نهاية العام
# ═══════════════════════════════════════════════════════════════
# لا يُفترض عدد الصفوف. المنطق القديم كان مثبَّتاً على ثلاثة (ثانوي)،
# فمدرسة ابتدائية تفقد طلاب صفها الثالث كأنهم تخرّجوا وتبقى صفوفها
# العليا مكانها.
#
# والابتدائي خاصةً لا ينضبط بقاعدة: بعض مدارس البنين تبدأ من الصف
# الثالث (الأول والثاني مع البنات) وبعضها يضم الستة. لذلك تُستنتج
# الخطة من الفصول الموجودة فعلاً، وتُعرض للمزوّد ليراجعها قبل التنفيذ.


def _class_level(cid) -> int:
    """رقم المستوى من معرّف الفصل: '3-A' -> 3. صفر إن تعذّر."""
    head = str(cid).split("-", 1)[0].strip()
    return int(head) if head.isdigit() else 0


def _class_suffix(cid) -> str:
    parts = str(cid).split("-", 1)
    return parts[1] if len(parts) > 1 else ""


_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"


def _derive_target_name(src_name: str, lvl: int, to_suffix: str) -> str:
    """
    يشتقّ اسم الفصل الهدف من اسم الفصل المصدر، حفاظاً على تسمية المدرسة.

    المدرسة قد تُسمّي فصولها «الصف 1 - فصل 2» لا «أول ثانوي / ب». لو بنينا
    اسم الفصل الجديد بالمخطط المدمج لظهر اسم دخيل بين إخوته — وهو ما حدث
    فعلاً في المدرسة الافتراضية: «الصف 1 - فصل 2» رُحِّل إلى «ثاني ثانوي / ب».

    الترتيب: اسم المستوى العربي إن ورد، ثم أول رقم مستوى مفرد (عربي أو
    هندي)، وإلا المخطط المدمج.
    """
    src_name = (src_name or "").strip()
    if not src_name:
        return _noor_build_class_name(
            stage_level_name(str(lvl + 1)),
            section_label_from_value(to_suffix, stage_level_name(str(lvl + 1))))

    # «أول ثانوي / ب»  ->  «ثاني ثانوي / ب»
    cur, nxt = stage_level_name(str(lvl)), stage_level_name(str(lvl + 1))
    if cur and cur in src_name:
        return src_name.replace(cur, nxt, 1)

    # «الصف 1 - فصل 2»  ->  «الصف 2 - فصل 2»  (أول رقم مستوى مفرد فقط)
    import re as _re
    if 0 <= lvl and lvl + 1 <= 9:
        for digits in ("0123456789", _AR_DIGITS):
            a, b = digits[lvl], digits[lvl + 1]
            m = _re.search(r"(?<!\d)%s(?!\d)" % _re.escape(a), src_name)
            if m:
                return src_name[:m.start()] + b + src_name[m.end():]

    return _noor_build_class_name(
        nxt, section_label_from_value(to_suffix, nxt))


def build_promotion_plan(classes=None) -> dict:
    """
    يبني خطة الترحيل من الفصول الموجودة.

    يُرجع:
      moves    [{from_id, from_name, to_id, to_name, count, target_exists}]
      graduate [{id, name, count}]   ← أعلى مستوى موجود
      levels   المستويات المكتشفة
      orphans  فصول بمعرّف لا يبدأ برقم — تُترك كما هي
    """
    if classes is None:
        classes = load_students(force_reload=True)["list"]

    levels = sorted({_class_level(c.get("id")) for c in classes} - {0})
    if not levels:
        return {"moves": [], "graduate": [], "levels": [], "orphans": classes}

    top = max(levels)
    by_id = {str(c.get("id")): c for c in classes}
    moves, graduate = [], []

    for c in classes:
        lvl = _class_level(c.get("id"))
        if lvl == 0:
            continue
        n = len(c.get("students") or [])
        if lvl == top:
            graduate.append({"id": c["id"], "name": c.get("name", ""), "count": n})
            continue
        suffix = _class_suffix(c["id"])
        to_id = f"{lvl + 1}-{suffix}"
        tgt = by_id.get(to_id)
        to_name = (tgt.get("name") if tgt else
                   _derive_target_name(c.get("name", ""), lvl, suffix))
        moves.append({"from_id": c["id"], "from_name": c.get("name", ""),
                      "to_id": to_id, "to_name": to_name, "count": n,
                      "target_exists": tgt is not None})

    # الأعلى مستوى يُرحَّل أولاً كي لا يُكتب فوق طلاب لم يُنقلوا بعد
    moves.sort(key=lambda m: -_class_level(m["from_id"]))
    orphans = [c for c in classes if _class_level(c.get("id")) == 0]
    return {"moves": moves, "graduate": graduate, "levels": levels,
            "orphans": orphans}


def apply_promotion_plan(plan: dict, graduate_top: bool = True) -> dict:
    """
    ينفّذ الخطة. `graduate_top=False` يُبقي طلاب أعلى مستوى مكانهم —
    لمدرسة لا يتخرّج صفها الأعلى (كابتدائية تنتهي عند صف وسيط).
    """
    classes = load_students(force_reload=True)["list"]
    by_id = {str(c.get("id")): c for c in classes}
    moved = graduated = created = 0

    if graduate_top:
        for g in plan.get("graduate", []):
            c = by_id.get(str(g["id"]))
            if c:
                graduated += len(c.get("students") or [])
                c["students"] = []

    for m in plan.get("moves", []):
        src = by_id.get(str(m["from_id"]))
        if not src or not src.get("students"):
            continue
        tgt = by_id.get(str(m["to_id"]))
        if tgt is None:
            tgt = {"id": m["to_id"], "name": m["to_name"], "students": []}
            classes.append(tgt)
            by_id[m["to_id"]] = tgt
            created += 1
        # إضافة لا استبدال: لو بقي في الفصل الهدف طلاب (حين لا يتخرّج
        # الصف الأعلى) فالاستبدال يمحوهم بصمت. الإضافة لا تفقد أحداً،
        # وفي المسار المعتاد يكون الهدف فارغاً فتتطابق مع الاستبدال.
        tgt["students"] = (tgt.get("students") or []) + src["students"]
        moved += len(src["students"])
        src["students"] = []

    _safe_write_json(STUDENTS_JSON, {"classes": classes})
    constants.STUDENTS_STORE = None
    return {"moved": moved, "graduated": graduated, "created": created,
            "classes": len(classes)}
