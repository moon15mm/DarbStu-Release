# -*- coding: utf-8 -*-
"""
gui/app_gui.py — الواجهة الرئيسية للتطبيق
مُبنية باستخدام Python Mixins لفصل كل تبويب في ملف منفصل
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, sys, json, datetime, threading, time, re, io, csv, base64
import sqlite3, subprocess, webbrowser, zipfile, urllib.request, urllib.parse
from typing import List, Dict, Any, Optional

# ── التبعات الثقيلة (مشتركة مع التبويبات) ──
from gui.lib_loader import Figure, FigureCanvasTkAgg, arabic_reshaper, get_display, HtmlFrame

try:
    from PIL import ImageTk
    import qrcode
except ImportError:
    ImageTk = qrcode = None

# ─── استيراد Mixins كل التبويبات ─────────────────────
from gui.tabs.dashboard_tab    import DashboardTabMixin
from gui.tabs.links_tab        import LinksTabMixin
from gui.tabs.absence_tab      import AbsenceTabMixin
from gui.tabs.reports_tab      import ReportsTabMixin
from gui.tabs.phones_tab       import PhonesTabMixin
from gui.tabs.messages_tab     import MessagesTabMixin
from gui.tabs.students_tab     import StudentsTabMixin
from gui.tabs.class_naming_tab   import ClassNamingTabMixin
from gui.tabs.tardiness_tab    import TardinessTabMixin
from gui.tabs.whatsapp_tab     import WhatsappTabMixin
from gui.tabs.excuses_tab      import ExcusesTabMixin
from gui.tabs.users_tab        import UsersTabMixin
from gui.tabs.settings_tab     import SettingsTabMixin
from gui.tabs.cloud_tab        import CloudTabMixin
from gui.tabs.tardiness_msg_tab import TardinessMessagesTabMixin
from gui.tabs.alerts_tab       import AlertsTabMixin
from gui.tabs.noor_tab         import NoorTabMixin
from gui.tabs.counselor_tab    import CounselorTabMixin
from gui.tabs.permissions_tab  import PermissionsTabMixin
from gui.tabs.term_report_tab  import TermReportTabMixin
from gui.tabs.results_tab      import ResultsTabMixin
from gui.tabs.monitor_tab      import MonitorTabMixin
from gui.tabs.schedule_tab     import ScheduleTabMixin
from gui.tabs.add_student_tab  import AddStudentTabMixin
from gui.tabs.grade_analysis_tab   import GradeAnalysisTabMixin
from gui.tabs.referral_teacher_tab import TeacherReferralTabMixin
from gui.tabs.referral_deputy_tab  import DeputyReferralTabMixin
from gui.tabs.teacher_forms_tab    import TeacherFormsTabMixin
from gui.tabs.teacher_inquiries_tab import TeacherInquiriesTabMixin
from gui.tabs.student_analysis_tab import StudentAnalysisTabMixin
from gui.tabs.circulars_tab        import CircularsTabMixin
from gui.tabs.exempted_tab         import ExemptedTabMixin
from gui.tabs.leaderboard_tab       import LeaderboardTabMixin
from gui.tabs.parent_visits_tab     import ParentVisitsTabMixin

# ─── استيراد كل الوحدات اللازمة ───────────────────────
from constants import (APP_TITLE, APP_VERSION, DB_PATH, DATA_DIR, HOST, PORT,
                       BASE_DIR, WHATS_PATH, STUDENTS_JSON, TEACHERS_JSON,
                       CONFIG_JSON, BACKUP_DIR, TZ_OFFSET, STATIC_DOMAIN,
                       CURRENT_USER, ROLES, ROLE_TABS, now_riyadh_date,
                       local_ip, debug_on, navbar_html, STUDENTS_STORE, ensure_dirs)



try:
    from tkcalendar import DateEntry
except ImportError:
    DateEntry = None

from config_manager import (load_config, save_config, get_terms, ar,
                             logo_img_tag_from_config, render_message,
                             get_message_template, invalidate_config_cache,
                             DEFAULT_CONFIG, get_window_title)
from database import (get_db, init_db, load_students, load_teachers,
                       query_absences, query_tardiness, insert_tardiness,
                       delete_tardiness, query_excuses, insert_excuse,
                       delete_excuse, student_has_excuse, compute_tardiness_metrics,
                       create_backup, get_backup_list,
                       get_all_users, create_user, delete_user, toggle_user_active,
                       hash_password, update_user_password, authenticate,
                       get_user_allowed_tabs, save_user_allowed_tabs,
                       norm_token, normalize_legacy_class_id, _apply_class_name_fix,
                       section_label_from_value, display_name_from_legacy,
                       level_name_from_value, import_students_from_excel_sheet2_format,
                       import_teachers_from_excel, insert_absences,
                       _cleanup_old_backups, schedule_auto_backup,
                       EXCUSE_REASONS, get_unread_circulars_count)
from report_builder import (build_daily_report_df, build_total_absences_with_dates_by_class,
                             compute_today_metrics, get_live_monitor_status,
                             export_to_noor_excel, generate_report_html,
                             generate_daily_report, generate_monthly_report,
                             generate_weekly_report, generate_student_report,
                             generate_term_report_html, generate_monitor_table_html,
                             detect_suspicious_patterns, parent_portal_html)
from pdf_generator import (generate_session_pdf, generate_behavioral_contract_pdf,
                             _render_pdf_page_as_png, _render_page_pillow,
                             parse_results_pdf, save_results_to_db, get_student_result,
                             results_portal_html, student_result_html)
from whatsapp_service import (send_whatsapp_message, send_whatsapp_pdf,
                               check_whatsapp_server_status, get_wa_servers,
                               start_whatsapp_server)
from api.mobile_routes import send_tardiness_link_to_all
from alerts_service import (log_message_status, query_today_messages,
                             run_smart_alerts, send_alert_for_student,
                             build_daily_summary_message, send_daily_report_to_admin,
                             schedule_daily_alerts, schedule_daily_report,
                             get_students_exceeding_threshold,
                             get_student_full_analysis,
                             get_top_absent_students, get_student_absence_count,
                             safe_send_absence_alert, get_tardiness_recipients,
                             save_tardiness_recipients,
                             load_schedule, save_schedule,
                             query_permissions, insert_permission,
                             update_permission_status, delete_permission,
                             send_permission_request,
                             PERMISSION_REASONS, PERM_APPROVED, PERM_WAITING,
                             build_absent_groups, get_absence_by_day_of_week,
                             get_week_comparison)
from license_manager import (check_license, LicenseWindow, LicenseClient,
                               activate_license, try_renew_license,
                               generate_tokens, consume_token,
                               _get_machine_id,
                               get_all_tokens, delete_all_tokens, get_tokens_count)
from updater import check_for_updates


class AppGUI(
    DashboardTabMixin,
    LinksTabMixin,
    AbsenceTabMixin,
    ReportsTabMixin,
    PhonesTabMixin,
    MessagesTabMixin,
    StudentsTabMixin,
    TardinessTabMixin,
    WhatsappTabMixin,
    ExcusesTabMixin,
    UsersTabMixin,
    SettingsTabMixin,
    CloudTabMixin,
    TardinessMessagesTabMixin,
    AlertsTabMixin,
    NoorTabMixin,
    CounselorTabMixin,
    PermissionsTabMixin,
    TermReportTabMixin,
    ResultsTabMixin,
    MonitorTabMixin,
    ScheduleTabMixin,
    AddStudentTabMixin,
    GradeAnalysisTabMixin,
    TeacherReferralTabMixin,
    DeputyReferralTabMixin,
    TeacherFormsTabMixin,
    TeacherInquiriesTabMixin,
    StudentAnalysisTabMixin,
    ClassNamingTabMixin,
    CircularsTabMixin,
    ExemptedTabMixin,
    LeaderboardTabMixin,
    ParentVisitsTabMixin,
):
    """الواجهة الرئيسية للتطبيق — تجمع كل Mixins في class واحد."""
    def __init__(self, root, public_url=None):
        # تأنيث تسميات الواجهة في مدارس البنات — قبل بناء أي أداة،
        # فالأدوات المُنشأة قبل الترقيع تبقى مذكَّرة.
        try:
            from gender_ui import install_tk_patch
            install_tk_patch()
        except Exception as _e:
            print(f"[GENDER-UI] تعذّر ترقيع الواجهة: {_e}")

        # 1. تعيين المتغيرات الأساسية أولاً
        self.root = root
        self.root.title(APP_TITLE)
        # في وضع السحاب: الرابط العام = عنوان السيرفر الرئيسي
        try:
            _cfg = load_config()
            if _cfg.get("cloud_mode") and _cfg.get("cloud_url"):
                self.public_url = _cfg["cloud_url"].rstrip("/")
            else:
                self.public_url = public_url
        except Exception:
            self.public_url = public_url
        
        self.scheduler_running = False
        self.scheduler_timers = []

        try:
            # مسار الأيقونة (يجب أن يكون ملف .ico)
            # icon_path = 'icon.ico' 
            # self.root.iconbitmap(icon_path)
            pass # تم تعطيله مؤقتاً
        except Exception as e:
            print(f"Could not load icon: {e}")

        self.store = load_students()
        self.ip = local_ip()
        # عرض الدور في عنوان النافذة
        role_label = CURRENT_USER.get("label","")
        user_name  = CURRENT_USER.get("name", CURRENT_USER.get("username",""))
        root.title(f"{get_window_title()} — {user_name} ({role_label})")
        self.cfg = load_config()

        # ─── كل التبويبات المتاحة في البرنامج ──────────────────────
        all_tabs = {
            "لوحة المراقبة":        "_build_dashboard_tab",
            "روابط الفصول":         "_build_links_tab",
            "التأخر":               "_build_tardiness_tab",
            "الأعذار":              "_build_excuses_tab",
            "الاستئذان":           "_build_permissions_tab",
            "المراقبة الحية":       "_build_live_monitor_tab",
            "السجلات / التصدير":    "_build_logs_tab",
            "إدارة الغياب":         "_build_absence_management_tab",
            "التقارير / الطباعة":   "_build_reports_tab",
            "تقرير الفصل":         "_build_term_report_tab",
            "نشر النتائج":          "_build_results_tab",
            "تحليل النتائج":        "_build_grade_analysis_tab",
            "تحليل الطالب":         "_build_student_analysis_tab",
            "تصدير نور":            "_build_noor_export_tab",
            "الإشعارات الذكية":     "_build_alerts_tab",
            "إرسال رسائل الغياب":   "_build_messages_tab",
            "رسائل التأخر":         "_build_tardiness_messages_tab",
            "مستلمو التأخر":        "_build_tardiness_recipients_tab",
            "جدولة الروابط":        "_build_schedule_tab",
            "إدارة الواتساب":       "_build_whatsapp_manager_tab",
            "إدارة الطلاب":         "_build_student_management_tab",
            "إضافة طالب":           "_build_add_student_tab",
            "إدارة الفصول":         "_build_class_naming_tab",
            "إدارة أرقام الجوالات": "_build_phones_tab",
            "إعدادات المدرسة":      "_build_school_settings_tab",
            "الربط السحابي":        "_build_cloud_tab",
            "المستخدمون":           "_build_users_tab",
            "النسخ الاحتياطية":     "_build_backup_tab",
            "الموجّه الطلابي":      "_build_counselor_tab",
            "تحويل طالب":           "_build_teacher_referral_tab",
            "استلام تحويلات":       "_build_deputy_referral_tab",
            "نماذج المعلم":         "_build_teacher_forms_tab",
            "خطابات الاستفسار":    "_build_teacher_inquiries_tab",
            "التعاميم والنشرات":    "_build_circulars_tab",
            "الطلاب المستثنون":     "_build_exempted_tab",
            "لوحة الصدارة (النقاط)": "_build_leaderboard_tab",
            "زيارات أولياء الأمور":  "_build_parent_visits_tab",
        }

        # مجموعات القائمة الجانبية
        _username = CURRENT_USER.get("username", "admin")
        _allowed  = get_user_allowed_tabs(_username)  # None = مدير = كل شيء

        def _vis(t): return _allowed is None or t in _allowed

        sidebar_groups = [
            ("⬤  يومي", [t for t in [
                "لوحة المراقبة","روابط الفصول","التأخر","لوحة الصدارة (النقاط)",
                "الأعذار","الاستئذان","المراقبة الحية","الموجّه الطلابي",
                "زيارات أولياء الأمور"] if _vis(t)]),
            ("⬤  السجلات", [t for t in [
                "السجلات / التصدير","إدارة الغياب",
                "التقارير / الطباعة","تقرير الفصل","نشر النتائج","تحليل النتائج","تحليل الطالب","تصدير نور","الإشعارات الذكية"] if _vis(t)]),
            ("⬤  الرسائل", [t for t in [
                "إرسال رسائل الغياب","رسائل التأخر",
                "التعاميم والنشرات",
                "مستلمو التأخر","جدولة الروابط","إدارة الواتساب"] if _vis(t)]),
            ("⬤  البيانات", [t for t in [
                "إدارة الطلاب","إضافة طالب",
                "إدارة الفصول","إدارة أرقام الجوالات","الطلاب المستثنون"] if _vis(t)]),
            ("⬤  الإعدادات", [t for t in [
                "إعدادات المدرسة","الربط السحابي","المستخدمون","النسخ الاحتياطية","معلومات الترخيص"] if _vis(t)]),
            ("⬤  التحويلات", [t for t in [
                "تحويل طالب","استلام تحويلات"] if _vis(t)]),
            ("⬤  نماذج المعلم", [t for t in [
                "نماذج المعلم","خطابات الاستفسار"] if _vis(t)]),
        ]

        # ─── فلترة التبويبات حسب صلاحيات المستخدم ───────────────
        username = CURRENT_USER.get("username", "admin")
        allowed  = get_user_allowed_tabs(username)

        if allowed is None:
            self.tabs_config = all_tabs
        else:
            self.tabs_config = {k: v for k, v in all_tabs.items() if k in allowed}
            if not self.tabs_config:
                self.tabs_config = {"لوحة المراقبة": "_build_dashboard_tab"}

        # ─── بناء الواجهة الجانبية ────────────────────────────────
        self._tabs_built   = set()
        self._tab_frames   = {}
        self._nav_buttons  = {}
        self._current_tab  = tk.StringVar()

        # الإطار الرئيسي: sidebar + content
        main_frame = tk.Frame(root, bg="#f0f0f0")
        main_frame.pack(fill="both", expand=True)

        # ── منطقة المحتوى ──
        self._content_area = tk.Frame(main_frame, bg="white")
        self._content_area.pack(side="left", fill="both", expand=True)

        # فاصل عمودي
        tk.Frame(main_frame, bg="#d0d0d0", width=1).pack(side="left", fill="y")

        # ── القائمة الجانبية ──
        sidebar_outer = tk.Frame(main_frame, bg="#f0f0f0", width=185)
        sidebar_outer.pack(side="left", fill="y")
        sidebar_outer.pack_propagate(False)

        sidebar_canvas = tk.Canvas(sidebar_outer, bg="#f0f0f0",
                                    highlightthickness=0, bd=0)
        sidebar_scroll = ttk.Scrollbar(sidebar_outer, orient="vertical",
                                        command=sidebar_canvas.yview)
        sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        sidebar_scroll.pack(side="right", fill="y")
        sidebar_canvas.pack(side="left", fill="both", expand=True)

        sidebar = tk.Frame(sidebar_canvas, bg="#f0f0f0")
        sidebar_win = sidebar_canvas.create_window((0, 0), window=sidebar,
                                                    anchor="nw")

        def _on_sidebar_configure(e):
            sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all"))
        sidebar.bind("<Configure>", _on_sidebar_configure)
        _sb_last_w = [0]
        def _on_sidebar_canvas_conf(e):
            w = sidebar_canvas.winfo_width()
            if w == _sb_last_w[0]: return
            _sb_last_w[0] = w
            sidebar_canvas.itemconfig(sidebar_win, width=w)
        sidebar_canvas.bind("<Configure>", _on_sidebar_canvas_conf)

        # ── بناء عناصر القائمة ──
        for group_title, group_tabs in sidebar_groups:
            # تصفية حسب الصلاحيات
            visible = [t for t in group_tabs if t in self.tabs_config]
            if not visible:
                continue

            # عنوان المجموعة
            grp_lbl = tk.Label(sidebar, text=group_title,
                               bg="#f0f0f0", fg="#888888",
                               font=("Tahoma", 8, "bold"),
                               anchor="w", padx=10, pady=2)
            grp_lbl.pack(fill="x")

            for tab_name in visible:
                btn = tk.Label(sidebar, text=tab_name,
                               bg="#f0f0f0", fg="#333333",
                               font=("Tahoma", 10),
                               anchor="w", padx=14, pady=6,
                               cursor="hand2")
                btn.pack(fill="x")

                def _make_click(name):
                    def _click(e=None):
                        self._switch_tab(name)
                    return _click

                btn.bind("<Button-1>", _make_click(tab_name))
                btn.bind("<Enter>", lambda e, b=btn: b.config(bg="#e0e8f0") if self._current_tab.get() != b.cget("text") else None)
                btn.bind("<Leave>", lambda e, b=btn: b.config(bg="#f0f0f0") if self._current_tab.get() != b.cget("text") else None)
                self._nav_buttons[tab_name] = btn

        # ─── مؤشر حالة Cloudflare (يظهر للمدير فقط) ──────────────
        if _allowed is None and public_url:  # مدير + السيرفر لديه نفق
            cf_bar = tk.Frame(sidebar, bg="#f0f0f0")
            cf_bar.pack(fill="x", padx=8, pady=(4, 0))
            self._cf_dot  = tk.Label(cf_bar, text="⬤", fg="#22c55e",
                                     bg="#f0f0f0", font=("Tahoma", 9))
            self._cf_dot.pack(side="right", padx=(0, 2))
            self._cf_text = tk.Label(cf_bar, text="النفق متصل",
                                     fg="#166534", bg="#f0f0f0",
                                     font=("Tahoma", 8))
            self._cf_text.pack(side="right")

            def _cf_status_update(is_alive: bool):
                color_dot  = "#22c55e" if is_alive else "#ef4444"
                color_text = "#166534" if is_alive else "#991b1b"
                label      = "النفق متصل" if is_alive else "النفق منقطع ⚠"
                self.root.after(0, lambda: (
                    self._cf_dot.config(fg=color_dot),
                    self._cf_text.config(text=label, fg=color_text)
                ))

            from tunnel_manager import set_tunnel_status_callback
            set_tunnel_status_callback(_cf_status_update)

        # ─── تنبيهات التعاميم (Badge) ────────────────────────────
        self.unread_circ_lbl = tk.Label(sidebar, text="", bg="#f0f0f0", fg="red", font=("Tahoma", 9, "bold"))
        self._check_unread_circulars()
        tk.Frame(sidebar, bg="#d8d8d8", height=1).pack(fill="x", padx=8, pady=2)

        # ── إنشاء frames للتبويبات ──
        for tab_name, builder_name in self.tabs_config.items():
            frame_attr = builder_name.replace("_build_", "").replace("_tab", "") + "_frame"
            f = tk.Frame(self._content_area, bg="white")
            f.place(relx=0, rely=0, relwidth=1, relheight=1)
            f.place_forget()
            setattr(self, frame_attr, f)
            self._tab_frames[tab_name] = f

        # ── دالة التبديل بين التبويبات ──
        def _switch_tab(name):
            if name not in self._tab_frames:
                return

            if hasattr(self, '_schedule_auto_refresh_active') and self._current_tab.get() == "جدولة الروابط":
                self._schedule_auto_refresh_active = False

            # أخفِ كل التبويبات
            for f in self._tab_frames.values():
                f.place_forget()

            # تحديث تمييز القائمة
            prev = self._current_tab.get()
            if prev and prev in self._nav_buttons:
                self._nav_buttons[prev].config(bg="#f0f0f0", fg="#333333",
                                                font=("Tahoma", 10))
            self._current_tab.set(name)
            if name in self._nav_buttons:
                self._nav_buttons[name].config(bg="#1565C0", fg="white",
                                                font=("Tahoma", 10, "bold"))

            # بناء التبويب عند أول فتح (Lazy Loading)
            builder_name = self.tabs_config.get(name)
            if builder_name and builder_name not in self._tabs_built:
                self._tabs_built.add(builder_name)
                getattr(self, builder_name)()
                if builder_name == "_build_dashboard_tab" and hasattr(self, "update_dashboard_metrics"):
                    self.root.after(500, self.update_dashboard_metrics)
                    self._start_dashboard_tick()
                if builder_name == "_build_dashboard_tab" and hasattr(self, "_start_msg_polling"):
                    self._start_msg_polling()

            # أظهر التبويب المطلوب
            self._tab_frames[name].place(relx=0, rely=0, relwidth=1, relheight=1)

            if name == "جدولة الروابط" and hasattr(self, '_schedule_auto_refresh_active'):
                self._schedule_auto_refresh_active = True

        self._switch_tab = _switch_tab
        self._main_notebook = None  # للتوافق

        # افتح أول تبويب
        first_tab = next(iter(self.tabs_config.keys()))
        _switch_tab(first_tab)

        # تحقق من التحديثات
        root.after(5000, lambda: check_for_updates(root, silent=True))
        self._build_menu(root)

    def _check_unread_circulars(self):
        def _task():
            try:
                count = get_unread_circulars_count(CURRENT_USER.get("username"), CURRENT_USER.get("role"))
                if count > 0:
                    self.root.after(0, lambda: self._update_circular_badge(count))
                else:
                    self.root.after(0, lambda: self.unread_circ_lbl.place_forget())
            except: pass
        threading.Thread(target=_task, daemon=True).start()
        # جدولة الفحص التالي من الـ main thread لضمان عدم تراكم الـ timers
        self.root.after(300000, self._check_unread_circulars)

    def _update_circular_badge(self, count):
        btn = self._nav_buttons.get("التعاميم والنشرات")
        if btn:
            self.unread_circ_lbl.config(text=str(count))
            self.unread_circ_lbl.place(in_=btn, relx=0.1, rely=0.5, anchor="center")

    def _build_menu(self, root):
        m = tk.Menu(root); root.config(menu=m)
        filem = tk.Menu(m, tearoff=0); m.add_cascade(label="ملف", menu=filem)
        filem.add_command(label="إعادة استيراد الطلاب...", command=self.reimport_students)
        filem.add_command(label="إعادة استيراد المعلمين...", command=self.reimport_teachers)
        filem.add_separator()
        filem.add_command(label="إعدادات المدرسة...", command=self._open_school_settings_tab)
        filem.add_command(label="فتح ملف الإعدادات (JSON)...", command=self.open_config_json)
        filem.add_separator()
        filem.add_command(label=f"التحقق من التحديثات... (v{APP_VERSION})",
                          command=lambda: check_for_updates(self.root, silent=False))
        filem.add_separator()
        filem.add_command(label="خروج", command=self.root.destroy)


    def open_student_analysis(self, student_id: str):
        """تفتح تبويب تحليل الطالب وتُحمل بياناته."""
        self._switch_tab("تحليل الطالب")
        if hasattr(self, "load_student_analysis"):
            self.load_student_analysis(student_id)

    def update_all_tabs_after_data_change(self):
        self.store = load_students(force_reload=True)
        if hasattr(self, "tree_dash"):         self.update_dashboard_metrics()
        if hasattr(self, "_refresh_links_and_teachers"): self._refresh_links_and_teachers()
        if hasattr(self, "refresh_logs"):         self.refresh_logs()
        if hasattr(self, "report_class_combo"):  self._refresh_report_options()
        if hasattr(self, "load_students_to_treeview"): self.load_students_to_treeview()
        if hasattr(self, "load_students_to_management_treeview"): self.load_students_to_management_treeview()
        if hasattr(self, "load_class_names_to_treeview"): self.load_class_names_to_treeview()
        if hasattr(self, "_msg_load_groups"):        self._msg_load_groups()
        if hasattr(self, "populate_schedule_table"):
            if hasattr(self, "schedule_widgets"):
                self._schedule_built_day = None
                self.populate_schedule_table()
        if hasattr(self, "_tard_load"):         self._tard_load()
        if hasattr(self, "_exc_load"):          self._exc_load()
        if hasattr(self, "_users_load"):         self._users_load()
        if hasattr(self, "refresh_analysis_students"): 
            self.refresh_analysis_students()
            if self._current_tab.get() == "تحليل الطالب":
                self._on_analysis_student_selected()
        if hasattr(self, "refresh_leaderboard"):
            self.refresh_leaderboard()


    def _refresh_report_options(self):
        if hasattr(self, "report_class_combo"):
            class_ids = ["(كل الفصول)"] + [c["id"] for c in self.store["list"]]
            self.report_class_combo['values'] = class_ids
            self.report_class_combo.current(0)

    # ─── استيراد البيانات ────────────────────────────────────
    def reimport_students(self):
        path = filedialog.askopenfilename(title="اختر ملف Excel (طلاب)", filetypes=[("Excel files","*.xlsx *.xls")])
        if not path: return
        self._preview_import(path)

    def _preview_import(self, xlsx_path: str):
        import threading as _th
        win = tk.Toplevel(self.root); win.title("معاينة الاستيراد"); win.geometry("860x560")
        loading = ttk.Label(win, text="⏳ جارٍ قراءة الملف...", font=("Tahoma",12)); loading.pack(expand=True)
        def _load():
            try:
                import pandas as pd
                xls = pd.ExcelFile(xlsx_path); REQUIRED = {"رقم الطالب","اسم الطالب","رقم الصف"}; df = None
                for sname in xls.sheet_names:
                    df_try = pd.read_excel(xlsx_path, sheet_name=sname, dtype=str)
                    if REQUIRED <= set(str(c).strip() for c in df_try.columns): df = df_try; break
                if df is None: win.after(0, win.destroy); return
                df.columns = [str(c).strip() for c in df.columns]
                df = df.dropna(subset=["رقم الطالب","اسم الطالب"])
                store = load_students(); current_ids = set(s["id"] for cls in store["list"] for s in cls["students"])
                new_ids = set(str(r["رقم الطالب"]).strip() for _,r in df.iterrows())
                added = new_ids - current_ids; removed = current_ids - new_ids; same = new_ids & current_ids
                win.after(0, lambda: self._show_import_preview(win, loading, df, added, removed, same, store, xlsx_path))
            except Exception as e: win.after(0, win.destroy)
        _th.Thread(target=_load, daemon=True).start()

    def _show_import_preview(self, win, loading, df, added, removed, same, store, xlsx_path):
        loading.destroy()
        hdr = tk.Frame(win, bg="#1565C0", height=46); hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="معاينة الاستيراد", bg="#1565C0", fg="white", font=("Tahoma",11,"bold")).pack(side="right", padx=12, pady=12)
        btns = tk.Frame(win, bg="white"); btns.pack(side="bottom", fill="x", padx=10, pady=8)
        ttk.Button(btns, text="✅ تأكيد الاستيراد", command=lambda: (win.destroy(), self._do_reimport_students(xlsx_path))).pack(side="right", padx=4)
        ttk.Button(btns, text="❌ إلغاء", command=win.destroy).pack(side="right", padx=4)

    def _do_reimport_students(self, path: str, _retry: bool = False):
        try:
            res = import_students_from_excel_sheet2_format(path)

            # لبس في الصفوف؟ نعود بالمستخدم إلى ترميزها يدوياً ثم نستورد
            # من جديد — بدل أن يُترك الرمز المجهول يمرّ بصمت.
            unknown = res.get("_unknown_levels") or {}
            if unknown and not _retry:
                from gui.noor_levels_dialog import resolve_noor_levels
                if resolve_noor_levels(self, unknown):
                    return self._do_reimport_students(path, _retry=True)

            cls = res.get("classes") or []
            cnt = sum(len(c.get("students") or []) for c in cls)
            msg = (f"تم تحديث الطلاب بنجاح.\n\n"
                   f"المرحلة: {res.get('_stage', '')}\n"
                   f"الفصول: {len(cls)}   الطلاب: {cnt}")
            if res.get("_skipped"):
                msg += f"\nالمستبعدون: {res['_skipped']}"
            messagebox.showinfo("تم", msg)

            # النسخة المبنية بلا نافذة أوامر، فتحذيرات الترميز لا تظهر
            # إلا هنا — بدونها يمرّ رمز صف مجهول دون أن يلحظه أحد.
            if res.get("_unknown_levels"):
                from database import noor_import_report
                report = noor_import_report(res)
                if report:
                    messagebox.showwarning("مراجعة ترميز نور", report)
            self.update_all_tabs_after_data_change()
        except Exception as e: messagebox.showerror("خطأ", str(e))

    def reimport_teachers(self):
        path = filedialog.askopenfilename(title="اختر ملف Excel (معلمون)", filetypes=[("Excel files","*.xlsx *.xls")])
        if not path: return
        try:
            import_teachers_from_excel(path)
            messagebox.showinfo("تم", "تم تحديث المعلمين بنجاح.")
            if hasattr(self, "_refresh_links_and_teachers"): self._refresh_links_and_teachers()
        except Exception as e: messagebox.showerror("خطأ", str(e))

    def _open_school_settings_tab(self):
        self._switch_tab("إعدادات المدرسة")

    def open_config_json(self):
        ensure_dirs()
        if not os.path.exists(CONFIG_JSON):
            with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f: content_str = f.read()
        except: return
        win = tk.Toplevel(self.root); win.title("تعديل config.json"); win.geometry("800x600")
        txt = tk.Text(win, font=("Courier New", 10)); txt.pack(fill="both", expand=True)
        txt.insert("1.0", content_str)
        def _save():
            try:
                parsed = json.loads(txt.get("1.0", "end").strip())
                with open(CONFIG_JSON, "w", encoding="utf-8") as f: json.dump(parsed, f, ensure_ascii=False, indent=2)
                invalidate_config_cache(); messagebox.showinfo("تم", "تم الحفظ")
            except Exception as e: messagebox.showerror("خطأ", str(e))
        ttk.Button(win, text="💾 حفظ", command=_save).pack(pady=5)
