# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
from constants import now_riyadh_date, CURRENT_USER
from database import EXCUSE_REASONS, delete_excuse, insert_excuse, query_excuses

class ExcusesTabMixin:
    """Mixin: ExcusesTabMixin"""
    def _build_excuses_tab(self):
        frame = self.excuses_frame

        ctrl = ttk.Frame(frame); ctrl.pack(fill="x", pady=(8,4), padx=5)
        ttk.Label(ctrl, text="التاريخ:").pack(side="right", padx=(0,5))
        self.exc_date_var = tk.StringVar(value=now_riyadh_date())
        ttk.Entry(ctrl, textvariable=self.exc_date_var, width=12).pack(side="right", padx=5)
        ttk.Button(ctrl, text="🔍 عرض", command=self._exc_load).pack(side="right", padx=5)
        ttk.Button(ctrl, text="➕ إضافة عذر", command=self._exc_add_dialog).pack(side="right", padx=5)
        ttk.Button(ctrl, text="🗑️ حذف", command=self._exc_delete).pack(side="left", padx=5)

        # شرح
        ttk.Label(frame,
            text="ملاحظة: الطلاب الذين لديهم عذر مقبول سيظهر غيابهم بلون مختلف في التقارير.",
            foreground="#5A6A7E", font=("Tahoma",9)).pack(anchor="e", padx=5)

        # ─── إطار الجدول (منفصل حتى لا يتعارض fill مع قسم البوت) ─
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True, padx=5, pady=(2, 2))

        cols = ("id","date","student_name","student_id","class_name","reason","source","approved_by")
        self.tree_excuses = ttk.Treeview(tree_frame, columns=cols, show="headings", height=10)
        for col, hdr, w in zip(cols,
            ["ID","التاريخ","اسم الطالب","رقم الطالب","الفصل","سبب العذر","المصدر","الموافق"],
            [40,90,220,110,160,160,80,120]):
            self.tree_excuses.heading(col, text=hdr)
            self.tree_excuses.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_excuses.yview)
        self.tree_excuses.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree_excuses.pack(side="left", fill="both", expand=True)

        self.tree_excuses.tag_configure("wa_excuse", background="#E8F5E9", foreground="#2E7D32")
        self.tree_excuses.tag_configure("admin_excuse", background="#E3F2FD", foreground="#1565C0")
        frame.after(100, self._exc_load)

        # ─── قسم بوت الواتساب ────────────────────────────────
        self._build_whatsapp_bot_section(frame)

    def _exc_load(self):
        date_f = self.exc_date_var.get().strip() if hasattr(self,"exc_date_var") else now_riyadh_date()
        rows   = query_excuses(date_filter=date_f or None)
        if not hasattr(self,"tree_excuses"): return
        for i in self.tree_excuses.get_children(): self.tree_excuses.delete(i)
        for r in rows:
            tag = "wa_excuse" if r.get("source")=="whatsapp" else "admin_excuse"
            self.tree_excuses.insert("", "end", tags=(tag,),
                values=(r["id"], r["date"], r["student_name"], r["student_id"],
                        r["class_name"], r["reason"],
                        "واتساب" if r.get("source")=="whatsapp" else "إداري",
                        r.get("approved_by","")))

    def _exc_add_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("إضافة عذر غياب")
        win.geometry("500x420")
        win.transient(self.root); win.grab_set()

        ttk.Label(win, text="إضافة عذر لطالب", font=("Tahoma",13,"bold")).pack(pady=(16,8))
        form = ttk.Frame(win, padding=20); form.pack(fill="both", expand=True)

        def row(lbl, widget_fn):
            f = ttk.Frame(form); f.pack(fill="x", pady=5)
            ttk.Label(f, text=lbl, width=14, anchor="e").pack(side="right")
            w = widget_fn(f); w.pack(side="right", fill="x", expand=True, padx=(0,6))
            return w

        date_var = tk.StringVar(value=self.exc_date_var.get())
        row("التاريخ:", lambda p: ttk.Entry(p, textvariable=date_var))

        cls_var = tk.StringVar()
        cls_combo = row("الفصل:", lambda p: ttk.Combobox(
            p, textvariable=cls_var,
            values=[c["name"] for c in self.store["list"]],
            state="readonly"))

        stu_var = tk.StringVar()
        stu_combo = row("الطالب:", lambda p: ttk.Combobox(
            p, textvariable=stu_var, state="readonly"))

        def on_cls(*_):
            cls = next((c for c in self.store["list"] if c["name"]==cls_var.get()), None)
            if cls:
                stu_combo["values"] = [f'{s["name"]} ({s["id"]})' for s in cls["students"]]
        cls_combo.bind("<<ComboboxSelected>>", on_cls)

        reason_var = tk.StringVar(value=EXCUSE_REASONS[0])
        row("سبب العذر:", lambda p: ttk.Combobox(
            p, textvariable=reason_var, values=EXCUSE_REASONS, state="readonly"))

        approved_var = tk.StringVar(value=CURRENT_USER.get("name","المدير"))
        row("الموافق:", lambda p: ttk.Entry(p, textvariable=approved_var))

        status_lbl = ttk.Label(win, text=""); status_lbl.pack()

        def save():
            cls_obj = next((c for c in self.store["list"] if c["name"]==cls_var.get()), None)
            if not cls_obj: messagebox.showwarning("تنبيه","اختر فصلاً",parent=win); return
            stu_txt = stu_var.get()
            if not stu_txt: messagebox.showwarning("تنبيه","اختر طالباً",parent=win); return
            sid   = stu_txt.split("(")[-1].rstrip(")")
            sname = stu_txt.split("(")[0].strip()
            insert_excuse(date_var.get(), sid, sname,
                          cls_obj["id"], cls_obj["name"],
                          reason_var.get(), "admin", approved_var.get())
            status_lbl.config(text="✅ تم حفظ العذر", foreground="green")
            self._exc_load()

        ttk.Button(win, text="💾 حفظ العذر", command=save).pack(pady=10)

    def _exc_delete(self):
        from database import authenticate
        from constants import CURRENT_USER
        from tkinter import simpledialog
        sel = self.tree_excuses.selection()
        if not sel: messagebox.showwarning("تنبيه","حدد سجلاً"); return
        rid = self.tree_excuses.item(sel[0])["values"][0]
        if not messagebox.askyesno("تأكيد","حذف هذا العذر؟"): return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        delete_excuse(rid); self._exc_load()

    # ══════════════════════════════════════════════════════════
    # تبويب المستخدمين (للمدير فقط)
    # ══════════════════════════════════════════════════════════
