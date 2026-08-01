# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import datetime, threading, webbrowser, os, tempfile

from gui.lib_loader import Figure, FigureCanvasTkAgg, arabic_reshaper, get_display
from database import (get_student_analytics_data, add_student_note,
                      delete_student_note)
from constants import CURRENT_USER, DATA_DIR
from config_manager import load_config

def ar(txt):
    if not txt: return ""
    if arabic_reshaper and get_display:
        return get_display(arabic_reshaper.reshape(str(txt)))
    return str(txt)

# ── ألوان الخطر ──────────────────────────────────────────────────
def _risk_level(absences, tardiness_mins, referrals):
    score = absences * 3 + (tardiness_mins // 10) + referrals * 5
    if score >= 30: return "عالي",   "#EF4444", "🔴"
    if score >= 15: return "متوسط",  "#F59E0B", "🟡"
    return            "منخفض", "#10B981", "🟢"


class StudentAnalysisTabMixin:
    """Mixin: تبويب تحليل الطالب الشامل"""

    # ─────────────────────────────────────────────────────────────
    def _build_student_analysis_tab(self):
        frame = self.student_analysis_frame
        frame.configure(bg="#F1F5F9")

        # ═══ شريط البحث العلوي ═══════════════════════════════════
        search_bar = tk.Frame(frame, bg="#0F172A", height=56)
        search_bar.pack(fill="x"); search_bar.pack_propagate(False)

        tk.Label(search_bar, text="👤 تحليل الطالب الشامل",
                 bg="#0F172A", fg="white",
                 font=("Tahoma", 13, "bold")).pack(side="right", padx=20)

        sf = tk.Frame(search_bar, bg="#1E293B", padx=8, pady=6)
        sf.pack(side="left", padx=20, pady=8)

        # قائمة الفصول
        tk.Label(sf, text="🏫 الفصل:", bg="#1E293B", fg="#CBD5E1",
                 font=("Tahoma", 9)).pack(side="right", padx=(10, 3))
        self.analysis_class_var = tk.StringVar()
        self.analysis_class_cb = ttk.Combobox(
            sf, textvariable=self.analysis_class_var,
            width=22, font=("Tahoma", 10), state="readonly")
        self.analysis_class_cb.pack(side="right", padx=3)

        # قائمة الطلاب
        tk.Label(sf, text="👤 الطالب:", bg="#1E293B", fg="#CBD5E1",
                 font=("Tahoma", 9)).pack(side="right", padx=(10, 3))
        self.analysis_search_var = tk.StringVar()
        self.analysis_student_cb = ttk.Combobox(
            sf, textvariable=self.analysis_search_var,
            width=36, font=("Tahoma", 10))
        self.analysis_student_cb.pack(side="right", padx=3)

        self.refresh_analysis_students()
        self.analysis_class_cb.bind("<<ComboboxSelected>>",
                                    self._on_analysis_class_selected)
        self.analysis_student_cb.bind("<<ComboboxSelected>>",
                                      self._on_analysis_student_selected)

        # ═══ منطقة قابلة للتمرير ════════════════════════════════
        scroll_outer = tk.Frame(frame, bg="#F1F5F9")
        scroll_outer.pack(fill="both", expand=True)

        _vsb = ttk.Scrollbar(scroll_outer, orient="vertical")
        self._ana_canvas = tk.Canvas(scroll_outer, bg="#F1F5F9",
                                     highlightthickness=0,
                                     yscrollcommand=_vsb.set)
        _vsb.configure(command=self._ana_canvas.yview)
        _vsb.pack(side="right", fill="y")
        self._ana_canvas.pack(side="left", fill="both", expand=True)

        self._ana_inner = tk.Frame(self._ana_canvas, bg="#F1F5F9")
        _inner_win = self._ana_canvas.create_window(
            (0, 0), window=self._ana_inner, anchor="nw")

        self._ana_inner.bind("<Configure>",
            lambda e: self._ana_canvas.configure(
                scrollregion=self._ana_canvas.bbox("all")))
        _ana_last_w = [0]
        def _on_ana_cv(e):
            w = self._ana_canvas.winfo_width()
            if w == _ana_last_w[0]: return
            _ana_last_w[0] = w
            self._ana_canvas.itemconfig(_inner_win, width=w)
        self._ana_canvas.bind("<Configure>", _on_ana_cv)
        self._ana_canvas.bind(
            "<MouseWheel>",
            lambda e: self._ana_canvas.yview_scroll(-1*(e.delta//120), "units"))

        # ═══ بطاقة الطالب الشخصية ════════════════════════════════
        profile_card = tk.Frame(self._ana_inner, bg="white",
                                highlightbackground="#E2E8F0",
                                highlightthickness=1)
        profile_card.pack(fill="x", padx=20, pady=(16, 6))

        self._ana_avatar = tk.Label(profile_card, text="👤", bg="white",
                                    font=("Tahoma", 36))
        self._ana_avatar.pack(side="right", padx=20, pady=12)

        info_col = tk.Frame(profile_card, bg="white")
        info_col.pack(side="right", fill="both", expand=True, pady=12)

        self._ana_name_lbl = tk.Label(info_col, text="— اختر طالباً —",
                                      bg="white", fg="#1E293B",
                                      font=("Tahoma", 14, "bold"), anchor="e")
        self._ana_name_lbl.pack(fill="x", padx=10)

        self._ana_class_lbl = tk.Label(info_col, text="",
                                       bg="white", fg="#64748B",
                                       font=("Tahoma", 10), anchor="e")
        self._ana_class_lbl.pack(fill="x", padx=10)

        self._ana_id_lbl = tk.Label(info_col, text="",
                                    bg="white", fg="#94A3B8",
                                    font=("Tahoma", 9), anchor="e")
        self._ana_id_lbl.pack(fill="x", padx=10)

        # مؤشر الخطر
        risk_col = tk.Frame(profile_card, bg="white")
        risk_col.pack(side="left", padx=20, pady=12)

        self._ana_risk_lbl = tk.Label(risk_col, text="", bg="white",
                                      font=("Tahoma", 11, "bold"))
        self._ana_risk_lbl.pack()
        self._ana_risk_bar = tk.Label(risk_col, text="", bg="white",
                                      font=("Tahoma", 8), fg="#64748B")
        self._ana_risk_bar.pack()

        # زر واتساب ولي الأمر
        self._ana_wa_btn = tk.Button(
            risk_col, text="📱 واتساب ولي الأمر",
            bg="#25D366", fg="white", relief="flat",
            font=("Tahoma", 9, "bold"), cursor="hand2",
            command=self._ana_open_wa)
        self._ana_wa_btn.pack(pady=(8, 0))
        self._ana_parent_phone = ""

        self._ana_portal_btn = tk.Button(
            risk_col, text="🔗 نسخ رابط بوابة ولي الأمر",
            bg="#1565C0", fg="white", relief="flat",
            font=("Tahoma", 9, "bold"), cursor="hand2",
            command=self._ana_copy_portal_link)
        self._ana_portal_btn.pack(pady=(5, 0))

        # ═══ كروت KPI (6 كروت) ══════════════════════════════════
        kpi_row = tk.Frame(self._ana_inner, bg="#F1F5F9")
        kpi_row.pack(fill="x", padx=20, pady=6)

        self.analysis_cards = {}
        kpi_defs = [
            ("إجمالي الغياب",     "#EF4444", "🚩"),
            ("غياب مبرر",         "#22C55E", "✅"),
            ("غياب غير مبرر",     "#F97316", "⚠️"),
            ("دقائق التأخر",      "#F59E0B", "⏱️"),
            ("نقاط التميز",       "#D97706", "⭐"),
            ("تحويلات للوكيل",    "#6366F1", "📋"),
            ("جلسات الموجه",      "#8B5CF6", "🧑‍🏫"),
            ("المعدل / الترتيب",  "#10B981", "🎓"),
        ]
        # صفان: الأول 4 كروت، الثاني 3 كروت
        for i, (title, color, icon) in enumerate(kpi_defs):
            row_i, col_i = divmod(i, 4)
            card = tk.Frame(kpi_row, bg="white",
                            highlightbackground=color,
                            highlightthickness=2, padx=10, pady=8)
            card.grid(row=row_i, column=col_i, padx=5, pady=(0,5), sticky="nsew")
            kpi_row.columnconfigure(col_i, weight=1)
            tk.Label(card, text=f"{icon}", bg="white",
                     font=("Tahoma", 16)).pack()
            tk.Label(card, text=title, bg="white", fg="#64748B",
                     font=("Tahoma", 8)).pack()
            val = tk.Label(card, text="—", bg="white", fg=color,
                           font=("Tahoma", 15, "bold"))
            val.pack()
            self.analysis_cards[title] = val

        # ═══ صف الرسوم البيانية ══════════════════════════════════
        charts_row = tk.Frame(self._ana_inner, bg="#F1F5F9")
        charts_row.pack(fill="both", expand=True, padx=20, pady=6)
        for i in range(3):
            charts_row.columnconfigure(i, weight=1)
        charts_row.rowconfigure(0, weight=1)

        # الرسم 1: الغياب الشهري
        abs_lf = tk.LabelFrame(charts_row,
                               text=ar(" اتجاه الغياب الشهري "),
                               bg="white", font=("Tahoma", 9, "bold"),
                               padx=6, pady=6)
        abs_lf.grid(row=0, column=2, sticky="nsew", padx=(0, 5))
        self.fig_abs = Figure(figsize=(4, 2.8), dpi=88)
        self.ax_abs  = self.fig_abs.add_subplot(111)
        self.canvas_abs = FigureCanvasTkAgg(self.fig_abs, abs_lf)
        self.canvas_abs.get_tk_widget().pack(fill="both", expand=True)

        # الرسم 2: نسبة الحضور
        att_lf = tk.LabelFrame(charts_row,
                               text=ar(" نسبة الحضور والالتزام "),
                               bg="white", font=("Tahoma", 9, "bold"),
                               padx=6, pady=6)
        att_lf.grid(row=0, column=1, sticky="nsew", padx=5)
        self.fig_cases = Figure(figsize=(4, 2.8), dpi=88)
        self.ax_cases  = self.fig_cases.add_subplot(111)
        self.canvas_cases = FigureCanvasTkAgg(self.fig_cases, att_lf)
        self.canvas_cases.get_tk_widget().pack(fill="both", expand=True)

        # الرسم 3: خريطة أيام الأسبوع
        dow_lf = tk.LabelFrame(charts_row,
                               text=ar(" توزيع الغياب على أيام الأسبوع "),
                               bg="white", font=("Tahoma", 9, "bold"),
                               padx=6, pady=6)
        dow_lf.grid(row=0, column=0, sticky="nsew", padx=(5, 0))
        self.fig_dow = Figure(figsize=(4, 2.8), dpi=88)
        self.ax_dow  = self.fig_dow.add_subplot(111)
        self.canvas_dow = FigureCanvasTkAgg(self.fig_dow, dow_lf)
        self.canvas_dow.get_tk_widget().pack(fill="both", expand=True)

        # ═══ الجدول الزمني ═══════════════════════════════════════
        tl_lf = tk.LabelFrame(self._ana_inner,
                              text=" 🕒 الجدول الزمني — آخر 20 إجراء ",
                              bg="white", font=("Tahoma", 9, "bold"),
                              padx=8, pady=8)
        tl_lf.pack(fill="x", padx=20, pady=6)

        tl_cols = ("date", "type", "details", "status")
        self.analysis_tree = ttk.Treeview(tl_lf, columns=tl_cols,
                                           show="headings", height=7)
        for c, h, w in zip(tl_cols,
                           ["التاريخ","النوع","التفاصيل","الحالة"],
                           [100, 120, 380, 110]):
            self.analysis_tree.heading(c, text=h)
            self.analysis_tree.column(c, width=w, anchor="center" if w<200 else "e")
        tl_sb = ttk.Scrollbar(tl_lf, orient="vertical",
                               command=self.analysis_tree.yview)
        self.analysis_tree.configure(yscrollcommand=tl_sb.set)
        tl_sb.pack(side="right", fill="y")
        self.analysis_tree.pack(side="left", fill="both", expand=True)
        
        # ═══ سجل نقاط التميز ══════════════════════════════════════
        pts_lf = tk.LabelFrame(self._ana_inner,
                               text=" ⭐ سجل نقاط التميز التفصيلي ",
                               bg="white", font=("Tahoma", 9, "bold"),
                               padx=8, pady=8)
        pts_lf.pack(fill="x", padx=20, pady=6)

        pts_cols = ("date", "points", "reason", "author")
        self.points_tree = ttk.Treeview(pts_lf, columns=pts_cols,
                                           show="headings", height=5)
        for c, h, w in zip(pts_cols,
                           ["التاريخ","النقاط","السبب","بواسطة"],
                           [100, 80, 350, 180]):
            self.points_tree.heading(c, text=h)
            self.points_tree.column(c, width=w, anchor="center" if w<200 else "e")
        pts_sb = ttk.Scrollbar(pts_lf, orient="vertical",
                                command=self.points_tree.yview)
        self.points_tree.configure(yscrollcommand=pts_sb.set)
        pts_sb.pack(side="right", fill="y")
        self.points_tree.pack(side="left", fill="both", expand=True)

        # ═══ قسم النتائج الدراسية (قابل للطي) ══════════════════════
        self._results_section = tk.Frame(self._ana_inner, bg="#F1F5F9")
        self._results_section.pack(fill="x", padx=20, pady=(0, 6))

        # شريط الرأس مع زر الطي
        _res_hdr = tk.Frame(self._results_section, bg="#065F46",
                            padx=10, pady=6)
        _res_hdr.pack(fill="x")
        self._results_toggle_lbl = tk.Label(
            _res_hdr, text="▼", bg="#065F46", fg="white",
            font=("Tahoma", 9), cursor="hand2")
        self._results_toggle_lbl.pack(side="left", padx=(0, 6))
        tk.Label(_res_hdr, text="🎓 النتائج الدراسية",
                 bg="#065F46", fg="white",
                 font=("Tahoma", 10, "bold")).pack(side="right")

        # الجسم القابل للطي
        self._results_body = tk.Frame(self._results_section,
                                       bg="white", padx=12, pady=10)
        self._results_body.pack(fill="x")

        # عرض المعدل + السنة فقط
        _res_summary = tk.Frame(self._results_body, bg="white")
        _res_summary.pack(fill="x", pady=6)
        _res_summary.columnconfigure(0, weight=2)
        _res_summary.columnconfigure(1, weight=1)

        # بطاقة المعدل (كبيرة)
        _gpa_card = tk.Frame(_res_summary, bg="#F0FDF4",
                             highlightbackground="#10B981",
                             highlightthickness=2, padx=16, pady=12)
        _gpa_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(_gpa_card, text="📊", bg="#F0FDF4",
                 font=("Tahoma", 22)).pack()
        tk.Label(_gpa_card, text="المعدل الأخير", bg="#F0FDF4",
                 fg="#6B7280", font=("Tahoma", 9)).pack()
        self._res_gpa_lbl = tk.Label(_gpa_card, text="—", bg="#F0FDF4",
                                      fg="#065F46", font=("Tahoma", 28, "bold"))
        self._res_gpa_lbl.pack()

        # بطاقة السنة الدراسية
        _yr_card = tk.Frame(_res_summary, bg="#F0FDF4",
                            highlightbackground="#10B981",
                            highlightthickness=2, padx=12, pady=12)
        _yr_card.grid(row=0, column=1, sticky="nsew")
        tk.Label(_yr_card, text="📅", bg="#F0FDF4",
                 font=("Tahoma", 18)).pack()
        tk.Label(_yr_card, text="العام الدراسي", bg="#F0FDF4",
                 fg="#6B7280", font=("Tahoma", 9)).pack()
        self._res_year_lbl = tk.Label(_yr_card, text="—", bg="#F0FDF4",
                                       fg="#065F46", font=("Tahoma", 14, "bold"))
        self._res_year_lbl.pack()
        self._res_rank_lbl = tk.Label(_yr_card, text="", bg="#F0FDF4",
                                       fg="#6B7280", font=("Tahoma", 9))
        self._res_rank_lbl.pack(pady=(4, 0))

        self._results_expanded = True
        def _toggle_results():
            if self._results_expanded:
                self._results_body.pack_forget()
                self._results_toggle_lbl.config(text="▶")
            else:
                self._results_body.pack(fill="x")
                self._results_toggle_lbl.config(text="▼")
            self._results_expanded = not self._results_expanded
        _res_hdr.bind("<Button-1>", lambda e: _toggle_results())
        self._results_toggle_lbl.bind("<Button-1>", lambda e: _toggle_results())

        # ═══ زر PDF + قسم الملاحظات ══════════════════════════════
        bottom_row = tk.Frame(self._ana_inner, bg="#F1F5F9")
        bottom_row.pack(fill="x", padx=20, pady=(6, 20))
        bottom_row.columnconfigure(0, weight=3)
        bottom_row.columnconfigure(1, weight=2)

        # ملاحظات إدارية
        notes_lf = tk.LabelFrame(bottom_row,
                                 text=" 📝 الملاحظات الإدارية ",
                                 bg="white", font=("Tahoma", 9, "bold"),
                                 padx=8, pady=8)
        notes_lf.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        notes_ctrl = tk.Frame(notes_lf, bg="white")
        notes_ctrl.pack(fill="x", pady=(0, 4))
        tk.Button(notes_ctrl, text="➕ إضافة ملاحظة",
                  bg="#1565C0", fg="white", relief="flat",
                  font=("Tahoma", 9), cursor="hand2",
                  command=self._ana_add_note).pack(side="right", padx=3)
        tk.Button(notes_ctrl, text="🗑️ حذف",
                  bg="#E53935", fg="white", relief="flat",
                  font=("Tahoma", 9), cursor="hand2",
                  command=self._ana_delete_note).pack(side="right", padx=3)

        n_cols = ("note", "author", "date")
        self._ana_notes_tree = ttk.Treeview(notes_lf, columns=n_cols,
                                             show="headings", height=5)
        for c, h, w in zip(n_cols,
                           ["الملاحظة","بقلم","التاريخ"],
                           [300, 100, 130]):
            self._ana_notes_tree.heading(c, text=h)
            self._ana_notes_tree.column(c, width=w,
                                        anchor="center" if w<200 else "e")
        notes_sb = ttk.Scrollbar(notes_lf, orient="vertical",
                                  command=self._ana_notes_tree.yview)
        self._ana_notes_tree.configure(yscrollcommand=notes_sb.set)
        notes_sb.pack(side="right", fill="y")
        self._ana_notes_tree.pack(side="left", fill="both", expand=True)

        # تصدير PDF
        pdf_lf = tk.LabelFrame(bottom_row, text=" 📄 تصدير ",
                                bg="white", font=("Tahoma", 9, "bold"),
                                padx=12, pady=12)
        pdf_lf.grid(row=0, column=1, sticky="nsew")

        tk.Label(pdf_lf,
                 text="احفظ تقريراً شاملاً\nعن هذا الطالب\nبصيغة HTML للطباعة",
                 bg="white", fg="#64748B",
                 font=("Tahoma", 9)).pack(pady=(8, 12))

        tk.Button(pdf_lf, text="🖨️ تصدير تقرير الطالب",
                  bg="#4A148C", fg="white", relief="flat",
                  font=("Tahoma", 10, "bold"), cursor="hand2",
                  padx=10, pady=8,
                  command=self._ana_export_pdf).pack(fill="x")

        # حفظ بيانات الطالب الحالي
        self._current_ana_student_id = None
        self._current_ana_data = None

    # ─────────────────────────────────────────────────────────────
    def refresh_analysis_students(self):
        if not hasattr(self, "analysis_class_cb"): return
        import constants
        store = constants.STUDENTS_STORE
        if not store or "list" not in store:
            return
        # ملء قائمة الفصول
        classes = ["الكل"] + [cls["name"] for cls in store["list"] if cls.get("name")]
        self.analysis_class_cb['values'] = classes
        if not self.analysis_class_var.get():
            self.analysis_class_var.set("الكل")
        # ملء قائمة الطلاب
        self._filter_analysis_students()

    def _filter_analysis_students(self):
        import constants
        store = constants.STUDENTS_STORE
        if not store or "list" not in store:
            return
        selected_class = self.analysis_class_var.get()
        student_list = []
        for cls in store["list"]:
            if selected_class and selected_class != "الكل" and cls.get("name") != selected_class:
                continue
            for s in cls.get("students", []):
                if s.get("id") and s.get("name"):
                    student_list.append(f"{s['name']} - {s['id']}")
        self.analysis_student_cb['values'] = sorted(set(student_list))
        self.analysis_search_var.set("")

    def _on_analysis_class_selected(self, event=None):
        self._filter_analysis_students()

    def _on_analysis_student_selected(self, event=None):
        val = self.analysis_search_var.get()
        if " - " in val:
            sid = val.split(" - ")[-1].strip()
            self.load_student_analysis(sid)

    def load_student_analysis(self, student_id: str):
        import constants
        store = constants.STUDENTS_STORE
        found_name = ""; found_class = ""; found_phone = ""
        if store and "list" in store:
            for cls in store["list"]:
                for s in cls.get("students", []):
                    if str(s.get("id")) == str(student_id):
                        found_name  = s.get("name", "")
                        found_class = cls.get("name", "")
                        found_phone = s.get("parent_phone", s.get("phone", ""))
                        break
                if found_name: break

        self._ana_parent_phone = found_phone
        self._current_ana_student_id = student_id

        if found_name:
            self.analysis_search_var.set(f"{found_name} - {student_id}")
        self._ana_name_lbl.config(text=found_name or f"طالب: {student_id}")
        self._ana_class_lbl.config(text=f"الفصل: {found_class}" if found_class else "")
        self._ana_id_lbl.config(text=f"رقم الطالب: {student_id}")
        self._ana_wa_btn.config(
            state="normal" if found_phone else "disabled",
            text=f"📱 واتساب ولي الأمر — {found_phone}" if found_phone else "📱 لا يوجد رقم")

        def _worker():
            try:
                from database import get_cloud_client
                client = get_cloud_client()
                if client and client.is_active():
                    resp = client.get(f"/web/api/student-analytics/{student_id}")
                    data = resp.get("data") if resp.get("ok") else get_student_analytics_data(student_id)
                else:
                    data = get_student_analytics_data(student_id)
                self.root.after(0, lambda d=data: self._update_analysis_ui(d))
            except Exception as e:
                print(f"[ANALYSIS-ERROR] {e}")
        threading.Thread(target=_worker, daemon=True).start()

    # ─────────────────────────────────────────────────────────────
    def _update_analysis_ui(self, data):
        self._current_ana_data = data

        abs_total  = len(data["absences"])
        excused    = data.get("excused_count", 0)
        unexcused  = data.get("unexcused_count", abs_total)
        tard_mins  = sum(r["minutes"] for r in data["tardiness"])
        ref_count  = len(data["referrals"])
        ses_count  = len(data["sessions"])
        gpa_val    = data["results"]["gpa"] if data["results"] else "—"
        rank_val   = data["results"].get("rank","") if data["results"] else ""
        gpa_str    = f"{gpa_val}" + (f" #{rank_val}" if rank_val else "")

        # KPI
        self.analysis_cards["إجمالي الغياب"].config(text=str(abs_total))
        self.analysis_cards["غياب مبرر"].config(text=str(excused))
        self.analysis_cards["غياب غير مبرر"].config(text=str(unexcused))
        self.analysis_cards["دقائق التأخر"].config(text=str(tard_mins))
        self.analysis_cards["نقاط التميز"].config(text=str(data.get("total_points", 0)))
        self.analysis_cards["تحويلات للوكيل"].config(text=str(ref_count))
        self.analysis_cards["جلسات الموجه"].config(text=str(ses_count))
        self.analysis_cards["المعدل / الترتيب"].config(text=gpa_str)

        # آخر تحويل وآخر جلسة في البطاقة الشخصية
        last_ref = data["referrals"][0] if data["referrals"] else None
        last_ses = data["sessions"][0]  if data["sessions"]  else None
        extra = ""
        if last_ref:
            extra += f"📋 آخر تحويل: {last_ref['date']} — {last_ref['violation'][:30]}  ({last_ref['status']})\n"
        if last_ses:
            extra += f"🧑‍🏫 آخر جلسة إرشادية: {last_ses['date']} — {last_ses['reason'][:35]}"
        self._ana_id_lbl.config(
            text=f"رقم الطالب: {self._current_ana_student_id}" +
                 (f"\n{extra}" if extra else ""))

        # مؤشر الخطر
        risk_lbl, risk_color, risk_icon = _risk_level(abs_total, tard_mins, ref_count)
        self._ana_risk_lbl.config(
            text=f"{risk_icon} مستوى الخطر: {risk_lbl}",
            fg=risk_color)
        self._ana_risk_bar.config(
            text=f"غياب×3 + تأخر÷10 + مخالفات×5 = {abs_total*3+(tard_mins//10)+ref_count*5}")

        # الرسوم
        self._draw_absence_chart(data["absences"])
        self._draw_cases_chart(data)
        self._draw_dow_chart(data.get("absence_by_dow", {}))

        # الجدول الزمني
        self.analysis_tree.delete(*self.analysis_tree.get_children())
        for ev in data.get("recent_events", []):
            self.analysis_tree.insert("", "end",
                values=(ev["date"], ev["type"], ev["details"], ev["status"]))
                
        # سجل النقاط التفصيلي
        self.points_tree.delete(*self.points_tree.get_children())
        for p in data.get("points_history", []):
            self.points_tree.insert("", "end",
                values=(p["date"], f"+{p['points']}", p["reason"], p.get("author_name", "—")))

        # النتائج الدراسية
        res = data.get("results")
        if res:
            self._res_gpa_lbl.config(text=str(res.get("gpa") or "—"))
            self._res_year_lbl.config(text=str(res.get("year") or "—"))
            rank_txt = ""
            if res.get("rank"):         rank_txt += f"ترتيب الفصل: #{res['rank']}"
            if res.get("section_rank"): rank_txt += f"  |  ترتيب المستوى: #{res['section_rank']}"
            self._res_rank_lbl.config(text=rank_txt)
        else:
            self._res_gpa_lbl.config(text="—")
            self._res_year_lbl.config(text="—")
            self._res_rank_lbl.config(text="")

        # الملاحظات
        self._refresh_notes_tree(data.get("notes", []))

    # ─────────────────────────────────────────────────────────────
    def _draw_absence_chart(self, absences):
        self.ax_abs.clear()
        if not absences:
            self.ax_abs.text(0.5, 0.5, ar("لا توجد بيانات"),
                             ha="center", va="center", fontsize=9)
        else:
            months = {}
            for a in absences:
                m = a["date"][:7]
                months[m] = months.get(m, 0) + 1
            keys = sorted(months)
            vals = [months[k] for k in keys]
            n = len(keys)
            bars = self.ax_abs.bar(range(n), vals, color="#6366F1", width=0.5)
            self.ax_abs.set_xticks(range(n))
            self.ax_abs.set_xticklabels(keys, rotation=40, ha="right", fontsize=7)
            self.ax_abs.set_xlim(-0.8, max(n - 0.2, 0.8))
            self.ax_abs.set_ylim(0, max(vals) + 1.5)
            for bar, v in zip(bars, vals):
                self.ax_abs.text(bar.get_x() + bar.get_width()/2,
                                 v + 0.1, str(v), ha="center", fontsize=7)
            self.ax_abs.set_title(ar("الغياب الشهري"), fontsize=9)
        self.fig_abs.tight_layout()
        self.canvas_abs.draw_idle()

    def _draw_cases_chart(self, data):
        """رسم بياني أفقي لنسبة الحضور والالتزام (أرقام مطلقة واضحة)."""
        self.ax_cases.clear()

        SCHOOL_DAYS = data.get("total_school_days", 1)
        abs_total = len(data["absences"])
        excused   = data.get("excused_count", 0)
        unexcused = data.get("unexcused_count", abs_total)
        attend    = max(0, SCHOOL_DAYS - abs_total)
        att_pct   = round(attend / SCHOOL_DAYS * 100, 1)

        categories = [ar("حضور"), ar("غياب مبرر"), ar("غياب غير مبرر")]
        values     = [attend, excused, unexcused]
        colors     = ["#22C55E", "#F59E0B", "#EF4444"]

        bars = self.ax_cases.barh(categories, values, color=colors, height=0.5)
        for bar, v in zip(bars, values):
            if v > 0:
                self.ax_cases.text(
                    bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                    str(v), va="center", fontsize=8, fontweight="bold")

        self.ax_cases.set_xlim(0, SCHOOL_DAYS + 15)
        self.ax_cases.set_title(
            ar(f"نسبة الحضور: {att_pct}%"),
            fontsize=10, fontweight="bold",
            color="#22C55E" if att_pct >= 90 else
                  "#F59E0B" if att_pct >= 75 else "#EF4444")
        self.ax_cases.tick_params(axis="y", labelsize=8)
        self.ax_cases.tick_params(axis="x", labelsize=7)
        self.fig_cases.tight_layout()
        self.canvas_cases.draw_idle()

    def _draw_dow_chart(self, dow: dict):
        self.ax_dow.clear()
        days = ["الأحد","الاثنين","الثلاثاء","الأربعاء","الخميس"]
        vals = [dow.get(d, 0) for d in days]
        colors = ["#FCA5A5" if v == max(vals) and v > 0 else "#93C5FD"
                  for v in vals]
        bars = self.ax_dow.bar(range(len(days)), vals, color=colors, width=0.6)
        self.ax_dow.set_xticks(range(len(days)))
        self.ax_dow.set_xticklabels([ar(d) for d in days], fontsize=7)
        for bar, v in zip(bars, vals):
            if v > 0:
                self.ax_dow.text(bar.get_x() + bar.get_width()/2,
                                 v + 0.05, str(v), ha="center", fontsize=7)
        self.ax_dow.set_title(ar("أيام الغياب المتكررة"), fontsize=9)
        self.fig_dow.tight_layout()
        self.canvas_dow.draw_idle()

    # ─────────────────────────────────────────────────────────────
    def _refresh_notes_tree(self, notes: list):
        self._ana_notes_tree.delete(*self._ana_notes_tree.get_children())
        for n in notes:
            self._ana_notes_tree.insert("", "end", iid=str(n["id"]),
                values=(n["note"], n["author"], n["created_at"][:10]))

    def _ana_add_note(self):
        if not self._current_ana_student_id:
            messagebox.showwarning("تنبيه", "اختر طالباً أولاً"); return
        note = simpledialog.askstring(
            "ملاحظة جديدة",
            "أدخل الملاحظة الإدارية:",
            parent=self.root)
        if not note or not note.strip(): return
        author = CURRENT_USER.get("name") or CURRENT_USER.get("username", "")
        new_id = add_student_note(
            self._current_ana_student_id, note.strip(), author)
        import datetime as _dt
        self._ana_notes_tree.insert("", 0, iid=str(new_id),
            values=(note.strip(), author,
                    _dt.datetime.now().strftime("%Y-%m-%d")))

    def _ana_delete_note(self):
        from database import authenticate
        from constants import CURRENT_USER
        from tkinter import simpledialog
        sel = self._ana_notes_tree.selection()
        if not sel: messagebox.showwarning("تنبيه", "اختر ملاحظة أولاً"); return
        if not messagebox.askyesno("تأكيد", "حذف الملاحظة المحددة؟"): return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        delete_student_note(int(sel[0]))
        self._ana_notes_tree.delete(sel[0])

    # ─────────────────────────────────────────────────────────────
    def _ana_open_wa(self):
        if not self._ana_parent_phone:
            messagebox.showwarning("تنبيه", "لا يوجد رقم لولي الأمر"); return
        phone = self._ana_parent_phone.strip().lstrip("0")
        if not phone.startswith("966"):
            phone = "966" + phone
        webbrowser.open(f"https://wa.me/{phone}")

    def _ana_copy_portal_link(self):
        if not self._current_ana_student_id:
            messagebox.showwarning("تنبيه", "اختر طالباً أولاً"); return
        
        try:
            from database import get_or_create_portal_token
            from constants import MY_STATIC_DOMAIN, STATIC_DOMAIN, local_ip, PORT, debug_on
            
            token = get_or_create_portal_token(self._current_ana_student_id)
            
            base = STATIC_DOMAIN or MY_STATIC_DOMAIN
            if not base or debug_on():
                base = f"http://{local_ip()}:{PORT}"
            
            link = f"{base}/p/{token}"
            
            self.root.clipboard_clear()
            self.root.clipboard_append(link)
            messagebox.showinfo("تم النسخ", f"تم نسخ رابط ولي الأمر للمحفظة:\n{link}")
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل توليد الرابط: {e}")

    # ─────────────────────────────────────────────────────────────
    def _ana_export_pdf(self):
        if not self._current_ana_data or not self._current_ana_student_id:
            messagebox.showwarning("تنبيه", "اختر طالباً وانتظر تحميل البيانات أولاً")
            return
        data = self._current_ana_data
        sid  = self._current_ana_student_id
        cfg  = load_config()
        school = cfg.get("school_name", "المدرسة")

        abs_total = len(data["absences"])
        excused   = data.get("excused_count", 0)
        unexcused = data.get("unexcused_count", abs_total)
        tard_mins = sum(r["minutes"] for r in data["tardiness"])
        ref_count = len(data["referrals"])
        gpa_val   = (data["results"]["gpa"] if data["results"] else "—")
        risk_lbl, risk_color, risk_icon = _risk_level(abs_total, tard_mins, ref_count)

        name_val = self._ana_name_lbl.cget("text")
        class_val = self._ana_class_lbl.cget("text").replace("الفصل: ","")

        events_rows = ""
        for ev in data.get("recent_events", []):
            events_rows += (
                f"<tr><td>{ev['date']}</td><td>{ev['type']}</td>"
                f"<td>{ev['details']}</td><td>{ev['status']}</td></tr>")

        notes_rows = ""
        for n in data.get("notes", []):
            notes_rows += (
                f"<tr><td>{n['note']}</td><td>{n['author']}</td>"
                f"<td>{n['created_at'][:10]}</td></tr>")

        html = f"""<!DOCTYPE html><html dir="rtl" lang="ar">
<head><meta charset="UTF-8">
<style>
  body{{font-family:Tahoma,Arial;background:#f8f9fa;color:#1e293b;margin:0;padding:20px}}
  h1{{background:#0F172A;color:white;padding:14px 20px;border-radius:8px;font-size:18px}}
  .card{{background:white;border-radius:8px;padding:16px;margin-bottom:14px;
         box-shadow:0 1px 4px rgba(0,0,0,.08)}}
  .kpi-row{{display:flex;gap:10px;flex-wrap:wrap}}
  .kpi{{flex:1;min-width:100px;text-align:center;border-radius:8px;
        padding:12px;background:#f1f5f9}}
  .kpi .num{{font-size:28px;font-weight:bold}}
  .risk{{padding:10px 18px;border-radius:20px;font-weight:bold;
         color:white;background:{risk_color};display:inline-block}}
  table{{width:100%;border-collapse:collapse;font-size:12px}}
  th{{background:#0F172A;color:white;padding:7px;text-align:right}}
  td{{padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:right}}
  tr:nth-child(even){{background:#f8fafc}}
  @media print{{body{{padding:0}}}}
</style>
</head><body>
<h1>📊 تقرير الطالب الشامل — {school}</h1>
<div class="card">
  <b style="font-size:15px">{name_val}</b> &nbsp;|&nbsp; {class_val}
  &nbsp;|&nbsp; رقم الطالب: {sid}
  &nbsp;&nbsp; <span class="risk">{risk_icon} مستوى الخطر: {risk_lbl}</span>
</div>
<div class="card">
  <b>مؤشرات الأداء</b>
  <div class="kpi-row" style="margin-top:10px">
    <div class="kpi"><div class="num" style="color:#EF4444">{abs_total}</div>إجمالي الغياب</div>
    <div class="kpi"><div class="num" style="color:#22C55E">{excused}</div>مبرر</div>
    <div class="kpi"><div class="num" style="color:#F97316">{unexcused}</div>غير مبرر</div>
    <div class="kpi"><div class="num" style="color:#F59E0B">{tard_mins}</div>دقائق تأخر</div>
    <div class="kpi"><div class="num" style="color:#6366F1">{ref_count}</div>مخالفات</div>
    <div class="kpi"><div class="num" style="color:#10B981">{gpa_val}</div>المعدل</div>
    <div class="kpi"><div class="num" style="color:#3B82F6">{round(max(0,data.get("total_school_days",1)-abs_total)/max(data.get("total_school_days",1),1)*100,1)}%</div>نسبة الحضور</div>
  </div>
</div>
<div class="card">
  <b>🕒 الجدول الزمني</b>
  <table style="margin-top:8px">
    <tr><th>التاريخ</th><th>النوع</th><th>التفاصيل</th><th>الحالة</th></tr>
    {events_rows or "<tr><td colspan='4' style='text-align:center'>لا توجد سجلات</td></tr>"}
  </table>
</div>
<div class="card">
  <b>📝 الملاحظات الإدارية</b>
  <table style="margin-top:8px">
    <tr><th>الملاحظة</th><th>بقلم</th><th>التاريخ</th></tr>
    {notes_rows or "<tr><td colspan='3' style='text-align:center'>لا توجد ملاحظات</td></tr>"}
  </table>
</div>
<div style="text-align:center;color:#94a3b8;font-size:11px;margin-top:16px">
  تم الإنشاء بواسطة نظام درب — {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
</div>
</body></html>"""

        tmp = os.path.join(DATA_DIR, f"student_report_{sid}.html")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(html)
        webbrowser.open("file://" + os.path.abspath(tmp))
