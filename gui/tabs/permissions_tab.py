# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
from constants import now_riyadh_date, CURRENT_USER
from alerts_service import (PERMISSION_REASONS, PERM_APPROVED, PERM_WAITING,
                             delete_permission, insert_permission,
                             query_permissions, send_permission_request)

class PermissionsTabMixin:
    """Mixin: PermissionsTabMixin"""
    def _build_permissions_tab(self):
        frame = self.permissions_frame

        hdr = tk.Frame(frame, bg="#0277BD", height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🚪 الاستئذان — موافقة ولي الأمر",
                 bg="#0277BD", fg="white",
                 font=("Tahoma",12,"bold")).pack(side="right", padx=14, pady=12)

        ctrl = ttk.Frame(frame); ctrl.pack(fill="x", padx=8, pady=(6,4))
        ttk.Label(ctrl, text="التاريخ:").pack(side="right", padx=(0,4))
        self.perm_date_var = tk.StringVar(value=now_riyadh_date())
        ttk.Entry(ctrl, textvariable=self.perm_date_var, width=12).pack(side="right", padx=4)
        ttk.Button(ctrl, text="🔍 عرض",
                   command=self._perm_load).pack(side="right", padx=4)
        ttk.Button(ctrl, text="➕ طلب استئذان",
                   command=self._perm_add_dialog).pack(side="right", padx=4)
        ttk.Button(ctrl, text="📲 إعادة إرسال",
                   command=self._perm_resend).pack(side="right", padx=4)
        ttk.Button(ctrl, text="🗑️ حذف",
                   command=self._perm_delete).pack(side="left", padx=4)

        # مؤشر الحالة
        ind = ttk.Frame(frame); ind.pack(fill="x", padx=8, pady=2)
        self.perm_wait_lbl = ttk.Label(ind, text="",
                                        foreground="#E65100", font=("Tahoma",9,"bold"))
        self.perm_wait_lbl.pack(side="right")
        self.perm_ok_lbl = ttk.Label(ind, text="",
                                      foreground="#2E7D32", font=("Tahoma",9,"bold"))
        self.perm_ok_lbl.pack(side="right", padx=12)

        cols = ("id","student_name","class_name","parent_phone",
                "reason","status","approved_by")
        self.tree_perm = ttk.Treeview(frame, columns=cols, show="headings", height=14)
        for c,h,w in zip(cols,
            ["ID","اسم الطالب","الفصل","جوال ولي الأمر","السبب","الحالة","الموافق"],
            [35,200,130,120,150,80,120]):
            self.tree_perm.heading(c,text=h)
            self.tree_perm.column(c,width=w,anchor="center")
        self.tree_perm.tag_configure("waiting",  background="#FFF8E1", foreground="#E65100")
        self.tree_perm.tag_configure("approved", background="#E8F5E9", foreground="#2E7D32")
        self.tree_perm.tag_configure("rejected", background="#FFEBEE", foreground="#C62828")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree_perm.yview)
        self.tree_perm.configure(yscrollcommand=sb.set)
        self.tree_perm.pack(side="left", fill="both", expand=True, padx=(8,0))
        sb.pack(side="right", fill="y", padx=(0,8))
        self._perm_load()
        self._perm_schedule_refresh()

    def _perm_schedule_refresh(self):
        """تحديث تلقائي كل 5 دقائق — يعمل فقط إذا كان تبويب الاستئذان نشطاً."""
        if hasattr(self, "_current_tab") and self._current_tab.get() == "الاستئذان":
            self._perm_load()
        self.root.after(300_000, self._perm_schedule_refresh)

    def _perm_load(self):
        if not hasattr(self,"tree_perm"): return
        date_f = self.perm_date_var.get().strip() if hasattr(self,"perm_date_var") else now_riyadh_date()
        rows = query_permissions(date_filter=date_f)
        for i in self.tree_perm.get_children(): self.tree_perm.delete(i)
        waiting = approved = 0
        for r in rows:
            s   = r.get("status", PERM_WAITING)
            tag = {"انتظار":"waiting","موافق":"approved","مرفوض":"rejected"}.get(s,"waiting")
            if s == PERM_WAITING:  waiting  += 1
            if s == PERM_APPROVED: approved += 1
            self.tree_perm.insert("","end", iid=str(r["id"]), tags=(tag,),
                values=(r["id"],r["student_name"],r["class_name"],
                        r.get("parent_phone",""),r.get("reason",""),
                        s, r.get("approved_by","")))
        if hasattr(self,"perm_wait_lbl"):
            self.perm_wait_lbl.config(
                text="⏳ انتظار: {}".format(waiting) if waiting else "")
        if hasattr(self,"perm_ok_lbl"):
            self.perm_ok_lbl.config(
                text="✅ وافق وخرج: {}".format(approved) if approved else "")

    def _perm_add_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("طلب استئذان جديد")
        win.geometry("480x380")
        win.transient(self.root); win.grab_set()

        ttk.Label(win, text="تسجيل طلب استئذان",
                  font=("Tahoma",12,"bold")).pack(pady=(12,4))
        ttk.Label(win, text="سيُرسَل واتساب لولي الأمر طالباً موافقته",
                  foreground="#5A6A7E").pack(pady=(0,8))

        form = ttk.Frame(win, padding=14); form.pack(fill="both")

        def row(lbl, w_fn):
            f = ttk.Frame(form); f.pack(fill="x", pady=4)
            ttk.Label(f, text=lbl, width=14, anchor="e").pack(side="right")
            w = w_fn(f); w.pack(side="right", fill="x", expand=True, padx=(0,6))
            return w

        date_var = tk.StringVar(value=now_riyadh_date())
        row("التاريخ:", lambda p: ttk.Entry(p, textvariable=date_var, width=14))

        cls_var = tk.StringVar()
        cls_cb  = row("الفصل:", lambda p: ttk.Combobox(
            p, textvariable=cls_var,
            values=[c["name"] for c in self.store["list"]], state="readonly"))

        stu_var = tk.StringVar()
        stu_cb  = row("الطالب:", lambda p: ttk.Combobox(p, textvariable=stu_var, state="readonly"))

        phone_var = tk.StringVar()
        row("جوال ولي الأمر:", lambda p: ttk.Entry(p, textvariable=phone_var, width=16, justify="right"))

        def on_cls(*_):
            cls = next((c for c in self.store["list"] if c["name"]==cls_var.get()), None)
            if cls:
                stu_cb["values"] = ["{} ({})".format(s["name"],s["id"])
                                     for s in sorted(cls["students"],key=lambda x:x["name"])]

        def on_stu(*_):
            import re as _re
            m = _re.match(r"^(.+)\(([^)]+)\)$", stu_var.get().strip())
            if not m: return
            sid = m.group(2).strip()
            for cls in self.store["list"]:
                for s in cls["students"]:
                    if s["id"] == sid:
                        phone_var.set(s.get("phone",""))
                        return

        cls_cb.bind("<<ComboboxSelected>>", on_cls)
        stu_cb.bind("<<ComboboxSelected>>", on_stu)

        reason_var = tk.StringVar(value=PERMISSION_REASONS[0])
        row("السبب:", lambda p: ttk.Combobox(p, textvariable=reason_var,
                                               values=PERMISSION_REASONS, state="readonly"))
        approved_var = tk.StringVar(
            value=CURRENT_USER.get("name", CURRENT_USER.get("username","")))
        row("الموافق:", lambda p: ttk.Entry(p, textvariable=approved_var))

        status_lbl = ttk.Label(win, text=""); status_lbl.pack()

        def save():
            import re as _re
            cls_obj = next((c for c in self.store["list"] if c["name"]==cls_var.get()), None)
            if not cls_obj:
                messagebox.showwarning("تنبيه","اختر فصلاً",parent=win); return
            m = _re.match(r"^(.+)\(([^)]+)\)$", stu_var.get().strip())
            if not m:
                messagebox.showwarning("تنبيه","اختر طالباً",parent=win); return
            sname, sid = m.group(1).strip(), m.group(2).strip()
            phone = phone_var.get().strip()

            pid = insert_permission(date_var.get(), sid, sname,
                                    cls_obj["id"], cls_obj["name"],
                                    phone, reason_var.get(), approved_var.get())
            if phone:
                status_lbl.config(text="⏳ جارٍ إرسال واتساب...", foreground="#1565C0")
                win.update_idletasks()
                ok, msg = send_permission_request(pid)
                if ok:
                    status_lbl.config(text="✅ أُرسل — في انتظار رد ولي الأمر",
                                       foreground="green")
                else:
                    status_lbl.config(text="⚠️ لم يُرسَل: {} — الطلب مسجّل".format(msg),
                                       foreground="orange")
            else:
                status_lbl.config(text="⚠️ لا رقم — الطلب مسجّل بدون إرسال",
                                   foreground="orange")
            self._perm_load()
            win.after(1200, win.destroy)

        ttk.Button(win, text="📲 تسجيل وإرسال لولي الأمر",
                   command=save).pack(pady=10)

    def _perm_resend(self):
        sel = self.tree_perm.selection() if hasattr(self,"tree_perm") else []
        if not sel:
            messagebox.showwarning("تنبيه","حدد طلباً أولاً"); return
        pid = int(self.tree_perm.item(sel[0],"values")[0])
        ok, msg = send_permission_request(pid)
        if ok:
            messagebox.showinfo("تم","✅ تم إعادة الإرسال")
        else:
            messagebox.showwarning("فشل","❌ " + msg)

    def _perm_delete(self):
        from database import authenticate
        from constants import CURRENT_USER
        from tkinter import simpledialog
        sel = self.tree_perm.selection() if hasattr(self,"tree_perm") else []
        if not sel:
            messagebox.showwarning("تنبيه","حدد سجلاً"); return
        if not messagebox.askyesno("تأكيد","حذف هذا السجل؟"): return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        delete_permission(int(self.tree_perm.item(sel[0],"values")[0]))
        self._perm_load()


