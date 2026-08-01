# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
from constants import PORT, now_riyadh_date, local_ip, STATIC_DOMAIN
from report_builder import generate_monitor_table_html, get_live_monitor_status

from gui.lib_loader import HtmlFrame

class MonitorTabMixin:
    """Mixin: MonitorTabMixin"""
    def _build_live_monitor_tab(self):
        frame = self.live_monitor_frame
        links_frame = ttk.LabelFrame(frame, text=" روابط الوصول الخارجي (للمتصفحات الأخرى) ", padding=10)
        links_frame.pack(fill="x", pady=5, padx=5)

        # تحديد الـ base URL الصحيحة (سيرفر أو محلي)
        try:
            from database import get_cloud_client
            _cl = get_cloud_client()
            _is_cloud = bool(_cl and _cl.is_active())
            _server_base = _cl.url.rstrip("/") if _is_cloud else None
        except Exception:
            _is_cloud = False; _server_base = None

        def copy_to_clipboard(text_to_copy):
            self.root.clipboard_clear(); self.root.clipboard_append(text_to_copy)
            messagebox.showinfo("تم النسخ", "تم نسخ الرابط إلى الحافظة بنجاح!")

        if _is_cloud and _server_base:
            # وضع العميل: اعرض رابط السيرفر فقط
            srv_frame = ttk.Frame(links_frame); srv_frame.pack(fill="x", pady=2)
            monitor_url_server = f"{_server_base}/monitor"
            ttk.Label(srv_frame, text="رابط السيرفر:", width=12).pack(side="right", padx=5)
            srv_entry = ttk.Entry(srv_frame, font=("Segoe UI", 9))
            srv_entry.insert(0, monitor_url_server); srv_entry.config(state="readonly")
            srv_entry.pack(side="right", fill="x", expand=True)
            ttk.Button(srv_frame, text="📋 نسخ", width=8,
                       command=lambda: copy_to_clipboard(monitor_url_server)).pack(side="left", padx=5)
        else:
            # وضع السيرفر: الرابط المحلي + العام
            local_frame = ttk.Frame(links_frame); local_frame.pack(fill="x", pady=2)
            monitor_url_local = f"http://{self.ip}:{PORT}/monitor"
            ttk.Label(local_frame, text="الرابط المحلي:", width=12).pack(side="right", padx=5)
            local_link_entry = ttk.Entry(local_frame, font=("Segoe UI", 9))
            local_link_entry.insert(0, monitor_url_local); local_link_entry.config(state="readonly")
            local_link_entry.pack(side="right", fill="x", expand=True)
            ttk.Button(local_frame, text="📋 نسخ", width=8,
                       command=lambda: copy_to_clipboard(monitor_url_local)).pack(side="left", padx=5)
            if self.public_url:
                public_frame = ttk.Frame(links_frame); public_frame.pack(fill="x", pady=2)
                monitor_url_public = self.public_url + "/monitor"
                ttk.Label(public_frame, text="الرابط العام:", width=12).pack(side="right", padx=5)
                public_link_entry = ttk.Entry(public_frame, font=("Segoe UI", 9))
                public_link_entry.insert(0, monitor_url_public); public_link_entry.config(state="readonly")
                public_link_entry.pack(side="right", fill="x", expand=True)
                ttk.Button(public_frame, text="📋 نسخ", width=8,
                           command=lambda: copy_to_clipboard(monitor_url_public)).pack(side="left", padx=5)
        browser_frame = ttk.Frame(frame, padding=(0, 10, 0, 0)); browser_frame.pack(fill="both", expand=True)
        live_monitor_browser = HtmlFrame(browser_frame, horizontal_scrollbar="auto", messages_enabled=False); live_monitor_browser.pack(fill="both", expand=True)
        self._live_monitor_active = False  # علم التحكم في حلقة التحديث

        def update_browser_content():
            # ── توقف إذا لم يكن تبويب المراقبة الحية نشطاً ──
            if not self._live_monitor_active:
                return
            if hasattr(self, "_current_tab") and self._current_tab.get() != "المراقبة الحية":
                self.root.after(10_000, update_browser_content)
                return
            try:
                today = now_riyadh_date()
                status_data = get_live_monitor_status(today)
                html_content = generate_monitor_table_html(status_data)
                now_str = datetime.datetime.now().strftime('%H:%M:%S')
                final_html = html_content.replace('<p id="last-update"></p>', f'<p id="last-update">\u0622\u062e\u0631 \u062a\u062d\u062f\u064a\u062b: {now_str}</p>')
                live_monitor_browser.load_html(final_html)
            except Exception as e:
                print(f"Error updating live monitor: {e}")
            self.root.after(60_000, update_browser_content)

        self._live_monitor_active = True
        self.root.after(500, update_browser_content)

    def reimport_students(self):
        path = filedialog.askopenfilename(
            title="اختر ملف Excel (طلاب)",
            filetypes=[("Excel files","*.xlsx *.xls")])
        if not path: return
        self._preview_import(path)

