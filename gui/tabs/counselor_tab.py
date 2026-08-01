# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
import sqlite3, subprocess
from constants import now_riyadh_date, DB_PATH, CONFIG_JSON, DATA_DIR
from config_manager import invalidate_config_cache, load_config, get_terms
from database import (get_db, load_students, insert_counselor_session, 
                      get_counselor_sessions, delete_counselor_session,
                      insert_counselor_alert, insert_behavioral_contract,
                      get_behavioral_contracts, delete_behavioral_contract)
from pdf_generator import generate_behavioral_contract_pdf, generate_session_pdf
from whatsapp_service import send_whatsapp_message, send_whatsapp_pdf

class CounselorTabMixin:
    """Mixin: CounselorTabMixin"""
    def _refresh_counselor_data(self):
        """تحديث القائمة مع مسح حقل البحث."""
        self.counselor_search_var.set("")
        self._load_counselor_data()

    def _open_class_students_dialog(self, class_id: str, class_name: str):
        """نافذة تعرض طلاب الفصل — نقرة مزدوجة على أي منهم تفتح تحليله."""
        win = tk.Toplevel(self.root)
        win.title("طلاب {} — اختر طالباً لتحليله".format(class_name))
        win.geometry("500x420")
        win.transient(self.root)

        tk.Label(win, text="طلاب {} — انقر مزدوجاً لتحليل أي طالب".format(class_name),
                 font=("Tahoma",11,"bold"),
                 bg="#1565C0", fg="white").pack(fill="x", ipady=10)

        cols = ("student_id","name","absences")
        tr = ttk.Treeview(win, columns=cols, show="headings", height=16)
        for c,h,w in zip(cols,["رقم الطالب","اسم الطالب","أيام الغياب"],[120,250,100]):
            tr.heading(c,text=h); tr.column(c,width=w,anchor="center")
        tr.tag_configure("has_abs", background="#FFEBEE", foreground="#C62828")

        # حمّل الطلاب وغيابهم
        store = load_students()
        cls_obj = next((c for c in store["list"] if c["id"]==class_id), None)
        if cls_obj:
            import sqlite3 as _sq
            con = _sq.connect(DB_PATH); con.row_factory = _sq.Row; cur = con.cursor()
            month = datetime.datetime.now().strftime("%Y-%m")
            cur.execute("""SELECT student_id, COUNT(DISTINCT date) as cnt
                           FROM absences WHERE class_id=? AND date LIKE ?
                           GROUP BY student_id""", (class_id, month+"%"))
            abs_map = {r["student_id"]: r["cnt"] for r in cur.fetchall()}
            con.close()

            for s in sorted(cls_obj["students"], key=lambda x: x["name"]):
                cnt = abs_map.get(s["id"], 0)
                tag = "has_abs" if cnt > 0 else ""
                tr.insert("","end", iid=s["id"], tags=(tag,) if tag else (),
                    values=(s["id"], s["name"],
                            "{} يوم".format(cnt) if cnt else "—"))

        sb = ttk.Scrollbar(win, orient="vertical", command=tr.yview)
        tr.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tr.pack(side="left", fill="both", expand=True)

        def on_dbl(event):
            sel = tr.selection()
            if not sel: return
            self.open_student_analysis(sel[0])

        tr.bind("<Double-1>", on_dbl)
        ttk.Label(win, text="انقر مزدوجاً على أي طالب لفتح تحليله",
                  foreground="#5A6A7E").pack(pady=6)


    # ─── تبويب الموجّه الطلابي ─────────────────────────────────────────
    def _build_counselor_tab(self):
        """بناء واجهة الموجّه الطلابي (قابلة للتمرير)."""
        main_frame = self.counselor_frame
        
        # 1. إعداد منطقة السكرول (Canvas + Scrollbar)
        canvas = tk.Canvas(main_frame, bg="#f8fafc", highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#f8fafc")

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        # ضبط عرض الإطار الداخلي ليناسب عرض الكانفس (مع guard لمنع التحديثات الزائدة)
        _csl_last_w = [0]
        def _on_canvas_configure(e):
            w = e.width
            if w == _csl_last_w[0]: return
            _csl_last_w[0] = w
            canvas.itemconfig(canvas_frame, width=w)
        canvas.bind("<Configure>", _on_canvas_configure)

        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # دعم عجلة الفأرة — نربط فقط عند دخول المؤشر لمنع التداخل مع التبويبات الأخرى
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # نستخدم الإطار الداخلي (scrollable_frame) كأصل لكافة العناصر بدلاً من frame
        frame = scrollable_frame

        # رأس التبويب
        hdr = tk.Frame(frame, bg="#7c3aed", height=60)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="👨‍🏫 مكتب الموجّه الطلابي", bg="#7c3aed", fg="white",
                 font=("Tahoma", 14, "bold")).pack(side="right", padx=20, pady=15)

        # ── شريط اختيار الموجّه النشط ──────────────────────────────
        _cfg_c = load_config()
        c1_name = _cfg_c.get("counselor1_name", "").strip() or "الموجّه الطلابي 1"
        c2_name = _cfg_c.get("counselor2_name", "").strip() or "الموجّه الطلابي 2"

        active_bar = tk.Frame(frame, bg="#ede9fe", pady=6)
        active_bar.pack(fill="x")

        tk.Label(active_bar, text="الموجّه العامل الآن:", bg="#ede9fe",
                 font=("Tahoma", 10, "bold"), fg="#5b21b6").pack(side="right", padx=(0, 14))

        self._active_counselor_var = tk.StringVar(
            value=_cfg_c.get("active_counselor", "1"))

        def _on_counselor_change(*_):
            """حفظ الاختيار فوراً في الإعداد."""
            cfg2 = load_config()
            cfg2["active_counselor"] = self._active_counselor_var.get()
            try:
                with open(CONFIG_JSON, "w", encoding="utf-8") as _f:
                    json.dump(cfg2, _f, ensure_ascii=False, indent=2)
                invalidate_config_cache()
                self._refresh_active_counselor_label()
            except Exception as _e:
                print("[counselor] خطأ حفظ:", _e)

        rb1 = tk.Radiobutton(active_bar, text=c1_name,
                             variable=self._active_counselor_var, value="1",
                             bg="#ede9fe", font=("Tahoma", 10, "bold"),
                             fg="#5b21b6", activebackground="#ede9fe",
                             selectcolor="#7c3aed", command=_on_counselor_change)
        rb1.pack(side="right", padx=8)

        rb2 = tk.Radiobutton(active_bar, text=c2_name,
                             variable=self._active_counselor_var, value="2",
                             bg="#ede9fe", font=("Tahoma", 10, "bold"),
                             fg="#5b21b6", activebackground="#ede9fe",
                             selectcolor="#7c3aed", command=_on_counselor_change)
        rb2.pack(side="right", padx=8)

        self._active_lbl = tk.Label(active_bar, text="", bg="#ede9fe",
                                    font=("Tahoma", 9, "italic"), fg="#7c3aed")
        self._active_lbl.pack(side="left", padx=16)
        self._refresh_active_counselor_label()
        # ────────────────────────────────────────────────────────────

        # منطقة البحث والاختيار
        search_fr = tk.Frame(frame, bg="#f8fafc", pady=10)
        search_fr.pack(fill="x", padx=20, pady=10)

        tk.Label(search_fr, text="بحث عن طالب:", bg="#f8fafc").pack(side="right", padx=5)
        self.counselor_search_var = tk.StringVar()
        search_ent = ttk.Entry(search_fr, textvariable=self.counselor_search_var, width=30)
        search_ent.pack(side="right", padx=5)
        search_ent.bind("<KeyRelease>", lambda e: self._filter_counselor_students())

        # قائمة الطلاب (الذين لديهم غياب أو تأخر متكرر)
        list_fr = tk.Frame(frame, bg="white")
        list_fr.pack(fill="both", expand=True, padx=20, pady=5)

        cols = ("id", "name", "class", "absences", "tardiness", "last_action")
        self.tree_counselor = ttk.Treeview(list_fr, columns=cols, show="headings", height=10)

        headings = {"id":"ID", "name":"اسم الطالب", "class":"الفصل",
                    "absences":"أيام الغياب", "tardiness":"مرات التأخر", "last_action":"آخر إجراء"}
        for c, h in headings.items():
            self.tree_counselor.heading(c, text=h)
            self.tree_counselor.column(c, width=100 if c in ("absences","tardiness") else 150, anchor="center")

        self.tree_counselor.column("id", width=0, stretch=False)  # إخفاء المعرف

        sb = ttk.Scrollbar(list_fr, orient="vertical", command=self.tree_counselor.yview)
        self.tree_counselor.configure(yscrollcommand=sb.set)
        self.tree_counselor.pack(side="right", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        self.tree_counselor.bind("<<TreeviewSelect>>", self._on_counselor_student_select)

        # أزرار الإجراءات
        btn_fr = tk.Frame(frame, bg="white", pady=10)
        btn_fr.pack(fill="x", padx=20)

        ttk.Button(btn_fr, text="📝 عقد جلسة إرشادية", command=self._open_session_dialog).pack(side="right", padx=5)
        ttk.Button(btn_fr, text="📋 عقد سلوكي", command=self._open_behavioral_contract_dialog,
                   style="Accent.TButton").pack(side="right", padx=5)
        ttk.Button(btn_fr, text="🔔 إرسال تنبيه (واتساب)", command=lambda: self._send_counselor_alert("تنبيه")).pack(side="right", padx=5)
        ttk.Button(btn_fr, text="✉️ توجيه استدعاء رسمي", command=lambda: self._send_counselor_alert("استدعاء")).pack(side="right", padx=5)
        ttk.Button(btn_fr, text="📊 سجل الطالب الإرشادي", command=self._show_student_counseling_history).pack(side="right", padx=5)
        
        # الزر المفقود: اتخاذ إجراء على التحويل (للحالات السلوكية)
        self._btn_referral_action = ttk.Button(btn_fr, text="⚡ اتخاذ إجراء على التحويل", 
                                                command=self._open_referral_action_dialog)
        self._btn_referral_action.pack(side="right", padx=15)
        self._btn_referral_action.state(["disabled"])
        
        ttk.Button(btn_fr, text="🔄 تحديث القائمة", command=self._refresh_counselor_data).pack(side="left", padx=5)
        # ── زر إضافة طالب يدوياً للموجّه ─────────────────────────
        tk.Button(btn_fr, text="➕ إضافة طالب يدوياً",
                  bg="#7c3aed", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=10, pady=4,
                  command=self._add_student_to_counselor_manually).pack(side="left", padx=8)
        # ── زر حذف الطالب من قائمة الموجّه ───────────────────────
        tk.Button(btn_fr, text="🗑️ حذف الطالب",
                  bg="#dc2626", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=10, pady=4,
                  command=self._delete_student_from_counselor).pack(side="left", padx=8)

        # ────────────────────────────────────────────────────────
        # أرشيف الجلسات والعقود لمراجعتها
        # ────────────────────────────────────────────────────────
        archive_fr = tk.Frame(frame, bg="white", pady=10)
        archive_fr.pack(fill="x", padx=20)

        # أرشيف الجلسات
        session_bar = tk.Frame(archive_fr, bg="#f5f3ff", pady=6)
        session_bar.pack(fill="x", pady=2)
        tk.Label(session_bar, text="📚 أرشيف الجلسات الإرشادية",
                 bg="#f5f3ff", font=("Tahoma", 10, "bold"), fg="#5b21b6").pack(side="right", padx=10)
        tk.Button(session_bar, text="عرض جميع الجلسات القديمة",
                  bg="#5b21b6", fg="white", font=("Tahoma", 9, "bold"),
                  relief="flat", cursor="hand2", padx=10,
                  command=self._open_sessions_archive).pack(side="right", padx=10)
        tk.Label(session_bar, text="اضغط لاسترجاع أي جلسة وطباعتها أو إرسالها",
                 bg="#f5f3ff", font=("Tahoma", 9), fg="#7c3aed").pack(side="right", padx=4)

        # أرشيف العقود
        contract_bar = tk.Frame(archive_fr, bg="#fef3c7", pady=6)
        contract_bar.pack(fill="x", pady=2)
        tk.Label(contract_bar, text="📜 أرشيف العقود السلوكية",
                 bg="#fef3c7", font=("Tahoma", 10, "bold"), fg="#92400e").pack(side="right", padx=10)
        tk.Button(contract_bar, text="عرض جميع العقود السلوكية",
                  bg="#d97706", fg="white", font=("Tahoma", 9, "bold"),
                  relief="flat", cursor="hand2", padx=10,
                  command=self._open_contracts_archive).pack(side="right", padx=10)
        tk.Label(contract_bar, text="اضغط لاسترجاع أي عقد وطباعته أو إرساله",
                 bg="#fef3c7", font=("Tahoma", 9), fg="#92400e").pack(side="right", padx=4)
        # ────────────────────────────────────────────────────────

        # ══════════════════════════════════════════════════════════
        # قسم خطابات الاستفسار الأكاديمي
        # ══════════════════════════════════════════════════════════
        inq_lf = tk.LabelFrame(frame, text=" 📩 خطابات الاستفسار الأكاديمي ",
                               font=("Tahoma", 11, "bold"), fg="#7E22CE",
                               bg="#FAF5FF", padx=10, pady=8)
        inq_lf.pack(fill="both", expand=True, padx=20, pady=(6, 10))

        # ── نموذج إرسال استفسار جديد ──────────────────────────────
        inq_form = tk.Frame(inq_lf, bg="#FAF5FF")
        inq_form.pack(fill="x", padx=5, pady=5)

        # صف 0: المعلم + الفصل
        tk.Label(inq_form, text="المعلم:", bg="#FAF5FF").grid(row=0, column=4, padx=5, pady=2, sticky="e")
        self.coun_inq_teacher_var = tk.StringVar()
        self.coun_inq_teacher_cb = ttk.Combobox(inq_form, textvariable=self.coun_inq_teacher_var, state="readonly", width=24)
        self.coun_inq_teacher_cb.grid(row=0, column=3, padx=5, pady=2)

        tk.Label(inq_form, text="الفصل:", bg="#FAF5FF").grid(row=0, column=2, padx=5, pady=2, sticky="e")
        self.coun_inq_class_var = tk.StringVar()
        self.coun_inq_class_cb = ttk.Combobox(inq_form, textvariable=self.coun_inq_class_var, state="readonly", width=15)
        self.coun_inq_class_cb.grid(row=0, column=1, padx=5, pady=2)
        try:
            _tmp_store = load_students()
            self.coun_inq_class_cb['values'] = [c["name"] for c in _tmp_store.get("list", [])]
        except: pass

        # صف 1: المادة + الطالب
        tk.Label(inq_form, text="المادة:", bg="#FAF5FF").grid(row=1, column=4, padx=5, pady=2, sticky="e")
        self.coun_inq_subject_var = tk.StringVar()
        tk.Entry(inq_form, textvariable=self.coun_inq_subject_var, width=27).grid(row=1, column=3, padx=5, pady=2)

        tk.Label(inq_form, text="الطالب:", bg="#FAF5FF").grid(row=1, column=2, padx=5, pady=2, sticky="e")
        self.coun_inq_student_var = tk.StringVar(value="الكل")
        self.coun_inq_student_cb = ttk.Combobox(inq_form, textvariable=self.coun_inq_student_var, state="readonly", width=15)
        self.coun_inq_student_cb.grid(row=1, column=1, padx=5, pady=2)


        # تحديث قائمة الطلاب عند تغيير الفصل
        def _on_inq_class_change(event=None):
            chosen = self.coun_inq_class_var.get()
            if not chosen:
                return
            st_data = []
            try:
                store = load_students()
                for c in store.get("list", []):
                    if c["name"] == chosen:
                        st_data = c.get("students", [])
                        break
            except: pass
            vals = ["الكل"] + [s["name"] for s in st_data]
            self.coun_inq_student_cb['values'] = vals
            self.coun_inq_student_var.set("الكل")

        self.coun_inq_class_cb.bind("<<ComboboxSelected>>", _on_inq_class_change)

        # زر الإرسال
        tk.Button(inq_form, text="📤 إرسال الاستفسار", bg="#7E22CE", fg="white", font=("Tahoma", 9, "bold"),
                  relief="flat", cursor="hand2", padx=15, command=self._send_academic_inquiry).grid(row=0, column=0, rowspan=2, padx=15, pady=5)

        # ── جدول الخطابات ─────────────────────────────────────────
        inq_list_fr = tk.Frame(inq_lf, bg="white")
        inq_list_fr.pack(fill="both", expand=True, padx=5, pady=5)

        inq_tool = tk.Frame(inq_list_fr, bg="white")
        inq_tool.pack(fill="x", pady=5)
        tk.Label(inq_tool, text="سجل الاستفسارات الأكاديمية:", bg="white", font=("Tahoma", 10, "bold")).pack(side="right")
        tk.Button(inq_tool, text="🔄 تحديث", command=self._load_academic_inquiries, bg="#E2E8F0", relief="flat", padx=8).pack(side="left", padx=5)
        tk.Button(inq_tool, text="🖨️ طباعة", command=self._print_academic_inquiry, bg="#10B981", fg="white", relief="flat", padx=8).pack(side="left")
        tk.Button(inq_tool, text="عرض الرد", command=self._view_academic_inquiry_reply, bg="#3B82F6", fg="white", relief="flat", padx=8).pack(side="left", padx=5)

        inq_cols = ("id", "date", "teacher", "class", "subject", "student", "status")
        self._coun_inq_tree = ttk.Treeview(inq_list_fr, columns=inq_cols, show="headings", height=8)
        for c, h, w in zip(inq_cols, ["#", "التاريخ", "المعلم", "الفصل", "المادة", "الطالب", "الحالة"], [35, 90, 160, 100, 100, 140, 110]):
            self._coun_inq_tree.heading(c, text=h)
            self._coun_inq_tree.column(c, width=w, anchor="center")

        inq_sb = ttk.Scrollbar(inq_list_fr, orient="vertical", command=self._coun_inq_tree.yview)
        self._coun_inq_tree.configure(yscrollcommand=inq_sb.set)
        inq_sb.pack(side="right", fill="y")
        self._coun_inq_tree.pack(side="left", fill="both", expand=True)
        self._coun_inq_tree.bind("<Double-1>", lambda e: self._view_academic_inquiry_reply())

        self._load_academic_inquirers_teachers()
        self._load_academic_inquiries()

        self._load_counselor_data()


    def _get_active_counselor_name(self) -> str:
        """يُرجع اسم الموجّه النشط حالياً."""
        cfg = load_config()
        which = cfg.get("active_counselor", "1")
        if which == "2":
            name = cfg.get("counselor2_name", "").strip()
            return name if name else "الموجّه الطلابي 2"
        else:
            name = cfg.get("counselor1_name", "").strip()
            return name if name else "الموجّه الطلابي 1"

    def _refresh_active_counselor_label(self):
        """يحدّث نص التسمية التوضيحية للموجّه النشط."""
        if not hasattr(self, "_active_lbl"):
            return
        name = self._get_active_counselor_name()
        self._active_lbl.config(text=f"✅ يعمل الآن: {name}")

    def _add_student_to_counselor_manually(self):
        """إضافة أي طالب يدوياً لقائمة الموجّه الطلابي بدون الحاجة لتحويل من وكيل شؤون الطلاب."""
        win = tk.Toplevel(self.root)
        win.title("➕ إضافة طالب يدوياً للموجّه")
        win.geometry("500x420")
        win.resizable(False, False)
        win.grab_set()

        # رأس النافذة
        hdr = tk.Frame(win, bg="#7c3aed", height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="➕ إضافة طالب يدوياً لقائمة الموجّه",
                 bg="#7c3aed", fg="white", font=("Tahoma", 12, "bold")).pack(pady=13)

        body = tk.Frame(win, bg="white", padx=20, pady=15)
        body.pack(fill="both", expand=True)

        # ── اختيار الطالب من قائمة الفصول ──────────────────────
        tk.Label(body, text="الفصل:", bg="white", font=("Tahoma", 10, "bold"),
                 anchor="e").grid(row=0, column=1, sticky="e", pady=6, padx=5)
        class_var = tk.StringVar()
        class_cb = ttk.Combobox(body, textvariable=class_var, state="readonly", width=28, font=("Tahoma", 10))
        class_cb.grid(row=0, column=0, sticky="w", pady=6)

        tk.Label(body, text="الطالب:", bg="white", font=("Tahoma", 10, "bold"),
                 anchor="e").grid(row=1, column=1, sticky="e", pady=6, padx=5)
        student_var = tk.StringVar()
        student_cb = ttk.Combobox(body, textvariable=student_var, state="readonly", width=28, font=("Tahoma", 10))
        student_cb.grid(row=1, column=0, sticky="w", pady=6)

        tk.Label(body, text="سبب الإضافة:", bg="white", font=("Tahoma", 10, "bold"),
                 anchor="e").grid(row=2, column=1, sticky="e", pady=6, padx=5)
        reason_var = tk.StringVar(value="غياب")
        reason_cb = ttk.Combobox(body, textvariable=reason_var, state="readonly", width=28, font=("Tahoma", 10),
                                  values=["غياب", "تأخر", "سلوك", "أكاديمي", "أخرى"])
        reason_cb.grid(row=2, column=0, sticky="w", pady=6)

        tk.Label(body, text="ملاحظات:", bg="white", font=("Tahoma", 10, "bold"),
                 anchor="e").grid(row=3, column=1, sticky="ne", pady=6, padx=5)
        notes_txt = tk.Text(body, width=30, height=4, font=("Tahoma", 10))
        notes_txt.grid(row=3, column=0, sticky="w", pady=6)

        # ── تحميل بيانات الطلاب ──────────────────────────────────
        store = load_students()
        classes_data = {}  # {class_name: [(student_id, student_name), ...]}
        for cls in store.get("list", []):
            cname = cls.get("name", "")
            classes_data[cname] = [(s["id"], s["name"]) for s in cls.get("students", [])]

        class_cb["values"] = sorted(classes_data.keys())

        def _on_class_change(event=None):
            chosen = class_var.get()
            students = classes_data.get(chosen, [])
            student_cb["values"] = [f"{s[1]} ({s[0]})" for s in students]
            student_cb.set("")
        class_cb.bind("<<ComboboxSelected>>", _on_class_change)

        # ── زر الحفظ ─────────────────────────────────────────────
        def _do_save():
            cname   = class_var.get().strip()
            stu_sel = student_var.get().strip()
            reason  = reason_var.get().strip()
            notes   = notes_txt.get("1.0", "end").strip()

            if not cname or not stu_sel:
                messagebox.showwarning("تنبيه", "الرجاء اختيار الفصل والطالب", parent=win)
                return

            # استخراج الـ id والاسم من النص المختار (الصيغة: "اسم الطالب (id)")
            import re as _re
            m = _re.match(r"^(.*)\s+\((\w+)\)$", stu_sel)
            if not m:
                messagebox.showerror("خطأ", "لم يتم التعرف على الطالب المختار", parent=win)
                return
            sname = m.group(1).strip()
            sid   = m.group(2).strip()

            # حساب الغياب والتأخر الفعلي
            con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
            cur.execute("SELECT COUNT(DISTINCT date) as c FROM absences WHERE student_id=?", (sid,))
            row = cur.fetchone(); abs_c = row["c"] if row else 0
            cur.execute("SELECT COUNT(*) as c FROM tardiness WHERE student_id=?", (sid,))
            row = cur.fetchone(); tard_c = row["c"] if row else 0

            # التحقق أن الطالب غير موجود مسبقاً هذا الشهر
            now_str  = datetime.datetime.now().isoformat()
            date_str = now_str[:10]
            month_prefix = date_str[:7]
            cur.execute("""SELECT id FROM counselor_referrals
                           WHERE student_id=? AND date LIKE ?""", (sid, month_prefix + "%"))
            existing = cur.fetchone()

            if existing:
                if not messagebox.askyesno("طالب موجود",
                        f"الطالب {sname} موجود بالفعل في قائمة الموجّه هذا الشهر.\nهل تريد إضافته مرة أخرى؟",
                        parent=win):
                    con.close(); return

            cur.execute("""
                INSERT INTO counselor_referrals
                    (date, student_id, student_name, class_name, referral_type,
                     absence_count, tardiness_count, notes, referred_by, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (date_str, sid, sname, cname, reason,
                  abs_c, tard_c, notes, "إضافة يدوية", "جديد", now_str))
            con.commit(); con.close()

            messagebox.showinfo("تم", f"✅ تم إضافة الطالب {sname} لقائمة الموجّه بنجاح", parent=win)
            win.destroy()
            self._load_counselor_data()

        btn_fr2 = tk.Frame(body, bg="white")
        btn_fr2.grid(row=4, column=0, columnspan=2, pady=14)
        tk.Button(btn_fr2, text="✅ حفظ", bg="#7c3aed", fg="white",
                  font=("Tahoma", 11, "bold"), relief="flat", cursor="hand2",
                  padx=20, pady=6, command=_do_save).pack(side="right", padx=8)
        tk.Button(btn_fr2, text="إلغاء", bg="#e5e7eb", fg="#374151",
                  font=("Tahoma", 11), relief="flat", cursor="hand2",
                  padx=20, pady=6, command=win.destroy).pack(side="right", padx=8)

    def _delete_student_from_counselor(self):
        """حذف الطالب المحدد من قائمة الموجّه الطلابي (جميع سجلاته في counselor_referrals)."""
        from database import authenticate
        from constants import CURRENT_USER
        from tkinter import simpledialog
        sel = self.tree_counselor.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "الرجاء اختيار طالب أولاً لحذفه")
            return

        values = self.tree_counselor.item(sel[0], "values")
        sid   = values[0]
        sname = values[1]
        scls  = values[2]

        if not messagebox.askyesno(
            "تأكيد الحذف",
            f"هل أنت متأكد من حذف الطالب:\n\n👤 {sname}\n🏫 {scls}\n\nمن قائمة الموجّه الطلابي؟\n"
            "(سيتم حذف جميع سجلات تحويله فقط، ولن يُحذف من بيانات المدرسة)"
        ):
            return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        try:
            con = get_db(); cur = con.cursor()
            cur.execute("DELETE FROM counselor_referrals WHERE student_id=?", (sid,))
            con.commit(); con.close()
            messagebox.showinfo("تم الحذف", f"✅ تم حذف الطالب {sname} من قائمة الموجّه بنجاح")
            self._load_counselor_data()
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل الحذف:\n{e}")

    def _load_counselor_data(self):
        """تحميل الطلاب المحوّلين من وكيل شؤون الطلاب (غياب + سلوك)."""
        # حذف جميع العناصر بشكل آمن (بما فيها المخفية بـ detach)
        self.tree_counselor.delete(*self.tree_counselor.get_children())

        con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()

        # 1. جلب محولي الغياب والتأخر
        cur.execute("""
            SELECT id, student_id, student_name, class_name,
                   referral_type, absence_count, tardiness_count,
                   date, status, notes, 'attendance' as source
            FROM counselor_referrals
            ORDER BY date DESC
        """)
        rows_att = [dict(r) for r in cur.fetchall()]

        # 2. جلب المحولين سلوكياً (من المعلم والوكيل)
        cur.execute("""
            SELECT id, student_id, student_name, class_name,
                   violation_type as referral_type, 0 as absence_count, 0 as tardiness_count,
                   ref_date as date, status, violation as notes, 'behavior' as source
            FROM student_referrals
            WHERE status = 'with_counselor'
            ORDER BY ref_date DESC
        """)
        rows_beh = [dict(r) for r in cur.fetchall()]

        # دمج القائمة والترتيب حسب التاريخ
        all_referrals = rows_att + rows_beh
        all_referrals.sort(key=lambda x: x.get("date", ""), reverse=True)

        # إزالة التكرار (نفس الطالب قد يُحوَّل أكثر من مرة — نُبقي الأحدث)
        seen = set()
        unique_referrals = []
        for ref in all_referrals:
            if ref["student_id"] not in seen:
                seen.add(ref["student_id"])
                unique_referrals.append(ref)

        # حفظ بيانات الطلاب لاستخدامها في الفلتر
        self._all_counselor_rows = []

        for ref in unique_referrals:
            sid  = ref["student_id"]
            name = ref["student_name"]
            cls  = ref["class_name"]

            # احسب الغياب والتأخر الفعلي من جداول الأحداث
            cur.execute("SELECT COUNT(DISTINCT date) as c FROM absences WHERE student_id=?", (sid,))
            row = cur.fetchone(); abs_c = row["c"] if row else ref["absence_count"]

            cur.execute("SELECT COUNT(*) as c FROM tardiness WHERE student_id=?", (sid,))
            row = cur.fetchone(); tard_c = row["c"] if row else ref["tardiness_count"]

            # آخر إجراء
            cur.execute("""SELECT type, date FROM counselor_alerts
                           WHERE student_id=? ORDER BY date DESC LIMIT 1""", (sid,))
            last = cur.fetchone()
            last_action = "{} ({})".format(last["type"], last["date"]) if last else "لا يوجد"

            if ref.get("source") == "behavior":
                tag = "referred_behavioral"
                item_iid = f"beh_{ref['id']}"
            else:
                tag = "referred_absence" if ref["referral_type"] == "غياب" else "referred_tardiness"
                item_iid = f"att_{sid}"
            
            row_data = (sid, name, cls, abs_c, tard_c, last_action, tag)
            self._all_counselor_rows.append(row_data)
            self.tree_counselor.insert("", "end", iid=item_iid, values=(sid, name, cls, abs_c, tard_c, last_action), tags=(tag,))

        con.close()

        # تلوين الصفوف حسب نوع التحويل
        self.tree_counselor.tag_configure("referred_absence",
            background="#FFF0F0", foreground="#991B1B")
        self.tree_counselor.tag_configure("referred_tardiness",
            background="#FFF7ED", foreground="#9A3412")
        self.tree_counselor.tag_configure("referred_behavioral",
            background="#F5F3FF", foreground="#5B21B6")

    def _filter_counselor_students(self):
        query = self.counselor_search_var.get().strip().lower()
        if not query:
            # بحث فارغ → أعد تحميل الكل من قاعدة البيانات
            self._load_counselor_data()
            return
        # أعد بناء القائمة بالعناصر المطابقة فقط (بدون detach لتجنب مشكلة بقاء العناصر المخفية)
        self.tree_counselor.delete(*self.tree_counselor.get_children())
        if not hasattr(self, "_all_counselor_rows"):
            self._load_counselor_data()
            return
        for row_data in self._all_counselor_rows:
            sid, name, cls, abs_c, tard_c, last_action, tag = row_data
            if query in str(name).lower() or query in str(cls).lower() or query in str(sid).lower():
                self.tree_counselor.insert("", "end", values=(sid, name, cls, abs_c, tard_c, last_action), tags=(tag,))
        self.tree_counselor.tag_configure("referred_absence",
            background="#FFF0F0", foreground="#991B1B")
        self.tree_counselor.tag_configure("referred_tardiness",
            background="#FFF7ED", foreground="#9A3412")
        self.tree_counselor.tag_configure("referred_behavioral",
            background="#F5F3FF", foreground="#5B21B6")

    def _on_counselor_student_select(self, event):
        sel = self.tree_counselor.selection()
        if not sel:
            self._btn_referral_action.state(["disabled"])
            return
        
        iid = sel[0]
        if iid.startswith("beh_"):
            self._btn_referral_action.state(["!disabled"])
        else:
            self._btn_referral_action.state(["disabled"])

    def _open_referral_action_dialog(self):
        """فتح نافذة إجراءات الموجه على التحويلات السلوكية (النموذج المفقود)."""
        sel = self.tree_counselor.selection()
        if not sel: return
        
        iid = sel[0]
        if not iid.startswith("beh_"):
            messagebox.showinfo("تنبيه", "هذا الإجراء مخصص للتحويلات السلوكية فقط.")
            return
            
        ref_id = int(iid.split("_")[1])
        from database import get_referral_by_id, update_referral_counselor, close_referral
        ref = get_referral_by_id(ref_id)
        if not ref:
            messagebox.showerror("خطأ", "لم يتم العثور على بيانات التحويل.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"إجراءات الموجه - {ref.get('student_name','')}")
        win.geometry("700x850")
        win.configure(bg="#f8fafc")
        
        # حاوية مع سكرول
        outer = tk.Frame(win, bg="#f8fafc"); outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg="#f8fafc", highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        scroll_fr = tk.Frame(canvas, bg="#f8fafc")
        scroll_fr.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=scroll_fr, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)

        def header(txt, bg="#7c3aed"):
            f = tk.Frame(scroll_fr, bg=bg, pady=5)
            f.pack(fill="x", padx=10, pady=(10,2))
            tk.Label(f, text=txt, bg=bg, fg="white", font=("Tahoma", 10, "bold")).pack()

        def row(lbl, val):
            r = tk.Frame(scroll_fr, bg="white")
            r.pack(fill="x", padx=10, pady=1)
            tk.Label(r, text=lbl+":", bg="white", font=("Tahoma", 9, "bold"), width=15, anchor="e").pack(side="right", padx=5)
            tk.Label(r, text=val or "—", bg="white", font=("Tahoma", 10), anchor="w", justify="right").pack(side="right", padx=5)

        # 1. بيانات التحويل الأساسية (المعلم)
        header("📤 تفاصيل تحويل المعلم")
        row("المعلم", ref.get("teacher_name"))
        row("التاريخ", ref.get("ref_date"))
        row("المخالفة", f"{ref.get('violation_type')} - {ref.get('violation')}")
        row("الأسباب", ref.get("problem_causes"))
        for i in range(1,6):
            act = ref.get(f"teacher_action{i}")
            if act: row(f"إجراء المعلم {i}", act)

        # 2. بيانات الوكيل
        header("📋 إجراءات وكيل شؤون الطلاب", "#0f172a")
        row("الوكيل", ref.get("deputy_name"))
        row("تاريخ المقابلة", ref.get("deputy_meeting_date"))
        for i in range(1,5):
            act = ref.get(f"deputy_action{i}")
            if act: row(f"إجراء الوكيل {i}", act)

        # 3. إجراءات الموجه (المدخلات)
        header("👨‍🏫 إجراءات الموجه الطلابي (نموذج التعامل)", "#1d4ed8")
        
        entry_fr = tk.Frame(scroll_fr, bg="white", pady=10)
        entry_fr.pack(fill="x", padx=10, pady=5)

        tk.Label(entry_fr, text="تاريخ المقابلة:", bg="white").grid(row=0, column=1, sticky="w", padx=5, pady=5)
        meet_date_var = tk.StringVar(value=ref.get("counselor_meeting_date") or now_riyadh_date())
        tk.Entry(entry_fr, textvariable=meet_date_var, width=15).grid(row=0, column=0, sticky="e", padx=5)

        tk.Label(entry_fr, text="الحصة:", bg="white").grid(row=1, column=1, sticky="w", padx=5, pady=5)
        period_var = tk.StringVar(value=ref.get("counselor_meeting_period") or "")
        ttk.Combobox(entry_fr, textvariable=period_var, values=[str(i) for i in range(1,10)], width=5).grid(row=1, column=0, sticky="e", padx=5)

        action_vars = []
        action_labels = ["التوجيه والإرشاد الفردي", "أخذ تعهد وإشعار ولي الأمر", "تحويل للهيئة الإدارية", "أخرى / ملاحظات"]
        for i, lbl in enumerate(action_labels, 1):
            tk.Label(entry_fr, text=f"الإجراء {i} ({lbl}):", bg="white").grid(row=i+1, column=1, sticky="w", padx=5, pady=5)
            v = tk.StringVar(value=ref.get(f"counselor_action{i}") or "")
            action_vars.append(v)
            tk.Entry(entry_fr, textvariable=v, width=40).grid(row=i+1, column=0, sticky="e", padx=5)

        tk.Label(entry_fr, text="توقيع الموجه:", bg="white").grid(row=6, column=1, sticky="w", padx=5, pady=5)
        cname_var = tk.StringVar(value=ref.get("counselor_name") or self._get_active_counselor_name())
        tk.Entry(entry_fr, textvariable=cname_var, width=25).grid(row=6, column=0, sticky="e", padx=5)

        # الأزرار
        btn_low = tk.Frame(scroll_fr, bg="#f1f5f9", pady=15)
        btn_low.pack(fill="x", side="bottom")

        def _save_counselor(close=False):
            data = {
                "counselor_meeting_date": meet_date_var.get(),
                "counselor_meeting_period": period_var.get(),
                "counselor_name": cname_var.get(),
                "counselor_date": now_riyadh_date(),
                "status": "resolved" if close else "with_counselor"
            }
            for i, v in enumerate(action_vars, 1):
                data[f"counselor_action{i}"] = v.get()
            
            try:
                update_referral_counselor(ref_id, data)
                messagebox.showinfo("نجاح", "تم حفظ إجراءات الموجه بنجاح.")
                win.destroy()
                self._load_counselor_data()
            except Exception as e:
                messagebox.showerror("خطأ", f"فشل الحفظ: {e}")

        tk.Button(btn_low, text="💾 حفظ التعديلات", bg="#1d4ed8", fg="white", font=("Tahoma", 10, "bold"),
                  command=lambda: _save_counselor(False), padx=15).pack(side="right", padx=10)
        
        tk.Button(btn_low, text="✅ إنهاء الإجراء (إغلاق التحويل)", bg="#059669", fg="white", font=("Tahoma", 10, "bold"),
                  command=lambda: _save_counselor(True), padx=15).pack(side="right", padx=10)

        tk.Button(btn_low, text="إلغاء", bg="#94a3b8", fg="white", command=win.destroy, padx=15).pack(side="left", padx=10)

    def _open_session_dialog(self, sid=None, sname=None, sclass=None, sabs=None, stard=None):
        """نافذة جلسة إرشادية فردية وفق نموذج وزارة التعليم — مع خانات اختيار."""
        if sid is None:
            sel = self.tree_counselor.selection()
            if not sel:
                messagebox.showwarning("تنبيه", "الرجاء اختيار طالب أولاً")
                return
            sid, sname, sclass, sabs, stard, _ = self.tree_counselor.item(sel[0], "values")

        cfg    = load_config()
        school = cfg.get("school_name", "المدرسة")
        # استخدم اسم الموجّه النشط حالياً كتوقيع على كل الأعمال
        counselor_name  = self._get_active_counselor_name()
        principal_phone = cfg.get("principal_phone", "")
        deputy_phone    = cfg.get("alert_admin_phone", "")

        today_h = datetime.datetime.now().strftime("%Y/%m/%d")

        win = tk.Toplevel(self.root)
        win.title(f"جلسة إرشاد فردي — {sname}")
        win.geometry("820x860")
        win.resizable(True, True)
        win.configure(bg="#f0f4f8")
        try: win.state("zoomed")
        except: pass

        outer = tk.Frame(win, bg="#f0f4f8"); outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg="#f0f4f8", highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg="#f0f4f8")
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        def _on_mw(e): canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        win.bind("<MouseWheel>", _on_mw)
        win.protocol("WM_DELETE_WINDOW", lambda: (win.unbind("<MouseWheel>"), win.destroy()))

        main = scroll_frame
        BORDER   = dict(relief="solid", bd=1)
        FONT_H   = ("Tahoma", 11, "bold")
        FONT_N   = ("Tahoma", 10)
        FONT_S   = ("Tahoma", 9)
        PURPLE   = "#7c3aed"
        BG_WHITE = "white"

        # رأس النموذج
        hdr_fr = tk.Frame(main, bg=PURPLE, pady=8); hdr_fr.pack(fill="x", padx=12, pady=(12,4))
        tk.Label(hdr_fr, text="جلسة إرشاد فردي", bg=PURPLE, fg="white",
                 font=("Tahoma",14,"bold")).pack()
        tk.Label(hdr_fr, text=school, bg=PURPLE, fg="#ddd6fe", font=("Tahoma",9)).pack()

        # بيانات الطالب
        info_fr = tk.LabelFrame(main, text=" بيانات الطالب ", font=FONT_H,
                                bg=BG_WHITE, **BORDER, padx=10, pady=8)
        info_fr.pack(fill="x", padx=12, pady=4)
        info_fr.configure(fg=PURPLE)

        row1 = tk.Frame(info_fr, bg=BG_WHITE); row1.pack(fill="x", pady=2)
        tk.Label(row1, text="اسم الطالب:", bg=BG_WHITE, font=FONT_N, width=12, anchor="e").pack(side="right")
        tk.Label(row1, text=str(sname), bg="#f5f3ff", font=("Tahoma",10,"bold"),
                 relief="sunken", bd=1, width=25, anchor="center").pack(side="right", padx=6)
        tk.Label(row1, text="الفصل:", bg=BG_WHITE, font=FONT_N, width=8, anchor="e").pack(side="right")
        tk.Label(row1, text=str(sclass), bg="#f5f3ff", font=("Tahoma",10,"bold"),
                 relief="sunken", bd=1, width=14, anchor="center").pack(side="right", padx=6)

        row2 = tk.Frame(info_fr, bg=BG_WHITE); row2.pack(fill="x", pady=2)
        tk.Label(row2, text="عنوان الجلسة:", bg=BG_WHITE, font=FONT_N, width=12, anchor="e").pack(side="right")
        session_title_var = tk.StringVar(value="الانضباط المدرسي")
        ttk.Entry(row2, textvariable=session_title_var, width=25, font=FONT_N).pack(side="right", padx=6)
        tk.Label(row2, text="مكانها:", bg=BG_WHITE, font=FONT_N, width=8, anchor="e").pack(side="right")
        tk.Label(row2, text="مكتب المرشد الطلابي", bg="#f5f3ff", font=FONT_S,
                 relief="sunken", bd=1, width=16, anchor="center").pack(side="right", padx=6)

        row3 = tk.Frame(info_fr, bg=BG_WHITE); row3.pack(fill="x", pady=2)
        tk.Label(row3, text="زمن الجلسة:", bg=BG_WHITE, font=FONT_N, width=12, anchor="e").pack(side="right")
        tk.Label(row3, text="30 دقيقة", bg="#f5f3ff", font=FONT_S,
                 relief="sunken", bd=1, width=10, anchor="center").pack(side="right", padx=6)
        tk.Label(row3, text="تاريخها:", bg=BG_WHITE, font=FONT_N, width=8, anchor="e").pack(side="right")
        date_var = tk.StringVar(value=today_h)
        ttk.Entry(row3, textvariable=date_var, width=14, font=FONT_N).pack(side="right", padx=6)

        # أهداف الجلسة
        goals_fr = tk.LabelFrame(main, text=" الهدف من الجلسة :- ", font=FONT_H,
                                 bg=BG_WHITE, **BORDER, padx=10, pady=8)
        goals_fr.pack(fill="x", padx=12, pady=4)
        goals_fr.configure(fg=PURPLE)

        DEFAULT_GOALS = [
            ("الحد من غياب الطالب المتكرر بلا عذر",              True),
            ("أن يدرك الطالب أضرار الغياب على تحصيله الدراسي",  True),
            ("أن ينظم الطالب وقته ويجتهد في دراسته",             True),
        ]
        goal_vars = []
        for i, (text, default) in enumerate(DEFAULT_GOALS):
            fr = tk.Frame(goals_fr, bg=BG_WHITE); fr.pack(fill="x", pady=2)
            var = tk.BooleanVar(value=default)
            goal_vars.append((var, text))
            tk.Label(fr, text=str(i+1), bg=BG_WHITE, font=FONT_S, width=3, anchor="center").pack(side="right")
            tk.Checkbutton(fr, variable=var, bg=BG_WHITE, activebackground=BG_WHITE,
                           selectcolor="#ede9fe").pack(side="right")
            tk.Label(fr, text=text, bg=BG_WHITE, font=FONT_N, anchor="e").pack(side="right", padx=4)

        cg_fr = tk.Frame(goals_fr, bg=BG_WHITE); cg_fr.pack(fill="x", pady=2)
        tk.Label(cg_fr, text="هدف إضافي:", bg=BG_WHITE, font=FONT_S).pack(side="right")
        custom_goal_var = tk.StringVar()
        ttk.Entry(cg_fr, textvariable=custom_goal_var, width=50, font=FONT_S).pack(side="right", padx=4)

        # المداولات
        disc_fr = tk.LabelFrame(main, text=" المداولات :- ", font=FONT_H,
                                bg=BG_WHITE, **BORDER, padx=10, pady=8)
        disc_fr.pack(fill="x", padx=12, pady=4)
        disc_fr.configure(fg=PURPLE)

        DEFAULT_DISCUSSIONS = [
            ("حوار ونقاش وعصف ذهني مع الطالب حول أضرار الغياب",             True),
            ("معرفة أسباب الغياب ومساعدة الطالب للتغلب عليها",               True),
            ("استخدام أسلوب الضبط الذاتي وشرحه للطالب للحد من الغياب بلا عذر", True),
        ]
        disc_vars = []
        for i, (text, default) in enumerate(DEFAULT_DISCUSSIONS):
            fr = tk.Frame(disc_fr, bg=BG_WHITE); fr.pack(fill="x", pady=2)
            var = tk.BooleanVar(value=default)
            disc_vars.append((var, text))
            tk.Label(fr, text=str(i+1), bg=BG_WHITE, font=FONT_S, width=3, anchor="center").pack(side="right")
            tk.Checkbutton(fr, variable=var, bg=BG_WHITE, activebackground=BG_WHITE,
                           selectcolor="#ede9fe").pack(side="right")
            lbl = tk.Label(fr, text=text, bg=BG_WHITE, font=FONT_N, anchor="e",
                           wraplength=560, justify="right")
            lbl.pack(side="right", padx=4, fill="x", expand=True)

        cd_fr = tk.Frame(disc_fr, bg=BG_WHITE); cd_fr.pack(fill="x", pady=2)
        tk.Label(cd_fr, text="مداولة إضافية:", bg=BG_WHITE, font=FONT_S).pack(side="right")
        custom_disc_var = tk.StringVar()
        ttk.Entry(cd_fr, textvariable=custom_disc_var, width=48, font=FONT_S).pack(side="right", padx=4)

        # التوصيات
        rec_fr = tk.LabelFrame(main, text=" التوصيات :- ", font=FONT_H,
                               bg=BG_WHITE, **BORDER, padx=10, pady=8)
        rec_fr.pack(fill="x", padx=12, pady=4)
        rec_fr.configure(fg=PURPLE)

        DEFAULT_RECS = [
            ("التزام الطالب بالحضور للمدرسة وعدم غيابه إلا بعذر مقبول",       True),
            ("التزام الطالب بتنظيم الوقت والضبط الذاتي",                       True),
            ("التأكيد على إدارة المدرسة بعدم التساهل في تطبيق لائحة المواظبة في جميع المراحل، وتكثيف التوعية الإعلامية لنشر ثقافة الانتباط، واحترام أوقات الدراسة، وجعل المدرسة بيئة جاذبة للطالب", True),
        ]
        rec_vars = []
        for i, (text, default) in enumerate(DEFAULT_RECS):
            fr = tk.Frame(rec_fr, bg=BG_WHITE); fr.pack(fill="x", pady=3)
            var = tk.BooleanVar(value=default)
            rec_vars.append((var, text))
            tk.Label(fr, text=str(i+1), bg=BG_WHITE, font=FONT_S, width=3, anchor="center").pack(side="right")
            tk.Checkbutton(fr, variable=var, bg=BG_WHITE, activebackground=BG_WHITE,
                           selectcolor="#ede9fe").pack(side="right")
            lbl = tk.Label(fr, text=text, bg=BG_WHITE, font=FONT_S,
                           anchor="e", wraplength=560, justify="right")
            lbl.pack(side="right", padx=4, fill="x", expand=True)

        cr_fr = tk.Frame(rec_fr, bg=BG_WHITE); cr_fr.pack(fill="x", pady=2)
        tk.Label(cr_fr, text="توصية إضافية:", bg=BG_WHITE, font=FONT_S).pack(side="right")
        custom_rec_var = tk.StringVar()
        ttk.Entry(cr_fr, textvariable=custom_rec_var, width=48, font=FONT_S).pack(side="right", padx=4)

        # ملاحظات
        notes_lf = tk.LabelFrame(main, text=" ملاحظات إضافية ", font=FONT_H,
                                 bg=BG_WHITE, **BORDER, padx=10, pady=6)
        notes_lf.pack(fill="x", padx=12, pady=4)
        notes_lf.configure(fg=PURPLE)
        notes_txt = tk.Text(notes_lf, height=3, font=FONT_S, relief="sunken", bd=1)
        notes_txt.pack(fill="x")

        # التواقيع
        sig_fr = tk.Frame(main, bg=BG_WHITE, relief="solid", bd=1, padx=10, pady=10)
        sig_fr.pack(fill="x", padx=12, pady=4)
        tk.Label(sig_fr, text=f"المرشد الطلابي: {counselor_name}", bg=BG_WHITE,
                 font=("Tahoma",10,"bold"), fg="#7c3aed").pack(side="right", padx=40)
        tk.Label(sig_fr, text="قائد المدرسة", bg=BG_WHITE,
                 font=("Tahoma",10,"bold"), fg="#374151").pack(side="left", padx=40)

        # ── دوال المساعدة الداخلية ───────────────────────────────────────
        def _collect():
            goals = [t for v,t in goal_vars if v.get()]
            cg = custom_goal_var.get().strip()
            if cg: goals.append(cg)
            discs = [t for v,t in disc_vars if v.get()]
            cd = custom_disc_var.get().strip()
            if cd: discs.append(cd)
            recs = [t for v,t in rec_vars if v.get()]
            cr = custom_rec_var.get().strip()
            if cr: recs.append(cr)
            return goals, discs, recs

        def _build_msg(goals, discs, recs, role=""):
            lines = []
            if role: lines.append(f"📋 جلسة إرشادية — {role}")
            lines.append("="*40)
            lines.append(f"جلسة إرشاد فردي — {session_title_var.get()}")
            lines.append(f"الطالب: {sname}  |  الفصل: {sclass}  |  التاريخ: {date_var.get()}")
            lines.append(f"المدرسة: {school}")
            lines.append("")
            lines.append("📌 الأهداف:")
            for i,g in enumerate(goals,1): lines.append(f"  {i}. {g}")
            lines.append("")
            lines.append("🗣 المداولات:")
            for i,d in enumerate(discs,1): lines.append(f"  {i}. {d}")
            lines.append("")
            lines.append("✅ التوصيات:")
            for i,r in enumerate(recs,1): lines.append(f"  {i}. {r}")
            extra = notes_txt.get("1.0","end-1c").strip()
            if extra: lines.append("\n📝 ملاحظات: " + extra)
            lines.append("\nالمرشد الطلابي: " + counselor_name)
            return "\n".join(lines)

        def _save_to_db(goals, discs, recs):
            reason   = session_title_var.get()
            notes_db = "الأهداف: " + "; ".join(goals) + "\nالمداولات: " + "; ".join(discs) + "\nالتوصيات: " + "; ".join(recs)
            extra    = notes_txt.get("1.0","end-1c").strip()
            if extra: notes_db += "\nملاحظات: " + extra
            action   = "; ".join(recs) if recs else "تنبيه الطالب"
            data_to_save = {
                "date": date_var.get().strip() or datetime.datetime.now().strftime("%Y-%m-%d"),
                "student_id": sid,
                "student_name": sname,
                "class_name": sclass,
                "reason": reason,
                "notes": notes_db,
                "action_taken": action
            }
            insert_counselor_session(data_to_save)
            try: self._load_counselor_data()
            except: pass

        def save_session():
            goals, discs, recs = _collect()
            _save_to_db(goals, discs, recs)
            messagebox.showinfo("✅ تم", "تم حفظ الجلسة الإرشادية بنجاح", parent=win)

        def send_to(phone, role):
            if not phone:
                messagebox.showerror("خطأ", f"لم يُسجَّل رقم جوال {role} في الإعدادات", parent=win)
                return False
            goals, discs, recs = _collect()
            # ── بناء بيانات الجلسة ───────────────────────────────────
            session_data = {
                "student_name":    sname,
                "class_name":      sclass,
                "date":            date_var.get(),
                "title":           session_title_var.get(),
                "goals":           goals,
                "discussions":     discs,
                "recommendations": recs,
                "notes":           notes_txt.get("1.0","end-1c").strip(),
                "counselor_name":  counselor_name,
            }
            # ── إنشاء PDF ────────────────────────────────────────────
            try:
                pdf_bytes = generate_session_pdf(session_data)
            except Exception as _pdf_err:
                messagebox.showerror("خطأ PDF", f"تعذّر إنشاء ملف PDF:\n{_pdf_err}", parent=win)
                return False
            fname   = "جلسة_ارشادية_{}_{}.pdf".format(sname, date_var.get())
            caption = "📋 جلسة إرشادية — {} — {} | {}".format(sname, sclass, role)
            # ── إرسال PDF ────────────────────────────────────────────
            ok, res = send_whatsapp_pdf(phone, pdf_bytes, fname, caption)
            if ok:
                _save_to_db(goals, discs, recs)
                messagebox.showinfo("✅ تم", f"✅ تم إرسال الجلسة كـ PDF لـ{role} بنجاح", parent=win)
                return True
            else:
                # اسأل المستخدم: هل يرسل نصاً بدلاً عن PDF؟
                retry = messagebox.askyesno(
                    "فشل إرسال PDF",
                    f"فشل إرسال الجلسة كـ PDF لـ{role}:\n{res}\n\nهل تريد إرسالها كرسالة نصية بدلاً عن ذلك؟",
                    parent=win
                )
                if retry:
                    msg = _build_msg(goals, discs, recs, role)
                    ok2, res2 = send_whatsapp_message(phone, msg)
                    if ok2:
                        _save_to_db(goals, discs, recs)
                        messagebox.showinfo("✅ تم", f"تم الإرسال كنص لـ{role}", parent=win)
                        return True
                    else:
                        messagebox.showerror("فشل", f"فشل الإرسال النصي: {res2}", parent=win)
                return False

        def send_to_both():
            goals, discs, recs = _collect()
            session_data = {
                "student_name":    sname,
                "class_name":      sclass,
                "date":            date_var.get(),
                "title":           session_title_var.get(),
                "goals":           goals,
                "discussions":     discs,
                "recommendations": recs,
                "notes":           notes_txt.get("1.0","end-1c").strip(),
                "counselor_name":  counselor_name,
            }
            try:
                pdf_bytes = generate_session_pdf(session_data)
            except Exception as _pdf_err:
                messagebox.showerror("خطأ PDF", f"تعذّر إنشاء ملف PDF:\n{_pdf_err}", parent=win)
                return
            sent = 0; failed_pdf = []
            fname = "جلسة_ارشادية_{}_{}.pdf".format(sname, date_var.get())
            for phone, role in [(principal_phone, "مدير المدرسة"), (deputy_phone, "وكيل المدرسة")]:
                if not phone: continue
                caption = "📋 جلسة إرشادية — {} — {} | {}".format(sname, sclass, role)
                ok_pdf, _ = send_whatsapp_pdf(phone, pdf_bytes, fname, caption)
                if ok_pdf:
                    sent += 1
                else:
                    failed_pdf.append(role)
            if sent:
                _save_to_db(goals, discs, recs)
                msg_ok = f"✅ تم إرسال الجلسة كـ PDF لـ {sent} جهة"
                if failed_pdf:
                    msg_ok += f"\n⚠️ فشل PDF لـ: {', '.join(failed_pdf)}"
                messagebox.showinfo("✅ تم", msg_ok, parent=win)
            else:
                messagebox.showwarning("تحذير",
                    "لم يتم الإرسال — تحقق من أرقام الجوال وتأكد من تحديث server.js",
                    parent=win)

        # أزرار الإرسال
        btn_fr = tk.Frame(main, bg="#f0f4f8", pady=10)
        btn_fr.pack(fill="x", padx=12, pady=(4,16))

        # قراءة أرقام الموجّهَين
        _cfg_sess = load_config()
        counselor1_phone = _cfg_sess.get("counselor1_phone", "").strip()
        counselor2_phone = _cfg_sess.get("counselor2_phone", "").strip()

        def send_to_counselors():
            """إرسال نسخة PDF للموجّهَين معاً."""
            goals, discs, recs = _collect()
            session_data = {
                "student_name":    sname,
                "class_name":      sclass,
                "date":            date_var.get(),
                "title":           session_title_var.get(),
                "goals":           goals,
                "discussions":     discs,
                "recommendations": recs,
                "notes":           notes_txt.get("1.0","end-1c").strip(),
                "counselor_name":  counselor_name,
            }
            if not counselor1_phone and not counselor2_phone:
                messagebox.showwarning("تنبيه",
                    "لا توجد أرقام موجّهين مسجّلة.\nأضفها من: إعدادات المدرسة  أرقام الجوال", parent=win)
                return
            try:
                pdf_bytes = generate_session_pdf(session_data)
            except Exception as _pdf_err:
                messagebox.showerror("خطأ PDF", f"تعذّر إنشاء ملف PDF:\n{_pdf_err}", parent=win)
                return
            sent = 0
            fname = "جلسة_ارشادية_{}_{}.pdf".format(sname, date_var.get())
            for _ph in [counselor1_phone, counselor2_phone]:
                if not _ph: continue
                caption = "📋 جلسة إرشادية — {} — {}".format(sname, sclass)
                ok_pdf, _ = send_whatsapp_pdf(_ph, pdf_bytes, fname, caption)
                if ok_pdf:
                    sent += 1
            if sent:
                _save_to_db(goals, discs, recs)
                messagebox.showinfo("✅ تم", f"✅ تم إرسال الجلسة كـ PDF للموجّه{'ين' if sent==2 else ''}", parent=win)
            else:
                messagebox.showwarning("فشل PDF",
                    "فشل إرسال PDF للموجهين.\nتاكد من تحديث server.js ثم اعادة تشغيل خادم الواتساب.", parent=win)

        btns = [
            ("💾 حفظ الجلسة",              "#6d28d9", save_session),
            ("📲 إرسال لمدير المدرسة",     "#1d4ed8", lambda: send_to(principal_phone, "مدير المدرسة")),
            ("📲 إرسال لوكيل المدرسة",     "#0369a1", lambda: send_to(deputy_phone,    "وكيل المدرسة")),
            ("📨 إرسال للمدير والوكيل",    "#065f46", send_to_both),
            ("🧭 إرسال للموجّهَين",        "#7c3aed", send_to_counselors),
            ("❌ إغلاق",                    "#6b7280", win.destroy),
        ]
        for txt, color, cmd in btns:
            tk.Button(btn_fr, text=txt, command=cmd,
                      bg=color, fg="white", font=("Tahoma",10,"bold"),
                      relief="flat", padx=12, pady=6, cursor="hand2").pack(side="right", padx=5)

    def _send_counselor_alert(self, alert_type):
        sel = self.tree_counselor.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "الرجاء اختيار طالب أولاً")
            return
        
        sid, sname, sclass, sabs, stard, _ = self.tree_counselor.item(sel[0], "values")
        
        # جلب رقم الجوال
        store = load_students()
        phone = ""
        for cls in store["list"]:
            for s in cls["students"]:
                if s["id"] == sid:
                    phone = s.get("phone", "")
                    break
        
        if not phone:
            messagebox.showerror("خطأ", "رقم جوال ولي الأمر غير مسجل لهذا الطالب")
            return
        
        # اسم الموجّه النشط حالياً للتوقيع
        active_name = self._get_active_counselor_name()

        _t = get_terms()
        _mkrm = "المكرمة" if _t["gender"] == "girls" else "المكرم"
        if alert_type == "تنبيه":
            msg = f"{_mkrm} {_t['guardian']}: {sname}\nنفيدكم بأن {_t['son']} قد تكرر غيابه/تأخره ({sabs} أيام غياب / {stard} مرات تأخر). نأمل منكم حثه على الانضباط.\n{active_name}"
        else:
            msg = f"{_mkrm} {_t['guardian']}: {sname}\nنظراً لتكرار غياب/تأخر {_t['son']} بشكل ملحوظ، نرجو منكم مراجعة مكتب التوجيه الطلابي بالمدرسة في أقرب وقت ممكن.\n{active_name}"
        
        if not messagebox.askyesno("تأكيد", f"هل تريد إرسال {alert_type} لولي الأمر عبر الواتساب؟"):
            return
        
        ok, res = send_whatsapp_message(phone, msg)
        try:
            data_alert = {
                "date": now_riyadh_date(),
                "student_id": sid,
                "student_name": sname,
                "type": alert_type,
                "method": "whatsapp",
                "status": "تم الإرسال" if ok else f"فشل: {res}"
            }
            insert_counselor_alert(data_alert)
        except:
            pass

        if ok:
            messagebox.showinfo("تم", f"تم إرسال {alert_type} بنجاح")
            self._load_counselor_data()
        else:
            messagebox.showerror("فشل", f"فشل الإرسال: {res}")

    def _show_student_counseling_history(self):
        sel = self.tree_counselor.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "الرجاء اختيار طالب أولاً")
            return
        sid, sname, _, _, _, _ = self.tree_counselor.item(sel[0], "values")
        self._open_sessions_archive(filter_sid=sid, filter_name=sname)

    def _open_sessions_archive(self, filter_sid=None, filter_name=None):
        """
        أرشيف الجلسات الإرشادية — يعرض كل الجلسات المحفوظة
        مع إمكانية البحث والتصفية وإعادة الطباعة أو الإرسال.
        """
        win = tk.Toplevel(self.root)
        title_txt = f"📚 أرشيف الجلسات — {filter_name}" if filter_name else "📚 أرشيف الجلسات الإرشادية"
        win.title(title_txt)
        win.geometry("1050x680")
        win.configure(bg="#f0f4f8")
        try: win.state("zoomed")
        except: pass

        cfg    = load_config()

        # ── رأس النافذة ──────────────────────────────────────────
        hdr = tk.Frame(win, bg="#5b21b6", height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📚 أرشيف الجلسات الإرشادية",
                 bg="#5b21b6", fg="white",
                 font=("Tahoma", 13, "bold")).pack(side="right", padx=20, pady=14)
        if filter_name:
            tk.Label(hdr, text=f"طالب: {filter_name}",
                     bg="#5b21b6", fg="#ddd6fe",
                     font=("Tahoma", 10)).pack(side="right", padx=10, pady=14)

        # ── شريط البحث والفلترة ──────────────────────────────────
        ctrl = tk.Frame(win, bg="#ede9fe", pady=8)
        ctrl.pack(fill="x")

        tk.Label(ctrl, text="🔍 بحث:", bg="#ede9fe",
                 font=("Tahoma", 10, "bold"), fg="#5b21b6").pack(side="right", padx=(10, 4))
        _search_var = tk.StringVar()
        search_ent = ttk.Entry(ctrl, textvariable=_search_var, width=22, font=("Tahoma", 10))
        search_ent.pack(side="right", padx=4)

        tk.Label(ctrl, text="من:", bg="#ede9fe",
                 font=("Tahoma", 10), fg="#5b21b6").pack(side="right", padx=(10, 4))
        _date_from = tk.StringVar()
        ttk.Entry(ctrl, textvariable=_date_from, width=12, font=("Tahoma", 10)).pack(side="right", padx=2)

        tk.Label(ctrl, text="إلى:", bg="#ede9fe",
                 font=("Tahoma", 10), fg="#5b21b6").pack(side="right", padx=(6, 4))
        _date_to = tk.StringVar()
        ttk.Entry(ctrl, textvariable=_date_to, width=12, font=("Tahoma", 10)).pack(side="right", padx=2)

        tk.Button(ctrl, text="🔍 تصفية", bg="#7c3aed", fg="white",
                  font=("Tahoma", 9, "bold"), relief="flat", cursor="hand2",
                  padx=8, command=lambda: _load_sessions()).pack(side="right", padx=8)
        tk.Button(ctrl, text="↺ إعادة تعيين", bg="#e5e7eb", fg="#374151",
                  font=("Tahoma", 9), relief="flat", cursor="hand2",
                  padx=8, command=lambda: [_search_var.set(""),
                                           _date_from.set(""), _date_to.set(""),
                                           _load_sessions()]).pack(side="right", padx=4)

        _count_lbl = tk.Label(ctrl, text="", bg="#ede9fe",
                               font=("Tahoma", 9), fg="#5b21b6")
        _count_lbl.pack(side="left", padx=14)

        # ── الجدول الرئيسي ────────────────────────────────────────
        tbl_fr = tk.Frame(win, bg="white")
        tbl_fr.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        cols = ("id", "date", "student_name", "class_name", "reason", "action_taken")
        tree = ttk.Treeview(tbl_fr, columns=cols, show="headings", height=18,
                            selectmode="browse")

        hdrs = {
            "id":           ("رقم", 50),
            "date":         ("التاريخ", 100),
            "student_name": ("اسم الطالب", 170),
            "class_name":   ("الفصل", 110),
            "reason":       ("موضوع الجلسة", 220),
            "action_taken": ("التوصيات", 250),
        }
        for col, (lbl, w) in hdrs.items():
            tree.heading(col, text=lbl, anchor="center")
            tree.column(col, width=w, anchor="center",
                        stretch=(col in ("reason", "action_taken")))
        tree.column("id", width=0, stretch=False)

        vsb = ttk.Scrollbar(tbl_fr, orient="vertical",   command=tree.yview)
        hsb = ttk.Scrollbar(tbl_fr, orient="horizontal",  command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="left",   fill="y")
        hsb.pack(side="bottom", fill="x")
        tree.pack(side="right", fill="both", expand=True)

        tree.tag_configure("odd",  background="#faf5ff")
        tree.tag_configure("even", background="white")

        # ── تحميل الجلسات ────────────────────────────────────────
        _all_sessions = []

        def _load_sessions():
            nonlocal _all_sessions
            tree.delete(*tree.get_children())
            rows = get_counselor_sessions(student_id=filter_sid)
            
            q = _search_var.get().strip().lower()
            if q:
                rows = [r for r in rows if q in r.get("student_name","").lower() or q in r.get("reason","").lower()]
            
            _all_sessions.clear()
            _all_sessions.extend(rows)
            _count_lbl.config(text=f"عدد الجلسات: {len(rows)}")

            for i, r in enumerate(rows):
                tag = "odd" if i % 2 == 0 else "even"
                tree.insert("", "end", iid=str(r["id"]),
                            values=(r["id"], r.get("date",""), r.get("student_name",""),
                                    r.get("class_name",""), r.get("reason","")),
                            tags=(tag,))

        _load_sessions()
        search_ent.bind("<KeyRelease>", lambda e: _load_sessions())

        # ── لوحة التفاصيل ────────────────────────────────────────
        detail_fr = tk.LabelFrame(win, text=" 📋 تفاصيل الجلسة المحددة ",
                                  font=("Tahoma", 10, "bold"),
                                  fg="#5b21b6", bg="#f0f4f8", padx=10, pady=6)
        detail_fr.pack(fill="x", padx=16, pady=(6, 0))

        _detail_txt = tk.Text(detail_fr, height=5, font=("Tahoma", 10),
                               state="disabled", bg="#faf5ff",
                               relief="flat", wrap="word")
        _detail_txt.pack(fill="x")

        def _on_select(event=None):
            sel = tree.selection()
            if not sel: return
            session = next((r for r in _all_sessions if str(r["id"]) == str(sel[0])), None)
            if not session: return
            notes = session.get("notes", "") or ""
            detail = (
                f"📅 التاريخ: {session.get('date','')}\n"
                f"👤 الطالب: {session.get('student_name','')}  |  الفصل: {session.get('class_name','')}\n"
                f"📌 الموضوع: {session.get('reason','')}\n"
                f"✅ التوصيات: {session.get('action_taken','')}\n"
            )
            if notes:
                detail += f"📝 الملاحظات:\n{notes}"
            _detail_txt.config(state="normal")
            _detail_txt.delete("1.0", "end")
            _detail_txt.insert("1.0", detail)
            _detail_txt.config(state="disabled")

        tree.bind("<<TreeviewSelect>>", _on_select)

        # ── دوال مساعدة ──────────────────────────────────────────
        def _get_sel():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("تنبيه", "الرجاء اختيار جلسة أولاً", parent=win)
                return None
            return next((r for r in _all_sessions if str(r["id"]) == str(sel[0])), None)

        def _rebuild(session):
            notes_raw = session.get("notes", "") or ""
            goals, discs, recs, extra = [], [], [], ""
            for line in notes_raw.split("\n"):
                line = line.strip()
                if line.startswith("الأهداف:"):
                    goals = [x.strip() for x in line[len("الأهداف:"):].split(";") if x.strip()]
                elif line.startswith("المداولات:"):
                    discs = [x.strip() for x in line[len("المداولات:"):].split(";") if x.strip()]
                elif line.startswith("التوصيات:"):
                    recs  = [x.strip() for x in line[len("التوصيات:"):].split(";") if x.strip()]
                elif line.startswith("ملاحظات:"):
                    extra = line[len("ملاحظات:"):].strip()
            if not recs:
                action = session.get("action_taken","") or ""
                if action:
                    recs = [x.strip() for x in action.split(";") if x.strip()]
            counselor_col = ""
            for line in notes_raw.split("\n"):
                if "الموجّه" in line or "المرشد" in line:
                    counselor_col = line.strip(); break
            return {
                "student_name":    session.get("student_name",""),
                "class_name":      session.get("class_name",""),
                "date":            session.get("date",""),
                "title":           session.get("reason","الانضباط المدرسي"),
                "goals":           goals or [session.get("reason","")],
                "discussions":     discs,
                "recommendations": recs,
                "notes":           extra,
                "counselor_name":  counselor_col or self._get_active_counselor_name(),
            }

        def _do_send(session, phone, role):
            sd = _rebuild(session)
            try:
                pdf_bytes = generate_session_pdf(sd)
            except Exception as e:
                messagebox.showerror("خطأ PDF", str(e), parent=win); return
            fname   = "جلسة_{}_{}.pdf".format(session.get("student_name",""), session.get("date",""))
            caption = "📋 جلسة إرشادية (أرشيف) — {} — {} | {}".format(
                session.get("student_name",""), session.get("class_name",""), role)
            ok, res = send_whatsapp_pdf(phone, pdf_bytes, fname, caption)
            if ok:
                messagebox.showinfo("✅ تم", f"تم إرسال الجلسة كـ PDF لـ{role}", parent=win)
            else:
                messagebox.showerror("فشل", f"فشل إرسال الجلسة لـ{role}:\n{res}", parent=win)

        # ── أزرار الإجراءات ───────────────────────────────────────
        act_fr = tk.Frame(win, bg="#f0f4f8", pady=10)
        act_fr.pack(fill="x", padx=16, pady=(4, 10))

        def _print_pdf():
            session = _get_sel()
            if not session: return
            sd = _rebuild(session)
            try:
                pdf_bytes = generate_session_pdf(sd)
            except Exception as e:
                messagebox.showerror("خطأ PDF", str(e), parent=win); return
            import tempfile
            fname = "جلسة_{}_{}.pdf".format(
                session.get("student_name","").replace(" ","_"), session.get("date",""))
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="darb_")
            tmp.write(pdf_bytes); tmp.close()
            try:
                if os.name == "nt": os.startfile(tmp.name)
                else:
                    import subprocess; subprocess.Popen(["xdg-open", tmp.name])
            except Exception: pass
            messagebox.showinfo("✅ تم", f"تم فتح ملف PDF\n{tmp.name}", parent=win)

        def _save_pdf():
            session = _get_sel()
            if not session: return
            sd = _rebuild(session)
            try:
                pdf_bytes = generate_session_pdf(sd)
            except Exception as e:
                messagebox.showerror("خطأ PDF", str(e), parent=win); return
            default = "جلسة_{}_{}.pdf".format(
                session.get("student_name","").replace(" ","_"), session.get("date",""))
            path = filedialog.asksaveasfilename(
                parent=win, defaultextension=".pdf", initialfile=default,
                filetypes=[("PDF", "*.pdf"), ("All files", "*.*")])
            if not path: return
            with open(path, "wb") as f: f.write(pdf_bytes)
            messagebox.showinfo("✅ تم", f"تم حفظ الجلسة:\n{path}", parent=win)

        def _send_principal():
            session = _get_sel()
            if not session: return
            ph = cfg.get("principal_phone","").strip()
            if not ph: messagebox.showerror("خطأ","لم يُسجَّل رقم مدير المدرسة",parent=win); return
            _do_send(session, ph, "مدير المدرسة")

        def _send_deputy():
            session = _get_sel()
            if not session: return
            ph = cfg.get("alert_admin_phone","").strip()
            if not ph: messagebox.showerror("خطأ","لم يُسجَّل رقم وكيل المدرسة",parent=win); return
            _do_send(session, ph, "وكيل المدرسة")

        def _send_counselors():
            session = _get_sel()
            if not session: return
            c1 = cfg.get("counselor1_phone","").strip()
            c2 = cfg.get("counselor2_phone","").strip()
            if not c1 and not c2:
                messagebox.showwarning("تنبيه","لا توجد أرقام موجّهين مسجّلة",parent=win); return
            sd = _rebuild(session)
            try: pdf_bytes = generate_session_pdf(sd)
            except Exception as e: messagebox.showerror("خطأ PDF",str(e),parent=win); return
            fname = "جلسة_{}_{}.pdf".format(session.get("student_name",""),session.get("date",""))
            sent = 0
            for ph in [c1, c2]:
                if ph:
                    caption = "📋 جلسة إرشادية (أرشيف) — {}".format(session.get("student_name",""))
                    ok, _ = send_whatsapp_pdf(ph, pdf_bytes, fname, caption)
                    if ok: sent += 1
            if sent: messagebox.showinfo("✅ تم", f"تم الإرسال لـ {sent} موجّه", parent=win)
            else: messagebox.showerror("فشل","فشل الإرسال — تحقق من الأرقام وحالة الواتساب",parent=win)

        tk.Button(act_fr, text="🖨️ فتح / طباعة PDF",
                  bg="#1565C0", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=12, pady=6,
                  command=_print_pdf).pack(side="right", padx=6)
        tk.Button(act_fr, text="💾 حفظ PDF",
                  bg="#065f46", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=12, pady=6,
                  command=_save_pdf).pack(side="right", padx=6)
        tk.Button(act_fr, text="📤 إرسال للمدير",
                  bg="#0369a1", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=10, pady=6,
                  command=_send_principal).pack(side="right", padx=6)
        tk.Button(act_fr, text="📤 إرسال للوكيل",
                  bg="#0369a1", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=10, pady=6,
                  command=_send_deputy).pack(side="right", padx=6)
        tk.Button(act_fr, text="📤 إرسال للموجّهَين",
                  bg="#7c3aed", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=10, pady=6,
                  command=_send_counselors).pack(side="right", padx=6)
        tk.Button(act_fr, text="🔄 تحديث",
                  bg="#e5e7eb", fg="#374151", font=("Tahoma", 9),
                  relief="flat", cursor="hand2", padx=8, pady=6,
                  command=_load_sessions).pack(side="left", padx=6)

        def _delete_session():
            session = _get_sel()
            if not session: return
            confirm = messagebox.askyesno(
                "تأكيد الحذف",
                f"هل أنت متأكد من حذف جلسة الطالب:\n{session.get('student_name','')} — {session.get('date','')}؟\n\nلا يمكن التراجع عن هذا الإجراء.",
                parent=win)
            if not confirm: return
            try:
                con = get_db(); cur = con.cursor()
                cur.execute("DELETE FROM counselor_sessions WHERE id=?", (session["id"],))
                con.commit(); con.close()
                _load_sessions()
                _detail_txt.config(state="normal")
                _detail_txt.delete("1.0", "end")
                _detail_txt.config(state="disabled")
                messagebox.showinfo("✅ تم", "تم حذف الجلسة الإرشادية بنجاح", parent=win)
            except Exception as e:
                messagebox.showerror("خطأ", f"فشل الحذف:\n{e}", parent=win)

        tk.Button(act_fr, text="🗑️ حذف الجلسة",
                  bg="#dc2626", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=10, pady=6,
                  command=_delete_session).pack(side="left", padx=6)

    # ══════════════════════════════════════════════════════════
    # العقد السلوكي — نافذة الإدخال
    # ══════════════════════════════════════════════════════════
    def _open_behavioral_contract_dialog(self, sid=None, sname=None, sclass=None):
        """نافذة إنشاء عقد سلوكي وفق نموذج وزارة التعليم."""
        if sid is None:
            sel = self.tree_counselor.selection()
            if not sel:
                messagebox.showwarning("تنبيه", "الرجاء اختيار طالب أولاً")
                return
            vals = self.tree_counselor.item(sel[0], "values")
            sid, sname, sclass = vals[0], vals[1], vals[2]

        cfg    = load_config()
        school = cfg.get("school_name", "المدرسة")

        win = tk.Toplevel(self.root)
        win.title(f"عقد سلوكي — {sname}")
        win.geometry("700x560")
        win.configure(bg="#fffbeb")
        try: win.state("zoomed")
        except: pass
        win.grab_set()

        AMBER   = "#d97706"
        AMBER_D = "#92400e"
        BG_WIN  = "#fffbeb"
        BG_SEC  = "#fef3c7"
        WHITE   = "#ffffff"
        FONT_H  = ("Tahoma", 11, "bold")
        FONT_N  = ("Tahoma", 10)
        FONT_S  = ("Tahoma",  9)

        # ── رأس النافذة ──────────────────────────────────────────
        hdr_fr = tk.Frame(win, bg=AMBER, height=52)
        hdr_fr.pack(fill="x"); hdr_fr.pack_propagate(False)
        tk.Label(hdr_fr, text="📋 عقد سلوكي", bg=AMBER, fg="white",
                 font=("Tahoma", 14, "bold")).pack(side="right", padx=20, pady=12)
        tk.Label(hdr_fr, text=school, bg=AMBER, fg="#fef3c7",
                 font=FONT_S).pack(side="left", padx=16, pady=12)

        # ── منطقة التمرير الرئيسية ───────────────────────────────
        canvas = tk.Canvas(win, bg=BG_WIN, highlightthickness=0)
        vsb = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        main = tk.Frame(canvas, bg=BG_WIN, padx=20, pady=14)
        canvas_win = canvas.create_window((0, 0), window=main, anchor="nw")

        def _on_frame_conf(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        main.bind("<Configure>", _on_frame_conf)
        _co_last_w = [0]
        def _on_canvas_conf_detail(e):
            w = canvas.winfo_width()
            if w == _co_last_w[0]: return
            _co_last_w[0] = w
            canvas.itemconfig(canvas_win, width=w)
        canvas.bind("<Configure>", _on_canvas_conf_detail)

        # ── بيانات الطالب ────────────────────────────────────────
        info_fr = tk.LabelFrame(main, text=" بيانات الطالب ", font=FONT_H,
                                fg=AMBER_D, bg=BG_WIN, pady=8, padx=10)
        info_fr.pack(fill="x", pady=(0, 10))

        row1 = tk.Frame(info_fr, bg=BG_WIN); row1.pack(fill="x", pady=3)
        tk.Label(row1, text="اسم الطالب:", bg=BG_WIN, font=FONT_N,
                 width=12, anchor="e").pack(side="right")
        tk.Label(row1, text=sname, bg=BG_SEC, font=("Tahoma", 10, "bold"),
                 fg=AMBER_D, relief="groove", padx=10).pack(side="right", padx=6)

        row2 = tk.Frame(info_fr, bg=BG_WIN); row2.pack(fill="x", pady=3)
        tk.Label(row2, text="الفصل الدراسي:", bg=BG_WIN, font=FONT_N,
                 width=12, anchor="e").pack(side="right")
        tk.Label(row2, text=sclass, bg=BG_SEC, font=("Tahoma", 10, "bold"),
                 fg=AMBER_D, relief="groove", padx=10).pack(side="right", padx=6)

        row3 = tk.Frame(info_fr, bg=BG_WIN); row3.pack(fill="x", pady=3)
        tk.Label(row3, text="موضوع العقد:", bg=BG_WIN, font=FONT_N,
                 width=12, anchor="e").pack(side="right")
        subject_var = tk.StringVar(value="الانضباط السلوكي")
        ttk.Entry(row3, textvariable=subject_var, width=30,
                  font=FONT_N).pack(side="right", padx=6)

        # ── الفترة الزمنية ───────────────────────────────────────
        period_fr = tk.LabelFrame(main, text=" الفترة الزمنية للعقد (بالتاريخ الهجري) ",
                                   font=FONT_H, fg=AMBER_D, bg=BG_WIN, pady=8, padx=10)
        period_fr.pack(fill="x", pady=(0, 10))

        today_h = now_riyadh_date()  # ميلادي — يمكن الكتابة يدوياً
        p_row = tk.Frame(period_fr, bg=BG_WIN); p_row.pack(fill="x")
        tk.Label(p_row, text="من:", bg=BG_WIN, font=FONT_N).pack(side="right", padx=(0,4))
        period_from_var = tk.StringVar(value="")
        ttk.Entry(p_row, textvariable=period_from_var, width=16,
                  font=FONT_N).pack(side="right", padx=6)
        tk.Label(p_row, text="إلى:", bg=BG_WIN, font=FONT_N).pack(side="right", padx=(10,4))
        period_to_var = tk.StringVar(value="")
        ttk.Entry(p_row, textvariable=period_to_var, width=16,
                  font=FONT_N).pack(side="right", padx=6)
        tk.Label(p_row, text="(مثال: 01/09/1446)", bg=BG_WIN,
                 font=("Tahoma", 8), fg="#9ca3af").pack(side="right", padx=4)

        # ── التاريخ الميلادي للحفظ ──────────────────────────────
        date_row = tk.Frame(main, bg=BG_WIN); date_row.pack(fill="x", pady=(0,6))
        tk.Label(date_row, text="تاريخ العقد (ميلادي):", bg=BG_WIN, font=FONT_N,
                 width=18, anchor="e").pack(side="right")
        date_var = tk.StringVar(value=today_h)
        ttk.Entry(date_row, textvariable=date_var, width=14,
                  font=FONT_N).pack(side="right", padx=6)

        # ── ملاحظات إضافية ──────────────────────────────────────
        notes_fr = tk.LabelFrame(main, text=" ملاحظات إضافية (اختياري) ",
                                  font=FONT_H, fg=AMBER_D, bg=BG_WIN, pady=6, padx=10)
        notes_fr.pack(fill="x", pady=(0, 10))
        notes_txt = tk.Text(notes_fr, height=4, font=FONT_N, relief="groove", wrap="word")
        notes_txt.pack(fill="x")

        # ── معاينة البنود ────────────────────────────────────────
        preview_fr = tk.LabelFrame(main, text=" بنود العقد (تُطبع تلقائياً) ",
                                    font=FONT_H, fg=AMBER_D, bg=BG_WIN, pady=6, padx=10)
        preview_fr.pack(fill="x", pady=(0, 10))
        preview_txt = tk.Text(preview_fr, height=8, font=("Tahoma", 9),
                               state="disabled", bg=BG_SEC, relief="flat", wrap="word")
        preview_txt.pack(fill="x")
        preview_content = (
            "المسؤوليات على الطالب:\n"
            "  1 - الحضور للمدرسة بانتظام.\n"
            "  2 - القيام بالواجبات المنزلية المُكلَّف بها.\n"
            "  3 - عدم الاعتداء على أي طالب بالمدرسة.\n"
            "  4 - عدم القيام بأي مخالفات داخل المدرسة.\n\n"
            "المزايا والتدعيمات:\n"
            "  1 - سوف يضاف له درجات في السلوك.\n"
            "  2 - سوف يذكر اسمه في الإذاعة المدرسية كطالب متميز.\n"
            "  3 - سوف يسلم شهادة تميز سلوكي.\n"
            "  4 - يُكرَّم في نهاية العام الدراسي.\n"
            "  5 - يتم مساعدته في المواد الدراسية من قبل المعلمين.\n\n"
            "مكافآت إضافية: عند الاستمرار في هذا التميز السلوكي حتى نهاية العام.\n"
            "عقوبات: في حالة عدم الالتزام تُلغى المزايا ويُتخذ الإجراء المناسب."
        )
        preview_txt.config(state="normal")
        preview_txt.insert("1.0", preview_content)
        preview_txt.config(state="disabled")

        # ── أزرار الإجراءات ──────────────────────────────────────
        btn_bot = tk.Frame(win, bg=BG_WIN, pady=10)
        btn_bot.pack(fill="x", padx=20, side="bottom")

        def _get_contract_data():
            return {
                "date":          date_var.get().strip(),
                "student_id":    sid,
                "student_name":  sname,
                "class_name":    sclass,
                "subject":       subject_var.get().strip(),
                "period_from":   period_from_var.get().strip(),
                "period_to":     period_to_var.get().strip(),
                "notes":         notes_txt.get("1.0", "end").strip(),
                "school_name":   school,
                "counselor_name": self._get_active_counselor_name(),
            }

        def save_contract():
            d = _get_contract_data()
            if not d["date"]:
                messagebox.showwarning("تنبيه", "الرجاء إدخال تاريخ العقد", parent=win)
                return
            try:
                insert_behavioral_contract(d)
                messagebox.showinfo("✅ تم", "تم حفظ العقد السلوكي بنجاح", parent=win)
            except Exception as e:
                messagebox.showerror("خطأ", str(e), parent=win)

        def _open_pdf():
            d = _get_contract_data()
            try:
                pdf_bytes = generate_behavioral_contract_pdf(d)
            except Exception as e:
                messagebox.showerror("خطأ PDF", str(e), parent=win); return
            import tempfile
            fname = "عقد_سلوكي_{}_{}.pdf".format(sname, d["date"])
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="contract_")
            tmp.write(pdf_bytes); tmp.close()
            try:
                if os.name == "nt": os.startfile(tmp.name)
                else: import subprocess; subprocess.Popen(["xdg-open", tmp.name])
            except Exception: pass
            messagebox.showinfo("✅ تم", f"تم فتح ملف PDF\n{tmp.name}", parent=win)

        def _save_pdf():
            d = _get_contract_data()
            try:
                pdf_bytes = generate_behavioral_contract_pdf(d)
            except Exception as e:
                messagebox.showerror("خطأ PDF", str(e), parent=win); return
            default = "عقد_سلوكي_{}_{}.pdf".format(
                sname.replace(" ", "_"), d["date"])
            path = filedialog.asksaveasfilename(
                parent=win, defaultextension=".pdf", initialfile=default,
                filetypes=[("PDF", "*.pdf"), ("All files", "*.*")])
            if not path: return
            with open(path, "wb") as f: f.write(pdf_bytes)
            messagebox.showinfo("✅ تم", f"تم حفظ العقد:\n{path}", parent=win)

        def _send_whatsapp(role_key, role_label):
            ph = load_config().get(role_key, "").strip()
            if not ph:
                messagebox.showerror("خطأ", f"لم يُسجَّل رقم {role_label}", parent=win)
                return
            d = _get_contract_data()
            try: pdf_bytes = generate_behavioral_contract_pdf(d)
            except Exception as e: messagebox.showerror("خطأ PDF", str(e), parent=win); return
            fname   = "عقد_سلوكي_{}_{}.pdf".format(sname, d["date"])
            caption = f"📋 عقد سلوكي — {sname} — {sclass} | {role_label}"
            ok, res = send_whatsapp_pdf(ph, pdf_bytes, fname, caption)
            if ok:
                messagebox.showinfo("✅ تم", f"تم إرسال العقد كـ PDF لـ{role_label}", parent=win)
            else:
                messagebox.showerror("فشل", f"فشل الإرسال لـ{role_label}:\n{res}", parent=win)

        def _send_parent():
            store = load_students()
            phone = ""
            for cls in store["list"]:
                for s in cls["students"]:
                    if s["id"] == sid:
                        phone = s.get("phone", "")
                        break
            if not phone:
                messagebox.showerror("خطأ", "رقم ولي الأمر غير مسجل", parent=win); return
            d = _get_contract_data()
            try: pdf_bytes = generate_behavioral_contract_pdf(d)
            except Exception as e: messagebox.showerror("خطأ PDF", str(e), parent=win); return
            fname   = "عقد_سلوكي_{}_{}.pdf".format(sname, d["date"])
            caption = f"📋 عقد سلوكي — {sname} — {sclass} | ولي الأمر"
            ok, res = send_whatsapp_pdf(phone, pdf_bytes, fname, caption)
            if ok:
                messagebox.showinfo("✅ تم", "تم إرسال العقد كـ PDF لولي الأمر", parent=win)
            else:
                messagebox.showerror("فشل", f"فشل الإرسال لولي الأمر:\n{res}", parent=win)

        for txt, bg, cmd in [
            ("💾 حفظ العقد",           "#d97706", save_contract),
            ("🖨️ معاينة / طباعة PDF", "#1565C0", _open_pdf),
            ("💾 تصدير PDF",           "#065f46", _save_pdf),
            ("📤 إرسال للمدير",        "#0369a1", lambda: _send_whatsapp("principal_phone",    "مدير المدرسة")),
            ("📤 إرسال للوكيل",        "#0369a1", lambda: _send_whatsapp("alert_admin_phone",  "وكيل المدرسة")),
            ("📤 إرسال لولي الأمر",    "#7c3aed", _send_parent),
        ]:
            tk.Button(btn_bot, text=txt, bg=bg, fg="white",
                      font=("Tahoma", 10, "bold"), relief="flat",
                      cursor="hand2", padx=10, pady=6,
                      command=cmd).pack(side="right", padx=5)

    # ══════════════════════════════════════════════════════════
    # العقد السلوكي — أرشيف العقود
    # ══════════════════════════════════════════════════════════
    def _open_contracts_archive(self, filter_sid=None, filter_name=None):
        """أرشيف العقود السلوكية — يعرض كل العقود المحفوظة مع إمكانية البحث والطباعة والإرسال والحذف."""
        win = tk.Toplevel(self.root)
        title_txt = f"📄 أرشيف العقود السلوكية — {filter_name}" if filter_name else "📄 أرشيف العقود السلوكية"
        win.title(title_txt)
        win.geometry("1050x680")
        win.configure(bg="#fffbeb")
        try: win.state("zoomed")
        except: pass

        cfg = load_config()

        AMBER   = "#d97706"
        AMBER_D = "#92400e"
        BG_HDR  = "#d97706"
        BG_CTRL = "#fef3c7"
        BG_WIN  = "#fffbeb"

        # ── رأس النافذة ──────────────────────────────────────────
        hdr = tk.Frame(win, bg=BG_HDR, height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📄 أرشيف العقود السلوكية",
                 bg=BG_HDR, fg="white",
                 font=("Tahoma", 13, "bold")).pack(side="right", padx=20, pady=14)
        if filter_name:
            tk.Label(hdr, text=f"طالب: {filter_name}",
                     bg=BG_HDR, fg="#fef3c7",
                     font=("Tahoma", 10)).pack(side="right", padx=10, pady=14)

        # ── شريط البحث والفلترة ──────────────────────────────────
        ctrl = tk.Frame(win, bg=BG_CTRL, pady=8)
        ctrl.pack(fill="x")

        tk.Label(ctrl, text="🔍 بحث:", bg=BG_CTRL,
                 font=("Tahoma", 10, "bold"), fg=AMBER_D).pack(side="right", padx=(10, 4))
        _search_var = tk.StringVar()
        search_ent = ttk.Entry(ctrl, textvariable=_search_var, width=22, font=("Tahoma", 10))
        search_ent.pack(side="right", padx=4)

        tk.Label(ctrl, text="من:", bg=BG_CTRL,
                 font=("Tahoma", 10), fg=AMBER_D).pack(side="right", padx=(10, 4))
        _date_from = tk.StringVar()
        ttk.Entry(ctrl, textvariable=_date_from, width=12, font=("Tahoma", 10)).pack(side="right", padx=2)

        tk.Label(ctrl, text="إلى:", bg=BG_CTRL,
                 font=("Tahoma", 10), fg=AMBER_D).pack(side="right", padx=(6, 4))
        _date_to = tk.StringVar()
        ttk.Entry(ctrl, textvariable=_date_to, width=12, font=("Tahoma", 10)).pack(side="right", padx=2)

        tk.Button(ctrl, text="🔍 تصفية", bg=AMBER, fg="white",
                  font=("Tahoma", 9, "bold"), relief="flat", cursor="hand2",
                  padx=8, command=lambda: _load_contracts()).pack(side="right", padx=8)
        tk.Button(ctrl, text="↺ إعادة تعيين", bg="#e5e7eb", fg="#374151",
                  font=("Tahoma", 9), relief="flat", cursor="hand2",
                  padx=8, command=lambda: [_search_var.set(""),
                                           _date_from.set(""), _date_to.set(""),
                                           _load_contracts()]).pack(side="right", padx=4)

        _count_lbl = tk.Label(ctrl, text="", bg=BG_CTRL,
                               font=("Tahoma", 9), fg=AMBER_D)
        _count_lbl.pack(side="left", padx=14)

        # ── الجدول الرئيسي ────────────────────────────────────────
        tbl_fr = tk.Frame(win, bg="white")
        tbl_fr.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        cols = ("id", "date", "student_name", "class_name", "subject", "period_from", "period_to")
        tree = ttk.Treeview(tbl_fr, columns=cols, show="headings", height=18,
                            selectmode="browse")

        hdrs = {
            "id":           ("رقم",         50),
            "date":         ("التاريخ",      100),
            "student_name": ("اسم الطالب",  170),
            "class_name":   ("الفصل",        110),
            "subject":      ("موضوع العقد",  200),
            "period_from":  ("من",            110),
            "period_to":    ("إلى",           110),
        }
        for col, (lbl, w) in hdrs.items():
            tree.heading(col, text=lbl, anchor="center")
            tree.column(col, width=w, anchor="center",
                        stretch=(col in ("subject",)))
        tree.column("id", width=0, stretch=False)

        vsb = ttk.Scrollbar(tbl_fr, orient="vertical",   command=tree.yview)
        hsb = ttk.Scrollbar(tbl_fr, orient="horizontal",  command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="left",   fill="y")
        hsb.pack(side="bottom", fill="x")
        tree.pack(side="right", fill="both", expand=True)

        tree.tag_configure("odd",  background="#fef9c3")
        tree.tag_configure("even", background="white")

        # ── تحميل العقود ────────────────────────────────────────
        _all_contracts = []

        def _load_contracts():
            nonlocal _all_contracts
            tree.delete(*tree.get_children())
            rows = get_behavioral_contracts(student_id=filter_sid)

            if filter_sid:
                rows = [r for r in rows if str(r.get("student_id","")) == str(filter_sid)]

            q = _search_var.get().strip().lower()
            if q:
                rows = [r for r in rows
                        if q in str(r.get("student_name","")).lower()
                        or q in str(r.get("class_name","")).lower()
                        or q in str(r.get("subject","")).lower()]

            df = _date_from.get().strip()
            dt = _date_to.get().strip()
            if df: rows = [r for r in rows if str(r.get("date","")) >= df]
            if dt: rows = [r for r in rows if str(r.get("date","")) <= dt]

            _all_contracts.clear()
            _all_contracts.extend(rows)
            _count_lbl.config(text=f"عدد العقود: {len(rows)}")

            for i, r in enumerate(rows):
                tag = "odd" if i % 2 == 0 else "even"
                tree.insert("", "end", iid=str(r["id"]),
                            values=(r["id"], r.get("date",""),
                                    r.get("student_name",""),
                                    r.get("class_name",""),
                                    r.get("subject",""),
                                    r.get("period_from",""),
                                    r.get("period_to","")),
                            tags=(tag,))

        _load_contracts()
        search_ent.bind("<KeyRelease>", lambda e: _load_contracts())

        # ── لوحة التفاصيل ────────────────────────────────────────
        detail_fr = tk.LabelFrame(win, text=" 📋 تفاصيل العقد المحدد ",
                                  font=("Tahoma", 10, "bold"),
                                  fg=AMBER_D, bg=BG_WIN, padx=10, pady=6)
        detail_fr.pack(fill="x", padx=16, pady=(6, 0))

        _detail_txt = tk.Text(detail_fr, height=4, font=("Tahoma", 10),
                               state="disabled", bg=BG_CTRL,
                               relief="flat", wrap="word")
        _detail_txt.pack(fill="x")

        def _on_select(event=None):
            sel = tree.selection()
            if not sel: return
            contract = next((r for r in _all_contracts if str(r["id"]) == str(sel[0])), None)
            if not contract: return
            notes = contract.get("notes", "") or ""
            detail = (
                f"📅 التاريخ: {contract.get('date','')}\n"
                f"👤 الطالب: {contract.get('student_name','')}  |  الفصل: {contract.get('class_name','')}\n"
                f"📌 الموضوع: {contract.get('subject','')}\n"
                f"🗓️ الفترة: من {contract.get('period_from','')} إلى {contract.get('period_to','')}\n"
            )
            if notes:
                detail += f"📝 الملاحظات: {notes}"
            _detail_txt.config(state="normal")
            _detail_txt.delete("1.0", "end")
            _detail_txt.insert("1.0", detail)
            _detail_txt.config(state="disabled")

        tree.bind("<<TreeviewSelect>>", _on_select)

        # ── دوال مساعدة ──────────────────────────────────────────
        def _get_sel():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("تنبيه", "الرجاء اختيار عقد أولاً", parent=win)
                return None
            return next((r for r in _all_contracts if str(r["id"]) == str(sel[0])), None)

        def _rebuild_contract(c):
            return {
                "date":          c.get("date",""),
                "student_id":    c.get("student_id",""),
                "student_name":  c.get("student_name",""),
                "class_name":    c.get("class_name",""),
                "subject":       c.get("subject",""),
                "period_from":   c.get("period_from",""),
                "period_to":     c.get("period_to",""),
                "notes":         c.get("notes",""),
                "school_name":   cfg.get("school_name","المدرسة"),
                "counselor_name": self._get_active_counselor_name(),
            }

        # ── أزرار الإجراءات ───────────────────────────────────────
        act_fr = tk.Frame(win, bg=BG_WIN, pady=10)
        act_fr.pack(fill="x", padx=16, pady=(4, 10))

        def _print_pdf():
            contract = _get_sel()
            if not contract: return
            cd = _rebuild_contract(contract)
            try: pdf_bytes = generate_behavioral_contract_pdf(cd)
            except Exception as e: messagebox.showerror("خطأ PDF", str(e), parent=win); return
            import tempfile
            fname = "عقد_سلوكي_{}_{}.pdf".format(
                contract.get("student_name","").replace(" ","_"), contract.get("date",""))
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="contract_")
            tmp.write(pdf_bytes); tmp.close()
            try:
                if os.name == "nt": os.startfile(tmp.name)
                else: import subprocess; subprocess.Popen(["xdg-open", tmp.name])
            except Exception: pass
            messagebox.showinfo("✅ تم", f"تم فتح ملف PDF\n{tmp.name}", parent=win)

        def _save_pdf():
            contract = _get_sel()
            if not contract: return
            cd = _rebuild_contract(contract)
            try: pdf_bytes = generate_behavioral_contract_pdf(cd)
            except Exception as e: messagebox.showerror("خطأ PDF", str(e), parent=win); return
            default = "عقد_سلوكي_{}_{}.pdf".format(
                contract.get("student_name","").replace(" ","_"), contract.get("date",""))
            path = filedialog.asksaveasfilename(
                parent=win, defaultextension=".pdf", initialfile=default,
                filetypes=[("PDF", "*.pdf"), ("All files", "*.*")])
            if not path: return
            with open(path, "wb") as f: f.write(pdf_bytes)
            messagebox.showinfo("✅ تم", f"تم حفظ العقد:\n{path}", parent=win)

        def _send_role(role_key, role_label):
            contract = _get_sel()
            if not contract: return
            ph = cfg.get(role_key,"").strip()
            if not ph:
                messagebox.showerror("خطأ", f"لم يُسجَّل رقم {role_label}", parent=win); return
            cd = _rebuild_contract(contract)
            try: pdf_bytes = generate_behavioral_contract_pdf(cd)
            except Exception as e: messagebox.showerror("خطأ PDF", str(e), parent=win); return
            fname   = "عقد_سلوكي_{}_{}.pdf".format(contract.get("student_name",""), contract.get("date",""))
            caption = f"📋 عقد سلوكي (أرشيف) — {contract.get('student_name','')} — {contract.get('class_name','')} | {role_label}"
            ok, res = send_whatsapp_pdf(ph, pdf_bytes, fname, caption)
            if ok: messagebox.showinfo("✅ تم", f"تم إرسال العقد كـ PDF لـ{role_label}", parent=win)
            else:  messagebox.showerror("فشل", f"فشل الإرسال:\n{res}", parent=win)

        def _delete_contract():
            contract = _get_sel()
            if not contract: return
            confirm = messagebox.askyesno(
                "تأكيد الحذف",
                f"هل أنت متأكد من حذف عقد الطالب:\n{contract.get('student_name','')} — {contract.get('date','')}؟\n\nلا يمكن التراجع عن هذا الإجراء.",
                parent=win)
            if not confirm: return
            try:
                delete_behavioral_contract(contract["id"])
                _load_contracts()
                _detail_txt.config(state="normal")
                _detail_txt.delete("1.0", "end")
                _detail_txt.config(state="disabled")
                messagebox.showinfo("✅ تم", "تم حذف العقد السلوكي بنجاح", parent=win)
            except Exception as e:
                messagebox.showerror("خطأ", f"فشل الحذف:\n{e}", parent=win)

        for txt, bg, cmd in [
            ("🖨️ فتح / طباعة PDF", "#1565C0", _print_pdf),
            ("💾 حفظ PDF",          "#065f46", _save_pdf),
            ("📤 إرسال للمدير",     "#0369a1", lambda: _send_role("principal_phone",   "مدير المدرسة")),
            ("📤 إرسال للوكيل",     "#0369a1", lambda: _send_role("alert_admin_phone", "وكيل المدرسة")),
            ("📤 إرسال للموجّهَين", "#7c3aed", lambda: _send_role("counselor1_phone",  "الموجّه الطلابي")),
        ]:
            tk.Button(act_fr, text=txt, bg=bg, fg="white",
                      font=("Tahoma", 10, "bold"), relief="flat",
                      cursor="hand2", padx=12, pady=6,
                      command=cmd).pack(side="right", padx=6)

        tk.Button(act_fr, text="🗑️ حذف العقد",
                  bg="#dc2626", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=10, pady=6,
                  command=_delete_contract).pack(side="left", padx=6)
        tk.Button(act_fr, text="🔄 تحديث",
                  bg="#e5e7eb", fg="#374151", font=("Tahoma", 9),
                  relief="flat", cursor="hand2", padx=8, pady=6,
                  command=_load_contracts).pack(side="left", padx=6)

    # ══════════════════════════════════════════════════════════
    # خطابات الاستفسار الأكاديمي — الدوال
    # ══════════════════════════════════════════════════════════

    def _load_academic_inquirers_teachers(self):
        """تحميل قائمة المعلمين في قائمة الاستفسار."""
        try:
            from database import get_all_users
            users = get_all_users()
            teachers = [u for u in users if u.get("role") == "teacher" and u.get("active")]
            self._coun_inq_teachers_list = teachers
            names = [u.get("full_name") or u.get("username") for u in teachers]
            self.coun_inq_teacher_cb['values'] = names
        except:
            pass

    def _load_academic_inquiries(self):
        """تحميل سجل الاستفسارات الأكاديمية في الجدول."""
        try:
            from database import get_academic_inquiries
            rows = get_academic_inquiries()
            self._coun_inq_tree.delete(*self._coun_inq_tree.get_children())
            for r in rows:
                self._coun_inq_tree.insert("", "end", iid=str(r["id"]), values=(
                    r["id"], r.get("date", ""), r.get("teacher_name", ""), r.get("class_name", ""),
                    r.get("subject", ""), r.get("student_name", ""), r.get("status", "")
                ))
            self._coun_inquiries_data = rows
        except Exception as e:
            print("Error loading inquiries", e)

    def _send_academic_inquiry(self):
        """إرسال استفسار أكاديمي جديد من الموجه للمعلم."""
        teacher_name = self.coun_inq_teacher_var.get().strip()
        class_name = self.coun_inq_class_var.get().strip()
        subject = self.coun_inq_subject_var.get().strip()
        student_name = self.coun_inq_student_var.get().strip()

        if not teacher_name or not class_name or not subject or not student_name:
            messagebox.showerror("خطأ", "يجب إكمال جميع الحقول.", parent=self.root)
            return

        teacher_username = ""
        for t in getattr(self, "_coun_inq_teachers_list", []):
            if (t.get("full_name") or t.get("username")) == teacher_name:
                teacher_username = t.get("username")
                break

        if not teacher_username:
             messagebox.showerror("خطأ", "يجب اختيار المعلم من القائمة.", parent=self.root)
             return

        try:
            from database import create_academic_inquiry
            cfg = load_config()
            active = self._active_counselor_var.get()
            c_name = cfg.get(f"counselor{active}_name") or "الموجه الطلابي"

            data = {
                "date": now_riyadh_date(),
                "teacher_username": teacher_username,
                "teacher_name": teacher_name,
                "counselor_name": c_name,
                "counselor_username": "counselor",
                "class_name": class_name,
                "subject": subject,
                "student_name": student_name,
            }
            create_academic_inquiry(data)
            messagebox.showinfo("✅ نجاح", "تم إرسال الخطاب بنجاح.", parent=self.root)
            self._load_academic_inquiries()
            self.coun_inq_class_var.set("")
            self.coun_inq_subject_var.set("")
            self.coun_inq_student_var.set("الكل")
            self.coun_inq_teacher_var.set("")
        except Exception as e:
            messagebox.showerror("خطأ", f"حدث خطأ أثناء الإرسال: {e}", parent=self.root)

    def _print_academic_inquiry(self):
        """طباعة خطاب الاستفسار الأكاديمي المحدد كـ PDF."""
        sel = self._coun_inq_tree.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "اختر استفساراً أولاً", parent=self.root)
            return
        inq_id = int(sel[0])
        try:
            from database import get_academic_inquiry
            from pdf_generator import generate_academic_inquiry_pdf
            inq = get_academic_inquiry(inq_id)
            if not inq:
                messagebox.showerror("خطأ", "لم يتم العثور على الاستفسار", parent=self.root)
                return
            pdf_bytes = generate_academic_inquiry_pdf(inq)
            import tempfile
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="inquiry_")
            tmp.write(pdf_bytes); tmp.close()
            try:
                if os.name == "nt": os.startfile(tmp.name)
                else:
                    import subprocess; subprocess.Popen(["xdg-open", tmp.name])
            except: pass
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل إنشاء PDF: {e}", parent=self.root)

    def _view_academic_inquiry_reply(self):
        """عرض رد المعلم على الاستفسار الأكاديمي."""
        sel = self._coun_inq_tree.selection()
        if not sel: return
        inq_id = int(sel[0])
        try:
            from database import get_academic_inquiry
            inq = get_academic_inquiry(inq_id)
            if not inq:
                return

            win = tk.Toplevel(self.root)
            win.title("📋 رد المعلم على الاستفسار")
            win.geometry("520x400")
            win.resizable(False, False)
            win.grab_set()

            tk.Label(win, text="📋 رد المعلم على الاستفسار",
                     bg="#7E22CE", fg="white", font=("Tahoma", 12, "bold")).pack(fill="x", ipady=8)

            info_fr = tk.Frame(win, bg="#FAF5FF", pady=8)
            info_fr.pack(fill="x", padx=12, pady=(8, 4))

            def _row(lbl, val):
                r = tk.Frame(info_fr, bg="#FAF5FF"); r.pack(fill="x", padx=8, pady=2)
                tk.Label(r, text=lbl + ":", bg="#FAF5FF", font=("Tahoma", 9, "bold"),
                         width=14, anchor="e").pack(side="right")
                tk.Label(r, text=val or "—", bg="#FAF5FF", font=("Tahoma", 10),
                         anchor="w", wraplength=350, justify="right").pack(side="right", padx=4)

            _row("المعلم", inq.get("teacher_name", ""))
            _row("المادة", inq.get("subject", ""))
            _row("الفصل", inq.get("class_name", ""))
            _row("الطالب", inq.get("student_name", ""))
            _row("نوع الاستفسار", inq.get("inquiry_type", ""))
            _row("الحالة", inq.get("status", ""))

            if inq.get("status") != "جديد":
                _row("تاريخ الرد", inq.get("teacher_reply_date", ""))
                tk.Label(info_fr, text="الأسباب:", bg="#FAF5FF", font=("Tahoma", 10, "bold"),
                         fg="#7E22CE").pack(anchor="e", padx=12, pady=(8, 2))
                reasons_txt = tk.Text(info_fr, height=4, font=("Tahoma", 10),
                                       state="normal", bg="white", relief="sunken", wrap="word")
                reasons_txt.pack(fill="x", padx=12)
                reasons_txt.insert("1.0", inq.get("teacher_reply_reasons", "لا يوجد"))
                reasons_txt.config(state="disabled")

                tk.Label(info_fr, text="الشواهد:", bg="#FAF5FF", font=("Tahoma", 10, "bold"),
                         fg="#7E22CE").pack(anchor="e", padx=12, pady=(8, 2))
                evidence_txt = tk.Text(info_fr, height=3, font=("Tahoma", 10),
                                        state="normal", bg="white", relief="sunken", wrap="word")
                evidence_txt.pack(fill="x", padx=12)
                evidence_txt.insert("1.0", inq.get("teacher_reply_evidence", "لا يوجد"))
                evidence_txt.config(state="disabled")
            else:
                tk.Label(info_fr, text="⏳ لم يتم الرد بعد", bg="#FAF5FF",
                         font=("Tahoma", 11, "bold"), fg="#d97706").pack(pady=20)

            tk.Button(win, text="إغلاق", bg="#6b7280", fg="white", font=("Tahoma", 10, "bold"),
                      relief="flat", padx=20, pady=6, command=win.destroy).pack(pady=12)

        except Exception as e:
            messagebox.showerror("خطأ", f"حدث خطأ: {e}", parent=self.root)

    # ══════════════════════════════════════════════════════════
    # تبويب الاستئذان
    # ══════════════════════════════════════════════════════════
