# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from database import get_points_leaderboard, load_students, add_student_points
from constants import now_riyadh_date, CURRENT_USER

class LeaderboardTabMixin:
    _lb_cache_data = None  # ذاكرة مؤقتة للبيانات لتجنب تكرار المسح والملء

    def _build_leaderboard_tab(self):
        # العنوان
        hdr = ttk.Frame(self.leaderboard_frame)
        hdr.pack(fill="x", padx=15, pady=10)
        ttk.Label(hdr, text="🏆 لوحة صدارة فرسان الانضباط (النقاط)", 
                  font=("Tahoma", 14, "bold"), foreground="#D97706").pack(side="right")
        
        ttk.Button(hdr, text="🔄 تحديث القائمة", 
                   command=self.refresh_leaderboard).pack(side="left")
        
        self.lb_status_lbl = ttk.Label(hdr, text="", font=("Tahoma", 9))
        self.lb_status_lbl.pack(side="left", padx=10)

        # الجسم الرئيسي: جدول + إضافة نقاط
        body = ttk.Frame(self.leaderboard_frame)
        body.pack(fill="both", expand=True, padx=15, pady=5)
        
        # ── القسم العلوي: جدول الترتيب
        list_lf = ttk.LabelFrame(body, text=" 📊 أعلى الطلاب نقاطاً ", padding=10)
        list_lf.pack(fill="both", expand=True, pady=(0, 10))
        
        cols = ("rank", "name", "class", "points")
        self.tree_lb = ttk.Treeview(list_lf, columns=cols, show="headings", height=15)
        for c, h, w in zip(cols, ["المركز", "اسم الطالب", "الفصل", "إجمالي النقاط"], [60, 250, 150, 100]):
            self.tree_lb.heading(c, text=h)
            self.tree_lb.column(c, width=w, anchor="center")
        
        self.tree_lb.tag_configure("top1", background="#FEF3C7", font=("Tahoma", 10, "bold"))
        self.tree_lb.pack(side="left", fill="both", expand=True)
        
        sb = ttk.Scrollbar(list_lf, orient="vertical", command=self.tree_lb.yview)
        self.tree_lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        
        # ── القسم السفلي: منح نقاط يدوية
        add_lf = ttk.LabelFrame(body, text=" ✨ منح نقاط تميز جديدة ", padding=10)
        add_lf.pack(fill="x")
        
        fg = ttk.Frame(add_lf)
        fg.pack(fill="x")
        
        ttk.Label(fg, text="الفصل:").pack(side="right", padx=5)
        self.lb_cls_var = tk.StringVar()
        self.lb_cls_cb = ttk.Combobox(fg, textvariable=self.lb_cls_var, width=15, state="readonly")
        self.lb_cls_cb.pack(side="right", padx=5)
        self.lb_cls_cb.bind("<<ComboboxSelected>>", self._on_lb_cls_selected)
        
        ttk.Label(fg, text="الطالب:").pack(side="right", padx=5)
        self.lb_stu_var = tk.StringVar()
        self.lb_stu_cb = ttk.Combobox(fg, textvariable=self.lb_stu_var, width=25, state="readonly")
        self.lb_stu_cb.pack(side="right", padx=5)
        
        ttk.Label(fg, text="النقاط:").pack(side="right", padx=5)
        self.lb_pts_var = tk.StringVar(value="5")
        ttk.Entry(fg, textvariable=self.lb_pts_var, width=5).pack(side="right", padx=5)
        
        ttk.Label(fg, text="السبب:").pack(side="right", padx=5)
        self.lb_reason_var = tk.StringVar()
        ttk.Entry(fg, textvariable=self.lb_reason_var, width=20).pack(side="right", padx=5)
        
        ttk.Button(fg, text="➕ منح النقاط", command=self._add_points_manual).pack(side="left", padx=10)
        
        self.lb_balance_lbl = ttk.Label(fg, text="", font=("Tahoma", 9, "bold"), foreground="#059669")
        self.lb_balance_lbl.pack(side="left", padx=10)

        # تحميل البيانات الأولية
        self.refresh_leaderboard()
        self._load_lb_classes()

    def refresh_leaderboard(self):
        # لا تقم بالتحديث إذا لم يكن التبويب ظاهراً حالياً (إلا إذا كانت أول مرة)
        if hasattr(self, "_current_tab") and self._current_tab.get() != "لوحة الصدارة (النقاط)":
             if LeaderboardTabMixin._lb_cache_data is not None:
                 return

        if hasattr(self, "lb_status_lbl"):
            self.lb_status_lbl.config(text="⏳ جارٍ التحميل...", foreground="blue")
        
        def _task():
            try:
                rows = get_points_leaderboard(limit=50)
                self.root.after(0, lambda: self._update_lb_tree(rows))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("خطأ", str(e)))
            finally:
                if hasattr(self, "lb_status_lbl"):
                    self.root.after(0, lambda: self.lb_status_lbl.config(text=""))
        threading.Thread(target=_task, daemon=True).start()

    def _update_lb_tree(self, rows):
        # إذا كانت البيانات هي نفسها السابقة، لا تفعل شيئاً (يمنع الرمش/Flickering)
        if LeaderboardTabMixin._lb_cache_data == rows:
            return
        LeaderboardTabMixin._lb_cache_data = rows

        # مسح القائمة الحالية
        for i in self.tree_lb.get_children():
            self.tree_lb.delete(i)
        for idx, r in enumerate(rows):
            tag = "top1" if idx == 0 else ""
            self.tree_lb.insert("", "end", values=(idx+1, r["name"], r["class_name"], r["points"]), tags=(tag,))

    def _load_lb_classes(self):
        store = load_students()
        cls_names = [c["name"] for c in store.get("list", [])]
        self.lb_cls_cb["values"] = cls_names
        self._update_teacher_balance_display()

    def _update_teacher_balance_display(self):
        if not hasattr(self, "lb_balance_lbl"): return
        author_id = CURRENT_USER.get("username", "admin")
        if author_id == "admin":
            self.lb_balance_lbl.config(text="🛡️ رصيد مفتوح (مدير)")
            return
            
        from database import get_teacher_points_balance
        import datetime
        month = datetime.date.today().isoformat()[:7]
        used = get_teacher_points_balance(author_id, month)
        rem = 100 - used
        self.lb_balance_lbl.config(text=f"💳 رصيدك المتبقي: {rem} نقطة")

    def _on_lb_cls_selected(self, e=None):
        cls_name = self.lb_cls_var.get()
        store = load_students()
        stus = []
        for c in store.get("list", []):
            if c["name"] == cls_name:
                stus = [s["name"] for s in c.get("students", [])]
                break
        self.lb_stu_cb["values"] = stus
        if stus: self.lb_stu_cb.current(0)

    def _add_points_manual(self):
        cls_name = self.lb_cls_var.get()
        stu_name = self.lb_stu_var.get()
        try:
            pts = int(self.lb_pts_var.get())
        except:
            messagebox.showerror("خطأ", "يجب إدخال رقم صحيح للنقاط")
            return
        
        reason = self.lb_reason_var.get()
        if not stu_name:
            messagebox.showerror("خطأ", "يجب اختيار طالب")
            return
        
        # البحث عن ID الطالب
        from database import get_student_map
        m = get_student_map()
        student_id = None
        for sid, info in m.items():
            if info["name"] == stu_name and info["class_name"] == cls_name:
                student_id = sid
                break
        
        if not student_id: return
        
        try:
            author_id = CURRENT_USER.get("username", "admin")
            author_name = CURRENT_USER.get("name") or CURRENT_USER.get("full_name") or "مدير"
            add_student_points(student_id, pts, reason, author_id=author_id, author_name=author_name)
            messagebox.showinfo("تم منح النقاط", f"تم منح {pts} نقطة للطالب {stu_name}.\nتم الخصم من رصيدك الشهري المتاح.")
            self.refresh_leaderboard()
            self._update_teacher_balance_display()
        except ValueError as ve:
            messagebox.showwarning("رصيد غير كافٍ", str(ve))
        except Exception as e:
            messagebox.showerror("خطأ", str(e))

        # تحديث باقي التبويبات إذا كانت مفتوحة
        if hasattr(self, "update_dashboard_metrics"):
            self.update_dashboard_metrics()
