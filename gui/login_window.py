# -*- coding: utf-8 -*-
"""
gui/login_window.py — نافذة تسجيل الدخول
"""
import tkinter as tk
from tkinter import ttk, messagebox
import os, json, base64
from constants import APP_VERSION, CURRENT_USER, ROLES, DATA_DIR
from database import authenticate, get_user_allowed_tabs, refresh_cloud_client, force_sync_cloud_data
from config_manager import load_config, save_config

# ملف حفظ بيانات الدخول
_SAVED_LOGIN = os.path.join(DATA_DIR, "saved_login.json")


def _save_credentials(username: str, password: str):
    """يحفظ بيانات الدخول مشفّرة بـ base64."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        data = {
            "u": base64.b64encode(username.encode("utf-8")).decode(),
            "p": base64.b64encode(password.encode("utf-8")).decode(),
        }
        with open(_SAVED_LOGIN, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def _load_credentials():
    """يُرجع (username, password) أو ('', '') إن لم تكن محفوظة."""
    try:
        if not os.path.exists(_SAVED_LOGIN):
            return "", ""
        with open(_SAVED_LOGIN, "r", encoding="utf-8") as f:
            data = json.load(f)
        u = base64.b64decode(data["u"].encode()).decode("utf-8")
        p = base64.b64decode(data["p"].encode()).decode("utf-8")
        return u, p
    except Exception:
        return "", ""


def _clear_credentials():
    """يحذف بيانات الدخول المحفوظة."""
    try:
        if os.path.exists(_SAVED_LOGIN):
            os.remove(_SAVED_LOGIN)
    except Exception:
        pass


class LoginWindow:
    """نافذة تسجيل الدخول — تظهر عند بدء البرنامج."""

    def __init__(self, root, on_success):
        self.root       = root
        self.on_success = on_success
        self.attempts   = 0
        self._build()

    def _build(self):
        self.root.title("تسجيل الدخول — DarbStu")

        WIN_W, WIN_H = 420, 520
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.resizable(False, False)
        try:
            self.root.set_theme("arc")
        except Exception:
            pass

        # ─── توسيط النافذة على الشاشة ─────────────────────────
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - WIN_W) // 2
        y  = (sh - WIN_H) // 2
        self.root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")

        # ─── رأس النافذة ───────────────────────────────────────
        header = tk.Frame(self.root, bg="#1565C0", height=110)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="DarbStu", bg="#1565C0", fg="white",
                 font=("Tahoma", 26, "bold")).pack(pady=(22, 0))
        tk.Label(header, text="نظام إدارة الغياب والتأخر", bg="#1565C0",
                 fg="#BBDEFB", font=("Tahoma", 11)).pack()

        # ─── نموذج الدخول ──────────────────────────────────────
        body = tk.Frame(self.root, bg="#F5F7FA", padx=40, pady=28)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="اسم المستخدم", bg="#F5F7FA",
                 font=("Tahoma", 11, "bold"), anchor="e").pack(fill="x")
        self.username_var = tk.StringVar()
        username_entry = ttk.Entry(body, textvariable=self.username_var,
                                   font=("Tahoma", 13), justify="right")
        username_entry.pack(fill="x", pady=(4, 14))

        tk.Label(body, text="كلمة المرور", bg="#F5F7FA",
                 font=("Tahoma", 11, "bold"), anchor="e").pack(fill="x")
        self.password_var = tk.StringVar()
        self.pw_entry = ttk.Entry(body, textvariable=self.password_var,
                                   font=("Tahoma", 13), show="●", justify="right")
        self.pw_entry.pack(fill="x", pady=(4, 6))

        # ─── خيارات (إظهار كلمة المرور + تذكّر) ───────────────
        opts_row = tk.Frame(body, bg="#F5F7FA")
        opts_row.pack(fill="x", pady=(4, 0))

        self.show_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts_row, text="إظهار كلمة المرور",
                        variable=self.show_pw,
                        command=self._toggle_pw).pack(side="right")

        self.remember_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts_row, text="تذكّر معلومات الدخول",
                        variable=self.remember_var).pack(side="left")

        # ─── رسالة الخطأ ───────────────────────────────────────
        self.error_lbl = tk.Label(body, text="", bg="#F5F7FA",
                                   fg="#C62828", font=("Tahoma", 10))
        self.error_lbl.pack(pady=(10, 0))

        # ─── زر الدخول ─────────────────────────────────────────
        tk.Button(
            body, text="تسجيل الدخول", bg="#1565C0", fg="white",
            font=("Tahoma", 13, "bold"), relief="flat",
            cursor="hand2", pady=10,
            command=self._do_login
        ).pack(fill="x", pady=(14, 0))

        # ─── رابط إعدادات السحاب ─────────────────────────────
        cloud_lbl = tk.Label(
            body, text="🌐 إعدادات المزامنة السحابية",
            bg="#F5F7FA", fg="#1565C0", font=("Tahoma", 10, "underline"),
            cursor="hand2")
        cloud_lbl.pack(pady=(16, 0))
        cloud_lbl.bind("<Button-1>", lambda e: self._open_cloud_settings())

        # ─── رابط حذف البيانات المحفوظة ────────────────────────
        saved_u, _ = _load_credentials()
        if saved_u:
            self._clear_lbl = tk.Label(
                body, text="🗑 حذف معلومات الدخول المحفوظة",
                bg="#F5F7FA", fg="#888", font=("Tahoma", 9),
                cursor="hand2")
            self._clear_lbl.pack(pady=(10, 0))
            self._clear_lbl.bind("<Button-1>", self._clear_saved)

        # ─── تعبئة البيانات المحفوظة تلقائياً ──────────────────
        saved_u, saved_p = _load_credentials()
        if saved_u:
            self.username_var.set(saved_u)
            self.password_var.set(saved_p)
            self.remember_var.set(True)
            self.pw_entry.focus()
        else:
            username_entry.focus()

        # ─── ربط Enter ─────────────────────────────────────────
        self.root.bind("<Return>", lambda e: self._do_login())

    def _toggle_pw(self):
        self.pw_entry.config(show="" if self.show_pw.get() else "●")

    def _clear_saved(self, _event=None):
        _clear_credentials()
        self.username_var.set("")
        self.password_var.set("")
        self.remember_var.set(False)
        try:
            self._clear_lbl.destroy()
        except Exception:
            pass
        self.error_lbl.config(text="✅ تم حذف معلومات الدخول المحفوظة",
                              fg="#2E7D32")

    def _do_login(self):
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()

        if not username or not password:
            self.error_lbl.config(
                text="⚠️ الرجاء إدخال اسم المستخدم وكلمة المرور",
                fg="#C62828")
            return

        user = authenticate(username, password)

        if user:
            # حفظ أو حذف بيانات الدخول حسب خيار المستخدم
            if self.remember_var.get():
                _save_credentials(username, password)
            else:
                _clear_credentials()

            # تحديث المستخدم الحالي
            CURRENT_USER["username"] = user["username"]
            CURRENT_USER["role"]     = user["role"]
            CURRENT_USER["label"]    = ROLES.get(user["role"], {}).get("label", user["role"])
            CURRENT_USER["name"]     = user.get("full_name", user["username"])
            
            # مزامنة البيانات تلقائياً عند الدخول في وضع السحاب
            from config_manager import load_config
            if load_config().get("cloud_mode"):
                import threading
                threading.Thread(target=force_sync_cloud_data, daemon=True).start()

            # تحذير التثبيتات القديمة التي ما زالت على كلمة المرور الافتراضية
            if user.get("default_password"):
                messagebox.showwarning(
                    "⚠️ كلمة مرور غير آمنة",
                    "ما زلت تستخدم كلمة المرور الافتراضية (admin123).\n\n"
                    "هذه الكلمة معروفة للجميع، وبيانات طلاب مدرستك مكشوفة\n"
                    "لأي شخص على الشبكة أو عبر الرابط الخارجي.\n\n"
                    "غيّرها الآن من تبويب «إدارة المستخدمين».",
                    parent=self.root)

            self.root.unbind("<Return>")
            self.on_success()

        else:
            self.attempts += 1
            if self.attempts >= 5:
                self.error_lbl.config(
                    text="⛔ تم إيقاف الحساب مؤقتاً — أعد تشغيل البرنامج",
                    fg="#C62828")
                self.pw_entry.config(state="disabled")
            else:
                remaining = 5 - self.attempts
                self.error_lbl.config(
                    text=f"❌ اسم المستخدم أو كلمة المرور غير صحيحة ({remaining} محاولات متبقية)",
                    fg="#C62828")
            self.password_var.set("")
            self.pw_entry.focus()

    def _open_cloud_settings(self):
        """تفتح نافذة لإدخال إعدادات السيرفر السحابي."""
        dialog = tk.Toplevel(self.root)
        dialog.title("إعدادات المزامنة السحابية")
        dialog.geometry("400x320")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        cfg = load_config()

        container = tk.Frame(dialog, padx=20, pady=20)
        container.pack(fill="both", expand=True)

        tk.Label(container, text="الربط بسيرفر المدرسة", font=("Tahoma", 12, "bold")).pack(pady=(0, 10))

        mode_var = tk.BooleanVar(value=cfg.get("cloud_mode", False))
        tk.Checkbutton(container, text="تفعيل الوضع السحابي (جهاز عميل)", variable=mode_var, font=("Tahoma", 10)).pack(fill="x", pady=5)

        tk.Label(container, text="رابط السيرفر (URL):", font=("Tahoma", 9)).pack(fill="x")
        url_var = tk.StringVar(value=cfg.get("cloud_url", ""))
        tk.Entry(container, textvariable=url_var, font=("Tahoma", 10), justify="left").pack(fill="x", pady=(2, 10))

        tk.Label(container, text="رمز الأمان (Access Token):", font=("Tahoma", 9)).pack(fill="x")
        token_var = tk.StringVar(value=cfg.get("cloud_token", ""))
        tk.Entry(container, textvariable=token_var, font=("Tahoma", 10), show="*", justify="left").pack(fill="x", pady=(2, 15))

        def save():
            cfg["cloud_mode"] = mode_var.get()
            cfg["cloud_url"] = url_var.get().strip()
            cfg["cloud_token"] = token_var.get().strip()
            save_config(cfg)
            refresh_cloud_client()
            
            if cfg["cloud_mode"]:
                import threading
                threading.Thread(target=force_sync_cloud_data, daemon=True).start()
                messagebox.showinfo("تم الحفظ", "تم تحديث الإعدادات. جاري جلب البيانات من السيرفر في الخلفية...")
            else:
                messagebox.showinfo("تم الحفظ", "تم تحديث إعدادات المزامنة.")
            dialog.destroy()

        tk.Button(container, text="حفظ الإعدادات", bg="#2E7D32", fg="white", font=("Tahoma", 10, "bold"), command=save).pack(fill="x")
