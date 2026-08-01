# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os, threading

from grade_analysis import (
    _ga_parse_file, _ga_export_word, _ga_open_header_editor,
    _GA_HEADER_DATA, _ga_grade, _ga_build_html
)

try:
    from tkinterweb import HtmlFrame
except ImportError:
    HtmlFrame = None

class GradeAnalysisTabMixin:
    """Mixin: تبويب تحليل نتائج الطلاب (النسخة المستقرة)"""

    def _build_grade_analysis_tab(self):
        self.ga_data = [] # لتخزين نتائج الطلاب
        
        frame = self.grade_analysis_frame
        frame.configure(bg="#F8FAFC")

        # ── شريط الأدوات العلوي ────────────────────────────────────
        toolbar = tk.Frame(frame, bg="#1E293B", pady=10)
        toolbar.pack(fill="x")

        tk.Label(toolbar, text="📊 تحليل نتائج الطلاب", bg="#1E293B", fg="white",
                 font=("Tahoma", 12, "bold")).pack(side="right", padx=15)

        btn_style = {"font": ("Tahoma", 9), "padx": 10, "pady": 5}
        
        tk.Button(toolbar, text="📂 اختيار ملف (Excel/PDF)", command=self._ga_browse,
                  bg="#3B82F6", fg="white", relief="flat", **btn_style).pack(side="right", padx=5)
        
        tk.Button(toolbar, text="⚡ بدء التحليل", command=self._ga_analyze,
                  bg="#10B981", fg="white", relief="flat", **btn_style).pack(side="right", padx=5)

        tk.Button(toolbar, text="📝 تصدير Word", command=self._ga_export,
                  bg="#6366F1", fg="white", relief="flat", **btn_style).pack(side="right", padx=5)

        tk.Button(toolbar, text="⚙️ الترويسة", command=lambda: _ga_open_header_editor(self.root),
                  bg="#64748B", fg="white", relief="flat", **btn_style).pack(side="right", padx=5)

        tk.Button(toolbar, text="🌐 فتح في المتصفح", command=self._ga_open_browser,
                  bg="#0F172A", fg="white", relief="flat", **btn_style).pack(side="right", padx=5)

        tk.Button(toolbar, text="🖨️ طباعة / PDF", command=self._ga_print_pdf,
                  bg="#F59E0B", fg="white", relief="flat", **btn_style).pack(side="right", padx=15)

        # ── شريط الفلترة ──────────────────────────────────────────
        filter_bar = tk.Frame(frame, bg="white", pady=5)
        filter_bar.pack(fill="x", padx=10, pady=5)
        
        tk.Label(filter_bar, text="عرض المادة:", bg="white").pack(side="right", padx=5)
        self.ga_subject_var = tk.StringVar(value="الكل")
        self.ga_subject_cb = ttk.Combobox(filter_bar, textvariable=self.ga_subject_var, state="readonly", width=30)
        self.ga_subject_cb.pack(side="right", padx=5)
        self.ga_subject_cb.bind("<<ComboboxSelected>>", lambda e: self._ga_refresh_table())

        # ── عرض النتائج (جدول البيانات فقط لضمان الثبات) ──────────
        table_frame = tk.Frame(frame, bg="white")
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("m", "name", "id", "score", "pct", "grade")
        self.ga_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=15)
        
        headings = {"m": "م", "name": "اسم الطالب", "id": "السجل/الهوية", 
                    "score": "الدرجة", "pct": "النسبة", "grade": "التقدير"}
        widths = {"m": 40, "name": 250, "id": 120, "score": 80, "pct": 80, "grade": 100}

        for c in cols:
            self.ga_tree.heading(c, text=headings[c])
            self.ga_tree.column(c, width=widths[c], anchor="center" if c != "name" else "e")

        sb = ttk.Scrollbar(table_frame, orient="vertical", command=self.ga_tree.yview)
        self.ga_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.ga_tree.pack(side="left", fill="both", expand=True)

        # رسالة توضيحية للمستخدم
        tk.Label(frame, text="💡 لمشاهدة الرسوم البيانية والتقرير الملون، اضغط على زر (🌐 فتح في المتصفح) في الأعلى لضمان أفضل ثبات.",
                 bg="#F8FAFC", fg="#64748B", font=("Tahoma", 9)).pack(pady=5)

        # ── شريط الحالة السفلي ─────────────────────────────────────
        self.ga_status_lbl = tk.Label(frame, text="جاهز. يرجى اختيار ملف النتائج (Excel أو PDF نور).", 
                                      anchor="e", bg="#F1F5F9", fg="#475569", padx=10)
        self.ga_status_lbl.pack(fill="x", side="bottom")

    def _ga_browse(self):
        f = filedialog.askopenfilename(filetypes=[("Result Files", "*.xlsx *.xls *.pdf *.csv")])
        if f:
            self.ga_selected_file = f
            self.ga_status_lbl.config(text=f"الملف المحدد: {os.path.basename(f)}")

    def _ga_analyze(self):
        if not hasattr(self, 'ga_selected_file') or not self.ga_selected_file:
            messagebox.showwarning("تنبيه", "يرجى اختيار ملف أولاً")
            return

        def _worker():
            try:
                self.root.after(0, lambda: self.ga_status_lbl.config(text="⏳ جاري التحليل... يرجى الانتظار"))
                data = _ga_parse_file(self.ga_selected_file)
                self.root.after(0, lambda: self._ga_on_data_ready(data))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("خطأ في التحليل", str(e)))
                self.root.after(0, lambda: self.ga_status_lbl.config(text="❌ فشل التحليل"))

        threading.Thread(target=_worker, daemon=True).start()

    def _ga_on_data_ready(self, data):
        try:
            print(f"[GA-DEBUG] Analysis finished correctly. Data received: {len(data)} students.")
            self.ga_data = data
            subjects = set()
            for s in data:
                for sub in s.get('subjects', []):
                    subjects.add(sub['subject'])
            
            self.ga_subject_cb['values'] = ["الكل"] + sorted(list(subjects))
            self.ga_subject_var.set("الكل")
            
            print("[GA-DEBUG] Refreshing Treeview table...")
            self._ga_refresh_table()
            print("[GA-DEBUG] Table refreshed successfully.")
            
            self.ga_status_lbl.config(text=f"✅ تم تحليل {len(data)} طالب بنجاح. استخدم زر (فتح في المتصفح) للمعاينة.")
            print("[GA-DEBUG] UI update complete. App is stable.")
        except Exception as e:
            print(f"[GA-DEBUG] CRITICAL ERROR in UI Thread: {e}")
            messagebox.showerror("خطأ", f"حدث خطأ أثناء معالجة النتائج: {e}")

    def _ga_refresh_table(self):
        self.ga_tree.delete(*self.ga_tree.get_children())
        sel_subj = self.ga_subject_var.get()
        
        for i, s in enumerate(self.ga_data, 1):
            if sel_subj == "الكل":
                sc = s.get('total_score', 0)
                mx = s.get('total_max', 100)
                pct = (sc/mx*100) if mx > 0 else 0
            else:
                target = next((sub for sub in s.get('subjects', []) if sub['subject'] == sel_subj), None)
                if not target: continue
                sc = target['score']
                mx = target['max_score']
                pct = (sc/mx*100) if mx > 0 else 0
            
            grade_lbl, *_ = _ga_grade(pct)
            self.ga_tree.insert("", "end", values=(i, s['name'], s.get('id', ''), sc, f"{pct:.1f}%", grade_lbl))

    def _ga_export(self):
        if not self.ga_data:
            messagebox.showwarning("تنبيه", "لا توجد بيانات لتصديرها. حلل ملفاً أولاً.")
            return
        
        f = filedialog.asksaveasfilename(defaultextension=".docx", filetypes=[("Word Document", "*.docx")])
        if f:
            try:
                from grade_analysis import _ga_export_word
                _ga_export_word(self.ga_data, f, self.ga_subject_var.get())
                messagebox.showinfo("نجاح", f"تم حفظ التقرير في:\n{f}")
            except Exception as e:
                messagebox.showerror("خطأ في التصدير", str(e))

    def _ga_open_browser(self):
        """تفتح التقرير في المتصفح الخارجي (أكثر ثباتاً من العرض الداخلي)"""
        if not self.ga_data:
            messagebox.showwarning("تنبيه", "لا توجد بيانات لعرضها. حلل ملفاً أولاً.")
            return
        
        try:
            html = _ga_build_html(self.ga_data, sel_subject=self.ga_subject_var.get())
            temp_path = os.path.join(os.getcwd(), "temp_report.html")
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(html)
            
            import webbrowser
            webbrowser.open(f"file:///{temp_path}")
            self.ga_status_lbl.config(text="🌐 تم فتح التقرير في المتصفح بنجاح.")
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل فتح المتصفح: {e}")

    def _ga_print_pdf(self):
        """تولد نسخة مهيئة للطباعة وتفتحها في المتصفح لطلب الطباعة تلقائياً"""
        if not self.ga_data:
            messagebox.showwarning("تنبيه", "لا توجد بيانات للطباعة. حلل ملفاً أولاً.")
            return
        
        try:
            from grade_analysis import _ga_build_print_html
            # جلب مادة واحدة إذا كان المستخدم يفلتر، أو الكل
            sel = self.ga_subject_var.get()
            html = _ga_build_print_html(self.ga_data, sel_subject=sel)
            
            # إضافة سكريبت للطباعة التلقائية
            if "</body>" in html:
                html = html.replace("</body>", "<script>window.onload = function() { window.print(); }</script></body>")

            temp_path = os.path.join(os.getcwd(), "temp_print_report.html")
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(html)
            
            import webbrowser
            webbrowser.open(f"file:///{temp_path}")
            self.ga_status_lbl.config(text="🖨️ تم تجهيز صفحة الطباعة وفتحها في المتصفح.")
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل تجهيز الطباعة: {e}")
