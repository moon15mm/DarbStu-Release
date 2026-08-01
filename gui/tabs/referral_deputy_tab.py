# -*- coding: utf-8 -*-
"""
gui/tabs/referral_deputy_tab.py — تبويب إدارة التحويلات (للوكيل)
"""
import tkinter as tk
from tkinter import ttk, messagebox
import datetime
from constants import now_riyadh_date, CURRENT_USER
from database import (get_db, get_all_referrals, get_referral_by_id,
                      update_referral_deputy, close_referral,
                      get_counselor_phones)
from whatsapp_service import send_whatsapp_message

_STATUS_LABELS = {
    "pending":        "⏳ بانتظار الوكيل",
    "with_deputy":    "📋 مع الوكيل",
    "with_counselor": "👨‍🏫 مع الموجه",
    "resolved":       "✅ تم الحل",
}
_STATUS_COLORS = {
    "pending":        "#FFF9E6",
    "with_deputy":    "#E3F2FD",
    "with_counselor": "#EDE7F6",
    "resolved":       "#E8F5E9",
}


class DeputyReferralTabMixin:
    """Mixin: تبويب استلام وإدارة التحويلات للوكيل"""

    # ───────────────────────────────────────────────────────────────
    def _build_deputy_referral_tab(self):
        frame = self.deputy_referral_frame

        # ─ Header ─
        hdr = tk.Frame(frame, bg="#0d47a1", height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📥 استلام وإدارة تحويلات الطلاب",
                 bg="#0d47a1", fg="white",
                 font=("Tahoma", 13, "bold")).pack(side="right", padx=16, pady=10)

        # ─ Filter bar ─
        bar = tk.Frame(frame, bg="#f8f9fa", pady=4)
        bar.pack(fill="x", padx=8)

        tk.Label(bar, text="الحالة:", bg="#f8f9fa",
                 font=("Tahoma", 10)).pack(side="right", padx=4)
        self._dep_status_var = tk.StringVar(value="all")
        for val, lbl in [("all","الكل"),("pending","بانتظار الوكيل"),
                          ("with_deputy","مع الوكيل"),
                          ("with_counselor","مع الموجه"),("resolved","مُغلق")]:
            ttk.Radiobutton(bar, text=lbl, variable=self._dep_status_var,
                            value=val,
                            command=self._load_deputy_referrals).pack(side="right", padx=2)

        ttk.Button(bar, text="🔄 تحديث",
                   command=self._load_deputy_referrals).pack(side="left", padx=6)

        # ─ PanedWindow: قائمة يسار + تفاصيل يمين ─
        paned = tk.PanedWindow(frame, orient="horizontal", sashwidth=6,
                               bg="#e5e7eb", sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        # ── قائمة التحويلات ──────────────────────────────────────
        list_frame = tk.Frame(paned, bg="white")
        paned.add(list_frame, minsize=460)

        tk.Label(list_frame, text="قائمة التحويلات",
                 bg="#0d47a1", fg="white",
                 font=("Tahoma", 10, "bold")).pack(fill="x", ipady=4)

        cols = ("id","date","student","class","subject","teacher","status")
        self._dep_tree = ttk.Treeview(list_frame, columns=cols,
                                       show="headings", height=22)
        for c, h, w in zip(cols,
            ["#","التاريخ","الطالب","الفصل","المادة","المعلم","الحالة"],
            [35, 90, 150, 110, 90, 110, 130]):
            self._dep_tree.heading(c, text=h)
            self._dep_tree.column(c, width=w, anchor="center")

        for st, bg in _STATUS_COLORS.items():
            self._dep_tree.tag_configure(st, background=bg)

        sb = ttk.Scrollbar(list_frame, orient="vertical",
                            command=self._dep_tree.yview)
        self._dep_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._dep_tree.pack(side="left", fill="both", expand=True)
        self._dep_tree.bind("<<TreeviewSelect>>", self._on_dep_select)
        self._dep_tree.bind("<Double-1>", lambda e: self._open_dep_detail())

        # ── لوحة التفاصيل / الإجراءات ───────────────────────────
        detail_outer = tk.Frame(paned, bg="white")
        paned.add(detail_outer, minsize=380)

        tk.Label(detail_outer, text="إجراءات الوكيل",
                 bg="#0d47a1", fg="white",
                 font=("Tahoma", 10, "bold")).pack(fill="x", ipady=4)

        # Scrollable canvas for detail area
        dcv = tk.Canvas(detail_outer, bg="white", highlightthickness=0)
        dvs = ttk.Scrollbar(detail_outer, orient="vertical", command=dcv.yview)
        dcv.configure(yscrollcommand=dvs.set)
        dvs.pack(side="right", fill="y")
        dcv.pack(fill="both", expand=True)

        self._dep_detail_frame = tk.Frame(dcv, bg="white")
        _dcv_win = dcv.create_window((0, 0), window=self._dep_detail_frame,
                                      anchor="nw")

        self._dep_detail_frame.bind("<Configure>",
            lambda e: dcv.configure(scrollregion=dcv.bbox("all")))
        _dcv_last_w = [0]
        def _dcfg(e):
            w = dcv.winfo_width()
            if w == _dcv_last_w[0]: return
            _dcv_last_w[0] = w
            dcv.itemconfig(_dcv_win, width=w)
        dcv.bind("<Configure>", _dcfg)
        dcv.bind("<MouseWheel>", lambda e: dcv.yview_scroll(-1*(e.delta//120), "units"))

        # placeholder
        self._dep_placeholder = tk.Label(self._dep_detail_frame,
                                          text="اختر تحويلاً من القائمة لعرض تفاصيله",
                                          bg="white", fg="#888888",
                                          font=("Tahoma", 11))
        self._dep_placeholder.pack(pady=60)

        self._dep_current_id = None
        self._load_deputy_referrals()

    # ───────────────────────────────────────────────────────────────
    def _load_deputy_referrals(self):
        sf = self._dep_status_var.get()
        rows = get_all_referrals(None if sf == "all" else sf)

        self._dep_tree.delete(*self._dep_tree.get_children())
        for r in rows:
            st = r.get("status","pending")
            self._dep_tree.insert("", "end", iid=str(r["id"]),
                values=(r["id"], r.get("ref_date",""),
                        r.get("student_name",""), r.get("class_name",""),
                        r.get("subject",""),    r.get("teacher_name",""),
                        _STATUS_LABELS.get(st, st)),
                tags=(st,))

    # ───────────────────────────────────────────────────────────────
    def _on_dep_select(self, event=None):
        sel = self._dep_tree.selection()
        if not sel:
            return
        ref_id = int(sel[0])
        self._dep_current_id = ref_id
        self._render_dep_detail(ref_id)

    # ───────────────────────────────────────────────────────────────
    def _open_dep_detail(self):
        if self._dep_current_id:
            self._render_dep_detail(self._dep_current_id)

    # ───────────────────────────────────────────────────────────────
    def _render_dep_detail(self, ref_id: int):
        """يبني نموذج إجراءات الوكيل داخل لوحة التفاصيل."""
        ref = get_referral_by_id(ref_id)
        if not ref:
            return

        # مسح المحتوى السابق
        for w in self._dep_detail_frame.winfo_children():
            w.destroy()

        pad = dict(padx=10, pady=3)

        def sec_hdr(text, color="#0d47a1"):
            f = tk.Frame(self._dep_detail_frame, bg=color, pady=3)
            f.pack(fill="x", padx=6, pady=(8,2))
            tk.Label(f, text=text, bg=color, fg="white",
                     font=("Tahoma", 10, "bold")).pack(side="right", padx=8)

        def info_row(label, value, bg="white"):
            r = tk.Frame(self._dep_detail_frame, bg=bg)
            r.pack(fill="x", **pad)
            tk.Label(r, text=label+":", bg=bg, fg="#555",
                     font=("Tahoma", 9, "bold"), width=18,
                     anchor="e").pack(side="right")
            tk.Label(r, text=value or "—", bg=bg,
                     font=("Tahoma", 10), anchor="w",
                     wraplength=220, justify="right").pack(side="right", padx=4)

        # ═══ بيانات المعلم ═══
        sec_hdr("  معلومات المعلم  ", "#1565C0")
        info_row("المعلم",     ref.get("teacher_name",""))
        info_row("التاريخ",    ref.get("ref_date",""))
        info_row("الطالب",     ref.get("student_name",""))
        info_row("الفصل",      ref.get("class_name",""))
        info_row("المادة",     ref.get("subject",""))
        info_row("الحصة",      str(ref.get("period","")))
        info_row("المخالفة",   ref.get("violation_type","") + " — " + ref.get("violation",""))
        info_row("الأسباب",    ref.get("problem_causes",""))
        info_row("التكرار",    ref.get("repeat_count",""))
        for i in range(1, 6):
            v = ref.get(f"teacher_action{i}", "")
            if v:
                info_row(f"إجراء {i}", v)

        # حالة راهنة
        status = ref.get("status", "pending")
        if status == "resolved":
            sec_hdr("  التحويل مُغلق — تم الحل  ", "#2e7d32")
            return
        if status == "with_counselor":
            sec_hdr("  جاري مع الموجّه الطلابي  ", "#6a1b9a")
            info_row("تاريخ الإحالة للموجه", ref.get("deputy_referred_date",""))
            return

        # ═══ قسم إجراءات الوكيل ═══
        sec_hdr("  إجراءات وكيل شؤون الطلاب  ", "#0d47a1")

        def frow(label, widget_fn):
            r = tk.Frame(self._dep_detail_frame, bg="white")
            r.pack(fill="x", **pad)
            tk.Label(r, text=label+":", bg="white",
                     font=("Tahoma", 9), width=18, anchor="e").pack(side="right")
            return widget_fn(r)

        # تاريخ المقابلة
        self._dep_meet_date = tk.StringVar(
            value=ref.get("deputy_meeting_date","") or now_riyadh_date())
        frow("تاريخ المقابلة",
             lambda p: ttk.Entry(p, textvariable=self._dep_meet_date,
                                  width=16, font=("Tahoma",10)).pack(side="right",padx=4) or None)

        # الحصة
        self._dep_meet_period = tk.StringVar(
            value=ref.get("deputy_meeting_period",""))
        frow("الحصة",
             lambda p: ttk.Combobox(p, textvariable=self._dep_meet_period,
                                     values=[str(i) for i in range(1,9)],
                                     width=5, state="readonly",
                                     font=("Tahoma",10)).pack(side="right",padx=4) or None)

        # الإجراءات الأربعة
        self._dep_actions = []
        dep_action_labels = [
            "التوجيه والإرشاد",
            "الاتصال بولي الأمر",
            "تحويل للموجه",
            "أخرى",
        ]
        for i, lbl in enumerate(dep_action_labels, 1):
            var = tk.StringVar(value=ref.get(f"deputy_action{i}",""))
            self._dep_actions.append(var)
            frow(f"الإجراء {i} ({lbl})",
                 lambda p, v=var: ttk.Entry(p, textvariable=v,
                                             width=28, font=("Tahoma",10)).pack(
                                             side="right",padx=4) or None)

        # اسم الوكيل
        self._dep_name_var = tk.StringVar(
            value=ref.get("deputy_name","") or CURRENT_USER.get("name",
                          CURRENT_USER.get("username","")))
        frow("اسم الوكيل",
             lambda p: ttk.Entry(p, textvariable=self._dep_name_var,
                                  width=24, font=("Tahoma",10)).pack(side="right",padx=4) or None)

        # تاريخ الوكيل
        self._dep_date_var = tk.StringVar(
            value=ref.get("deputy_date","") or now_riyadh_date())
        frow("تاريخ الوكيل",
             lambda p: ttk.Entry(p, textvariable=self._dep_date_var,
                                  width=16, font=("Tahoma",10)).pack(side="right",padx=4) or None)

        # ─ أزرار الإجراءات ─
        btn_frame = tk.Frame(self._dep_detail_frame, bg="white")
        btn_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(btn_frame, text="💾 حفظ إجراءات الوكيل",
                   command=lambda: self._save_deputy_action(ref_id, False)
                   ).pack(side="right", padx=4)

        ttk.Button(btn_frame, text="👨‍🏫 تحويل للموجّه + إشعار",
                   command=lambda: self._save_deputy_action(ref_id, True)
                   ).pack(side="right", padx=4)

        ttk.Button(btn_frame, text="✅ إغلاق (تم الحل)",
                   command=lambda: self._close_dep_referral(ref_id)
                   ).pack(side="right", padx=4)

    # ───────────────────────────────────────────────────────────────
    def _save_deputy_action(self, ref_id: int, refer_to_counselor: bool):
        data = {
            "deputy_meeting_date":   self._dep_meet_date.get().strip(),
            "deputy_meeting_period": self._dep_meet_period.get().strip(),
            "deputy_name":           self._dep_name_var.get().strip(),
            "deputy_date":           self._dep_date_var.get().strip(),
            "deputy_referred_date":  now_riyadh_date() if refer_to_counselor else "",
            "status":                "with_counselor" if refer_to_counselor else "with_deputy",
        }
        for i, var in enumerate(self._dep_actions, 1):
            data[f"deputy_action{i}"] = var.get().strip()

        if not data["deputy_name"]:
            messagebox.showwarning("تنبيه", "الرجاء إدخال اسم الوكيل")
            return

        update_referral_deputy(ref_id, data)

        if refer_to_counselor:
            # إشعار الموجّه
            ref = get_referral_by_id(ref_id)
            msg = (f"🔔 تحويل طالب للموجّه الطلابي\n"
                   f"الطالب: {ref.get('student_name','')}\n"
                   f"الفصل: {ref.get('class_name','')}\n"
                   f"المادة: {ref.get('subject','')}\n"
                   f"المخالفة: {ref.get('violation','')}\n"
                   f"تاريخ التحويل: {now_riyadh_date()}\n"
                   f"الوكيل: {data['deputy_name']}")
            phones = get_counselor_phones()
            for ph in phones:
                try:
                    send_whatsapp_message(ph, msg)
                except Exception:
                    pass
            if phones:
                messagebox.showinfo("تم", "تم حفظ الإجراءات وإرسال إشعار للموجّه الطلابي ✅")
            else:
                messagebox.showinfo("تم", "تم حفظ الإجراءات\n(لا يوجد رقم موجّه مسجّل في النظام)")
        else:
            messagebox.showinfo("تم", "تم حفظ إجراءات الوكيل ✅")

        self._load_deputy_referrals()
        self._render_dep_detail(ref_id)

    # ───────────────────────────────────────────────────────────────
    def _close_dep_referral(self, ref_id: int):
        if not messagebox.askyesno("تأكيد", "هل تريد إغلاق هذا التحويل وتعليمه (تم الحل)؟"):
            return
        close_referral(ref_id)
        messagebox.showinfo("تم", "تم إغلاق التحويل ✅")
        self._load_deputy_referrals()
        # مسح لوحة التفاصيل
        for w in self._dep_detail_frame.winfo_children():
            w.destroy()
        self._dep_placeholder = tk.Label(self._dep_detail_frame,
                                          text="اختر تحويلاً من القائمة لعرض تفاصيله",
                                          bg="white", fg="#888888",
                                          font=("Tahoma", 11))
        self._dep_placeholder.pack(pady=60)
        self._dep_current_id = None
