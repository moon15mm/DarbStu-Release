# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time, webbrowser
import sqlite3
from constants import PORT, STATIC_DOMAIN, local_ip, DATA_DIR, DB_PATH
from pdf_generator import parse_results_pdf, save_results_to_db
from license_manager import activate_license
from database import load_students, clear_student_results, get_cloud_client

class ResultsTabMixin:
    """Mixin: ResultsTabMixin"""
    def _build_results_tab(self):
        frame = self.results_frame

        hdr = tk.Frame(frame, bg="#1A237E", height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🎓 نشر نتائج الطلاب",
                 bg="#1A237E", fg="white",
                 font=("Tahoma",12,"bold")).pack(side="right", padx=14, pady=12)

        body = ttk.Frame(frame); body.pack(fill="both", expand=True, padx=16, pady=12)

        # ─ قسم رفع الملف
        upload_lf = ttk.LabelFrame(body, text=" 📂 رفع ملف النتائج (PDF) ", padding=12)
        upload_lf.pack(fill="x", pady=(0,12))

        r1 = ttk.Frame(upload_lf); r1.pack(fill="x", pady=4)
        ttk.Label(r1, text="ملف PDF:", width=12, anchor="e").pack(side="right")
        self.results_path_var = tk.StringVar()
        ttk.Entry(r1, textvariable=self.results_path_var,
                  state="readonly", width=40).pack(side="right", padx=4, fill="x", expand=True)
        ttk.Button(r1, text="📁 اختر الملف",
                   command=self._results_browse).pack(side="right", padx=4)

        r2 = ttk.Frame(upload_lf); r2.pack(fill="x", pady=4)
        ttk.Label(r2, text="العام الدراسي:", width=12, anchor="e").pack(side="right")
        self.results_year_var = tk.StringVar(
            value=str(datetime.date.today().year))
        ttk.Entry(r2, textvariable=self.results_year_var, width=10).pack(side="right", padx=4)

        br = ttk.Frame(upload_lf); br.pack(fill="x", pady=(8,0))
        ttk.Button(br, text="⬆️ استيراد النتائج",
                   command=self._results_import).pack(side="right", padx=4)

        self.results_status = ttk.Label(upload_lf, text="",
                                         font=("Tahoma",9))
        self.results_status.pack(anchor="e", pady=(6,0))

        # ─ قسم الرابط
        link_lf = ttk.LabelFrame(body, text=" 🔗 رابط بوابة النتائج ", padding=12)
        link_lf.pack(fill="x", pady=(0,12))

        base = (STATIC_DOMAIN if STATIC_DOMAIN
                else "http://{}:{}".format(local_ip(), PORT))
        portal_url = "{}/results".format(base)

        ttk.Label(link_lf,
            text=portal_url,
            font=("Tahoma",11,"bold"),
            foreground="#1565C0").pack(anchor="e", pady=(0,8))

        btn_row = ttk.Frame(link_lf); btn_row.pack(fill="x")
        ttk.Button(btn_row, text="📋 نسخ الرابط",
                   command=lambda u=portal_url: (
                       self.root.clipboard_clear(),
                       self.root.clipboard_append(u),
                       messagebox.showinfo("تم","✅ تم نسخ رابط البوابة")
                   )).pack(side="right", padx=4)
        ttk.Button(btn_row, text="🌐 فتح البوابة",
                   command=lambda u=portal_url: webbrowser.open(u)
                   ).pack(side="right", padx=4)

        ttk.Label(link_lf,
            text="شارك هذا الرابط مع الطلاب — كل طالب يدخل رقم هويته ويرى نتيجته فقط",
            foreground="#5A6A7E", font=("Tahoma",8)).pack(anchor="e", pady=(6,0))

        # ─ إحصائيات
        stats_lf = ttk.LabelFrame(body, text=" 📊 إحصائيات النتائج المنشورة ", padding=8)
        stats_lf.pack(fill="x")

        self.results_stats_lbl = ttk.Label(stats_lf, text="",
                                            font=("Tahoma",10))
        self.results_stats_lbl.pack(anchor="e")
        srow = ttk.Frame(stats_lf); srow.pack(fill="x", pady=4)
        ttk.Button(srow, text="🔄 تحديث الإحصائيات",
                   command=self._results_refresh_stats).pack(side="right", padx=4)
        ttk.Button(srow, text="🗑️ مسح جميع النتائج السابقة",
                   command=self._results_clear_all).pack(side="right", padx=4)

        self._results_refresh_stats()

    def _results_browse(self):
        path = filedialog.askopenfilename(
            title="اختر ملف PDF للنتائج",
            filetypes=[("PDF files","*.pdf")])
        if path:
            self.results_path_var.set(path)

    def _results_import(self):
        path = self.results_path_var.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("تنبيه","اختر ملف PDF أولاً"); return

        self.results_status.config(
            text="⏳ جارٍ فهرسة الشهادات... قد يستغرق دقيقة",
            foreground="#1565C0")
        self.root.update_idletasks()

        import threading as _th
        year = self.results_year_var.get().strip()

        def _run():
            try:
                client = get_cloud_client()
                if client.is_active():
                    # وضع الربط السحابي: ارفع الملف للسيرفر ودعه يقوم بالتنقية والفهرسة
                    self.root.after(0, lambda: self.results_status.config(text="☁️ جارٍ رفع الملف للسيرفر للمزامنة..."))
                    res = client.upload("/web/api/upload-results", path, data={"year": year})
                    
                    if res.get("ok"):
                        def _done():
                            count = res.get("count", 0)
                            self.results_status.config(
                                text=f"✅ تم الرفع والمزامنة — تم فهرسة {count} شهادة على السيرفر",
                                foreground="#2E7D32")
                            self._results_refresh_stats()
                        self.root.after(0, _done)
                        return
                    else:
                        raise Exception(res.get("msg", "فشل الرفع للسيرفر"))

                # الوضع المحلي: فهرسة يدوية
                results_dir = os.path.join(DATA_DIR, "results")
                os.makedirs(results_dir, exist_ok=True)
                shared_pdf = os.path.join(results_dir, f"results_{year or 'current'}.pdf")
                try:
                    import shutil as _sh
                    if os.path.abspath(path) != os.path.abspath(shared_pdf):
                        _sh.copy2(path, shared_pdf)
                    parse_path = shared_pdf
                except Exception as _ce:
                    print(f"[RESULTS] تعذّر نسخ PDF للمشاركة: {_ce}")
                    parse_path = path

                students = parse_results_pdf(parse_path)
                inserted, _ = save_results_to_db(students, year)
                def _done():
                    self.results_status.config(
                        text="✅ تم فهرسة {} شهادة — متاحة في التطبيق والويب".format(len(students)),
                        foreground="#2E7D32")
                    self._results_refresh_stats()
                self.root.after(0, _done)
            except Exception as e:
                import traceback
                full_err = traceback.format_exc()
                print("[RESULTS ERROR]", full_err)
                def _err(msg=str(e), tb=full_err):
                    self.results_status.config(
                        text="❌ خطأ: {}".format(msg),
                        foreground="#C62828")
                    messagebox.showerror("تفاصيل الخطأ", tb)
                self.root.after(0, _err)

        _th.Thread(target=_run, daemon=True).start()

    def _results_refresh_stats(self):
        if not hasattr(self,"results_stats_lbl"): return
        try:
            con = sqlite3.connect(DB_PATH); cur = con.cursor()
            cur.execute("SELECT COUNT(*) as c, MAX(uploaded_at) as last FROM student_results")
            row = cur.fetchone(); con.close()
            count = row[0] if row else 0
            last  = (row[1] or "")[:16].replace("T"," ") if row and row[1] else "—"
            self.results_stats_lbl.config(
                text="إجمالي الطلاب المنشورة نتائجهم: {}  |  آخر تحديث: {}".format(
                    count, last))
        except Exception as e:
            self.results_stats_lbl.config(text="خطأ: {}".format(e))

    def _results_clear_all(self):
        if not messagebox.askyesno("تأكيد المَسح",
            "🔴 هل أنت متأكد من رغبتك في حذف جميع نتائج الطلاب المنشورة سابقاً؟\n\nلا يمكن التراجع عن هذه الخطوة."):
            return
            
        try:
            from database import clear_student_results
            clear_student_results()
            messagebox.showinfo("تم", "✅ تم مسح جميع النتائج بنجاح.")
            self._results_refresh_stats()
            # تحديث الحالة أيضاً
            self.results_status.config(text="تم مسح النتائج السابقة — بانتظار رفع ملف جديد", foreground="#5A6A7E")
        except Exception as e:
            messagebox.showerror("خطأ", f"تعذر المسح: {e}")


    def _build_license_tab(self):
        frame = self.license_frame

        hdr = tk.Frame(frame, bg="#1565C0", height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🔐 معلومات الترخيص",
                 bg="#1565C0", fg="white",
                 font=("Tahoma",12,"bold")).pack(side="right", padx=14, pady=12)

        body = ttk.Frame(frame); body.pack(fill="both", expand=True, padx=20, pady=16)

        # ─ حالة الترخيص الحالية
        lf = ttk.LabelFrame(body, text=" حالة الترخيص ", padding=14)
        lf.pack(fill="x", pady=(0,14))

        self.lic_status_lbl = ttk.Label(lf, text="", font=("Tahoma",11,"bold"))
        self.lic_status_lbl.pack(anchor="e", pady=(0,6))
        self.lic_school_lbl = ttk.Label(lf, text="", foreground="#5A6A7E")
        self.lic_school_lbl.pack(anchor="e", pady=(0,4))
        self.lic_expiry_lbl = ttk.Label(lf, text="", foreground="#5A6A7E")
        self.lic_expiry_lbl.pack(anchor="e", pady=(0,4))
        self.lic_machine_lbl = ttk.Label(lf, text="", foreground="#9CA3AF",
                                          font=("Tahoma",8))
        self.lic_machine_lbl.pack(anchor="e")

        self._refresh_license_status()

        ttk.Button(lf, text="🔄 تحديث الحالة",
                   command=self._refresh_license_status).pack(side="left", pady=(8,0))

        # ─ إدخال مفتاح جديد
        renew_lf = ttk.LabelFrame(body, text=" تجديد / تفعيل مفتاح جديد ", padding=14)
        renew_lf.pack(fill="x")

        ttk.Label(renew_lf, text="مفتاح الترخيص:").pack(anchor="e", pady=(0,4))
        self.lic_key_var = tk.StringVar()
        key_entry = ttk.Entry(renew_lf, textvariable=self.lic_key_var,
                               width=36, justify="center",
                               font=("Tahoma",10))
        key_entry.pack(pady=4, ipady=4)

        self.lic_act_status = ttk.Label(renew_lf, text="")
        self.lic_act_status.pack(pady=(4,8))

        def do_activate():
            key = self.lic_key_var.get().strip()
            if not key:
                self.lic_act_status.config(text="أدخل المفتاح أولاً", foreground="#C62828")
                return
            self.lic_act_status.config(text="⏳ جارٍ التفعيل...", foreground="#1565C0")
            frame.update_idletasks()
            import threading as _th
            def _run():
                ok, msg = activate_license(key)
                def _done():
                    if ok:
                        self.lic_act_status.config(text="✅ " + msg, foreground="#2E7D32")
                        self._refresh_license_status()
                    else:
                        self.lic_act_status.config(text="❌ " + msg, foreground="#C62828")
                self.root.after(0, _done)
            _th.Thread(target=_run, daemon=True).start()

        ttk.Button(renew_lf, text="✅ تفعيل / تجديد",
                   command=do_activate).pack()

    def _refresh_license_status(self):
        if not hasattr(self,"lic_status_lbl"): return
