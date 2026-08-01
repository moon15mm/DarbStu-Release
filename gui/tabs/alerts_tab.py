# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time, webbrowser
import sqlite3
from constants import now_riyadh_date, DATA_DIR, CONFIG_JSON
from config_manager import invalidate_config_cache, load_config
from database import get_db, load_students
from alerts_service import (get_students_exceeding_threshold, run_smart_alerts,
                             schedule_daily_report, send_alert_for_student,
                             send_daily_report_to_admin, get_student_absence_count,
                             get_student_full_analysis, get_perfect_attendance_students,
                             run_weekly_rewards)
from report_builder import detect_suspicious_patterns, export_to_noor_excel
from whatsapp_service import send_whatsapp_message
from config_manager import render_reward_message

class AlertsTabMixin:
    """Mixin: AlertsTabMixin"""
    def _build_alerts_tab(self):
        frame = self.alerts_frame

        # ══ رأس ═══════════════════════════════════════════════════
        hdr = tk.Frame(frame, bg="#7C3AED", height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🔔 الإشعارات الذكية — الغياب والتأخر",
                 bg="#7C3AED", fg="white",
                 font=("Tahoma",13,"bold")).pack(side="right", padx=16, pady=12)

        # ══ إعدادات (ثابتة في الأعلى بدون canvas) ════════════════
        cfg_lf = ttk.LabelFrame(frame, text=" ⚙️ إعدادات التنبيه ", padding=8)
        cfg_lf.pack(fill="x", padx=8, pady=(6,4))

        cfg = load_config()
        r1 = ttk.Frame(cfg_lf); r1.pack(fill="x", pady=2)
        ttk.Label(r1, text="تنبيه عند تجاوز:", width=18, anchor="e").pack(side="right")
        self.alert_thresh_var = tk.IntVar(value=cfg.get("alert_absence_threshold", 5))
        ttk.Spinbox(r1, from_=1, to=30, textvariable=self.alert_thresh_var,
                    width=6).pack(side="right", padx=4)
        ttk.Label(r1, text="يوم غياب").pack(side="right")
        self.alert_enabled_var = tk.BooleanVar(value=cfg.get("alert_enabled", True))
        ttk.Checkbutton(r1, text="تفعيل الإشعارات التلقائية",
                        variable=self.alert_enabled_var).pack(side="left", padx=16)

        r2 = ttk.Frame(cfg_lf); r2.pack(fill="x", pady=2)
        self.alert_parent_var = tk.BooleanVar(value=cfg.get("alert_notify_parent", True))
        ttk.Checkbutton(r2, text="إشعار ولي الأمر",
                        variable=self.alert_parent_var).pack(side="right", padx=4)
        self.alert_admin_var = tk.BooleanVar(value=cfg.get("alert_notify_admin", True))
        ttk.Checkbutton(r2, text="إشعار الإدارة",
                        variable=self.alert_admin_var).pack(side="right", padx=4)
        ttk.Label(r2, text="جوال الإدارة:", anchor="e").pack(side="right", padx=(10,2))
        self.alert_admin_phone_var = tk.StringVar(value=cfg.get("alert_admin_phone", ""))
        ttk.Entry(r2, textvariable=self.alert_admin_phone_var,
                  width=18, justify="right").pack(side="right", padx=2)

        r3 = ttk.Frame(cfg_lf); r3.pack(fill="x", pady=2)
        self.alert_hour_var = tk.IntVar(value=cfg.get("alert_run_hour", 14))
        ttk.Label(r3, text="وقت التشغيل اليومي:", anchor="e").pack(side="right")
        ttk.Spinbox(r3, from_=8, to=20, textvariable=self.alert_hour_var,
                    width=5).pack(side="right", padx=4)
        ttk.Label(r3, text=":00 أحد–خميس").pack(side="right")

        # التقرير اليومي
        self.daily_report_var = tk.BooleanVar(value=cfg.get("daily_report_enabled", False))
        ttk.Checkbutton(r3, text="تقرير يومي تلقائي",
                        variable=self.daily_report_var,
                        command=self._toggle_daily_report).pack(side="left", padx=16)
        self.dr_hour_var   = tk.IntVar(value=cfg.get("daily_report_hour",   13))
        self.dr_minute_var = tk.IntVar(value=cfg.get("daily_report_minute", 30))
        ttk.Spinbox(r3, from_=8, to=17, textvariable=self.dr_hour_var,
                    width=4).pack(side="left", padx=2)
        ttk.Label(r3, text=":").pack(side="left")
        ttk.Spinbox(r3, from_=0, to=59, textvariable=self.dr_minute_var,
                    width=4).pack(side="left", padx=2)
        self.dr_status_lbl = ttk.Label(r3, text="", foreground="#5A6A7E",
                                        font=("Tahoma", 8))
        self.dr_status_lbl.pack(side="left", padx=6)
        self._update_dr_status_label()

        btn_row = ttk.Frame(cfg_lf); btn_row.pack(fill="x", pady=(4,0))
        ttk.Button(btn_row, text="💾 حفظ الإعدادات",
                   command=self._save_alert_settings).pack(side="right", padx=4)
        ttk.Button(btn_row, text="▶ تشغيل الإشعارات الآن",
                   command=self._run_alerts_now).pack(side="right", padx=4)
        ttk.Button(btn_row, text="📊 إرسال التقرير اليومي الآن",
                   command=self._send_daily_report_now).pack(side="right", padx=4)

        # ══ Notebook داخلي — قسم الغياب / قسم التأخر / الأنماط ═══
        nb = ttk.Notebook(frame)
        nb.pack(fill="both", expand=True, padx=8, pady=(4,8))

        # ─────────────────────────────────────────────────────────
        # تبويب الغياب
        # ─────────────────────────────────────────────────────────
        tab_abs = ttk.Frame(nb); nb.add(tab_abs, text=" 🔴 الغياب ")

        abs_ctrl = ttk.Frame(tab_abs); abs_ctrl.pack(fill="x", padx=6, pady=6)
        self.alert_month_var = tk.StringVar(
            value=datetime.datetime.now().strftime("%Y-%m"))
        ttk.Label(abs_ctrl, text="الشهر (YYYY-MM):").pack(side="right", padx=(0,4))
        ttk.Entry(abs_ctrl, textvariable=self.alert_month_var,
                  width=10).pack(side="right")
        ttk.Button(abs_ctrl, text="🔍 تحديث",
                   command=self._load_alert_students).pack(side="right", padx=4)
        ttk.Button(abs_ctrl, text="📤 إرسال للمحددين",
                   command=self._send_alerts_selected).pack(side="left", padx=4)
        ttk.Button(abs_ctrl, text="👨‍🏫 تحويل للموجّه",
                   command=lambda: self._refer_to_counselor("غياب")).pack(side="left", padx=4)
        self.alert_sel_lbl = ttk.Label(abs_ctrl, text="", foreground="#7C3AED")
        self.alert_sel_lbl.pack(side="left", padx=8)

        cols = ("chk","student_name","class_name","absence_count",
                "last_date","parent_phone","status")
        tree_frame_abs = ttk.Frame(tab_abs)
        tree_frame_abs.pack(fill="both", expand=True, padx=6, pady=(0,6))
        self.tree_alerts = ttk.Treeview(tree_frame_abs, columns=cols,
                                         show="headings", height=14)
        for col, hd, w in zip(cols,
            ["☐","اسم الطالب","الفصل","أيام الغياب","آخر غياب","جوال ولي الأمر","الحالة"],
            [30,200,140,100,100,130,110]):
            self.tree_alerts.heading(col, text=hd)
            self.tree_alerts.column(col, width=w, anchor="center")
        self.tree_alerts.tag_configure("high",     background="#FFEBEE", foreground="#C62828")
        self.tree_alerts.tag_configure("medium",   background="#FFF8E1", foreground="#E65100")
        self.tree_alerts.tag_configure("sent",     background="#E8F5E9", foreground="#2E7D32")
        self.tree_alerts.tag_configure("referred", background="#EDE9FE", foreground="#5B21B6")
        abs_sb = ttk.Scrollbar(tree_frame_abs, orient="vertical",
                                command=self.tree_alerts.yview)
        self.tree_alerts.configure(yscrollcommand=abs_sb.set)
        abs_sb.pack(side="right", fill="y")
        self.tree_alerts.pack(side="left", fill="both", expand=True)
        self.tree_alerts.bind("<Button-1>", self._alert_toggle_check)

        # سجل إرسال الغياب
        log_abs_lf = ttk.LabelFrame(tab_abs, text=" 📝 سجل الإرسال ", padding=4)
        log_abs_lf.pack(fill="x", padx=6, pady=(0,6))
        self.alert_log = tk.Text(log_abs_lf, height=4, state="disabled",
                                  font=("Tahoma",9), wrap="word")
        self.alert_log.pack(fill="x")

        # ─────────────────────────────────────────────────────────
        # تبويب التأخر
        # ─────────────────────────────────────────────────────────
        tab_tard = ttk.Frame(nb); nb.add(tab_tard, text=" 🟠 التأخر ")

        tard_ctrl = ttk.Frame(tab_tard); tard_ctrl.pack(fill="x", padx=6, pady=6)
        self.alert_tard_thresh_var = tk.IntVar(value=cfg.get("alert_tardiness_threshold", 3))
        ttk.Label(tard_ctrl, text="تنبيه عند تجاوز:").pack(side="right", padx=(0,2))
        ttk.Spinbox(tard_ctrl, from_=1, to=30,
                    textvariable=self.alert_tard_thresh_var, width=5).pack(side="right")
        ttk.Label(tard_ctrl, text="مرة  |  الشهر:").pack(side="right", padx=(4,2))
        self.alert_tard_month_var = tk.StringVar(
            value=datetime.datetime.now().strftime("%Y-%m"))
        ttk.Entry(tard_ctrl, textvariable=self.alert_tard_month_var,
                  width=10).pack(side="right")
        ttk.Button(tard_ctrl, text="🔍 تحديث",
                   command=self._load_tardiness_alert_students).pack(side="right", padx=4)
        ttk.Button(tard_ctrl, text="👨‍🏫 تحويل للموجّه",
                   command=lambda: self._refer_to_counselor("تأخر")).pack(side="left", padx=4)
        self.alert_tard_sel_lbl = ttk.Label(tard_ctrl, text="", foreground="#EA580C")
        self.alert_tard_sel_lbl.pack(side="left", padx=8)

        cols_t = ("chk","student_name","class_name","tardiness_count",
                  "last_date","parent_phone","status")
        tree_frame_tard = ttk.Frame(tab_tard)
        tree_frame_tard.pack(fill="both", expand=True, padx=6, pady=(0,6))
        self.tree_alerts_tard = ttk.Treeview(tree_frame_tard, columns=cols_t,
                                              show="headings", height=14)
        for col, hd, w in zip(cols_t,
            ["☐","اسم الطالب","الفصل","مرات التأخر","آخر تأخر","جوال ولي الأمر","الحالة"],
            [30,200,140,110,100,130,110]):
            self.tree_alerts_tard.heading(col, text=hd)
            self.tree_alerts_tard.column(col, width=w, anchor="center")
        self.tree_alerts_tard.tag_configure("high",     background="#FFF3E0", foreground="#E65100")
        self.tree_alerts_tard.tag_configure("medium",   background="#FFF8E1", foreground="#F57C00")
        self.tree_alerts_tard.tag_configure("referred", background="#EDE9FE", foreground="#5B21B6")
        tard_sb = ttk.Scrollbar(tree_frame_tard, orient="vertical",
                                 command=self.tree_alerts_tard.yview)
        self.tree_alerts_tard.configure(yscrollcommand=tard_sb.set)
        tard_sb.pack(side="right", fill="y")
        self.tree_alerts_tard.pack(side="left", fill="both", expand=True)
        self.tree_alerts_tard.bind("<Button-1>", self._tard_alert_toggle_check)

        # ─────────────────────────────────────────────────────────
        # تبويب الأنماط المشبوهة
        # ─────────────────────────────────────────────────────────
        tab_pat = ttk.Frame(nb); nb.add(tab_pat, text=" 🔍 الأنماط المشبوهة ")

        pat_ctrl = ttk.Frame(tab_pat); pat_ctrl.pack(fill="x", padx=6, pady=6)
        ttk.Button(pat_ctrl, text="🔍 تحليل الأنماط الآن",
                   command=self._detect_patterns).pack(side="right", padx=4)
        ttk.Label(pat_ctrl,
            text="يكتشف: غياب متكرر الأحد/الخميس | غياب جماعي +30%",
            foreground="#5A6A7E", font=("Tahoma",8)).pack(side="right", padx=8)

        cols_p = ("type","name_or_class","desc","count")
        self.tree_patterns = ttk.Treeview(tab_pat, columns=cols_p,
                                           show="headings", height=14)
        for c,h,w in zip(cols_p,
            ["النوع","الطالب/الفصل","التفاصيل","العدد"],
            [110,200,360,70]):
            self.tree_patterns.heading(c, text=h)
            self.tree_patterns.column(c, width=w, anchor="center")
        self.tree_patterns.tag_configure("repeated", background="#FFF8E1", foreground="#E65100")
        self.tree_patterns.tag_configure("mass",     background="#FFEBEE", foreground="#C62828")
        pat_sb = ttk.Scrollbar(tab_pat, orient="vertical",
                                command=self.tree_patterns.yview)
        self.tree_patterns.configure(yscrollcommand=pat_sb.set)
        pat_sb.pack(side="right", fill="y", pady=6, padx=(0,6))
        self.tree_patterns.pack(side="left", fill="both", expand=True, padx=(6,0))

        # ─────────────────────────────────────────────────────────
        # تبويب تعزيز الحضور (Weekly Rewards)
        # ─────────────────────────────────────────────────────────
        tab_reward = ttk.Frame(nb); nb.add(tab_reward, text=" 🏆 تعزيز الحضور ")
        
        rew_ctrl = ttk.Frame(tab_reward); rew_ctrl.pack(fill="x", padx=6, pady=6)
        self.weekly_reward_enabled_var = tk.BooleanVar(value=cfg.get("weekly_reward_enabled", False))
        ttk.Checkbutton(rew_ctrl, text="تفعيل التعزيز الأسبوعي التلقائي",
                        variable=self.weekly_reward_enabled_var,
                        command=self._save_weekly_reward_settings).pack(side="right", padx=10)
        
        ttk.Button(rew_ctrl, text="🔎 حصر الملتزمين الآن",
                   command=self._load_perfect_students).pack(side="right", padx=4)
        
        ttk.Button(rew_ctrl, text="🚀 إرسال رسائل التعزيز الآن",
                   command=self._run_weekly_rewards_now).pack(side="left", padx=4)

        # إعدادات الوقت والقالب
        rew_cfg_f = ttk.LabelFrame(tab_reward, text=" 📝 إعدادات الرسالة والوقت ", padding=8)
        rew_cfg_f.pack(fill="x", padx=8, pady=4)
        
        rf1 = ttk.Frame(rew_cfg_f); rf1.pack(fill="x", pady=2)
        ttk.Label(rf1, text="وقت الإرسال (كل خميس):", width=20, anchor="e").pack(side="right")
        self.rew_hour_var = tk.IntVar(value=cfg.get("weekly_reward_hour", 14))
        self.rew_min_var  = tk.IntVar(value=cfg.get("weekly_reward_minute", 0))
        ttk.Spinbox(rf1, from_=8, to=20, textvariable=self.rew_hour_var, width=4).pack(side="right", padx=2)
        ttk.Label(rf1, text=":").pack(side="right")
        ttk.Spinbox(rf1, from_=0, to=59, textvariable=self.rew_min_var, width=4).pack(side="right", padx=2)
        
        ttk.Button(rf1, text="💾 حفظ الوقت والقالب", command=self._save_weekly_reward_settings).pack(side="left")

        rf2 = ttk.Frame(rew_cfg_f); rf2.pack(fill="x", pady=4)
        ttk.Label(rf2, text="نص الرسالة:", width=20, anchor="e").pack(side="right", anchor="n")
        self.rew_template_txt = tk.Text(rf2, height=4, width=50, font=("Tahoma", 9))
        self.rew_template_txt.pack(side="right", padx=4, fill="x", expand=True)
        self.rew_template_txt.insert("1.0", cfg.get("weekly_reward_template", ""))

        # جدول الطلاب الملتزمين
        rew_list_f = ttk.Frame(tab_reward)
        rew_list_f.pack(fill="both", expand=True, padx=6, pady=4)
        
        cols_r = ("name", "class", "phone", "status")
        self.tree_rewards = ttk.Treeview(rew_list_f, columns=cols_r, show="headings", height=8)
        for c, h, w in zip(cols_r, ["اسم الطالب", "الفصل", "الجوال", "الحالة"], [200, 150, 120, 120]):
            self.tree_rewards.heading(c, text=h)
            self.tree_rewards.column(c, width=w, anchor="center")
        
        rew_sb = ttk.Scrollbar(rew_list_f, orient="vertical", command=self.tree_rewards.yview)
        self.tree_rewards.configure(yscrollcommand=rew_sb.set)
        rew_sb.pack(side="right", fill="y")
        self.tree_rewards.pack(side="left", fill="both", expand=True)

        # ══ تهيئة ══════════════════════════════════════════════════
        self._alert_checked      = set()
        self._tard_alert_checked = set()
        self._load_alert_students()
        self._load_tardiness_alert_students()

    def _detect_patterns(self):
        """يحلل أنماط الغياب ويعرضها في الجدول."""
        if not hasattr(self,"tree_patterns"): return
        for i in self.tree_patterns.get_children(): self.tree_patterns.delete(i)

        import threading as _th
        def _run():
            patterns = detect_suspicious_patterns()
            def _show():
                for p in patterns:
                    if p["type"] == "repeated_day":
                        self.tree_patterns.insert("","end", tags=("repeated",),
                            values=("تكرار يومي",
                                    p["name"]+" / "+p["class_name"],
                                    p["desc"], p["count"]))
                    elif p["type"] == "mass_absence":
                        self.tree_patterns.insert("","end", tags=("mass",),
                            values=("غياب جماعي",
                                    p["class_name"],
                                    p["desc"], "{}%".format(p["pct"])))
                if not patterns:
                    self.tree_patterns.insert("","end",
                        values=("✅","—","لا توجد أنماط مشبوهة","—"))
            self.root.after(0, _show)
        _th.Thread(target=_run, daemon=True).start()

    # ── قسم التأخر: تحميل الطلاب ────────────────────────────────
    def _load_tardiness_alert_students(self):
        """يحمّل الطلاب المتأخرين المتكررين في قسم التأخر."""
        if not hasattr(self, "tree_alerts_tard"): return
        for i in self.tree_alerts_tard.get_children():
            self.tree_alerts_tard.delete(i)
        if hasattr(self, "_tard_alert_checked"):
            self._tard_alert_checked.clear()

        month     = self.alert_tard_month_var.get().strip() if hasattr(self, "alert_tard_month_var") else datetime.datetime.now().strftime("%Y-%m")
        threshold = self.alert_tard_thresh_var.get() if hasattr(self, "alert_tard_thresh_var") else 3

        def _worker():
            try:
                from database import get_cloud_client
                client = get_cloud_client()
                if client and client.is_active():
                    resp = client.get("/web/api/alerts-tardiness")
                    if resp.get("ok"):
                        rows = resp.get("rows", [])
                        referred_ids = set()
                        self.root.after(0, lambda r=rows, ri=referred_ids: self._fill_tard_alert_tree(r, ri, threshold))
                        return
            except Exception:
                pass
            # محلي
            con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
            cur.execute("""
                SELECT student_id,
                       MAX(student_name) as student_name,
                       MAX(class_name)   as class_name,
                       COUNT(*)          as tardiness_count,
                       MAX(date)         as last_date
                FROM tardiness
                WHERE date LIKE ?
                GROUP BY student_id
                HAVING tardiness_count >= ?
                ORDER BY tardiness_count DESC
            """, (month + "%", threshold))
            rows = [dict(r) for r in cur.fetchall()]
            con.close()
            store = load_students()
            phone_map = {s["id"]: s.get("phone","") for cls in store["list"] for s in cls["students"]}
            for r in rows:
                r["parent_phone"] = phone_map.get(r["student_id"], "")
            con2 = get_db(); con2.row_factory = sqlite3.Row; cur2 = con2.cursor()
            cur2.execute("SELECT student_id FROM counselor_referrals WHERE referral_type='تأخر'")
            referred_ids = {r["student_id"] for r in cur2.fetchall()}
            con2.close()
            self.root.after(0, lambda r=rows, ri=referred_ids: self._fill_tard_alert_tree(r, ri, threshold))

        threading.Thread(target=_worker, daemon=True).start()

    def _fill_tard_alert_tree(self, rows, referred_ids, threshold):
        if not hasattr(self, "tree_alerts_tard"): return
        for i in self.tree_alerts_tard.get_children():
            self.tree_alerts_tard.delete(i)
        if hasattr(self, "_tard_alert_checked"):
            self._tard_alert_checked.clear()
        for r in rows:
            cnt    = r.get("tardiness_count", 0)
            sid    = r["student_id"]
            is_ref = r.get("already_referred", sid in referred_ids)
            tag    = "referred" if is_ref else ("high" if cnt >= threshold * 2 else "medium")
            phone  = r.get("parent_phone","") or "—"
            status = "✅ محوّل للموجّه" if is_ref else ""
            self.tree_alerts_tard.insert("", "end", tags=(tag,),
                iid="tard_" + sid,
                values=("☐", r["student_name"], r["class_name"],
                        "{} مرة".format(cnt), r.get("last_date",""), phone, status))
        if hasattr(self, "alert_tard_sel_lbl"):
            self.alert_tard_sel_lbl.configure(text="إجمالي: {} طالب".format(len(rows)))

    def _tard_alert_toggle_check(self, event):
        """تبديل تحديد الطلاب في قسم التأخر."""
        region = self.tree_alerts_tard.identify("region", event.x, event.y)
        if region != "cell": return
        col = self.tree_alerts_tard.identify_column(event.x)
        if col != "#1": return
        iid = self.tree_alerts_tard.identify_row(event.y)
        if not iid: return
        if iid in self._tard_alert_checked:
            self._tard_alert_checked.discard(iid)
            vals = list(self.tree_alerts_tard.item(iid, "values"))
            vals[0] = "☐"
            self.tree_alerts_tard.item(iid, values=vals)
        else:
            self._tard_alert_checked.add(iid)
            vals = list(self.tree_alerts_tard.item(iid, "values"))
            vals[0] = "☑"
            self.tree_alerts_tard.item(iid, values=vals)
        if hasattr(self, "alert_tard_sel_lbl"):
            self.alert_tard_sel_lbl.configure(
                text="محدد: {} | إجمالي: {}".format(
                    len(self._tard_alert_checked),
                    len(self.tree_alerts_tard.get_children())))

    def _refer_to_counselor(self, referral_type: str = "غياب"):
        """
        يحوّل الطلاب المحددين (☑) للموجّه الطلابي.
        referral_type: 'غياب' أو 'تأخر'
        """
        if referral_type == "غياب":
            checked   = self._alert_checked
            tree      = self.tree_alerts
            month     = self.alert_month_var.get().strip() if hasattr(self,"alert_month_var") else datetime.datetime.now().strftime("%Y-%m")
            threshold = self.alert_thresh_var.get() if hasattr(self,"alert_thresh_var") else 5
            all_stu   = {s["student_id"]: s for s in get_students_exceeding_threshold(threshold, month)}
        else:
            checked   = self._tard_alert_checked
            tree      = self.tree_alerts_tard
            month     = self.alert_tard_month_var.get().strip() if hasattr(self,"alert_tard_month_var") else datetime.datetime.now().strftime("%Y-%m")
            threshold = self.alert_tard_thresh_var.get() if hasattr(self,"alert_tard_thresh_var") else 3
            all_stu   = None  # سنقرأ من الـ tree مباشرة

        if not checked:
            messagebox.showwarning("تنبيه",
                "انقر على ☐ لتحديد الطلاب أولاً", parent=self.root); return

        if not messagebox.askyesno("تأكيد",
            "تحويل {} طالب للموجّه الطلابي كـ '{}'؟".format(len(checked), referral_type),
            parent=self.root): return

        now_str  = datetime.datetime.now().isoformat()
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        con = get_db(); cur = con.cursor()
        count_new = 0

        for iid in checked:
            # استخرج بيانات الطالب من الـ tree
            vals = tree.item(iid, "values")
            # vals: (chk, student_name, class_name, count_col, last_date, phone, status)
            sname = vals[1]; sclass = vals[2]; cnt_str = vals[3]
            # استخرج الـ student_id من iid
            if referral_type == "غياب":
                sid = iid  # في قسم الغياب iid == student_id
                abs_c  = int(str(cnt_str).split()[0]) if cnt_str else 0
                tard_c = 0
            else:
                sid = iid.replace("tard_", "", 1)  # في قسم التأخر iid == "tard_" + student_id
                tard_c = int(str(cnt_str).split()[0]) if cnt_str else 0
                abs_c  = 0

            # تجنب التكرار: أضف فقط إذا لم يكن موجوداً بنفس النوع والشهر
            cur.execute("""SELECT id FROM counselor_referrals
                           WHERE student_id=? AND referral_type=? AND date LIKE ?""",
                        (sid, referral_type, date_str[:7] + "%"))
            if cur.fetchone():
                continue  # مُحوَّل مسبقاً هذا الشهر

            cur.execute("""
                INSERT INTO counselor_referrals
                    (date, student_id, student_name, class_name, referral_type,
                     absence_count, tardiness_count, notes, referred_by, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (date_str, sid, sname, sclass, referral_type,
                  abs_c, tard_c, "", "وكيل شؤون الطلاب", "جديد", now_str))
            count_new += 1

        con.commit(); con.close()

        # لوّن الصفوف المحوّلة وحدّث حقل الحالة
        for iid in checked:
            if tree.exists(iid):
                v = list(tree.item(iid, "values"))
                v[-1] = "✅ محوّل للموجّه"
                tree.item(iid, values=v, tags=("referred",))

        skipped = len(checked) - count_new
        msg = "✅ تم تحويل {} طالب للموجّه الطلابي".format(count_new)
        if skipped:
            msg += "\n(تم تجاهل {} طالب محوّل مسبقاً هذا الشهر)".format(skipped)
        messagebox.showinfo("تم التحويل", msg, parent=self.root)

        # ── إرسال تنبيه واتساب لجوالَي الموجّهَين تلقائياً ─────────────
        if count_new > 0:
            _cfg_ref = load_config()
            _c1 = _cfg_ref.get("counselor1_phone", "").strip()
            _c2 = _cfg_ref.get("counselor2_phone", "").strip()
            if _c1 or _c2:
                # بناء قائمة أسماء الطلاب المحوّلين
                _names = []
                for _iid in checked:
                    if tree.exists(_iid):
                        _v = tree.item(_iid, "values")
                        if _v:
                            _names.append("• {} ({})".format(_v[1], _v[2]))
                _extra = ""
                if len(_names) > 10:
                    _extra = "\n... و{} طلاب آخرين".format(len(_names) - 10)
                _alert_msg = (
                    "🔔 تنبيه جديد من نظام درب\n"
                    "━━━━━━━━━━━━━━━━━━━\n"
                    "📋 تم تحويل {} طالب إليك كـ ({})\n\n"
                    "{}{}\n\n"
                    "👤 بواسطة: وكيل شؤون الطلاب\n"
                    "📅 التاريخ: {}"
                ).format(
                    count_new, referral_type,
                    "\n".join(_names[:10]), _extra,
                    date_str
                )
                for _phone in [_c1, _c2]:
                    if _phone:
                        threading.Thread(
                            target=send_whatsapp_message,
                            args=(_phone, _alert_msg),
                            daemon=True
                        ).start()
        # ────────────────────────────────────────────────────────────────

        checked.clear()

    def _save_alert_settings(self):
        cfg = load_config()
        cfg["alert_absence_threshold"] = self.alert_thresh_var.get()
        cfg["alert_enabled"]           = self.alert_enabled_var.get()
        cfg["alert_notify_parent"]     = self.alert_parent_var.get()
        cfg["alert_notify_admin"]      = self.alert_admin_var.get()
        cfg["alert_admin_phone"]       = self.alert_admin_phone_var.get().strip()
        if hasattr(self, "alert_hour_var"):
            cfg["alert_run_hour"]       = self.alert_hour_var.get()
        if hasattr(self, "daily_report_var"):
            cfg["daily_report_enabled"] = self.daily_report_var.get()
            cfg["daily_report_hour"]    = self.dr_hour_var.get()
            cfg["daily_report_minute"]  = self.dr_minute_var.get()
        with open(CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        invalidate_config_cache()
        # أعد جدولة التقرير بالإعدادات الجديدة
        schedule_daily_report(self.root)
        self._update_dr_status_label()
        messagebox.showinfo("تم", "تم حفظ إعدادات الإشعارات بنجاح")

    def _toggle_daily_report(self):
        """تفعيل/إيقاف التقرير اليومي فوراً."""
        cfg = load_config()
        cfg["daily_report_enabled"] = self.daily_report_var.get()
        cfg["daily_report_hour"]    = self.dr_hour_var.get()
        cfg["daily_report_minute"]  = self.dr_minute_var.get()
        with open(CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        invalidate_config_cache()
        schedule_daily_report(self.root)
        self._update_dr_status_label()

    def _update_dr_status_label(self):
        if not hasattr(self, "dr_status_lbl"): return
        cfg = load_config()
        if cfg.get("daily_report_enabled"):
            h = cfg.get("daily_report_hour", 13)
            m = cfg.get("daily_report_minute", 30)
            phone = cfg.get("alert_admin_phone", "")
            self.dr_status_lbl.config(
                text="✅ مفعّل — يُرسَل كل يوم أحد–خميس في {:02d}:{:02d} → {}".format(
                    h, m, phone or "لم يُحدَّد رقم"),
                foreground="#2E7D32")
        else:
            self.dr_status_lbl.config(
                text="⏸ معطّل — فعّله بالخيار أعلاه",
                foreground="#9CA3AF")

    def _send_daily_report_now(self):
        ok, status = send_daily_report_to_admin()
        if ok:
            messagebox.showinfo("تم", "✅ تم إرسال التقرير اليومي للإدارة")
        else:
            messagebox.showwarning("فشل", "❌ تعذّر الإرسال:\n" + status)

    def _load_alert_students(self):
        if not hasattr(self, "tree_alerts"): return
        for i in self.tree_alerts.get_children(): self.tree_alerts.delete(i)
        self._alert_checked.clear()
        month     = self.alert_month_var.get().strip() if hasattr(self,"alert_month_var") else datetime.datetime.now().strftime("%Y-%m")
        threshold = self.alert_thresh_var.get() if hasattr(self,"alert_thresh_var") else 5

        def _worker():
            try:
                from database import get_cloud_client
                client = get_cloud_client()
                if client and client.is_active():
                    resp = client.get("/web/api/alerts-students")
                    students = resp.get("rows", []) if resp.get("ok") else get_students_exceeding_threshold(threshold, month)
                else:
                    students = get_students_exceeding_threshold(threshold, month)
            except Exception:
                students = get_students_exceeding_threshold(threshold, month)
            self.root.after(0, lambda s=students: self._fill_alert_tree(s, threshold))

        threading.Thread(target=_worker, daemon=True).start()

    def _fill_alert_tree(self, students, threshold):
        if not hasattr(self, "tree_alerts"): return
        for i in self.tree_alerts.get_children(): self.tree_alerts.delete(i)
        self._alert_checked.clear()
        for s in students:
            cnt   = s.get("absence_count", 0)
            tag   = "high" if cnt >= threshold * 2 else "medium"
            phone = s.get("parent_phone","") or "—"
            self.tree_alerts.insert("", "end", tags=(tag,),
                iid=s["student_id"],
                values=("☐", s["student_name"], s["class_name"],
                        "{} يوم".format(cnt), s.get("last_date",""),
                        phone, ""))
        self.alert_sel_lbl.configure(
            text="إجمالي: {} طالب".format(len(students)))

    def _alert_toggle_check(self, event):
        region = self.tree_alerts.identify("region", event.x, event.y)
        if region != "cell": return
        col = self.tree_alerts.identify_column(event.x)
        if col != "#1": return  # عمود الـ checkbox فقط
        iid = self.tree_alerts.identify_row(event.y)
        if not iid: return
        if iid in self._alert_checked:
            self._alert_checked.discard(iid)
            vals = list(self.tree_alerts.item(iid, "values"))
            vals[0] = "☐"
            self.tree_alerts.item(iid, values=vals)
        else:
            self._alert_checked.add(iid)
            vals = list(self.tree_alerts.item(iid, "values"))
            vals[0] = "☑"
            self.tree_alerts.item(iid, values=vals)
        self.alert_sel_lbl.configure(
            text="محدد: {} | إجمالي: {}".format(
                len(self._alert_checked),
                len(self.tree_alerts.get_children())))

    def _run_alerts_now(self):
        if not messagebox.askyesno("تأكيد",
            "سيتم إرسال تنبيهات لجميع الطلاب المتجاوزين للعتبة.\nهل تريد المتابعة؟"):
            return
        self._append_alert_log("▶ بدء الإشعارات التلقائية...")
        def do():
            result = run_smart_alerts(
                month=self.alert_month_var.get().strip() if hasattr(self,"alert_month_var") else None,
                log_cb=lambda m: self.root.after(0, lambda msg=m: self._append_alert_log(msg)))
            summary = "✅ اكتمل — ولي أمر: {} | إدارة: {} | فشل: {}".format(
                result.get("sent_parent",0),
                result.get("sent_admin",0),
                result.get("failed",0))
            self.root.after(0, lambda: self._append_alert_log(summary))
            self.root.after(0, self._load_alert_students)
        threading.Thread(target=do, daemon=True).start()

    def _send_alerts_selected(self):
        if not self._alert_checked:
            messagebox.showwarning("تنبيه","انقر على ☐ لتحديد الطلاب أولاً"); return
        if not messagebox.askyesno("تأكيد",
            "إرسال تنبيهات لـ {} طالب؟".format(len(self._alert_checked))):
            return
        month  = self.alert_month_var.get().strip() if hasattr(self,"alert_month_var") else datetime.datetime.now().strftime("%Y-%m")
        thresh = self.alert_thresh_var.get() if hasattr(self,"alert_thresh_var") else 5
        all_s  = {s["student_id"]: s for s in get_students_exceeding_threshold(thresh, month)}
        selected = [all_s[sid] for sid in self._alert_checked if sid in all_s]
        self._append_alert_log("▶ إرسال لـ {} طالب محدد...".format(len(selected)))
        def do():
            cfg = load_config(); ok_p = ok_a = fail = 0
            _delay = max(1, cfg.get("tard_msg_delay_sec", 8))
            for s in selected:
                res = send_alert_for_student(s, cfg)
                if res["parent"]: ok_p += 1
                if res["admin"]:  ok_a += 1
                if res["errors"]: fail += 1
                status = "✅" if (res["parent"] or res["admin"]) else "❌"
                msg = "{} {} — ولي أمر: {} | إدارة: {}".format(
                    status, s["student_name"],
                    "تم" if res["parent"] else "فشل/لا رقم",
                    "تم" if res["admin"]  else "فشل/لا رقم")
                sid = s["student_id"]
                self.root.after(0, lambda m=msg, i=sid: (
                    self._append_alert_log(m),
                    self._update_alert_row(i, "✅ أُرسل" if "✅" in m else "❌ فشل")))
                time.sleep(_delay)  # تأخير بين الرسائل لتجنب حظر الواتساب
            summary = "اكتمل — ولي أمر: {} | إدارة: {} | فشل: {}".format(ok_p, ok_a, fail)
            self.root.after(0, lambda: self._append_alert_log(summary))
        threading.Thread(target=do, daemon=True).start()

    def _update_alert_row(self, iid, status):
        if not self.tree_alerts.exists(iid): return
        vals = list(self.tree_alerts.item(iid, "values"))
        vals[-1] = status
        self.tree_alerts.item(iid, values=vals,
                               tags=("sent" if "✅" in status else "high",))

    def _append_alert_log(self, msg: str):
        if not hasattr(self, "alert_log"): return
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.alert_log.configure(state="normal")
        self.alert_log.insert("end", "[{}] {}\n".format(ts, msg))
        self.alert_log.see("end")
        self.alert_log.configure(state="disabled")

    # ══════════════════════════════════════════════════════════
    # تبويب تصدير نور التلقائي
    # ══════════════════════════════════════════════════════════
    def _build_noor_export_tab(self):
        frame = self.noor_export_frame

        hdr = tk.Frame(frame, bg="#1565C0", height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📤 تصدير ملف نور — يدوي وتلقائي",
                 bg="#1565C0", fg="white",
                 font=("Tahoma",13,"bold")).pack(side="right", padx=16, pady=12)

        body = ttk.Frame(frame); body.pack(fill="both", expand=True, padx=15, pady=15)

        # ─ تصدير يدوي
        manual = ttk.LabelFrame(body, text=" 📋 تصدير يدوي ", padding=12)
        manual.pack(fill="x", pady=(0,12))

        mr1 = ttk.Frame(manual); mr1.pack(fill="x", pady=4)
        ttk.Label(mr1, text="التاريخ:", width=14, anchor="e").pack(side="right")
        self.noor_date_var = tk.StringVar(value=now_riyadh_date())
        ttk.Entry(mr1, textvariable=self.noor_date_var, width=14).pack(side="right", padx=4)

        mr2 = ttk.Frame(manual); mr2.pack(fill="x", pady=4)
        ttk.Label(mr2, text="مجلد الحفظ:", width=14, anchor="e").pack(side="right")
        self.noor_dir_var = tk.StringVar(value=os.path.abspath(DATA_DIR))
        ttk.Entry(mr2, textvariable=self.noor_dir_var, state="readonly",
                  font=("Courier",9), width=40).pack(side="right", padx=4)
        ttk.Button(mr2, text="تغيير", width=8,
                   command=self._noor_choose_dir).pack(side="left")

        ttk.Button(manual, text="💾 تصدير الآن",
                   command=self._noor_export_now).pack(anchor="e", pady=6)
        self.noor_status = ttk.Label(manual, text="", foreground="green")
        self.noor_status.pack(anchor="e")

        # ─ تصدير تلقائي
        auto = ttk.LabelFrame(body, text=" ⏰ تصدير تلقائي في نهاية اليوم ", padding=12)
        auto.pack(fill="x", pady=(0,12))

        ar1 = ttk.Frame(auto); ar1.pack(fill="x", pady=4)
        self.noor_auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ar1, text="تفعيل التصدير التلقائي اليومي",
                        variable=self.noor_auto_var).pack(side="right")

        ar2 = ttk.Frame(auto); ar2.pack(fill="x", pady=4)
        ttk.Label(ar2, text="وقت التصدير:", width=14, anchor="e").pack(side="right")
        self.noor_hour_var = tk.IntVar(value=13)
        ttk.Spinbox(ar2, from_=10, to=17,
                    textvariable=self.noor_hour_var, width=5).pack(side="right", padx=4)
        ttk.Label(ar2, text=":30 (يومياً أيام الأحد–الخميس)").pack(side="right")

        ttk.Button(auto, text="💾 حفظ إعدادات التصدير التلقائي",
                   command=self._noor_save_auto).pack(anchor="e", pady=6)

        # ─ سجل الملفات المُصدَّرة
        hist = ttk.LabelFrame(body, text=" 📁 ملفات نور المُصدَّرة ", padding=8)
        hist.pack(fill="both", expand=True)

        cols = ("filename","date","size","path")
        self.tree_noor = ttk.Treeview(hist, columns=cols, show="headings", height=8)
        for col, hdr_t, w in zip(cols,
            ["اسم الملف","التاريخ","الحجم","المسار"],
            [200,100,80,300]):
            self.tree_noor.heading(col, text=hdr_t)
            self.tree_noor.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(hist, orient="vertical", command=self.tree_noor.yview)
        self.tree_noor.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree_noor.pack(side="left", fill="both", expand=True)
        ttk.Button(hist, text="📂 فتح المجلد",
                   command=self._noor_open_dir).pack(pady=4)
        frame.after(100, self._noor_load_history)

    def _noor_choose_dir(self):
        d = filedialog.askdirectory(title="اختر مجلد حفظ ملفات نور")
        if d and hasattr(self, "noor_dir_var"):
            self.noor_dir_var.set(d)

    def _noor_export_now(self):
        date_str = self.noor_date_var.get().strip() if hasattr(self,"noor_date_var") else now_riyadh_date()
        save_dir = self.noor_dir_var.get().strip() if hasattr(self,"noor_dir_var") else DATA_DIR
        os.makedirs(save_dir, exist_ok=True)
        filename = os.path.join(save_dir, "noor_{}.xlsx".format(date_str))
        try:
            export_to_noor_excel(date_str, filename)
            size_kb = os.path.getsize(filename) // 1024
            if hasattr(self,"noor_status"):
                self.noor_status.configure(
                    text="✅ تم التصدير: {} ({} KB)".format(
                        os.path.basename(filename), size_kb),
                    foreground="green")
            self.noor_export_frame.after(100, self._noor_load_history)
            messagebox.showinfo("تم التصدير", "تم حفظ ملف نور:\n{}".format(filename))
        except Exception as e:
            if hasattr(self,"noor_status"):
                self.noor_status.configure(
                    text="❌ فشل: {}".format(e), foreground="red")

    def _noor_save_auto(self):
        messagebox.showinfo("تم","إعدادات التصدير التلقائي محفوظة. سيعمل كل يوم عمل في الوقت المحدد.")

    def _noor_open_dir(self):
        d = self.noor_dir_var.get() if hasattr(self,"noor_dir_var") else DATA_DIR
        try: os.startfile(os.path.abspath(d))
        except Exception: webbrowser.open("file://{}".format(os.path.abspath(d)))

    def _noor_load_history(self):
        if not hasattr(self,"tree_noor"): return
        for i in self.tree_noor.get_children(): self.tree_noor.delete(i)
        save_dir = self.noor_dir_var.get().strip() if hasattr(self,"noor_dir_var") else DATA_DIR
        if not os.path.isdir(save_dir): return
        files = sorted(
            [f for f in os.listdir(save_dir) if f.startswith("noor_") and f.endswith(".xlsx")],
            reverse=True)
        for f in files[:30]:
            full = os.path.join(save_dir, f)
            size = "{} KB".format(os.path.getsize(full)//1024) if os.path.exists(full) else "—"
            date = f.replace("noor_","").replace(".xlsx","")
            self.tree_noor.insert("","end", values=(f, date, size, full))

    # ══════════════════════════════════════════════════════════
    # ميزات تعزيز الحضور الأسبوعي
    # ══════════════════════════════════════════════════════════
    
    def _save_weekly_reward_settings(self):
        cfg = load_config()
        cfg["weekly_reward_enabled"] = self.weekly_reward_enabled_var.get()
        cfg["weekly_reward_hour"]    = self.rew_hour_var.get()
        cfg["weekly_reward_minute"]  = self.rew_min_var.get()
        cfg["weekly_reward_template"] = self.rew_template_txt.get("1.0", "end-1c").strip()
        
        with open(CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        invalidate_config_cache()
        
        from alerts_service import schedule_weekly_rewards
        schedule_weekly_rewards(self.root)
        
        messagebox.showinfo("تم", "تم حفظ إعدادات تعزيز الحضور بنجاح")

    def _load_perfect_students(self):
        """تحميل قائمة الطلاب الملتزمين لهذا الأسبوع وعرضهم في الجدول."""
        for i in self.tree_rewards.get_children():
            self.tree_rewards.delete(i)
            
        def _worker():
            # حساب الأسبوع الحالي
            today = datetime.date.today()
            days_since_sun = (today.weekday() + 1) % 7
            sun = today - datetime.timedelta(days=days_since_sun)
            thu = sun + datetime.timedelta(days=4)
            
            students = get_perfect_attendance_students(sun.isoformat(), thu.isoformat())
            
            def _show():
                for s in students:
                    self.tree_rewards.insert("", "end", values=(s["name"], s["class_name"], s["phone"], ""))
                if not students:
                    self.tree_rewards.insert("", "end", values=("—", "لا يوجد طلاب ملتزمون", "—", "—"))
            
            self.root.after(0, _show)
            
        threading.Thread(target=_worker, daemon=True).start()

    def _run_weekly_rewards_now(self):
        """تشغيل عملية الإرسال يدوياً."""
        if not messagebox.askyesno("تأكيد", "سيتم إرسال رسائل تهنئة لجميع الطلاب الملتزمين بالحضور هذا الأسبوع.\nهل تريد المتابعة؟"):
            return
            
        def _do():
            result = run_weekly_rewards(log_cb=lambda m: print("[GUI-REWARD]", m))
            
            msg = "✅ اكتملت العملية\n"
            if result.get("skipped"):
                msg = "⚠️ " + result.get("reason", "تم التخطي")
            else:
                msg += "تم الإرسال لـ {} طالب\nفشل الإرسال لـ {} طالب".format(result.get("sent", 0), result.get("failed", 0))
            
            self.root.after(0, lambda: messagebox.showinfo("النتيجة", msg))
            self.root.after(0, self._load_perfect_students)
            
        threading.Thread(target=_do, daemon=True).start()


