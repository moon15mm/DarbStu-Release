# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
import subprocess
from constants import WHATS_PATH
from config_manager import invalidate_config_cache, save_config, load_config
from whatsapp_service import get_wa_servers, start_whatsapp_server
import qrcode
from PIL import Image, ImageTk

class WhatsappTabMixin:
    """Mixin: WhatsappTabMixin"""
    # ══════════════════════════════════════════════════════════
    def _build_whatsapp_bot_section(self, parent_frame):
        """قسم إدارة بوت الواتساب."""

        wa_lf = ttk.LabelFrame(parent_frame, text=" 🤖 بوت واتساب الأعذار ", padding=8)
        wa_lf.pack(fill="x", padx=5, pady=(6, 6))

        # ─── صف الحالة ──────────────────────────────────────
        wa_top = ttk.Frame(wa_lf); wa_top.pack(fill="x", pady=(0, 4))
        self._wa_status_dot  = tk.Label(wa_top, text="⬤", font=("Tahoma", 14), fg="#aaaaaa")
        self._wa_status_dot.pack(side="right", padx=(0, 4))
        self._wa_status_text = ttk.Label(wa_top, text="اضغط 'فحص الحالة' للتحقق",
                                          font=("Tahoma", 10))
        self._wa_status_text.pack(side="right", padx=(0, 8))

        # ─── أزرار التشغيل والفحص ───────────────────────────
        btn_row = ttk.Frame(wa_lf); btn_row.pack(fill="x", pady=(0, 4))

        def _start_wa():
            start_whatsapp_server()
            self._wa_status_text.config(
                text="⏳ جارٍ التشغيل... تفقد التبويب لإدارة الواتساب")

        def _check_once():
            self._wa_status_dot.config(fg="#aaaaaa")
            self._wa_status_text.config(text="⏳ جارٍ الفحص...")
            def _do():
                try:
                    import urllib.request, json as _j
                    r    = urllib.request.urlopen("http://localhost:3000/status", timeout=2)
                    data = _j.loads(r.read())
                    if data.get("ready"):
                        pending = data.get("pending", 0)
                        self.root.after(0, lambda: (
                            self._wa_status_dot.config(fg="#22c55e"),
                            self._wa_status_text.config(
                                text="✅ متصل  |  طلبات معلّقة: {}".format(pending),
                                foreground="#166534")))
                    else:
                        self.root.after(0, lambda: (
                            self._wa_status_dot.config(fg="#f59e0b"),
                            self._wa_status_text.config(
                                text="⏳ يعمل لكن لم يتصل — امسح QR",
                                foreground="#92400e")))
                except Exception:
                    self.root.after(0, lambda: (
                        self._wa_status_dot.config(fg="#ef4444"),
                        self._wa_status_text.config(
                            text="🔴 الخادم غير متصل", foreground="#991b1b")))
            threading.Thread(target=_do, daemon=True).start()

        ttk.Button(btn_row, text="▶ تشغيل خادم الواتساب",
                   command=_start_wa).pack(side="right", padx=(0, 4))
        ttk.Button(btn_row, text="🔍 فحص الحالة",
                   command=_check_once).pack(side="right", padx=(0, 4))

        # ─── حالة البوت ─────────────────────────────────────
        bot_row = ttk.Frame(wa_lf); bot_row.pack(fill="x", pady=(0, 4))
        ttk.Label(bot_row, text="حالة البوت:", font=("Tahoma", 9, "bold")).pack(side="right", padx=(0, 6))
        self._bot_toggle_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            bot_row,
            text="البوت مفعّل (يرد على الأعذار تلقائياً)",
            variable=self._bot_toggle_var,
            command=lambda: _toggle_bot(self._bot_toggle_var.get())
        ).pack(side="right")

        def _toggle_bot(enabled: bool):
            def _do():
                try:
                    import urllib.request as _ur
                    data = json.dumps({"enabled": enabled}).encode()
                    req = _ur.Request("http://localhost:3000/bot-toggle",
                                      data=data, headers={"Content-Type": "application/json"},
                                      method="POST")
                    _ur.urlopen(req, timeout=3)
                except Exception:
                    pass
                # السحابي: لا خادم Node يحفظ الحالة — تُكتب في الملف الذي يقرؤه بوته
                try:
                    import wa_evolution as _evo
                    if _evo.provider() != "local":
                        _evo.write_bot_config(enabled=bool(enabled))
                except Exception:
                    pass
                status = "مفعّل ✅" if enabled else "موقوف ⏸"
                color  = "#166634" if enabled else "#92400e"
                self.root.after(0, lambda: self._wa_status_text.config(
                    text=f"البوت {status}", foreground=color))
            threading.Thread(target=_do, daemon=True).start()

        # ─── الكلمات المفتاحية ───────────────────────────────
        ttk.Separator(wa_lf, orient="horizontal").pack(fill="x", pady=(4, 6))

        kw_hdr = ttk.Frame(wa_lf); kw_hdr.pack(fill="x", pady=(0, 2))
        ttk.Label(kw_hdr, text="🔑 الكلمات المفتاحية للأعذار:",
                  font=("Tahoma", 9, "bold")).pack(side="right")
        ttk.Button(kw_hdr, text="💾 حفظ الكلمات",
                   command=lambda: _save_keywords()).pack(side="left", padx=(0, 4))
        ttk.Button(kw_hdr, text="🔄 تحميل من الخادم",
                   command=lambda: _load_keywords()).pack(side="left")

        ttk.Label(wa_lf,
            text="أدخل الكلمات مفصولة بفاصلة — مثال: عذر، مريض، سفر، ok",
            font=("Tahoma", 8), foreground="#666").pack(anchor="e", pady=(0, 2))

        self._kw_text = tk.Text(wa_lf, height=3, font=("Tahoma", 10),
                                 wrap="word", relief="solid", bd=1)
        self._kw_text.pack(fill="x", pady=(0, 4))
        self._kw_text.insert("1.0",
            "عذر، معذور، مريض، مرض، علاج، مستشفى، وفاة، سفر، ظروف، إجازة، اجازة، excuse، ok، اوك، نعم، موافق، 1")

        def _load_keywords():
            def _do():
                try:
                    import wa_evolution as _evo
                    if _evo.provider() == "evolution":
                        # لا خادم محلي في السحابي — الكلمات والحالة من ملف البوت
                        _bc = _evo.bot_config()
                        def _apply_cloud():
                            self._kw_text.delete("1.0", "end")
                            self._kw_text.insert("1.0", "، ".join(_bc["keywords"]))
                            self._bot_toggle_var.set(_bc["bot_enabled"])
                        self.root.after(0, _apply_cloud)
                        return
                except Exception:
                    pass
                try:
                    import urllib.request as _ur, json as _j
                    r   = _ur.urlopen("http://localhost:3000/bot-config", timeout=1)
                    cfg = _j.loads(r.read())
                    kws     = cfg.get("keywords", [])
                    enabled = cfg.get("bot_enabled", True)
                    def _apply():
                        self._kw_text.delete("1.0", "end")
                        self._kw_text.insert("1.0", "، ".join(kws))
                        self._bot_toggle_var.set(enabled)
                    self.root.after(0, _apply)
                except Exception:
                    pass
            threading.Thread(target=_do, daemon=True).start()

        def _save_keywords():
            raw = self._kw_text.get("1.0", "end").strip()
            kws = [k.strip() for k in re.split(r'[،,،\n]+', raw) if k.strip()]
            if not kws:
                messagebox.showerror("خطأ", "لا توجد كلمات للحفظ!")
                return
            try:
                import wa_evolution as _evo
                if _evo.provider() != "local":
                    # السحابي: الكلمات في ملف البوت الذي يقرؤه بوته (والمحلي عند تشغيله)
                    if _evo.write_bot_config(keywords=kws):
                        messagebox.showinfo("تم", f"تم حفظ {len(kws)} كلمة مفتاحية بنجاح.")
                    else:
                        messagebox.showerror("خطأ", "تعذّر حفظ الكلمات في ملف البوت.")
                    if _evo.provider() == "evolution":
                        return
            except Exception:
                pass
            def _do():
                try:
                    import urllib.request as _ur, json as _j
                    data = json.dumps({"keywords": kws}, ensure_ascii=False).encode("utf-8")
                    # ‏‎/bot-config‎ لا ‎/bot-keywords‎: الأخير لا وجود له في server.js، فكان
                    # الحفظ يفشل دائماً. وserver.js يردّ ‎{status:'ok'}‎ لا ‎{ok:true}‎.
                    req  = _ur.Request("http://localhost:3000/bot-config",
                                       data=data,
                                       headers={"Content-Type": "application/json"},
                                       method="POST")
                    resp   = _ur.urlopen(req, timeout=3)
                    result = _j.loads(resp.read())
                    if result.get("ok") or result.get("status") == "ok":
                        self.root.after(0, lambda: messagebox.showinfo(
                            "تم", f"تم حفظ {len(kws)} كلمة مفتاحية بنجاح."))
                        _load_keywords()
                    else:
                        _why = str(result.get("message") or result)
                        self.root.after(0, lambda: messagebox.showerror(
                            "خطأ", "تعذّر حفظ الكلمات.\n" + _why))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror(
                        "خطأ", "تعذّر حفظ الكلمات.\nتأكد من تشغيل الخادم أولاً.\n" + str(e)))
            threading.Thread(target=_do, daemon=True).start()

        parent_frame.after(600, _load_keywords)


    def check_whatsapp_status_ui(self):
        """وظيفة مساعدة لفحص حالة الواتساب وعرض رسالة للمستخدم (تُستخدم من تبويبات مختلفة)."""
        def _cloud_msg():
            # السحابي: الحالة من الخادم السحابي لا من المنفذ 3000 (لا خادم محلي فيه)
            try:
                import wa_evolution as _evo
                if not _evo.configured():
                    return "warn", "☁️ الوضع السحابي مختار، لكن إعداده ناقص.\nأكمل الرابط واسم الجلسة والمفتاح في تبويب 'إدارة الواتساب'."
                if _evo.state(fresh=True) == "open":
                    return "ok", "✅ الواتساب السحابي متصل وجاهز."
                return "warn", "⏳ الجلسة السحابية غير مربوطة.\nامسح رمز الـ QR من تبويب 'إدارة الواتساب'."
            except Exception as e:
                return "err", "🔴 تعذّر بلوغ الخادم السحابي.\n" + str(e)

        def _show(kind, msg):
            box = {"ok": messagebox.showinfo, "warn": messagebox.showwarning}.get(kind, messagebox.showerror)
            self.root.after(0, lambda: box("حالة الواتساب", msg))

        try:
            import wa_evolution as _evo
            _prov = _evo.provider()
        except Exception:
            _prov = "local"
        if _prov == "evolution":
            threading.Thread(target=lambda: _show(*_cloud_msg()), daemon=True).start()
            return

        def _do():
            if _prov == "auto":
                # التلقائي: يكفي أن يجهز أحدهما — المحلي أولاً كما يرسل
                try:
                    import urllib.request, json as _j
                    r = urllib.request.urlopen("http://localhost:3000/status", timeout=3)
                    if _j.loads(r.read()).get("ready"):
                        _show("ok", "✅ الواتساب المحلي متصل وجاهز (والسحابي احتياطٌ له).")
                        return
                except Exception:
                    pass
                kind, msg = _cloud_msg()
                _show(kind, "المحلي غير جاهز — " + msg if kind == "ok" else msg)
                return
            try:
                import urllib.request, json as _j
                # فحص الحالة على المنفذ الافتراضي 3000
                r = urllib.request.urlopen("http://localhost:3000/status", timeout=3)
                data = _j.loads(r.read())
                
                if data.get("ready"):
                    pending = data.get("pending", 0)
                    msg = f"✅ الواتساب متصل وجاهز.\nالطلبات المعلقة: {pending}"
                    self.root.after(0, lambda: messagebox.showinfo("حالة الواتساب", msg))
                else:
                    msg = "⏳ خادم الواتساب يعمل، لكن لم يتم ربط الحساب بعد.\nيرجى الذهاب لتبويب 'إدارة الواتساب' لمسح رمز الـ QR."
                    self.root.after(0, lambda: messagebox.showwarning("حالة الواتساب", msg))
            except Exception:
                msg = "🔴 خادم الواتساب غير متصل.\nيرجى الذهاب لتبويب 'إدارة الواتساب' وتشغيل الخادم أولاً."
                self.root.after(0, lambda: messagebox.showerror("حالة الواتساب", msg))
        
        threading.Thread(target=_do, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    # مزوّد الواتساب: محلي · سحابي (Evolution API) · تلقائي
    # ═══════════════════════════════════════════════════════════════
    # المحلي يبقى كما كان حرفاً. السحابي على خادم درب الطلاب بجلسةٍ ومفتاحٍ لهذه
    # المدرسة وحدها (darbstu-evo-add). والتلقائي يحوّل إلى السحابي حين يجزم
    # المحلي بأن شيئاً لم يخرج. والبطاقة لا تتصل بالشبكة ما دام «المحلي» مختاراً.
    _WA_PROV_LABELS = {
        "local":     "💻  الخادم المحلي (جهاز المدرسة)",
        "evolution": "☁️  الخادم السحابي (Evolution API)",
        "auto":      "🔄  الوضع التلقائي (محلي مع تحويل سحابي للطوارئ)",
    }

    def _build_wa_provider_card(self, inner, _card):
        try:
            import wa_evolution as _evo
        except Exception as e:
            print(f"[WA-GUI] وحدة الإرسال السحابي غير متاحة: {e}")
            return
        card = _card(inner, "☁️  مزوّد الواتساب", "#0f766e")
        tk.Label(card,
                 text="المحلي يرسل من جهاز المدرسة كما كان. السحابي يرسل من خادم درب "
                      "الطلاب برقمٍ تربطه المدرسة مرة واحدة بمسح رمز. والتلقائي يرسل "
                      "محلياً، ويحوّل إلى السحابي إن توقف المحلي أو بلغ سقفه اليومي.\n"
                      "للبدء: اختر السحابي أو التلقائي، ثم «تفعيل الواتساب السحابي»، ثم امسح الرمز.",
                 font=("Tahoma", 9), bg="white", fg="#6b7280",
                 justify="right", wraplength=560).pack(anchor="e", padx=10, pady=(6, 4))

        cfg0 = load_config()
        s0 = _evo.settings(cfg0)
        prov_var = tk.StringVar(value=_evo.provider(cfg0))
        url_var = tk.StringVar(value=s0["url"])
        inst_var = tk.StringVar(value=s0["instance"])
        key_var = tk.StringVar(value=s0["key"])
        self._wa_prov_vars = (prov_var, url_var, inst_var, key_var)

        for val in ("local", "evolution", "auto"):
            tk.Radiobutton(card, text=self._WA_PROV_LABELS[val], value=val,
                           variable=prov_var, font=("Tahoma", 10), bg="white",
                           activebackground="white", anchor="e", justify="right",
                           command=lambda: _apply_enabled()).pack(fill="x", padx=14)

        # التفعيل: جلسة هذه المدرسة من سيرفر درب الطلاب بتوقيع مفتاح نفقها —
        # فلا تكتب المدرسة مفتاحاً. الحقول اليدوية تبقى للدعم الفني مطويّة.
        act_row = tk.Frame(card, bg="white")
        act_row.pack(fill="x", padx=10, pady=(8, 2))
        act_btn = tk.Button(act_row, text="⚡  تفعيل الواتساب السحابي", bg="#0f766e", fg="white",
                            font=("Tahoma", 10, "bold"), relief="flat", cursor="hand2",
                            padx=14, pady=6, command=lambda: _activate())
        act_btn.pack(side="right")
        tk.Label(act_row, text="يجلب جلسة هذه المدرسة من سيرفر درب الطلاب — بلا مفتاح تكتبه",
                 font=("Tahoma", 8), bg="white", fg="#6b7280").pack(side="right", padx=(0, 8))

        manual = {"open": False}
        manual_btn = tk.Button(card, text="⚙️  إعداد يدوي (للدعم الفني)  ▾", bg="white",
                               fg="#475569", font=("Tahoma", 8), relief="flat", cursor="hand2",
                               bd=0, activebackground="white", command=lambda: _toggle_manual())
        manual_btn.pack(anchor="e", padx=10, pady=(2, 0))

        fields = tk.Frame(card, bg="white")
        entries = []

        def _row(label, var, show=""):
            r = tk.Frame(fields, bg="white")
            r.pack(fill="x", pady=2)
            tk.Label(r, text=label, font=("Tahoma", 9), bg="white",
                     width=16, anchor="e").pack(side="right")
            e = ttk.Entry(r, textvariable=var, show=show, justify="left")
            e.pack(side="right", fill="x", expand=True, padx=(0, 6))
            entries.append(e)

        _row("رابط الخادم السحابي:", url_var)
        _row("اسم الجلسة:", inst_var)
        _row("مفتاح الجلسة:", key_var, show="•")

        status_lbl = tk.Label(card, text="", font=("Tahoma", 10), bg="white",
                              fg="#555555", justify="right", wraplength=560)
        status_lbl.pack(anchor="e", padx=10, pady=(4, 2))
        self._evo_status_lbl = status_lbl

        btns = tk.Frame(card, bg="white")
        btns.pack(fill="x", padx=10, pady=(2, 6))

        qr_box = tk.Frame(card, bg="#f8fafc", bd=1, relief="sunken")
        qr_lbl = tk.Label(qr_box, text="", font=("Tahoma", 9),
                          bg="#f8fafc", fg="#64748b", pady=12)
        qr_lbl.pack(expand=True)
        self._evo_qr_img = None          # مرجعٌ يمنع حذف الصورة من الذاكرة
        self._evo_qr_lbl = qr_lbl
        poll = {"busy": False, "qr_at": 0.0}

        def _status(text, color="#555555"):
            self.root.after(0, lambda: status_lbl.config(text=text, fg=color))

        def _apply_enabled():
            cloud = prov_var.get() != "local"
            for e in entries:
                e.config(state="normal" if cloud else "disabled")
            for b in cloud_btns:
                b.config(state="normal" if cloud else "disabled")
            if cloud:
                qr_box.pack(fill="x", padx=10, pady=(2, 10))
            else:
                qr_box.pack_forget()

        def _show_qr_b64(b64):
            try:
                raw = base64.b64decode(b64.split(",", 1)[-1])
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                img = img.resize((230, 230), Image.Resampling.LANCZOS)
                tk_img = ImageTk.PhotoImage(img)
                qr_lbl.config(image=tk_img, text="")
                self._evo_qr_img = tk_img
            except Exception as e:
                qr_lbl.config(image="", text="تعذّر عرض الرمز: %s" % e)

        def _render(res):
            """يعرض نتيجة fetch_qr أو الحالة — في خيط الواجهة."""
            if res.get("state") == "open":
                self._evo_qr_img = None
                qr_lbl.config(image="", text="✅ الجلسة السحابية متصلة", fg="#059669")
                status_lbl.config(text="✅ الواتساب السحابي متصل وجاهز", fg="#166534")
            elif res.get("base64"):
                _show_qr_b64(res["base64"])
                status_lbl.config(text="📱 " + res.get("msg", ""), fg="#92400e")
            else:
                qr_lbl.config(image="", text=res.get("msg", ""), fg="#991b1b")
                status_lbl.config(text="🔴 " + res.get("msg", ""), fg="#991b1b")

        def _refresh(force_qr=False):
            if poll["busy"]:
                return
            poll["busy"] = True

            def _do():
                try:
                    st = _evo.state(fresh=True)
                    poll["open"] = (st == "open")
                    if st == "open":
                        res = {"state": "open"}
                    elif force_qr or time.time() - poll["qr_at"] > 18:
                        poll["qr_at"] = time.time()
                        res = _evo.fetch_qr()
                    else:
                        res = None
                    if res is not None:
                        self.root.after(0, lambda: _render(res))
                    elif st is None:
                        _status("🔴 تعذّر بلوغ الخادم السحابي — تحقق من الرابط والإنترنت",
                                "#991b1b")
                finally:
                    poll["busy"] = False
            threading.Thread(target=_do, daemon=True).start()

        def _toggle_manual():
            manual["open"] = not manual["open"]
            if manual["open"]:
                fields.pack(fill="x", padx=10, pady=(4, 2), after=manual_btn)
                manual_btn.config(text="⚙️  إعداد يدوي (للدعم الفني)  ▴")
            else:
                fields.pack_forget()
                manual_btn.config(text="⚙️  إعداد يدوي (للدعم الفني)  ▾")

        def _activate():
            choice = prov_var.get()
            act_btn.config(state="disabled")
            _status("⏳ جارٍ طلب جلسة هذه المدرسة من سيرفر درب الطلاب...", "#92400e")

            def _do():
                res = _evo.activate(choice)

                def _done():
                    act_btn.config(state="normal")
                    if not res.get("ok"):
                        status_lbl.config(text="🔴 " + res.get("msg", ""), fg="#991b1b")
                        return
                    s = _evo.settings()
                    prov_var.set(res["provider"])
                    url_var.set(s["url"])
                    inst_var.set(s["instance"])
                    key_var.set(s["key"])
                    _apply_enabled()
                    msg = "✅ " + res["msg"]
                    if not res.get("webhook_ok"):
                        msg += "\n⚠️ " + res.get("webhook_msg", "")
                    status_lbl.config(text=msg, fg="#166534" if res.get("webhook_ok") else "#92400e")
                    _refresh(force_qr=True)
                self.root.after(0, _done)
            threading.Thread(target=_do, daemon=True).start()

        def _save():
            prov = prov_var.get()
            url = url_var.get().strip().rstrip("/")
            inst = inst_var.get().strip()
            key = key_var.get().strip()
            if prov != "local" and not (url and inst and key):
                messagebox.showerror(
                    "لم تُفعَّل الخدمة السحابية",
                    "لم تُفعَّل الخدمة السحابية لهذه المدرسة بعد.\n"
                    "اضغط «⚡ تفعيل الواتساب السحابي» — أو أدخل بيانات الجلسة في «إعداد يدوي».")
                return
            if prov != "local" and not url.startswith("https://") \
                    and not url.startswith(("http://127.", "http://localhost")):
                if not messagebox.askyesno(
                        "رابط غير مشفّر",
                        "الرابط ليس https — سيعبر مفتاح الجلسة الإنترنت مكشوفاً.\nمتابعة؟"):
                    return
            cfg = load_config()
            cfg.update({"whatsapp_provider": prov, "evolution_server_url": url,
                        "evolution_instance_name": inst, "evolution_api_key": key})
            save_config(cfg)
            invalidate_config_cache()
            _apply_enabled()
            if prov == "local":
                _status("✅ حُفظ: " + self._WA_PROV_LABELS[prov].strip(), "#166534")
                return
            _status("⏳ حُفظ — جارٍ ضبط الاستقبال وفحص الجلسة السحابية...", "#92400e")

            def _after():
                okw, msgw = _evo.ensure_webhook()
                if not okw:
                    _status("⚠️ " + msgw, "#92400e")
                _refresh(force_qr=True)
            threading.Thread(target=_after, daemon=True).start()

        def _logout():
            if not messagebox.askyesno(
                    "فصل الجلسة السحابية",
                    "سيُفصل رقم الواتساب عن الخادم السحابي ويلزم مسح رمز جديد.\nمتابعة؟"):
                return
            def _do():
                ok = _evo.logout()
                _status("✅ فُصلت الجلسة — امسح الرمز الجديد" if ok
                        else "🔴 تعذّر فصل الجلسة", "#92400e" if ok else "#991b1b")
                _refresh(force_qr=True)
            threading.Thread(target=_do, daemon=True).start()

        tk.Button(btns, text="💾  حفظ المزوّد", bg="#0f766e", fg="white",
                  font=("Tahoma", 10, "bold"), relief="flat", cursor="hand2",
                  padx=14, pady=6, command=_save).pack(side="right", padx=(0, 6))
        cloud_btns = [
            tk.Button(btns, text="🔗  عرض رمز الربط", bg="#115e59", fg="white",
                      font=("Tahoma", 10), relief="flat", cursor="hand2",
                      padx=12, pady=6, command=lambda: _refresh(force_qr=True)),
            tk.Button(btns, text="🔍  فحص الاتصال السحابي", bg="#134e4a", fg="white",
                      font=("Tahoma", 10), relief="flat", cursor="hand2",
                      padx=12, pady=6, command=lambda: _refresh(force_qr=False)),
            tk.Button(btns, text="🚪  فصل الجلسة", bg="#f3f4f6", fg="#991b1b",
                      font=("Tahoma", 10), relief="flat", cursor="hand2",
                      padx=12, pady=6, command=_logout),
        ]
        for b in cloud_btns:
            b.pack(side="right", padx=(0, 4))
        self._evo_save = _save           # للاختبار
        self._evo_refresh = _refresh
        self._evo_activate = _activate
        self._evo_toggle_manual = _toggle_manual

        def _poll():
            # كل ٦ ثوانٍ أثناء انتظار المسح، وكل دقيقة بعد الاتصال — لا حِمل بلا داعٍ
            if not self.whatsapp_manager_frame.winfo_exists():
                return
            if prov_var.get() != "local" and _evo.provider() != "local":
                _refresh()
            self.root.after(60000 if poll.get("open") else 6000, _poll)

        _apply_enabled()
        if prov_var.get() != "local":
            _status("الوضع: " + self._WA_PROV_LABELS[prov_var.get()].strip()
                    + ("" if s0["key"] else " — لم تُفعَّل بعد: اضغط «تفعيل الواتساب السحابي»"),
                    "#555555" if s0["key"] else "#92400e")
        self.root.after(1500, _poll)

    # ═══════════════════════════════════════════════════════════════
    # تبويب إدارة الواتساب
    # ═══════════════════════════════════════════════════════════════
    def _build_whatsapp_manager_tab(self):
        frame = self.whatsapp_manager_frame
        frame.config(bg="white")

        hdr = tk.Frame(frame, bg="#1565C0", height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📱  إدارة الواتساب", bg="#1565C0", fg="white",
                 font=("Tahoma", 14, "bold")).pack(side="right", padx=16, pady=10)

        scroll_canvas = tk.Canvas(frame, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(scroll_canvas, bg="white")
        inner_win = scroll_canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_conf(e):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))
        inner.bind("<Configure>", _on_inner_conf)
        _wt_last_w = [0]
        def _on_canvas_conf(e):
            w = scroll_canvas.winfo_width()
            if w == _wt_last_w[0]: return
            _wt_last_w[0] = w
            scroll_canvas.itemconfig(inner_win, width=w)
        scroll_canvas.bind("<Configure>", _on_canvas_conf)

        PAD = dict(padx=18, pady=8)

        def _card(parent, title, color="#1565C0"):
            lf = tk.LabelFrame(parent, text="  {}  ".format(title),
                               font=("Tahoma", 10, "bold"),
                               fg=color, bg="white",
                               relief="groove", bd=2)
            lf.pack(fill="x", **PAD)
            return lf

        # ── بطاقة 0: المفتاح الرئيسي ────────────────────────────
        # ستة أشياء ترسل تلقائياً. إطفاؤها واحداً واحداً متعب، ونسيان
        # واحد يعني رسائل تخرج بلا قصد — خاصة أثناء التجربة والتجهيز.
        from config_manager import (set_bots_master, bots_status, BOT_FLAGS)

        _BOT_AR = {
            "absence_bot_enabled":        "رسائل الغياب",
            "permission_bot_enabled":     "رسائل الاستئذان",
            "alert_enabled":              "الإشعارات الذكية",
            "daily_report_enabled":       "التقرير اليومي",
            "tardiness_auto_send_enabled": "رابط التأخر المجدوَل",
            "weekly_reward_enabled":      "مكافأة الحضور الأسبوعية",
        }

        mst_card = _card(inner, "🛑  إيقاف الإرسال لأولياء الأمور", "#b91c1c")
        tk.Label(mst_card,
                 text="يوقف كل ما يُرسل تلقائياً لأولياء الأمور دفعةً واحدة. "
                      "ما يصل الطاقم الإداري — كالتقرير اليومي وتنبيهات "
                      "الإدارة — يستمر. ولا يمحو إعداداتك: عند التشغيل يعود "
                      "كل شيء كما كان.",
                 font=("Tahoma", 9), bg="white", fg="#6b7280",
                 justify="right", wraplength=560).pack(anchor="e", padx=10, pady=(6, 2))

        mst_row = tk.Frame(mst_card, bg="white")
        mst_row.pack(fill="x", padx=10, pady=(0, 4))
        self._wm_master_lbl = tk.Label(mst_row, text="",
                                       font=("Tahoma", 11, "bold"), bg="white")
        self._wm_master_lbl.pack(side="right", padx=(0, 10))
        self._wm_master_detail = tk.Label(mst_card, text="", font=("Tahoma", 9),
                                          bg="white", fg="#6b7280",
                                          justify="right", wraplength=560)
        self._wm_master_detail.pack(anchor="e", padx=10, pady=(0, 8))

        def _refresh_master():
            from config_manager import PARENT_FLAGS
            st = bots_status()
            if st["master"]:
                self._wm_master_lbl.config(text="✅  الإرسال لأولياء الأمور مُشغَّل",
                                           fg="#059669")
                names = [_BOT_AR[f] for f in BOT_FLAGS if st["flags"].get(f)]
                self._wm_master_detail.config(
                    text=("العاملة الآن: " + "، ".join(names)) if names
                    else "لا توجد مهمة مفعّلة حالياً — كلها مطفأة فردياً.",
                    fg="#6b7280")
                self._wm_master_off.config(state="normal", bg="#fee2e2", fg="#b91c1c")
                self._wm_master_on.config(state="disabled", bg="#f3f4f6", fg="#9ca3af")
            else:
                self._wm_master_lbl.config(
                    text="⛔  الإرسال لأولياء الأمور موقوف", fg="#b91c1c")
                still = [_BOT_AR[f] for f in BOT_FLAGS
                         if f not in PARENT_FLAGS and st["flags"].get(f)]
                self._wm_master_detail.config(
                    text=("لن تخرج رسالة لولي أمر. الإرسال اليدوي يعمل كالمعتاد."
                          + ("\nويستمر للطاقم الإداري: " + "، ".join(still)
                             if still else "")),
                    fg="#b91c1c")
                self._wm_master_off.config(state="disabled", bg="#f3f4f6", fg="#9ca3af")
                self._wm_master_on.config(state="normal", bg="#dcfce7", fg="#059669")

        def _set_master(on):
            set_bots_master(on)
            _refresh_master()
            try:
                if on:
                    _set_absence_bot(load_config().get("absence_bot_enabled", True))
                    _set_permission_bot(load_config().get("permission_bot_enabled", True))
            except Exception:
                pass

        btn_row = tk.Frame(mst_card, bg="white")
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        self._wm_master_off = tk.Button(btn_row, text="⛔  إيقاف الإرسال لأولياء الأمور",
            font=("Tahoma", 10, "bold"), relief="flat", cursor="hand2",
            padx=14, pady=6, command=lambda: _set_master(False))
        self._wm_master_off.pack(side="right", padx=(0, 6))
        self._wm_master_on = tk.Button(btn_row, text="▶  تشغيل الإرسال لأولياء الأمور",
            font=("Tahoma", 10, "bold"), relief="flat", cursor="hand2",
            padx=14, pady=6, command=lambda: _set_master(True))
        self._wm_master_on.pack(side="right")

        self._wm_refresh_master = _refresh_master

        # ── بطاقة: مزوّد الواتساب — محلي · سحابي · تلقائي ───────────────
        self._build_wa_provider_card(inner, _card)

        # ── بطاقة 1: خادم الواتساب ──────────────────────────────
        srv_card = _card(inner, "🖥️  خادم الواتساب", "#1565C0")

        status_row = tk.Frame(srv_card, bg="white")
        status_row.pack(fill="x", padx=10, pady=(8, 4))
        self._wm_dot = tk.Label(status_row, text="⬤", font=("Tahoma", 16),
                                 fg="#aaaaaa", bg="white")
        self._wm_dot.pack(side="right", padx=(0, 6))
        self._wm_lbl = tk.Label(status_row,
                                 text="اضغط فحص الحالة للتحقق من الاتصال",
                                 font=("Tahoma", 10), bg="white", fg="#555555")
        self._wm_lbl.pack(side="right")

        btn_row = tk.Frame(srv_card, bg="white")
        btn_row.pack(fill="x", padx=10, pady=(2, 10))

        def _wm_start():
            start_whatsapp_server()
            self._wm_lbl.config(
                text="⏳ جارٍ التشغيل في الخلفية... انتظر رمز الـ QR أدناه",
                fg="#92400e")
            self._wm_dot.config(fg="#f59e0b")

        def _wm_check():
            self._wm_lbl.config(text="⏳ جارٍ الفحص...", fg="#555555")
            self._wm_dot.config(fg="#aaaaaa")
            def _do_check():
                try:
                    import urllib.request as _ur, json as _j
                    servers = get_wa_servers()
                    results = []
                    for srv in servers:
                        port = srv.get("port", 3000)
                        try:
                            r = _ur.urlopen("http://localhost:{}/status".format(port), timeout=2)
                            data = _j.loads(r.read())
                            results.append((port, data.get("ready", False), data.get("pending", 0)))
                        except Exception:
                            results.append((port, False, 0))
                    ready_count = sum(1 for _, r, _ in results if r)
                    total = len(results)
                    if ready_count == total and total > 0:
                        txt   = "✅ متصل ({}/{} خادم)  |  معلّقة: {}".format(
                            ready_count, total, sum(p for _, _, p in results))
                        self.root.after(0, lambda: (
                            self._wm_dot.config(fg="#22c55e"),
                            self._wm_lbl.config(text=txt, fg="#166534")))
                    elif ready_count > 0:
                        txt = "⚠️ متصل جزئياً ({}/{})".format(ready_count, total)
                        self.root.after(0, lambda: (
                            self._wm_dot.config(fg="#f59e0b"),
                            self._wm_lbl.config(text=txt, fg="#92400e")))
                    else:
                        self.root.after(0, lambda: (
                            self._wm_dot.config(fg="#ef4444"),
                            self._wm_lbl.config(
                                text="🔴 الخادم غير متصل — امسح QR أو شغّل الخادم",
                                fg="#991b1b")))
                except Exception:
                    self.root.after(0, lambda: (
                        self._wm_dot.config(fg="#ef4444"),
                        self._wm_lbl.config(text="🔴 الخادم غير متصل", fg="#991b1b")))
            threading.Thread(target=_do_check, daemon=True).start()

        tk.Button(btn_row, text="▶  تشغيل الخادم",
                  bg="#1565C0", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=14, pady=6,
                  command=_wm_start).pack(side="right", padx=(0, 8))
        tk.Button(btn_row, text="🔍  فحص الحالة",
                  bg="#0d47a1", fg="white", font=("Tahoma", 10),
                  relief="flat", cursor="hand2", padx=14, pady=6,
                  command=_wm_check).pack(side="right", padx=(0, 4))

        # ── مساحة عرض الـ QR Code ────────────────────────────
        qr_frame = tk.Frame(srv_card, bg="#f8fafc", bd=1, relief="sunken")
        qr_frame.pack(fill="x", padx=10, pady=(4, 10))
        
        qr_label = tk.Label(qr_frame, text="بانتظار رمز الـ QR...", font=("Tahoma", 9), 
                            bg="#f8fafc", fg="#64748b", pady=20)
        qr_label.pack(expand=True)
        
        self._last_qr_img = None # لمنع حذف الصورة من الذاكرة

        def _update_qr_display(qr_text):
            try:
                # توليد صورة QR من النص القادم من السيرفر
                qr = qrcode.QRCode(version=1, box_size=6, border=2)
                qr.add_data(qr_text)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                
                # تحويل لمقاس مناسب للعرض
                img = img.resize((200, 200), Image.Resampling.LANCZOS)
                
                tk_img = ImageTk.PhotoImage(img)
                qr_label.config(image=tk_img, text="")
                self._last_qr_img = tk_img # حفظ المرجع
            except Exception as e:
                print(f"[WA-GUI] خطأ في معالجة الـ QR: {e}")

        def _poll_qr():
            if not self.whatsapp_manager_frame.winfo_exists(): return
            try:
                import urllib.request as _ur, json as _j
                # نسحب الحالة من رابط /qr الجديد
                r = _ur.urlopen("http://localhost:3000/qr", timeout=1)
                data = _j.loads(r.read())
                
                if data.get("ready"):
                    qr_label.config(image="", text="✅ المتصفح متصل وجاهز", fg="#059669")
                    self._wm_dot.config(fg="#22c55e")
                    self._wm_lbl.config(text="✅ خادم الواتساب متصل", fg="#166534")
                elif data.get("qr"):
                    _update_qr_display(data["qr"])
                else:
                    # شغال بس ما فيه QR حالياً (ممكن لسه بيفتح أو متصل)
                    pass
            except Exception:
                pass
            # كرر الفحص كل 4 ثواني
            self.root.after(4000, _poll_qr)

        # ابدأ الفحص التلقائي
        self.root.after(2000, _poll_qr)

        # ── بطاقة 2: بوت الغياب ─────────────────────────────────
        abs_card = _card(inner, "📋  بوت رسائل الغياب", "#7c3aed")
        tk.Label(abs_card,
                 text="عند تسجيل غياب طالب يُرسل تلقائياً رسالة واتساب لولي أمره.",
                 font=("Tahoma", 9), bg="white", fg="#6b7280").pack(anchor="e", padx=10, pady=(6, 2))
        abs_row = tk.Frame(abs_card, bg="white")
        abs_row.pack(fill="x", padx=10, pady=(0, 10))
        self._wm_abs_lbl = tk.Label(abs_row, text="", font=("Tahoma", 10, "bold"), bg="white")
        self._wm_abs_lbl.pack(side="right", padx=(0, 14))

        def _set_absence_bot(enabled):
            cfg = load_config()
            cfg["absence_bot_enabled"] = enabled
            save_config(cfg)
            invalidate_config_cache()
            if enabled:
                self._wm_abs_lbl.config(text="✅  البوت مفعّل", fg="#166534")
                self._wm_abs_on.config(relief="sunken", bg="#bbf7d0")
                self._wm_abs_off.config(relief="flat", bg="#f3f4f6")
            else:
                self._wm_abs_lbl.config(text="⏸  البوت موقوف", fg="#991b1b")
                self._wm_abs_on.config(relief="flat", bg="#f3f4f6")
                self._wm_abs_off.config(relief="sunken", bg="#fecaca")
        self._set_absence_bot = _set_absence_bot

        self._wm_abs_off = tk.Button(abs_row, text="⏸  إيقاف",
            font=("Tahoma", 10), relief="flat", cursor="hand2",
            padx=12, pady=5, bg="#f3f4f6",
            command=lambda: _set_absence_bot(False))
        self._wm_abs_off.pack(side="left", padx=(0, 4))
        self._wm_abs_on = tk.Button(abs_row, text="▶  تشغيل",
            font=("Tahoma", 10, "bold"), relief="flat", cursor="hand2",
            padx=12, pady=5, bg="#f3f4f6",
            command=lambda: _set_absence_bot(True))
        self._wm_abs_on.pack(side="left")

        # ── بطاقة 3: بوت الاستئذان ──────────────────────────────
        perm_card = _card(inner, "🚪  بوت رسائل الاستئذان", "#0891b2")
        tk.Label(perm_card,
                 text="عند طلب استئذان طالب يُرسل تلقائياً رسالة لولي أمره لأخذ الموافقة.",
                 font=("Tahoma", 9), bg="white", fg="#6b7280").pack(anchor="e", padx=10, pady=(6, 2))
        perm_row = tk.Frame(perm_card, bg="white")
        perm_row.pack(fill="x", padx=10, pady=(0, 10))
        self._wm_perm_lbl = tk.Label(perm_row, text="", font=("Tahoma", 10, "bold"), bg="white")
        self._wm_perm_lbl.pack(side="right", padx=(0, 14))

        def _set_permission_bot(enabled):
            cfg = load_config()
            cfg["permission_bot_enabled"] = enabled
            save_config(cfg)
            invalidate_config_cache()
            if enabled:
                self._wm_perm_lbl.config(text="✅  البوت مفعّل", fg="#166534")
                self._wm_perm_on.config(relief="sunken", bg="#bbf7d0")
                self._wm_perm_off.config(relief="flat", bg="#f3f4f6")
            else:
                self._wm_perm_lbl.config(text="⏸  البوت موقوف", fg="#991b1b")
                self._wm_perm_on.config(relief="flat", bg="#f3f4f6")
                self._wm_perm_off.config(relief="sunken", bg="#fecaca")
        self._set_permission_bot = _set_permission_bot

        self._wm_perm_off = tk.Button(perm_row, text="⏸  إيقاف",
            font=("Tahoma", 10), relief="flat", cursor="hand2",
            padx=12, pady=5, bg="#f3f4f6",
            command=lambda: _set_permission_bot(False))
        self._wm_perm_off.pack(side="left", padx=(0, 4))
        self._wm_perm_on = tk.Button(perm_row, text="▶  تشغيل",
            font=("Tahoma", 10, "bold"), relief="flat", cursor="hand2",
            padx=12, pady=5, bg="#f3f4f6",
            command=lambda: _set_permission_bot(True))
        self._wm_perm_on.pack(side="left")

        # ── بطاقة 4: بوت ردود الأعذار ───────────────────────────
        exc_card = _card(inner, "💬  بوت ردود الأعذار", "#059669")
        tk.Label(exc_card,
                 text="يرد تلقائياً على أولياء الأمور ويقبل الأعذار عبر واتساب.",
                 font=("Tahoma", 9), bg="white", fg="#6b7280").pack(anchor="e", padx=10, pady=(6, 2))
        exc_row = tk.Frame(exc_card, bg="white")
        exc_row.pack(fill="x", padx=10, pady=(0, 10))
        self._wm_exc_lbl = tk.Label(exc_row, text="", font=("Tahoma", 10, "bold"), bg="white")
        self._wm_exc_lbl.pack(side="right", padx=(0, 14))

        def _set_excuse_bot(enabled):
            def _do():
                try:
                    import urllib.request as _ur, json as _j
                    data = _j.dumps({"enabled": enabled}).encode()
                    req  = _ur.Request("http://localhost:3000/bot-toggle",
                                       data=data,
                                       headers={"Content-Type": "application/json"},
                                       method="POST")
                    _ur.urlopen(req, timeout=3)
                except Exception:
                    pass
                # السحابي لا خادم Node فيه يحفظ الحالة — تُكتب في الملف الذي يقرؤه بوته
                try:
                    import wa_evolution as _evo
                    if _evo.provider() != "local":
                        _evo.write_bot_config(enabled=bool(enabled))
                except Exception:
                    pass
                def _apply():
                    if enabled:
                        self._wm_exc_lbl.config(text="✅  البوت مفعّل", fg="#166534")
                        self._wm_exc_on.config(relief="sunken", bg="#bbf7d0")
                        self._wm_exc_off.config(relief="flat", bg="#f3f4f6")
                    else:
                        self._wm_exc_lbl.config(text="⏸  البوت موقوف", fg="#991b1b")
                        self._wm_exc_on.config(relief="flat", bg="#f3f4f6")
                        self._wm_exc_off.config(relief="sunken", bg="#fecaca")
                self.root.after(0, _apply)
            threading.Thread(target=_do, daemon=True).start()
        self._set_excuse_bot = _set_excuse_bot

        self._wm_exc_off = tk.Button(exc_row, text="⏸  إيقاف",
            font=("Tahoma", 10), relief="flat", cursor="hand2",
            padx=12, pady=5, bg="#f3f4f6",
            command=lambda: _set_excuse_bot(False))
        self._wm_exc_off.pack(side="left", padx=(0, 4))
        self._wm_exc_on = tk.Button(exc_row, text="▶  تشغيل",
            font=("Tahoma", 10, "bold"), relief="flat", cursor="hand2",
            padx=12, pady=5, bg="#f3f4f6",
            command=lambda: _set_excuse_bot(True))
        self._wm_exc_on.pack(side="left")

        tk.Frame(inner, bg="white", height=20).pack()

        def _load_initial():
            cfg = load_config()
            try:
                self._wm_refresh_master()
            except Exception:
                pass
            _set_absence_bot(cfg.get("absence_bot_enabled", True))
            _set_permission_bot(cfg.get("permission_bot_enabled", True))
            # جلب حالة بوت الأعذار في خيط خلفي
            def _fetch_excuse():
                try:
                    import wa_evolution as _evo
                    if _evo.provider() == "evolution":
                        # لا خادم محلي في السحابي — الحالة من ملفها الذي يقرؤه البوت
                        _on = _evo.bot_config()["bot_enabled"]
                        self.root.after(0, lambda: _set_excuse_bot(_on))
                        return
                except Exception:
                    pass
                try:
                    import urllib.request as _ur, json as _j
                    r = _ur.urlopen("http://localhost:3000/bot-config", timeout=1)
                    d = _j.loads(r.read())
                    self.root.after(0, lambda: _set_excuse_bot(d.get("bot_enabled", True)))
                except Exception:
                    self.root.after(0, lambda: _set_excuse_bot(True))
            threading.Thread(target=_fetch_excuse, daemon=True).start()

        frame.after(400, _load_initial)
