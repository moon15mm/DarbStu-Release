# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time, webbrowser
try:
    import qrcode
    from PIL import ImageTk
except ImportError:
    qrcode = ImageTk = None
from constants import PORT, now_riyadh_date, local_ip, STATIC_DOMAIN
from database import _apply_class_name_fix, load_teachers, query_absences
from whatsapp_service import send_whatsapp_message
from config_manager import load_config

class LinksTabMixin:
    """Mixin: LinksTabMixin"""
    def _build_links_tab(self):
        if self.public_url:
            ttk.Label(self.links_frame, text=f"الرابط العام: {self.public_url}", foreground="blue", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0,4))
            ttk.Label(self.links_frame, text="امسح الـ QR Code للوصول من الإنترنت.").pack(anchor="w", pady=(0,8))
        else:
            ttk.Label(self.links_frame, text=f"الخادم المحلي: http://{self.ip}:{PORT} (يعمل على نفس الشبكة فقط )").pack(anchor="w", pady=(0,8))
        main_container = ttk.Frame(self.links_frame)
        main_container.pack(fill="both", expand=True)
        left_frame = ttk.Frame(main_container)
        left_frame.pack(side="left", fill="both", expand=True, padx=5)
        cols = ("class_id", "class_name", "students", "link")
        tree = ttk.Treeview(left_frame, columns=cols, show="headings", height=8)
        for c, t, w in zip(cols, ["المعرّف","اسم الفصل","عدد الطلاب","الرابط"], [80, 180, 80, 300]):
            tree.heading(c, text=t); tree.column(c, width=w, anchor="center")
        tree.pack(fill="x", expand=True); self.tree_links = tree
        self.qr_canvas = tk.Label(left_frame); self.qr_canvas.pack(pady=8, anchor="center")
        send_controls_frame = ttk.LabelFrame(main_container, text=" إرسال الرابط إلى معلم ", padding=10)
        send_controls_frame.pack(side="right", fill="y", padx=5, anchor="n")
        ttk.Label(send_controls_frame, text="اختر المعلم:").pack(anchor="e")
        self.teacher_var = tk.StringVar()
        self.teacher_combo = ttk.Combobox(send_controls_frame, textvariable=self.teacher_var, state="readonly", width=30)
        self.teacher_combo.pack(anchor="e", pady=5, fill="x")
        self.send_link_button = ttk.Button(send_controls_frame, text="إرسال الرابط المحدد عبر واتساب", command=self.on_send_link_to_teacher, state="disabled")
        self.send_link_button.pack(anchor="e", pady=10)
        self.tree_links.bind("<<TreeviewSelect>>", self.on_class_select)
        self.teacher_combo.bind("<<ComboboxSelected>>", self.on_teacher_select)
        self._refresh_links_and_teachers()

    def _refresh_links_and_teachers(self):
        if not hasattr(self, "tree_links") or not self.tree_links.winfo_exists():
            return
        for i in self.tree_links.get_children(): self.tree_links.delete(i)
        # في وضع العميل السحابي استخدم رابط السيرفر
        try:
            from database import get_cloud_client
            _cl = get_cloud_client()
            if _cl and _cl.is_active():
                base_url = _cl.url.rstrip("/")
            else:
                base_url = self.public_url or f"http://{self.ip}:{PORT}"
        except Exception:
            base_url = self.public_url or f"http://{self.ip}:{PORT}"
        for c in self.store["list"]:
            link = f"{base_url}/c/{c['id']}"
            self.tree_links.insert("", "end", values=(c["id"], c["name"], len(c["students"] ), link))
        self.teachers_data = load_teachers()
        teacher_names = [t.get("اسم المعلم", "") for t in self.teachers_data.get("teachers", [])]
        self.teacher_combo['values'] = teacher_names
        self.teacher_var.set("")
        self.send_link_button.config(state="disabled")
        self.qr_img = None
        self.qr_canvas.config(image=None)

    def on_class_select(self, event=None):
        if not (sel := self.tree_links.selection()): return
        link = self.tree_links.item(sel[0])["values"][3]
        img = qrcode.make(link).resize((220,220)); self.qr_img = ImageTk.PhotoImage(img)
        self.qr_canvas.config(image=self.qr_img)
        if self.teacher_var.get():
            self.send_link_button.config(state="normal")

    def on_teacher_select(self, event=None):
        if self.tree_links.selection():
            self.send_link_button.config(state="normal")

    def on_send_link_to_teacher(self):
        if not (sel := self.tree_links.selection()):
            messagebox.showwarning("تنبيه", "الرجاء تحديد فصل من القائمة أولاً.")
            return
        if not (teacher_name := self.teacher_var.get()):
            messagebox.showwarning("تنبيه", "الرجاء اختيار معلم من القائمة.")
            return
        class_name, link = self.tree_links.item(sel[0])["values"][1], self.tree_links.item(sel[0])["values"][3]
        teacher = next((t for t in self.teachers_data.get("teachers", []) if t.get("اسم المعلم", "") == teacher_name), None)
        if not teacher:
            messagebox.showerror("خطأ", "لم يتم العثور على بيانات المعلم المحدد.")
            return
        teacher_phone = teacher.get("رقم الجوال")
        if not teacher_phone:
            messagebox.showwarning("تنبيه", f"لا يوجد رقم جوال مسجل للمعلم '{teacher_name}'.")
            return
        if not messagebox.askyesno("تأكيد الإرسال", f"هل أنت متأكد من إرسال رابط فصل '{class_name}' إلى المعلم '{teacher_name}'؟"):
            return
        self.send_link_button.config(state="disabled"); self.root.update_idletasks()
        # Note: send_link_to_teacher is not defined in the provided code, assuming it's a wrapper for send_whatsapp_message
        message_body = f"السلام عليكم أ. {teacher_name},\nإليك رابط تسجيل غياب فصل: {class_name}\n{link}"
        success, message = send_whatsapp_message(teacher_phone, message_body)
        messagebox.showinfo("نتيجة الإرسال", message)
        self.send_link_button.config(state="normal")


