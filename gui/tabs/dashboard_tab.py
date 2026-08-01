# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
from constants import now_riyadh_date
from config_manager import ar
from database import query_tardiness
from alerts_service import get_top_absent_students, get_week_comparison, get_absence_by_day_of_week
from report_builder import compute_today_metrics

# مكتبات الرسم البياني مشتركة لضمان التوافق
from gui.lib_loader import Figure, FigureCanvasTkAgg

class DashboardTabMixin:
    """Mixin: DashboardTabMixin"""
    def _build_dashboard_tab(self):
        style = ttk.Style(); style.theme_use("arc")
        style.configure("Card.TFrame",      background="#ffffff")
        style.configure("CardTitle.TLabel", background="#ffffff",
                        foreground="#6b7280", font=("Tahoma", 9, "bold"))
        style.configure("CardValue.TLabel", background="#ffffff",
                        font=("Tahoma", 22, "bold"))
        style.configure("Treeview",         rowheight=26, font=("Tahoma", 10))
        style.configure("Treeview.Heading", font=("Tahoma", 10, "bold"))

        # ─ شريط التحكم العلوي (ثابت خارج الـ scroll)
        top_bar = ttk.Frame(self.dashboard_frame)
        top_bar.pack(fill="x", padx=10, pady=(10,4))
        ttk.Label(top_bar, text="تاريخ اليوم:",
                  font=("Tahoma",10)).pack(side="right", padx=(0,6))
        self.dash_date_var = tk.StringVar(value=now_riyadh_date())
        ttk.Entry(top_bar, textvariable=self.dash_date_var,
                  width=12).pack(side="right", padx=4)
        ttk.Button(top_bar, text="🔄 تحديث الآن",
                   command=self.update_dashboard_metrics).pack(side="right", padx=4)
        
        # زر الإخفاء في الخلفية (للسيرفر فقط)
        from config_manager import load_config
        if not load_config().get("cloud_mode", False):
            def _hide_app():
                if messagebox.askyesno("إخفاء البرنامج", "سيتم إخفاء نافذة البرنامج وستستمر في العمل في الخلفية.\n\nلإظهارها مرة أخرى، اضغط على أحد الاختصارات التالية:\n1. (Ctrl + Alt + S)\n2. (Ctrl + Shift + S)\n\nهل تريد الإخفاء الآن؟"):
                    self.root.withdraw()
            
            ttk.Button(top_bar, text="👁️ إخفاء في الخلفية",
                       command=_hide_app).pack(side="right", padx=4)
        self.dash_week_lbl = ttk.Label(top_bar, text="",
                                        foreground="#5A6A7E", font=("Tahoma",9))
        self.dash_week_lbl.pack(side="left", padx=8)

        # ─ Canvas قابل للتمرير يحتوي كل المحتوى ──────────────────
        _dash_sb = ttk.Scrollbar(self.dashboard_frame, orient="vertical")
        _dash_sb.pack(side="right", fill="y")
        _dash_canvas = tk.Canvas(self.dashboard_frame, yscrollcommand=_dash_sb.set,
                                  highlightthickness=0)
        _dash_canvas.pack(side="left", fill="both", expand=True)
        _dash_sb.config(command=_dash_canvas.yview)

        _dash_inner = ttk.Frame(_dash_canvas)
        _dash_win   = _dash_canvas.create_window((0,0), window=_dash_inner, anchor="nw")

        def _on_inner_conf(e):
            _dash_canvas.configure(scrollregion=_dash_canvas.bbox("all"))
        _dash_inner.bind("<Configure>", _on_inner_conf)

        _last_cw = [0]
        def _on_canvas_conf(e):
            w = _dash_canvas.winfo_width()
            if w == _last_cw[0]: return
            _last_cw[0] = w
            _dash_canvas.itemconfig(_dash_win, width=w)
        _dash_canvas.bind("<Configure>", _on_canvas_conf)

        _dash_canvas.bind("<Enter>",
            lambda e: _dash_canvas.bind_all("<MouseWheel>",
                lambda ev: _dash_canvas.yview_scroll(int(-1*(ev.delta/120)), "units")))
        _dash_canvas.bind("<Leave>",
            lambda e: _dash_canvas.unbind_all("<MouseWheel>"))

        # كل المحتوى داخل _dash_inner بدلاً من self.dashboard_frame
        _f = _dash_inner  # اختصار

        # ─ شريط التنبيهات الذكية (جديد)
        self.dash_alerts_frame = ttk.Frame(_f)
        self.dash_alerts_frame.pack(fill="x", padx=10, pady=(4,0))
        
        # ─ بطاقات الإحصاء (صف واحد)
        cards_row = ttk.Frame(_f)
        cards_row.pack(fill="x", padx=10, pady=6)

        def make_card(parent, title, color, sub=""):
            fr = ttk.Frame(parent, style="Card.TFrame")
            fr.pack(side="right", padx=6, fill="x", expand=True,
                    ipadx=10, ipady=10)
            ttk.Label(fr, text=title,
                      style="CardTitle.TLabel").pack(anchor="w", padx=10, pady=(8,0))
            val = ttk.Label(fr, text="—", style="CardValue.TLabel",
                             foreground=color)
            val.pack(anchor="w", padx=10)
            sub_lbl = ttk.Label(fr, text=sub, background="#ffffff",
                                 foreground="#9CA3AF", font=("Tahoma",8))
            sub_lbl.pack(anchor="w", padx=10, pady=(0,8))
            return val, sub_lbl

        self.lbl_total,   self.lbl_total_sub   = make_card(cards_row, "إجمالي الطلاب",  "#3B82F6")
        self.lbl_present, self.lbl_present_sub  = make_card(cards_row, "الحضور اليوم",   "#10B981")
        self.lbl_absent,  self.lbl_absent_sub   = make_card(cards_row, "الغياب اليوم",   "#EF4444")
        self.lbl_tard,    self.lbl_tard_sub      = make_card(cards_row, "التأخر اليوم",   "#F59E0B")
        self.lbl_week,    self.lbl_week_sub      = make_card(cards_row, "غياب الأسبوع",   "#8B5CF6",
                                                               "مقارنة بالأسبوع الماضي")
        self.lbl_points,  self.lbl_points_sub    = make_card(cards_row, "نقاط التميز",    "#D97706",
                                                               "إجمالي النقاط اليوم")

        # ─ الجسم الرئيسي: جدول + رسوم بيانية
        body = ttk.Frame(_f)
        body.pack(fill="both", expand=True, padx=10, pady=4)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)

        # ── العمود الأيسر: جدول الفصول + أكثر الطلاب غياباً
        left = ttk.Frame(body); left.grid(row=0, column=0, sticky="nsew", padx=(0,6))
        left.rowconfigure(0, weight=2); left.rowconfigure(1, weight=1)

        # جدول الفصول
        cls_lf = ttk.LabelFrame(left, text=" 📋 الفصول — الحضور والغياب ", padding=4)
        cls_lf.grid(row=0, column=0, sticky="nsew", pady=(0,6))
        cols = ("class_id","class_name","total","present","absent","pct")
        self.tree_dash = ttk.Treeview(cls_lf, columns=cols, show="headings", height=9)
        for c, h, w in zip(cols,
            ["المعرّف","اسم الفصل","الإجمالي","🟢 حاضر","🔴 غائب","نسبة الغياب"],
            [80, 200, 80, 90, 90, 100]):
            self.tree_dash.heading(c, text=h)
            self.tree_dash.column(c, width=w, anchor="center")
        self.tree_dash.tag_configure("high",   background="#FFF0F0")
        self.tree_dash.tag_configure("normal", background="#F0FFF4")
        sb1 = ttk.Scrollbar(cls_lf, orient="vertical",
                             command=self.tree_dash.yview)
        self.tree_dash.configure(yscrollcommand=sb1.set)
        sb1.pack(side="right", fill="y")
        self.tree_dash.pack(side="left", fill="both", expand=True)
        self.tree_dash.bind("<Double-1>", self._on_dash_dblclick)

        # أكثر الطلاب غياباً
        top_lf = ttk.LabelFrame(left, text=" 🏆 أكثر الطلاب غياباً هذا الشهر ", padding=4)
        top_lf.grid(row=1, column=0, sticky="nsew")
        top_cols = ("name","class_name","days","last_date")
        self.tree_top_absent = ttk.Treeview(
            top_lf, columns=top_cols, show="headings", height=5)
        for c, h, w in zip(top_cols,
            ["اسم الطالب","الفصل","أيام الغياب","آخر غياب"],
            [200, 150, 90, 100]):
            self.tree_top_absent.heading(c, text=h)
            self.tree_top_absent.column(c, width=w, anchor="center")
        self.tree_top_absent.tag_configure("top1", background="#FFEBEE",
                                            foreground="#C62828")
        self.tree_top_absent.tag_configure("top3", background="#FFF8E1",
                                            foreground="#E65100")
        self.tree_top_absent.pack(fill="both", expand=True)
        self.tree_top_absent.bind("<Double-1>", self._on_top_absent_dblclick)

        # ── العمود الأيمن: الرسوم البيانية
        right = ttk.Frame(body); right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1); right.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)

        # دائرة الحضور/الغياب
        pie_lf = ttk.LabelFrame(right, text=" نسبة الحضور/الغياب اليوم ", padding=4)
        pie_lf.grid(row=0, column=0, sticky="nsew", pady=(0,4))
        self.fig_pie = Figure(figsize=(4, 2.5), dpi=90)
        self.ax_pie  = self.fig_pie.add_subplot(111)
        self.canvas_pie = FigureCanvasTkAgg(self.fig_pie, pie_lf)
        self.canvas_pie.get_tk_widget().pack(fill="both", expand=True)

        # مقارنة الأسبوعين
        week_lf = ttk.LabelFrame(right, text=" مقارنة هذا الأسبوع بالماضي ", padding=4)
        week_lf.grid(row=1, column=0, sticky="nsew", pady=(0,4))
        self.fig_week = Figure(figsize=(4, 2.3), dpi=90)
        self.ax_week  = self.fig_week.add_subplot(111)
        self.canvas_week = FigureCanvasTkAgg(self.fig_week, week_lf)
        self.canvas_week.get_tk_widget().pack(fill="both", expand=True)

        # أكثر الأيام غياباً
        dow_lf = ttk.LabelFrame(right, text=" أكثر أيام الأسبوع غياباً ", padding=4)
        dow_lf.grid(row=2, column=0, sticky="nsew")
        self.fig_dow = Figure(figsize=(4, 2.3), dpi=90)
        self.ax_dow  = self.fig_dow.add_subplot(111)
        self.canvas_dow = FigureCanvasTkAgg(self.fig_dow, dow_lf)
        self.canvas_dow.get_tk_widget().pack(fill="both", expand=True)

        # ابدأ دورة التحديث التلقائي وفحص التاريخ
        self.root.after(100, self._dashboard_tick)


    # ── بيانات مُخزَّنة مؤقتاً للمخططات الثقيلة ──────────────────
    _dash_cache_wk       = None
    _dash_cache_top      = None
    _dash_cache_dow      = None
    _dash_slow_tick      = 0   # عداد دورات لتحديث المخططات كل 15 دورة (30 دقيقة)

    _last_day_check_time = 0

    def _dashboard_tick(self):
        """دورة تحديث كل دقيقتين، مع تحديث الرسوم الثقيلة كل 30 دقيقة."""
        from constants import now_riyadh_date
        import time
        
        now_ts = time.time()
        # فحص تغير اليوم كل 6 ساعات (21600 ثانية)
        if now_ts - DashboardTabMixin._last_day_check_time >= 21600:
            DashboardTabMixin._last_day_check_time = now_ts
            current_today = now_riyadh_date()
            if hasattr(self, "dash_date_var"):
                if self.dash_date_var.get() != current_today:
                    now_hour = datetime.datetime.now().hour
                    if 0 <= now_hour <= 4: # التحول التلقائي فجراً فقط
                        self.dash_date_var.set(current_today)
                        print(f"[DASHBOARD] Daily refresh check (6h): Switched to {current_today}")

        if hasattr(self, "_current_tab") and self._current_tab.get() == "لوحة المراقبة":
            DashboardTabMixin._dash_slow_tick += 1
            # تحديث الرسوم كل 15 دورة (15 * 2 دقيقة = 30 دقيقة)
            refresh_heavy = DashboardTabMixin._dash_slow_tick >= 15
            if refresh_heavy:
                DashboardTabMixin._dash_slow_tick = 0
            self.update_dashboard_metrics(refresh_heavy=refresh_heavy)
        
        # تكرار الدورة كل دقيقتين (120000 مللي ثانية)
        self.root.after(120000, self._dashboard_tick)

    def update_dashboard_metrics(self, refresh_heavy=True):
        """جلب البيانات في خيط خلفي — الاستعلامات الثقيلة فقط عند refresh_heavy=True."""
        date_str = self.dash_date_var.get().strip() or now_riyadh_date()

        def _fetch():
            try:
                metrics    = compute_today_metrics(date_str)
                tard_today = len(query_tardiness(date_filter=date_str))
                from database import get_points_awarded_on_date
                pts_today  = get_points_awarded_on_date(date_str)
                if refresh_heavy or DashboardTabMixin._dash_cache_wk is None:
                    month      = date_str[:7]
                    wk         = get_week_comparison()
                    top_absent = get_top_absent_students(month, limit=8)
                    dow_data   = get_absence_by_day_of_week()
                    DashboardTabMixin._dash_cache_wk  = wk
                    DashboardTabMixin._dash_cache_top = top_absent
                    DashboardTabMixin._dash_cache_dow = dow_data
                else:
                    wk         = DashboardTabMixin._dash_cache_wk
                    top_absent = DashboardTabMixin._dash_cache_top
                    dow_data   = DashboardTabMixin._dash_cache_dow
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("خطأ", str(e)))
                return
            self.root.after(0, lambda: _update_ui(metrics, tard_today, pts_today, wk, top_absent, dow_data, refresh_heavy))
            
            # فحص التنبيهات الذكية (تحويلات الموجه والتعاميم)
            from database import get_unread_referrals_count, get_circulars, get_user_unread_circulars
            from constants import CURRENT_USER
            try:
                ref_unread = get_unread_referrals_count()
                circs = get_circulars()
                unread_circs = get_user_unread_circulars(CURRENT_USER.get("username", ""), circs)
                self.root.after(0, lambda: self._show_dash_alerts(ref_unread, len(unread_circs)))
            except: pass

        def _update_ui(metrics, tard_today, pts_today, wk, top_absent, dow_data, refresh_heavy=True):
            t = metrics["totals"]
            pct_absent = round(t["absent"] / max(t["students"], 1) * 100, 1)

            # ─ بطاقات الإحصاء
            self.lbl_total.config(text=str(t["students"]))
            self.lbl_present.config(text=str(t["present"]))
            self.lbl_absent.config(text=str(t["absent"]))
            if hasattr(self, "lbl_absent_sub"):
                self.lbl_absent_sub.config(text="{}% من الإجمالي".format(pct_absent))
            if hasattr(self, "lbl_tard"):
                self.lbl_tard.config(text=str(tard_today))
            if hasattr(self, "lbl_points"):
                self.lbl_points.config(text=str(pts_today))

            # مقارنة الأسبوع
            try:
                if hasattr(self, "lbl_week"):
                    self.lbl_week.config(text=str(wk["this_total"]))
                if hasattr(self, "lbl_week_sub"):
                    arrow = "▲" if wk["change"] > 0 else ("▼" if wk["change"] < 0 else "=")
                    color = "#EF4444" if wk["change"] > 0 else "#10B981"
                    self.lbl_week_sub.config(
                        text="{} {}% عن الأسبوع الماضي".format(arrow, abs(wk["pct"])),
                        foreground=color)
                if hasattr(self, "dash_week_lbl"):
                    self.dash_week_lbl.config(
                        text="الأسبوع الماضي: {} غياب".format(wk["last_total"]))
            except Exception as e:
                print("[DASH-WEEK]", e)

            # ─ جدول الفصول
            for i in self.tree_dash.get_children():
                self.tree_dash.delete(i)
            for r in metrics["by_class"]:
                pct = round(r["absent"] / max(r["total"], 1) * 100, 0)
                tag = "high" if pct >= 20 else "normal"
                self.tree_dash.insert("", "end", tags=(tag,),
                    values=(r["class_id"], r["class_name"], r["total"],
                            "🟢 {}".format(r["present"]),
                            "🔴 {}".format(r["absent"]),
                            "{}%".format(int(pct))))

            # ─ أكثر الطلاب غياباً (فقط في دورة ثقيلة)
            if refresh_heavy and hasattr(self, "tree_top_absent"):
                for i in self.tree_top_absent.get_children():
                    self.tree_top_absent.delete(i)
                for idx, s in enumerate(top_absent):
                    tag = "top1" if idx == 0 else ("top3" if idx < 3 else "")
                    self.tree_top_absent.insert("", "end", tags=(tag,),
                        values=(s["name"], s["class_name"],
                                "{} يوم".format(s["days"]), s["last_date"]))

            if not refresh_heavy:
                return  # تخطي رسم المخططات في الدورات السريعة

            # ─ رسم الدائرة
            try:
                self.ax_pie.clear()
                sizes = [t["present"], t["absent"]]
                if sum(sizes) > 0:
                    self.ax_pie.pie(sizes,
                        labels=[ar("الحضور"), ar("الغياب")],
                        autopct="%1.1f%%", startangle=90,
                        colors=["#10B981", "#EF4444"])
                self.ax_pie.set_title(ar("الحضور/الغياب اليوم"), fontsize=9)
                self.canvas_pie.draw_idle()
            except Exception as e:
                print("[DASH-PIE]", e)

            # ─ رسم مقارنة الأسبوعين
            try:
                self.ax_week.clear()
                day_names_short = ["أحد", "إثنين", "ثلاث", "أربع", "خميس"]
                x = range(5)
                this_vals = [wk["this_daily"].get(
                    (datetime.date.fromisoformat(wk["this_week_start"]) +
                     datetime.timedelta(days=i)).isoformat(), 0) for i in range(5)]
                last_vals = [wk["last_daily"].get(
                    (datetime.date.fromisoformat(wk["last_week_start"]) +
                     datetime.timedelta(days=i)).isoformat(), 0) for i in range(5)]
                w_bar = 0.35
                self.ax_week.bar([i - w_bar / 2 for i in x], last_vals,
                                  w_bar, label=ar("الأسبوع الماضي"), color="#93C5FD")
                self.ax_week.bar([i + w_bar / 2 for i in x], this_vals,
                                  w_bar, label=ar("هذا الأسبوع"), color="#3B82F6")
                self.ax_week.set_xticks(list(x))
                self.ax_week.set_xticklabels([ar(d) for d in day_names_short], fontsize=7)
                self.ax_week.legend(fontsize=7)
                self.ax_week.set_title(ar("مقارنة الأسبوعين"), fontsize=9)
                self.canvas_week.draw_idle()
            except Exception as e:
                print("[DASH-WEEK-CHART]", e)

            # ─ رسم أكثر الأيام غياباً
            try:
                self.ax_dow.clear()
                days_ar = list(dow_data.keys())
                vals    = list(dow_data.values())
                if vals:
                    bars = self.ax_dow.bar(
                        [ar(d) for d in days_ar], vals,
                        color=["#EF4444" if v == max(vals) else "#FCA5A5" for v in vals])
                    self.ax_dow.set_title(ar("متوسط الغياب حسب اليوم"), fontsize=9)
                    for bar_r, v in zip(bars, vals):
                        if v > 0:
                            self.ax_dow.text(
                                bar_r.get_x() + bar_r.get_width() / 2,
                                bar_r.get_height(),
                                "{:.0f}".format(v),
                                ha="center", va="bottom", fontsize=7)
                self.canvas_dow.draw_idle()
            except Exception as e:
                print("[DASH-DOW]", e)

        threading.Thread(target=_fetch, daemon=True).start()

    def _show_dash_alerts(self, ref_count, circ_count):
        for widget in self.dash_alerts_frame.winfo_children():
            widget.destroy()
        
        if ref_count == 0 and circ_count == 0:
            return
        
        container = tk.Frame(self.dash_alerts_frame, bg="#FFFBEB", highlightbackground="#FCD34D", highlightthickness=1)
        container.pack(fill="x", pady=4)
        
        lbl_icon = tk.Label(container, text="🔔", bg="#FFFBEB", font=("Tahoma", 14))
        lbl_icon.pack(side="right", padx=10, pady=10)
        
        txt = []
        if ref_count > 0:
            txt.append(f"يوجد ({ref_count}) تحويلات جديدة للموجه الطلابي بانتظار الإجراء.")
        if circ_count > 0:
            txt.append(f"لديك ({circ_count}) تعاميم جديدة غير مقروءة.")
            
        lbl_msg = tk.Label(container, text="\n".join(txt), bg="#FFFBEB", fg="#92400E",
                           font=("Tahoma", 10, "bold"), justify="right")
        lbl_msg.pack(side="right", padx=5)
        
        btn_go = tk.Button(container, text="عرض التفاصيل", bg="#D97706", fg="white", relief="flat",
                           font=("Tahoma", 9, "bold"), cursor="hand2", padx=10,
                           command=lambda: self._switch_tab("التعاميم") if circ_count > 0 else None)
        btn_go.pack(side="left", padx=15, pady=10)

    def _start_msg_polling(self):
        def _poll():
            while True:
                try:
                    from database import get_cloud_client
                    c = get_cloud_client()
                    if c.is_active():
                        res = c.get("/web/api/sync-info")
                        if res.get("ok"):
                           txt = f"متصل بالسيرفر: {c.url}\nآخر مزامنة: {res.get('last_sync','...')}\nعدد السجلات: {res.get('total_records',0)}"
                           self.root.after(0, lambda t=txt: self._set_sync_info(t))
                except: pass
                import time
                time.sleep(120)
        import threading
        threading.Thread(target=_poll, daemon=True).start()

    def _set_sync_info(self, text):
        if hasattr(self, "sync_info_text"):
            self.sync_info_text.config(state="normal")
            self.sync_info_text.delete("1.0", "end")
            self.sync_info_text.insert("1.0", text)
            self.sync_info_text.config(state="disabled")

    def _start_dashboard_tick(self):
        DashboardTabMixin._dash_slow_tick = 0
        DashboardTabMixin._dash_cache_wk  = None
        self.root.after(30000, self._dashboard_tick)

    def _on_dash_dblclick(self, event):
        item = self.tree_dash.focus()
        if not item: return
        vals = self.tree_dash.item(item, "values")
        class_id = vals[0]
        self._switch_tab("إدارة الغياب")
        if hasattr(self, "abs_class_var"):
            self.abs_class_var.set(class_id)
            self.abs_query()

    def _on_top_absent_dblclick(self, event):
        item = self.tree_top_absent.focus()
        if not item: return
        vals = self.tree_top_absent.item(item, "values")
        # في لوحة المراقبة، student_id غير مخفي في الـ values حالياً
        # سأقوم بالبحث عن الطالب بالاسم لفتح تحليله
        # الأفضل هو تعديل الـ Treeview ليحتوي على ID مخفي، لكن سأستخدم البحث الآن لعدم تغيير الـ UI كثيراً
        student_name = vals[0]
        
        # ابحث عن الـ ID من STUDENTS_STORE
        import constants
        store = constants.STUDENTS_STORE
        if store and "list" in store:
            for cls in store["list"]:
                for s in cls.get("students", []):
                    if s.get("name") == student_name:
                        self.open_student_analysis(s.get("id"))
                        return
        
        # إذا لم نجد الـ ID، نفتح التبويب على الأقل
        self._switch_tab("تحليل الطالب")
