# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time, webbrowser
from constants import now_riyadh_date, DATA_DIR, BASE_DIR
from report_builder import export_to_noor_excel
from database import import_students_from_excel_sheet2_format

class NoorTabMixin:
    """Mixin: NoorTabMixin"""
    def _build_noor_export_tab(self):
        frame = self.noor_export_frame

        hdr = tk.Frame(frame, bg="#1565C0", height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📤 تصدير ملف نور — يدوي وتلقائي",
                 bg="#1565C0", fg="white",
                 font=("Tahoma",13,"bold")).pack(side="right", padx=16, pady=12)

        body = ttk.Frame(frame); body.pack(fill="both", expand=True, padx=15, pady=15)

        # ─ تصدير يدوي
        manual = ttk.LabelFrame(body, text=" 📋 تصدير يدوي ", padding=12)
        manual.pack(fill="x", pady=(0,12))

        mr1 = ttk.Frame(manual); mr1.pack(fill="x", pady=4)
        ttk.Label(mr1, text="التاريخ:", width=14, anchor="e").pack(side="right")
        self.noor_date_var = tk.StringVar(value=now_riyadh_date())
        ttk.Entry(mr1, textvariable=self.noor_date_var, width=14).pack(side="right", padx=4)

        mr2 = ttk.Frame(manual); mr2.pack(fill="x", pady=4)
        ttk.Label(mr2, text="مجلد الحفظ:", width=14, anchor="e").pack(side="right")
        self.noor_dir_var = tk.StringVar(value=os.path.abspath(DATA_DIR))
        ttk.Entry(mr2, textvariable=self.noor_dir_var, state="readonly",
                  font=("Courier",9), width=40).pack(side="right", padx=4)
        ttk.Button(mr2, text="تغيير", width=8,
                   command=self._noor_choose_dir).pack(side="left")

        ttk.Button(manual, text="💾 تصدير الآن",
                   command=self._noor_export_now).pack(anchor="e", pady=6)
        self.noor_status = ttk.Label(manual, text="", foreground="green")
        self.noor_status.pack(anchor="e")

        # ─ تصدير تلقائي
        auto = ttk.LabelFrame(body, text=" ⏰ تصدير تلقائي في نهاية اليوم ", padding=12)
        auto.pack(fill="x", pady=(0,12))

        ar1 = ttk.Frame(auto); ar1.pack(fill="x", pady=4)
        self.noor_auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ar1, text="تفعيل التصدير التلقائي اليومي",
                        variable=self.noor_auto_var).pack(side="right")

        ar2 = ttk.Frame(auto); ar2.pack(fill="x", pady=4)
        ttk.Label(ar2, text="وقت التصدير:", width=14, anchor="e").pack(side="right")
        self.noor_hour_var = tk.IntVar(value=13)
        ttk.Spinbox(ar2, from_=10, to=17,
                    textvariable=self.noor_hour_var, width=5).pack(side="right", padx=4)
        ttk.Label(ar2, text=":30 (يومياً أيام الأحد–الخميس)").pack(side="right")

        ttk.Button(auto, text="💾 حفظ إعدادات التصدير التلقائي",
                   command=self._noor_save_auto).pack(anchor="e", pady=6)

        # ─ سجل الملفات المُصدَّرة
        hist = ttk.LabelFrame(body, text=" 📁 ملفات نور المُصدَّرة ", padding=8)
        hist.pack(fill="both", expand=True)

        cols = ("filename","date","size","path")
        self.tree_noor = ttk.Treeview(hist, columns=cols, show="headings", height=8)
        for col, hdr_t, w in zip(cols,
            ["اسم الملف","التاريخ","الحجم","المسار"],
            [200,100,80,300]):
            self.tree_noor.heading(col, text=hdr_t)
            self.tree_noor.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(hist, orient="vertical", command=self.tree_noor.yview)
        self.tree_noor.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree_noor.pack(side="left", fill="both", expand=True)
        ttk.Button(hist, text="📂 فتح المجلد",
                   command=self._noor_open_dir).pack(pady=4)
        frame.after(100, self._noor_load_history)

        # ─ امتداد Chrome لنقل الغياب مباشرةً لنور ─────────────
        ext_frame = ttk.LabelFrame(body,
            text=" 🔗 امتداد Chrome لنقل الغياب المباشر لنور ",
            padding=12)
        ext_frame.pack(fill="x", pady=(0, 6))
        self._build_noor_extension_section(ext_frame)

    # ──────────────────────────────────────────────────────────
    # قسم امتداد Chrome
    # ──────────────────────────────────────────────────────────
    def _build_noor_extension_section(self, parent):
        from config_manager import load_config
        cfg       = load_config()
        cloud_url = cfg.get("cloud_url", "").strip()
        token     = cfg.get("cloud_token", "").strip()

        desc = ttk.Label(parent,
            text="الامتداد يتصل بسيرفر DarbStu ويجلب قائمة الغائبين ثم يملأ صفحة نور تلقائياً.",
            wraplength=560, justify="right", foreground="#555")
        desc.pack(anchor="e", pady=(0, 8))

        creds = ttk.Frame(parent); creds.pack(fill="x", pady=(0, 8))

        row_url = ttk.Frame(creds); row_url.pack(fill="x", pady=2)
        ttk.Label(row_url, text="رابط السيرفر:", width=16, anchor="e").pack(side="right")
        self._noor_url_var = tk.StringVar(value=cloud_url or "لم يُضبط بعد — اضبطه من تبويب الربط السحابي")
        ttk.Entry(row_url, textvariable=self._noor_url_var,
                  state="readonly", width=42, font=("Courier", 9)).pack(side="right", padx=4)
        ttk.Button(row_url, text="📋 نسخ",
                   command=lambda: self._noor_copy(cloud_url)).pack(side="right")

        row_tok = ttk.Frame(creds); row_tok.pack(fill="x", pady=2)
        ttk.Label(row_tok, text="رمز الأمان (Token):", width=16, anchor="e").pack(side="right")
        self._noor_tok_var = tk.StringVar(value="••••••••" if token else "لم يُضبط بعد")
        ttk.Entry(row_tok, textvariable=self._noor_tok_var,
                  state="readonly", width=42, font=("Courier", 9)).pack(side="right", padx=4)
        ttk.Button(row_tok, text="📋 نسخ",
                   command=lambda: self._noor_copy(token)).pack(side="right")
        ttk.Button(row_tok, text="👁 إظهار",
                   command=lambda: self._noor_tok_var.set(
                       token if self._noor_tok_var.get().startswith("•") else "••••••••")
                   ).pack(side="right", padx=4)

        btns = ttk.Frame(parent); btns.pack(fill="x", pady=(4, 0))
        ext_dir = os.path.join(BASE_DIR, "noor_extension")
        ttk.Button(btns, text="📂 فتح مجلد الامتداد",
                   command=lambda: self._noor_open_ext_dir(ext_dir)
                   ).pack(side="right", padx=4)
        ttk.Button(btns, text="❓ تعليمات التثبيت",
                   command=self._noor_show_install_instructions
                   ).pack(side="right", padx=4)

    def _noor_copy(self, text):
        if not text:
            messagebox.showwarning("تنبيه", "لا توجد قيمة لنسخها.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        messagebox.showinfo("تم النسخ", "✅ تم نسخ القيمة للحافظة.")

    def _noor_open_ext_dir(self, ext_dir):
        if not os.path.isdir(ext_dir):
            messagebox.showerror("خطأ", f"المجلد غير موجود:\n{ext_dir}")
            return
        try:
            os.startfile(os.path.abspath(ext_dir))
        except Exception:
            webbrowser.open("file://{}".format(os.path.abspath(ext_dir).replace("\\", "/")))

    def _noor_show_install_instructions(self):
        win = tk.Toplevel(self.root)
        win.title("تعليمات تثبيت امتداد نقل الغياب لنور")
        win.geometry("560x440")
        win.resizable(False, False)

        hdr = tk.Frame(win, bg="#1565C0", height=45)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🔧 تثبيت امتداد Chrome — خطوة بخطوة",
                 bg="#1565C0", fg="white",
                 font=("Tahoma", 12, "bold")).pack(side="right", padx=14, pady=10)

        txt = tk.Text(win, font=("Tahoma", 11), wrap="word", padx=14, pady=10,
                      bg="#fafbff", relief="flat")
        txt.pack(fill="both", expand=True)
        instructions = (
            "الخطوة 1: افتح متصفح Chrome\n\n"
            "الخطوة 2: اكتب في شريط العنوان:\n"
            "          chrome://extensions\n\n"
            "الخطوة 3: فعّل \"وضع المطور\" (Developer Mode)\n"
            "          — المفتاح في الزاوية العلوية اليسرى\n\n"
            "الخطوة 4: اضغط على \"تحميل غير مضغوط\" (Load unpacked)\n\n"
            "الخطوة 5: اختر مجلد «noor_extension» من مجلد DarbStu\n\n"
            "الخطوة 6: سيظهر الامتداد في شريط Chrome 🎉\n\n"
            "─────────────────────────────────────────────\n\n"
            "كيف تستخدمه يومياً:\n\n"
            "① افتح Chrome وادخل نظام نور كالمعتاد\n"
            "② انتقل لصفحة «إدخال السلوك والمواظبة»\n"
            "③ اضغط أيقونة الامتداد في شريط Chrome\n"
            "④ اضغط «🔄 جلب تلقائي» لملء الرابط والرمز\n"
            "⑤ اضغط «🚀 بدء رفع الغياب» — وستشاهد التقدم مباشرة\n\n"
            "تنبيه: يلزم ضبط جدول «ربط الفصول» مرة واحدة\n"
            "       (اسم الفصل في DarbStu ↔ الصف+القسم+الفصل في نور)"
        )
        txt.insert("1.0", instructions)
        txt.config(state="disabled")
        ttk.Button(win, text="إغلاق", command=win.destroy).pack(pady=8)

    def _noor_choose_dir(self):
        d = filedialog.askdirectory(title="اختر مجلد حفظ ملفات نور")
        if d and hasattr(self, "noor_dir_var"):
            self.noor_dir_var.set(d)

    def _noor_export_now(self):
        date_str = self.noor_date_var.get().strip() if hasattr(self,"noor_date_var") else now_riyadh_date()
        save_dir = self.noor_dir_var.get().strip() if hasattr(self,"noor_dir_var") else DATA_DIR
        os.makedirs(save_dir, exist_ok=True)
        filename = os.path.join(save_dir, "noor_{}.xlsx".format(date_str))
        try:
            export_to_noor_excel(date_str, filename)
            size_kb = os.path.getsize(filename) // 1024
            if hasattr(self,"noor_status"):
                self.noor_status.configure(
                    text="✅ تم التصدير: {} ({} KB)".format(
                        os.path.basename(filename), size_kb),
                    foreground="green")
            self.noor_export_frame.after(100, self._noor_load_history)
            messagebox.showinfo("تم التصدير", "تم حفظ ملف نور:\n{}".format(filename))
        except Exception as e:
            if hasattr(self,"noor_status"):
                self.noor_status.configure(
                    text="❌ فشل: {}".format(e), foreground="red")

    def _noor_save_auto(self):
        messagebox.showinfo("تم","إعدادات التصدير التلقائي محفوظة. سيعمل كل يوم عمل في الوقت المحدد.")

    def _noor_open_dir(self):
        d = self.noor_dir_var.get() if hasattr(self,"noor_dir_var") else DATA_DIR
        try: os.startfile(os.path.abspath(d))
        except Exception: webbrowser.open("file://{}".format(os.path.abspath(d)))

    def _noor_load_history(self):
        if not hasattr(self,"tree_noor"): return
        for i in self.tree_noor.get_children(): self.tree_noor.delete(i)
        save_dir = self.noor_dir_var.get().strip() if hasattr(self,"noor_dir_var") else DATA_DIR
        if not os.path.isdir(save_dir): return
        files = sorted(
            [f for f in os.listdir(save_dir) if f.startswith("noor_") and f.endswith(".xlsx")],
            reverse=True)
        for f in files[:30]:
            full = os.path.join(save_dir, f)
            size = "{} KB".format(os.path.getsize(full)//1024) if os.path.exists(full) else "—"
            date = f.replace("noor_","").replace(".xlsx","")
            self.tree_noor.insert("","end", values=(f, date, size, full))


