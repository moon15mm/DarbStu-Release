# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
from typing import List, Dict, Any, Optional
from constants import now_riyadh_date, CONFIG_JSON
from config_manager import DEFAULT_CONFIG, get_message_template, render_message, load_config
from alerts_service import (build_absent_groups, log_message_status,
                             query_today_messages, safe_send_absence_alert)
from whatsapp_service import send_whatsapp_message

class MessagesTabMixin:
    """Mixin: MessagesTabMixin"""
    def _build_messages_tab(self):
        self.msg_template_var = tk.StringVar(value=get_message_template())
        self.msg_date_var = tk.StringVar(value=now_riyadh_date())
        self.msg_groups = {}
        self.msg_vars = {}
        self.class_select_vars = {}
        self.global_select_var = tk.BooleanVar(value=False)

        top = ttk.Frame(self.messages_frame); top.pack(fill="x", pady=(6,6))
        ttk.Label(top, text="تاريخ الغياب:").pack(side="right", padx=(0,5))
        ttk.Entry(top, textvariable=self.msg_date_var, width=12).pack(side="right", padx=5)
        ttk.Button(top, text="تحميل الغياب", command=self._msg_load_groups).pack(side="right", padx=5)

        chk_all = ttk.Checkbutton(top, text="اختيار الجميع", variable=self.global_select_var, command=self._msg_toggle_all)
        chk_all.pack(side="right", padx=10)

        ttk.Button(top, text="تعديل نص الرسالة", command=self._msg_open_template_editor).pack(side="right", padx=5)
        ttk.Button(top, text="🔍 حالة الواتساب", command=self.check_whatsapp_status_ui).pack(side="right", padx=5)
        self.send_button = ttk.Button(top, text="إرسال للمحددين", command=self._msg_send_selected)
        self.send_button.pack(side="right", padx=5)

        status_bar = ttk.Frame(self.messages_frame); status_bar.pack(fill="x", padx=5)
        ttk.Label(status_bar, text="الحالة:").pack(side="right")
        self.status_label = ttk.Label(status_bar, text="جاهز", foreground="green")
        self.status_label.pack(side="right")

        wrapper = ttk.Frame(self.messages_frame); wrapper.pack(fill="both", expand=True, padx=5, pady=5)

        self.msg_scroll = ttk.Scrollbar(wrapper, orient="vertical")
        self.msg_scroll.pack(side="right", fill="y")

        self.msg_canvas = tk.Canvas(wrapper, yscrollcommand=self.msg_scroll.set, highlightthickness=0)
        self.msg_canvas.pack(side="left", fill="both", expand=True)

        self.msg_scroll.config(command=self.msg_canvas.yview)

        self.msg_inner = ttk.Frame(self.msg_canvas)
        self._msg_canvas_window = self.msg_canvas.create_window((0, 0), window=self.msg_inner, anchor="nw")

        self.msg_inner.bind(
            "<Configure>",
            lambda e: self.msg_canvas.configure(scrollregion=self.msg_canvas.bbox("all"))
        )

        _msg_last_w = [0]
        def _on_msg_canvas_conf(e):
            w = e.width
            if w == _msg_last_w[0]: return
            _msg_last_w[0] = w
            self.msg_canvas.itemconfigure(self._msg_canvas_window, width=w)
        self.msg_canvas.bind("<Configure>", _on_msg_canvas_conf)

        self._msg_load_groups()

    def _msg_load_groups(self):
        if not hasattr(self, "msg_inner"): return
        date_str = self.msg_date_var.get().strip()
        if not date_str:
            if self.msg_inner.winfo_children():
                 messagebox.showerror("خطأ", "الرجاء إدخال تاريخ.")
            return

        for child in self.msg_inner.winfo_children():
            child.destroy()
        self.msg_vars.clear()
        self.class_select_vars.clear()

        self.msg_groups = build_absent_groups(date_str)
        total_students = sum(len(v["students"]) for v in self.msg_groups.values())
        if not self.msg_groups or total_students == 0:
            self.status_label.config(text=f"لا توجد غيابات بتاريخ {date_str}", foreground="orange")
            ttk.Label(self.msg_inner, text="لا توجد بيانات لعرضها.", foreground="#888").pack(pady=20)
            self.msg_inner.update_idletasks()
            self.msg_canvas.configure(scrollregion=self.msg_canvas.bbox("all"))
            return

        for cid, obj in sorted(self.msg_groups.items(), key=lambda kv: kv[0]):
            self._msg_build_class_section(cid, obj["class_name"], obj["students"])

        self.status_label.config(text=f"تم تحميل {total_students} طالبًا غائبًا.", foreground="green")

        self.msg_inner.update_idletasks()
        self.msg_canvas.configure(scrollregion=self.msg_canvas.bbox("all"))


    def _msg_build_class_section(self, class_id: str, class_name: str, students: List[Dict[str, str]]):
        frame = ttk.LabelFrame(self.msg_inner, text=class_name, padding=10)
        frame.pack(fill="x", expand=True, pady=6)

        top_row = ttk.Frame(frame)
        top_row.pack(fill="x", pady=(0, 6))
        var_all = tk.BooleanVar(value=False)
        self.class_select_vars[class_id] = var_all

        chk = ttk.Checkbutton(top_row, text="اختيار جميع طلاب هذا الفصل", variable=var_all,
                              command=lambda cid=class_id: self._msg_toggle_class(cid))
        chk.pack(side="right")

        ttk.Label(top_row, text=f"عدد الطلاب: {len(students)}").pack(side="left")

        grid = ttk.Frame(frame)
        grid.pack(fill="x", expand=True)

        cols = 2
        for i, s in enumerate(students):
            r = i // cols
            c = i % cols
            cell = ttk.Frame(grid)
            cell.grid(row=r, column=c, sticky="ew", padx=4, pady=3)

            var = tk.BooleanVar(value=False)
            self.msg_vars[s["id"]] = var

            phone_txt = s.get("phone", "")
            label = f"{s['name']} — {phone_txt if phone_txt else 'لا يوجد رقم'}"
            ttk.Checkbutton(cell, text=label, variable=var).pack(anchor="w")

        for c in range(cols):
            grid.columnconfigure(c, weight=1)


    def _msg_toggle_class(self, class_id: str):
        checked = self.class_select_vars.get(class_id, tk.BooleanVar(value=False)).get()
        for s in self.msg_groups.get(class_id, {}).get("students", []):
            sid = s["id"]
            if sid in self.msg_vars:
                self.msg_vars[sid].set(checked)

    def _msg_toggle_all(self):
        checked = self.global_select_var.get()
        for var in self.class_select_vars.values():
            var.set(checked)
        for v in self.msg_vars.values():
            v.set(checked)

    def _msg_open_template_editor(self):
        win = tk.Toplevel(self.root)
        win.title("تعديل نص رسالة الغياب")
        win.geometry("650x350")
        win.transient(self.root)
        win.grab_set()

        info_frame = ttk.Frame(win)
        info_frame.pack(fill="x", padx=15, pady=(10, 5))
        ttk.Label(info_frame, text="المتغيّرات المدعومة:", anchor="e").pack(side="right")
        ttk.Label(info_frame, text="{school_name}, {student_name}, {class_name}, {date}", foreground="#007bff", anchor="w").pack(side="left")
        ttk.Separator(win, orient='horizontal').pack(fill='x', padx=10, pady=5)

        fields_frame = ttk.Frame(win, padding="10")
        fields_frame.pack(fill="both", expand=True)

        current_template = (load_config().get("message_template") or DEFAULT_CONFIG["message_template"]).strip()
        lines = current_template.split('\n')

        entries = []
        labels = [
            "السطر الأول (تنبيه):",
            "السطر الثاني (ولي الأمر):",
            "السطر الثالث (نص الإفادة):",
            "السطر الرابع (الحث على المتابعة):",
            "السطر الخامس (التحية):",
            "السطر السادس (التوقيع):"
        ]
        
        for i in range(6):
            row_frame = ttk.Frame(fields_frame)
            row_frame.pack(fill="x", pady=4)
            
            label_text = labels[i] if i < len(labels) else f"السطر الإضافي {i+1}:"
            lbl = ttk.Label(row_frame, text=label_text, width=25, anchor="e")
            lbl.pack(side="right", padx=5)
            
            entry = ttk.Entry(row_frame, font=("Tahoma", 10), justify='right')
            entry.pack(side="left", fill="x", expand=True)
            
            if i < len(lines):
                entry.insert(0, lines[i])
            
            entries.append(entry)

        def save_and_close():
            new_lines = [e.get().strip() for e in entries if e.get().strip()]
            new_template = "\n".join(new_lines)

            if not new_template:
                messagebox.showwarning("تنبيه", "لا يمكن حفظ قالب فارغ.", parent=win)
                return
            
            try:
                cfg = load_config()
                cfg["message_template"] = new_template
                with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                
                if hasattr(self, 'msg_template_var'):
                    self.msg_template_var.set(new_template)

                messagebox.showinfo("تم الحفظ", "تم تحديث نص الرسالة بنجاح.", parent=win)
                win.destroy()

            except Exception as e:
                messagebox.showerror("خطأ في الحفظ", f"حدث خطأ أثناء حفظ القالب:\n{e}", parent=win)

        buttons_frame = ttk.Frame(win)
        buttons_frame.pack(fill="x", padx=10, pady=(10, 10))

        ttk.Button(buttons_frame, text="حفظ وإغلاق", command=save_and_close).pack(side="left", padx=5)
        ttk.Button(buttons_frame, text="إلغاء", command=win.destroy).pack(side="right", padx=5)

    def _msg_send_selected(self):
        date_str = self.msg_date_var.get().strip()
        if not date_str:
            messagebox.showerror("خطأ", "الرجاء إدخال تاريخ.")
            return

        selected = []
        for cid, obj in self.msg_groups.items():
            cname = obj["class_name"]
            for s in obj["students"]:
                if self.msg_vars.get(s["id"], tk.BooleanVar()).get():
                    selected.append((cid, cname, s))

        if not selected:
            messagebox.showinfo("تنبيه", "الرجاء تحديد طالب واحد على الأقل.")
            return

        tpl = self.msg_template_var.get() or get_message_template()
        self.status_label.config(text="جارٍ الإرسال...", foreground="blue")
        self.send_button.config(state="disabled")
        self.root.update_idletasks()

        s_ok, s_fail = 0, 0
        for cid, cname, s in selected:
            student_name = s["name"]
            phone = s.get("phone", "")
            body = render_message(student_name, class_name=cname, date_str=date_str)
            success, msg = safe_send_absence_alert(s["id"], student_name, cname, date_str)
            status_text = "تم الإرسال" if success else f"فشل: {msg}"
            if success:
                s_ok += 1
            else:
                s_fail += 1

            try:
                log_message_status(date_str, s["id"], student_name, cid, cname, phone, status_text, body)
            except Exception as e:
                print("log_message_status error:", e)

            self.status_label.config(text=f"جاري الإرسال... ✅{s_ok} / ❌{s_fail}", foreground="blue")
            self.root.update_idletasks()

        self.send_button.config(state="normal")
        summary = f"اكتمل: نجح {s_ok}، فشل {s_fail}."
        self.status_label.config(text=summary, foreground="green" if s_fail == 0 else "red")
        messagebox.showinfo("نتيجة الإرسال", summary)
    
    def _open_today_messages_report(self):
        date_str = now_riyadh_date()
        rows = query_today_messages(date_str)
        win = tk.Toplevel(self.root)
        win.title(f"تقرير رسائل اليوم ({date_str})")
        win.geometry("800x500")

        cols = ("student_name", "class_name", "phone", "status")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for c, h, w in zip(cols, ["اسم الطالب", "الفصل", "رقم الجوال", "حالة الرسالة"], [220, 220, 140, 200]):
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor="center")
        tree.pack(fill="both", expand=True)

        for r in rows:
            tree.insert("", "end", values=(r["student_name"], r["class_name"], r["phone"], r["status"]))

