# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
from constants import DATA_DIR, STUDENTS_JSON
from database import load_students, import_students_from_excel_sheet2_format, save_students
from config_manager import load_config

class StudentsTabMixin:
    """Mixin: StudentsTabMixin"""
    def _build_student_management_tab(self):
        top_frame = ttk.Frame(self.student_management_frame); top_frame.pack(fill="x", pady=(8, 8))
        ttk.Label(top_frame, text="بحث:").pack(side="left", padx=(0, 5))
        self.student_search_var = tk.StringVar()
        ttk.Entry(top_frame, textvariable=self.student_search_var, width=30).pack(side="left", padx=5)
        ttk.Button(top_frame, text="بحث", command=self.search_students_for_management).pack(side="left", padx=5)
        ttk.Button(top_frame, text="مسح", command=self.clear_student_search).pack(side="left", padx=5)
        ttk.Button(top_frame, text="حفظ التعديلات", command=self.save_student_class_edits).pack(side="right", padx=5)
        cols = ("student_id", "student_name", "current_class", "new_class")
        self.tree_student_management = ttk.Treeview(self.student_management_frame, columns=cols, show="headings", height=15)
        for col, header, w in zip(cols, ["رقم الطالب", "اسم الطالب", "الفصل الحالي", "الفصل الجديد"], [120, 250, 200, 200]):
            self.tree_student_management.heading(col, text=header); self.tree_student_management.column(col, width=w, anchor="center")
        self.tree_student_management.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree_student_management.bind("<Double-1>", self.on_double_click_student_class)
                # أزرار الحذف
        delete_frame = ttk.Frame(top_frame)
        delete_frame.pack(side="right", padx=10)
        ttk.Button(delete_frame, text="🗑️ حذف الطالب المحدد", command=self.delete_selected_student).pack(pady=2)
        ttk.Button(delete_frame, text="🗑️ حذف فصل محدد", command=self.delete_selected_class).pack(pady=2)
        
        self.load_students_to_management_treeview()

    def load_students_to_management_treeview(self):
        if not hasattr(self, "tree_student_management"): return
        for item in self.tree_student_management.get_children():
            self.tree_student_management.delete(item)
        self.all_students_class_data = []
        for c in self.store["list"]:
            for s in c["students"]:
                self.all_students_class_data.append({"student_id": s.get("id", ""), "student_name": s.get("name", ""), "current_class_id": c["id"], "current_class_name": c["name"]})
        self.display_students_for_management(self.all_students_class_data)

    def display_students_for_management(self, students_list):
        all_class_names = [c["name"] for c in self.store["list"]]
        for student in students_list:
            self.tree_student_management.insert("", "end", values=(student["student_id"], student["student_name"], student["current_class_name"], student["current_class_name"]))
        self.all_class_names_for_student_mng = all_class_names

    def on_double_click_student_class(self, event):
        # تحديد العمود المخطوط للتمييز بين فتح التحليل وتعديل الفصل
        region = self.tree_student_management.identify("region", event.x, event.y)
        if region != "cell":
            return
            
        column = self.tree_student_management.identify_column(event.x) # "#1", "#2", etc.
        item_id = self.tree_student_management.focus()
        if not item_id: return
        
        current_values = list(self.tree_student_management.item(item_id, "values"))
        student_id = current_values[0]

        # إذا كان الضغط على خانة "الفصل الجديد" (#4)، نقوم بتفعيل التعديل
        if column == "#4":
            combo = ttk.Combobox(self.tree_student_management, values=self.all_class_names_for_student_mng, state="readonly"); combo.set(current_values[3]); combo.focus()
            if not (bbox := self.tree_student_management.bbox(item_id, column="#4")): return
            combo.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
            def save_edit(e=None):
                selected_class = combo.get(); current_values[3] = selected_class
                self.tree_student_management.item(item_id, values=current_values); combo.destroy()
            combo.bind("<<ComboboxSelected>>", save_edit); combo.bind("<FocusOut>", save_edit); combo.bind("<Escape>", lambda e: combo.destroy())
        else:
            # إذا كان الضغط على أي خانة أخرى (مثل الاسم أو الهوية)، نفتح تبويب التحليل
            if hasattr(self, "open_student_analysis"):
                self.open_student_analysis(student_id)

    def search_students_for_management(self):
        query = self.student_search_var.get().strip().lower()
        filtered = [s for s in self.all_students_class_data if not query or query in str(s["student_id"]).lower() or query in str(s["student_name"]).lower()]
        for item in self.tree_student_management.get_children():
            self.tree_student_management.delete(item)
        self.display_students_for_management(filtered)

    def clear_student_search(self):
        self.student_search_var.set("")
        self.search_students_for_management()

    def save_student_class_edits(self):
        changes_made = False
        for item in self.tree_student_management.get_children():
            values = self.tree_student_management.item(item, "values")
            student_id, current_class_name, new_class_name = values[0], values[2], values[3]
            if current_class_name != new_class_name:
                changes_made = True
                student_data = None; old_class_index = -1
                for i, c in enumerate(self.store["list"]):
                    for j, s in enumerate(c["students"]):
                        if s.get("id") == student_id:
                            student_data = c["students"].pop(j)
                            old_class_index = i
                            break
                    if student_data: break
                
                if not student_data: continue

                new_class_found = False
                for c in self.store["list"]:
                    if c["name"] == new_class_name:
                        c["students"].append(student_data)
                        new_class_found = True
                        break
                
                if not new_class_found:
                    self.store["list"][old_class_index]["students"].append(student_data)

        if changes_made:
            with open(STUDENTS_JSON, "w", encoding="utf-8") as f:
                json.dump({"classes": self.store["list"]}, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("تم الحفظ", "تم نقل الطلاب وحفظ التعديلات بنجاح.")
            self.update_all_tabs_after_data_change()
        else:
            messagebox.showinfo("لا توجد تغييرات", "لم يتم إجراء أي تغييرات على فصول الطلاب.")

    def delete_selected_student(self):
        from constants import CURRENT_USER, STUDENTS_JSON
        from database import authenticate
        from tkinter import simpledialog
        import json

        if CURRENT_USER.get("role") not in ["admin", "deputy"]:
            messagebox.showerror("صلاحيات غير كافية", "هذا الإجراء متاح للمدير والوكيل فقط.")
            return

        sel = self.tree_student_management.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "حدد الطالب الذي تريد حذفه.")
            return

        values = self.tree_student_management.item(sel[0], "values")
        student_id = values[0]
        student_name = values[1]

        if not messagebox.askyesno("تأكيد الحذف", f"هل أنت متأكد من حذف الطالب:\n{student_name}؟", icon="warning"):
            return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        student_removed = False
        for c in self.store["list"]:
            for j, s in enumerate(c["students"]):
                if s.get("id") == student_id:
                    del c["students"][j]
                    student_removed = True
                    break
            if student_removed:
                break
        
        if student_removed:
            if save_students(self.store["list"]):
                messagebox.showinfo("تم الحذف", f"تم حذف الطالب {student_name} بنجاح.")
                self.update_all_tabs_after_data_change()
            else:
                messagebox.showerror("خطأ", "فشل في حفظ التعديلات أو مزامنتها مع السيرفر.")

    def delete_selected_class(self):
        from constants import CURRENT_USER, STUDENTS_JSON
        from database import authenticate
        from tkinter import simpledialog
        import json

        if CURRENT_USER.get("role") != "admin":
            messagebox.showerror("صلاحيات غير كافية", "هذا الإجراء متاح لمدير النظام فقط.")
            return

        sel = self.tree_student_management.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "الرجاء تحديد طالب من الفصل الذي تريد حذفه أولاً.")
            return

        values = self.tree_student_management.item(sel[0], "values")
        class_name = values[2]  # current_class

        if not messagebox.askyesno("تأكيد حذف الفصل", f"هل أنت متأكد من حذف الفصل بالكامل ({class_name}) وجميع طلابه؟\nهذا الإجراء لا يمكن التراجع عنه.", icon="warning"):
            return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك للمتابعة:", show="*")
        if not pw:
            return
            
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        class_index = -1
        for i, c in enumerate(self.store["list"]):
            if c["name"] == class_name:
                class_index = i
                break
        
        if class_index != -1:
            del self.store["list"][class_index]
            if save_students(self.store["list"]):
                messagebox.showinfo("تم الحذف", f"تم حذف الفصل '{class_name}' بنجاح.")
                self.update_all_tabs_after_data_change()
            else:
                messagebox.showerror("خطأ", "فشل في حفظ التعديلات أو مزامنتها مع السيرفر.")

