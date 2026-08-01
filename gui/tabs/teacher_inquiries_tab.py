# -*- coding: utf-8 -*-
"""
teacher_inquiries_tab.py — تبويب خطابات الاستفسار الأكاديمي للمعلم
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import datetime, os
from database import get_academic_inquiries, reply_academic_inquiry, get_academic_inquiry
from constants import CURRENT_USER

class TeacherInquiriesTabMixin:
    """Mixin: خطابات الاستفسار للمعلم"""

    def _build_teacher_inquiries_tab(self):
        """ينشئ تبويب خطابات الاستفسار للمعلم المحدّد."""
        frame = self.teacher_inquiries_frame

        # رأس التبويب
        hdr = tk.Frame(frame, bg="#4c1d95", height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="✉ خطابات الاستفسار الأكاديمي",
                 bg="#4c1d95", fg="white",
                 font=("Tahoma", 14, "bold")).pack(side="right", padx=20, pady=15)

        # شريط وصفي وزر التحميل
        info = tk.Frame(frame, bg="#ede9fe", pady=8)
        info.pack(fill="x")
        tk.Label(info, text="استعرض خطابات الاستفسار الموجهة إليك من الموجه الطلابي، وانقر نقراً مزدوجاً للرد عليها.",
                 bg="#ede9fe", font=("Tahoma", 10), fg="#4c1d95").pack(side="right", padx=20)
        
        tk.Button(info, text="🔄 تحديث القائمة", bg="#6d28d9", fg="white", font=("Tahoma", 9, "bold"),
                  relief="flat", cursor="hand2", padx=10, command=self._refresh_teacher_inquiries).pack(side="left", padx=20)

        # جدول الخطابات
        list_fr = tk.Frame(frame, bg="white")
        list_fr.pack(fill="both", expand=True, padx=20, pady=20)

        cols = ("id", "date", "counselor", "class", "subject", "student", "status")
        self._tch_inq_tree = ttk.Treeview(list_fr, columns=cols, show="headings", height=20)
        
        headings = {
            "id": ("المعرف", 50),
            "date": ("التاريخ", 90),
            "counselor": ("الموجه الطلابي", 150),
            "class": ("الفصل", 100),
            "subject": ("المادة", 120),
            "student": ("الطالب", 150),
            "status": ("الحالة", 80)
        }
        for c, (txt, w) in headings.items():
            self._tch_inq_tree.heading(c, text=txt)
            self._tch_inq_tree.column(c, width=w, anchor="center")

        sb = ttk.Scrollbar(list_fr, orient="vertical", command=self._tch_inq_tree.yview)
        self._tch_inq_tree.configure(yscrollcommand=sb.set)
        
        sb.pack(side="right", fill="y")
        self._tch_inq_tree.pack(side="left", fill="both", expand=True)

        self._tch_inq_tree.tag_configure("جديد", foreground="red", background="#fff0f0")
        self._tch_inq_tree.tag_configure("تم الرد", foreground="green", background="#f0fff0")

        self._tch_inq_tree.bind("<Double-1>", self._on_teacher_inquiry_dlbclick)
        
        # جلب البيانات
        self.root.after(200, self._refresh_teacher_inquiries)

    def _refresh_teacher_inquiries(self):
        """يحدث القائمة بالخادم (استفسارات هذا المعلم فقط)."""
        if not hasattr(self, "_tch_inq_tree"):
            return
        
        for item in self._tch_inq_tree.get_children():
            self._tch_inq_tree.delete(item)
            
        me = CURRENT_USER.get("name", CURRENT_USER.get("username", ""))
        
        try:
            # نجلب كل الاستفسارات ثم نفلتر للمعلم الحالي
            rows = get_academic_inquiries()
            for r in rows:
                if r.get("teacher_name") == me or r.get("teacher_name") == CURRENT_USER.get("username"):
                    st = r.get("status", "جديد")
                    self._tch_inq_tree.insert("", "end", values=(
                        r["id"], r.get("inquiry_date", ""),
                        r.get("counselor_name", ""),
                        r.get("class_name", ""), r.get("subject", ""),
                        r.get("student_name", ""), st
                    ), tags=(st,))
        except Exception as e:
            print("[Teacher Inquiries] Error loading:", e)

    def _on_teacher_inquiry_dlbclick(self, event=None):
        sel = self._tch_inq_tree.selection()
        if not sel: return
        inq_id = self._tch_inq_tree.item(sel[0])["values"][0]
        
        try:
            data = get_academic_inquiry(inq_id)
        except:
            messagebox.showerror("خطأ", "فشل في جلب الاستفسار.", parent=self.root)
            return

        win = tk.Toplevel(self.root)
        win.title("💬 رد المعلم على الاستفسار")
        win.geometry("650x700")
        win.configure(bg="#f4f4f5")
        win.grab_set()

        # بيانات الاستفسار
        info = tk.LabelFrame(win, text=" بيانات الاستفسار ", bg="#f4f4f5", font=("Tahoma", 10, "bold"), fg="#4c1d95")
        info.pack(fill="x", padx=15, pady=10)

        tk.Label(info, text=f"الطالب: {data.get('student_name','')}", bg="#f4f4f5", font=("Tahoma", 10)).grid(row=0, column=1, sticky="e", padx=10, pady=5)
        tk.Label(info, text=f"الفصل: {data.get('class_name','')}", bg="#f4f4f5", font=("Tahoma", 10)).grid(row=0, column=0, sticky="e", padx=10, pady=5)
        tk.Label(info, text=f"المادة: {data.get('subject','')}", bg="#f4f4f5", font=("Tahoma", 10)).grid(row=1, column=1, sticky="e", padx=10, pady=5)
        tk.Label(info, text=f"الموجه: {data.get('counselor_name','')}", bg="#f4f4f5", font=("Tahoma", 10)).grid(row=1, column=0, sticky="e", padx=10, pady=5)
        
        info.columnconfigure(0, weight=1)
        info.columnconfigure(1, weight=1)

        # الرد
        reply_fr = tk.LabelFrame(win, text=" إفادة المعلم عن مستوى الطالب ", bg="white", font=("Tahoma", 10, "bold"), fg="#111827")
        reply_fr.pack(fill="both", expand=True, padx=15, pady=10)

        # اختيار مستوى الطالب
        type_fr = tk.Frame(reply_fr, bg="white")
        type_fr.pack(fill="x", padx=10, pady=(10, 5))
        tk.Label(type_fr, text="مستوى الطالب في المادة:", bg="white", font=("Tahoma", 10, "bold"), fg="#4c1d95").pack(side="right", padx=(0, 5))
        inq_type_var = tk.StringVar(value=data.get("inquiry_type", ""))
        inq_type_cb = ttk.Combobox(type_fr, textvariable=inq_type_var,
                                    values=["تحسن ملحوظ", "تدني ملحوظ"], state="readonly", width=20, font=("Tahoma", 10))
        inq_type_cb.pack(side="right", padx=5)
        
        tk.Label(reply_fr, text="الأسباب والإجراءات المتخذة:", bg="white", font=("Tahoma", 9)).pack(anchor="e", padx=10, pady=(10, 5))
        
        reason_txt = tk.Text(reply_fr, height=10, font=("Tahoma", 11), relief="groove")
        reason_txt.pack(fill="both", expand=True, padx=10, pady=5)
        if data.get("teacher_reply_reasons"):
            reason_txt.insert("1.0", data["teacher_reply_reasons"])
            
        tk.Label(reply_fr, text="الشواهد (اختياري - روابط أو نصوص):", bg="white", font=("Tahoma", 9)).pack(anchor="e", padx=10, pady=(10, 5))
        ev_txt = tk.Text(reply_fr, height=4, font=("Tahoma", 11), relief="groove")
        ev_txt.pack(fill="x", padx=10, pady=5)
        if data.get("teacher_reply_evidence"):
            ev_txt.insert("1.0", data["teacher_reply_evidence"])

        # أزرار الإجراء
        btn_fr = tk.Frame(win, bg="#e2e8f0", pady=10)
        btn_fr.pack(fill="x", side="bottom")

        def _preview():
            from pdf_generator import generate_academic_inquiry_pdf
            # ندمج الرد الحالي للمعاينة
            data_copy = dict(data)
            data_copy["reasons"] = reason_txt.get("1.0", "end-1c").strip()
            data_copy["evidence_text"] = ev_txt.get("1.0", "end-1c").strip()
            data_copy["status"] = "تم الرد" if data_copy["reasons"] else data_copy["status"]
            try:
                pdf_b = generate_academic_inquiry_pdf(data_copy)
                import tempfile
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="inquiry_")
                tmp.write(pdf_b); tmp.close()
                if os.name == "nt": os.startfile(tmp.name)
            except Exception as e:
                messagebox.showerror("خطأ", f"خطأ توليد الـ PDF:\n{e}", parent=win)
                
        def _save():
            r = reason_txt.get("1.0", "end-1c").strip()
            ev = ev_txt.get("1.0", "end-1c").strip()
            if not r:
                messagebox.showwarning("تنبيه", "يجب كتابة مبررات أولاً.", parent=win)
                return
            
            chosen_type = inq_type_var.get().strip()
            if not chosen_type:
                messagebox.showwarning("تنبيه", "يجب اختيار مستوى الطالب (تحسن ملحوظ / تدني ملحوظ).", parent=win)
                return
            
            payload = {
                "reasons": r,
                "evidence": ev,
                "inquiry_type": chosen_type
            }
            try:
                reply_academic_inquiry(inq_id, payload)
                messagebox.showinfo("✅ نجاح", "تم حفظ الإفادة بنجاح والرد على الموجه.", parent=win)
                self._refresh_teacher_inquiries()
                win.destroy()
            except Exception as e:
                messagebox.showerror("خطأ", f"فشل الحفظ: {e}", parent=win)

        tk.Button(btn_fr, text=" حفظ وإرسال الرد", bg="#059669", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=20, pady=6, command=_save).pack(side="right", padx=15)
        
        tk.Button(btn_fr, text="🖨️ معاينة الملف (PDF)", bg="#1d4ed8", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=15, pady=6, command=_preview).pack(side="right", padx=5)
        
        tk.Button(btn_fr, text="إلغاء", bg="#94a3b8", fg="white", font=("Tahoma", 10, "bold"),
                  relief="flat", cursor="hand2", padx=15, pady=6, command=win.destroy).pack(side="right", padx=5)
