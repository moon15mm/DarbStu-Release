# -*- coding: utf-8 -*-
"""
teacher_forms_tab.py — نماذج المعلم (تحضير الدرس / تقرير تنفيذ البرنامج)
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os, datetime, io

from constants import BASE_DIR, CONFIG_JSON
from config_manager import load_config
from whatsapp_service import send_whatsapp_pdf


# ══════════════════════════════════════════════════════════════════
class TeacherFormsTabMixin:
    """Mixin: نماذج المعلم"""

    # ─────────────────────────────────────────────────────────────
    def _build_teacher_forms_tab(self):
        frame = self.teacher_forms_frame

        # رأس التبويب
        hdr = tk.Frame(frame, bg="#0d7377", height=58)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📋 نماذج المعلم",
                 bg="#0d7377", fg="white",
                 font=("Tahoma", 14, "bold")).pack(side="right", padx=20, pady=15)

        # شريط وصفي
        info = tk.Frame(frame, bg="#e0f7fa", pady=8)
        info.pack(fill="x")
        tk.Label(info,
                 text="اختر النموذج المراد تعبئته، ثم أرسله بصيغة PDF لمدير المدرسة عبر الواتساب.",
                 bg="#e0f7fa", font=("Tahoma", 10), fg="#004d50").pack(padx=20)

        # منطقة البطاقات
        cards = tk.Frame(frame, bg="#f5fffe")
        cards.pack(fill="both", expand=True, padx=40, pady=30)

        self._make_form_card(
            cards,
            icon="📘",
            title="نموذج تحضير الدرس",
            desc="يشمل الاستراتيجية والأهداف والأدوات والشواهد",
            color="#0d7377",
            command=self._open_lesson_plan_dialog,
            col=0
        )
        self._make_form_card(
            cards,
            icon="📊",
            title="تقرير تنفيذ البرنامج",
            desc="يشمل المنفذ والأهداف والمستهدفين وشواهد بالصور",
            color="#1565C0",
            command=self._open_program_report_dialog,
            col=1
        )
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)

    def _make_form_card(self, parent, icon, title, desc, color, command, col):
        card = tk.Frame(parent, bg="white", relief="groove", bd=2,
                        cursor="hand2")
        card.grid(row=0, column=col, padx=20, pady=10, sticky="nsew")

        top = tk.Frame(card, bg=color, pady=18)
        top.pack(fill="x")
        tk.Label(top, text=icon, bg=color, fg="white",
                 font=("Tahoma", 30)).pack()
        tk.Label(top, text=title, bg=color, fg="white",
                 font=("Tahoma", 12, "bold")).pack(pady=(4, 0))

        tk.Label(card, text=desc, bg="white", fg="#555",
                 font=("Tahoma", 9), wraplength=200,
                 justify="center").pack(pady=14)

        btn = tk.Button(card, text=f"فتح {title}",
                        bg=color, fg="white",
                        font=("Tahoma", 10, "bold"),
                        relief="flat", cursor="hand2",
                        padx=20, pady=8,
                        command=command)
        btn.pack(pady=(0, 18))

        for w in (card, top):
            w.bind("<Button-1>", lambda e, c=command: c())

    # ══════════════════════════════════════════════════════════════
    #  نموذج تحضير الدرس
    # ══════════════════════════════════════════════════════════════
    def _open_lesson_plan_dialog(self):
        cfg  = load_config()
        school = cfg.get("school_name", "")
        principal_phone = cfg.get("principal_phone", "").strip()

        win = tk.Toplevel(self.root)
        win.title("📘 نموذج تحضير الدرس")
        win.geometry("860x780")
        win.resizable(True, True)
        win.configure(bg="#f0f4f8")
        try: win.state("zoomed")
        except: pass
        win.grab_set()

        # ── canvas scroll ───────────────────────────────────────
        outer = tk.Frame(win, bg="#f0f4f8")
        outer.pack(fill="both", expand=True)
        cvs = tk.Canvas(outer, bg="#f0f4f8", highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=cvs.yview)
        cvs.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        cvs.pack(side="left", fill="both", expand=True)
        main = tk.Frame(cvs, bg="#f0f4f8", padx=24, pady=18)
        _win_id = cvs.create_window((0, 0), window=main, anchor="nw")
        main.bind("<Configure>", lambda e: cvs.configure(
            scrollregion=cvs.bbox("all")))
        _last_w = [0]
        def _on_cvs_conf(e):
            w = cvs.winfo_width()
            if w == _last_w[0]: return
            _last_w[0] = w
            cvs.itemconfig(_win_id, width=w)
        cvs.bind("<Configure>", _on_cvs_conf)
        win.bind("<MouseWheel>",
                 lambda e: cvs.yview_scroll(int(-1*(e.delta/120)), "units"))

        GREEN = "#0d7377"; WHITE = "white"
        FONT_H = ("Tahoma", 11, "bold"); FONT_N = ("Tahoma", 10)

        # ── رأس النموذج ─────────────────────────────────────────
        hdr_f = tk.Frame(main, bg=GREEN, pady=10)
        hdr_f.pack(fill="x", pady=(0, 10))
        tk.Label(hdr_f, text="نموذج تحضير الدرس",
                 bg=GREEN, fg=WHITE, font=("Tahoma", 14, "bold")).pack()
        tk.Label(hdr_f, text=school or "— اسم المدرسة —",
                 bg=GREEN, fg="#b2ebf2", font=("Tahoma", 9)).pack()

        def section(title):
            f = tk.LabelFrame(main, text=f"  {title}  ",
                              font=FONT_H, fg=GREEN,
                              bg=WHITE, relief="solid", bd=1,
                              padx=10, pady=8)
            f.pack(fill="x", pady=(0, 8))
            return f

        def field_row(parent, label, widget_fn, row, col_label=3, col_widget=9):
            tk.Label(parent, text=label+":", bg=WHITE,
                     font=FONT_N, anchor="e",
                     width=col_label).grid(
                         row=row, column=1, sticky="e", padx=4, pady=3)
            w = widget_fn(parent)
            w.grid(row=row, column=0, sticky="w", padx=4, pady=3)
            return w

        # ── القسم 1: بيانات الدرس ──────────────────────────────
        s1 = section("بيانات الدرس")
        s1.columnconfigure(0, weight=1); s1.columnconfigure(1, weight=0)

        strategies = [
            "التعلم المبني على حل المشكلات",
            "التعلم التعاوني",
            "التعلم المدمج",
            "التعلم بالاستفسار",
            "الفصل المقلوب",
            "التعلم النشط",
            "التعلم بالمشروع",
            "التعلم الفردي",
        ]
        strat_var = tk.StringVar()
        strat_cb  = ttk.Combobox(s1, textvariable=strat_var,
                                  values=strategies, width=28,
                                  font=FONT_N, state="normal")
        strat_cb.grid(row=0, column=0, sticky="w", padx=4, pady=3)
        tk.Label(s1, text="الاستراتيجية:", bg=WHITE,
                 font=FONT_N, anchor="e").grid(
                     row=0, column=1, sticky="e", padx=4, pady=3)

        subject_var = tk.StringVar()
        tk.Entry(s1, textvariable=subject_var,
                 width=30, font=FONT_N).grid(
                     row=1, column=0, sticky="w", padx=4, pady=3)
        tk.Label(s1, text="المادة:", bg=WHITE,
                 font=FONT_N, anchor="e").grid(
                     row=1, column=1, sticky="e", padx=4, pady=3)

        date_var = tk.StringVar(
            value=datetime.datetime.now().strftime("%Y/%m/%d"))
        tk.Entry(s1, textvariable=date_var,
                 width=18, font=FONT_N).grid(
                     row=2, column=0, sticky="w", padx=4, pady=3)
        tk.Label(s1, text="تاريخ التنفيذ:", bg=WHITE,
                 font=FONT_N, anchor="e").grid(
                     row=2, column=1, sticky="e", padx=4, pady=3)

        grade_var = tk.StringVar()
        grade_cb  = ttk.Combobox(s1, textvariable=grade_var,
                                  values=["الأول ابتدائي","الثاني ابتدائي",
                                          "الثالث ابتدائي","الرابع ابتدائي",
                                          "الخامس ابتدائي","السادس ابتدائي",
                                          "الأول متوسط","الثاني متوسط","الثالث متوسط",
                                          "الأول ثانوي","الثاني ثانوي","الثالث ثانوي"],
                                  width=22, font=FONT_N, state="readonly")
        grade_cb.grid(row=3, column=0, sticky="w", padx=4, pady=3)
        tk.Label(s1, text="المرحلة الدراسية:", bg=WHITE,
                 font=FONT_N, anchor="e").grid(
                     row=3, column=1, sticky="e", padx=4, pady=3)

        class_var = tk.StringVar(value="جميع الفصول")
        tk.Entry(s1, textvariable=class_var,
                 width=22, font=FONT_N).grid(
                     row=4, column=0, sticky="w", padx=4, pady=3)
        tk.Label(s1, text="الفصل:", bg=WHITE,
                 font=FONT_N, anchor="e").grid(
                     row=4, column=1, sticky="e", padx=4, pady=3)

        count_var = tk.StringVar(value="30")
        tk.Entry(s1, textvariable=count_var,
                 width=8, font=FONT_N).grid(
                     row=5, column=0, sticky="w", padx=4, pady=3)
        tk.Label(s1, text="عدد الطلاب:", bg=WHITE,
                 font=FONT_N, anchor="e").grid(
                     row=5, column=1, sticky="e", padx=4, pady=3)

        lesson_var = tk.StringVar()
        tk.Entry(s1, textvariable=lesson_var,
                 width=40, font=FONT_N).grid(
                     row=6, column=0, sticky="w", padx=4, pady=3)
        tk.Label(s1, text="الدرس:", bg=WHITE,
                 font=FONT_N, anchor="e").grid(
                     row=6, column=1, sticky="e", padx=4, pady=3)

        # ── القسم 2: الأدوات والوسائل ──────────────────────────
        s2 = section("الأدوات والوسائل التعليمية")
        _ALL_TOOLS = [
            "سبورة تقليدية", "جهاز عرض",
            "سبورة ذكية",    "جهاز الحاسب",
            "بطاقات تعليمية","صور توضيحية",
            "أوراق عمل",     "أدوات رياضية",
            "عرض تقديمي",    "كتاب",
        ]
        # مجموعة الأدوات المختارة — تُعدَّل مباشرةً عند الضغط
        _selected_tools = set()
        _tool_btns = {}

        def _toggle_tool(name):
            if name in _selected_tools:
                _selected_tools.discard(name)
                _tool_btns[name].config(
                    text=f"☐  {name}", bg="#f0f0f0", fg="#333",
                    relief="groove")
            else:
                _selected_tools.add(name)
                _tool_btns[name].config(
                    text=f"☑  {name}", bg=GREEN, fg=WHITE,
                    relief="flat")

        for i, t_name in enumerate(_ALL_TOOLS):
            row_, col_ = divmod(i, 2)
            col_frame = 1 - col_   # RTL: col 1 = يمين، col 0 = يسار
            btn = tk.Button(s2,
                            text=f"☐  {t_name}",
                            bg="#f0f0f0", fg="#333",
                            font=("Tahoma", 10),
                            relief="groove", cursor="hand2",
                            anchor="e", width=18,
                            command=lambda n=t_name: _toggle_tool(n))
            btn.grid(row=row_, column=col_frame, sticky="ew",
                     padx=6, pady=3)
            _tool_btns[t_name] = btn

        # ── القسم 3: الأهداف ────────────────────────────────────
        s3 = section("الأهداف  (اتركها فارغة لاستبعادها من الملف)")
        _GOAL_DEFAULTS = ["الهدف الأول.", "الهدف الثاني.", "الهدف الثالث.",
                          "الهدف الرابع.", "الهدف الخامس."]
        goal_vars = []
        for i in range(1, 6):
            v = tk.StringVar(value="")   # فارغة — المعلم يكتب بنفسه
            goal_vars.append(v)
            r = tk.Frame(s3, bg=WHITE); r.pack(fill="x", pady=2)
            tk.Label(r, text=f"{i}.", bg=WHITE,
                     font=FONT_N, width=3).pack(side="right")
            tk.Entry(r, textvariable=v, width=58,
                     font=FONT_N).pack(side="right", fill="x", expand=True)

        # ── القسم 4: الشواهد ────────────────────────────────────
        s4 = section("الشواهد")
        evidence_txt = tk.Text(s4, height=5, font=FONT_N,
                                relief="groove", wrap="word")
        evidence_txt.pack(fill="x")

        # صورة شاهد اختيارية
        _ev_img_path = [None]
        ev_img_lbl   = tk.Label(s4, text="لا توجد صورة مرفقة",
                                 bg=WHITE, fg="#888",
                                 font=("Tahoma", 9))
        ev_img_lbl.pack(side="right", padx=6, pady=4)

        def _pick_ev_img():
            p = filedialog.askopenfilename(
                parent=win, title="اختر صورة الشاهد",
                filetypes=[("الصور", "*.png *.jpg *.jpeg *.bmp"),
                           ("الكل", "*.*")])
            if p:
                _ev_img_path[0] = p
                ev_img_lbl.config(text=f"✅ {os.path.basename(p)}", fg=GREEN)

        tk.Button(s4, text="📎 إرفاق صورة شاهد",
                  bg=GREEN, fg=WHITE,
                  font=("Tahoma", 9, "bold"),
                  relief="flat", cursor="hand2",
                  command=_pick_ev_img).pack(side="right", pady=4)

        # ── التواقيع ─────────────────────────────────────────────
        sig_f = tk.Frame(main, bg=WHITE, relief="groove", bd=1, pady=8)
        sig_f.pack(fill="x", pady=(0, 8))
        teacher_name_var = tk.StringVar()
        principal_name_var = tk.StringVar(
            value=cfg.get("principal_name", ""))

        sig_r = tk.Frame(sig_f, bg=WHITE); sig_r.pack(fill="x", padx=20)
        tk.Label(sig_r, text="اسم المعلم:", bg=WHITE,
                 font=FONT_N).pack(side="right", padx=4)
        tk.Entry(sig_r, textvariable=teacher_name_var,
                 width=22, font=FONT_N).pack(side="right")
        tk.Label(sig_r, text="     ", bg=WHITE).pack(side="right")
        tk.Label(sig_r, text="مدير المدرسة:", bg=WHITE,
                 font=FONT_N).pack(side="right", padx=4)
        tk.Entry(sig_r, textvariable=principal_name_var,
                 width=22, font=FONT_N).pack(side="right")

        # ── أزرار الإجراءات ──────────────────────────────────────
        btns_f = tk.Frame(win, bg="#e8f5e9", pady=10)
        btns_f.pack(fill="x", side="bottom")

        def _collect_lesson():
            return {
                "school":         school,
                "strategy":       strat_var.get().strip(),
                "subject":        subject_var.get().strip(),
                "date":           date_var.get().strip(),
                "grade":          grade_var.get().strip(),
                "class_name":     class_var.get().strip(),
                "student_count":  count_var.get().strip(),
                "lesson":         lesson_var.get().strip(),
                "tools":          list(_selected_tools),
                "goals":          [v.get().strip() for v in goal_vars],
                "evidence":       evidence_txt.get("1.0", "end-1c").strip(),
                "evidence_img":   _ev_img_path[0],
                "executor_name":  teacher_name_var.get().strip(),
                "teacher_name":   teacher_name_var.get().strip(),
                "principal_name": principal_name_var.get().strip(),
            }

        def _preview():
            d = _collect_lesson()
            try:
                pdf_bytes = _make_lesson_pdf(d)
            except Exception as e:
                messagebox.showerror("خطأ PDF", str(e), parent=win); return
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".pdf", prefix="lesson_plan_")
            tmp.write(pdf_bytes); tmp.close()
            try:
                if os.name == "nt": os.startfile(tmp.name)
            except Exception: pass
            messagebox.showinfo("تم", f"تم فتح ملف PDF\n{tmp.name}", parent=win)

        def _send():
            if not principal_phone:
                messagebox.showerror(
                    "خطأ", "لم يُسجَّل رقم مدير المدرسة في الإعدادات",
                    parent=win); return
            d = _collect_lesson()
            try:
                pdf_bytes = _make_lesson_pdf(d)
            except Exception as e:
                messagebox.showerror("خطأ PDF", str(e), parent=win); return
            fname   = "تحضير_الدرس_{}.pdf".format(
                d.get("lesson","").replace(" ", "_") or
                datetime.datetime.now().strftime("%Y%m%d"))
            caption = "📘 نموذج تحضير الدرس — {} — {}".format(
                d.get("lesson",""), d.get("date",""))
            ok, res = send_whatsapp_pdf(principal_phone, pdf_bytes,
                                        fname, caption)
            if ok:
                messagebox.showinfo(
                    "✅ تم", "تم إرسال النموذج لمدير المدرسة ✅", parent=win)
            else:
                messagebox.showerror(
                    "فشل الإرسال", res, parent=win)

        for txt, bg, cmd in [
            ("🖨️ معاينة / طباعة", "#0d7377", _preview),
            ("📲 إرسال لمدير المدرسة", "#1565C0", _send),
            ("❌ إغلاق", "#6b7280", win.destroy),
        ]:
            tk.Button(btns_f, text=txt, bg=bg, fg=WHITE,
                      font=("Tahoma", 10, "bold"),
                      relief="flat", cursor="hand2",
                      padx=14, pady=7,
                      command=cmd).pack(side="right", padx=8)

    # ══════════════════════════════════════════════════════════════
    #  نموذج تقرير تنفيذ البرنامج
    # ══════════════════════════════════════════════════════════════
    def _open_program_report_dialog(self):
        cfg   = load_config()
        school = cfg.get("school_name", "")
        principal_phone = cfg.get("principal_phone", "").strip()

        win = tk.Toplevel(self.root)
        win.title("📊 تقرير تنفيذ البرنامج")
        win.geometry("800x760")
        win.resizable(True, True)
        win.configure(bg="#f0f4f8")
        try: win.state("zoomed")
        except: pass
        win.grab_set()

        outer = tk.Frame(win, bg="#f0f4f8")
        outer.pack(fill="both", expand=True)
        cvs = tk.Canvas(outer, bg="#f0f4f8", highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=cvs.yview)
        cvs.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        cvs.pack(side="left", fill="both", expand=True)
        main = tk.Frame(cvs, bg="#f0f4f8", padx=24, pady=18)
        _wid = cvs.create_window((0, 0), window=main, anchor="nw")
        main.bind("<Configure>",
                  lambda e: cvs.configure(scrollregion=cvs.bbox("all")))
        _lw = [0]
        def _cc(e):
            w = cvs.winfo_width()
            if w == _lw[0]: return
            _lw[0] = w; cvs.itemconfig(_wid, width=w)
        cvs.bind("<Configure>", _cc)
        win.bind("<MouseWheel>",
                 lambda e: cvs.yview_scroll(int(-1*(e.delta/120)), "units"))

        BLUE = "#1565C0"; WHITE = "white"
        FONT_H = ("Tahoma", 11, "bold"); FONT_N = ("Tahoma", 10)

        # رأس
        hf = tk.Frame(main, bg=BLUE, pady=12)
        hf.pack(fill="x", pady=(0, 10))
        tk.Label(hf, text="تقرير تنفيذ البرنامج",
                 bg=BLUE, fg=WHITE,
                 font=("Tahoma", 14, "bold")).pack()
        tk.Label(hf, text=school or "— اسم المدرسة —",
                 bg=BLUE, fg="#bbdefb",
                 font=("Tahoma", 9)).pack()

        def section(title):
            f = tk.LabelFrame(main, text=f"  {title}  ",
                              font=FONT_H, fg=BLUE, bg=WHITE,
                              relief="solid", bd=1,
                              padx=10, pady=8)
            f.pack(fill="x", pady=(0, 8))
            return f

        # ── بيانات التقرير ───────────────────────────────────────
        s1 = section("بيانات البرنامج")
        fields_data = [
            ("المنفذ",           "executor",    ""),
            ("مكان التنفيذ",     "place",       ""),
            ("المستهدفون",       "target",      ""),
            ("عدد المستفيدين",   "count",       ""),
            ("تاريخ التنفيذ",    "date",
             datetime.datetime.now().strftime("%Y/%m/%d")),
        ]
        prog_vars = {}
        for i, (lbl, key, default) in enumerate(fields_data):
            s1.columnconfigure(0, weight=1)
            v = tk.StringVar(value=default)
            prog_vars[key] = v
            r = tk.Frame(s1, bg=WHITE); r.pack(fill="x", pady=2)
            tk.Label(r, text=lbl+":", bg=WHITE,
                     font=FONT_N, width=14, anchor="e").pack(side="right")
            tk.Entry(r, textvariable=v, width=40,
                     font=FONT_N).pack(side="right", fill="x",
                                       expand=True, padx=4)

        # ── الأهداف ──────────────────────────────────────────────
        s2 = section("الأهداف")
        prog_goal_vars = []
        for i in range(1, 6):
            v = tk.StringVar(
                value=f"الهدف {['الأول','الثاني','الثالث','الرابع','الخامس'][i-1]}: يكتب النص هنا.")
            prog_goal_vars.append(v)
            r = tk.Frame(s2, bg=WHITE); r.pack(fill="x", pady=2)
            tk.Label(r, text=f"—", bg=WHITE,
                     font=FONT_N, width=3).pack(side="right")
            tk.Entry(r, textvariable=v, width=58,
                     font=FONT_N).pack(side="right",
                                       fill="x", expand=True)

        # ── الشواهد بالصور ───────────────────────────────────────
        s3 = section("الشواهد بالصور")
        _img_paths = [None, None]
        _img_lbls  = []

        img_row = tk.Frame(s3, bg=WHITE)
        img_row.pack(fill="x")
        for i in range(2):
            col_f = tk.Frame(img_row, bg="#f5f5f5", relief="groove",
                             bd=1, padx=10, pady=10)
            col_f.pack(side="right", fill="both",
                       expand=True, padx=8, pady=4)

            tk.Label(col_f,
                     text=f"{i+1} - صورة الشاهد (رقم {i+1})",
                     bg="#f5f5f5", fg=BLUE,
                     font=("Tahoma", 9, "bold")).pack()
            lbl = tk.Label(col_f,
                           text="لا توجد صورة", bg="#f5f5f5",
                           fg="#888", font=("Tahoma", 9))
            lbl.pack(pady=6)
            _img_lbls.append(lbl)

            def _pick(idx=i, l=lbl):
                p = filedialog.askopenfilename(
                    parent=win,
                    title=f"اختر صورة الشاهد {idx+1}",
                    filetypes=[("الصور", "*.png *.jpg *.jpeg *.bmp"),
                               ("الكل", "*.*")])
                if p:
                    _img_paths[idx] = p
                    l.config(text=f"✅ {os.path.basename(p)}", fg=BLUE)

            tk.Button(col_f, text="📎 اختر صورة",
                      bg=BLUE, fg=WHITE,
                      font=("Tahoma", 9, "bold"),
                      relief="flat", cursor="hand2",
                      command=_pick).pack()

        # ── التواقيع ─────────────────────────────────────────────
        sig_f2 = tk.Frame(main, bg="white", relief="groove", bd=1, pady=8)
        sig_f2.pack(fill="x", pady=(0, 8))
        prog_executor_var  = tk.StringVar()
        prog_principal_var = tk.StringVar(value=cfg.get("principal_name", ""))
        sig_r2 = tk.Frame(sig_f2, bg="white"); sig_r2.pack(fill="x", padx=20)
        tk.Label(sig_r2, text="اسم المنفذ:", bg="white",
                 font=("Tahoma", 10)).pack(side="right", padx=4)
        tk.Entry(sig_r2, textvariable=prog_executor_var,
                 width=22, font=("Tahoma", 10)).pack(side="right")
        tk.Label(sig_r2, text="     ", bg="white").pack(side="right")
        tk.Label(sig_r2, text="مدير المدرسة:", bg="white",
                 font=("Tahoma", 10)).pack(side="right", padx=4)
        tk.Entry(sig_r2, textvariable=prog_principal_var,
                 width=22, font=("Tahoma", 10)).pack(side="right")

        # ── أزرار ────────────────────────────────────────────────
        btns_f = tk.Frame(win, bg="#e3f2fd", pady=10)
        btns_f.pack(fill="x", side="bottom")

        def _collect_prog():
            return {
                "school":         school,
                "executor":       prog_vars["executor"].get().strip(),
                "executor_name":  prog_executor_var.get().strip() or prog_vars["executor"].get().strip(),
                "principal_name": prog_principal_var.get().strip(),
                "place":          prog_vars["place"].get().strip(),
                "target":         prog_vars["target"].get().strip(),
                "count":          prog_vars["count"].get().strip(),
                "date":           prog_vars["date"].get().strip(),
                "goals":          [v.get().strip() for v in prog_goal_vars],
                "img1":           _img_paths[0],
                "img2":           _img_paths[1],
            }

        def _preview():
            d = _collect_prog()
            try:
                pdf_bytes = _make_program_pdf(d)
            except Exception as e:
                messagebox.showerror("خطأ PDF", str(e), parent=win); return
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".pdf", prefix="prog_report_")
            tmp.write(pdf_bytes); tmp.close()
            try:
                if os.name == "nt": os.startfile(tmp.name)
            except Exception: pass
            messagebox.showinfo(
                "تم", f"تم فتح ملف PDF\n{tmp.name}", parent=win)

        def _send():
            if not principal_phone:
                messagebox.showerror(
                    "خطأ", "لم يُسجَّل رقم مدير المدرسة في الإعدادات",
                    parent=win); return
            d = _collect_prog()
            try:
                pdf_bytes = _make_program_pdf(d)
            except Exception as e:
                messagebox.showerror("خطأ PDF", str(e), parent=win); return
            fname   = "تقرير_تنفيذ_البرنامج_{}.pdf".format(
                datetime.datetime.now().strftime("%Y%m%d"))
            caption = "📊 تقرير تنفيذ البرنامج — {}".format(d.get("date",""))
            ok, res = send_whatsapp_pdf(
                principal_phone, pdf_bytes, fname, caption)
            if ok:
                messagebox.showinfo(
                    "✅ تم", "تم إرسال التقرير لمدير المدرسة ✅", parent=win)
            else:
                messagebox.showerror("فشل الإرسال", res, parent=win)

        for txt, bg, cmd in [
            ("🖨️ معاينة / طباعة", BLUE, _preview),
            ("📲 إرسال لمدير المدرسة", "#0d7377", _send),
            ("❌ إغلاق", "#6b7280", win.destroy),
        ]:
            tk.Button(btns_f, text=txt, bg=bg, fg=WHITE,
                      font=("Tahoma", 10, "bold"),
                      relief="flat", cursor="hand2",
                      padx=14, pady=7,
                      command=cmd).pack(side="right", padx=8)


# ══════════════════════════════════════════════════════════════════
#  مولّدات PDF
# ══════════════════════════════════════════════════════════════════

def _ar(txt: str) -> str:
    """معالجة النص العربي للعرض الصحيح في ReportLab."""
    try:
        import arabic_reshaper as _rs
        from bidi.algorithm import get_display as _bd
        return _bd(_rs.reshape(str(txt))) if txt else ""
    except ImportError:
        return str(txt) if txt else ""


def _register_fonts():
    """يُسجّل الخط العادي والعريض ويُعيد (regular, bold)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    reg  = "DarbFont"
    bold = "DarbFontBold"

    if reg not in pdfmetrics.getRegisteredFontNames():
        for fp in [r"C:\Windows\Fonts\tahoma.ttf",
                   r"C:\Windows\Fonts\Arial.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
            if os.path.exists(fp):
                try:
                    pdfmetrics.registerFont(TTFont(reg, fp)); break
                except Exception: pass
        else:
            reg = "Helvetica"

    if bold not in pdfmetrics.getRegisteredFontNames():
        for fp in [r"C:\Windows\Fonts\tahomabd.ttf",
                   r"C:\Windows\Fonts\arialbd.ttf",
                   r"C:\Windows\Fonts\Arial Bold.ttf"]:
            if os.path.exists(fp):
                try:
                    pdfmetrics.registerFont(TTFont(bold, fp)); break
                except Exception: pass
        else:
            bold = reg

    return reg, bold


def _register_font():
    return _register_fonts()[0]


def _official_header(font: str, font_bold: str, form_title: str) -> list:
    """
    يبني الترويسة الرسمية — يقرأ اسم المدرسة والمنطقة التعليمية من ملف الإعدادات.
    ┌──────────────────────────────────────────────────────┐  ← navy
    │ المملكة العربية السعودية  │  وزارة التعليم  │       │
    │   [education_region من الإعدادات]  (ممتدة)          │
    └──────────────────────────────────────────────────────┘
    [  [school_name من الإعدادات]  ]  ← teal
    [  عنوان النموذج  ]  ← أبيض بإطار navy
    """
    _cfg = load_config()
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle, Spacer, Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

    NAVY       = colors.HexColor("#1d3d5f")
    TEAL       = colors.HexColor("#0d7a6e")
    DIVIDER    = colors.HexColor("#3a6080")
    WHITE      = colors.white

    def _p(txt, size, fn, align, color):
        s = ParagraphStyle("",
            fontName=fn, fontSize=size,
            textColor=color, alignment=align,
            leading=size * 1.55, wordWrap="RTL")
        return Paragraph(_ar(txt), s)

    # ── الشريط الكبير (navy) يضم صفّين ───────────────────────────
    main = Table(
        [
            # الصف 1: المملكة | وزارة التعليم | فراغ
            [
                _p("المملكة العربية السعودية", 11, font_bold, TA_RIGHT,  WHITE),
                _p("وزارة التعليم",            13, font_bold, TA_CENTER, WHITE),
                _p("",                          11, font_bold, TA_LEFT,   WHITE),
            ],
            # الصف 2: الإدارة العامة (ممتد)
            [
                _p(_cfg.get("education_region", "الإدارة العامة للتعليم"), 11, font_bold, TA_CENTER, WHITE),
                "", "",
            ],
        ],
        colWidths=["38%", "24%", "38%"],
        style=TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), NAVY),
            ("SPAN",          (0,1), (2,1)),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            # صف المملكة ووزارة التعليم
            ("TOPPADDING",    (0,0), (-1,0), 14),
            ("BOTTOMPADDING", (0,0), (-1,0), 6),
            ("RIGHTPADDING",  (0,0), (-1,0), 14),
            ("LEFTPADDING",   (0,0), (-1,0), 14),
            # الفاصل الناعم بين الصفين
            ("LINEBELOW",     (0,0), (-1,0), 0.6, DIVIDER),
            # صف الإدارة العامة
            ("TOPPADDING",    (0,1), (-1,1), 6),
            ("BOTTOMPADDING", (0,1), (-1,1), 12),
        ])
    )

    # ── شريط اسم المدرسة ─────────────────────────────────────────
    school = Table(
        [[_p(_cfg.get("school_name", "اسم المدرسة"), 13, font_bold, TA_CENTER, WHITE)]],
        colWidths=["100%"],
        style=TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), TEAL),
            ("TOPPADDING",    (0,0), (-1,-1), 9),
            ("BOTTOMPADDING", (0,0), (-1,-1), 9),
        ])
    )

    # ── عنوان النموذج ────────────────────────────────────────────
    title = Table(
        [[_p(form_title, 14, font_bold, TA_CENTER, NAVY)]],
        colWidths=["100%"],
        style=TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#eef4fb")),
            ("BOX",           (0,0), (-1,-1), 1.5, NAVY),
            ("TOPPADDING",    (0,0), (-1,-1), 10),
            ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ])
    )

    return [main, school, title, Spacer(1, 0.35*cm)]


def _make_lesson_pdf(d: dict) -> bytes:
    """ينشئ PDF لنموذج تحضير الدرس."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                    Spacer, Table, TableStyle,
                                    HRFlowable, Image as RLImage)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

    buf  = io.BytesIO()
    font, font_bold = _register_fonts()

    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=1.8*cm, leftMargin=1.8*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)

    NAVY    = colors.HexColor("#1d3d5f")
    GREEN_H = colors.HexColor("#0d7377")
    GREEN_L = colors.HexColor("#e0f7fa")
    DARK    = colors.HexColor("#1a1a1a")

    def sty(size=10, bold=False, align=TA_RIGHT, color=DARK):
        fn = font_bold if bold else font
        return ParagraphStyle("",
            fontName=fn, fontSize=size,
            textColor=color, alignment=align,
            leading=size*1.5, wordWrap="RTL")

    def p(txt, size=10, bold=False, align=TA_RIGHT, color=DARK):
        return Paragraph(_ar(txt), sty(size, bold, align, color))

    def hrow(label, value):
        return [p(value, 10), p(label+":", 9, bold=True, color=colors.HexColor("#475569"))]

    story = []
    story.extend(_official_header(font, font_bold, "نموذج تحضير الدرس"))


    # ── جدول البيانات ───────────────────────────────────────────
    data_rows = [
        hrow("الاستراتيجية", d.get("strategy","")),
        hrow("المادة",        d.get("subject","")),
        hrow("تاريخ التنفيذ", d.get("date","")),
        hrow("المرحلة الدراسية", d.get("grade","")),
        hrow("الفصل",        d.get("class_name","")),
        hrow("عدد الطلاب",   d.get("student_count","")),
        hrow("الدرس",        d.get("lesson","")),
    ]
    tbl1 = Table(data_rows, colWidths=["70%", "30%"],
                 style=TableStyle([
                     ("GRID",       (0,0), (-1,-1), 0.5, colors.lightgrey),
                     ("BACKGROUND", (1,0), (1,-1), GREEN_L),
                     ("ALIGN",      (0,0), (-1,-1), "RIGHT"),
                     ("TOPPADDING",    (0,0), (-1,-1), 5),
                     ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                     ("RIGHTPADDING",  (0,0), (-1,-1), 8),
                 ]))
    story.append(tbl1)
    story.append(Spacer(1, 0.3*cm))

    # ── الأدوات ─────────────────────────────────────────────────
    story.append(Table(
        [[p("الأدوات والوسائل التعليمية", 11, align=TA_CENTER,
            color=colors.white)]],
        colWidths=["100%"],
        style=TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), GREEN_H),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ])
    ))
    tools = d.get("tools", [])
    all_tools = ["سبورة تقليدية","جهاز عرض","سبورة ذكية","جهاز الحاسب",
                 "بطاقات تعليمية","صور توضيحية","أوراق عمل","أدوات رياضية",
                 "عرض تقديمي","كتاب"]
    tool_cells = []
    for i in range(0, len(all_tools), 2):
        row_ = []
        for j in range(2):
            if i+j < len(all_tools):
                t = all_tools[i+j]
                mark = "[ X ]" if t in tools else "[   ]"
                row_.append(p(f"{mark}  {t}", 10))
            else:
                row_.append(p(""))
        tool_cells.append(row_[::-1])   # RTL: right col first

    tool_tbl = Table(tool_cells, colWidths=["50%","50%"],
                     style=TableStyle([
                         ("GRID",    (0,0), (-1,-1), 0.4, colors.lightgrey),
                         ("ALIGN",   (0,0), (-1,-1), "RIGHT"),
                         ("TOPPADDING",    (0,0), (-1,-1), 4),
                         ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                         ("RIGHTPADDING",  (0,0), (-1,-1), 12),
                     ]))
    story.append(tool_tbl)
    story.append(Spacer(1, 0.3*cm))

    # ── الأهداف ─────────────────────────────────────────────────
    story.append(Table(
        [[p("الأهداف", 11, align=TA_CENTER, color=colors.white)]],
        colWidths=["100%"],
        style=TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), GREEN_H),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ])
    ))
    goals = d.get("goals", [])
    g_rows = [[p(f"{i+1}. {g}", 10)]
              for i, g in enumerate(goals) if g]
    if g_rows:
        story.append(Table(g_rows, colWidths=["100%"],
                           style=TableStyle([
                               ("GRID",  (0,0), (-1,-1), 0.4, colors.lightgrey),
                               ("ALIGN", (0,0), (-1,-1), "RIGHT"),
                               ("TOPPADDING",    (0,0), (-1,-1), 4),
                               ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                               ("RIGHTPADDING",  (0,0), (-1,-1), 10),
                           ])))
    story.append(Spacer(1, 0.3*cm))

    # ── الشواهد ─────────────────────────────────────────────────
    story.append(Table(
        [[p("الشواهد", 11, align=TA_CENTER, color=colors.white)]],
        colWidths=["100%"],
        style=TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), GREEN_H),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ])
    ))
    ev_text = d.get("evidence", "")
    ev_rows = [[p(ev_text or " ", 10)]]
    story.append(Table(ev_rows, colWidths=["100%"],
                       style=TableStyle([
                           ("BOX",  (0,0), (-1,-1), 0.5, colors.lightgrey),
                           ("ALIGN",(0,0), (-1,-1), "RIGHT"),
                           ("TOPPADDING",    (0,0), (-1,-1), 30),
                           ("BOTTOMPADDING", (0,0), (-1,-1), 30),
                           ("RIGHTPADDING",  (0,0), (-1,-1), 8),
                       ])))

    # صورة الشاهد إن وجدت
    ev_img = d.get("evidence_img")
    if ev_img and os.path.exists(ev_img):
        try:
            story.append(Spacer(1, 0.2*cm))
            story.append(RLImage(ev_img, width=10*cm, height=7*cm,
                                  kind="proportional"))
        except Exception:
            pass

    story.append(Spacer(1, 0.4*cm))

    # ── التواقيع ─────────────────────────────────────────────────
    executor_name  = d.get("executor_name") or d.get("teacher_name") or "اسم المنفذ"
    principal_name = d.get("principal_name") or load_config().get("principal_name", "")
    NAVY_SIG = colors.HexColor("#1d3d5f")
    sig_data = [[
        p("مدير المدرسة", 9, bold=True, align=TA_CENTER, color=NAVY_SIG),
        p("", 9),
        p("اسم المنفذ",   9, bold=True, align=TA_CENTER, color=NAVY_SIG),
    ],[
        p(principal_name, 10, align=TA_CENTER),
        p("", 9),
        p(executor_name,  10, align=TA_CENTER),
    ]]
    story.append(Table(sig_data, colWidths=["40%","20%","40%"],
                       style=TableStyle([
                           ("BOX",           (0,0), (0,-1), 1,   NAVY_SIG),
                           ("BOX",           (2,0), (2,-1), 1,   NAVY_SIG),
                           ("BACKGROUND",    (0,0), (0,0),  colors.HexColor("#e0f7fa")),
                           ("BACKGROUND",    (2,0), (2,0),  colors.HexColor("#e0f7fa")),
                           ("ALIGN",         (0,0), (-1,-1), "CENTER"),
                           ("TOPPADDING",    (0,0), (-1,-1), 10),
                           ("BOTTOMPADDING", (0,0), (-1,-1), 10),
                       ])))

    doc.build(story)
    return buf.getvalue()


def _make_program_pdf(d: dict) -> bytes:
    """ينشئ PDF لتقرير تنفيذ البرنامج."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                    Spacer, Table, TableStyle,
                                    Image as RLImage)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

    buf  = io.BytesIO()
    font, font_bold = _register_fonts()

    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=1.8*cm, leftMargin=1.8*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)

    NAVY   = colors.HexColor("#1d3d5f")
    BLUE_L = colors.HexColor("#e3f2fd")
    TEAL_H = colors.HexColor("#0d7a6e")
    DARK   = colors.HexColor("#1a1a1a")

    def sty(size=10, bold=False, align=TA_RIGHT, color=DARK):
        fn = font_bold if bold else font
        return ParagraphStyle("",
            fontName=fn, fontSize=size,
            textColor=color, alignment=align,
            leading=size*1.6, wordWrap="RTL")

    def p(txt, size=10, bold=False, align=TA_RIGHT, color=DARK):
        return Paragraph(_ar(txt), sty(size, bold, align, color))

    story = []
    story.extend(_official_header(font, font_bold, "تقرير تنفيذ البرنامج"))


    # بيانات
    fields = [
        ("المنفذ",         d.get("executor", "")),
        ("مكان التنفيذ",   d.get("place",    "")),
        ("المستهدفون",     d.get("target",   "")),
        ("عدد المستفيدين", d.get("count",    "")),
        ("تاريخ التنفيذ",  d.get("date",     "")),
    ]
    f_rows = [[p(val, 10), p(lbl+":", 9, bold=True, color=colors.HexColor("#475569"))]
              for lbl, val in fields]
    story.append(Table(f_rows, colWidths=["70%","30%"],
                       style=TableStyle([
                           ("GRID",       (0,0), (-1,-1), 0.5, colors.lightgrey),
                           ("BACKGROUND", (1,0), (1,-1), BLUE_L),
                           ("ALIGN",      (0,0), (-1,-1), "RIGHT"),
                           ("TOPPADDING",    (0,0), (-1,-1), 6),
                           ("BOTTOMPADDING", (0,0), (-1,-1), 6),
                           ("RIGHTPADDING",  (0,0), (-1,-1), 8),
                       ])))
    story.append(Spacer(1, 0.3*cm))

    # الأهداف
    story.append(Table(
        [[p("الأهداف", 11, align=TA_CENTER, color=colors.white)]],
        colWidths=["100%"],
        style=TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), TEAL_H),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ])
    ))
    goals = d.get("goals", [])
    g_rows = [[p(f"— {g}", 10)]
              for g in goals if g]
    if g_rows:
        story.append(Table(g_rows, colWidths=["100%"],
                           style=TableStyle([
                               ("BOX",  (0,0), (-1,-1), 0.5, colors.lightgrey),
                               ("ALIGN",(0,0), (-1,-1), "RIGHT"),
                               ("TOPPADDING",    (0,0), (-1,-1), 5),
                               ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                               ("RIGHTPADDING",  (0,0), (-1,-1), 10),
                           ])))
    story.append(Spacer(1, 0.3*cm))

    # الشواهد بالصور
    story.append(Table(
        [[p("الشواهد", 11, align=TA_CENTER, color=colors.white)]],
        colWidths=["100%"],
        style=TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), TEAL_H),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ])
    ))

    img1 = d.get("img1"); img2 = d.get("img2")

    def _img_cell(idx, img_path):
        lbl_txt = _ar(f"الشاهد {idx}")
        inner = [[Paragraph(lbl_txt, sty(9, False, TA_CENTER, colors.grey))]]
        if img_path and os.path.exists(img_path):
            try:
                inner.append([RLImage(img_path, width=7*cm,
                                      height=5*cm, kind="proportional")])
            except Exception:
                inner.append([Paragraph(_ar("(خطأ في تحميل الصورة)"),
                                         sty(9, False, TA_CENTER, colors.grey))])
        else:
            inner.append([Paragraph(_ar("(لا توجد صورة)"),
                                     sty(9, False, TA_CENTER, colors.grey))])
        return Table(inner, colWidths=["100%"],
                     style=TableStyle([
                         ("BOX",  (0,0), (-1,-1), 0.5, colors.lightgrey),
                         ("ALIGN",(0,0), (-1,-1), "CENTER"),
                         ("TOPPADDING",    (0,0), (-1,-1), 8),
                         ("BOTTOMPADDING", (0,0), (-1,-1), 8),
                     ]))

    story.append(Table(
        [[_img_cell(1, img1), _img_cell(2, img2)]],
        colWidths=["50%", "50%"],
        style=TableStyle([("ALIGN", (0,0), (-1,-1), "CENTER")])
    ))

    story.append(Spacer(1, 0.4*cm))

    # ── التواقيع ─────────────────────────────────────────────────
    executor_name  = d.get("executor_name") or d.get("executor") or "اسم المنفذ"
    principal_name = d.get("principal_name") or load_config().get("principal_name", "")
    NAVY_SIG = colors.HexColor("#1d3d5f")
    sig_data = [[
        p("مدير المدرسة", 9, bold=True, align=TA_CENTER, color=NAVY_SIG),
        p("", 9),
        p("اسم المنفذ",   9, bold=True, align=TA_CENTER, color=NAVY_SIG),
    ],[
        p(principal_name, 10, align=TA_CENTER),
        p("", 9),
        p(executor_name,  10, align=TA_CENTER),
    ]]
    story.append(Table(sig_data, colWidths=["40%","20%","40%"],
                       style=TableStyle([
                           ("BOX",           (0,0), (0,-1), 1,   NAVY_SIG),
                           ("BOX",           (2,0), (2,-1), 1,   NAVY_SIG),
                           ("BACKGROUND",    (0,0), (0,0),  colors.HexColor("#e3f2fd")),
                           ("BACKGROUND",    (2,0), (2,0),  colors.HexColor("#e3f2fd")),
                           ("ALIGN",         (0,0), (-1,-1), "CENTER"),
                           ("TOPPADDING",    (0,0), (-1,-1), 10),
                           ("BOTTOMPADDING", (0,0), (-1,-1), 10),
                       ])))

    doc.build(story)
    return buf.getvalue()
