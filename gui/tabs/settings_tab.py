# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time, webbrowser
from typing import List, Dict, Any, Optional
import zipfile
from constants import (CURRENT_USER, BACKUP_DIR, CONFIG_JSON, DATA_DIR,
                        DB_PATH, STUDENTS_JSON, TEACHERS_JSON)
from config_manager import invalidate_config_cache, load_config, get_window_title
from database import (authenticate, create_backup, get_backup_list,
                       get_db, load_students, import_students_from_excel_sheet2_format,
                       import_teachers_from_excel, clear_yearly_data)
from whatsapp_service import send_whatsapp_message

class SettingsTabMixin:
    """Mixin: SettingsTabMixin"""
    def _build_school_settings_tab(self):
        """تبويب إعدادات المدرسة — تعديل بيانات المدرسة والإدارة."""
        frame = self.school_settings_frame

        # عنوان
        hdr = tk.Frame(frame, bg="#1565C0", height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="\U0001f3eb إعدادات المدرسة",
                 bg="#1565C0", fg="white",
                 font=("Tahoma", 13, "bold")).pack(side="right", padx=16, pady=12)

        # ── إطار تمرير للمحتوى ──────────────────────────────────
        _canvas = tk.Canvas(frame, highlightthickness=0)
        _vsb = ttk.Scrollbar(frame, orient="vertical", command=_canvas.yview)
        _canvas.configure(yscrollcommand=_vsb.set)
        _vsb.pack(side="left", fill="y")
        _canvas.pack(side="left", fill="both", expand=True)
        scroll = ttk.Frame(_canvas)
        _canvas_win = _canvas.create_window((0, 0), window=scroll, anchor="nw")

        # [تعديل مؤقت] أظهر قسم التحديثات في القمة للتأكد من ظهوره
        self._build_update_settings_section(scroll)

        def _on_frame_configure(e):
            _canvas.configure(scrollregion=_canvas.bbox("all"))
        _ss_last_w = [0]
        def _on_canvas_configure(e):
            w = e.width
            if w == _ss_last_w[0]: return
            _ss_last_w[0] = w
            _canvas.itemconfig(_canvas_win, width=w)
        scroll.bind("<Configure>", _on_frame_configure)
        _canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            _canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        def _ss_bind_mw(e=None):  _canvas.bind("<MouseWheel>", _on_mousewheel)
        def _ss_unbind_mw(e=None): _canvas.unbind("<MouseWheel>")
        _canvas.bind("<Enter>", _ss_bind_mw)
        _canvas.bind("<Leave>", _ss_unbind_mw)
        scroll.bind("<Enter>", _ss_bind_mw)
        scroll.bind("<Leave>", _ss_unbind_mw)
        # ────────────────────────────────────────────────────────

        lf = ttk.LabelFrame(scroll, text=" بيانات المدرسة والإدارة ", padding=16)
        lf.pack(fill="x", padx=20, pady=16)

        cfg = load_config()

        fields = [
            ("school_name",      "اسم المدرسة:"),
            ("assistant_title",  "لقب الوكيل:"),
            ("assistant_name",   "اسم الوكيل:"),
            ("principal_title",  "لقب المدير:"),
            ("principal_name",   "اسم المدير:"),
        ]

        self._school_vars = {}
        for key, label in fields:
            row = ttk.Frame(lf); row.pack(fill="x", pady=6)
            ttk.Label(row, text=label, width=16, anchor="e",
                      font=("Tahoma", 10, "bold")).pack(side="right", padx=(0, 8))
            var = tk.StringVar(value=cfg.get(key, ""))
            ttk.Entry(row, textvariable=var, width=40,
                      font=("Tahoma", 10), justify="right").pack(side="right", fill="x", expand=True)
            self._school_vars[key] = var

        # ── قسم أرقام الجوال ─────────────────────────────────────
        ttk.Separator(lf, orient="horizontal").pack(fill="x", pady=(10, 8))

        phones_hdr = tk.Frame(lf, bg="#7c3aed", pady=5)
        phones_hdr.pack(fill="x", pady=(0, 8))
        tk.Label(phones_hdr, text="📱 أرقام الجوال — للإرسال والإشعارات",
                 bg="#7c3aed", fg="white",
                 font=("Tahoma", 10, "bold")).pack(side="right", padx=12)

        # ── حقلا اسم الموجّهَين ──────────────────────────────────
        counselor_names_hdr = tk.Frame(lf, bg="#5b21b6", pady=4)
        counselor_names_hdr.pack(fill="x", pady=(4, 6))
        tk.Label(counselor_names_hdr, text="👨‍🏫 أسماء الموجّهَين الطلابيّين",
                 bg="#5b21b6", fg="white",
                 font=("Tahoma", 10, "bold")).pack(side="right", padx=12)

        for cn_key, cn_label in [("counselor1_name", "اسم الموجّه الطلابي 1:"),
                                   ("counselor2_name", "اسم الموجّه الطلابي 2:")]:
            cn_row = ttk.Frame(lf); cn_row.pack(fill="x", pady=4)
            ttk.Label(cn_row, text=cn_label, width=20, anchor="e",
                      font=("Tahoma", 10, "bold")).pack(side="right", padx=(0, 8))
            cn_var = tk.StringVar(value=cfg.get(cn_key, ""))
            ttk.Entry(cn_row, textvariable=cn_var, width=35,
                      font=("Tahoma", 10), justify="right").pack(side="right", fill="x", expand=True)
            self._school_vars[cn_key] = cn_var

        ttk.Separator(lf, orient="horizontal").pack(fill="x", pady=(6, 8))

        phone_fields = [
            ("principal_phone",  "📞 جوال مدير المدرسة:",       "#1d4ed8",
             "يُستخدم لإرسال الجلسات الإرشادية والتقارير اليومية"),
            ("alert_admin_phone","📞 جوال وكيل المدرسة:",        "#0369a1",
             "يُستخدم لإرسال الجلسات الإرشادية وتنبيهات الغياب"),
            ("counselor1_phone", "📞 جوال الموجّه الطلابي 1:",   "#7c3aed",
             "يستقبل تنبيهات التحويل من الوكيل وإرسال الجلسات الإرشادية"),
            ("counselor2_phone", "📞 جوال الموجّه الطلابي 2:",   "#6d28d9",
             "يستقبل تنبيهات التحويل من الوكيل وإرسال الجلسات الإرشادية"),
        ]

        for key, label, color, hint in phone_fields:
            ph_row = tk.Frame(lf, bg="white", relief="groove", bd=1)
            ph_row.pack(fill="x", pady=4, ipady=4)

            # الصف العلوي: الليبل + حقل الإدخال
            top = tk.Frame(ph_row, bg="white"); top.pack(fill="x", padx=8, pady=(4,0))
            tk.Label(top, text=label, bg="white", fg=color,
                     font=("Tahoma", 10, "bold"), width=20, anchor="e").pack(side="right")
            var = tk.StringVar(value=cfg.get(key, ""))
            ent = tk.Entry(top, textvariable=var, width=22,
                           font=("Tahoma", 11), justify="center",
                           relief="solid", bd=1, fg="#1a1a1a")
            ent.pack(side="right", padx=8)

            # زر اختبار الإرسال
            def _test_send(v=var, lbl=label):
                phone = v.get().strip()
                if not phone:
                    messagebox.showwarning("تنبيه", f"أدخل رقم {lbl} أولاً", parent=frame)
                    return
                ok, res = send_whatsapp_message(phone,
                    f"✅ رسالة اختبار من نظام درب\nتم التحقق من رقم {lbl} بنجاح.")
                if ok:
                    messagebox.showinfo("✅ نجح الاختبار", f"تم إرسال رسالة اختبار لـ {lbl}", parent=frame)
                else:
                    messagebox.showerror("فشل", f"فشل الإرسال:\n{res}", parent=frame)

            tk.Button(top, text="🧪 اختبار", command=_test_send,
                      bg=color, fg="white", font=("Tahoma", 9, "bold"),
                      relief="flat", padx=8, pady=2, cursor="hand2").pack(side="right", padx=4)

            # التلميح
            tk.Label(ph_row, text=hint, bg="white", fg="#6b7280",
                     font=("Tahoma", 8), anchor="e").pack(fill="x", padx=12, pady=(0,4))

            self._school_vars[key] = var

        tk.Label(lf,
                 text="⚠️  أدخل الرقم بصيغة دولية بدون + مثل: 966501234567",
                 bg="#fffbeb", fg="#92400e",
                 font=("Tahoma", 8), relief="flat", pady=4, padx=8,
                 anchor="e").pack(fill="x", pady=(4, 2))

        # ── خيار جنس المدرسة ────────────────────────────────────
        gender_row = ttk.Frame(lf); gender_row.pack(fill="x", pady=6)
        ttk.Label(gender_row, text="نوع المدرسة:", width=16, anchor="e",
                  font=("Tahoma", 10, "bold")).pack(side="right", padx=(0, 8))
        self._gender_var = tk.StringVar(value=cfg.get("school_gender", "boys"))
        gender_frame = ttk.Frame(gender_row); gender_frame.pack(side="right")

        # أزرار اختيار النوع بدون emoji لتجنب مشاكل Windows
        btn_boys  = tk.Button(gender_frame, text="بنين",
                              font=("Tahoma", 10, "bold"), relief="raised",
                              cursor="hand2", width=8, bd=2)
        btn_girls = tk.Button(gender_frame, text="بنات",
                              font=("Tahoma", 10, "bold"), relief="raised",
                              cursor="hand2", width=8, bd=2)

        def _update_gender_style(*_):
            g = self._gender_var.get()
            if g == "boys":
                btn_boys.config( bg="#1565C0", fg="white",  relief="sunken")
                btn_girls.config(bg="#F1F5F9", fg="#555555", relief="raised")
            else:
                btn_boys.config( bg="#F1F5F9", fg="#555555", relief="raised")
                btn_girls.config(bg="#7C3AED", fg="white",  relief="sunken")

        btn_boys.config( command=lambda: [self._gender_var.set("boys"),  _update_gender_style()])
        btn_girls.config(command=lambda: [self._gender_var.set("girls"), _update_gender_style()])
        btn_boys.pack(side="right", padx=4)
        btn_girls.pack(side="right", padx=4)
        self._school_vars["school_gender"] = self._gender_var
        _update_gender_style()

        # ── مرحلة المدرسة ───────────────────────────────────────
        # تُقرأ تلقائياً من ملف نور، وهذا الاختيار للملفات التي لا تذكرها.
        stage_row = ttk.Frame(lf); stage_row.pack(fill="x", pady=6)
        ttk.Label(stage_row, text="المرحلة:", width=16, anchor="e",
                  font=("Tahoma", 10, "bold")).pack(side="right", padx=(0, 8))
        self._stage_var = tk.StringVar(value=cfg.get("school_stage", "ثانوي"))
        stage_frame = ttk.Frame(stage_row); stage_frame.pack(side="right")

        _stage_btns = {}
        def _update_stage_style(*_):
            cur = self._stage_var.get()
            for name, b in _stage_btns.items():
                if name == cur:
                    b.config(bg="#0F766E", fg="white", relief="sunken")
                else:
                    b.config(bg="#F1F5F9", fg="#555555", relief="raised")

        for _st in ("ابتدائي", "متوسط", "ثانوي"):
            b = tk.Button(stage_frame, text=_st, font=("Tahoma", 10, "bold"),
                          relief="raised", cursor="hand2", width=8, bd=2)
            b.config(command=lambda s=_st: [self._stage_var.set(s),
                                            _update_stage_style()])
            b.pack(side="right", padx=4)
            _stage_btns[_st] = b
        self._school_vars["school_stage"] = self._stage_var
        _update_stage_style()

        tk.Label(lf,
                 text="ℹ️  تُحدَّد تلقائياً عند استيراد ملف نور — غيّرها فقط إن كانت خاطئة",
                 bg="#f0fdfa", fg="#0f766e",
                 font=("Tahoma", 8), relief="flat", pady=4, padx=8,
                 anchor="e").pack(fill="x", pady=(2, 2))

        ttk.Separator(lf, orient="horizontal").pack(fill="x", pady=(12, 8))

        btn_row = ttk.Frame(lf); btn_row.pack(fill="x")
        self._school_status = ttk.Label(btn_row, text="", foreground="green",
                                         font=("Tahoma", 10))
        self._school_status.pack(side="right", padx=12)

        def _save():
            cfg = load_config()
            for key, var in self._school_vars.items():
                v = (var.get() if key in ("school_gender", "school_stage")
                     else var.get().strip())
                cfg[key] = v
            try:
                with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                invalidate_config_cache()
                gender_lbl = "بنات" if cfg.get("school_gender") == "girls" else "بنين"
                self._school_status.config(
                    text=f"✅ تم الحفظ — النوع: {gender_lbl}", foreground="green")
                frame.after(3000, lambda: self._school_status.config(text=""))
                # تحديث عنوان النافذة فوراً ليعكس النوع الجديد
                _role_label = CURRENT_USER.get("label", "")
                _user_name  = CURRENT_USER.get("name", CURRENT_USER.get("username", ""))
                self.root.title(f"{get_window_title()} — {_user_name} ({_role_label})")
            except Exception as e:
                messagebox.showerror("خطأ", f"فشل الحفظ:\n{e}")

        def _reset():
            cfg = load_config()
            for key, var in self._school_vars.items():
                var.set(cfg.get(key, ""))
            self._school_status.config(text="تم إعادة التحميل", foreground="#555")
            frame.after(2000, lambda: self._school_status.config(text=""))

        ttk.Button(btn_row, text="💾 حفظ التغييرات", command=_save).pack(side="right", padx=4)
        ttk.Button(btn_row, text="🔄 إعادة تحميل", command=_reset).pack(side="right", padx=4)

        # ─ قسم أرقام واتساب المتعددة
        wa_lf = ttk.LabelFrame(frame,
            text=" 📱 خوادم واتساب المتعددة (لتوزيع الإرسال وتجنب الحجب) ",
            padding=12)
        wa_lf.pack(fill="x", padx=8, pady=(0,10))

        ttk.Label(wa_lf,
            text="أضف خادم واتساب لكل رقم — الرسائل تُوزَّع تلقائياً بالتناوب",
            foreground="#5A6A7E", font=("Tahoma",8)).pack(anchor="e", pady=(0,8))

        # جدول الخوادم
        wa_cols = ("port", "note")
        self._tree_wa_servers = ttk.Treeview(
            wa_lf, columns=wa_cols, show="headings", height=4)
        self._tree_wa_servers.heading("port", text="المنفذ (Port)")
        self._tree_wa_servers.heading("note", text="ملاحظة")
        self._tree_wa_servers.column("port", width=100, anchor="center")
        self._tree_wa_servers.column("note", width=250, anchor="center")
        self._tree_wa_servers.pack(fill="x", pady=(0,6))

        # أزرار
        wa_btn = ttk.Frame(wa_lf); wa_btn.pack(fill="x")
        port_var = tk.IntVar(value=3001)
        note_var = tk.StringVar(value="رقم 2")
        ttk.Label(wa_btn, text="المنفذ:").pack(side="right", padx=(0,4))
        ttk.Spinbox(wa_btn, from_=3000, to=3010,
                    textvariable=port_var, width=6).pack(side="right", padx=4)
        ttk.Label(wa_btn, text="ملاحظة:").pack(side="right", padx=(8,4))
        ttk.Entry(wa_btn, textvariable=note_var, width=14).pack(side="right", padx=4)
        ttk.Button(wa_btn, text="➕ إضافة",
                   command=lambda: self._wa_server_add(
                       port_var.get(), note_var.get())).pack(side="right", padx=4)
        ttk.Button(wa_btn, text="🗑️ حذف المحدد",
                   command=self._wa_server_del).pack(side="left", padx=4)

        ttk.Label(wa_lf,
            text="⚠️ المنفذ 3000 هو الافتراضي — أضف المنافذ الإضافية فقط (3001، 3002...)\n"
                 "لكل منفذ شغّل نسخة منفصلة من server.js على جهاز مختلف أو نفس الجهاز",
            foreground="#E65100", font=("Tahoma",8),
            justify="right").pack(anchor="e", pady=(8,0))

        self._wa_servers_load()

        # ─── قسم الترخيص (للمدير فقط، في وضع السيرفر) ────────────
        from config_manager import load_config as _lcfg
        role = CURRENT_USER.get("role")
        if role == "admin" and not _lcfg().get("cloud_mode", False):
            self._build_license_section(scroll)

        # ─── قسم إدارة الفصل الدراسي (للمدير فقط) ───────────────
        if role == "admin":
            self._build_term_management_section(scroll)

    def _build_term_management_section(self, parent_frame):
        """قسم إنهاء الفصل الدراسي ونهاية السنة — للمدير فقط."""

        sep = ttk.Separator(parent_frame, orient="horizontal")
        sep.pack(fill="x", padx=20, pady=(0, 8))

        lf = ttk.LabelFrame(parent_frame,
                             text=" 🔐 إدارة الفصل الدراسي — للمدير فقط ",
                             padding=16)
        lf.pack(fill="x", padx=20, pady=(0, 16))

        # تحذير
        warn = tk.Label(lf,
            text="⚠️  هذه الإجراءات لا يمكن التراجع عنها. ستُنشأ نسخة احتياطية تلقائياً قبل كل إجراء.",
            bg="#fff8e1", fg="#7c4a00", font=("Tahoma", 9),
            wraplength=700, justify="right", pady=6, padx=10, relief="flat")
        warn.pack(fill="x", pady=(0, 12))

        # ── الزر 1: نهاية الفصل الدراسي ──
        term_lf = ttk.LabelFrame(lf, text=" نهاية الفصل الدراسي ", padding=10)
        term_lf.pack(fill="x", pady=(0, 10))

        tk.Label(term_lf,
            text="يحذف جميع سجلات الغياب والتأخر ويبقي الطلاب والإعدادات والجداول كما هي.",
            font=("Tahoma", 9), fg="#555", wraplength=650, justify="right"
        ).pack(anchor="e", pady=(0, 8))

        ttk.Button(term_lf, text="📋 إنهاء الفصل الدراسي",
                   command=self._end_semester).pack(side="right")

        # ── الزر 2: نهاية السنة الدراسية ──
        year_lf = ttk.LabelFrame(lf, text=" نهاية السنة الدراسية ", padding=10)
        year_lf.pack(fill="x", pady=(0, 10))

        tk.Label(year_lf,
            text="يُرقّي الطلاب: أول→ثاني، ثاني→ثالث، ثالث يُحذفون. ثم يحذف كافة البيانات المستجدة (غياب، تأخر، حالات سلوكية، تحويلات، استفسارات، نتائج).",
            font=("Tahoma", 9), fg="#555", wraplength=650, justify="right"
        ).pack(anchor="e", pady=(0, 8))

        ttk.Button(year_lf, text="🎓 إنهاء السنة الدراسية وترقية الطلاب",
                   command=self._end_academic_year).pack(side="right")

        # ── النسخ الاحتياطية الخاصة بالفصول ──
        backup_lf = ttk.LabelFrame(lf, text=" 💾 نسخ احتياطية الفصول الدراسية ", padding=10)
        backup_lf.pack(fill="x", pady=(0,4))

        # أزرار في صف واحد: تحديث + فتح المجلد + استعادة
        btn_row2 = ttk.Frame(backup_lf); btn_row2.pack(fill="x", pady=(0, 4))
        ttk.Button(btn_row2, text="🔄 تحديث",
                   command=self._load_term_backups).pack(side="right", padx=4)
        ttk.Button(btn_row2, text="📂 فتح المجلد",
                   command=lambda: (
                       os.makedirs(os.path.join(BACKUP_DIR, "terms"), exist_ok=True),
                       os.startfile(os.path.join(BACKUP_DIR, "terms"))
                   )).pack(side="right", padx=4)
        tk.Button(btn_row2,
                   text="↩️ استعادة المحددة",
                   command=self._restore_term_backup,
                   bg="#c62828", fg="white",
                   font=("Tahoma", 9, "bold"),
                   relief="flat", cursor="hand2").pack(side="right", padx=4)

        # القائمة
        list_frame = ttk.Frame(backup_lf)
        list_frame.pack(fill="x")
        sb = ttk.Scrollbar(list_frame, orient="vertical")
        self._term_backup_list = tk.Listbox(list_frame, height=6,
                                             font=("Courier", 9), selectmode="single",
                                             bg="#f9f9f9",
                                             yscrollcommand=sb.set)
        sb.config(command=self._term_backup_list.yview)
        sb.pack(side="right", fill="y")
        self._term_backup_list.pack(side="left", fill="x", expand=True)

        parent_frame.after(200, self._load_term_backups)

    def _build_update_settings_section(self, parent_frame):
        """قسم التحديثات التلقائية — للمدير فقط."""
        sep = ttk.Separator(parent_frame, orient="horizontal")
        sep.pack(fill="x", padx=20, pady=(0, 8))

        lf = ttk.LabelFrame(parent_frame, text=" ⚡ التحديثات التلقائية المجدولة ", padding=16)
        lf.pack(fill="x", padx=20, pady=(0, 16))

        cfg = load_config()
        
        # خيار تفعيل/تعطيل التحديث التلقائي
        row1 = ttk.Frame(lf); row1.pack(fill="x", pady=4)
        self._auto_update_var = tk.BooleanVar(value=cfg.get("auto_update_enabled", False))
        cb = ttk.Checkbutton(row1, text="تفعيل التحديث التلقائي للملفات البرمجية", 
                             variable=self._auto_update_var)
        cb.pack(side="right")
        
        # اختيار الساعة
        row2 = ttk.Frame(lf); row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="وقت التحديث (الساعة):", font=("Tahoma", 10)).pack(side="right", padx=(0, 8))
        self._auto_update_hour_var = tk.IntVar(value=cfg.get("auto_update_hour", 3))
        spin = ttk.Spinbox(row2, from_=0, to=23, textvariable=self._auto_update_hour_var, width=5)
        spin.pack(side="right", padx=4)
        ttk.Label(row2, text="فجراً/صباحاً (نظام 24 ساعة)", font=("Tahoma", 8), foreground="#666").pack(side="right")
        
        # ملاحظة
        tk.Label(lf, text="💡 سيقوم البرنامج بالتحقق من وجود تحديثات في الساعة المحددة وتثبيتها تلقائياً ثم إعادة تشغيل البرنامج.\nتأكد من ترك البرنامج مفتوحاً على السيرفر لتنفيذ التحديث.",
                 font=("Tahoma", 8), fg="#1e40af", bg="#eff6ff", justify="right", padx=10, pady=6).pack(fill="x", pady=10)
        
        # زر الحفظ الخاص بالقسم (أو نعتمد على زر الحفظ الرئيسي؟ يفضل زر هنا لسهولة التجربة)
        def _save_update_cfg():
            c = load_config()
            c["auto_update_enabled"] = self._auto_update_var.get()
            c["auto_update_hour"] = self._auto_update_hour_var.get()
            from constants import CONFIG_JSON
            try:
                with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                    json.dump(c, f, ensure_ascii=False, indent=2)
                invalidate_config_cache()
                messagebox.showinfo("نجاح", "تم حفظ إعدادات التحديث التلقائي.")
            except Exception as e:
                messagebox.showerror("خطأ", f"فشل الحفظ: {e}")

        ttk.Button(lf, text="💾 حفظ إعدادات التحديث", command=_save_update_cfg).pack(side="right", pady=5)
        
        # زر التحقق اليدوي
        from updater import check_for_updates
        ttk.Button(lf, text="🔍 التحقق من وجود تحديث الآن", 
                   command=lambda: check_for_updates(self.root, silent=False)).pack(side="left", pady=5)

    def _load_term_backups(self):
        """يحمّل قائمة نسخ الفصول الاحتياطية."""
        if not hasattr(self, "_term_backup_list"):
            return
        self._term_backup_list.delete(0, "end")
        terms_dir = os.path.join(BACKUP_DIR, "terms")
        if not os.path.exists(terms_dir):
            self._term_backup_list.insert("end", "(لا توجد نسخ احتياطية بعد)")
            return
        files = sorted(
            [f for f in os.listdir(terms_dir) if f.endswith(".zip")],
            reverse=True
        )
        if not files:
            self._term_backup_list.insert("end", "(لا توجد نسخ احتياطية بعد)")
            return
        for f in files:
            size = os.path.getsize(os.path.join(terms_dir, f)) // 1024
            self._term_backup_list.insert("end", f"  {f}   ({size} KB)")

    def _create_term_backup(self, label: str) -> tuple:
        """ينشئ نسخة احتياطية خاصة بالفصل/السنة."""
        terms_dir = os.path.join(BACKUP_DIR, "terms")
        os.makedirs(terms_dir, exist_ok=True)
        ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(terms_dir, f"{label}_{ts}.zip")
        try:
            with zipfile.ZipFile(fname, "w", zipfile.ZIP_DEFLATED) as zf:
                if os.path.exists(DB_PATH):
                    zf.write(DB_PATH, os.path.basename(DB_PATH))
                for jf in [STUDENTS_JSON, TEACHERS_JSON, CONFIG_JSON]:
                    if os.path.exists(jf):
                        zf.write(jf, os.path.basename(jf))
            return True, fname
        except Exception as e:
            return False, str(e)

    def _end_semester(self):
        """إنهاء الفصل الدراسي — حذف الغياب والتأخر فقط."""
        if CURRENT_USER.get("role") != "admin":
            messagebox.showerror("غير مسموح", "هذا الإجراء للمدير فقط.")
            return

        # تأكيد مزدوج
        if not messagebox.askyesno("تأكيد إنهاء الفصل",
            "سيتم حذف جميع سجلات الغياب والتأخر.\nستُنشأ نسخة احتياطية تلقائياً قبل الحذف.\n\nهل أنت متأكد؟", icon="warning"):
            return

        pw = simpledialog.askstring("تأكيد الهوية",
            "أدخل كلمة مرور حسابك للمتابعة:", show="*")
        if not pw:
            return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        # نسخة احتياطية
        ok, path = self._create_term_backup("نهاية_فصل")
        if not ok:
            messagebox.showerror("خطأ", "فشل إنشاء النسخة الاحتياطية:\n" + str(path))
            return

        # حذف بيانات الفصل
        try:
            clear_yearly_data(reset_type='term')

            global STUDENTS_STORE
            STUDENTS_STORE = None

            messagebox.showinfo("تم", "✅ تم إنهاء الفصل الدراسي وتصفير البيانات (الغياب، التأخر، السلوك، التحويلات، الاستفسارات) بنجاح.\nالنسخة الاحتياطية: " + os.path.basename(path))
            self._load_term_backups()
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل الحذف:\n{e}")

    def _end_academic_year(self):
        """إنهاء السنة الدراسية — ترقية الطلاب + حذف الغياب والتأخر."""
        if CURRENT_USER.get("role") != "admin":
            messagebox.showerror("غير مسموح", "هذا الإجراء للمدير فقط.")
            return

        if not messagebox.askyesno("تأكيد إنهاء السنة",
            "سيتم:\n• ترقية طلاب أول ثانوي → ثاني ثانوي\n• ترقية طلاب ثاني ثانوي → ثالث ثانوي\n• حذف طلاب ثالث ثانوي من البرنامج\n• حذف جميع سجلات الغياب والتأخر\n\nستُنشأ نسخة احتياطية تلقائياً قبل الإجراء.\n\nهل أنت متأكد؟", icon="warning"):
            return

        pw = simpledialog.askstring("تأكيد الهوية",
            "أدخل كلمة مرور حسابك للمتابعة:", show="*")
        if not pw:
            return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        # نسخة احتياطية
        ok, path = self._create_term_backup("نهاية_سنة")
        if not ok:
            messagebox.showerror("خطأ", "فشل إنشاء النسخة الاحتياطية:\n" + str(path))
            return

        # ── ترقية الطلاب ──
        try:
            store = load_students(force_reload=True)
            classes = store["list"]

            # خريطة الترقية: ID الفصل → المستوى والقسم
            # نفترض أن ID الفصل بصيغة "1-أ", "2-ب", "3-ج" إلخ
            upgraded = 0
            deleted  = 0
            errors   = []

            # جمّع الطلاب حسب المستوى
            level1_classes = [c for c in classes if str(c["id"]).startswith("1-")]
            level2_classes = [c for c in classes if str(c["id"]).startswith("2-")]
            level3_classes = [c for c in classes if str(c["id"]).startswith("3-")]

            # 1. احذف طلاب المستوى 3
            for cls in level3_classes:
                deleted += len(cls["students"])
                cls["students"] = []

            # 2. انقل طلاب المستوى 2 → المستوى 3
            for cls2 in level2_classes:
                suffix = str(cls2["id"])[2:]  # مثلاً "أ" من "2-أ"
                target_id = f"3-{suffix}"
                target = next((c for c in level3_classes if c["id"] == target_id), None)
                if target:
                    target["students"] = cls2["students"]
                    upgraded += len(cls2["students"])
                    cls2["students"] = []
                else:
                    errors.append(f"لم يُوجد فصل {target_id}")

            # 3. انقل طلاب المستوى 1 → المستوى 2
            for cls1 in level1_classes:
                suffix = str(cls1["id"])[2:]
                target_id = f"2-{suffix}"
                target = next((c for c in level2_classes if c["id"] == target_id), None)
                if target:
                    target["students"] = cls1["students"]
                    upgraded += len(cls1["students"])
                    cls1["students"] = []
                else:
                    errors.append(f"لم يُوجد فصل {target_id}")

            # احفظ الطلاب المُحدَّثين
            with open(STUDENTS_JSON, "w", encoding="utf-8") as f:
                json.dump({"classes": classes}, f, ensure_ascii=False, indent=2)

            global STUDENTS_STORE
            STUDENTS_STORE = None

            # احذف بيانات السنة
            clear_yearly_data(reset_type='year')

            msg = ("✅ تمت إنهاء السنة الدراسية بنجاح وتصفير كافة السجلات.\n\n"
                   f"• طلاب مُرقَّون: {upgraded}\n"
                   f"• طلاب محذوفون (ثالث): {deleted}\n"
                   f"• النسخة الاحتياطية: {os.path.basename(path)}")
            if errors:
                msg += "\n\n⚠️ تحذيرات:\n" + "\n".join(errors)
            messagebox.showinfo("تم", msg)
            self._load_term_backups()
            self.update_all_tabs_after_data_change()

        except Exception as e:
            messagebox.showerror("خطأ", f"فشل ترقية الطلاب:\n{e}")

    def _restore_term_backup(self):
        """استعادة نسخة احتياطية من نسخ الفصول."""
        if CURRENT_USER.get("role") != "admin":
            messagebox.showerror("غير مسموح", "هذا الإجراء للمدير فقط.")
            return

        sel = self._term_backup_list.curselection()
        if not sel:
            messagebox.showwarning("تنبيه", "اختر نسخة احتياطية من القائمة أولاً.")
            return

        item = self._term_backup_list.get(sel[0]).strip()
        if item.startswith("("):
            return

        fname = item.split("(")[0].strip()
        terms_dir = os.path.join(BACKUP_DIR, "terms")
        fpath = os.path.join(terms_dir, fname)

        if not os.path.exists(fpath):
            messagebox.showerror("خطأ", "الملف غير موجود.")
            return

        if not messagebox.askyesno("تأكيد الاستعادة",
            f"سيتم استبدال جميع البيانات الحالية بالنسخة:\n{fname}\n\nهل أنت متأكد؟", icon="warning"):
            return

        pw = simpledialog.askstring("تأكيد الهوية",
            "أدخل كلمة مرور حسابك للمتابعة:", show="*")
        if not pw:
            return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        try:
            # نسخة احتياطية من الوضع الحالي قبل الاستعادة
            self._create_term_backup("قبل_استعادة")

            with zipfile.ZipFile(fpath, "r") as zf:
                # استعد DB
                if "absences.db" in zf.namelist():
                    zf.extract("absences.db", os.path.dirname(DB_PATH))
                # استعد JSON
                for jname in ["students.json", "teachers.json", "config.json"]:
                    if jname in zf.namelist():
                        zf.extract(jname, DATA_DIR)

            global STUDENTS_STORE
            STUDENTS_STORE = None
            invalidate_config_cache()

            messagebox.showinfo("تم", f"✅ تمت الاستعادة بنجاح من:\n{fname}\n\nأعد تشغيل البرنامج لتطبيق التغييرات.")
            try:
                self.update_all_tabs_after_data_change()
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل الاستعادة:\n{e}")

    def _build_backup_tab(self):
        frame = self.backup_frame

        ttk.Label(frame, text="النسخ الاحتياطية",
                  font=("Tahoma",13,"bold")).pack(pady=(12,4))

        ctrl = ttk.Frame(frame); ctrl.pack(fill="x", padx=10, pady=8)
        ttk.Button(ctrl, text="💾 نسخ احتياطي الآن",
                   command=self._do_backup).pack(side="right", padx=4)
        ttk.Button(ctrl, text="📂 فتح مجلد النسخ",
                   command=self._open_backup_dir).pack(side="right", padx=4)
        ttk.Button(ctrl, text="🗑️ حذف المحدد",
                   command=self._delete_backup).pack(side="right", padx=4)

        # معلومات المجلد
        info = ttk.LabelFrame(frame, text=" إعدادات النسخ الاحتياطية ", padding=10)
        info.pack(fill="x", padx=10, pady=4)

        r1 = ttk.Frame(info); r1.pack(fill="x", pady=3)
        ttk.Label(r1, text="مجلد الحفظ:", width=16, anchor="e").pack(side="right")
        self.backup_dir_var = tk.StringVar(value=os.path.abspath(BACKUP_DIR))
        ttk.Entry(r1, textvariable=self.backup_dir_var, state="readonly",
                  font=("Courier",9)).pack(side="right", fill="x", expand=True, padx=4)
        ttk.Button(r1, text="تغيير", width=8,
                   command=self._change_backup_dir).pack(side="left")

        r2 = ttk.Frame(info); r2.pack(fill="x", pady=3)
        ttk.Label(r2, text="النسخ كل:", width=16, anchor="e").pack(side="right")
        self.backup_interval_var = tk.StringVar(value="24")
        ttk.Spinbox(r2, from_=1, to=168, textvariable=self.backup_interval_var,
                    width=6).pack(side="right", padx=4)
        ttk.Label(r2, text="ساعة").pack(side="right")

        self.backup_status = ttk.Label(frame, text="", foreground="green",
                                        font=("Tahoma",10))
        self.backup_status.pack(pady=4)

        # سجل النسخ
        ttk.Label(frame, text="سجل النسخ السابقة:",
                  font=("Tahoma",10,"bold")).pack(anchor="e", padx=10)
        cols = ("filename","size_kb","created_at")
        self.tree_backup = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        for col, hdr, w in zip(cols,
            ["اسم الملف","الحجم (KB)","تاريخ الإنشاء"],
            [280,100,200]):
            self.tree_backup.heading(col, text=hdr)
            self.tree_backup.column(col, width=w, anchor="center")
        self.tree_backup.pack(fill="both", expand=True, padx=10, pady=5)
        frame.after(100, self._backup_load)

    def _backup_load(self):
        if not hasattr(self,"tree_backup"): return
        for i in self.tree_backup.get_children(): self.tree_backup.delete(i)
        for b in get_backup_list():
            self.tree_backup.insert("","end",
                values=(os.path.basename(b["filename"]),
                        b.get("size_kb",0),
                        b["created_at"][:19]))

    def _do_backup(self):
        backup_dir = self.backup_dir_var.get() if hasattr(self,"backup_dir_var") else BACKUP_DIR
        ok, path, size = create_backup(backup_dir)
        if ok:
            self.backup_status.config(
                text=f"✅ تم إنشاء النسخة: {os.path.basename(path)} ({size} KB)",
                foreground="green")
            frame.after(100, self._backup_load)
        else:
            self.backup_status.config(text=f"❌ فشل: {path}", foreground="red")

    def _open_backup_dir(self):
        d = self.backup_dir_var.get() if hasattr(self,"backup_dir_var") else BACKUP_DIR
        os.makedirs(d, exist_ok=True)
        try: os.startfile(os.path.abspath(d))
        except Exception: webbrowser.open(f"file://{os.path.abspath(d)}")

    def _change_backup_dir(self):
        d = filedialog.askdirectory(title="اختر مجلد النسخ الاحتياطية")
        if d and hasattr(self,"backup_dir_var"):
            self.backup_dir_var.set(d)

    def _delete_backup(self):
        from database import authenticate
        from constants import CURRENT_USER
        from tkinter import simpledialog
        sel = self.tree_backup.selection()
        if not sel: messagebox.showwarning("تنبيه","حدد نسخة"); return
        fname = self.tree_backup.item(sel[0])["values"][0]
        d = self.backup_dir_var.get() if hasattr(self,"backup_dir_var") else BACKUP_DIR
        full_path = os.path.join(d, fname)
        if not messagebox.askyesno("تأكيد",f"حذف النسخة: {fname}؟"): return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        try:
            if os.path.exists(full_path): os.remove(full_path)
            messagebox.showinfo("تم","تم حذف النسخة الاحتياطية")
            self.backup_frame.after(100, self._backup_load)
        except Exception as e:
            messagebox.showerror("خطأ",str(e))




    def _build_license_section(self, parent):
        """قسم الترخيص — يظهر فقط إذا لم يكن البرنامج مفعّلاً."""
        from license_manager import LicenseClient, TRIAL_FILE, TRIAL_DAYS
        import datetime, json as _j

        client = LicenseClient()

        # لا تُظهر القسم إذا كان البرنامج مفعّلاً
        if client.is_activated():
            return

        lf = ttk.LabelFrame(parent, text=" 🔐 الترخيص والتفعيل ", padding=16)
        lf.pack(fill="x", padx=20, pady=(0, 16))

        # حساب أيام التجربة
        try:
            if os.path.exists(TRIAL_FILE):
                with open(TRIAL_FILE, "r", encoding="utf-8") as f:
                    tdata = _j.load(f)
                start = datetime.datetime.fromisoformat(tdata["start"])
                days_left = max(0, TRIAL_DAYS - (datetime.datetime.utcnow() - start).days)
            else:
                days_left = TRIAL_DAYS
        except Exception:
            days_left = TRIAL_DAYS

        status_text  = "⏳ فترة التجربة — متبقي {} يوم".format(days_left) if days_left > 0 else "❌ انتهت فترة التجربة"
        status_color = "#d97706" if days_left > 0 else "#dc2626"

        self._lic_status_lbl = tk.Label(lf, text=status_text, fg=status_color,
                                         font=("Tahoma", 11, "bold"))
        self._lic_status_lbl.pack(anchor="e", pady=(0, 10))

        row = tk.Frame(lf); row.pack(fill="x", pady=4)
        tk.Label(row, text="مفتاح الترخيص:", font=("Tahoma", 10, "bold"),
                 width=18, anchor="e").pack(side="right")
        self._lic_key_var = tk.StringVar()
        tk.Entry(row, textvariable=self._lic_key_var,
                 font=("Courier", 12), justify="center", width=26).pack(side="right", padx=8)

        row2 = tk.Frame(lf); row2.pack(fill="x", pady=4)
        tk.Label(row2, text="اسم المدرسة:", font=("Tahoma", 10),
                 width=18, anchor="e").pack(side="right")
        self._lic_school_var = tk.StringVar()
        tk.Entry(row2, textvariable=self._lic_school_var,
                 font=("Tahoma", 10), justify="right", width=26).pack(side="right", padx=8)

        self._lic_msg_lbl = tk.Label(lf, text="", font=("Tahoma", 9))
        self._lic_msg_lbl.pack(anchor="e", pady=4)

        tk.Button(lf, text="✅ تفعيل البرنامج",
                  bg="#1565C0", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", padx=20, pady=6, cursor="hand2",
                  command=self._do_activate).pack(anchor="e")

    def _do_activate(self):
        from license_manager import LicenseClient
        import threading as _th
        key    = self._lic_key_var.get().strip()
        school = self._lic_school_var.get().strip()
        if not key:
            self._lic_msg_lbl.config(text="أدخل مفتاح الترخيص", fg="#dc2626"); return
        self._lic_msg_lbl.config(text="⏳ جارٍ التحقق...", fg="#1565C0")
        def _run():
            client = LicenseClient()
            ok, msg, _ = client.activate(key, school)
            def _done():
                if ok:
                    self._lic_msg_lbl.config(text=msg, fg="#16a34a")
                    self._lic_status_lbl.config(
                        text="✅ مفعّل — {}".format(school or ""), fg="#16a34a")
                else:
                    self._lic_msg_lbl.config(text=msg, fg="#dc2626")
            self._lic_msg_lbl.after(0, _done)
        _th.Thread(target=_run, daemon=True).start()

    def _wa_servers_load(self):
        if not hasattr(self, "_tree_wa_servers"): return
        for i in self._tree_wa_servers.get_children(): self._tree_wa_servers.delete(i)
        cfg = load_config()
        servers = cfg.get("wa_servers", [])
        for s in servers:
            self._tree_wa_servers.insert("", "end", values=(s.get("port", 3000), s.get("note", "")))

    def _wa_server_add(self, port, note):
        try:
            p = int(port)
        except: messagebox.showerror("خطأ", "المنفذ يجب أن يكون رقماً"); return
        cfg = load_config()
        svs = cfg.get("wa_servers", [])
        if any(str(s.get("port")) == str(p) for s in svs):
            messagebox.showwarning("تنبيه", "هذا المنفذ مضاف بالفعل"); return
        svs.append({"port": p, "note": note})
        cfg["wa_servers"] = svs
        save_config(cfg)
        invalidate_config_cache()
        self._wa_servers_load()

    def _wa_server_del(self):
        sel = self._tree_wa_servers.selection()
        if not sel: return
        val = self._tree_wa_servers.item(sel[0])["values"]
        port = str(val[0])
        if not messagebox.askyesno("تأكيد", f"حذف خادم المنفذ {port}؟"): return
        cfg = load_config()
        svs = cfg.get("wa_servers", [])
        new_svs = [s for s in svs if str(s.get("port")) != port]
        cfg["wa_servers"] = new_svs
        save_config(cfg)
        invalidate_config_cache()
        self._wa_servers_load()
