# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
import sqlite3
from constants import now_riyadh_date, CURRENT_USER
from database import get_db, query_absences, _apply_class_name_fix, EXCUSE_REASONS

try:
    from tkcalendar import DateEntry
except ImportError:
    DateEntry = None

class AbsenceTabMixin:
    """Mixin: AbsenceTabMixin"""
    def _build_logs_tab(self):
        top = ttk.Frame(self.logs_frame); top.pack(fill="x", pady=(0,8))
        ttk.Label(top, text="تاريخ:").pack(side="right")
        self.date_var = tk.StringVar(value=now_riyadh_date())
        ttk.Entry(top, textvariable=self.date_var, width=12).pack(side="right", padx=5)
        ttk.Label(top, text="فصل:").pack(side="right")
        self.class_var = tk.StringVar()
        class_ids = ["(الكل)"] + [c["id"] for c in self.store["list"]]
        cb = ttk.Combobox(top, textvariable=self.class_var, values=class_ids, width=12, state="readonly"); cb.current(0); cb.pack(side="right", padx=5)
        ttk.Button(top, text="تحديث", command=self.refresh_logs).pack(side="right", padx=5)
        ttk.Button(top, text="تقرير رسائل اليوم", command=self._open_today_messages_report).pack(side="left", padx=5)

        cols = ("date","class_id","class_name","student_id","student_name","teacher_name","period","created_at")
        tree = ttk.Treeview(self.logs_frame, columns=cols, show="headings", height=12)
        for c,h,w in zip(cols, ["التاريخ","المعرّف","الفصل","رقم الطالب","اسم الطالب","المعلم","الحصة","وقت التسجيل"], [90,90,200,120,240,140,60,170]):
            tree.heading(c, text=h); tree.column(c, width=w, anchor="center")
        tree.pack(fill="both", expand=True); self.tree_logs = tree
        self.tree_logs.bind("<Double-1>", self._on_log_dblclick)
        self.refresh_logs()

    def _on_log_dblclick(self, event):
        item = self.tree_logs.focus()
        if not item: return
        vals = self.tree_logs.item(item, "values")
        student_name = vals[4]
        # التبديل لتبويب التقارير للبحث عن هذا الطالب
        self._switch_tab("التقارير / الطباعة")
        if hasattr(self, "report_student_var"):
            self.report_type_var.set("student")
            self._update_report_controls()
            self.report_student_var.set(student_name)
            self.on_generate_report()

    def _open_today_messages_report(self):
        from alerts_service import query_today_messages, build_daily_summary_message
        msgs = query_today_messages()
        if not msgs:
            messagebox.showinfo("تنبيه", "لا توجد رسائل مرسلة اليوم حتى الآن."); return
        summary = build_daily_summary_message()
        win = tk.Toplevel(self.root); win.title("تقرير رسائل اليوم"); win.geometry("600x500")
        txt = tk.Text(win, font=("Tahoma", 10)); txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", summary); txt.config(state="disabled")

    def refresh_logs(self):
        try:
            date_f = self.date_var.get().strip() if hasattr(self, "date_var") else now_riyadh_date()
            class_id = self.class_var.get() if hasattr(self, "class_var") else None
            if class_id == "(الكل)":
                class_id = None

            rows = _apply_class_name_fix(query_absences(date_f or None, class_id))

            if not hasattr(self, "tree_logs"):
                return

            for i in self.tree_logs.get_children():
                self.tree_logs.delete(i)

            for r in rows:
                self.tree_logs.insert(
                    "", "end",
                    values=(
                        r.get("date", ""),
                        r.get("class_id", ""),
                        r.get("class_name", ""),
                        r.get("student_id", ""),
                        r.get("student_name", ""),
                        r.get("teacher_name", ""),
                        r.get("period", ""),
                        r.get("created_at", "")
                    )
                )
        except Exception as e:
            messagebox.showerror("خطأ", f"تعذر تحديث السجلات:\n{e}")

    def _build_absence_management_tab(self):
        frame = self.absence_management_frame
        controls_frame = ttk.LabelFrame(frame, text=" بحث وتعديل ", padding=10)
        controls_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(controls_frame, text="اسم الطالب أو رقمه:").pack(side="right", padx=(0, 5))
        self.absence_search_var = tk.StringVar()
        ttk.Entry(controls_frame, textvariable=self.absence_search_var, width=25).pack(side="right", padx=5)
        ttk.Label(controls_frame, text="في تاريخ:").pack(side="right", padx=(10, 5))
        self.absence_date_entry = DateEntry(controls_frame, width=12, background='darkblue', foreground='white', borderwidth=2, date_pattern='y-mm-dd', locale='ar_SA')
        self.absence_date_entry.pack(side="right", padx=5)
        search_button = ttk.Button(controls_frame, text="🔍 بحث", command=self.search_absences_for_student)
        search_button.pack(side="right", padx=10)
        self.delete_absence_button = ttk.Button(controls_frame, text="🗑️ حذف الغياب المحدد", state="disabled", command=self.delete_selected_absence)
        self.delete_absence_button.pack(side="left", padx=10)

        results_frame = ttk.Frame(frame); results_frame.pack(fill="both", expand=True, padx=10, pady=5)
        cols = ("record_id", "student_id", "student_name", "class_name", "period", "teacher_name")
        self.tree_absences = ttk.Treeview(results_frame, columns=cols, show="headings", height=15)
        for col, header, w in zip(cols, ["ID", "رقم الطالب", "اسم الطالب", "الفصل", "الحصة", "مسجل بواسطة"], [60, 100, 250, 180, 60, 150]):
            self.tree_absences.heading(col, text=header); self.tree_absences.column(col, width=w, anchor="center")
        self.tree_absences.pack(fill="both", expand=True)
        self.tree_absences.bind("<<TreeviewSelect>>", self.on_absence_record_select)

    def on_absence_record_select(self, event=None):
        if self.tree_absences.selection():
            self.delete_absence_button.config(state="normal")
        else:
            self.delete_absence_button.config(state="disabled")

    def search_absences_for_student(self):
        for item in self.tree_absences.get_children():
            self.tree_absences.delete(item)
        query = self.absence_search_var.get().strip()
        date_filter = self.absence_date_entry.get()
        if not query:
            messagebox.showwarning("تنبيه", "الرجاء إدخال اسم أو رقم الطالب للبحث.")
            return
        if not date_filter:
            messagebox.showwarning("تنبيه", "الرجاء تحديد التاريخ للبحث.")
            return
        con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
        sql_query = "SELECT id, student_id, student_name, class_name, period, teacher_name FROM absences WHERE date = ? AND (student_name LIKE ? OR student_id = ?)"
        params = (date_filter, f'%{query}%', query)
        cur.execute(sql_query, params); rows = cur.fetchall(); con.close()
        if not rows:
            messagebox.showinfo("لا توجد نتائج", f"لم يتم العثور على أي سجلات غياب للطالب '{query}' في تاريخ {date_filter}.")
        else:
            for row in rows:
                self.tree_absences.insert("", "end", values=(row['id'], row['student_id'], row['student_name'], row['class_name'], row['period'], row['teacher_name']))
        self.delete_absence_button.config(state="disabled")

    def delete_selected_absence(self):
        from database import authenticate
        from constants import CURRENT_USER
        from tkinter import simpledialog
        if not (selected_items := self.tree_absences.selection()):
            messagebox.showwarning("تنبيه", "الرجاء تحديد سجل الغياب الذي تريد حذفه أولاً.")
            return
        item_id = selected_items[0]
        record_values = self.tree_absences.item(item_id, "values")
        db_id = record_values[0]; student_name = record_values[2]; class_name = record_values[3]; period = record_values[4]
        confirmation_message = (f"هل أنت متأكد من حذف سجل الغياب التالي؟\n\nالطالب: {student_name}\nالفصل: {class_name}\nالحصة: {period}\n\nهذا الإجراء سيحول الطالب إلى 'حاضر' في هذه الحصة ولا يمكن التراجع عنه.")
        if not messagebox.askyesno("تأكيد الحذف", confirmation_message): return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return
        try:
            con = get_db(); cur = con.cursor()
            cur.execute("DELETE FROM absences WHERE id = ?", (db_id,)); con.commit(); con.close()
            self.tree_absences.delete(item_id)
            messagebox.showinfo("تم الحذف", "تم حذف سجل الغياب بنجاح.")
            self.update_dashboard_metrics()
            self.delete_absence_button.config(state="disabled")
        except Exception as e:
            messagebox.showerror("خطأ", f"حدث خطأ أثناء محاولة الحذف من قاعدة البيانات:\n{e}")

