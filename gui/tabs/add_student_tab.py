# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
from constants import DATA_DIR, STUDENTS_JSON
from database import load_students, save_students, import_students_from_excel_sheet2_format
from config_manager import load_config

class AddStudentTabMixin:
    """Mixin: AddStudentTabMixin"""
    def _build_add_student_tab(self):
        frame = self.add_student_frame

    # الحقول
        ttk.Label(frame, text="الاسم الكامل:").grid(row=0, column=1, padx=10, pady=10, sticky="e")
        self.add_name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.add_name_var, width=40).grid(row=0, column=0, padx=10, pady=10, sticky="w")
    
        ttk.Label(frame, text="الرقم الأكاديمي:").grid(row=1, column=1, padx=10, pady=10, sticky="e")
        self.add_id_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.add_id_var, width=40).grid(row=1, column=0, padx=10, pady=10, sticky="w")
    
        ttk.Label(frame, text="رقم الجوال (اختياري):").grid(row=2, column=1, padx=10, pady=10, sticky="e")
        self.add_phone_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.add_phone_var, width=40).grid(row=2, column=0, padx=10, pady=10, sticky="w")
    
        ttk.Label(frame, text="الفصل:").grid(row=3, column=1, padx=10, pady=10, sticky="e")
        self.add_class_var = tk.StringVar()
        class_names = [c["name"] for c in self.store["list"]]
        self.add_class_combo = ttk.Combobox(frame, textvariable=self.add_class_var, values=class_names, state="readonly", width=37)
        self.add_class_combo.grid(row=3, column=0, padx=10, pady=10, sticky="w")

    # زر الإضافة
        ttk.Button(frame, text="➕ إضافة الطالب", command=self.add_new_student).grid(row=4, column=0, columnspan=2, pady=20)

    # رسالة الحالة
        self.add_status_label = ttk.Label(frame, text="")
        self.add_status_label.grid(row=5, column=0, columnspan=2, pady=10)       

    def add_new_student(self):
        name = self.add_name_var.get().strip()
        student_id = self.add_id_var.get().strip()
        phone = self.add_phone_var.get().strip()
        class_name = self.add_class_var.get().strip()
    
        if not name or not student_id or not class_name:
            messagebox.showwarning("بيانات ناقصة", "الرجاء تعبئة الاسم، الرقم الأكاديمي، والفصل.")
            return
    
        # البحث عن class_id من الاسم
        target_class = None
        for c in self.store["list"]:
            if c["name"] == class_name:
                target_class = c
                break
        if not target_class:
            messagebox.showerror("خطأ", "الفصل المحدد غير موجود.")
            return

    # التحقق من التكرار
        for c in self.store["list"]:
            for s in c["students"]:
                if s.get("id") == student_id:
                    messagebox.showerror("تكرار", f"الرقم الأكاديمي '{student_id}' مستخدم مسبقًا.")
                    return

    # إضافة الطالب
        new_student = {"id": student_id, "name": name, "phone": phone}
        target_class["students"].append(new_student)

    # حفظ
        if save_students(self.store["list"]):
            messagebox.showinfo("تم", "تمت إضافة الطالب بنجاح!")
            self.add_status_label.config(text="✅ تم الحفظ", foreground="green")
            # مسح الحقول
            self.add_name_var.set("")
            self.add_id_var.set("")
            self.add_phone_var.set("")
            self.add_class_var.set("")
            # تحديث باقي التبويبات
            self.update_all_tabs_after_data_change()
        else:
            messagebox.showerror("خطأ", "فشل في حفظ التعديلات أو مزامنتها مع السيرفر.")
            
    def delete_selected_student(self):
        from database import authenticate
        from constants import CURRENT_USER
        if not (selection := self.tree_student_management.selection()):
            messagebox.showwarning("تنبيه", "الرجاء تحديد طالب من القائمة أولاً.")
            return
        values = self.tree_student_management.item(selection[0], "values")
        student_id = values[0]
        student_name = values[1]
        if not messagebox.askyesno("تأكيد الحذف", f"هل أنت متأكد من حذف الطالب:\nالاسم: {student_name}\nالرقم: {student_id}\n\nلا يمكن التراجع عن هذا الإجراء!"):
            return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

    # ← ابدأ المسافة البادئة هنا (4 مسافات)
        store = load_students(force_reload=True)
        classes = store.get("list", [])
        found = False
        for c in classes:
            for i, s in enumerate(c.get("students", [])):
                if s.get("id") == student_id:
                    del c["students"][i]
                    found = True
                    break
            if found:
                break

        if not found:
            messagebox.showerror("خطأ", "الطالب غير موجود في البيانات!")
            return

        if save_students(classes):
            messagebox.showinfo("تم", "تم حذف الطالب بنجاح.")
            self.update_all_tabs_after_data_change()
        else:
            messagebox.showerror("خطأ", "فشل في حفظ التعديلات أو مزامنتها مع السيرفر.")

    def delete_selected_class(self):
        from database import authenticate
        from constants import CURRENT_USER
        class_names = [c["name"] for c in self.store["list"]]
        class_name = simpledialog.askstring("حذف فصل", "اكتب اسم الفصل الذي تريد حذفه بالضبط:", parent=self.root)
        if not class_name:
            return
        if class_name not in class_names:
            messagebox.showerror("خطأ", "اسم الفصل غير موجود!")
            return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return
    
        class_id = next(c["id"] for c in self.store["list"] if c["name"] == class_name)
        student_count = len(next(c["students"] for c in self.store["list"] if c["id"] == class_id))
    
        if not messagebox.askyesno("تأكيد الحذف", f"تحذير: سيتم حذف الفصل '{class_name}' وجميع طلابه ({student_count} طالب)!\nهل أنت متأكد؟"):
            return

        new_classes = [c for c in self.store["list"] if c["id"] != class_id]
        if save_students(new_classes):
            messagebox.showinfo("تم", f"تم حذف الفصل '{class_name}' بنجاح.")
            self.update_all_tabs_after_data_change()
        else:
            messagebox.showerror("خطأ", "فشل في حفظ التعديلات أو مزامنتها مع السيرفر.")

