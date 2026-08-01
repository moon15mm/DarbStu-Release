# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox
import json
from constants import STUDENTS_JSON
from database import load_students, save_students

class ClassNamingTabMixin:
    """Mixin: ClassNamingTabMixin for managing school class names."""
    
    def _build_class_naming_tab(self):
        frame = self.class_naming_frame
        
        # Header
        hdr = tk.Frame(frame, bg="#E65100", height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🏫 إدارة وتسمية الفصول", 
                 bg="#E65100", fg="white", 
                 font=("Tahoma", 13, "bold")).pack(side="right", padx=16, pady=12)
        
        # Info label
        tk.Label(frame, 
                 text="هنا يمكنك تعديل أسماء الفصول (مثلاً تغيير 1/1 إلى 'أولى أول'). \nانقر نقراً مزدوجاً فوق اسم الفصل في العمود الأيمن للتعديل.",
                 font=("Tahoma", 10), fg="#444", justify="right").pack(anchor="e", padx=16, pady=10)
        
        # Main container for Treeview
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True, padx=16, pady=5)
        
        cols = ("id", "name", "student_count")
        self.tree_classes = ttk.Treeview(table_frame, columns=cols, show="headings", height=15)
        
        for col, header, width in zip(cols, ["معرّف الفصل (ID)", "اسم الفصل الحالي", "عدد الطلاب"], [150, 300, 150]):
            self.tree_classes.heading(col, text=header)
            self.tree_classes.column(col, width=width, anchor="center")
            
        self.tree_classes.pack(side="right", fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree_classes.yview)
        self.tree_classes.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        
        # Control buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", padx=16, pady=10)
        
        ttk.Button(btn_frame, text="💾 حفظ التعديلات", command=self._save_class_renames).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="🔄 تحديث القائمة", command=self._refresh_class_list).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="🗑️ حذف الفصل المحدد", command=self._delete_selected_class_direct).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="🏫 ترميز صفوف نور",
                   command=self._open_noor_levels_editor).pack(side="left", padx=5)

        # Binding
        self.tree_classes.bind("<Double-1>", self._on_class_name_double_click)
        
        self._refresh_class_list()

    def _refresh_class_list(self):
        """Loads or reloads classes from the store into the treeview."""
        if not hasattr(self, "tree_classes"): return
        
        for item in self.tree_classes.get_children():
            self.tree_classes.delete(item)
            
        # Ensure latest data
        self.store = load_students()
        
        for c in self.store["list"]:
            self.tree_classes.insert("", "end", values=(c["id"], c["name"], len(c["students"])))

    def _on_class_name_double_click(self, event):
        """Allows in-place editing of the class name cell."""
        region = self.tree_classes.identify("region", event.x, event.y)
        if region != "cell" or self.tree_classes.identify_column(event.x) != "#2":
            return
            
        item_id = self.tree_classes.focus()
        if not item_id: return
        
        current_values = list(self.tree_classes.item(item_id, "values"))
        
        # Create an entry widget for editing
        entry = ttk.Entry(self.tree_classes)
        entry.insert(0, current_values[1])
        entry.focus()
        
        bbox = self.tree_classes.bbox(item_id, column="#2")
        if not bbox: return
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        
        def save_edit(e=None):
            new_name = entry.get().strip()
            if new_name:
                current_values[1] = new_name
                self.tree_classes.item(item_id, values=current_values)
            entry.destroy()
            
        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    def _save_class_renames(self):
        """Persists all current treeview names back to STUDENTS_JSON."""
        changes = {}
        for item in self.tree_classes.get_children():
            vals = self.tree_classes.item(item, "values")
            changes[str(vals[0])] = str(vals[1])
            
        if not changes: return
        
        updated = False
        for c in self.store["list"]:
            cid = str(c["id"])
            if cid in changes and c["name"] != changes[cid]:
                c["name"] = changes[cid]
                updated = True
                
        if updated:
            if save_students(self.store["list"]):
                messagebox.showinfo("نجاح", "تم حفظ أسماء الفصول الجديدة بنجاح.")
                self.update_all_tabs_after_data_change()
            else:
                messagebox.showerror("خطأ", "فشل في حفظ التعديلات أو مزامنتها مع السيرفر.")
        else:
            messagebox.showinfo("تنبيه", "لم يتم اكتشاف أي تغييرات في الأسماء.")

    def _delete_selected_class_direct(self):
        from constants import CURRENT_USER, STUDENTS_JSON
        from database import authenticate
        from tkinter import simpledialog
        import json

        if CURRENT_USER.get("role") != "admin":
            messagebox.showerror("صلاحيات غير كافية", "هذا الإجراء متاح لمدير النظام فقط.")
            return

        sel = self.tree_classes.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "الرجاء تحديد الفصل الذي تريد حذفه من القائمة أولاً.")
            return

        values = self.tree_classes.item(sel[0], "values")
        class_id = values[0]
        class_name = values[1]

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
            if str(c["id"]) == str(class_id):
                class_index = i
                break
        
        if class_index != -1:
            del self.store["list"][class_index]
            if save_students(self.store["list"]):
                messagebox.showinfo("تم الحذف", f"تم حذف الفصل '{class_name}' بنجاح.")
                self._refresh_class_list()
                if hasattr(self, "update_all_tabs_after_data_change"):
                    self.update_all_tabs_after_data_change()
            else:
                messagebox.showerror("خطأ", "فشل في حفظ التعديلات أو مزامنتها مع السيرفر.")

    def _open_noor_levels_editor(self):
        """مراجعة ترميز رموز نور خارج وقت الاستيراد."""
        from database import load_noor_levels, load_noor_excludes
        from gui.noor_levels_dialog import resolve_noor_levels

        levels = load_noor_levels()
        excluded = load_noor_excludes()
        # نبني نفس شكل «المجهول» ليعمل الحوار على الرموز المعروفة أيضاً
        entries = {}
        for code, info in levels.items():
            if code == "_exclude" or not isinstance(info, dict):
                continue
            entries[code] = {
                "name": info.get("name", ""),
                "count": "—",
                "sections": ["مستبعد"] if code in excluded else [],
            }
        if not entries:
            messagebox.showinfo(
                "لا يوجد ترميز",
                "لم يُستورد ملف نور بعد، فلا توجد رموز صفوف لمراجعتها.")
            return

        if resolve_noor_levels(self, entries):
            messagebox.showinfo(
                "تم الحفظ",
                "حُفظ الترميز. أعد استيراد ملف نور ليُطبَّق على الطلاب.")
