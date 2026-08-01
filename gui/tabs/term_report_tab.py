# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time, webbrowser
from constants import DATA_DIR
from report_builder import generate_term_report_html

class TermReportTabMixin:
    """Mixin: TermReportTabMixin"""
    def _build_term_report_tab(self):
        frame = self.term_report_frame

        hdr = tk.Frame(frame, bg="#4A148C", height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📊 تقرير نهاية الفصل الدراسي",
                 bg="#4A148C", fg="white",
                 font=("Tahoma",12,"bold")).pack(side="right", padx=14, pady=12)

        body = ttk.Frame(frame); body.pack(fill="both", expand=True, padx=16, pady=12)

        lf = ttk.LabelFrame(body, text=" الفترة الزمنية ", padding=12)
        lf.pack(fill="x", pady=(0,12))

        now2 = datetime.datetime.now()
        r1 = ttk.Frame(lf); r1.pack(fill="x", pady=4)
        ttk.Label(r1, text="من (YYYY-MM):", width=16, anchor="e").pack(side="right")
        self.term_from_var = tk.StringVar(
            value=(now2-datetime.timedelta(days=120)).strftime("%Y-%m"))
        ttk.Entry(r1, textvariable=self.term_from_var, width=12).pack(side="right", padx=4)

        r2 = ttk.Frame(lf); r2.pack(fill="x", pady=4)
        ttk.Label(r2, text="إلى (YYYY-MM):", width=16, anchor="e").pack(side="right")
        self.term_to_var = tk.StringVar(value=now2.strftime("%Y-%m"))
        ttk.Entry(r2, textvariable=self.term_to_var, width=12).pack(side="right", padx=4)

        br = ttk.Frame(lf); br.pack(fill="x", pady=(8,0))
        ttk.Button(br, text="📊 إنشاء التقرير",
                   command=self._generate_term_report).pack(side="right", padx=4)
        ttk.Button(br, text="🖨️ فتح للطباعة",
                   command=self._open_term_report).pack(side="right", padx=4)

        self.term_status = ttk.Label(lf, text="", foreground="#5A6A7E")
        self.term_status.pack(anchor="e", pady=(6,0))

        prev_lf = ttk.LabelFrame(body, text=" معاينة ", padding=4)
        prev_lf.pack(fill="both", expand=True)
        self.term_preview = tk.Text(prev_lf, wrap="word",
                                     font=("Tahoma",9), state="disabled", bg="#FAFAFA")
        sb = ttk.Scrollbar(prev_lf, orient="vertical", command=self.term_preview.yview)
        self.term_preview.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.term_preview.pack(side="left", fill="both", expand=True)
        self._term_html = ""

    def _generate_term_report(self):
        mf = self.term_from_var.get().strip() if hasattr(self,"term_from_var") else None
        mt = self.term_to_var.get().strip()   if hasattr(self,"term_to_var")   else None
        if hasattr(self,"term_status"):
            self.term_status.config(text="⏳ جارٍ الإنشاء...")
        import threading as _th
        def _build():
            try:
                html = generate_term_report_html(mf, mt)
                self._term_html = html
                self.root.after(0, self._show_term_preview)
            except Exception as e:
                self.root.after(0, lambda: self.term_status.config(
                    text="❌ خطأ: {}".format(e), foreground="red"))
        _th.Thread(target=_build, daemon=True).start()

    def _show_term_preview(self):
        import re as _re
        html = self._term_html
        # احذف style وscript كاملاً أولاً
        html = _re.sub(r'<style[^>]*>.*?</style>', '', html, flags=_re.DOTALL)
        html = _re.sub(r'<script[^>]*>.*?</script>', '', html, flags=_re.DOTALL)
        # احذف باقي الـ tags
        text = _re.sub(r'<[^>]+>', ' ', html)
        # نظّف المسافات والأسطر الزائدة
        text = _re.sub(r'[ \t]{2,}', ' ', text)
        text = _re.sub(r'\n{3,}', '\n\n', text).strip()
        if hasattr(self,"term_preview"):
            self.term_preview.config(state="normal")
            self.term_preview.delete("1.0","end")
            self.term_preview.insert("1.0", text)
            self.term_preview.config(state="disabled")
        if hasattr(self,"term_status"):
            self.term_status.config(
                text="✅ جاهز — اضغط 'فتح للطباعة'", foreground="green")
    def _open_term_report(self):
        if not self._term_html:
            self._generate_term_report()
            messagebox.showinfo("تنبيه","انتظر اكتمال التقرير ثم اضغط مجدداً")
            return
        tmp = os.path.join(DATA_DIR, "term_report.html")
        with open(tmp,"w",encoding="utf-8") as f: f.write(self._term_html)
        webbrowser.open("file://{}".format(os.path.abspath(tmp)))


