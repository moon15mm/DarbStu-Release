# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
from constants import now_riyadh_date
from database import delete_tardiness, insert_tardiness, load_teachers, query_tardiness, compute_tardiness_metrics

class TardinessTabMixin:
    """Mixin: TardinessTabMixin"""
    def _build_tardiness_tab(self):
        frame = self.tardiness_frame

        # شريط التحكم
        ctrl = ttk.Frame(frame); ctrl.pack(fill="x", pady=(8,4), padx=5)
        ttk.Label(ctrl, text="التاريخ:").pack(side="right", padx=(0,5))
        self.tard_date_var = tk.StringVar(value=now_riyadh_date())
        ttk.Entry(ctrl, textvariable=self.tard_date_var, width=12).pack(side="right", padx=5)
        ttk.Label(ctrl, text="الفصل:").pack(side="right", padx=(10,5))
        self.tard_class_var = tk.StringVar()
        class_ids = ["(الكل)"] + [c["id"] for c in self.store["list"]]
        ttk.Combobox(ctrl, textvariable=self.tard_class_var,
                     values=class_ids, width=12, state="readonly").pack(side="right", padx=5)
        ttk.Button(ctrl, text="🔍 عرض", command=self._tard_load).pack(side="right", padx=5)
        ttk.Button(ctrl, text="➕ إضافة تأخر", command=self._tard_add_dialog).pack(side="right", padx=5)
        ttk.Button(ctrl, text="🗑️ حذف المحدد", command=self._tard_delete).pack(side="left", padx=5)

        # إحصائيات سريعة
        stats_row = ttk.Frame(frame); stats_row.pack(fill="x", padx=5, pady=4)
        self.tard_stat_lbl = ttk.Label(stats_row, text="", foreground="#1565C0",
                                        font=("Tahoma",10,"bold"))
        self.tard_stat_lbl.pack(side="right")

        # الجدول
        cols = ("id","date","class_name","student_name","student_id",
                "teacher_name","period","minutes_late")
        self.tree_tard = ttk.Treeview(frame, columns=cols, show="headings", height=14)
        for col, hdr, w in zip(cols,
            ["ID","التاريخ","الفصل","اسم الطالب","رقم الطالب","المعلم","الحصة","دقائق التأخر"],
            [40,90,160,220,110,140,60,100]):
            self.tree_tard.heading(col, text=hdr)
            self.tree_tard.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree_tard.yview)
        self.tree_tard.configure(yscrollcommand=sb.set)
        self.tree_tard.pack(side="left", fill="both", expand=True, padx=(5,0))
        sb.pack(side="right", fill="y", padx=(0,5))

        # ألوان التأخر
        self.tree_tard.tag_configure("late_heavy", background="#FFEBEE", foreground="#C62828")
        self.tree_tard.tag_configure("late_mild",  background="#FFF8E1", foreground="#E65100")
        self._tard_load()

    def _tard_load(self):
        date_f  = self.tard_date_var.get().strip() if hasattr(self,"tard_date_var") else now_riyadh_date()
        cls_id  = self.tard_class_var.get() if hasattr(self,"tard_class_var") else None
        if cls_id == "(الكل)": cls_id = None
        rows = query_tardiness(date_filter=date_f or None, class_id=cls_id)
        if not hasattr(self,"tree_tard"): return
        for i in self.tree_tard.get_children(): self.tree_tard.delete(i)
        total_min = 0
        for r in rows:
            mins = r.get("minutes_late", 0)
            total_min += mins
            tag = "late_heavy" if mins >= 15 else "late_mild" if mins >= 5 else ""
            self.tree_tard.insert("", "end", tags=(tag,),
                values=(r["id"], r["date"], r["class_name"], r["student_name"],
                        r["student_id"], r.get("teacher_name",""), r.get("period",""),
                        f"{mins} دقيقة"))
        if hasattr(self,"tard_stat_lbl"):
            self.tard_stat_lbl.config(
                text=f"الإجمالي: {len(rows)} طالب متأخر | متوسط التأخر: {total_min//max(len(rows),1)} دقيقة")

    def _tard_add_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("إضافة تأخر")
        win.geometry("460x420")
        win.transient(self.root); win.grab_set()

        ttk.Label(win, text="إضافة سجل تأخر", font=("Tahoma",13,"bold")).pack(pady=(16,8))

        form = ttk.Frame(win, padding=20); form.pack(fill="both", expand=True)

        def row(lbl, widget_fn):
            f = ttk.Frame(form); f.pack(fill="x", pady=4)
            ttk.Label(f, text=lbl, width=14, anchor="e").pack(side="right")
            w = widget_fn(f); w.pack(side="right", fill="x", expand=True, padx=(0,6))
            return w

        date_var = tk.StringVar(value=self.tard_date_var.get())
        row("التاريخ:", lambda p: ttk.Entry(p, textvariable=date_var))

        cls_var = tk.StringVar()
        cls_combo = row("الفصل:", lambda p: ttk.Combobox(
            p, textvariable=cls_var,
            values=[c["name"] for c in self.store["list"]],
            state="readonly"))

        stu_var = tk.StringVar()
        stu_combo = row("الطالب:", lambda p: ttk.Combobox(
            p, textvariable=stu_var, state="readonly"))

        def on_cls_change(*_):
            cls = next((c for c in self.store["list"] if c["name"]==cls_var.get()), None)
            if cls:
                stu_combo["values"] = [f'{s["name"]} ({s["id"]})' for s in cls["students"]]
        cls_combo.bind("<<ComboboxSelected>>", on_cls_change)

        tch_var = tk.StringVar()
        teachers = load_teachers()
        tch_names = [t.get("اسم المعلم", "") for t in teachers.get("teachers",[])]
        row("المعلم:", lambda p: ttk.Combobox(p, textvariable=tch_var,
                                               values=tch_names, state="readonly"))

        period_var = tk.StringVar(value="1")
        row("الحصة:", lambda p: ttk.Combobox(p, textvariable=period_var,
                                              values=[str(i) for i in range(1,8)],
                                              state="readonly", width=6))

        mins_var = tk.StringVar(value="10")
        mins_entry = row("دقائق التأخر:", lambda p: ttk.Entry(p, textvariable=mins_var, width=8))

        status_lbl = ttk.Label(win, text="", foreground="green")
        status_lbl.pack()

        def save():
            cls_obj = next((c for c in self.store["list"] if c["name"]==cls_var.get()), None)
            if not cls_obj: messagebox.showwarning("تنبيه","اختر فصلاً",parent=win); return
            stu_txt = stu_var.get()
            if not stu_txt: messagebox.showwarning("تنبيه","اختر طالباً",parent=win); return
            sid   = stu_txt.split("(")[-1].rstrip(")")
            sname = stu_txt.split("(")[0].strip()
            try: mins = int(mins_var.get())
            except ValueError: mins = 0
            ok = insert_tardiness(
                date_var.get(), cls_obj["id"], cls_obj["name"],
                sid, sname, tch_var.get(),
                int(period_var.get() or 1), mins)
            if ok:
                status_lbl.config(text="✅ تم التسجيل")
                self._tard_load()
            else:
                status_lbl.config(text="⚠️ السجل موجود مسبقاً", foreground="orange")

        ttk.Button(win, text="💾 حفظ", command=save).pack(pady=10)

    def _tard_delete(self):
        from database import authenticate
        from constants import CURRENT_USER
        from tkinter import simpledialog
        sel = self.tree_tard.selection()
        if not sel: messagebox.showwarning("تنبيه","حدد سجلاً أولاً"); return
        rid = self.tree_tard.item(sel[0])["values"][0]
        if not messagebox.askyesno("تأكيد","هل تريد حذف هذا السجل؟"): return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return

        delete_tardiness(rid)
        self._tard_load()

    # ══════════════════════════════════════════════════════════
    # تبويب الأعذار
    # ══════════════════════════════════════════════════════════
