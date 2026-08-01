# -*- coding: utf-8 -*-
"""
setup_wizard.py — معالج الإعداد الأولي (يُشغَّل مرة واحدة فقط)

⚠️ هذا الملف مستقل تماماً — لا يستورد constants أو config_manager
   حتى يضمن تشغيله قبل أي استيراد ثقيل في main.py
"""
import os, sys, json, tkinter as tk
from tkinter import ttk, messagebox
import security as _sec        # وحدة مستقلة بلا اعتماديات — آمنة للاستيراد هنا
import provisioning as _prov   # كذلك

# ── مسارات مستقلة (بدون constants) ──────────────────────────────
_BASE_DIR   = (os.path.dirname(sys.executable)
               if getattr(sys, 'frozen', False)
               else os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR   = os.path.join(_BASE_DIR, 'data')
_CONFIG_JSON = os.path.join(_DATA_DIR, 'config.json')
_SETUP_FLAG  = os.path.join(_DATA_DIR, '.setup_done')

# ── المناطق التعليمية ──────────────────────────────────────────
_REGIONS = [
    "الإدارة العامة للتعليم بمنطقة الرياض",
    "الإدارة العامة للتعليم بمنطقة مكة المكرمة",
    "الإدارة العامة للتعليم بمنطقة المدينة المنورة",
    "الإدارة العامة للتعليم بمنطقة الشرقية",
    "الإدارة العامة للتعليم بمنطقة القصيم",
    "الإدارة العامة للتعليم بمنطقة حائل",
    "الإدارة العامة للتعليم بمنطقة تبوك",
    "الإدارة العامة للتعليم بمنطقة الجوف",
    "الإدارة العامة للتعليم بمنطقة الحدود الشمالية",
    "الإدارة العامة للتعليم بمنطقة عسير",
    "الإدارة العامة للتعليم بمنطقة جازان",
    "الإدارة العامة للتعليم بمنطقة نجران",
    "الإدارة العامة للتعليم بمنطقة الباحة",
]


def is_setup_needed() -> bool:
    return not os.path.exists(_SETUP_FLAG)


def _mark_done():
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_SETUP_FLAG, 'w', encoding='utf-8') as f:
        f.write('done')


def _read_config() -> dict:
    """يقرأ config.json مباشرة بدون config_manager."""
    try:
        if os.path.exists(_CONFIG_JSON):
            with open(_CONFIG_JSON, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _write_config(cfg: dict):
    """يكتب config.json مباشرة بدون config_manager."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_CONFIG_JSON, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────
class SetupWizard:
    """نافذة الإعداد الأولي — modal تمنع بقية البرنامج حتى تكتمل."""

    _NAVY  = "#1a3a5c"
    _BLUE  = "#1565C0"
    _LBLUE = "#e8f0fe"
    _WHITE = "#ffffff"
    _GRAY  = "#f0f4f8"
    _RED   = "#c62828"
    _GREEN = "#2e7d32"

    def __init__(self, parent: tk.Tk):
        self.parent    = parent
        self.completed = False
        # يطبّق ملف التجهيز الذي وضعه المزوّد قبل التسليم (إن وُجد)،
        # فيصير النطاق جاهزاً ولا تُسأل المدرسة عنه إطلاقاً.
        try:
            _prov.apply_provision_file()
        except Exception as _e:
            print(f"[SETUP] تعذّر تطبيق ملف التجهيز: {_e}")
        self.provisioned = _prov.is_provisioned()
        self.prov_domain = _prov.get_public_domain()
        self._build()

    # ─────────────────────────────────────────────────────────────
    def _build(self):
        win = tk.Toplevel(self.parent)
        self.win = win
        win.title("إعداد بيانات المدرسة — أول تشغيل")
        win.configure(bg=self._GRAY)
        win.resizable(False, False)
        win.grab_set()
        win.protocol("WM_DELETE_WINDOW", self._on_close)

        W, H = 660, 820
        win.update_idletasks()
        sx, sy = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{W}x{H}+{(sx-W)//2}+{(sy-H)//2}")

        # ── رأس ──────────────────────────────────────────────────
        hdr = tk.Frame(win, bg=self._NAVY, height=100)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🏫  إعداد بيانات مدرستك",
                 bg=self._NAVY, fg=self._WHITE,
                 font=("Tahoma", 18, "bold")).pack(pady=(18, 4))
        tk.Label(hdr,
                 text="أدخل البيانات التالية — تظهر هذه الشاشة مرة واحدة فقط",
                 bg=self._NAVY, fg="#90caf9",
                 font=("Tahoma", 10)).pack()

        # ── منطقة قابلة للتمرير ──────────────────────────────────
        canvas    = tk.Canvas(win, bg=self._GRAY, highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="left", fill="y")
        canvas.pack(fill="both", expand=True)

        body     = tk.Frame(canvas, bg=self._GRAY, padx=40, pady=24)
        body_win = canvas.create_window((0, 0), window=body, anchor="nw")

        def _resize(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(body_win, width=canvas.winfo_width())
        body.bind("<Configure>", _resize)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(body_win, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # ── متغيرات ───────────────────────────────────────────────
        self.v_school   = tk.StringVar()
        self.v_region   = tk.StringVar(value=_REGIONS[0])
        self.v_principal = tk.StringVar()
        self.v_assistant = tk.StringVar()
        self.v_p_phone   = tk.StringVar()
        self.v_gender    = tk.StringVar(value="boys")
        self.v_start     = tk.StringVar(value="07:00")
        self.v_domain    = tk.StringVar()
        self.v_pw        = tk.StringVar()
        self.v_pw2       = tk.StringVar()

        # ── دوال مساعدة ──────────────────────────────────────────
        def section(title):
            tk.Frame(body, bg=self._NAVY, height=2).pack(fill="x", pady=(18, 0))
            tk.Label(body, text=title, bg=self._GRAY, fg=self._NAVY,
                     font=("Tahoma", 11, "bold"), anchor="e").pack(fill="x", pady=(4, 0))

        def field(label, var, required=False, hint="",
                  is_combo=False, options=None, ph=""):
            wrap = tk.Frame(body, bg=self._GRAY, pady=4)
            wrap.pack(fill="x")
            lbl = ("* " if required else "  ") + label
            clr = self._RED if required else "#37474f"
            tk.Label(wrap, text=lbl, bg=self._GRAY, fg=clr,
                     font=("Tahoma", 10, "bold"), anchor="e").pack(fill="x")
            if is_combo and options:
                w = ttk.Combobox(wrap, textvariable=var, values=options,
                                 font=("Tahoma", 10), state="readonly", justify="right")
                w.pack(fill="x", ipady=4)
            else:
                w = tk.Entry(wrap, textvariable=var, font=("Tahoma", 11),
                             relief="solid", bd=1, bg=self._WHITE,
                             justify="right", insertbackground=self._BLUE)
                w.pack(fill="x", ipady=6)
            if hint:
                tk.Label(wrap, text="  "+hint, bg=self._GRAY, fg="#78909c",
                         font=("Tahoma", 8), anchor="e").pack(fill="x")
            return w

        # ── القسم 1: بيانات المدرسة ───────────────────────────────
        section("📋  بيانات المدرسة الأساسية")
        field("اسم المدرسة", self.v_school, required=True,
              hint="الاسم كاملاً كما يظهر في الوثائق الرسمية")
        field("المنطقة التعليمية", self.v_region, required=True,
              is_combo=True, options=_REGIONS,
              hint="اختر المنطقة التي تتبع لها مدرستك")

        # ── القسم 2: الإدارة ─────────────────────────────────────
        section("👤  إدارة المدرسة")
        field("اسم مدير المدرسة", self.v_principal, required=True,
              hint="يظهر في توقيع نماذج المعلمين والتقارير")
        field("اسم وكيل شؤون الطلاب", self.v_assistant,
              hint="اختياري — يُعرض في رسائل الغياب")
        field("جوال مدير المدرسة", self.v_p_phone,
              hint="اختياري — للإشعارات التلقائية  (مثال: 9665XXXXXXXX)")

        # ── القسم 3: حساب المدير ─────────────────────────────────
        section("🔐  حساب الدخول للبرنامج")

        tk.Label(body, text="  اسم المستخدم: admin", bg=self._GRAY, fg="#37474f",
                 font=("Tahoma", 10, "bold"), anchor="e").pack(fill="x", pady=(4, 0))

        for _lbl, _var in [("كلمة مرور المدير", self.v_pw),
                           ("تأكيد كلمة المرور", self.v_pw2)]:
            wrap = tk.Frame(body, bg=self._GRAY, pady=4)
            wrap.pack(fill="x")
            tk.Label(wrap, text="* " + _lbl, bg=self._GRAY, fg=self._RED,
                     font=("Tahoma", 10, "bold"), anchor="e").pack(fill="x")
            tk.Entry(wrap, textvariable=_var, font=("Tahoma", 11), show="●",
                     relief="solid", bd=1, bg=self._WHITE,
                     justify="right", insertbackground=self._BLUE).pack(fill="x", ipady=6)

        note_pw = tk.Frame(body, bg="#ffebee", relief="flat", pady=8, padx=12)
        note_pw.pack(fill="x", pady=(4, 0))
        tk.Label(note_pw,
                 text="🔒  ٨ أحرف على الأقل. هذه الكلمة تحمي بيانات طلاب مدرستك\n"
                      "    على الشبكة والإنترنت — اختر كلمة قوية ولا تشاركها.",
                 bg="#ffebee", fg="#b71c1c",
                 font=("Tahoma", 8), anchor="e", justify="right").pack(fill="x")

        # ── القسم 4: الدوام ──────────────────────────────────────
        section("⏰  إعدادات الدوام")

        gf = tk.Frame(body, bg=self._GRAY, pady=4)
        gf.pack(fill="x")
        tk.Label(gf, text="  جنس المدرسة", bg=self._GRAY, fg="#37474f",
                 font=("Tahoma", 10, "bold"), anchor="e").pack(fill="x")
        gr = tk.Frame(gf, bg=self._GRAY)
        gr.pack(anchor="e")
        for txt, val in [("بنين", "boys"), ("بنات", "girls")]:
            tk.Radiobutton(gr, text=txt, variable=self.v_gender, value=val,
                           bg=self._GRAY, fg=self._NAVY, font=("Tahoma", 11),
                           selectcolor=self._LBLUE,
                           activebackground=self._GRAY).pack(side="right", padx=20)

        sf = tk.Frame(body, bg=self._GRAY, pady=4)
        sf.pack(fill="x")
        tk.Label(sf, text="  وقت بداية الدوام", bg=self._GRAY, fg="#37474f",
                 font=("Tahoma", 10, "bold"), anchor="e").pack(fill="x")
        tk.Entry(sf, textvariable=self.v_start, font=("Tahoma", 12),
                 relief="solid", bd=1, bg=self._WHITE,
                 justify="center", width=10).pack(anchor="e", ipady=5)
        tk.Label(sf, text="  صيغة 24 ساعة  (مثال: 07:16)",
                 bg=self._GRAY, fg="#78909c", font=("Tahoma", 8),
                 anchor="e").pack(fill="x")

        # ── القسم 5: الاتصال الخارجي ──────────────────────────────
        # الجهاز يُجهَّز من المزوّد قبل التسليم، فلا تُسأل المدرسة عن شيء.
        section("🌐  الاتصال الخارجي")

        if self.provisioned:
            ok_f = tk.Frame(body, bg="#e8f5e9", relief="flat", pady=10, padx=12)
            ok_f.pack(fill="x", pady=(4, 0))
            tk.Label(ok_f, text="✅  هذا الجهاز مُجهَّز ومربوط بخوادم DarbStu",
                     bg="#e8f5e9", fg="#1b5e20",
                     font=("Tahoma", 10, "bold"), anchor="e").pack(fill="x")
            tk.Label(ok_f, text=f"     رابط مدرستك:  https://{self.prov_domain}",
                     bg="#e8f5e9", fg="#2e7d32",
                     font=("Tahoma", 9), anchor="e").pack(fill="x", pady=(4, 0))
            tk.Label(ok_f,
                     text="     يعمل تلقائياً — لا يحتاج أي إعداد منك.",
                     bg="#e8f5e9", fg="#558b2f",
                     font=("Tahoma", 8), anchor="e").pack(fill="x")
        else:
            warn_f = tk.Frame(body, bg="#fff8e1", relief="flat", pady=10, padx=12)
            warn_f.pack(fill="x", pady=(4, 0))
            tk.Label(warn_f,
                     text="ℹ️  لم يُجهَّز هذا الجهاز للاتصال الخارجي بعد.\n"
                          "     البرنامج يعمل كاملاً داخل شبكة المدرسة،\n"
                          "     لكن روابط أولياء الأمور من خارجها لن تعمل.\n"
                          "     تواصل مع مزوّد النظام لتفعيلها.",
                     bg="#fff8e1", fg="#e65100",
                     font=("Tahoma", 9), anchor="e", justify="right").pack(fill="x")

        # ── ملاحظة عامة ──────────────────────────────────────────
        note = tk.Frame(body, bg=self._LBLUE, relief="flat", pady=8, padx=14)
        note.pack(fill="x", pady=(14, 4))
        tk.Label(note,
                 text="💡  يمكنك تعديل جميع هذه البيانات لاحقاً من تبويب الإعدادات",
                 bg=self._LBLUE, fg="#0d47a1",
                 font=("Tahoma", 9), anchor="e", justify="right").pack(fill="x")

        # ── زر الحفظ ─────────────────────────────────────────────
        btn_f = tk.Frame(win, bg=self._GRAY, pady=16)
        btn_f.pack(fill="x")
        tk.Button(btn_f,
                  text="  حفظ وبدء البرنامج  ",
                  font=("Tahoma", 13, "bold"),
                  bg=self._GREEN, fg=self._WHITE,
                  relief="flat", cursor="hand2",
                  padx=40, pady=12,
                  activebackground="#1b5e20",
                  command=self._save).pack()

    # ─────────────────────────────────────────────────────────────
    def _save(self):
        school    = self.v_school.get().strip()
        region    = self.v_region.get().strip()
        principal = self.v_principal.get().strip()

        pw        = self.v_pw.get()
        pw2       = self.v_pw2.get()

        errors = []
        if not school:
            errors.append("اسم المدرسة مطلوب")
        if not region:
            errors.append("المنطقة التعليمية مطلوبة")
        if not principal:
            errors.append("اسم مدير المدرسة مطلوب")
        if len(pw) < 8:
            errors.append("كلمة مرور المدير مطلوبة (٨ أحرف على الأقل)")
        elif pw != pw2:
            errors.append("كلمة المرور وتأكيدها غير متطابقين")
        elif pw.lower() in ("admin123", "12345678", "password"):
            errors.append("كلمة المرور ضعيفة جداً — اختر كلمة أخرى")

        if errors:
            messagebox.showwarning("بيانات ناقصة",
                                   "\n".join(f"•  {e}" for e in errors),
                                   parent=self.win)
            return

        # ── حفظ مباشر في config.json (بدون config_manager) ────────
        cfg = _read_config()
        cfg["school_name"]       = school
        cfg["education_region"]  = region
        cfg["principal_name"]    = principal
        cfg["assistant_name"]    = self.v_assistant.get().strip()
        cfg["principal_phone"]   = self.v_p_phone.get().strip()
        cfg["school_gender"]     = self.v_gender.get()
        cfg["school_start_time"] = self.v_start.get().strip() or "07:00"
        # النطاق يأتي من ملف التجهيز الذي أعدّه المزوّد — لا يُلمس هنا.
        # إن لم يُجهَّز الجهاز يبقى فارغاً فيعمل البرنامج محلياً وعلى الشبكة.
        cfg.setdefault("cloudflare_domain", _prov.get_public_domain() or "")
        # توكن الربط السحابي يُولَّد عشوائياً لكل مدرسة عند أول تحميل للإعدادات
        cfg["cloud_token"]       = ""
        _write_config(cfg)

        # تُستهلك عند تهيئة قاعدة البيانات في نفس هذا التشغيل
        _sec.store_initial_admin_password(pw)

        _mark_done()
        self.completed = True
        self.win.destroy()

    # ─────────────────────────────────────────────────────────────
    def _on_close(self):
        if messagebox.askokcancel(
            "تأكيد الخروج",
            "لم تُكمل إعداد البرنامج.\n"
            "هل تريد الخروج؟\n"
            "(يمكنك إعادة التشغيل لإكمال الإعداد لاحقاً)",
            parent=self.win):
            self.win.destroy()
            sys.exit(0)


# ─────────────────────────────────────────────────────────────────
def run_setup_if_needed(root: tk.Tk) -> bool:
    """يعرض المعالج إن لزم. يعيد True إذا اكتمل أو لم يكن ضرورياً."""
    if not is_setup_needed():
        return True
    wizard = SetupWizard(root)
    root.wait_window(wizard.win)
    return wizard.completed
