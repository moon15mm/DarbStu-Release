# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
import constants
from constants import ROLES, ROLE_TABS
from database import (create_user, delete_user, get_all_users,
                       save_user_allowed_tabs, toggle_user_active,
                       update_user_password, DB_PATH)

class UsersTabMixin:
    """Mixin: UsersTabMixin"""
    def _build_users_tab(self):
        frame = self.users_frame

        # ─ العنوان
        hdr = tk.Frame(frame, bg="#7C3AED", height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="👥 إدارة المستخدمين وصلاحيات التبويبات",
                 bg="#7C3AED", fg="white",
                 font=("Tahoma",12,"bold")).pack(side="right", padx=14, pady=10)

        # ─ تقسيم رأسي: قائمة المستخدمين + لوحة الصلاحيات
        paned = ttk.PanedWindow(frame, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        # ══ الجانب الأيمن: قائمة المستخدمين ═════════════════════
        left_lf = ttk.LabelFrame(paned, text=" قائمة المستخدمين ", padding=6)
        paned.add(left_lf, weight=2)

        ctrl = ttk.Frame(left_lf); ctrl.pack(fill="x", pady=(0,6))
        ttk.Button(ctrl, text="➕ جديد",
                   command=self._user_add_dialog).pack(side="right", padx=3)
        ttk.Button(ctrl, text="🔑 كلمة المرور",
                   command=self._user_change_pw).pack(side="right", padx=3)
        ttk.Button(ctrl, text="🔄 تفعيل/تعطيل",
                   command=self._user_toggle).pack(side="right", padx=3)
        ttk.Button(ctrl, text="🗑️ حذف",
                   command=self._user_delete).pack(side="right", padx=3)
        ttk.Button(ctrl, text="📤 إرسال بيانات الدخول",
                   command=self._user_send_teacher_creds).pack(side="right", padx=3)
        ttk.Button(ctrl, text="⚙️ توليد حسابات المعلمين",
                   command=self._user_generate_teachers).pack(side="right", padx=3)
        ttk.Button(ctrl, text="✏️ تعديل",
                   command=self._user_edit_dialog).pack(side="right", padx=3)
        ttk.Button(ctrl, text="📲 إرسال للمحدد",
                   command=self._user_send_individual_creds).pack(side="right", padx=3)

        cols = ("id","username","full_name","role","active","last_login","tabs_info")
        self.tree_users = ttk.Treeview(left_lf, columns=cols,
                                        show="headings", height=16)
        for col, hdr_t, w in zip(cols,
            ["ID","اسم المستخدم","الاسم الكامل","الدور","الحالة","آخر ظهور","التبويبات"],
            [35, 120, 150, 80, 50, 130, 90]):
            self.tree_users.heading(col, text=hdr_t)
            self.tree_users.column(col, width=w, anchor="center")
        self.tree_users.tag_configure("inactive",  foreground="#9E9E9E")
        self.tree_users.tag_configure("admin_row", foreground="#7C3AED",
                                       font=("Tahoma",10,"bold"))
        self.tree_users.tag_configure("custom",    foreground="#1565C0")
        sb = ttk.Scrollbar(left_lf, orient="vertical",
                            command=self.tree_users.yview)
        self.tree_users.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree_users.pack(side="left", fill="both", expand=True)
        self.tree_users.bind("<<TreeviewSelect>>", self._on_user_select)

        # ══ الجانب الأيسر: صلاحيات التبويبات ════════════════════
        right_lf = ttk.LabelFrame(paned, text=" صلاحيات التبويبات ", padding=8)
        paned.add(right_lf, weight=3)

        self._tabs_perm_user_lbl = ttk.Label(
            right_lf,
            text="← اختر مستخدماً من القائمة",
            font=("Tahoma",11,"bold"), foreground="#5A6A7E")
        self._tabs_perm_user_lbl.pack(pady=(4,8))

        hint = ttk.Label(right_lf,
            text="✅ مُفعَّل  |  ☐ مُعطَّل  —  المدير يرى كل التبويبات دائماً",
            foreground="#5A6A7E", font=("Tahoma",9))
        hint.pack(anchor="e", pady=(0,6))

        # أزرار تحديد سريع
        quick = ttk.Frame(right_lf); quick.pack(fill="x", pady=(0,8))
        ttk.Button(quick, text="تحديد الكل",
                   command=self._tabs_select_all).pack(side="right", padx=3)
        ttk.Button(quick, text="إلغاء الكل",
                   command=self._tabs_deselect_all).pack(side="right", padx=3)
        ttk.Button(quick, text="افتراضي للدور",
                   command=self._tabs_reset_to_role).pack(side="right", padx=3)
        self._tabs_save_btn = ttk.Button(
            quick, text="💾 حفظ الصلاحيات",
            command=self._tabs_save, state="disabled")
        self._tabs_save_btn.pack(side="left", padx=3)

        ttk.Separator(right_lf, orient="horizontal").pack(fill="x", pady=(0,8))

        # شبكة checkboxes للتبويبات
        all_tabs_list = [
            # يومي
            "لوحة المراقبة",        "روابط الفصول",         "التأخر",
            "الأعذار",               "الاستئذان",             "المراقبة الحية",
            "الموجّه الطلابي",       "استلام تحويلات",
            # السجلات
            "السجلات / التصدير",    "إدارة الغياب",          "التقارير / الطباعة",
            "تقرير الفصل",           "تقرير الإدارة",         "نشر النتائج",           
            "تحليل النتائج",         "تصدير نور",            "الإشعارات الذكية",
            "الطلاب المستثنون",      "أكثر الطلاب غياباً",
            # الرسائل
            "إرسال رسائل الغياب",   "إرسال رسائل التأخر",    "مستلمو التأخر",
            "جدولة الروابط",         "إدارة الواتساب",       "قصص المدرسة",
            "تعزيز الحضور الأسبوعي", "زيارات أولياء الأمور", "روابط بوابة أولياء الأمور",
            # البيانات
            "إدارة الطلاب",          "إضافة طالب",            "إدارة الفصول",
            "إدارة أرقام الجوالات",
            # أدوات المعلم
            "تحويل طالب",            "نماذج المعلم",          "خطابات الاستفسار",
            "التعاميم والنشرات",     "لوحة الصدارة (النقاط)", "تحليل طالب",
            # الإعدادات
            "إعدادات المدرسة",       "المستخدمون",            "النسخ الاحتياطية",
        ]
        # أزل المكررات مع الحفاظ على الترتيب
        seen_tabs = set()
        self._all_tabs = []
        for t in all_tabs_list:
            if t not in seen_tabs:
                seen_tabs.add(t); self._all_tabs.append(t)

        self._tab_vars = {}
        scroll_frame_outer = ttk.Frame(right_lf)
        scroll_frame_outer.pack(fill="both", expand=True)

        sb2    = ttk.Scrollbar(scroll_frame_outer, orient="vertical")
        self._tabs_canvas = tk.Canvas(scroll_frame_outer, highlightthickness=0, bg="white",
                                      yscrollcommand=sb2.set)
        canvas = self._tabs_canvas
        sb2.configure(command=canvas.yview)
        self._tabs_inner = ttk.Frame(canvas)

        _tabs_win = canvas.create_window((0,0), window=self._tabs_inner, anchor="nw")
        self._tabs_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _tabs_last_w = [0]
        def _on_tabs_canvas_conf(e):
            w = canvas.winfo_width()
            if w == _tabs_last_w[0]: return
            _tabs_last_w[0] = w
            canvas.itemconfig(_tabs_win, width=w)
        canvas.bind("<Configure>", _on_tabs_canvas_conf)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
        sb2.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # بناء checkboxes في شبكة عمودين
        COLS = 2
        for idx, tab_name in enumerate(self._all_tabs):
            var = tk.BooleanVar(value=False)
            self._tab_vars[tab_name] = var
            r, c = divmod(idx, COLS)
            cb = ttk.Checkbutton(
                self._tabs_inner,
                text=tab_name,
                variable=var,
                command=self._on_tab_perm_change)
            cb.grid(row=r, column=c, sticky="w",
                    padx=12, pady=4, ipadx=4)

        for c in range(COLS):
            self._tabs_inner.columnconfigure(c, weight=1)

        self._current_perm_user = None
        frame.after(100, self._users_load)

    def _users_load(self):
        if not hasattr(self,"tree_users"): return
        
        # 1. عرض البيانات المخزنة مؤقتاً فوراً (إن وجدت) لتجنب البطء
        if hasattr(constants, "_USERS_CACHE") and constants._USERS_CACHE:
            self._users_fill_ui(constants._USERS_CACHE)

        def _fetch_task():
            try:
                users = get_all_users()
                # 2. تحديث التخزين المؤقت بالبيانات الجديدة من السيرفر
                constants._USERS_CACHE = users
                self.root.after(0, lambda: self._users_fill_ui(users))
            except Exception as e:
                print(f"[USERS-LOAD-ERROR] {e}")

        threading.Thread(target=_fetch_task, daemon=True).start()

    def _users_fill_ui(self, users):
        if not hasattr(self,"tree_users") or not self.tree_users.winfo_exists(): return
        for i in self.tree_users.get_children(): self.tree_users.delete(i)
        import json as _j
        for u in users:
            tag = "admin_row" if u["role"]=="admin" else (
                  "inactive"  if not u["active"] else "")
            role_label  = ROLES.get(u["role"],{}).get("label", u["role"])
            active_lbl  = "✅" if u["active"] else "❌"
            
            # معلومة التبويبات
            if u["role"] == "admin":
                tabs_info = "كل التبويبات"
                tag = "admin_row"
            elif u.get("allowed_tabs"):
                try:
                    tlist = _j.loads(u["allowed_tabs"])
                    tabs_info = "{} تبويب".format(len(tlist))
                    tag = "custom"
                except:
                    tabs_info = "افتراضي"
            else:
                tabs_info = "افتراضي"
            
            # وقت آخر دخول
            login_time = u.get("last_login")
            if not login_time:
                login_time = "⚠️ لم يفعّل بعد"
            
            self.tree_users.insert("","end", tags=(tag,),
                values=(u["id"], u["username"],
                        u.get("full_name",""),
                        role_label, active_lbl, login_time, tabs_info))

    def _on_user_select(self, event=None):
        """عند اختيار مستخدم — حمّل صلاحياته في checkboxes."""
        sel = self.tree_users.selection()
        if not sel: return
        vals     = self.tree_users.item(sel[0], "values")
        username = vals[1]
        role_lbl = vals[3]
        is_admin = (role_lbl == "مدير")

        self._current_perm_user = username
        self._tabs_save_btn.configure(state="disabled")
        label = "{} — {}".format(vals[2] or username, role_lbl)
        self._tabs_perm_user_lbl.configure(
            text="تبويبات المستخدم: " + label,
            foreground="#1565C0" if not is_admin else "#7C3AED")

        def _fetch():
            import json as _j, sqlite3 as _sq
            con = _sq.connect(DB_PATH); con.row_factory = _sq.Row; cur = con.cursor()
            cur.execute("SELECT role, allowed_tabs FROM users WHERE username=?", (username,))
            row = cur.fetchone(); con.close()
            self.root.after(0, lambda: self._apply_user_perms(row, is_admin))

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_user_perms(self, row, is_admin):
        """يُطبَّق بعد جلب البيانات في الخلفية."""
        import json as _j
        if not row: return

        # تعطيل Configure وcommand مؤقتاً لمنع التقطيع
        self._tabs_inner.unbind("<Configure>")
        for cb in self._tabs_inner.winfo_children():
            if isinstance(cb, ttk.Checkbutton):
                cb.configure(command="")

        try:
            if row["role"] == "admin":
                for var in self._tab_vars.values(): var.set(True)
                for cb in self._tabs_inner.winfo_children():
                    if isinstance(cb, ttk.Checkbutton):
                        cb.configure(state="disabled")
            else:
                for cb in self._tabs_inner.winfo_children():
                    if isinstance(cb, ttk.Checkbutton):
                        cb.configure(state="normal")
                if row["allowed_tabs"]:
                    try:    allowed = set(_j.loads(row["allowed_tabs"]))
                    except: allowed = set(ROLE_TABS.get(row["role"]) or [])
                else:
                    allowed = set(ROLE_TABS.get(row["role"]) or [])
                for tab_name, var in self._tab_vars.items():
                    var.set(tab_name in allowed)
                if not is_admin:
                    self._tabs_save_btn.configure(state="normal")
        finally:
            for cb in self._tabs_inner.winfo_children():
                if isinstance(cb, ttk.Checkbutton):
                    cb.configure(command=self._on_tab_perm_change)
            self._tabs_inner.bind("<Configure>",
                lambda e: self._tabs_canvas.configure(
                    scrollregion=self._tabs_canvas.bbox("all")))
            self._tabs_canvas.configure(
                scrollregion=self._tabs_canvas.bbox("all"))

    def _on_tab_perm_change(self):
        """عند تغيير أي checkbox."""
        if self._current_perm_user:
            self._tabs_save_btn.configure(state="normal")

    def _tabs_select_all(self):
        if not self._current_perm_user: return
        for var in self._tab_vars.values(): var.set(True)
        self._tabs_save_btn.configure(state="normal")

    def _tabs_deselect_all(self):
        if not self._current_perm_user: return
        for var in self._tab_vars.values(): var.set(False)
        self._tabs_save_btn.configure(state="normal")

    def _tabs_reset_to_role(self):
        """إعادة التبويبات لافتراضيات الدور."""
        if not self._current_perm_user: return
        import sqlite3 as _sq
        con = _sq.connect(DB_PATH); con.row_factory = _sq.Row; cur = con.cursor()
        cur.execute("SELECT role FROM users WHERE username=?",
                    (self._current_perm_user,))
        row = cur.fetchone(); con.close()
        if not row: return
        role_tabs = ROLE_TABS.get(row["role"])
        allowed   = set(role_tabs) if role_tabs else set(self._all_tabs)
        for tab_name, var in self._tab_vars.items():
            var.set(tab_name in allowed)
        self._tabs_save_btn.configure(state="normal")

    def _tabs_save(self):
        """حفظ صلاحيات التبويبات للمستخدم المحدد."""
        if not self._current_perm_user:
            messagebox.showwarning("تنبيه","اختر مستخدماً أولاً"); return
        selected = [t for t, v in self._tab_vars.items() if v.get()]
        if not selected:
            if not messagebox.askyesno("تأكيد",
                "لم تختر أي تبويب — هل تريد حفظ (لن يرى المستخدم أي تبويب)؟"):
                return
        save_user_allowed_tabs(self._current_perm_user, selected)
        self._tabs_save_btn.configure(state="disabled")
        self.users_frame.after(100, self._users_load)
        messagebox.showinfo("تم",
            "تم حفظ {} تبويب للمستخدم '{}'".format(
                len(selected), self._current_perm_user))



    def _user_add_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("مستخدم جديد")
        win.geometry("400x360")
        win.transient(self.root); win.grab_set()

        ttk.Label(win, text="إنشاء مستخدم جديد",
                  font=("Tahoma",12,"bold")).pack(pady=(14,8))
        form = ttk.Frame(win, padding=16); form.pack(fill="both")

        fields = {}
        for lbl, key, show in [
            ("اسم المستخدم *","username",""),
            ("الاسم الكامل","full_name",""),
            ("كلمة المرور *","password","●"),
            ("تأكيد كلمة المرور","confirm","●"),
        ]:
            f = ttk.Frame(form); f.pack(fill="x", pady=4)
            ttk.Label(f, text=lbl, width=18, anchor="e").pack(side="right")
            var = tk.StringVar()
            e = ttk.Entry(f, textvariable=var, show=show, justify="right")
            e.pack(side="right", fill="x", expand=True)
            fields[key] = var

        f_ph = ttk.Frame(form); f_ph.pack(fill="x", pady=4)
        ttk.Label(f_ph, text="رقم الجوال", width=18, anchor="e").pack(side="right")
        var_ph = tk.StringVar()
        ttk.Entry(f_ph, textvariable=var_ph, justify="right").pack(side="right", fill="x", expand=True)
        fields["phone"] = var_ph

        f = ttk.Frame(form); f.pack(fill="x", pady=4)
        ttk.Label(f, text="الدور *", width=18, anchor="e").pack(side="right")
        
        # جلب المسميات العربية من القاموس
        role_labels = [r['label'] for r in ROLES.values()]
        # قاموس عكسي للتحويل من المسمى العربي إلى المفتاح البرمجي
        label_to_key = {r['label']: k for k, r in ROLES.items()}
        
        role_label_var = tk.StringVar(value=ROLES['teacher']['label'])
        combo = ttk.Combobox(f, textvariable=role_label_var,
                     values=role_labels,
                     state="readonly", justify="right")
        combo.pack(side="right", fill="x", expand=True)

        status_lbl = ttk.Label(win, text=""); status_lbl.pack()

        def save():
            un = fields["username"].get().strip()
            fn = fields["full_name"].get().strip()
            ph = fields["phone"].get().strip()
            pw = fields["password"].get()
            cp = fields["confirm"].get()
            
            # تحويل المسمى العربي المختار إلى المفتاح البرمجي (مثلاً 'معلم' -> 'teacher')
            role_key = label_to_key.get(role_label_var.get(), "teacher")
            
            if not un or not pw:
                status_lbl.config(text="⚠️ اسم المستخدم وكلمة المرور مطلوبان",
                                   foreground="orange"); return
            if pw != cp:
                status_lbl.config(text="❌ كلمتا المرور غير متطابقتين",
                                   foreground="red"); return
            if len(pw) < 6:
                status_lbl.config(text="⚠️ كلمة المرور يجب أن تكون 6 أحرف على الأقل",
                                   foreground="orange"); return
            ok, msg = create_user(un, pw, role_key, fn, ph)
            if ok:
                status_lbl.config(text="✅ "+msg, foreground="green")
                self.users_frame.after(100, self._users_load)
                win.after(1200, win.destroy)
            else:
                status_lbl.config(text="❌ "+msg, foreground="red")

        ttk.Button(win, text="إنشاء المستخدم", command=save).pack(pady=10)

    def _user_edit_dialog(self):
        sel = self.tree_users.selection()
        if not sel: messagebox.showwarning("تنبيه","حدد مستخدماً للتعديل"); return
        
        vals = self.tree_users.item(sel[0])["values"]
        user_id = vals[0]
        
        # جلب البيانات الكاملة
        from database import get_all_users, update_user
        user_data = next((u for u in get_all_users() if str(u["id"]) == str(user_id)), None)
        if not user_data:
            messagebox.showerror("خطأ", "تعذر العثور على بيانات المستخدم."); return
        username = user_data["username"]

        win = tk.Toplevel(self.root)
        win.title(f"تعديل المستخدم: {username}")
        win.geometry("400x320")
        win.transient(self.root); win.grab_set()

        ttk.Label(win, text=f"تعديل بيانات: {username}",
                  font=("Tahoma",12,"bold")).pack(pady=(14,8))
        form = ttk.Frame(win, padding=16); form.pack(fill="both")

        fields = {}
        for lbl, key, val in [
            ("الاسم الكامل","full_name", user_data.get("full_name","")),
            ("رقم الجوال","phone", user_data.get("phone","")),
        ]:
            f = ttk.Frame(form); f.pack(fill="x", pady=4)
            ttk.Label(f, text=lbl, width=18, anchor="e").pack(side="right")
            var = tk.StringVar(value=val)
            e = ttk.Entry(f, textvariable=var, justify="right")
            e.pack(side="right", fill="x", expand=True)
            fields[key] = var

        f = ttk.Frame(form); f.pack(fill="x", pady=4)
        ttk.Label(f, text="الدور *", width=18, anchor="e").pack(side="right")
        
        role_labels = [r['label'] for r in ROLES.values()]
        label_to_key = {r['label']: k for k, r in ROLES.items()}
        
        current_role_label = ROLES.get(user_data["role"], {}).get("label", user_data["role"])
        role_label_var = tk.StringVar(value=current_role_label)
        combo = ttk.Combobox(f, textvariable=role_label_var,
                     values=role_labels,
                     state="readonly", justify="right")
        combo.pack(side="right", fill="x", expand=True)

        status_lbl = ttk.Label(win, text=""); status_lbl.pack()

        def save():
            fn = fields["full_name"].get().strip()
            ph = fields["phone"].get().strip()
            role_key = label_to_key.get(role_label_var.get(), "teacher")
            
            ok, msg = update_user(username, role_key, fn, ph)
            if ok:
                status_lbl.config(text="✅ "+msg, foreground="green")
                self.users_frame.after(100, self._users_load)
                win.after(1000, win.destroy)
            else:
                status_lbl.config(text="❌ "+msg, foreground="red")

        ttk.Button(win, text="حفظ التعديلات", command=save).pack(pady=10)

    def _user_change_pw(self):
        sel = self.tree_users.selection()
        if not sel: messagebox.showwarning("تنبيه","حدد مستخدماً"); return
        username = self.tree_users.item(sel[0])["values"][1]
        new_pw = simpledialog.askstring("كلمة المرور الجديدة",
                                         f"أدخل كلمة مرور جديدة للمستخدم: {username}",
                                         show="●", parent=self.root)
        if not new_pw: return
        if len(new_pw) < 6:
            messagebox.showwarning("تنبيه","كلمة المرور يجب أن تكون 6 أحرف على الأقل"); return
        try:
            update_user_password(username, new_pw)
            messagebox.showinfo("تم","تم تغيير كلمة المرور بنجاح")
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل تغيير كلمة المرور:\n{e}")

    def _user_toggle(self):
        sel = self.tree_users.selection()
        if not sel: messagebox.showwarning("تنبيه","حدد مستخدماً"); return
        vals    = self.tree_users.item(sel[0])["values"]
        user_id = vals[0]
        is_active = "✅" in str(vals[4])
        if vals[1] == "admin":
            messagebox.showwarning("تنبيه","لا يمكن تعطيل حساب المدير الرئيسي"); return
        toggle_user_active(user_id, 0 if is_active else 1)
        self.users_frame.after(100, self._users_load)

    def _user_delete(self):
        from database import authenticate
        from constants import CURRENT_USER
        from tkinter import simpledialog
        sel = self.tree_users.selection()
        if not sel: messagebox.showwarning("تنبيه","حدد مستخدماً"); return
        vals    = self.tree_users.item(sel[0])["values"]
        user_id, username = vals[0], vals[1]
        if username == "admin":
            messagebox.showwarning("تنبيه","لا يمكن حذف حساب المدير الرئيسي"); return
        if not messagebox.askyesno("تأكيد",f"حذف المستخدم '{username}'؟"): return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        delete_user(user_id); self._users_load()

    def _user_generate_teachers(self):
        """توليد حسابات للمعلمين الذين ليس لديهم حسابات (بدون إرسال)."""
        if not messagebox.askyesno("تأكيد",
                "سيتم توليد حسابات بكلمة مرور عشوائية للمعلمين الذين ليس لديهم حسابات.\n"
                "لن يتم الإرسال — استخدم زر 'إرسال بيانات الدخول' بعد ذلك.\nهل تريد المتابعة؟"):
            return
        from database import load_teachers, create_user, save_user_allowed_tabs, get_all_users
        import random

        teachers_data = load_teachers().get("teachers", [])
        if not teachers_data:
            messagebox.showwarning("تنبيه", "لا يوجد معلمين. تأكد من استيراد ملف المعلمين أولاً.")
            return

        existing_users = {u["username"] for u in get_all_users()}
        success_count = 0
        skip_count = 0

        self.root.config(cursor="wait")
        try:
            for t in teachers_data:
                name    = t.get("اسم المعلم", "").strip()
                phone   = t.get("رقم الجوال", "").strip()
                civ_id  = t.get("رقم الهوية", "").strip()
                username = civ_id if civ_id else phone
                if not username:
                    skip_count += 1; continue
                if username in existing_users:
                    skip_count += 1; continue
                password = str(random.randint(100000, 999999))
                ok, _ = create_user(username, password, "teacher", name)
                if ok:
                    save_user_allowed_tabs(username, [
                        "لوحة المراقبة", "تحليل النتائج", "تحويل طالب",
                        "نماذج المعلم", "خطابات الاستفسار", "التعاميم والنشرات"])
                    success_count += 1
            self._users_load()
            messagebox.showinfo("اكتمل",
                f"✅ تم إنشاء {success_count} حساب جديد.\n"
                f"⏭️ تم تخطي {skip_count} (موجود مسبقاً أو بياناته ناقصة).\n\n"
                "استخدم زر 'إرسال بيانات الدخول' لإرسال بيانات الدخول عبر الواتساب.")
        finally:
            self.root.config(cursor="")

    def _user_send_teacher_creds(self):
        """إعادة توليد كلمة مرور وإرسال بيانات الدخول للمعلمين عبر الواتساب."""
        if not messagebox.askyesno("تأكيد",
                "سيتم إعادة توليد كلمة مرور جديدة لكل معلم وإرسالها له عبر الواتساب.\n"
                "هل أنت متأكد؟"):
            return
        from database import load_teachers, get_all_users, update_user_password
        from config_manager import load_config
        from whatsapp_service import send_whatsapp_message
        import random

        teachers_data = load_teachers().get("teachers", [])
        if not teachers_data:
            messagebox.showwarning("تنبيه", "لا يوجد معلمين في الملف."); return

        cfg = load_config()
        public_url = cfg.get("cloud_url_internal", "") or cfg.get("cloud_url", "")
        if not public_url:
            messagebox.showwarning("تنبيه",
                "لم يتم العثور على الرابط العام للبرنامج. تأكد من عمل السيرفر أو من شاشة الربط السحابي."); return

        existing_users = {u["username"]: u for u in get_all_users()}
        sent_count = 0
        skip_count = 0

        self.root.config(cursor="wait")
        try:
            for t in teachers_data:
                name    = t.get("اسم المعلم", "").strip()
                phone   = t.get("رقم الجوال", "").strip()
                civ_id  = t.get("رقم الهوية", "").strip()
                username = civ_id if civ_id else phone
                if not username or username not in existing_users:
                    skip_count += 1; continue
                if not phone:
                    skip_count += 1; continue
                password = str(random.randint(100000, 999999))
                update_user_password(username, password)
                msg = (f"مرحباً أستاذ {name}\n\n"
                       f"بيانات دخولك للنظام:\n\n"
                       f"الرابط: {public_url}/web/login\n"
                       f"اسم المستخدم: {username}\n"
                       f"كلمة المرور: {password}\n\n"
                       f"مع تحيات إدارة المدرسة")
                send_whatsapp_message(phone, msg)
                sent_count += 1
            messagebox.showinfo("اكتمل",
                f"✅ تم الإرسال لـ {sent_count} معلم.\n"
                f"⏭️ تم تخطي {skip_count} (لا حساب أو لا رقم جوال).")
        finally:
            self.root.config(cursor="")

    def _user_send_individual_creds(self):
        """إرسال بيانات الدخول للمستخدم المحدد حالياً."""
        sel = self.tree_users.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "يرجى تحديد مستخدم من القائمة أولاً."); return
        
        vals = self.tree_users.item(sel[0])["values"]
        user_id = vals[0]
        
        # جلب بيانات المستخدم كاملة للحصول على رقم الجوال
        from database import get_all_users, update_user_password
        user_data = next((u for u in get_all_users() if str(u["id"]) == str(user_id)), None)
        
        if not user_data:
            messagebox.showerror("خطأ", "تعذر العثور على بيانات المستخدم."); return
        
        username = user_data["username"]
        name = user_data.get("full_name") or username
            
        phone = user_data.get("phone", "").strip()
        if not phone:
            # إذا لم يوجد رقم جوال، نطلبه من المستخدم
            from tkinter import simpledialog
            phone = simpledialog.askstring("رقم الجوال", f"لم يتم العثور على رقم جوال لـ {name}.\nأدخل رقم الجوال (مثال: 9665...):", parent=self.root)
            if not phone: return
            # حفظ الرقم للمستقبل
            from database import save_user_phone
            save_user_phone(username, phone)

        if not messagebox.askyesno("تأكيد", f"سيتم إنشاء كلمة مرور جديدة وإرسالها إلى {name} عبر الواتساب.\nهل تريد المتابعة؟"):
            return

        import random
        from config_manager import load_config
        from whatsapp_service import send_whatsapp_message
        
        cfg = load_config()
        public_url = cfg.get("cloud_url_internal", "") or cfg.get("cloud_url", "")
        if not public_url:
            messagebox.showwarning("تنبيه", "لم يتم العثور على الرابط العام للبرنامج."); return

        password = str(random.randint(100000, 999999))
        try:
            update_user_password(username, password)
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل تغيير كلمة المرور:\n{e}"); return

        msg = (f"مرحباً أستاذ {name}\n\n"
               f"بيانات دخولك للنظام:\n\n"
               f"الرابط: {public_url}/web/login\n"
               f"اسم المستخدم: {username}\n"
               f"كلمة المرور: {password}\n\n"
               f"مع تحيات إدارة المدرسة")
        
        self.root.config(cursor="wait")
        try:
            ok = send_whatsapp_message(phone, msg)
            if ok:
                messagebox.showinfo("تم", f"تم إرسال بيانات الدخول إلى {name} بنجاح.")
            else:
                messagebox.showerror("خطأ", "فشل إرسال الرسالة عبر الواتساب. تأكد من اتصال الهاتف.")
        finally:
            self.root.config(cursor="")

    # ══════════════════════════════════════════════════════════
    # تبويب النسخ الاحتياطية
    # ══════════════════════════════════════════════════════════
