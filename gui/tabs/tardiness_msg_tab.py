# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os, json, datetime, threading, re, io, csv, base64, time
import sqlite3
from constants import now_riyadh_date, CONFIG_JSON
from config_manager import invalidate_config_cache, load_config, get_terms
from database import get_db, load_students, query_tardiness
from whatsapp_service import send_whatsapp_message
from alerts_service import (claim_daily_message, release_daily_message,
                            message_outcome, DAILY_SKIP_TEXT)

class TardinessMessagesTabMixin:
    """Mixin: TardinessMessagesTabMixin"""
    def _build_tardiness_messages_tab(self):
        frame = self.tardiness_messages_frame

        # ─ رأس
        hdr = tk.Frame(frame, bg="#E65100", height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📲 إرسال رسائل ولي الأمر — المتأخرون",
                 bg="#E65100", fg="white",
                 font=("Tahoma",13,"bold")).pack(side="right", padx=16, pady=12)

        # ─ شريط الأدوات العلوي
        top = ttk.Frame(frame); top.pack(fill="x", padx=10, pady=(8,4))

        ttk.Label(top, text="التاريخ:").pack(side="right", padx=(0,4))
        self.tard_msg_date_var = tk.StringVar(value=now_riyadh_date())
        ttk.Entry(top, textvariable=self.tard_msg_date_var,
                  width=12).pack(side="right", padx=4)
        ttk.Button(top, text="تحميل المتأخرين",
                   command=self._tard_msg_load).pack(side="right", padx=4)
        ttk.Button(top, text="🔍 حالة الواتساب",
                   command=self.check_whatsapp_status_ui).pack(side="right", padx=4)

        self.tard_global_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="اختيار الجميع",
                        variable=self.tard_global_var,
                        command=self._tard_msg_toggle_all).pack(side="right", padx=8)

        self.tard_send_msg_btn = ttk.Button(
            top, text="📤 إرسال للمحددين",
            command=self._tard_msg_send_selected)
        self.tard_send_msg_btn.pack(side="right", padx=4)

        # ── تأخير بين الرسائل لتجنب حظر الواتساب ──────────────────
        delay_row = ttk.Frame(frame); delay_row.pack(fill="x", padx=10, pady=(0,2))
        ttk.Label(delay_row,
                  text="⏱ تأخير بين الرسائل:",
                  font=("Tahoma",9,"bold")).pack(side="right", padx=(0,4))
        cfg_d = load_config()
        self.tard_msg_delay_var = tk.IntVar(value=cfg_d.get("tard_msg_delay_sec", 8))
        ttk.Spinbox(delay_row, from_=1, to=60,
                    textvariable=self.tard_msg_delay_var, width=5).pack(side="right", padx=2)
        ttk.Label(delay_row, text="ثانية بين كل رسالة",
                  foreground="#374151").pack(side="right")
        ttk.Label(delay_row,
                  text="⚠️ القيمة الموصى بها: 8–15 ث لتجنب حظر الرقم",
                  foreground="#E65100", font=("Tahoma",8)).pack(side="left", padx=8)
        ttk.Button(delay_row, text="💾 حفظ",
                   command=self._tard_save_delay_setting).pack(side="left", padx=4)

        # حالة الإرسال
        self.tard_msg_status = ttk.Label(
            frame, text="", foreground="green", font=("Tahoma",10))
        self.tard_msg_status.pack(anchor="e", padx=10)

        # ─ قالب الرسالة (قابل للتعديل)
        tpl_lf = ttk.LabelFrame(frame, text=" ✏️ نص الرسالة ", padding=8)
        tpl_lf.pack(fill="x", padx=10, pady=(0,6))

        tpl_top = ttk.Frame(tpl_lf); tpl_top.pack(fill="x", pady=(0,4))
        ttk.Label(tpl_top,
                  text="المتغيرات: {student_name} {class_name} {date} {minutes_late} {school_name}",
                  foreground="#5A6A7E", font=("Tahoma",9)).pack(side="right")
        ttk.Button(tpl_top, text="حفظ القالب",
                   command=self._tard_msg_save_template).pack(side="left")

        cfg = load_config()
        self.tard_msg_tpl_text = tk.Text(
            tpl_lf, height=5, font=("Tahoma",10), wrap="word")
        self.tard_msg_tpl_text.insert("1.0",
            cfg.get("tardiness_message_template", ""))
        self.tard_msg_tpl_text.pack(fill="x")

        # ─ قائمة المتأخرين
        list_lf = ttk.LabelFrame(
            frame, text=" 📋 المتأخرون ", padding=6)
        list_lf.pack(fill="both", expand=True, padx=10, pady=(0,6))

        cols = ("chk","student_name","class_name","minutes_late",
                "register_time","parent_phone","msg_status")
        self.tree_tard_msg = ttk.Treeview(
            list_lf, columns=cols, show="headings", height=12)
        headers = ["☐","اسم الطالب","الفصل","دقائق التأخر",
                   "وقت التسجيل","جوال ولي الأمر","حالة الرسالة"]
        widths   = [30, 220, 150, 100, 90, 130, 110]
        for col, hdr_t, w in zip(cols, headers, widths):
            self.tree_tard_msg.heading(col, text=hdr_t)
            self.tree_tard_msg.column(col, width=w, anchor="center")

        self.tree_tard_msg.tag_configure("no_phone",  background="#FFEBEE", foreground="#9E9E9E")
        self.tree_tard_msg.tag_configure("has_phone", background="#F5F5F5")
        self.tree_tard_msg.tag_configure("sent_ok",   background="#E8F5E9", foreground="#2E7D32")
        self.tree_tard_msg.tag_configure("sent_fail", background="#FFEBEE", foreground="#C62828")

        sb = ttk.Scrollbar(list_lf, orient="vertical",
                            command=self.tree_tard_msg.yview)
        self.tree_tard_msg.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree_tard_msg.pack(side="left", fill="both", expand=True)
        self.tree_tard_msg.bind("<Button-1>", self._tard_msg_toggle_row)

        # ─ سجل الإرسال
        log_lf = ttk.LabelFrame(frame, text=" 📝 سجل الإرسال ", padding=4)
        log_lf.pack(fill="x", padx=10, pady=(0,8))
        self.tard_msg_log = tk.Text(
            log_lf, height=4, state="disabled",
            font=("Tahoma",9), wrap="word")
        self.tard_msg_log.pack(fill="x")

        self._tard_msg_checked = set()
        self._tard_msg_vars    = {}   # student_id -> BooleanVar
        frame.after(100, self._tard_msg_load)

    def _tard_save_delay_setting(self):
        """يحفظ إعداد التأخير بين رسائل التأخر في الإعدادات."""
        delay = max(1, self.tard_msg_delay_var.get() if hasattr(self, "tard_msg_delay_var") else 8)
        cfg = load_config()
        cfg["tard_msg_delay_sec"] = delay
        with open(CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        invalidate_config_cache()
        messagebox.showinfo("تم", f"✅ تم حفظ التأخير: {delay} ثانية بين كل رسالة")

    def _tard_msg_load(self):
        """يُحمّل المتأخرين لليوم المحدد."""
        if not hasattr(self, "tree_tard_msg"): return
        for i in self.tree_tard_msg.get_children():
            self.tree_tard_msg.delete(i)
        self._tard_msg_checked.clear()
        self._tard_msg_vars.clear()

        date_str = self.tard_msg_date_var.get().strip() if hasattr(self,"tard_msg_date_var") else now_riyadh_date()
        if hasattr(self, "tard_msg_status"):
            self.tard_msg_status.configure(text="جارٍ التحميل...", foreground="gray")

        def _worker():
            rows      = query_tardiness(date_filter=date_str)
            store     = load_students()
            phone_map = {s["id"]: s.get("phone","") for cls in store["list"] for s in cls["students"]}
            sent_map  = self._tard_msg_get_sent_map(date_str)
            self.root.after(0, lambda: self._tard_msg_fill(rows, phone_map, sent_map, date_str))

        threading.Thread(target=_worker, daemon=True).start()

    def _tard_msg_fill(self, rows, phone_map, sent_map, date_str):
        """يملأ الجدول بعد انتهاء التحميل في الخلفية."""
        if not hasattr(self, "tree_tard_msg"): return
        for i in self.tree_tard_msg.get_children():
            self.tree_tard_msg.delete(i)
        self._tard_msg_checked.clear()

        if not rows:
            self.tard_msg_status.configure(
                text="لا يوجد متأخرون بتاريخ {}".format(date_str),
                foreground="orange")
            return

        count = 0
        for r in rows:
            sid       = r["student_id"]
            phone     = phone_map.get(sid, "")
            mins      = r.get("minutes_late", 0)
            reg_time  = r.get("created_at","")[:5] if r.get("created_at") else ""
            sent_stat = sent_map.get(sid, "")

            tag = ("sent_ok"   if sent_stat == "تم الإرسال" else
                   "sent_fail" if "فشل" in sent_stat        else
                   "no_phone"  if not phone                  else
                   "has_phone")

            self.tree_tard_msg.insert(
                "", "end", iid=sid, tags=(tag,),
                values=("☐", r["student_name"], r.get("class_name",""),
                        "{} دقيقة".format(mins), reg_time,
                        phone or "— لا يوجد رقم",
                        sent_stat or ""))
            count += 1

        self.tard_msg_status.configure(
            text="{} متأخر — {} لديهم رقم جوال".format(
                count, sum(1 for r in rows if phone_map.get(r["student_id"]))),
            foreground="#1565C0")

    def _tard_msg_get_sent_map(self, date_str: str) -> dict:
        """
        أفضل نتيجة اليوم لكل طالب من سجلّ الرسائل: «تم الإرسال» ثم «لم يُتأكد»
        ثم آخر فشل. الويب يكتب Success/Failed والمكتبي «تم الإرسال»/«فشل: …».
        """
        try:
            con = get_db()
            con.row_factory = sqlite3.Row; cur = con.cursor()
            cur.execute("""SELECT * FROM messages_log
                           WHERE date=? AND message_type='tardiness' ORDER BY id""",
                        (date_str,))
            rank = {"sent": 3, "unsure": 2, "legacy": 1, "failed": 0}
            best = {}
            for r in cur.fetchall():
                r = dict(r)
                o = message_outcome(r.get("status"), r.get("detail"))
                sid = r["student_id"]
                if sid in best and rank[best[sid][0]] > rank[o]:
                    continue
                label = {"sent": "تم الإرسال", "unsure": "لم يُتأكد"}.get(
                    o, str(r.get("status") or ""))
                if o == "failed" and "فشل" not in label:
                    label = "فشل: " + str(r.get("detail") or label)
                best[sid] = (o, label)
            con.close()
            return {sid: lab for sid, (_o, lab) in best.items()}
        except Exception:
            return {}

    def _tard_msg_toggle_row(self, event):
        region = self.tree_tard_msg.identify("region", event.x, event.y)
        if region != "cell": return
        col = self.tree_tard_msg.identify_column(event.x)
        if col != "#1": return
        iid = self.tree_tard_msg.identify_row(event.y)
        if not iid: return
        if iid in self._tard_msg_checked:
            self._tard_msg_checked.discard(iid)
            vals = list(self.tree_tard_msg.item(iid,"values"))
            vals[0] = "☐"
            self.tree_tard_msg.item(iid, values=vals)
        else:
            self._tard_msg_checked.add(iid)
            vals = list(self.tree_tard_msg.item(iid,"values"))
            vals[0] = "☑"
            self.tree_tard_msg.item(iid, values=vals)

    def _tard_msg_toggle_all(self):
        checked = self.tard_global_var.get()
        for iid in self.tree_tard_msg.get_children():
            vals = list(self.tree_tard_msg.item(iid,"values"))
            vals[0] = "☑" if checked else "☐"
            self.tree_tard_msg.item(iid, values=vals)
            if checked: self._tard_msg_checked.add(iid)
            else:        self._tard_msg_checked.discard(iid)

    def _tard_msg_save_template(self):
        tpl = self.tard_msg_tpl_text.get("1.0","end").strip()               if hasattr(self,"tard_msg_tpl_text") else ""
        if not tpl: return
        cfg = load_config()
        cfg["tardiness_message_template"] = tpl
        with open(CONFIG_JSON,"w",encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("تم","تم حفظ قالب رسالة التأخر")

    def _tard_msg_send_selected(self):
        if not self._tard_msg_checked:
            messagebox.showwarning("تنبيه","حدد طلاباً أولاً"); return

        date_str = self.tard_msg_date_var.get().strip()                    if hasattr(self,"tard_msg_date_var") else now_riyadh_date()
        from alerts_service import is_message_day, NOT_TODAY_MSG
        if not is_message_day(date_str):
            messagebox.showwarning("تنبيه", NOT_TODAY_MSG); return
        cfg      = load_config()
        school   = cfg.get("school_name","المدرسة")
        tpl      = cfg.get("tardiness_message_template","")
        store    = load_students()
        phone_map = {s["id"]: s.get("phone","")
                     for cls in store["list"] for s in cls["students"]}
        tard_rows = {r["student_id"]: r
                     for r in query_tardiness(date_filter=date_str)}

        if not messagebox.askyesno("تأكيد",
            "إرسال رسائل التأخر لـ {} طالب؟".format(
                len(self._tard_msg_checked))):
            return

        self.tard_send_msg_btn.configure(state="disabled")
        self.root.update_idletasks()

        def do_send():
            ok_cnt = fail_cnt = skip_cnt = 0
            sent_once = False
            for sid in list(self._tard_msg_checked):
                row   = tard_rows.get(sid)
                phone = phone_map.get(sid,"")
                if not row:
                    skip_cnt += 1; continue
                if not phone:
                    skip_cnt += 1
                    self._tard_msg_log_append("⚠️ {} — لا يوجد رقم جوال".format(
                        row.get("student_name",sid)))
                    self._tard_msg_update_row(sid, "لا يوجد رقم")
                    continue
                # رسالة تأخر واحدة في اليوم لكل طالب — أياً كان مُرسِلها
                # (الويب أو هذا التبويب أو جهاز البصمة)؛ انظر alerts_service
                why = claim_daily_message(date_str, sid, "tardiness")
                if why:
                    skip_cnt += 1
                    self._tard_msg_log_append("⏭ {} — {}".format(
                        row.get("student_name", sid), DAILY_SKIP_TEXT.get(why, why)))
                    if why == "sent":
                        self._tard_msg_update_row(sid, "تم الإرسال", "sent_ok")
                    continue
                if sent_once:
                    # ── تأخير بين الرسائل لتجنب حظر الواتساب ──
                    delay_sec = self.tard_msg_delay_var.get() if hasattr(self, "tard_msg_delay_var") else 8
                    try:
                        import wa_limits
                        # التباعد المتصاعد أهم من رقم ثابت يختاره المستخدم
                        delay_sec = max(delay_sec, wa_limits.next_delay())
                    except Exception:
                        pass
                    time.sleep(max(1, delay_sec))
                sent_once = True
                outcome = "failed"
                try:
                    try:
                        mins = row.get("minutes_late",0)
                        from config_manager import render_template
                        msg  = render_template(
                            tpl,
                            student_name=row.get("student_name",""),
                            class_name=row.get("class_name",""),
                            date=date_str, minutes_late=mins)
                    except Exception:
                        _t = get_terms()
                        mins = row.get("minutes_late",0)
                        msg = "تنبيه: {late_v} {son} {} دقيقة بتاريخ {}".format(
                            row.get("minutes_late",0), date_str,
                            late_v=_t["late_v"], son=_t["son"])

                    try:
                        ok, status = send_whatsapp_message(phone, msg)
                    except Exception as e:
                        ok, status = False, "حدث خطأ غير متوقع أثناء الإرسال: {}".format(e)
                    log_status = "تم الإرسال" if ok else "فشل: {}".format(status)
                    outcome = "sent" if ok else message_outcome(log_status)

                    # سجّل في message_log — قبل فكّ الحجز، فلا تُعيدها حلقةٌ أخرى
                    try:
                        created = datetime.datetime.utcnow().isoformat()
                        con = get_db(); cur = con.cursor()
                        cur.execute("""INSERT INTO messages_log
                            (date,student_id,student_name,class_id,class_name,
                             phone,status,template_used,message_type,created_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (date_str, sid,
                             row.get("student_name",""),
                             row.get("class_id",""),
                             row.get("class_name",""),
                             phone, log_status, msg, "tardiness", created))
                        con.commit(); con.close()
                    except Exception: pass
                finally:
                    release_daily_message(date_str, sid, "tardiness",
                                          outcome if outcome != "legacy" else "failed")

                if ok:
                    ok_cnt += 1
                    self._tard_msg_log_append(
                        "✅ {} ({} دقيقة)".format(
                            row.get("student_name",""), mins))
                    self._tard_msg_update_row(sid, "تم الإرسال", "sent_ok")
                else:
                    fail_cnt += 1
                    short_err = status[:40] if len(status) > 40 else status
                    self._tard_msg_log_append(
                        "❌ {} — {}".format(
                            row.get("student_name",""), status))
                    self._tard_msg_update_row(sid, short_err, "sent_fail")

            summary = "اكتمل — نجح: {} | فشل: {} | تخطّى: {}".format(
                ok_cnt, fail_cnt, skip_cnt)
            self.root.after(0, lambda: (
                self.tard_msg_status.configure(
                    text=summary,
                    foreground="green" if fail_cnt==0 else "orange"),
                self.tard_send_msg_btn.configure(state="normal"),
                messagebox.showinfo("نتيجة الإرسال", summary)
            ))

        threading.Thread(target=do_send, daemon=True).start()

    def _tard_msg_log_append(self, msg: str):
        def _do():
            if not hasattr(self,"tard_msg_log"): return
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.tard_msg_log.configure(state="normal")
            self.tard_msg_log.insert("end","[{}] {}\n".format(ts, msg))
            self.tard_msg_log.see("end")
            self.tard_msg_log.configure(state="disabled")
        self.root.after(0, _do)

    def _tard_msg_update_row(self, iid: str, status: str, tag: str = ""):
        def _do():
            if not self.tree_tard_msg.exists(iid): return
            vals = list(self.tree_tard_msg.item(iid,"values"))
            vals[-1] = status
            self.tree_tard_msg.item(iid, values=vals,
                                     tags=(tag,) if tag else ())
        self.root.after(0, _do)

    # ══════════════════════════════════════════════════════════
    # تبويب الإشعارات الذكية
    # ══════════════════════════════════════════════════════════
