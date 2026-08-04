# -*- coding: utf-8 -*-
"""
darbstu_migrate.py — نقل مدرسة قديمة إلى النسخة الجديدة.

يُشغَّل على **جهاز المدرسة** من فلاشة. لا يحتاج بايثون مثبَّتاً.

المرحلتان:
  ① نسخ  — قبل التنصيب: يحفظ absences.db و data كاملاً في مجلد مؤرَّخ
  ② استرجاع — بعد التنصيب: يُعيدها ويدمج هوية المدرسة في الإعداد الجديد

ما لا يُنقل عمداً:
  • config.json كما هو — فيه إعدادات Cloudflare ميتة، وقوالب رسائل
    مذكَّرة لا تعرف متغيّرات تأنيث مدارس البنات. تُنقل الحقول المفيدة
    وحدها ويُحفظ القديم كاملاً للمراجعة.
  • .darb_keys.json — أسرار فريدة لكل تثبيت، يولّدها الجديد بنفسه
  • license.dat و .darb_license — نظام الترخيص القديم لم يعد قائماً
  • .wwebjs_auth — جلسة واتساب تُربَط من جديد بمسح QR
"""
import datetime
import json
import os
import shutil
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP = "نقل مدرسة قديمة — DarbStu"
NAVY, BLUE, GRAY, WHITE = "#1a3a5c", "#1565C0", "#f0f4f8", "#ffffff"
GREEN, RED, AMBER, MUTED = "#2e7d32", "#c62828", "#e65100", "#78909c"

DB_NAME = "absences.db"

# حقول هوية المدرسة — تُنقل من الإعداد القديم
CARRY = [
    "school_name", "education_region", "assistant_title", "assistant_name",
    "principal_title", "principal_name", "logo_path",
    "school_gender", "school_stage",
    "period_times", "school_start_time",
    "alert_absence_threshold", "alert_admin_phone", "principal_phone",
    "counselor1_name", "counselor1_phone", "counselor2_name",
    "counselor2_phone", "active_counselor", "tardiness_recipients",
    "msg_send_delay", "tard_msg_delay_sec",
]

# حقول تُصفَّر دائماً — بقايا الاستضافة القديمة
CLEAR = ["cloudflare_domain", "cloud_token", "cloud_url",
         "cloud_url_internal"]

# ملفات لا تُنقل إطلاقاً
SKIP_FILES = {".darb_keys.json", "license.dat", ".darb_license",
              ".darb_trial", ".darb_init_admin", "config.json"}
SKIP_DIRS = {".wwebjs_auth", ".wwebjs_cache", "__pycache__"}


def guess_old_install():
    """مسارات التثبيت المعتادة."""
    cands = []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", ""),
                 r"C:\DarbStu", os.path.expanduser("~/Desktop")):
        if not base:
            continue
        for name in ("DarbStu", "DarbStu_Dist", "تسجيل الغياب"):
            p = os.path.join(base, name)
            if os.path.isdir(p) and (os.path.exists(os.path.join(p, DB_NAME))
                                     or os.path.isdir(os.path.join(p, "data"))):
                cands.append(p)
    return cands


def _copytree(src, dst, log):
    """نسخ مجلد مع تخطي ما لا يُنقل. يُرجع عدد الملفات."""
    n = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for f in files:
            try:
                shutil.copy2(os.path.join(root, f), os.path.join(target, f))
                n += 1
            except Exception as e:
                log(f"   ⚠️ تعذّر نسخ {f}: {e}\n")
    return n


# ═══════════════════════════════════════════════════════════════
#  ① النسخ
# ═══════════════════════════════════════════════════════════════
def do_backup(old_dir, dest_root, log):
    if not os.path.isdir(old_dir):
        raise ValueError("مجلد التثبيت القديم غير موجود.")

    db = os.path.join(old_dir, DB_NAME)
    data = os.path.join(old_dir, "data")
    if not os.path.exists(db) and not os.path.isdir(data):
        raise ValueError("لم أجد absences.db ولا مجلد data — "
                         "تأكد أنك اخترت مجلد البرنامج الصحيح.")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(dest_root, f"DarbStu_نسخة_المدرسة_{ts}")
    os.makedirs(dest, exist_ok=True)

    report = {"created": ts, "source": old_dir, "files": 0, "db_bytes": 0}

    log("① نسخ بيانات المدرسة\n\n")
    if os.path.exists(db):
        shutil.copy2(db, os.path.join(dest, DB_NAME))
        report["db_bytes"] = os.path.getsize(db)
        log(f"   ✅ {DB_NAME}  ({report['db_bytes']:,} بايت)\n")
    else:
        log("   ⚠️ لا توجد قاعدة بيانات\n")

    if os.path.isdir(data):
        n = _copytree(data, os.path.join(dest, "data"), log)
        report["files"] = n
        log(f"   ✅ مجلد data  ({n} ملفاً)\n")

    # الإعداد القديم يُحفظ كاملاً للمراجعة — ولا يُستعمل كما هو
    cfg_src = os.path.join(data, "config.json")
    if os.path.exists(cfg_src):
        shutil.copy2(cfg_src, os.path.join(dest, "config_القديم_للمراجعة.json"))
        log("   ✅ config.json (نسخة للمراجعة)\n")

    with open(os.path.join(dest, "معلومات_النسخة.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # تحقق: قاعدة البيانات تُفتح فعلاً
    ok_db = True
    if report["db_bytes"]:
        try:
            import sqlite3
            con = sqlite3.connect(os.path.join(dest, DB_NAME))
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            rows = 0
            for t in ("absences", "tardiness", "users"):
                if t in tables:
                    rows += con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            con.close()
            log(f"\n   🔍 القاعدة سليمة — {len(tables)} جدولاً، "
                f"{rows:,} سجلاً في الجداول الأساسية\n")
        except Exception as e:
            ok_db = False
            log(f"\n   ❌ القاعدة لا تُفتح: {e}\n")

    log(f"\n✅ حُفظت النسخة في:\n   {dest}\n")
    if not ok_db:
        log("\n⚠️ راجع القاعدة قبل المتابعة.\n")
    return dest


# ═══════════════════════════════════════════════════════════════
#  ② الاسترجاع
# ═══════════════════════════════════════════════════════════════
def do_restore(backup_dir, new_dir, log, keep_old_templates=False):
    if not os.path.isdir(new_dir):
        raise ValueError("مجلد التثبيت الجديد غير موجود.")
    new_data = os.path.join(new_dir, "data")
    if not os.path.isdir(new_data):
        raise ValueError("لم أجد مجلد data في التثبيت الجديد — "
                         "شغّل البرنامج الجديد مرة واحدة أولاً ثم أغلقه.")

    log("② استرجاع البيانات\n\n")

    # قاعدة البيانات
    src_db = os.path.join(backup_dir, DB_NAME)
    if os.path.exists(src_db):
        dst_db = os.path.join(new_dir, DB_NAME)
        if os.path.exists(dst_db):
            shutil.copy2(dst_db, dst_db + ".before_restore")
        shutil.copy2(src_db, dst_db)
        log(f"   ✅ {DB_NAME} ({os.path.getsize(src_db):,} بايت)\n")

    # مجلد data عدا الإعداد والأسرار
    src_data = os.path.join(backup_dir, "data")
    n = 0
    if os.path.isdir(src_data):
        for root, dirs, files in os.walk(src_data):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            rel = os.path.relpath(root, src_data)
            target = new_data if rel == "." else os.path.join(new_data, rel)
            os.makedirs(target, exist_ok=True)
            for f in files:
                if f in SKIP_FILES:
                    continue
                try:
                    shutil.copy2(os.path.join(root, f),
                                 os.path.join(target, f))
                    n += 1
                except Exception as e:
                    log(f"   ⚠️ {f}: {e}\n")
        log(f"   ✅ بيانات data ({n} ملفاً)\n")

    # دمج هوية المدرسة في الإعداد الجديد
    old_cfg_path = os.path.join(backup_dir, "config_القديم_للمراجعة.json")
    if not os.path.exists(old_cfg_path):
        old_cfg_path = os.path.join(src_data, "config.json")
    new_cfg_path = os.path.join(new_data, "config.json")

    carried, skipped_tpl = [], []
    if os.path.exists(old_cfg_path) and os.path.exists(new_cfg_path):
        old = json.load(open(old_cfg_path, encoding="utf-8"))
        new = json.load(open(new_cfg_path, encoding="utf-8"))

        for k in CARRY:
            if k in old and old[k] not in (None, "", []):
                new[k] = old[k]
                carried.append(k)

        if keep_old_templates:
            for k in list(old):
                if "template" in k and old.get(k):
                    new[k] = old[k]
                    carried.append(k)
        else:
            skipped_tpl = [k for k in old if "template" in k and old.get(k)]

        for k in CLEAR:
            new[k] = ""

        json.dump(new, open(new_cfg_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        log(f"\n   ✅ نُقلت {len(carried)} خانة من إعدادات المدرسة\n")
        log(f"      المدرسة: {new.get('school_name', '؟')}\n")
        log(f"      النوع  : {'بنات' if new.get('school_gender') == 'girls' else 'بنين'}\n")
        log("   ✅ صُفِّرت إعدادات الاستضافة القديمة (Cloudflare/السحابة)\n")
        if skipped_tpl:
            log(f"\n   ℹ️ لم تُنقل {len(skipped_tpl)} قوالب رسائل — "
                "الجديدة تدعم تأنيث مدارس البنات.\n"
                "      القديمة محفوظة في config_القديم_للمراجعة.json\n")

    log("\n✅ اكتمل الاسترجاع.\n\n"
        "الخطوات المتبقية:\n"
        "  ١. ضع provision.json بجانب البرنامج (من لوحة الإدارة)\n"
        "  ٢. شغّل البرنامج وتأكد من ظهور غيابات السنة الماضية\n"
        "  ٣. أعد ربط واتساب بمسح QR\n"
        "  ٤. لا تحذف النسخة الاحتياطية قبل التأكد\n")
    return True


# ═══════════════════════════════════════════════════════════════
#  الواجهة
# ═══════════════════════════════════════════════════════════════
class MigrateApp:
    def __init__(self, root):
        self.root = root
        root.title(APP)
        root.configure(bg=GRAY)
        root.geometry("820x680")
        root.minsize(700, 560)

        hdr = tk.Frame(root, bg=NAVY, height=58)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🔄  نقل مدرسة قديمة إلى النسخة الجديدة",
                 bg=NAVY, fg=WHITE, font=("Tahoma", 13, "bold")).pack(pady=15)

        body = tk.Frame(root, bg=GRAY, padx=20, pady=12)
        body.pack(fill="both", expand=True)

        # ① النسخ
        f1 = tk.LabelFrame(body, text="  ①  قبل التنصيب — خذ نسخة  ",
                           font=("Tahoma", 10, "bold"), fg=BLUE, bg=WHITE,
                           relief="groove", bd=2)
        f1.pack(fill="x", pady=(0, 10))
        self.v_old = tk.StringVar()
        cands = guess_old_install()
        if cands:
            self.v_old.set(cands[0])
        r1 = tk.Frame(f1, bg=WHITE); r1.pack(fill="x", padx=10, pady=8)
        tk.Label(r1, text="مجلد البرنامج القديم:", bg=WHITE,
                 font=("Tahoma", 9)).pack(anchor="e")
        tk.Entry(r1, textvariable=self.v_old, font=("Consolas", 9),
                 relief="solid", bd=1).pack(fill="x", ipady=4)
        b1 = tk.Frame(f1, bg=WHITE); b1.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(b1, text="📁 اختر", bg="#e8f0fe", fg=NAVY, relief="flat",
                  cursor="hand2", padx=10, pady=4,
                  command=self._pick_old).pack(side="left")
        tk.Button(b1, text="💾  خذ نسخة الآن", bg=GREEN, fg=WHITE,
                  relief="flat", font=("Tahoma", 10, "bold"), cursor="hand2",
                  padx=16, pady=6, command=self._backup).pack(side="right")

        # ② الاسترجاع
        f2 = tk.LabelFrame(body, text="  ②  بعد تنصيب النسخة الجديدة — استرجع  ",
                           font=("Tahoma", 10, "bold"), fg=AMBER, bg=WHITE,
                           relief="groove", bd=2)
        f2.pack(fill="x", pady=(0, 10))
        self.v_bak = tk.StringVar()
        self.v_new = tk.StringVar()
        for lbl, var, cmd in (("مجلد النسخة الاحتياطية:", self.v_bak, self._pick_bak),
                              ("مجلد التثبيت الجديد:", self.v_new, self._pick_new)):
            rr = tk.Frame(f2, bg=WHITE); rr.pack(fill="x", padx=10, pady=(6, 0))
            tk.Label(rr, text=lbl, bg=WHITE, font=("Tahoma", 9)).pack(anchor="e")
            row = tk.Frame(rr, bg=WHITE); row.pack(fill="x")
            tk.Entry(row, textvariable=var, font=("Consolas", 9),
                     relief="solid", bd=1).pack(side="right", fill="x",
                                                expand=True, ipady=4)
            tk.Button(row, text="📁", bg="#e8f0fe", fg=NAVY, relief="flat",
                      cursor="hand2", padx=8, command=cmd).pack(side="left")
        self.v_tpl = tk.BooleanVar(value=False)
        tk.Checkbutton(f2, text="أبقِ قوالب الرسائل القديمة "
                                "(لا يُنصح — الجديدة تدعم مدارس البنات)",
                       variable=self.v_tpl, bg=WHITE, fg=MUTED,
                       font=("Tahoma", 8), anchor="e").pack(fill="x", padx=10)
        tk.Button(f2, text="♻️  استرجع البيانات", bg=AMBER, fg=WHITE,
                  relief="flat", font=("Tahoma", 10, "bold"), cursor="hand2",
                  padx=16, pady=6,
                  command=self._restore).pack(anchor="w", padx=10, pady=(4, 10))

        self.out = tk.Text(body, font=("Consolas", 9), bg="#0f1720",
                           fg="#d6e2ee", wrap="word", relief="flat",
                           state="disabled")
        self.out.pack(fill="both", expand=True)
        self._log("جاهز.\n\n"
                  "الترتيب: خذ نسخة ← ثبّت النسخة الجديدة ← "
                  "شغّلها مرة وأغلقها ← استرجع.\n")
        if cands:
            self._log(f"\nوجدت تثبيتاً قديماً:\n   {cands[0]}\n")

    def _log(self, t, clear=False):
        self.out.config(state="normal")
        if clear:
            self.out.delete("1.0", "end")
        self.out.insert("end", t)
        self.out.see("end")
        self.out.config(state="disabled")
        self.root.update_idletasks()

    def _pick_old(self):
        p = filedialog.askdirectory(title="مجلد البرنامج القديم")
        if p:
            self.v_old.set(p)

    def _pick_bak(self):
        p = filedialog.askdirectory(title="مجلد النسخة الاحتياطية")
        if p:
            self.v_bak.set(p)

    def _pick_new(self):
        p = filedialog.askdirectory(title="مجلد التثبيت الجديد")
        if p:
            self.v_new.set(p)

    def _backup(self):
        old = self.v_old.get().strip()
        if not old:
            messagebox.showerror("ناقص", "اختر مجلد البرنامج القديم.")
            return
        dest = filedialog.askdirectory(title="أين تُحفظ النسخة؟ (فلاشة مثلاً)")
        if not dest:
            return
        self._log("", clear=True)

        def _w():
            try:
                d = do_backup(old, dest, self._log)
                self.v_bak.set(d)
            except Exception as e:
                self._log(f"\n⛔ {e}\n")
        threading.Thread(target=_w, daemon=True).start()

    def _restore(self):
        bak, new = self.v_bak.get().strip(), self.v_new.get().strip()
        if not bak or not new:
            messagebox.showerror("ناقص", "حدّد النسخة ومجلد التثبيت الجديد.")
            return
        if not messagebox.askyesno(
                "تأكيد", "سيُستبدل محتوى التثبيت الجديد ببيانات المدرسة.\n\n"
                         "المتابعة؟", icon="warning"):
            return
        self._log("", clear=True)

        def _w():
            try:
                do_restore(bak, new, self._log, self.v_tpl.get())
            except Exception as e:
                self._log(f"\n⛔ {e}\n")
        threading.Thread(target=_w, daemon=True).start()


def main():
    root = tk.Tk()
    MigrateApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
