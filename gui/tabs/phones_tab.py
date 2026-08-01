# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
from constants import DATA_DIR, STUDENTS_JSON
from database import load_students
from config_manager import load_config

class PhonesTabMixin:
    """Mixin: PhonesTabMixin"""
    def _build_phones_tab(self):
        top_frame = ttk.Frame(self.phones_frame); top_frame.pack(fill="x", pady=(8, 8))
        ttk.Label(top_frame, text="بحث:").pack(side="left", padx=(0, 5)); self.search_var = tk.StringVar()
        ttk.Entry(top_frame, textvariable=self.search_var, width=30).pack(side="left", padx=5)
        ttk.Button(top_frame, text="بحث", command=self.search_students).pack(side="left", padx=5)
        ttk.Button(top_frame, text="مسح", command=self.clear_search).pack(side="left", padx=5)
        ttk.Button(top_frame, text="حفظ التعديلات", command=self.save_phone_edits).pack(side="right", padx=5)
        cols = ("student_id", "student_name", "phone", "class_name")
        self.tree_phones = ttk.Treeview(self.phones_frame, columns=cols, show="headings", height=15)
        for col, header, w in zip(cols, ["رقم الطالب", "اسم الطالب", "رقم الجوال", "الفصل"], [120, 250, 180, 200]):
            self.tree_phones.heading(col, text=header); self.tree_phones.column(col, width=w, anchor="center")
        self.tree_phones.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree_phones.bind("<Double-1>", self.on_double_click_phone)
        self.load_students_to_treeview()

    def load_students_to_treeview(self):
        if not hasattr(self, "tree_phones"): return
        for item in self.tree_phones.get_children(): self.tree_phones.delete(item)
        self.all_students_data = [{"student_id": s.get("id", ""), "student_name": s.get("name", ""), "phone": s.get("phone", ""), "class_name": c["name"]} for c in self.store["list"] for s in c["students"]]
        self.display_students(self.all_students_data)

    def display_students(self, students_list):
        for student in students_list: self.tree_phones.insert("", "end", values=(student["student_id"], student["student_name"], student["phone"], student["class_name"]))
        self.highlight_phone_numbers()

    def highlight_phone_numbers(self):
        def _is_valid_phone(phone: str) -> bool:
            """يقبل الأرقام بصيغة 05xxxxxxxx أو 966xxxxxxxxx أو +966 أو 00966."""
            d = phone.replace("+", "").replace(" ", "").replace("-", "")
            if not d.isdigit():
                return False
            if d.startswith("05") and len(d) == 10:
                return True
            if d.startswith("966") and len(d) == 12:
                return True
            if d.startswith("00966") and len(d) == 14:
                return True
            return False

        all_phones = [self.tree_phones.item(i, "values")[2].strip() for i in self.tree_phones.get_children() if self.tree_phones.item(i, "values")[2].strip()]
        phone_counts = {p: all_phones.count(p) for p in all_phones}
        for item in self.tree_phones.get_children():
            phone = self.tree_phones.item(item, "values")[2].strip()
            tags = ()
            if not phone:
                pass
            elif not _is_valid_phone(phone):
                tags = ("invalid",)
            elif phone_counts.get(phone, 0) > 1:
                tags = ("duplicate",)
            self.tree_phones.item(item, tags=tags)
        self.tree_phones.tag_configure("invalid", background="#ffebee", foreground="#c62828")
        self.tree_phones.tag_configure("duplicate", background="#e8f5e9", foreground="#2e7d32")

    def on_double_click_phone(self, event):
        if self.tree_phones.identify("region", event.x, event.y) != "cell" or self.tree_phones.identify_column(event.x) != "#3": return
        if not (item_id := self.tree_phones.focus()): return
        current_values = list(self.tree_phones.item(item_id, "values"))
        entry = ttk.Entry(self.tree_phones); entry.insert(0, current_values[2]); entry.select_range(0, tk.END); entry.focus()
        if not (bbox := self.tree_phones.bbox(item_id, column="#3")): return
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        def save_edit(e=None):
            current_values[2] = entry.get().strip(); self.tree_phones.item(item_id, values=current_values); entry.destroy(); self.highlight_phone_numbers()
        entry.bind("<Return>", save_edit); entry.bind("<FocusOut>", save_edit); entry.bind("<Escape>", lambda e: entry.destroy())

    def save_phone_edits(self):
        updated_phones = {self.tree_phones.item(i, "values")[0]: self.tree_phones.item(i, "values")[2] for i in self.tree_phones.get_children()}
        for c in self.store["list"]:
            for s in c["students"]:
                if (sid := s.get("id")) in updated_phones: s["phone"] = updated_phones[sid]
        
        from database import save_students
        if save_students(self.store["list"]):
            messagebox.showinfo("تم الحفظ", "تم حفظ أرقام الجوالات بنجاح.")
            self.load_students_to_treeview()
        else:
            messagebox.showerror("خطأ", "فشل في حفظ التعديلات أو مزامنتها مع السيرفر.")

    def search_students(self):
        query = self.search_var.get().strip().lower()
        filtered = [s for s in self.all_students_data if not query or query in str(s["student_id"]).lower() or query in str(s["student_name"]).lower()]
        for item in self.tree_phones.get_children(): self.tree_phones.delete(item)
        self.display_students(filtered)

    def clear_search(self): self.search_var.set(""); self.search_students()

