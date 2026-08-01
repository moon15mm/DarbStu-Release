# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time, webbrowser
from constants import now_riyadh_date, DATA_DIR
from report_builder import (export_to_noor_excel, generate_daily_report,
                             generate_monthly_report, generate_student_report,
                             generate_weekly_report, generate_term_report_html,
                             parent_portal_html)
from database import load_students

from gui.lib_loader import HtmlFrame

class ReportsTabMixin:
    """Mixin: ReportsTabMixin"""
    def _build_reports_tab(self):
        controls_frame = ttk.LabelFrame(self.reports_frame, text="خيارات التقرير", padding=10)
        controls_frame.pack(fill="x", padx=5, pady=5)
        self.report_type_var = tk.StringVar(value="daily")
        types_frame = ttk.Frame(controls_frame); types_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(types_frame, text="نوع التقرير:").pack(side="right", padx=(0, 10))
        report_types = [("يومي", "daily"), ("أسبوعي", "weekly"), ("شهري", "monthly"), ("طالب محدد", "student")]
        for text, value in report_types:
            ttk.Radiobutton(types_frame, text=text, variable=self.report_type_var, value=value, command=self._update_report_controls).pack(side="right", padx=5)
        self.inputs_frame = ttk.Frame(controls_frame); self.inputs_frame.pack(fill="x", pady=5)
        self.report_date_label = ttk.Label(self.inputs_frame, text="تاريخ:")
        self.report_date_var = tk.StringVar(value=now_riyadh_date())
        self.report_date_entry = ttk.Entry(self.inputs_frame, textvariable=self.report_date_var, width=15)
        self.report_class_label = ttk.Label(self.inputs_frame, text="الفصل:")
        self.report_class_var = tk.StringVar()
        class_ids = ["(كل الفصول)"] + [c["id"] for c in self.store["list"]]
        self.report_class_combo = ttk.Combobox(self.inputs_frame, textvariable=self.report_class_var, values=class_ids, width=15, state="readonly")
        self.report_class_combo.current(0)
        self.report_student_label = ttk.Label(self.inputs_frame, text="ابحث عن الطالب (بالاسم أو الرقم):")
        self.report_student_var = tk.StringVar()
        self.report_student_entry = ttk.Entry(self.inputs_frame, textvariable=self.report_student_var, width=30)
        
        buttons_frame = ttk.Frame(controls_frame)
        buttons_frame.pack(pady=5)
        ttk.Button(buttons_frame, text="إنشاء التقرير", command=self.on_generate_report).pack(side="right", padx=5)
        self.print_button = ttk.Button(buttons_frame, text="طباعة التقرير الحالي", command=self.on_print_report, state="disabled")
        self.print_button.pack(side="right", padx=5)
        
        ttk.Button(buttons_frame, text="📤 تصدير لـ نور", command=self.export_to_noor_from_ui).pack(side="right", padx=5)

        view_frame = ttk.LabelFrame(self.reports_frame, text="عرض التقرير", padding=10)
        view_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.report_browser = HtmlFrame(view_frame, horizontal_scrollbar="auto", messages_enabled=False)
        self.report_browser.pack(fill="both", expand=True)
        self.report_browser.load_html("<html><body style='font-family:sans-serif; text-align:center; color:#888;'><h1>جاهز لإنشاء التقارير</h1><p>اختر نوع التقرير من الأعلى ثم اضغط على 'إنشاء التقرير'</p></body></html>")
        self._update_report_controls()

    def _update_report_controls(self):
        for widget in [self.report_date_label, self.report_date_entry, self.report_class_label, self.report_class_combo, self.report_student_label, self.report_student_entry]:
            widget.pack_forget()
        report_type = self.report_type_var.get()
        if report_type in ["daily", "weekly", "monthly"]:
            self.report_date_label.pack(side="right", padx=(0, 5))
            self.report_date_entry.pack(side="right", padx=5)
            self.report_class_label.pack(side="right", padx=(15, 5))
            self.report_class_combo.pack(side="right", padx=5)
            if report_type == "daily": self.report_date_label.config(text="تاريخ اليوم:")
            elif report_type == "weekly": self.report_date_label.config(text="أي يوم في الأسبوع:")
            elif report_type == "monthly": self.report_date_label.config(text="أي يوم في الشهر:")
        elif report_type == "student":
            self.report_student_label.pack(side="right", padx=(0, 5))
            self.report_student_entry.pack(side="right", padx=5)

    def on_generate_report(self):
        report_type = self.report_type_var.get()
        html_content = ""
        self.current_report_html = "" 
        try:
            self.root.config(cursor="wait"); self.root.update_idletasks()
            class_id_filter = self.report_class_var.get()
            if class_id_filter == "(كل الفصول)": class_id_filter = None
            if report_type == "student":
                search_query = self.report_student_var.get().strip()
                if not search_query:
                    messagebox.showwarning("بيانات ناقصة", "الرجاء إدخال اسم أو رقم الطالب للبحث عنه.")
                    return
                found_student = None
                for c in self.store['list']:
                    for s in c['students']:
                        if search_query.lower() in s['name'].lower() or search_query == s['id']:
                            found_student = s
                            break
                    if found_student: break
                
                # --- START: هذا هو السطر الذي تم إصلاحه ---
                if not found_student:
                    messagebox.showerror("غير موجود", f"لم يتم العثور على طالب يطابق البحث: '{search_query}'")
                    return
                # --- END: هذا هو السطر الذي تم إصلاحه ---

                if not messagebox.askyesno("تأكيد", f"هل تريد إنشاء تقرير للطالب:\n\nالاسم: {found_student['name']}\nالرقم: {found_student['id']}"):
                    return
                html_content = generate_student_report(found_student['id'])
            else:
                date_str = self.report_date_var.get()
                if not date_str:
                    messagebox.showerror("خطأ", "الرجاء إدخال تاريخ صالح.")
                    return
                if report_type == "daily":
                    html_content = generate_daily_report(date_str, class_id_filter)
                elif report_type == "weekly":
                    html_content = generate_weekly_report(date_str, class_id_filter)
                elif report_type == "monthly":
                    html_content = generate_monthly_report(date_str, class_id_filter)
            
            if html_content and "لا توجد بيانات" not in html_content:
                self.current_report_html = html_content
                self.report_browser.load_html(html_content)
                self.print_button.config(state="normal")
            else:
                self.current_report_html = ""
                self.report_browser.load_html(html_content or "<html><body><h2>لم يتم إنشاء التقرير أو لا توجد بيانات.</h2></body></html>")
                self.print_button.config(state="disabled")
        except Exception as e:
            messagebox.showerror("خطأ فادح", f"حدث خطأ أثناء إنشاء التقرير:\n{e}")
            self.print_button.config(state="disabled")
        finally:
            self.root.config(cursor="")


    def on_print_report(self):
        if not hasattr(self, 'current_report_html') or not self.current_report_html:
            messagebox.showwarning("لا يوجد تقرير", "الرجاء إنشاء تقرير أولاً قبل محاولة الطباعة.")
            return
        
        try:
            temp_report_path = os.path.join(DATA_DIR, "temp_report_to_print.html")
            with open(temp_report_path, "w", encoding="utf-8") as f:
                f.write(self.current_report_html)
            webbrowser.open(f"file://{os.path.abspath(temp_report_path)}")
            messagebox.showinfo("جاهز للطباعة", "تم فتح التقرير في متصفحك. الرجاء استخدام أمر الطباعة من هناك (Ctrl+P).")
        except Exception as e:
            messagebox.showerror("خطأ في تجهيز الطباعة", f"لم يتمكن من إنشاء ملف الطباعة المؤقت:\n{e}")

    def export_to_noor_from_ui(self):
        date_str = self.report_date_var.get().strip()
        if not date_str:
            messagebox.showerror("خطأ", "الرجاء تحديد تاريخ صالح.")
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            title="حفظ ملف نور"
        )
        if file_path:
            export_to_noor_excel(date_str, file_path)

