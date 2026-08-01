# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time, webbrowser
import subprocess
from constants import PORT, STATIC_DOMAIN, WHATS_PATH, debug_on, local_ip, CONFIG_JSON
from config_manager import load_config
from database import load_teachers
from alerts_service import (get_tardiness_recipients, load_schedule,
                             save_schedule, save_tardiness_recipients)
from whatsapp_service import check_whatsapp_server_status, send_whatsapp_message

class ScheduleTabMixin:
    """Mixin: ScheduleTabMixin"""
    def _build_schedule_tab(self):
        self.cfg = load_config()
        frame = self.schedule_frame
        self.schedule_widgets = {}
        self.schedule_time_vars = {}

        today_weekday = (datetime.datetime.now().weekday() + 1) % 7
        default_day = today_weekday if today_weekday <= 4 else 0
        self.selected_day_var = tk.IntVar(value=default_day)

        days_frame = ttk.Frame(frame, padding=(10, 5))
        days_frame.pack(fill="x", side="top")
        ttk.Label(days_frame, text="اختر اليوم لعرض/تعديل جدوله:", font=("Segoe UI", 10, "bold")).pack(side="right", padx=(0, 10))
        
        days_map = {0: "الأحد", 1: "الاثنين", 2: "الثلاثاء", 3: "الأربعاء", 4: "الخميس"}
        for day_index, day_name in days_map.items():
            rb = ttk.Radiobutton(days_frame, text=day_name, variable=self.selected_day_var, value=day_index, command=self.populate_schedule_table)
            rb.pack(side="right", padx=5)

        main_controls_frame = ttk.Frame(frame, padding=10)
        main_controls_frame.pack(fill="x", side="top")

        buttons_frame = ttk.Frame(main_controls_frame)
        buttons_frame.pack(side="right", fill="y", padx=(10, 0))
        self.start_scheduler_button = ttk.Button(buttons_frame, text="🚀 بدء الإرسال الآلي (لليوم)", command=self.start_scheduler)
        self.start_scheduler_button.pack(fill="x", pady=2)
        self.stop_scheduler_button = ttk.Button(buttons_frame, text="🛑 إيقاف الإرسال", command=self.stop_scheduler, state="disabled")
        self.stop_scheduler_button.pack(fill="x", pady=2)
        ttk.Button(buttons_frame, text="💾 حفظ الجدول والتواقيت", command=self.on_save_schedule_and_times).pack(fill="x", pady=(10, 2))
        ttk.Button(buttons_frame, text="🔄 تحديث الجدول", command=self.populate_schedule_table).pack(fill="x", pady=2)
        self._schedule_last_sync = ttk.Label(buttons_frame, text="", foreground="#888", font=("Tahoma", 8))
        self._schedule_last_sync.pack(fill="x", pady=(0,2))
        
        # --- NEW: Web Editor and Clear Buttons ---
        web_buttons_frame = ttk.Frame(buttons_frame)
        web_buttons_frame.pack(fill="x", pady=(10, 0))
        
        web_menu = tk.Menu(web_buttons_frame, tearoff=0)
        try:
            from database import get_cloud_client as _gcc
            _cl2 = _gcc(); _cloud_mode = bool(_cl2 and _cl2.is_active())
        except Exception:
            _cloud_mode = False
        if _cloud_mode:
            web_menu.add_command(label="فتح من السيرفر", command=lambda: self.open_schedule_editor('cloud'))
        else:
            web_menu.add_command(label="فتح الرابط المحلي", command=lambda: self.open_schedule_editor('local'))
            if self.public_url:
                web_menu.add_command(label="فتح الرابط العالمي", command=lambda: self.open_schedule_editor('public'))
            else:
                web_menu.add_command(label="فتح الرابط العالمي (معطل)", state="disabled")

        menubutton = ttk.Menubutton(web_buttons_frame, text="✏️ تعديل الجدول من الويب", menu=web_menu, direction="below")
        menubutton.pack(fill="x", pady=2)

        ttk.Button(web_buttons_frame, text="🗑️ مسح الجدول الحالي", command=self.clear_current_schedule).pack(fill="x", pady=2)
        # --- END NEW ---

        # ─── وقت بداية الدوام (لحساب التأخر) ──────────────────
        start_frame = ttk.LabelFrame(main_controls_frame, text=" 🏫 بداية الدوام ")
        start_frame.pack(side="right", fill="y", padx=(0,6))
        ttk.Label(start_frame, text="وقت بداية الدوام:", font=("Tahoma",10)).pack(pady=(8,2))
        self.school_start_var = tk.StringVar(
            value=self.cfg.get("school_start_time","07:00"))
        start_entry = ttk.Entry(start_frame, textvariable=self.school_start_var,
                                 width=8, justify="center", font=("Courier",12,"bold"))
        start_entry.pack(padx=10, pady=4)
        ttk.Label(start_frame, text="(HH:MM)", foreground="#5A6A7E",
                  font=("Tahoma",8)).pack()
        ttk.Label(start_frame,
                  text="يُستخدم لحساب\ndقائق التأخر",
                  foreground="#5A6A7E", font=("Tahoma",8),
                  justify="center").pack(pady=(4,8))
        # ──────────────────────────────────────────────────────

        times_frame = ttk.LabelFrame(main_controls_frame, text="⏰ توقيت الحصص (HH:MM)")
        times_frame.pack(side="right", fill="y", padx=10)
        
        default_times = self.cfg.get("period_times", ["07:00", "07:50", "08:40", "09:50", "10:40", "11:30", "12:20"])
        for i in range(7):
            period = i + 1
            row = ttk.Frame(times_frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"الحصة {period}:").pack(side="right")
            
            time_var = tk.StringVar(value=default_times[i] if i < len(default_times) else "")
            time_entry = ttk.Entry(row, textvariable=time_var, width=7, justify='center')
            time_entry.pack(side="left", padx=5)
            self.schedule_time_vars[period] = time_var

        status_frame = ttk.LabelFrame(main_controls_frame, text="📝 سجل الحالة")
        status_frame.pack(side="left", fill="both", expand=True)
        self.scheduler_log = tk.Text(status_frame, height=8, width=50, state="disabled", wrap="word", font=("Segoe UI", 9))
        log_scroll = ttk.Scrollbar(status_frame, orient="vertical", command=self.scheduler_log.yview)
        self.scheduler_log.config(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.scheduler_log.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        table_container = ttk.Frame(frame)
        table_container.pack(fill="both", expand=True, padx=5, pady=5)

        canvas = tk.Canvas(table_container)
        scrollbar_y = ttk.Scrollbar(table_container, orient="vertical", command=canvas.yview)
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x = ttk.Scrollbar(table_container, orient="horizontal", command=canvas.xview)
        scrollbar_x.pack(side="bottom", fill="x")
        canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        canvas.pack(side="left", fill="both", expand=True)
        self.schedule_table_frame = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=self.schedule_table_frame, anchor="nw")
        self.schedule_table_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        
        self.populate_schedule_table()

        # ── تحديث تلقائي كل 30 ثانية لمزامنة التغييرات من الويب ──
        self._schedule_auto_refresh_active = True
        def _auto_refresh_schedule():
            if not self._schedule_auto_refresh_active:
                return
            if self._current_tab.get() == "جدولة الروابط":
                self.populate_schedule_table()
                if hasattr(self, "_schedule_last_sync"):
                    now = datetime.datetime.now().strftime("%H:%M:%S")
                    self._schedule_last_sync.config(text=f"آخر تحديث: {now}")
            frame.after(120_000, _auto_refresh_schedule)
        frame.after(120_000, _auto_refresh_schedule)

    def open_schedule_editor(self, link_type: str):
        if link_type == 'cloud':
            try:
                from database import get_cloud_client
                _cl = get_cloud_client()
                if _cl and _cl.is_active():
                    url = f"{_cl.url.rstrip('/')}/schedule/edit"
                else:
                    messagebox.showerror("خطأ", "تعذّر الاتصال بالسيرفر.")
                    return
            except Exception as e:
                messagebox.showerror("خطأ", str(e)); return
        elif link_type == 'local':
            url = f"http://{self.ip}:{PORT}/schedule/edit"
        elif link_type == 'public':
            if not self.public_url:
                messagebox.showerror("خطأ", "الرابط العالمي غير متاح حاليًا.")
                return
            url = f"{self.public_url}/schedule/edit"
        else:
            return
        webbrowser.open(url)

    def clear_current_schedule(self):
        password = simpledialog.askstring("تأكيد", "للمتابعة، الرجاء إدخال كلمة المرور:", show='*')
        if password != "123":
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return
        
        selected_day = self.selected_day_var.get()
        day_name = {0: "الأحد", 1: "الاثنين", 2: "الثلاثاء", 3: "الأربعاء", 4: "الخميس"}.get(selected_day, "المحدد")
        
        if not messagebox.askyesno("تأكيد المسح", f"هل أنت متأكد من أنك تريد مسح جميع مدخلات جدول يوم {day_name}؟\nلا يمكن التراجع عن هذا الإجراء."):
            return
            
        try:
            save_schedule(selected_day, []) # Save an empty schedule
            self.populate_schedule_table() # Refresh the UI
            messagebox.showinfo("تم المسح", f"تم مسح جدول يوم {day_name} بنجاح.")
        except Exception as e:
            messagebox.showerror("خطأ", f"حدث خطأ أثناء مسح الجدول: {e}")

    # ══════════════════════════════════════════════════════════
    # إعداد مستلمي رابط التأخر (داخل تبويب جدولة الروابط)
    # ══════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════
    # تبويب مستقل: مستلمو رابط التأخر
    # ══════════════════════════════════════════════════════════
    def _build_tardiness_recipients_tab(self):
        """يبني تبويب إدارة مستلمي رابط التأخر."""
        frame = self.tardiness_recipients_frame

        # عنوان التبويب
        hdr = tk.Frame(frame, bg="#E65100", height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⏱ إعداد إرسال رابط التأخر التلقائي",
                 bg="#E65100", fg="white",
                 font=("Tahoma", 13, "bold")).pack(side="right", padx=16, pady=12)

        tk.Label(frame,
            text="يُرسَل رابط تسجيل التأخر (كل طلاب المدرسة) لجميع المستلمين "
                 "تلقائياً في وقت بداية الدوام يومياً — أو يدوياً بضغطة زر.",
            font=("Tahoma", 10), fg="#444", justify="right",
            wraplength=900
        ).pack(anchor="e", padx=16, pady=(10, 0))

        # ─── مؤشر خادم الواتساب المختصر ─────────────────────────
        wa_mini = ttk.LabelFrame(frame, text=" 🟢 خادم واتساب ", padding=6)
        wa_mini.pack(fill="x", padx=10, pady=(6, 0))
        wa_mini_row = ttk.Frame(wa_mini); wa_mini_row.pack(fill="x")

        self._wa_mini_dot = tk.Label(wa_mini_row, text="⬤", font=("Tahoma", 13), fg="#aaaaaa")
        self._wa_mini_dot.pack(side="right", padx=(0, 4))
        self._wa_mini_text = ttk.Label(wa_mini_row, text="جارٍ التحقق...", font=("Tahoma", 9))
        self._wa_mini_text.pack(side="right", padx=(0, 6))

        def _mini_check():
            self.check_whatsapp_status_ui()
            # فحص سريع للمؤشر الصغير أيضاً
            try:
                import urllib.request, json as _j
                r = urllib.request.urlopen("http://localhost:3000/status", timeout=1)
                data = _j.loads(r.read())
                if data.get("ready"):
                    self._wa_mini_dot.config(fg="#22c55e")
                    self._wa_mini_text.config(text="✅ متصل ويعمل", foreground="#166534")
                else:
                    self._wa_mini_dot.config(fg="#f59e0b")
                    self._wa_mini_text.config(text="⏳ يعمل — امسح QR", foreground="#92400e")
            except Exception:
                self._wa_mini_dot.config(fg="#ef4444")
                self._wa_mini_text.config(text="🔴 غير متصل", foreground="#991b1b")

        ttk.Button(wa_mini_row, text="🔍 فحص الحالة",
                   command=_mini_check).pack(side="left", padx=4)

        # فحص عند الضغط فقط — لا جدولة تلقائية

        # بناء الواجهة الرئيسية
        self._build_tardiness_recipients_ui(frame)

    def _build_tardiness_recipients_ui(self, parent_frame):
        """يبني واجهة إدارة مستلمي رابط التأخر."""

        lf = ttk.LabelFrame(
            parent_frame,
            text=" 📤 مستلمو رابط التأخر التلقائي ",
            padding=10
        )
        lf.pack(fill="both", expand=True, padx=10, pady=(8,4))

        # رابط التأخر للنسخ — يأخذ من السيرفر في وضع العميل
        def get_tard_url():
            try:
                from database import get_cloud_client as _gcc
                _cl = _gcc()
                if _cl and _cl.is_active():
                    return "{}/tardiness".format(_cl.url.rstrip("/"))
            except Exception:
                pass
            base = (STATIC_DOMAIN if STATIC_DOMAIN and not debug_on()
                    else "http://{}:{}".format(local_ip(), PORT))
            return "{}/tardiness".format(base)

        url_row = ttk.Frame(lf); url_row.pack(fill="x", pady=(0,8))
        ttk.Label(url_row, text="رابط التأخر:", font=("Tahoma",9,"bold")).pack(side="right", padx=(0,6))
        self.tard_url_var = tk.StringVar(value=get_tard_url())
        url_entry = ttk.Entry(url_row, textvariable=self.tard_url_var,
                               state="readonly", font=("Courier",9))
        url_entry.pack(side="right", fill="x", expand=True)

        def copy_url():
            url = get_tard_url()
            self.tard_url_var.set(url)   # تحديث فوري
            self.root.clipboard_clear()
            self.root.clipboard_append(url)

        def refresh_url():
            self.tard_url_var.set(get_tard_url())

        btn_frame = ttk.Frame(url_row); btn_frame.pack(side="left", padx=4)
        ttk.Button(btn_frame, text="نسخ",    width=5, command=copy_url).pack(side="right", padx=2)
        ttk.Button(btn_frame, text="تحديث",  width=5, command=refresh_url).pack(side="right", padx=2)

        # تحديث الرابط تلقائياً بعد ثانية (بعد أن يكون الخادم جاهزاً)
        lf.after(1500, refresh_url)

        # أزرار الإرسال اليدوي
        send_row = ttk.Frame(lf); send_row.pack(fill="x", pady=(0,8))
        self.tard_send_btn = ttk.Button(
            send_row, text="📲 إرسال الرابط الآن للجميع",
            command=self._send_tardiness_now)
        self.tard_send_btn.pack(side="right", padx=4)
        self.tard_status_lbl = ttk.Label(
            send_row, text="", foreground="green", font=("Tahoma",9))
        self.tard_status_lbl.pack(side="right", padx=8)

        # حالة الجدول التلقائي
        auto_row = ttk.Frame(lf); auto_row.pack(fill="x", pady=(0,8))
        self.tard_auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            auto_row,
            text="إرسال تلقائي عند بداية الدوام",
            variable=self.tard_auto_var
        ).pack(side="right")
        ttk.Label(auto_row, text="(يتم يومياً أيام الأحد—الخميس)",
                  foreground="#5A6A7E", font=("Tahoma",9)).pack(side="right", padx=6)

        ttk.Separator(lf, orient="horizontal").pack(fill="x", pady=6)

        # ─ إضافة مستلم
        add_row = ttk.Frame(lf); add_row.pack(fill="x", pady=(0,6))
        ttk.Label(add_row, text="اسم المستلم:", width=12, anchor="e").pack(side="right")
        self.tard_name_var  = tk.StringVar()
        ttk.Entry(add_row, textvariable=self.tard_name_var,
                  width=20, justify="right").pack(side="right", padx=4)
        ttk.Label(add_row, text="الجوال:", width=7, anchor="e").pack(side="right", padx=(8,0))
        self.tard_phone_var = tk.StringVar()
        ttk.Entry(add_row, textvariable=self.tard_phone_var,
                  width=14, justify="right").pack(side="right", padx=4)
        ttk.Button(add_row, text="➕ إضافة",
                   command=self._tard_recipient_add).pack(side="right", padx=4)

        # ─ جدول المستلمين
        cols = ("name","phone","role")
        tree_frame = ttk.Frame(lf)
        tree_frame.pack(fill="both", expand=True)
        self.tree_tard_recv = ttk.Treeview(
            tree_frame, columns=cols, show="headings", height=6)
        for col, hdr, w in zip(cols,
            ["الاسم", "رقم الجوال", "الدور/الوظيفة"],
            [200, 140, 160]):
            self.tree_tard_recv.heading(col, text=hdr)
            self.tree_tard_recv.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self.tree_tard_recv.yview)
        self.tree_tard_recv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree_tard_recv.pack(side="left", fill="both", expand=True)

        del_row = ttk.Frame(lf); del_row.pack(fill="x", pady=(6,0))
        ttk.Button(del_row, text="🗑️ حذف المحدد",
                   command=self._tard_recipient_del).pack(side="right", padx=4)
        ttk.Button(del_row, text="استيراد من قائمة المعلمين",
                   command=self._tard_import_teachers).pack(side="right", padx=4)

        self._tard_recipients_load()

    def _tard_recipients_load(self):
        if not hasattr(self, "tree_tard_recv"): return
        for i in self.tree_tard_recv.get_children():
            self.tree_tard_recv.delete(i)
        for r in get_tardiness_recipients():
            self.tree_tard_recv.insert("", "end",
                values=(r.get("name",""), r.get("phone",""), r.get("role","")))

    def _tard_recipient_add(self):
        name  = self.tard_name_var.get().strip() if hasattr(self,"tard_name_var") else ""
        phone = self.tard_phone_var.get().strip() if hasattr(self,"tard_phone_var") else ""
        if not name or not phone:
            messagebox.showwarning("تنبيه", "أدخل الاسم ورقم الجوال")
            return
        role = simpledialog.askstring(
            "الدور", "ما دور/وظيفة '"+name+"'؟ (اختياري)",
            parent=self.root) or ""
        recps = get_tardiness_recipients()
        # تجنب التكرار
        if any(r["phone"]==phone for r in recps):
            messagebox.showwarning("تنبيه","رقم الجوال موجود مسبقاً")
            return
        recps.append({"name":name,"phone":phone,"role":role})
        save_tardiness_recipients(recps)
        self.tard_name_var.set("")
        self.tard_phone_var.set("")
        self._tard_recipients_load()

    def _tard_recipient_del(self):
        if not hasattr(self,"tree_tard_recv"): return
        sel = self.tree_tard_recv.selection()
        if not sel:
            messagebox.showwarning("تنبيه","حدد مستلماً أولاً")
            return
        vals  = self.tree_tard_recv.item(sel[0])["values"]
        phone = vals[1]
        if not messagebox.askyesno("تأكيد",f"حذف '{vals[0]}'؟"): return
        recps = [r for r in get_tardiness_recipients() if r.get("phone")!=phone]
        save_tardiness_recipients(recps)
        self._tard_recipients_load()

    def _tard_import_teachers(self):
        """يستورد أرقام المعلمين من قائمة المعلمين الموجودة."""
        teachers_data = load_teachers()
        teachers      = teachers_data.get("teachers", [])
        recps         = get_tardiness_recipients()
        existing_phones = {r["phone"] for r in recps}
        added = 0
        for t in teachers:
            name  = t.get("اسم المعلم","")
            phone = t.get("رقم الجوال","")
            if phone and phone not in existing_phones:
                recps.append({"name":name,"phone":phone,"role":"معلم"})
                existing_phones.add(phone)
                added += 1
        save_tardiness_recipients(recps)
        self._tard_recipients_load()
        messagebox.showinfo("تم",f"تم استيراد {added} معلم من قائمة المعلمين.")

    def _send_tardiness_now(self):
        """يرسل رابط التأخر الآن لجميع المستلمين."""
        if not hasattr(self,"tard_send_btn"): return
        recps = get_tardiness_recipients()
        if not recps:
            messagebox.showwarning("تنبيه","لا يوجد مستلمون. أضف مستلمين أولاً.")
            return
        if not check_whatsapp_server_status():
            messagebox.showerror("خطأ","خادم واتساب غير متاح. شغّله أولاً.")
            return
        self.tard_send_btn.config(state="disabled")
        if hasattr(self,"tard_status_lbl"):
            self.tard_status_lbl.config(
                text=f"⏳ جارٍ الإرسال لـ {len(recps)} مستلم...",
                foreground="blue")
        self.root.update_idletasks()

        def do_send():
            sent, failed, details = send_tardiness_link_to_all()
            detail_txt = "\n".join(details)
            self.root.after(0, lambda: self._after_tardiness_send(
                sent, failed, detail_txt))

        threading.Thread(target=do_send, daemon=True).start()

    def _after_tardiness_send(self, sent, failed, detail_txt):
        if hasattr(self,"tard_send_btn"):
            self.tard_send_btn.config(state="normal")
        if hasattr(self,"tard_status_lbl"):
            color = "green" if failed==0 else ("orange" if sent>0 else "red")
            self.tard_status_lbl.config(
                text=f"✅ {sent} | ❌ {failed}",
                foreground=color)
        messagebox.showinfo(
            "نتيجة الإرسال",
            "تم الإرسال بنجاح: {}\nفشل: {}\n\nالتفاصيل:\n{}".format(
                sent, failed, detail_txt))

    def populate_schedule_table(self):
        for widget in self.schedule_table_frame.winfo_children():
            widget.destroy()
        self.schedule_widgets.clear()

        selected_day = self.selected_day_var.get()
        classes = sorted(self.store["list"], key=lambda c: c['id'])
        teachers_data = load_teachers()
        teacher_names = [""] + [t.get("اسم المعلم", "") for t in teachers_data.get("teachers", [])]
        saved_schedule = load_schedule(selected_day)

        header_font = ("Segoe UI", 10, "bold")
        ttk.Label(self.schedule_table_frame, text="الحصة", font=header_font, borderwidth=1, relief="solid", padding=5).grid(row=0, column=0, sticky="nsew")
        for col_idx, cls in enumerate(classes, 1):
            ttk.Label(self.schedule_table_frame, text=cls['name'], font=header_font, borderwidth=1, relief="solid", padding=5, anchor="center").grid(row=0, column=col_idx, sticky="nsew")

        for period in range(1, 8):
            ttk.Label(self.schedule_table_frame, text=f"الحصة {period}", font=header_font, borderwidth=1, relief="solid", padding=5).grid(row=period, column=0, sticky="nsew")
            for col_idx, cls in enumerate(classes, 1):
                class_id = cls['id']
                combo = ttk.Combobox(self.schedule_table_frame, values=teacher_names, state="readonly", justify='center', width=15)
                
                # Dynamic width adjustment
                max_len = max(len(name) for name in teacher_names) if teacher_names else 15
                combo.bind('<Button-1>', lambda e, c=combo, w=max_len: c.config(width=w))

                combo.grid(row=period, column=col_idx, sticky="nsew", padx=1, pady=1)
                teacher = saved_schedule.get((class_id, period))
                if teacher in teacher_names:
                    combo.set(teacher)
                self.schedule_widgets[(class_id, period)] = combo

    def log_scheduler_message(self, message):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        full_message = f"[{now}] {message}\n"
        self.scheduler_log.config(state="normal")
        self.scheduler_log.insert("1.0", full_message)
        self.scheduler_log.config(state="disabled")

    def on_save_schedule_and_times(self):
        selected_day = self.selected_day_var.get()
        day_name = {0: "الأحد", 1: "الاثنين", 2: "الثلاثاء", 3: "الأربعاء", 4: "الخميس"}.get(selected_day, "المحدد")

        schedule_data = []
        for period in range(1, 8):
            for cls in self.store["list"]:
                widget = self.schedule_widgets.get((cls['id'], period))
                if widget:
                    schedule_data.append({"class_id": cls['id'], "period": period, "teacher_name": widget.get()})
        try:
            save_schedule(selected_day, schedule_data)
        except Exception as e:
            messagebox.showerror("خطأ في الحفظ", f"حدث خطأ أثناء حفظ جدول يوم {day_name}:\n{e}")
            return

        period_times = [self.schedule_time_vars[p].get() for p in range(1, 8)]
        self.cfg["period_times"] = period_times
        # حفظ وقت بداية الدوام
        if hasattr(self, "school_start_var"):
            self.cfg["school_start_time"] = self.school_start_var.get().strip()
        try:
            with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("خطأ في الحفظ", f"حدث خطأ أثناء حفظ التواقيت:\n{e}")
            return
            
        messagebox.showinfo("تم الحفظ", f"تم حفظ جدول يوم {day_name} والتواقيت بنجاح.")
        self.log_scheduler_message(f"تم حفظ جدول يوم {day_name}.")


    def start_scheduler(self):
        today = datetime.datetime.now()
        day_of_week = (today.weekday() + 1) % 7 
        
        if day_of_week > 4:
            messagebox.showwarning("يوم عطلة", "لا يمكن بدء المرسل الآلي في يوم عطلة نهاية الأسبوع.")
            self.log_scheduler_message("⚠️ محاولة بدء الإرسال في يوم عطلة. تم الرفض.")
            return

        if self.scheduler_running:
            messagebox.showwarning("قيد التشغيل", "المرسل الآلي يعمل بالفعل.")
            return

        if not messagebox.askyesno("تأكيد البدء", "هل أنت متأكد من أنك تريد بدء الإرسال الآلي لروابط الحصص؟"):
            return

        self.scheduler_running = True
        self.start_scheduler_button.config(state="disabled")
        self.stop_scheduler_button.config(state="normal")
        day_name = {0: "الأحد", 1: "الاثنين", 2: "الثلاثاء", 3: "الأربعاء", 4: "الخميس"}.get(day_of_week)
        self.log_scheduler_message(f"🚀 تم بدء المرسل الآلي لجدول يوم {day_name}.")

        schedule = load_schedule(day_of_week)
        if not schedule:
            self.log_scheduler_message(f"⚠️ تحذير: جدول يوم {day_name} فارغ. لن يتم إرسال أي شيء.")
            self.stop_scheduler()
            return

        now = datetime.datetime.now()
        try:
            from database import get_cloud_client as _gcc
            _cl3 = _gcc()
            base_url = _cl3.url.rstrip("/") if (_cl3 and _cl3.is_active()) else (self.public_url or f"http://{self.ip}:{PORT}")
        except Exception:
            base_url = self.public_url or f"http://{self.ip}:{PORT}"
        
        for period in range(1, 8  ):
            time_str = self.schedule_time_vars[period].get()
            try:
                hour, minute = map(int, time_str.split(':'))
                target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                delay = (target_time - now).total_seconds()
                if delay < 0:
                    self.log_scheduler_message(f"الحصة {period} ({time_str}): الوقت قد فات. تم تخطيها.")
                    continue

                timer = threading.Timer(delay, self.send_links_for_period, args=[period, schedule, base_url])
                self.scheduler_timers.append(timer)
                timer.start()
                self.log_scheduler_message(f"الحصة {period}: تمت جدولتها للإرسال الساعة {time_str}.")

            except (ValueError, AttributeError):
                self.log_scheduler_message(f"الحصة {period}: صيغة الوقت ({time_str}) غير صالحة. تم تخطيها.")
        
        if not self.scheduler_timers:
            self.log_scheduler_message("لم تتم جدولة أي حصص. تأكد من التواقيت.")
            self.stop_scheduler()


    def stop_scheduler(self):
        for timer in self.scheduler_timers:
            timer.cancel()
        
        self.scheduler_timers = []
        self.scheduler_running = False
        self.start_scheduler_button.config(state="normal")
        self.stop_scheduler_button.config(state="disabled")
        self.log_scheduler_message("🛑 تم إيقاف المرسل الآلي.")

    def send_links_for_period(self, period, schedule, base_url):
        self.log_scheduler_message(f"🔔 حان وقت الحصة {period}! جارٍ إرسال الروابط...")
        
        teachers_to_notify = {}
        
        for (class_id, p), teacher_name in schedule.items():
            if p == period and teacher_name:
                class_info = self.store["by_id"].get(class_id)
                if class_info:
                    if teacher_name not in teachers_to_notify:
                        teachers_to_notify[teacher_name] = []
                    teachers_to_notify[teacher_name].append(class_info)

        if not teachers_to_notify:
            self.log_scheduler_message(f"الحصة {period}: لا يوجد معلمون مجدولون لهذه الحصة.")
            return

        all_teachers = {t.get("اسم المعلم", ""): t for t in load_teachers().get("teachers", [])}

        for teacher_name, assigned_classes in teachers_to_notify.items():
            teacher_data = all_teachers.get(teacher_name)
            if not teacher_data or not teacher_data.get("رقم الجوال"):
                self.log_scheduler_message(f"الحصة {period}: فشل إرسال لـ '{teacher_name}' (لا يوجد رقم جوال).")
                continue

            links_text = "\n".join([f"- فصل: {c['name']}\n  الرابط: {base_url}/c/{c['id']}" for c in assigned_classes])
            message_body = (
                f"السلام عليكم أ. {teacher_name},\n"
                f"إليك روابط تسجيل الغياب للحصة {period}:\n\n"
                f"{links_text}\n\n"
                "مع تحيات إدارة المدرسة."
            )
            
            success, msg = send_whatsapp_message(teacher_data["رقم الجوال"], message_body)
            
            if success:
                self.log_scheduler_message(f"✅ تم إرسال روابط الحصة {period} إلى '{teacher_name}'.")
            else:
                self.log_scheduler_message(f"❌ فشل إرسال لـ '{teacher_name}': {msg}")


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
