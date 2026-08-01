# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox
import datetime, threading

from constants import now_riyadh_date, CURRENT_USER

VISIT_REASONS = [
    "غياب الطالب", "التأخر المتكرر", "السلوك والانضباط",
    "المتابعة الأكاديمية", "طلب إجازة", "استفسار عام",
    "تسليم وثيقة", "أخرى",
]
RECEIVED_BY_OPTIONS = [
    "المدير", "الوكيل", "المرشد الطلابي", "الإداري", "المعلم", "أخرى",
]
VISIT_RESULTS = [
    "تم التوجيه والإرشاد", "تم الإشعار والتنبيه",
    "اتخذ إجراء رسمي", "تم الاستلام وقيد الدراسة",
    "لم يُتخذ إجراء", "أخرى",
]

_TIME_SLOTS = [
    "07:00", "07:15", "07:30", "07:45",
    "08:00", "08:15", "08:30", "08:45",
    "09:00", "09:15", "09:30", "09:45",
    "10:00", "10:15", "10:30", "10:45",
    "11:00", "11:15", "11:30", "11:45",
    "12:00", "12:15", "12:30", "12:45",
    "13:00", "13:15", "13:30", "13:45",
    "14:00", "14:30", "15:00",
]


class ParentVisitsTabMixin:
    """Mixin: تبويب سجل زيارات أولياء الأمور"""

    def _build_parent_visits_tab(self):
        frame = self.parent_visits_frame
        frame.config(bg="white")

        # ── شريط العنوان ─────────────────────────────────────────
        hdr = tk.Frame(frame, bg="#1565C0", height=46)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="👨‍👦 سجل زيارات أولياء الأمور",
                 bg="#1565C0", fg="white",
                 font=("Tahoma", 13, "bold")).pack(side="right", padx=16, pady=8)

        # ── شريط أدوات ────────────────────────────────────────────
        bar = tk.Frame(frame, bg="#f0f4f8", pady=6)
        bar.pack(fill="x", padx=8, pady=(4, 0))

        ttk.Button(bar, text="➕ تسجيل زيارة",
                   command=self._pv_add_dialog).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="🗑️ حذف المحدد",
                   command=self._pv_delete).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="🔄 تحديث",
                   command=self._pv_load).pack(side="right", padx=(0, 6))

        # فلتر التاريخ
        tk.Label(bar, text="من:", bg="#f0f4f8",
                 font=("Tahoma", 9)).pack(side="right", padx=(0, 2))
        self._pv_from = ttk.Entry(bar, width=11)
        self._pv_from.insert(0, now_riyadh_date()[:7] + "-01")
        self._pv_from.pack(side="right")

        tk.Label(bar, text="إلى:", bg="#f0f4f8",
                 font=("Tahoma", 9)).pack(side="right", padx=(8, 2))
        self._pv_to = ttk.Entry(bar, width=11)
        self._pv_to.insert(0, now_riyadh_date())
        self._pv_to.pack(side="right")

        # بحث
        tk.Label(bar, text="بحث:", bg="#f0f4f8",
                 font=("Tahoma", 9)).pack(side="right", padx=(8, 2))
        self._pv_search_var = tk.StringVar()
        self._pv_search_var.trace_add("write", lambda *_: self._pv_filter())
        ttk.Entry(bar, textvariable=self._pv_search_var, width=14).pack(side="right")

        # ── جدول السجلات ──────────────────────────────────────────
        tree_frame = tk.Frame(frame, bg="white")
        tree_frame.pack(fill="both", expand=True, padx=8, pady=(4, 4))

        cols = ("id", "date", "visit_time", "student_name", "class_name",
                "guardian_name", "visit_reason", "received_by", "visit_result", "notes")
        hdrs = ("#", "التاريخ", "الوقت", "اسم الطالب", "الفصل",
                "اسم ولي الأمر", "سبب الزيارة", "الجهة المستقبلة", "النتيجة", "ملاحظات")

        self._pv_tree = ttk.Treeview(tree_frame, columns=cols,
                                      show="headings", selectmode="browse")
        widths = (40, 90, 65, 140, 100, 130, 130, 110, 140, 180)
        for c, h, w in zip(cols, hdrs, widths):
            self._pv_tree.heading(c, text=h)
            self._pv_tree.column(c, width=w, minwidth=40, anchor="center")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self._pv_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal",
                            command=self._pv_tree.xview)
        self._pv_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self._pv_tree.pack(fill="both", expand=True)

        self._pv_all_rows = []
        frame.after(300, self._pv_load)

    # ─── تحميل البيانات ─────────────────────────────────���────────
    def _pv_load(self):
        date_from = self._pv_from.get().strip() or None
        date_to   = self._pv_to.get().strip()   or None

        def _worker():
            from database import get_parent_visits
            rows = get_parent_visits(date_from=date_from, date_to=date_to)
            self.root.after(0, lambda r=rows: self._pv_populate(r))

        threading.Thread(target=_worker, daemon=True).start()

    def _pv_populate(self, rows):
        self._pv_all_rows = rows
        self._pv_filter()

    def _pv_filter(self):
        q = self._pv_search_var.get().strip().lower()
        for item in self._pv_tree.get_children():
            self._pv_tree.delete(item)
        for r in self._pv_all_rows:
            if q and not any(q in str(v).lower() for v in r.values()):
                continue
            self._pv_tree.insert("", "end", iid=str(r["id"]), values=(
                r["id"], r["date"], r["visit_time"],
                r["student_name"], r["class_name"],
                r.get("guardian_name", ""),
                r["visit_reason"], r["received_by"],
                r["visit_result"], r.get("notes", ""),
            ))

    # ─── نافذة إضافة زيارة ───────────────────────────────────────
    def _pv_add_dialog(self):
        from database import get_parent_visits
        dlg = tk.Toplevel(self.root)
        dlg.title("تسجيل زيارة ولي أمر")
        dlg.resizable(False, False)
        dlg.grab_set()

        # ── تجميع بيانات الفصول والطلاب ─────────────────────────
        classes = []
        cls_to_students = {}
        try:
            import json, os
            from constants import STUDENTS_JSON
            with open(STUDENTS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            for cls in data.get("classes", []):
                cname = cls["name"]
                classes.append(cname)
                cls_to_students[cname] = cls.get("students", [])
        except Exception:
            pass

        PAD = dict(padx=12, pady=4)

        tk.Label(dlg, text="👨‍👦 تسجيل زيارة ولي أمر",
                 font=("Tahoma", 11, "bold"), fg="#1565C0").grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 8))

        def lbl(row, text):
            tk.Label(dlg, text=text, font=("Tahoma", 9),
                     anchor="e", width=16).grid(row=row, column=0, sticky="e", **PAD)

        # ── صف 1: التاريخ ─────────────────────────��─────────────
        lbl(1, "التاريخ:")
        date_var = tk.StringVar(value=now_riyadh_date())
        try:
            from tkcalendar import DateEntry
            date_w = DateEntry(dlg, textvariable=date_var, width=13,
                               date_pattern="yyyy-mm-dd")
        except ImportError:
            date_w = ttk.Combobox(dlg, textvariable=date_var, width=13,
                                  values=[now_riyadh_date()], state="normal")
        date_w.grid(row=1, column=1, sticky="w", **PAD)

        # ── صف 2: الوقت ─────────────────────────────────────────
        lbl(2, "الوقت:")
        now_t = datetime.datetime.now().strftime("%H:%M")
        closest = min(_TIME_SLOTS, key=lambda t: abs(
            int(t[:2])*60+int(t[3:]) - int(now_t[:2])*60-int(now_t[3:])))
        time_var = tk.StringVar(value=closest)
        ttk.Combobox(dlg, textvariable=time_var, values=_TIME_SLOTS,
                     width=13, state="readonly").grid(
            row=2, column=1, sticky="w", **PAD)

        # ── صف 3: الفصل ─────────────────────────────────────────
        lbl(3, "الفصل:")
        cls_var = tk.StringVar()
        cls_cb  = ttk.Combobox(dlg, textvariable=cls_var, values=classes,
                               width=22, state="readonly")
        cls_cb.grid(row=3, column=1, sticky="w", **PAD)

        # ── صف 4: الطالب ────────────────────────────────────────
        lbl(4, "الطالب:")
        stu_var = tk.StringVar()
        stu_cb  = ttk.Combobox(dlg, textvariable=stu_var, values=[],
                               width=22, state="readonly")
        stu_cb.grid(row=4, column=1, sticky="w", **PAD)

        # ── صف 5: اسم ولي الأمر (يملأ تلقائياً) ────────────────
        lbl(5, "اسم ولي الأمر:")
        grd_var = tk.StringVar()
        ttk.Entry(dlg, textvariable=grd_var, width=24,
                  state="readonly").grid(row=5, column=1, sticky="w", **PAD)

        # ── ربط الفصل بالطلاب ────────────────────────────────────
        _stu_map = {}

        def _on_cls(*_):
            cls = cls_var.get()
            stus = cls_to_students.get(cls, [])
            _stu_map.clear()
            for s in stus:
                _stu_map[s["name"]] = s["id"]
            stu_cb["values"] = [s["name"] for s in stus]
            stu_var.set("")
            grd_var.set("")

        def _on_stu(*_):
            name = stu_var.get()
            if name:
                grd_var.set(f"ولي أمر: {name}")

        cls_var.trace_add("write", _on_cls)
        stu_var.trace_add("write", _on_stu)

        # ── صف 6: سبب الزيارة ───────────────────────────────────
        lbl(6, "سبب الزيارة:")
        reason_var = tk.StringVar()
        ttk.Combobox(dlg, textvariable=reason_var, values=VISIT_REASONS,
                     width=22, state="readonly").grid(
            row=6, column=1, sticky="w", **PAD)

        # ── صف 7: الجهة المستقبلة ────────────────────────────────
        lbl(7, "الجهة المستقبلة:")
        rcv_var = tk.StringVar()
        ttk.Combobox(dlg, textvariable=rcv_var, values=RECEIVED_BY_OPTIONS,
                     width=22, state="readonly").grid(
            row=7, column=1, sticky="w", **PAD)

        # ── صف 8: نتيجة الزيارة ─────────────────────────────────
        lbl(8, "نتيجة الزيارة:")
        res_var = tk.StringVar()
        ttk.Combobox(dlg, textvariable=res_var, values=VISIT_RESULTS,
                     width=22, state="readonly").grid(
            row=8, column=1, sticky="w", **PAD)

        # ── صف 9: الملاحظات (حرة الكتابة) ──────────────────────
        lbl(9, "ملاحظات:")
        notes_txt = tk.Text(dlg, width=26, height=4,
                            font=("Tahoma", 10), relief="solid", bd=1)
        notes_txt.grid(row=9, column=1, sticky="w", **PAD)

        # ── أزرار ─────────────────────────────────────────────────
        def _save():
            missing = []
            if not date_var.get():      missing.append("التاريخ")
            if not time_var.get():      missing.append("الوقت")
            if not cls_var.get():       missing.append("الفصل")
            if not stu_var.get():       missing.append("الطالب")
            if not reason_var.get():    missing.append("سبب الزيارة")
            if not rcv_var.get():       missing.append("الجهة المستقبلة")
            if not res_var.get():       missing.append("نتيجة الزيارة")
            if missing:
                messagebox.showwarning("حقول مطلوبة",
                    "يرجى إكمال الحقول التالية:\n" + "، ".join(missing),
                    parent=dlg)
                return

            stu_name = stu_var.get()
            stu_id   = _stu_map.get(stu_name, "")
            data = {
                "date":         date_var.get(),
                "visit_time":   time_var.get(),
                "student_id":   stu_id,
                "student_name": stu_name,
                "class_name":   cls_var.get(),
                "guardian_name": grd_var.get(),
                "visit_reason": reason_var.get(),
                "received_by":  rcv_var.get(),
                "visit_result": res_var.get(),
                "notes":        notes_txt.get("1.0", "end").strip(),
                "created_by":   CURRENT_USER.get("username", ""),
            }

            def _worker():
                from database import insert_parent_visit
                insert_parent_visit(data)
                self.root.after(0, lambda: (dlg.destroy(), self._pv_load()))

            threading.Thread(target=_worker, daemon=True).start()

        btn_row = tk.Frame(dlg)
        btn_row.grid(row=10, column=0, columnspan=2, pady=(6, 12))
        ttk.Button(btn_row, text="💾 حفظ", command=_save).pack(
            side="right", padx=6)
        ttk.Button(btn_row, text="إلغاء", command=dlg.destroy).pack(
            side="right", padx=6)

    # ─── حذف ─────────────────────────────────────────────────────
    def _pv_delete(self):
        sel = self._pv_tree.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "اختر سجلاً أولاً.")
            return
        if not messagebox.askyesno("تأكيد", "هل تريد حذف هذا السجل؟"):
            return
        vid = int(sel[0])

        def _worker():
            from database import delete_parent_visit
            delete_parent_visit(vid)
            self.root.after(0, self._pv_load)

        threading.Thread(target=_worker, daemon=True).start()
