# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from database import (get_exempted_students, add_exempted_student, 
                      remove_exempted_student, load_students)
import datetime

class ExemptedTabMixin:
    """Mixin: ExemptedTabMixin لإدارة الطلاب المستثنين من الغياب والتأخر"""
    def _build_exempted_tab(self):
        main_frame = self.exempted_frame
        
        # --- الإطار العلوي: إضافة طالب ---
        top_frame = ttk.LabelFrame(main_frame, text=" إضافة طالب لقائمة الاستثناء ", padding=10)
        top_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(top_frame, text="اختر الفصل:").pack(side="left", padx=5)
        self.exempt_class_var = tk.StringVar()
        classes = [c["name"] for c in self.store.get("list", [])]
        self.exempt_class_cb = ttk.Combobox(top_frame, textvariable=self.exempt_class_var, values=classes, state="readonly", width=20)
        self.exempt_class_cb.pack(side="left", padx=5)
        self.exempt_class_cb.bind("<<ComboboxSelected>>", self._on_exempt_class_selected)
        
        ttk.Label(top_frame, text="اختر الطالب:").pack(side="left", padx=5)
        self.exempt_student_var = tk.StringVar()
        self.exempt_student_cb = ttk.Combobox(top_frame, textvariable=self.exempt_student_var, state="readonly", width=30)
        self.exempt_student_cb.pack(side="left", padx=5)
        
        ttk.Label(top_frame, text="السبب:").pack(side="left", padx=5)
        self.exempt_reason_var = tk.StringVar()
        ttk.Entry(top_frame, textvariable=self.exempt_reason_var, width=30).pack(side="left", padx=5)
        
        ttk.Button(top_frame, text="➕ إضافة للقائمة", command=self._add_exempted_student_ui).pack(side="left", padx=10)

        # --- الإطار الأوسط: القائمة ---
        list_frame = ttk.LabelFrame(main_frame, text=" قائمة الطلاب المستثنين حالياً ", padding=10)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        cols = ("id", "name", "class", "reason", "date")
        self.tree_exempted = ttk.Treeview(list_frame, columns=cols, show="headings", height=15)
        for col, head, w in zip(cols, ["رقم الطالب", "اسم الطالب", "الفصل", "السبب / الملاحظات", "تاريخ الإضافة"], [100, 200, 150, 250, 150]):
            self.tree_exempted.heading(col, text=head)
            self.tree_exempted.column(col, width=w, anchor="center")
        
        self.tree_exempted.pack(fill="both", expand=True, side="left")
        
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree_exempted.yview)
        sb.pack(fill="y", side="right")
        self.tree_exempted.configure(yscrollcommand=sb.set)
        
        # --- الإطار السفلي: إجراءات ---
        btn_frame = ttk.Frame(main_frame, padding=5)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        ttk.Button(btn_frame, text="🗑️ حذف الطالب المحدد من القائمة", command=self._remove_exempted_student_ui).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="🔄 تحديث القائمة", command=self.load_exempted_students_list).pack(side="right", padx=5)
        
        self.load_exempted_students_list()

    def _on_exempt_class_selected(self, event=None):
        cls_name = self.exempt_class_var.get()
        students = []
        for c in self.store.get("list", []):
            if c["name"] == cls_name:
                students = ["{} | {}".format(s["id"], s["name"]) for s in c.get("students", [])]
                break
        self.exempt_student_cb["values"] = students
        if students: self.exempt_student_cb.current(0)
        else: self.exempt_student_var.set("")

    def _add_exempted_student_ui(self):
        st_val = self.exempt_student_var.get()
        if not st_val or "|" not in st_val:
            messagebox.showwarning("تنبيه", "الرجاء اختيار الطالب أولاً.")
            return
        
        sid, sname = st_val.split("|")[0].strip(), st_val.split("|")[1].strip()
        reason = self.exempt_reason_var.get().strip()
        cls_name = self.exempt_class_var.get()
        
        try:
            add_exempted_student(sid, sname, cls_name, reason)
            messagebox.showinfo("تم", "تمت إضافة الطالب لقائمة الاستثناء بنجاح.")
            self.exempt_reason_var.set("")
            self.load_exempted_students_list()
        except Exception as e:
            messagebox.showerror("خطأ", str(e))

    def _remove_exempted_student_ui(self):
        sel = self.tree_exempted.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "الرجاء تحديد الطالب من القائمة.")
            return
        
        sid = self.tree_exempted.item(sel[0], "values")[0]
        sname = self.tree_exempted.item(sel[0], "values")[1]
        
        if messagebox.askyesno("تأكيد", "هل أنت متأكد من إزالة الطالب ({}) من قائمة الاستثناء؟".format(sname)):
            remove_exempted_student(sid)
            self.load_exempted_students_list()

    def load_exempted_students_list(self):
        for item in self.tree_exempted.get_children():
            self.tree_exempted.delete(item)
        
        rows = get_exempted_students()
        for r in rows:
            dt = r["created_at"].split("T")[0] if "T" in r["created_at"] else r["created_at"]
            self.tree_exempted.insert("", "end", values=(
                r["student_id"], r["student_name"], r["class_name"], r["reason"], dt
            ))
