# -*- coding: utf-8 -*-
"""
gui/tabs/referral_teacher_tab.py — تبويب تحويل طالب (للمعلم)
"""
import tkinter as tk
from tkinter import ttk, messagebox
import os, datetime, webbrowser, tempfile
from constants import now_riyadh_date, CURRENT_USER, DATA_DIR
from database import (get_db, load_students,
                      create_student_referral, get_referrals_for_teacher,
                      get_referral_by_id)
from config_manager import load_config
from whatsapp_service import send_whatsapp_message

_STATUS_LABELS = {
    "pending":        "⏳ بانتظار الوكيل",
    "with_deputy":    "📋 مع الوكيل",
    "with_counselor": "👨‍🏫 مع الموجه",
    "resolved":       "✅ تم الحل",
}

class TeacherReferralTabMixin:
    """Mixin: تبويب تحويل طالب للمعلم"""

    # ───────────────────────────────────────────────────
    def _build_teacher_referral_tab(self):
        frame = self.teacher_referral_frame

        # ─ Header ─
        hdr = tk.Frame(frame, bg="#1565C0", height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📋 تحويل طالب إلى وكيل شؤون الطلاب",
                 bg="#1565C0", fg="white",
                 font=("Tahoma", 13, "bold")).pack(side="right", padx=16, pady=10)

        # ─ PanedWindow: نموذج يسار + سجل يمين ─
        paned = tk.PanedWindow(frame, orient="horizontal", sashwidth=6,
                               bg="#e5e7eb", sashrelief="flat")
        paned.pack(fill="both", expand=True)

        # ─────────────────── لوحة النموذج ───────────────────
        form_outer = tk.Frame(paned, bg="white")
        paned.add(form_outer, minsize=340, stretch="always")

        tk.Label(form_outer, text="نموذج تحويل جديد",
                 bg="#1565C0", fg="white",
                 font=("Tahoma", 11, "bold")).pack(fill="x", ipady=5)

        # Scrollable canvas
        _cv = tk.Canvas(form_outer, bg="white", highlightthickness=0)
        _vsb = ttk.Scrollbar(form_outer, orient="vertical", command=_cv.yview)
        _cv.configure(yscrollcommand=_vsb.set)
        _vsb.pack(side="right", fill="y")
        _cv.pack(fill="both", expand=True)

        form_frame = tk.Frame(_cv, bg="white")
        _cv_win = _cv.create_window((0, 0), window=form_frame, anchor="nw")

        form_frame.bind("<Configure>",
            lambda e: _cv.configure(scrollregion=_cv.bbox("all")))
        _cv_last_w = [0]
        def _on_cfg(e):
            w = _cv.winfo_width()
            if w == _cv_last_w[0]: return
            _cv_last_w[0] = w
            _cv.itemconfig(_cv_win, width=w)
        _cv.bind("<Configure>", _on_cfg)
        _cv.bind("<MouseWheel>", lambda e: _cv.yview_scroll(-1*(e.delta//120), "units"))

        self._build_referral_form(form_frame)

        # ─────────────────── لوحة السجل ───────────────────
        hist_outer = tk.Frame(paned, bg="white")
        paned.add(hist_outer, minsize=280, stretch="always")

        # ضبط موقع الـ sash نسبياً (55% للنموذج) بعد اكتمال الرسم
        def _set_sash():
            total = paned.winfo_width()
            if total > 10:
                paned.sash_place(0, int(total * 0.55), 0)
        frame.after(150, _set_sash)

        tk.Label(hist_outer, text="سجل تحويلاتي",
                 bg="#7c3aed", fg="white",
                 font=("Tahoma", 11, "bold")).pack(fill="x", ipady=5)

        # Toolbar
        bar = tk.Frame(hist_outer, bg="#f8f9fa")
        bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar, text="🔄 تحديث",
                   command=self._load_referral_history).pack(side="right", padx=4)
        ttk.Button(bar, text="🔍 عرض التفاصيل",
                   command=self._open_selected_referral).pack(side="right", padx=4)

        # TreeView
        cols = ("id","date","student","class","status")
        self._ref_tree = ttk.Treeview(hist_outer, columns=cols,
                                       show="headings", height=20)
        for c, h, w in zip(cols,
            ["#","التاريخ","الطالب","الفصل","الحالة"],
            [40, 90, 160, 140, 140]):
            self._ref_tree.heading(c, text=h)
            self._ref_tree.column(c, width=w, anchor="center")
        self._ref_tree.tag_configure("pending",        background="#FFF9E6")
        self._ref_tree.tag_configure("with_deputy",    background="#E3F2FD")
        self._ref_tree.tag_configure("with_counselor", background="#EDE7F6")
        self._ref_tree.tag_configure("resolved",       background="#E8F5E9")

        sb = ttk.Scrollbar(hist_outer, orient="vertical",
                            command=self._ref_tree.yview)
        self._ref_tree.configure(yscrollcommand=sb.set)
        self._ref_tree.pack(side="left", fill="both", expand=True, padx=(6,0))
        sb.pack(side="right", fill="y")
        self._ref_tree.bind("<Double-1>", lambda e: self._open_selected_referral())

        self._load_referral_history()

    # ───────────────────────────────────────────────────
    def _build_referral_form(self, parent):
        """يبني حقول نموذج التحويل."""
        pad = {"padx": 12, "pady": 4}

        def section_header(text, color="#1565C0"):
            f = tk.Frame(parent, bg=color, pady=4)
            f.pack(fill="x", padx=8, pady=(10, 4))
            tk.Label(f, text=text, bg=color, fg="white",
                     font=("Tahoma", 10, "bold")).pack(side="right", padx=10)

        def row(parent, label, widget_fn, colspan=1):
            r = tk.Frame(parent, bg="white")
            r.pack(fill="x", **pad)
            tk.Label(r, text=label + " :", bg="white",
                     font=("Tahoma", 10), width=18, anchor="e").pack(side="right")
            return widget_fn(r)

        # ═══ بيانات الطالب ═══
        section_header("  بيانات عن الطالب  ")

        # اختيار الطالب
        r1 = tk.Frame(parent, bg="white"); r1.pack(fill="x", **pad)
        tk.Label(r1, text="اسم الطالب :", bg="white",
                 font=("Tahoma", 10), width=18, anchor="e").pack(side="right")
        self._ref_student_var = tk.StringVar()
        self._ref_students = []
        self._ref_student_cb = ttk.Combobox(r1, textvariable=self._ref_student_var,
                                             state="readonly", font=("Tahoma", 10))
        self._ref_student_cb.pack(side="right", padx=4, fill="x", expand=True)
        self._ref_student_cb.bind("<<ComboboxSelected>>", self._on_ref_student_select)
        ttk.Button(r1, text="🔄", width=3,
                   command=self._reload_ref_students).pack(side="right")

        # الفصل / المادة / الحصة
        r2 = tk.Frame(parent, bg="white"); r2.pack(fill="x", **pad)
        tk.Label(r2, text="الصف :", bg="white",
                 font=("Tahoma",10), width=8, anchor="e").pack(side="right")
        self._ref_class_var = tk.StringVar()
        tk.Entry(r2, textvariable=self._ref_class_var, width=16,
                 font=("Tahoma",10), state="readonly",
                 bg="#f0f0f0").pack(side="right", padx=4)
        tk.Label(r2, text="المادة :", bg="white",
                 font=("Tahoma",10), width=8, anchor="e").pack(side="right")
        self._ref_subject_var = tk.StringVar()
        tk.Entry(r2, textvariable=self._ref_subject_var, width=16,
                 font=("Tahoma",10)).pack(side="right", padx=4)

        r3 = tk.Frame(parent, bg="white"); r3.pack(fill="x", **pad)
        tk.Label(r3, text="الحصة :", bg="white",
                 font=("Tahoma",10), width=8, anchor="e").pack(side="right")
        self._ref_period_var = tk.StringVar(value="1")
        ttk.Combobox(r3, textvariable=self._ref_period_var,
                     values=[str(i) for i in range(1,9)],
                     width=5, state="readonly",
                     font=("Tahoma",10)).pack(side="right", padx=4)
        tk.Label(r3, text="الوقت :", bg="white",
                 font=("Tahoma",10), width=8, anchor="e").pack(side="right")
        self._ref_time_var = tk.StringVar()
        tk.Entry(r3, textvariable=self._ref_time_var, width=10,
                 font=("Tahoma",10)).pack(side="right", padx=4)
        self._ref_ampm_var = tk.StringVar(value="ص")
        for v in ["ص","م"]:
            tk.Radiobutton(r3, text=v, variable=self._ref_ampm_var, value=v,
                           bg="white", font=("Tahoma",10)).pack(side="right")

        # ═══ إجراءات المعلم ═══
        section_header("  الإجراءات التي اتخذها المعلم  ")

        # نوع المخالفة
        r4 = tk.Frame(parent, bg="white"); r4.pack(fill="x", **pad)
        tk.Label(r4, text="نوع المخالفة :", bg="white",
                 font=("Tahoma",10), width=18, anchor="e").pack(side="right")
        self._ref_vtype_var = tk.StringVar(value="سلوكية")
        for v in ["تربوية","سلوكية","أخرى"]:
            tk.Radiobutton(r4, text=v, variable=self._ref_vtype_var, value=v,
                           bg="white", font=("Tahoma",10)).pack(side="right", padx=4)

        r5 = tk.Frame(parent, bg="white"); r5.pack(fill="x", **pad)
        tk.Label(r5, text="المخالفة :", bg="white",
                 font=("Tahoma",10), width=18, anchor="e").pack(side="right")
        self._ref_violation_var = tk.StringVar()
        tk.Entry(r5, textvariable=self._ref_violation_var, width=36,
                 font=("Tahoma",10)).pack(side="right", padx=4, fill="x", expand=True)

        r6 = tk.Frame(parent, bg="white"); r6.pack(fill="x", **pad)
        tk.Label(r6, text="أسباب التحويل :", bg="white",
                 font=("Tahoma",10), width=18, anchor="e").pack(side="right", anchor="n")
        self._ref_causes_text = tk.Text(r6, height=3, width=36,
                                         font=("Tahoma",10), wrap="word")
        self._ref_causes_text.pack(side="right", padx=4, fill="x", expand=True)

        # تكرار المشكلة
        r7 = tk.Frame(parent, bg="white"); r7.pack(fill="x", **pad)
        tk.Label(r7, text="تكرار المشكلة :", bg="white",
                 font=("Tahoma",10), width=18, anchor="e").pack(side="right")
        self._ref_repeat_var = tk.StringVar(value="الأول")
        for v in ["الأول","الثاني","الثالث","الرابع"]:
            tk.Radiobutton(r7, text="التكرار "+v, variable=self._ref_repeat_var, value=v,
                           bg="white", font=("Tahoma",10)).pack(side="right", padx=2)

        # الإجراءات المتخذة (5 سطور)
        r8 = tk.Frame(parent, bg="white"); r8.pack(fill="x", **pad)
        tk.Label(r8, text="الإجراءات المتخذة :", bg="white",
                 font=("Tahoma",10), width=18, anchor="e").pack(side="right", anchor="n")
        actions_frame = tk.Frame(r8, bg="white")
        actions_frame.pack(side="right", fill="x", expand=True, padx=4)
        self._ref_action_vars = []
        for i in range(1, 6):
            af = tk.Frame(actions_frame, bg="white")
            af.pack(fill="x", pady=1)
            tk.Label(af, text=f"{i}.", bg="white",
                     font=("Tahoma",10), width=3).pack(side="right")
            v = tk.StringVar()
            tk.Entry(af, textvariable=v, width=38,
                     font=("Tahoma",10)).pack(side="right", fill="x", expand=True)
            self._ref_action_vars.append(v)

        # الملاحظة التوضيحية
        note_f = tk.Frame(parent, bg="#FFF8E1")
        note_f.pack(fill="x", padx=8, pady=4)
        tk.Label(note_f, text="ملاحظة: أرفق شواهد الإجراءات التي اتخذها مع الطالب",
                 bg="#FFF8E1", fg="#F57F17",
                 font=("Tahoma", 9, "bold")).pack(side="right", padx=10, pady=4)

        # معلومات المعلم
        r9 = tk.Frame(parent, bg="white"); r9.pack(fill="x", **pad)
        teacher_name = CURRENT_USER.get("name", CURRENT_USER.get("username",""))
        tk.Label(r9, text=f"اسم المعلم: {teacher_name}   |   التاريخ: {now_riyadh_date()}",
                 bg="white", fg="#555",
                 font=("Tahoma", 9)).pack(side="right", padx=8)

        # ═══ أزرار الإرسال ═══
        btn_frame = tk.Frame(parent, bg="#f0f4f8")
        btn_frame.pack(fill="x", padx=8, pady=12)
        tk.Button(btn_frame, text="📤 إرسال التحويل",
                  bg="#1565C0", fg="white",
                  font=("Tahoma", 11, "bold"), relief="flat",
                  padx=16, pady=8, cursor="hand2",
                  command=self._submit_referral).pack(side="right", padx=8)
        tk.Button(btn_frame, text="🗑️ مسح النموذج",
                  bg="#e53935", fg="white",
                  font=("Tahoma", 10), relief="flat",
                  padx=10, pady=8, cursor="hand2",
                  command=self._clear_referral_form).pack(side="right", padx=4)

        # تحميل الطلاب عند البناء
        self._reload_ref_students()

    # ───────────────────────────────────────────────────
    def _reload_ref_students(self):
        """يُعيد تحميل قائمة الطلاب."""
        try:
            store = load_students()
            self._ref_students = []
            names = []
            for cls in store.get("list", []):
                for st in cls.get("students", []):
                    self._ref_students.append({
                        "display": f"{st['name']}  ({cls.get('name','')[:20]})",
                        "name": st["name"],
                        "id": st.get("id",""),
                        "class_id": cls.get("id",""),
                        "class_name": cls.get("name",""),
                    })
                    names.append(f"{st['name']}  ({cls.get('name','')[:20]})")
            self._ref_student_cb["values"] = names
        except Exception as e:
            print(f"[REFERRAL] خطأ تحميل الطلاب: {e}")

    def _on_ref_student_select(self, _event=None):
        """يملأ الفصل تلقائياً عند اختيار الطالب."""
        idx = self._ref_student_cb.current()
        if 0 <= idx < len(self._ref_students):
            st = self._ref_students[idx]
            self._ref_class_var.set(st["class_name"])

    # ───────────────────────────────────────────────────
    def _submit_referral(self):
        """يُرسل النموذج ويُنبّه الوكيل."""
        idx = self._ref_student_cb.current()
        if idx < 0:
            messagebox.showwarning("تحذير", "اختر طالباً أولاً")
            return
        st = self._ref_students[idx]
        causes = self._ref_causes_text.get("1.0", "end").strip()
        if not causes:
            messagebox.showwarning("تحذير", "أدخل أسباب التحويل وإيضاح المشكلة")
            return

        teacher_name = CURRENT_USER.get("name", CURRENT_USER.get("username",""))
        data = {
            "ref_date":        now_riyadh_date(),
            "student_id":      st["id"],
            "student_name":    st["name"],
            "class_id":        st["class_id"],
            "class_name":      st["class_name"],
            "subject":         self._ref_subject_var.get().strip(),
            "period":          self._ref_period_var.get(),
            "session_time":    self._ref_time_var.get().strip(),
            "session_ampm":    self._ref_ampm_var.get(),
            "violation_type":  self._ref_vtype_var.get(),
            "violation":       self._ref_violation_var.get().strip(),
            "problem_causes":  causes,
            "repeat_count":    self._ref_repeat_var.get(),
            "teacher_action1": self._ref_action_vars[0].get().strip(),
            "teacher_action2": self._ref_action_vars[1].get().strip(),
            "teacher_action3": self._ref_action_vars[2].get().strip(),
            "teacher_action4": self._ref_action_vars[3].get().strip(),
            "teacher_action5": self._ref_action_vars[4].get().strip(),
            "teacher_name":    teacher_name,
            "teacher_username": CURRENT_USER.get("username",""),
            "teacher_date":    now_riyadh_date(),
        }
        ref_id = create_student_referral(data)

        # إرسال إشعار واتساب للوكيل
        self._notify_deputy_referral(st["name"], st["class_name"], teacher_name, ref_id)

        messagebox.showinfo("تم", f"تم إرسال التحويل بنجاح\nرقم التحويل: {ref_id}")
        self._clear_referral_form()
        self._load_referral_history()

    def _notify_deputy_referral(self, student_name, class_name, teacher_name, ref_id):
        """يُرسل إشعار واتساب للوكيل."""
        try:
            from database import get_deputy_phones
            phones = get_deputy_phones()
            cfg = load_config()
            # استخدم principal_phone كاحتياطي إذا لم يكن هناك وكيل مسجل
            if not phones and cfg.get("principal_phone"):
                phones = [cfg["principal_phone"]]
            msg = (
                f"🔔 *تنبيه: تحويل طالب جديد*\n\n"
                f"الطالب: {student_name}\n"
                f"الفصل: {class_name}\n"
                f"المعلم: {teacher_name}\n"
                f"التاريخ: {now_riyadh_date()}\n"
                f"رقم التحويل: {ref_id}\n\n"
                f"يرجى مراجعة نظام درب لاتخاذ الإجراء المناسب."
            )
            for ph in phones:
                try:
                    send_whatsapp_message(ph, msg)
                except Exception:
                    pass
        except Exception as e:
            print(f"[REFERRAL] خطأ إشعار الوكيل: {e}")

    # ───────────────────────────────────────────────────
    def _clear_referral_form(self):
        """يمسح النموذج."""
        self._ref_student_cb.set("")
        self._ref_class_var.set("")
        self._ref_subject_var.set("")
        self._ref_period_var.set("1")
        self._ref_time_var.set("")
        self._ref_ampm_var.set("ص")
        self._ref_vtype_var.set("سلوكية")
        self._ref_violation_var.set("")
        self._ref_causes_text.delete("1.0", "end")
        self._ref_repeat_var.set("الأول")
        for v in self._ref_action_vars:
            v.set("")

    # ───────────────────────────────────────────────────
    def _load_referral_history(self):
        """يُحدّث جدول السجل."""
        uname = CURRENT_USER.get("username", "")
        try:
            rows = get_referrals_for_teacher(uname)
        except Exception:
            rows = []
        self._ref_tree.delete(*self._ref_tree.get_children())
        for r in rows:
            status_lbl = _STATUS_LABELS.get(r.get("status",""), r.get("status",""))
            self._ref_tree.insert("", "end",
                iid=str(r["id"]),
                values=(r["id"], r.get("ref_date",""),
                        r.get("student_name",""),
                        r.get("class_name","")[:22],
                        status_lbl),
                tags=(r.get("status",""),))

    def _open_selected_referral(self):
        """يفتح نافذة تفاصيل التحويل المحدد."""
        sel = self._ref_tree.selection()
        if not sel:
            messagebox.showinfo("تنبيه", "اختر تحويلاً من القائمة")
            return
        ref_id = int(sel[0])
        self._open_referral_detail(ref_id)

    # ───────────────────────────────────────────────────
    def _open_referral_detail(self, ref_id: int):
        """نافذة تفاصيل التحويل الكاملة."""
        ref = get_referral_by_id(ref_id)
        if not ref:
            messagebox.showerror("خطأ", "لم يُعثر على التحويل")
            return

        win = tk.Toplevel(self.root)
        win.title(f"تفاصيل التحويل #{ref_id} — {ref.get('student_name','')}")
        win.geometry("700x700")
        win.transient(self.root)

        # Header
        hdr = tk.Frame(win, bg="#1565C0", height=44)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text=f"نموذج تحويل طالب إلى وكيل شؤون الطلاب  (#{ref_id})",
                 bg="#1565C0", fg="white",
                 font=("Tahoma", 11, "bold")).pack(side="right", padx=12, pady=10)
        status_lbl = _STATUS_LABELS.get(ref.get("status",""), ref.get("status",""))
        tk.Label(hdr, text=status_lbl, bg="#1565C0", fg="#FFD54F",
                 font=("Tahoma", 10, "bold")).pack(side="left", padx=12)

        # Scrollable body
        cv = tk.Canvas(win, bg="white", highlightthickness=0)
        vsb = ttk.Scrollbar(win, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        cv.pack(fill="both", expand=True)
        body = tk.Frame(cv, bg="white")
        cw = cv.create_window((0,0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(cw, width=e.width))
        cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(-1*(e.delta//120),"units"))

        def field(parent, label, value, full=False):
            r = tk.Frame(parent, bg="white"); r.pack(fill="x", padx=12, pady=2)
            tk.Label(r, text=label+":", bg="white", fg="#555",
                     font=("Tahoma", 9, "bold"), width=20, anchor="e").pack(side="right")
            tk.Label(r, text=value or "—", bg="white", fg="#111",
                     font=("Tahoma", 10),
                     wraplength=400 if full else 0,
                     justify="right", anchor="e").pack(side="right", padx=6)

        def section(parent, title, color):
            f = tk.Frame(parent, bg=color, pady=3)
            f.pack(fill="x", padx=8, pady=(10,4))
            tk.Label(f, text=title, bg=color, fg="white",
                     font=("Tahoma", 10, "bold")).pack(side="right", padx=10)

        # ── بيانات الطالب ──
        section(body, "بيانات عن الطالب", "#1565C0")
        field(body, "اسم الطالب",  ref.get("student_name",""))
        field(body, "الفصل",       ref.get("class_name",""))
        field(body, "المادة",      ref.get("subject",""))
        field(body, "الحصة",       ref.get("period",""))
        field(body, "الوقت",       f"{ref.get('session_time','')} {ref.get('session_ampm','')}")
        field(body, "التاريخ",     ref.get("ref_date",""))

        # ── إجراءات المعلم ──
        section(body, "الإجراءات التي اتخذها المعلم", "#1565C0")
        field(body, "نوع المخالفة",    ref.get("violation_type",""))
        field(body, "المخالفة",        ref.get("violation",""), full=True)
        field(body, "أسباب التحويل",   ref.get("problem_causes",""), full=True)
        field(body, "تكرار المشكلة",   "التكرار " + ref.get("repeat_count",""))
        for i, k in enumerate(["teacher_action1","teacher_action2","teacher_action3",
                                "teacher_action4","teacher_action5"], 1):
            v = ref.get(k,"")
            if v: field(body, f"الإجراء {i}", v, full=True)
        field(body, "المعلم",  ref.get("teacher_name",""))
        field(body, "التاريخ", ref.get("teacher_date",""))

        # ── إجراءات الوكيل ──
        if ref.get("deputy_name") or ref.get("deputy_action1"):
            section(body, "الإجراءات التي اتخذها وكيل المدرسة", "#0d47a1")
            field(body, "تاريخ المقابلة", ref.get("deputy_meeting_date",""))
            field(body, "الحصة",          ref.get("deputy_meeting_period",""))
            for i, k in enumerate(["deputy_action1","deputy_action2",
                                    "deputy_action3","deputy_action4"], 1):
                v = ref.get(k,"")
                if v: field(body, f"الإجراء {i}", v, full=True)
            field(body, "الوكيل",  ref.get("deputy_name",""))
            field(body, "التاريخ", ref.get("deputy_date",""))
            if ref.get("deputy_referred_date"):
                field(body, "تاريخ الإحالة للموجه", ref.get("deputy_referred_date",""))

        # ── إجراءات الموجه ──
        if ref.get("counselor_name") or ref.get("counselor_action1"):
            section(body, "الإجراءات التي اتخذها الموجه الطلابي", "#4a148c")
            field(body, "تاريخ المقابلة", ref.get("counselor_meeting_date",""))
            field(body, "الحصة",          ref.get("counselor_meeting_period",""))
            for i, k in enumerate(["counselor_action1","counselor_action2",
                                    "counselor_action3","counselor_action4"], 1):
                v = ref.get(k,"")
                if v: field(body, f"الإجراء {i}", v, full=True)
            field(body, "الموجه",  ref.get("counselor_name",""))
            field(body, "التاريخ", ref.get("counselor_date",""))

        # ── أزرار ──
        btn_row = tk.Frame(win, bg="#f0f4f8", pady=8)
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="🖨️ طباعة النموذج",
                  bg="#1565C0", fg="white",
                  font=("Tahoma", 10, "bold"), relief="flat",
                  padx=12, pady=6, cursor="hand2",
                  command=lambda: self._print_referral(ref)).pack(side="right", padx=8)
        tk.Button(btn_row, text="📱 إرسال للمدير",
                  bg="#2e7d32", fg="white",
                  font=("Tahoma", 10, "bold"), relief="flat",
                  padx=12, pady=6, cursor="hand2",
                  command=lambda: self._send_referral_to_principal(ref)).pack(side="right", padx=4)
        tk.Button(btn_row, text="✖ إغلاق",
                  bg="#757575", fg="white",
                  font=("Tahoma", 10), relief="flat",
                  padx=10, pady=6,
                  command=win.destroy).pack(side="left", padx=8)

    # ───────────────────────────────────────────────────
    def _print_referral(self, ref: dict):
        """يُنشئ HTML ويفتحه في المتصفح للطباعة."""
        html = _build_referral_html(ref)
        try:
            tmp = os.path.join(DATA_DIR, f"referral_{ref.get('id','')}_print.html")
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(html)
            webbrowser.open(f"file:///{tmp.replace(os.sep, '/')}")
        except Exception as e:
            messagebox.showerror("خطأ", f"تعذّر فتح الطباعة:\n{e}")

    def _send_referral_to_principal(self, ref: dict):
        """يُرسل ملخص التحويل للمدير عبر واتساب."""
        cfg = load_config()
        phone = cfg.get("principal_phone","")
        if not phone:
            messagebox.showwarning("تنبيه", "لم يُحدَّد جوال المدير في الإعدادات")
            return
        msg = (
            f"📋 *نموذج تحويل طالب — رقم {ref.get('id','')}*\n\n"
            f"الطالب: {ref.get('student_name','')}\n"
            f"الفصل: {ref.get('class_name','')}\n"
            f"المادة: {ref.get('subject','')}\n"
            f"نوع المخالفة: {ref.get('violation_type','')}\n"
            f"المخالفة: {ref.get('violation','')}\n"
            f"تكرار: التكرار {ref.get('repeat_count','')}\n"
            f"المعلم: {ref.get('teacher_name','')}\n"
            f"التاريخ: {ref.get('ref_date','')}"
        )
        ok, result = send_whatsapp_message(phone, msg)
        if ok:
            messagebox.showinfo("تم", "تم إرسال النموذج للمدير بنجاح")
        else:
            messagebox.showerror("خطأ", f"فشل الإرسال:\n{result}")


# ══════════════════════════════════════════════════════════════
# دالة توليد HTML للطباعة (تشبه النموذج الأصلي)
# ══════════════════════════════════════════════════════════════
def _build_referral_html(ref: dict) -> str:
    def dots(text, n=40):
        t = str(text) if text else ""
        return t + ("." * max(0, n - len(t)))

    def radio_row(options, selected):
        cells = ""
        for opt in options:
            checked = "●" if opt == selected else "○"
            cells += f'<span style="margin-left:14px">{checked} {opt}</span>'
        return cells

    teacher_actions = "".join(
        f'<tr><td style="width:22px;text-align:center;font-weight:bold">{i}</td>'
        f'<td style="border-bottom:1px dotted #999;padding:3px 6px">'
        f'{ref.get(f"teacher_action{i}","") or "&nbsp;"}</td></tr>'
        for i in range(1, 6)
    )
    deputy_actions = "".join(
        f'<tr><td style="width:22px;text-align:center;font-weight:bold">{i}</td>'
        f'<td style="border-bottom:1px dotted #999;padding:3px 6px">'
        f'{ref.get(f"deputy_action{i}","") or "&nbsp;"}</td></tr>'
        for i in range(1, 5)
    )
    counselor_actions = "".join(
        f'<tr><td style="width:22px;text-align:center;font-weight:bold">{i}</td>'
        f'<td style="border-bottom:1px dotted #999;padding:3px 6px">'
        f'{ref.get(f"counselor_action{i}","") or "&nbsp;"}</td></tr>'
        for i in range(1, 5)
    )

    def dots_td(val, w=180):
        v = val or ""
        return (f'<td style="border-bottom:1px dotted #999;padding:2px 6px;'
                f'min-width:{w}px;direction:rtl">{v}</td>')

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head><meta charset="UTF-8">
<title>نموذج تحويل طالب</title>
<style>
  body {{font-family:Tahoma,Arial,sans-serif;font-size:12px;direction:rtl;margin:20px}}
  .page-title {{text-align:center;color:#c62828;font-size:15px;font-weight:bold;
                border-bottom:2px solid #c62828;margin-bottom:12px;padding-bottom:6px}}
  .section {{border:1.5px solid #555;margin-bottom:10px;border-radius:2px}}
  .section-header {{background:#e8eaf6;padding:4px 10px;font-weight:bold;
                    font-size:12px;border-bottom:1px solid #555}}
  .section-body {{padding:8px 12px}}
  table {{width:100%;border-collapse:collapse}}
  td {{padding:3px 6px;vertical-align:top}}
  .label {{font-weight:bold;white-space:nowrap}}
  .dline {{border-bottom:1px dotted #999;min-width:120px;display:inline-block}}
  .footer-row {{display:flex;justify-content:space-between;margin-top:8px}}
  @media print {{ body{{margin:10px}} }}
</style>
</head>
<body>
<div class="page-title">"نموذج تحويل طالب إلى الوكيل"</div>

<!-- بيانات الطالب -->
<div class="section">
  <div class="section-header">بيانات عن الطالب :</div>
  <div class="section-body">
    <table>
      <tr>
        <td class="label">اسم الطالب :</td>{dots_td(ref.get('student_name',''))}
        <td class="label">الصف :</td>{dots_td(ref.get('class_name',''))}
      </tr>
      <tr>
        <td class="label">الحصة الدراسية :</td>{dots_td(ref.get('period',''),80)}
        <td class="label">المادة الدراسية :</td>{dots_td(ref.get('subject',''))}
        <td class="label">الوقت :</td>{dots_td(f"{ref.get('session_time','')} {ref.get('session_ampm','')}",80)}
      </tr>
    </table>
  </div>
</div>

<!-- إجراءات المعلم -->
<div class="section">
  <div class="section-header">الإجراءات التي اتخذها المعلم تجاه الطالب :</div>
  <div class="section-body">
    <table>
      <tr>
        <td class="label">نوع المخالفة :</td>
        <td>{radio_row(["تربوية","سلوكية","أخرى"], ref.get("violation_type",""))}</td>
        <td class="label">المخالفة :</td>{dots_td(ref.get("violation",""),140)}
      </tr>
      <tr>
        <td class="label">أسباب التحويل وإيضاح المشكلة :</td>
        <td colspan="3" style="border-bottom:1px dotted #999;padding:4px 6px">
          {ref.get("problem_causes","") or "&nbsp;"}
        </td>
      </tr>
      <tr>
        <td class="label">تكرار المشكلة :</td>
        <td colspan="3">
          {radio_row(["الأول","الثاني","الثالث","الرابع"], ref.get("repeat_count",""))}
        </td>
      </tr>
    </table>
    <div style="margin-top:6px"><b>الإجراءات التي تم اتخاذها مع الطالب :</b></div>
    <table>{teacher_actions}</table>
    <p style="font-size:11px;color:#c62828">
      <b>ملاحظة :</b> أرفق شواهد الإجراءات التي اتخذها مع الطالب
    </p>
    <div class="footer-row">
      <span><b>التوقيع :</b> <span style="display:inline-block;min-width:80px;border-bottom:1px solid #333">&nbsp;</span></span>
      <span><b>التاريخ :</b> {ref.get('teacher_date','')}</span>
      <span><b>اسم المعلم :</b> {ref.get('teacher_name','')}</span>
    </div>
  </div>
</div>

<!-- إجراءات الوكيل -->
<div class="section">
  <div class="section-header">الإجراءات التي اتخذها وكيل المدرسة تجاه الطالب :</div>
  <div class="section-body">
    <table>
      <tr>
        <td class="label">تاريخ مقابلة الطالب :</td>
        {dots_td(ref.get('deputy_meeting_date',''))}
        <td class="label">الحصة :</td>
        {dots_td(ref.get('deputy_meeting_period',''),80)}
      </tr>
    </table>
    <table style="margin-top:4px">{deputy_actions}</table>
    <div class="footer-row">
      <span><b>التوقيع :</b> <span style="display:inline-block;min-width:80px;border-bottom:1px solid #333">&nbsp;</span></span>
      <span><b>التاريخ :</b> {ref.get('deputy_date','')}</span>
      <span><b>اسم الوكيل :</b> {ref.get('deputy_name','')}</span>
    </div>
    <div style="margin-top:6px;font-size:11px">
      <b>تم إحالته إلى الموجه الطلابي بتاريخ :</b>
      {ref.get('deputy_referred_date','') or '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'}
    </div>
  </div>
</div>

<!-- إجراءات الموجه -->
<div class="section">
  <div class="section-header">الإجراءات التي اتخذها الموجه الطلابي تجاه الطالب :</div>
  <div class="section-body">
    <table>
      <tr>
        <td class="label">تاريخ مقابلة الطالب :</td>
        {dots_td(ref.get('counselor_meeting_date',''))}
        <td class="label">الحصة :</td>
        {dots_td(ref.get('counselor_meeting_period',''),80)}
      </tr>
    </table>
    <table style="margin-top:4px">{counselor_actions}</table>
    <div class="footer-row">
      <span><b>التوقيع :</b> <span style="display:inline-block;min-width:80px;border-bottom:1px solid #333">&nbsp;</span></span>
      <span><b>التاريخ :</b> {ref.get('counselor_date','')}</span>
      <span><b>اسم الموجه الطلابي :</b> {ref.get('counselor_name','')}</span>
    </div>
    <div style="margin-top:6px;font-size:11px">
      <b>تم إحالته إلى وكيل المدرسة لعدم تحسن حالة الطالب بتاريخ :</b>
      {ref.get('counselor_referred_back_date','') or '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'}
    </div>
  </div>
</div>

<div style="text-align:center;margin-top:16px">
  <button onclick="window.print()" style="padding:8px 24px;font-size:13px;cursor:pointer">
    🖨️ طباعة
  </button>
</div>
</body></html>"""
