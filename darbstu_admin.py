# -*- coding: utf-8 -*-
"""
darbstu_admin.py — لوحة تجهيز وإدارة مدارس DarbStu

أداة للمزوّد وحده (لا تُسلَّم للمدارس). تنفّذ خطوات دليل التسليم بصرياً:
  • تجهيز مدرسة جديدة على السيرفر بضغطة واحدة
  • تنزيل ملف التجهيز provision.json وحفظه حيث تريد
  • عرض كل المدارس وحالة اتصال كل واحدة (متصلة / غير متصلة)
  • إيقاف وتفعيل مدرسة (عند تأخر الدفع مثلاً)

تعتمد على إعداد SSH الموجود عندك (~/.ssh/config → backup-server).
لا تحتوي على أي مفاتيح أو أسرار.
"""
import os
import re
import sys
import json
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_TITLE   = "لوحة إدارة مدارس DarbStu"
SSH_HOST    = "backup-server"
DOMAIN      = "darbstu.com"

# ألوان متسقة مع البرنامج الرئيسي
NAVY   = "#1a3a5c"
BLUE   = "#1565C0"
LBLUE  = "#e8f0fe"
WHITE  = "#ffffff"
GRAY   = "#f0f4f8"
RED    = "#c62828"
GREEN  = "#2e7d32"
AMBER  = "#e65100"
MUTED  = "#78909c"

_NO_WINDOW = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else {}


def _find_ssh() -> str:
    import shutil
    for p in (r"C:\Windows\System32\OpenSSH\ssh.exe",
              r"C:\Program Files\Git\usr\bin\ssh.exe"):
        if os.path.isfile(p):
            return p
    return shutil.which("ssh") or "ssh"


SSH = _find_ssh()


def run_remote(command: str, timeout: int = 90):
    """ينفّذ أمراً على السيرفر. يُرجع (نجح, المخرجات)."""
    try:
        r = subprocess.run(
            [SSH, "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
             SSH_HOST, command],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, **_NO_WINDOW)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out.strip()
    except subprocess.TimeoutExpired:
        return False, "انتهت المهلة — تحقق من الاتصال بالإنترنت"
    except Exception as e:
        return False, f"تعذّر تنفيذ الأمر: {e}"


# ══════════════════════════════════════════════════════════════════
#  التطبيق
# ══════════════════════════════════════════════════════════════════
class AdminApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.q = queue.Queue()
        self.provision_text = ""
        self.provision_name = ""
        self._build()
        self.root.after(120, self._pump)
        self._check_connection()

    # ── الواجهة ──────────────────────────────────────────────────
    def _build(self):
        r = self.root
        r.title(APP_TITLE)
        r.configure(bg=GRAY)
        r.update_idletasks()
        sx, sy = r.winfo_screenwidth(), r.winfo_screenheight()
        # الارتفاع يتكيّف مع الشاشة — على شاشة 768 مثلاً لا تخرج النافذة عنها
        W = min(880, sx - 80)
        H = min(860, sy - 90)
        r.geometry(f"{W}x{H}+{max(0,(sx-W)//2)}+{max(0,(sy-H)//2)}")
        r.minsize(720, 520)

        # رأس
        hdr = tk.Frame(r, bg=NAVY, height=62)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🏫  لوحة إدارة مدارس DarbStu", bg=NAVY, fg=WHITE,
                 font=("Tahoma", 14, "bold")).pack(pady=(9, 0))
        self.conn_lbl = tk.Label(hdr, text="جارٍ فحص الاتصال بالسيرفر...",
                                 bg=NAVY, fg="#90caf9", font=("Tahoma", 9))
        self.conn_lbl.pack()

        nb = ttk.Notebook(r)
        nb.pack(fill="both", expand=True, padx=10, pady=(8, 8))
        self.tab_new  = tk.Frame(nb, bg=GRAY)
        self.tab_list = tk.Frame(nb, bg=GRAY)
        self.tab_pub  = tk.Frame(nb, bg=GRAY)
        nb.add(self.tab_new,  text="  تجهيز مدرسة جديدة  ")
        nb.add(self.tab_list, text="  المدارس المسجّلة  ")
        self.tab_keys = tk.Frame(nb, bg=GRAY)
        nb.add(self.tab_pub,  text="  نشر تحديث  ")
        self.tab_vis = tk.Frame(nb, bg=GRAY)
        nb.add(self.tab_keys, text="  🔐 نسخ المفاتيح  ")
        self.tab_frm = tk.Frame(nb, bg=GRAY)
        nb.add(self.tab_frm,  text="  📥 الطلبات  ")
        nb.add(self.tab_vis,  text="  📊 الزوّار  ")
        self._build_new(self.tab_new)
        self._build_list(self.tab_list)
        self._build_publish(self.tab_pub)
        self._build_keys(self.tab_keys)
        self._build_forms(self.tab_frm)
        self._build_visits(self.tab_vis)

    # ── منطقة قابلة للتمرير ──────────────────────────────────────
    def _scrollable(self, parent):
        """
        يُرجع إطاراً داخلياً قابلاً للتمرير.
        ضروري لأن محتوى تبويب التجهيز أطول من النافذة على الشاشات الصغيرة،
        فبدونه تختفي خطوات التنفيذ وزر حفظ ملف التجهيز.
        """
        canvas = tk.Canvas(parent, bg=GRAY, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="left", fill="y")
        canvas.pack(side="right", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=GRAY)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas(e):
            canvas.itemconfig(win, width=e.width)
        inner.bind("<Configure>", _on_inner)
        canvas.bind("<Configure>", _on_canvas)

        # عجلة الفأرة — مربوطة بهذا الكانفس وحده لا بالنافذة كلها
        def _wheel(e):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return inner

    # ── تبويب التجهيز ────────────────────────────────────────────
    def _build_new(self, parent):
        holder = self._scrollable(parent)
        body = tk.Frame(holder, bg=GRAY, padx=28, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="بيانات المدرسة", bg=GRAY, fg=NAVY,
                 font=("Tahoma", 12, "bold"), anchor="e").pack(fill="x")
        tk.Frame(body, bg=NAVY, height=2).pack(fill="x", pady=(2, 8))

        self.v_id   = tk.StringVar()
        self.v_sub  = tk.StringVar()
        self.v_name = tk.StringVar()

        def field(label, var, hint):
            f = tk.Frame(body, bg=GRAY, pady=2)
            f.pack(fill="x")
            tk.Label(f, text=label, bg=GRAY, fg="#37474f",
                     font=("Tahoma", 10, "bold"), anchor="e").pack(fill="x")
            e = tk.Entry(f, textvariable=var, font=("Consolas", 12),
                         relief="solid", bd=1, bg=WHITE, justify="left")
            e.pack(fill="x", ipady=6)
            tk.Label(f, text=hint, bg=GRAY, fg=MUTED,
                     font=("Tahoma", 8), anchor="e").pack(fill="x")
            return e

        e1 = field("* معرّف المدرسة",  self.v_id,
                   "حروف إنجليزية صغيرة وأرقام وشرطات فقط — مثال: alnoor")
        field("النطاق الفرعي", self.v_sub,
              "اتركه فارغاً ليكون نفس المعرّف")
        field("اسم المدرسة بالعربي", self.v_name,
              "اختياري — للعرض في هذه اللوحة فقط")
        e1.focus_set()

        # معاينة الرابط
        self.preview = tk.Label(body, text="", bg=LBLUE, fg="#0d47a1",
                                font=("Consolas", 11, "bold"), pady=8)
        self.preview.pack(fill="x", pady=(6, 2))
        self.v_id.trace_add("write", self._update_preview)
        self.v_sub.trace_add("write", self._update_preview)
        self._update_preview()

        self.btn = tk.Button(body, text="  ⚡  جهّز المدرسة الآن  ",
                             font=("Tahoma", 12, "bold"), bg=GREEN, fg=WHITE,
                             relief="flat", cursor="hand2", pady=10,
                             activebackground="#1b5e20", command=self._start)
        self.btn.pack(pady=(8, 10))

        # خطوات التنفيذ
        tk.Label(body, text="خطوات التنفيذ", bg=GRAY, fg=NAVY,
                 font=("Tahoma", 11, "bold"), anchor="e").pack(fill="x")
        tk.Frame(body, bg=NAVY, height=2).pack(fill="x", pady=(2, 8))

        steps_f = tk.Frame(body, bg=WHITE, relief="solid", bd=1)
        steps_f.pack(fill="x")
        self.step_lbls = []
        for txt in ("الاتصال بالسيرفر",
                    "إنشاء المدرسة وتوليد مفتاحها",
                    "تحديث توجيه nginx",
                    "تنزيل ملف التجهيز"):
            l = tk.Label(steps_f, text=f"   ○   {txt}", bg=WHITE, fg=MUTED,
                         font=("Tahoma", 10), anchor="e", pady=4)
            l.pack(fill="x", padx=10)
            self.step_lbls.append((l, txt))

        self.result = tk.Label(body, text="", bg=GRAY, fg=NAVY,
                               font=("Tahoma", 10), anchor="e",
                               justify="right", wraplength=760)
        self.result.pack(fill="x", pady=(10, 6))

        self.save_btn = tk.Button(body, text="  💾  حفظ ملف التجهيز  ",
                                  font=("Tahoma", 11, "bold"), bg=BLUE, fg=WHITE,
                                  relief="flat", cursor="hand2", pady=8,
                                  state="disabled", command=self._save_provision)
        self.save_btn.pack(pady=(0, 14))

    def _update_preview(self, *_):
        sid = self.v_id.get().strip().lower()
        sub = (self.v_sub.get().strip() or sid).lower()
        self.preview.config(
            text=f"https://{sub}.{DOMAIN}" if sub else "أدخل معرّف المدرسة")

    # ── تبويب المدارس ────────────────────────────────────────────
    def _build_list(self, parent):
        body = tk.Frame(parent, bg=GRAY, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        top = tk.Frame(body, bg=GRAY)
        top.pack(fill="x", pady=(0, 10))
        tk.Button(top, text="  🔄  تحديث  ", font=("Tahoma", 10, "bold"),
                  bg=BLUE, fg=WHITE, relief="flat", cursor="hand2", pady=6,
                  command=self._refresh_list).pack(side="right")
        self.list_status = tk.Label(top, text="", bg=GRAY, fg=MUTED,
                                    font=("Tahoma", 9), anchor="e")
        self.list_status.pack(side="right", padx=12)

        cols = ("id", "domain", "license", "state", "online")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=14)
        for c, t, w in (("id", "المعرّف", 120), ("domain", "الرابط", 230),
                        ("license", "الاشتراك", 170), ("state", "الحالة", 90),
                        ("online", "الاتصال", 110)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure("online",  foreground=GREEN)
        self.tree.tag_configure("offline", foreground=MUTED)
        self.tree.tag_configure("paused",  foreground=RED)
        self.tree.tag_configure("expiring", foreground=AMBER)

        btns = tk.Frame(body, bg=GRAY, pady=10)
        btns.pack(fill="x")
        tk.Button(btns, text="  ✅  تفعيل / تجديد سنة  ", font=("Tahoma", 11, "bold"),
                  bg=GREEN, fg=WHITE, relief="flat", cursor="hand2", pady=7,
                  command=lambda: self._license("activate", 12)).pack(side="right", padx=4)
        tk.Button(btns, text="  ⛔  إلغاء الاشتراك  ", font=("Tahoma", 10, "bold"),
                  bg=RED, fg=WHITE, relief="flat", cursor="hand2", pady=7,
                  command=lambda: self._license("revoke", 0)).pack(side="right", padx=4)
        tk.Frame(btns, bg=GRAY, width=18).pack(side="right")
        tk.Button(btns, text="  ⏸  إيقاف مؤقت  ", font=("Tahoma", 10),
                  bg="#78909c", fg=WHITE, relief="flat", cursor="hand2", pady=7,
                  command=lambda: self._toggle("off")).pack(side="right", padx=4)
        tk.Button(btns, text="  ▶  إعادة تشغيل  ", font=("Tahoma", 10),
                  bg="#455a64", fg=WHITE, relief="flat", cursor="hand2", pady=7,
                  command=lambda: self._toggle("on")).pack(side="right", padx=4)

        tk.Label(body,
                 text="«تفعيل / تجديد سنة» يمنح المدرسة اشتراك سنة — والتجديد يُضاف إلى\n"
                      "ما تبقّى لا يُلغيه. البرنامج يتوقف تلقائياً عند انتهاء المدة.\n"
                      "«إيقاف مؤقت» يُعطّل الرابط فوراً دون المساس بمدة الاشتراك.",
                 bg=GRAY, fg=MUTED, font=("Tahoma", 8),
                 anchor="e", justify="right").pack(fill="x")

    # ── منطق التجهيز ─────────────────────────────────────────────
    def _set_step(self, i, state, extra=""):
        marks = {"run": ("   ⏳  ", BLUE), "ok": ("   ✅  ", GREEN),
                 "err": ("   ❌  ", RED), "idle": ("   ○   ", MUTED)}
        m, c = marks[state]
        lbl, txt = self.step_lbls[i]
        lbl.config(text=f"{m}{txt}{extra}", fg=c)

    def _start(self):
        sid = self.v_id.get().strip().lower()
        sub = (self.v_sub.get().strip() or sid).lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}", sid):
            messagebox.showwarning("معرّف غير صالح",
                                   "المعرّف: حروف إنجليزية صغيرة وأرقام وشرطات،\n"
                                   "ويبدأ بحرف أو رقم (٢–٣١ خانة).", parent=self.root)
            return
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}", sub):
            messagebox.showwarning("نطاق غير صالح",
                                   "النطاق الفرعي بنفس قواعد المعرّف.", parent=self.root)
            return

        self.btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.result.config(text="")
        self.provision_text = ""
        for i in range(len(self.step_lbls)):
            self._set_step(i, "idle")
        threading.Thread(target=self._worker, args=(sid, sub), daemon=True).start()

    def _worker(self, sid, sub):
        p = self.q.put
        p(("step", 0, "run", ""))
        ok, out = run_remote("echo READY", timeout=40)
        if not ok or "READY" not in out:
            p(("step", 0, "err", ""))
            p(("fail", f"تعذّر الاتصال بالسيرفر:\n{out}"))
            return
        p(("step", 0, "ok", ""))

        p(("step", 1, "run", ""))
        ok, out = run_remote(f"darbstu-add-school {sid} {sub}", timeout=120)
        if not ok:
            p(("step", 1, "err", ""))
            p(("fail", f"فشل إنشاء المدرسة:\n{out}"))
            return
        if "مستخدم من" in out:
            p(("step", 1, "err", ""))
            p(("fail", out))
            return
        p(("step", 1, "ok", ""))
        p(("step", 2, "ok", ""))   # الأداة تحدّث nginx بنفسها

        port = ""
        m = re.search(r"المنفذ الداخلي\s*:\s*(\d+)", out)
        if m:
            port = m.group(1)

        p(("step", 3, "run", ""))
        ok, js = run_remote(f"cat /root/provision-{sid}.json", timeout=60)
        if not ok or not js.lstrip().startswith("{"):
            p(("step", 3, "err", ""))
            p(("fail", f"تعذّر تنزيل ملف التجهيز:\n{js}"))
            return
        try:
            json.loads(js)
        except Exception as e:
            p(("step", 3, "err", ""))
            p(("fail", f"ملف التجهيز غير صالح: {e}"))
            return
        p(("step", 3, "ok", ""))
        p(("done", sid, sub, port, js))

    # ── تبويب الطلبات ────────────────────────────────────────────
    def _build_forms(self, parent):
        """ما يصل من نموذجَي الموقع: طلب تجربة، وبيانات تجهيز مدرسة."""
        body = tk.Frame(parent, bg=GRAY, padx=22, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="📥  الطلبات الواردة من الموقع", bg=GRAY,
                 fg=NAVY, font=("Tahoma", 13, "bold")).pack(anchor="e")
        tk.Label(body, bg=GRAY, fg=MUTED, font=("Tahoma", 9), justify="right",
                 anchor="e", wraplength=680,
                 text=("طلبات التجربة من darbstu.com، وبيانات التجهيز من "
                       "darbstu.com/join/ التي ترسلها للعميل بعد الاتفاق.")
                 ).pack(anchor="e", pady=(2, 10))

        row = tk.Frame(body, bg=GRAY)
        row.pack(fill="x", pady=(4, 8))
        for lbl, arg in (("الكل", ""), ("طلبات التجربة", "lead"),
                         ("بيانات التجهيز", "onboard")):
            tk.Button(row, text=lbl, bg=BLUE, fg=WHITE, relief="flat",
                      font=("Tahoma", 10, "bold"), cursor="hand2",
                      padx=16, pady=6,
                      command=lambda a=arg: self._forms_load(a)
                      ).pack(side="right", padx=(0, 8))
        tk.Button(row, text="🔗 نسخ رابط التجهيز", bg=LBLUE, fg=NAVY,
                  relief="flat", font=("Tahoma", 9), cursor="hand2",
                  padx=10, pady=6, command=self._copy_join_link).pack(side="left")

        self._frm_out = tk.Text(body, font=("Consolas", 9), bg="#0f1720",
                                fg="#d6e2ee", wrap="word", relief="flat",
                                state="disabled")
        self._frm_out.pack(fill="both", expand=True)
        self._frm_log("اضغط لعرض الطلبات.\n")

    def _copy_join_link(self):
        url = f"https://{DOMAIN}/join/"
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        messagebox.showinfo(
            "نُسخ الرابط",
            f"{url}\n\nأرسله للعميل بعد الاتفاق ليعبّئ بيانات مدرسته.")

    def _frm_log(self, txt, clear=True):
        self._frm_out.config(state="normal")
        if clear:
            self._frm_out.delete("1.0", "end")
        self._frm_out.insert("end", txt)
        self._frm_out.config(state="disabled")

    def _forms_load(self, kind):
        self._frm_log("⏳ جارٍ الجلب...\n")

        def _w():
            ok, out = run_remote(f"darbstu-forms {kind}".strip(), timeout=60)
            self.q.put(("frm", ok, out or "لا طلبات بعد."))

        threading.Thread(target=_w, daemon=True).start()

    # ── تبويب الزوّار ────────────────────────────────────────────
    def _build_visits(self, parent):
        """
        قياس اهتمام المدارس بصفحة العرض.

        لا عدّاد مرئي على الصفحة عمداً: رقم صغير يراه مدير مدرسة يقرأ
        كدليل على أن لا أحد يثق بالنظام. القياس هنا، لك وحدك.
        """
        body = tk.Frame(parent, bg=GRAY, padx=22, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="📊  اهتمام المدارس بصفحة darbstu.com", bg=GRAY,
                 fg=NAVY, font=("Tahoma", 13, "bold")).pack(anchor="e")
        tk.Label(body, bg=GRAY, fg=MUTED, font=("Tahoma", 9), justify="right",
                 wraplength=680, anchor="e",
                 text=("ثلاث إشارات مرتّبة بقوتها: نقرة واتساب (ترك الصفحة "
                       "ليكلّمك) ← قراءة الدليل ← فتح الصفحة.\n"
                       "يُقرأ من سجل الخادم مباشرة — بلا كوكيز ولا تتبّع "
                       "خارجي على زوّارك.")
                 ).pack(anchor="e", pady=(2, 10))

        row = tk.Frame(body, bg=GRAY)
        row.pack(fill="x", pady=(4, 8))
        for lbl, days in (("اليوم", 1), ("٧ أيام", 7), ("٣٠ يوماً", 30),
                          ("٩٠ يوماً", 90)):
            tk.Button(row, text=lbl, bg=BLUE, fg=WHITE, relief="flat",
                      font=("Tahoma", 10, "bold"), cursor="hand2",
                      padx=16, pady=6,
                      command=lambda d=days: self._visits_load(d)
                      ).pack(side="right", padx=(0, 8))

        self._vis_out = tk.Text(body, font=("Consolas", 9), bg="#0f1720",
                                fg="#d6e2ee", wrap="word", relief="flat",
                                state="disabled")
        self._vis_out.pack(fill="both", expand=True)
        self._vis_log("اضغط مدة لعرض التقرير.\n")

    def _vis_log(self, txt, clear=True):
        self._vis_out.config(state="normal")
        if clear:
            self._vis_out.delete("1.0", "end")
        self._vis_out.insert("end", txt)
        self._vis_out.config(state="disabled")

    def _visits_load(self, days):
        self._vis_log(f"⏳ جارٍ قراءة آخر {days} يوماً...\n")

        def _w():
            ok, out = run_remote(f"darbstu-visits {days}", timeout=60)
            self.q.put(("vis", ok, out or "لا بيانات بعد."))

        threading.Thread(target=_w, daemon=True).start()

    # ── تبويب نسخ المفاتيح ───────────────────────────────────────
    def _build_keys(self, parent):
        """
        نسخ احتياطي مشفَّر لمفتاحَي الخادم.

        ضياع مفتاح التحديث يقطع القناة عن كل المدارس بلا إصلاح عن بُعد،
        وضياع مفتاح التراخيص يوقفها عند انتهاء اشتراكاتها. والمفتاحان
        اليوم في ملفين على خادم واحد بلا نسخة.
        """
        body = tk.Frame(parent, bg=GRAY, padx=22, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="🔐  نسخة احتياطية من مفاتيح الخادم", bg=GRAY,
                 fg=NAVY, font=("Tahoma", 13, "bold")).pack(anchor="e")
        tk.Label(body, bg=GRAY, fg=MUTED, font=("Tahoma", 9), justify="right",
                 wraplength=680, anchor="e",
                 text=("المفتاحان على خادم واحد. ضياعهما لا يُصلَح عن بُعد:\n"
                       "• مفتاح التحديث — تنقطع التحديثات عن كل المدارس نهائياً\n"
                       "• مفتاح التراخيص — تتوقف المدارس عند انتهاء اشتراكاتها\n"
                       "⚠️ النسخة تُشفَّر بكلمة سرّ إلزامية — احفظها فمن يملك "
                       "الملف وكلمتها يوقّع تحديثاً تقبله كل المدارس.")
                 ).pack(anchor="e", pady=(2, 10))

        row = tk.Frame(body, bg=GRAY)
        row.pack(fill="x", pady=(4, 8))
        tk.Button(row, text="💾  أخذ نسخة احتياطية", bg=GREEN, fg=WHITE,
                  relief="flat", font=("Tahoma", 10, "bold"), cursor="hand2",
                  padx=16, pady=7, command=self._keys_backup).pack(side="right",
                                                                   padx=(0, 8))
        tk.Button(row, text="🔍  فحص نسخة موجودة", bg=BLUE, fg=WHITE,
                  relief="flat", font=("Tahoma", 10, "bold"), cursor="hand2",
                  padx=16, pady=7, command=self._keys_verify).pack(side="right")
        tk.Button(row, text="استرجاع إلى الخادم", bg=LBLUE, fg=RED,
                  relief="flat", font=("Tahoma", 9), cursor="hand2",
                  padx=10, pady=6, command=self._keys_restore).pack(side="left")

        self._keys_out = tk.Text(body, height=16, font=("Consolas", 9),
                                 bg="#0f1720", fg="#d6e2ee", wrap="word",
                                 relief="flat", state="disabled")
        self._keys_out.pack(fill="both", expand=True)

    def _keys_log(self, txt, clear=False):
        self._keys_out.config(state="normal")
        if clear:
            self._keys_out.delete("1.0", "end")
        self._keys_out.insert("end", txt)
        self._keys_out.see("end")
        self._keys_out.config(state="disabled")

    def _ask_pass(self, confirm=False) -> str:
        from tkinter import simpledialog
        p1 = simpledialog.askstring("كلمة سرّ النسخة",
                                    "أدخل كلمة سرّ (٨ أحرف فأكثر):",
                                    show="*", parent=self.root)
        if not p1:
            return ""
        if confirm:
            p2 = simpledialog.askstring("تأكيد", "أعد كتابة كلمة السرّ:",
                                        show="*", parent=self.root)
            if p1 != p2:
                messagebox.showerror("غير متطابقة", "كلمتا السرّ مختلفتان.")
                return ""
        return p1

    def _keys_backup(self):
        pw = self._ask_pass(confirm=True)
        if not pw:
            return
        dest = filedialog.asksaveasfilename(
            title="احفظ النسخة", defaultextension=".dsbak",
            initialfile="darbstu_keys.dsbak",
            filetypes=[("نسخة مفاتيح DarbStu", "*.dsbak")])
        if not dest:
            return
        self._keys_log("⏳ جارٍ الجلب من الخادم والتشفير...\n", clear=True)

        def _w():
            try:
                import key_backup as kb
                rep = kb.backup(dest, pw, SSH_HOST)
                lines = [f"✅ حُفظت النسخة\n   {rep['path']}\n",
                         f"   التاريخ: {rep['created']}\n\n",
                         "المفاتيح العامة (للتأكد أنها نسختك):\n"]
                for n, p in rep["publics"].items():
                    lines.append(f"   {n}\n     {p}\n")
                lines.append("\n✅ فُكَّت النسخة وتحقّقت فوراً — صالحة.\n"
                             if rep["verified"] else "\n⚠️ تعذّر التحقق.\n")
                lines.append("\n⚠️ احفظ الملف وكلمة السرّ في مكانين مختلفين، "
                             "خارج هذا الجهاز.\n")
                self.q.put(("keys", True, "".join(lines)))
            except Exception as e:
                self.q.put(("keys", False, f"⛔ فشل: {e}\n"))

        threading.Thread(target=_w, daemon=True).start()

    def _keys_verify(self):
        path = filedialog.askopenfilename(title="اختر نسخة",
                                          filetypes=[("نسخة مفاتيح", "*.dsbak"),
                                                     ("كل الملفات", "*.*")])
        if not path:
            return
        pw = self._ask_pass()
        if not pw:
            return
        self._keys_log("⏳ جارٍ الفحص...\n", clear=True)

        def _w():
            try:
                import key_backup as kb
                r = kb.verify(path, pw)
                out = [f"{'✅ النسخة سليمة' if r['ok'] else '⛔ النسخة تالفة'}\n",
                       f"   تاريخها: {r.get('created')}\n\n"]
                for n, d in r["keys"].items():
                    out.append(f"   {'✅' if d['matches'] else '❌'} {n}"
                               f"  ({d['size']} بايت)\n     {d['public']}\n")
                self.q.put(("keys", r["ok"], "".join(out)))
            except Exception as e:
                self.q.put(("keys", False, f"⛔ {e}\n"))

        threading.Thread(target=_w, daemon=True).start()

    def _keys_restore(self):
        if not messagebox.askyesno(
                "استرجاع المفاتيح",
                "سيُستبدل المفتاحان على الخادم بما في النسخة.\n\n"
                "لا تفعل هذا إلا إذا ضاعت المفاتيح الأصلية أو تلفت.\n\n"
                "المتابعة؟", icon="warning", default="no"):
            return
        path = filedialog.askopenfilename(title="اختر النسخة",
                                          filetypes=[("نسخة مفاتيح", "*.dsbak")])
        if not path:
            return
        pw = self._ask_pass()
        if not pw:
            return
        self._keys_log("⏳ جارٍ الاسترجاع...\n", clear=True)

        def _w():
            try:
                import key_backup as kb
                r = kb.restore(path, pw, SSH_HOST)
                self.q.put(("keys", True,
                            "✅ استُرجع: " + "، ".join(r["restored"]) +
                            "\n\nأعد تشغيل خدمة التراخيص إن لزم:\n"
                            "   systemctl restart darbstu-license\n"))
            except Exception as e:
                self.q.put(("keys", False, f"⛔ فشل الاسترجاع: {e}\n"))

        threading.Thread(target=_w, daemon=True).start()

    # ── تبويب نشر التحديث ────────────────────────────────────────
    def _build_publish(self, parent):
        """
        نشر تحديث للمدارس.

        خطوتان إلزاميتان: فحص أولاً ثم نشر. النشر يصل إلى **كل** المدارس
        تلقائياً، فزرٌّ واحد بلا فحص خطأ فيه يُصيبها جميعاً دفعة واحدة.
        """
        body = tk.Frame(parent, bg=GRAY, padx=22, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="📤  نشر تحديث لكل المدارس", bg=GRAY, fg=NAVY,
                 font=("Tahoma", 13, "bold")).pack(anchor="e")
        tk.Label(body, bg=GRAY, fg=MUTED, font=("Tahoma", 9), justify="right",
                 wraplength=680, anchor="e",
                 text=("يرفع المصدر إلى GitHub، ويبني الحزمة ويوقّعها على خادمك، "
                       "ثم يتحقق منها من الإنترنت كما تفعل المدرسة.\n"
                       "⚠️ ما يُنشر يصل تلقائياً إلى كل المدارس المثبَّتة.")
                 ).pack(anchor="e", pady=(2, 10))

        self._pub_script = _find_publish_script()
        path_txt = self._pub_script or "⚠️ لم يُعثر على publish_update.py"
        self._pub_path_lbl = tk.Label(body, text=path_txt, bg=GRAY,
                                      fg=(MUTED if self._pub_script else RED),
                                      font=("Consolas", 8), anchor="e")
        self._pub_path_lbl.pack(anchor="e", fill="x")

        row = tk.Frame(body, bg=GRAY)
        row.pack(fill="x", pady=(10, 8))
        self._pub_check_btn = tk.Button(
            row, text="①  فحص قبل النشر", bg=BLUE, fg=WHITE, relief="flat",
            font=("Tahoma", 10, "bold"), cursor="hand2", padx=16, pady=7,
            command=lambda: self._pub_run(False))
        self._pub_check_btn.pack(side="right", padx=(0, 8))
        self._pub_send_btn = tk.Button(
            row, text="②  نشر للمدارس", bg="#9e9e9e", fg=WHITE, relief="flat",
            font=("Tahoma", 10, "bold"), cursor="hand2", padx=16, pady=7,
            state="disabled", command=lambda: self._pub_run(True))
        self._pub_send_btn.pack(side="right")
        tk.Button(row, text="اختيار الملف يدوياً", bg=LBLUE, fg=NAVY,
                  relief="flat", font=("Tahoma", 9), cursor="hand2",
                  padx=10, pady=6, command=self._pub_browse).pack(side="left")

        self._pub_out = tk.Text(body, height=18, font=("Consolas", 9),
                                bg="#0f1720", fg="#d6e2ee", wrap="word",
                                relief="flat", state="disabled")
        self._pub_out.pack(fill="both", expand=True)

    def _pub_browse(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title="اختر publish_update.py",
                                       filetypes=[("Python", "*.py")])
        if p:
            self._pub_script = p
            self._pub_path_lbl.config(text=p, fg=MUTED)

    def _pub_log(self, txt, clear=False):
        self._pub_out.config(state="normal")
        if clear:
            self._pub_out.delete("1.0", "end")
        self._pub_out.insert("end", txt)
        self._pub_out.see("end")
        self._pub_out.config(state="disabled")

    def _pub_run(self, confirm: bool):
        if not self._pub_script or not os.path.isfile(self._pub_script):
            messagebox.showerror("غير موجود",
                                 "لم يُعثر على publish_update.py — اختره يدوياً.")
            return
        if confirm:
            if not messagebox.askyesno(
                    "تأكيد النشر",
                    "سيصل هذا التحديث إلى كل المدارس المثبَّتة تلقائياً.\n\n"
                    "هل راجعت نتيجة الفحص؟ هل الإصدار صحيح؟\n\nالمتابعة؟",
                    icon="warning", default="no"):
                return

        self._pub_check_btn.config(state="disabled")
        self._pub_send_btn.config(state="disabled")
        self._pub_log("", clear=True)
        self._pub_log(("⏳ جارٍ النشر...\n\n" if confirm
                       else "⏳ جارٍ الفحص...\n\n"))

        def _worker():
            args = [_find_python(), self._pub_script]
            if confirm:
                args.append("--confirm")
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            try:
                pr = subprocess.Popen(
                    args, cwd=os.path.dirname(self._pub_script),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                    errors="replace", env=env, **_NO_WINDOW)
                # السكربت يطلب كلمة تأكيد على stdin — نمرّرها بعد أن
                # أكّد المستخدم في النافذة أعلاه
                out, _ = pr.communicate(input="PUBLISH\n" if confirm else "\n",
                                        timeout=900)
                self.q.put(("pub", pr.returncode == 0, out or "", confirm))
            except subprocess.TimeoutExpired:
                self.q.put(("pub", False, "انتهت المهلة (١٥ دقيقة).", confirm))
            except Exception as e:
                self.q.put(("pub", False, f"تعذّر التشغيل: {e}", confirm))

        threading.Thread(target=_worker, daemon=True).start()

    def _pump(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "frm":
                    self._frm_log(msg[2] if msg[1] else "⛔ " + msg[2])
                elif kind == "vis":
                    self._vis_log(msg[2] if msg[1] else "⛔ " + msg[2])
                elif kind == "keys":
                    self._keys_log(msg[2])
                elif kind == "pub":
                    # الوضع يأتي صريحاً لا مستنتَجاً من النص: مخرجات
                    # الفحص تحوي «--confirm» في سطر الإرشاد، فاستنتاجه
                    # منها كان يفتح زر النشر بعد النشر ويقفله بعد الفحص.
                    _, ok, out, was_publish = msg
                    self._pub_log(out + "\n")
                    self._pub_check_btn.config(state="normal")
                    if not ok:
                        self._pub_send_btn.config(state="disabled", bg="#9e9e9e")
                        self._pub_log("\n⛔ لم يكتمل — راجع ما سبق.\n")
                    elif was_publish:
                        self._pub_send_btn.config(state="disabled", bg="#9e9e9e")
                        self._pub_log("\n✅ اكتمل النشر ووصل الخادم.\n")
                    else:
                        self._pub_send_btn.config(state="normal", bg=AMBER)
                        self._pub_log("\n✅ الفحص نجح — راجعه ثم اضغط «نشر للمدارس».\n")
                elif kind == "step":
                    self._set_step(msg[1], msg[2], msg[3])
                elif kind == "fail":
                    self.result.config(text="⛔  " + msg[1], fg=RED)
                    self.btn.config(state="normal")
                elif kind == "done":
                    _, sid, sub, port, js = msg
                    self.provision_text = js
                    self.provision_name = f"provision.json"
                    self.result.config(
                        fg=GREEN,
                        text=(f"✅  جُهِّزت المدرسة «{sid}» بنجاح\n"
                              f"الرابط:  https://{sub}.{DOMAIN}"
                              + (f"     المنفذ: {port}" if port else "") +
                              "\n\nاحفظ ملف التجهيز الآن وضعه بجانب DarbStu.exe "
                              "على جهاز المدرسة قبل أول تشغيل."))
                    self.save_btn.config(state="normal")
                    self.btn.config(state="normal")
                    self._refresh_list()
                elif kind == "conn":
                    ok, txt = msg[1], msg[2]
                    self.conn_lbl.config(text=txt, fg="#a5d6a7" if ok else "#ffab91")
                elif kind == "list":
                    self._fill_list(msg[1], msg[2])
                elif kind == "info":
                    messagebox.showinfo("تم", msg[1], parent=self.root)
        except queue.Empty:
            pass
        self.root.after(120, self._pump)

    def _save_provision(self):
        if not self.provision_text:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="حفظ ملف التجهيز",
            defaultextension=".json", initialfile="provision.json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.provision_text)
            messagebox.showinfo(
                "حُفظ الملف",
                f"حُفظ في:\n{path}\n\n"
                "⚠️ يحوي المفتاح الخاص للمدرسة.\n"
                "ضعه بجانب DarbStu.exe ثم احذف هذه النسخة بعد التسليم.",
                parent=self.root)
        except Exception as e:
            messagebox.showerror("خطأ", f"تعذّر الحفظ:\n{e}", parent=self.root)

    # ── قائمة المدارس ────────────────────────────────────────────
    def _check_connection(self):
        def w():
            ok, out = run_remote("hostname", timeout=40)
            self.q.put(("conn", ok,
                        f"✅ متصل بالسيرفر ({out})" if ok
                        else "❌ لا اتصال بالسيرفر — تحقق من الإنترنت"))
            if ok:
                self._load_list()
        threading.Thread(target=w, daemon=True).start()

    def _refresh_list(self):
        self.list_status.config(text="جارٍ التحديث...")
        threading.Thread(target=self._load_list, daemon=True).start()

    def _load_list(self):
        ok, out = run_remote("darbstu-status", timeout=60)
        if not ok:
            self.q.put(("list", [], f"تعذّر جلب القائمة: {out[:80]}"))
            return
        try:
            data = json.loads(out)
        except Exception:
            data = []
        self.q.put(("list", data, ""))

    def _fill_list(self, rows, err):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for s in rows:
            days = s.get("days_left")
            exp  = s.get("expiry", "")
            if not exp:
                lic, tag = "بلا اشتراك", "paused"
            elif days is not None and days < 0:
                lic, tag = f"منتهٍ منذ {-days} يوم", "paused"
            elif days is not None and days <= 30:
                lic, tag = f"ينتهي بعد {days} يوم", "expiring"
            else:
                lic, tag = f"صالح {days} يوم", "online"

            if not s.get("active", True):
                state = "موقوف"; tag = "paused"
            else:
                state = "مفعّل"
                if tag == "online" and not s.get("online"):
                    tag = "offline"

            self.tree.insert("", "end", values=(
                s.get("id", ""), s.get("domain", ""), lic, state,
                "🟢 متصلة" if s.get("online") else "⚪ غير متصلة"), tags=(tag,))
        self.list_status.config(
            text=err or (f"{len(rows)} مدرسة" if rows else "لا مدارس مسجّلة بعد"))

    def _selected_school(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("اختر مدرسة",
                                "اختر مدرسة من القائمة أولاً.", parent=self.root)
            return None
        return self.tree.item(sel[0])["values"][0]

    def _license(self, action, months):
        """تفعيل/تجديد أو إلغاء اشتراك المدرسة المحددة."""
        sid = self._selected_school()
        if not sid:
            return

        if action == "activate":
            msg = (f"تفعيل اشتراك «{sid}» لمدة سنة؟\n\n"
                   "إن كان لديها اشتراك سارٍ فستُضاف السنة إلى ما تبقّى.")
            title = "تأكيد التفعيل"
        else:
            msg = (f"إلغاء اشتراك «{sid}»؟\n\n"
                   "سيتوقف البرنامج عندها فوراً حتى تجدّد.\n"
                   "بياناتها لا تُحذف.")
            title = "تأكيد الإلغاء"

        if not messagebox.askyesno(title, msg, parent=self.root):
            return

        cmd = (f"darbstu-license activate {sid} {months}" if action == "activate"
               else f"darbstu-license revoke {sid}")

        def w():
            ok, out = run_remote(cmd, timeout=60)
            self.q.put(("info", out.strip() if ok else f"فشل: {out}"))
            self._load_list()
        threading.Thread(target=w, daemon=True).start()

    def _toggle(self, state):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("اختر مدرسة",
                                "اختر مدرسة من القائمة أولاً.", parent=self.root)
            return
        sid = self.tree.item(sel[0])["values"][0]
        word = "تفعيل" if state == "on" else "إيقاف"
        if not messagebox.askyesno(f"تأكيد {word}",
                                   f"هل تريد {word} اشتراك المدرسة «{sid}»؟",
                                   parent=self.root):
            return

        def w():
            ok, out = run_remote(f"darbstu-toggle-school {sid} {state}", timeout=60)
            self.q.put(("info", out if ok else f"فشل: {out}"))
            self._load_list()
        threading.Thread(target=w, daemon=True).start()


def _find_python() -> str:
    """مسار بايثون. `sys.executable` هو الـ EXE نفسه في النسخة المجمّدة."""
    import shutil
    if not getattr(sys, "frozen", False):
        return sys.executable
    for c in (shutil.which("python"), shutil.which("py"),
              r"C:\Users\%s\AppData\Local\Programs\Python\Python311\python.exe"
              % os.environ.get("USERNAME", "")):
        if c and os.path.isfile(c):
            return c
    return "python"


def _find_publish_script() -> str:
    """يبحث عن publish_update.py في المواضع المعتادة."""
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    home = os.path.expanduser("~")
    for c in (os.path.join(here, "publish_update.py"),
              os.path.join(here, "..", "publish_update.py"),
              os.path.join(home, "Desktop", "DarbStu_Dist", "publish_update.py")):
        c = os.path.abspath(c)
        if os.path.isfile(c):
            return c
    return ""


def main():
    root = tk.Tk()
    try:
        ico = os.path.join(
            os.path.dirname(sys.executable if getattr(sys, 'frozen', False)
                            else os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass
    AdminApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
