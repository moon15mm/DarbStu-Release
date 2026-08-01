# -*- coding: utf-8 -*-
"""
gui/tabs/circulars_tab.py — تبويب التعاميم والنشرات
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os, threading, webbrowser, datetime
from database import create_circular, get_circulars, mark_circular_as_read
from constants import CURRENT_USER, DATA_DIR, PORT, local_ip
from config_manager import load_config

class CircularsTabMixin:
    """Mixin لتبويب التعاميم والنشرات."""
    
    def _build_circulars_tab(self):
        self.circulars_frame.config(bg="#f8f9fa")
        
        # ─── الحاوية العلوية (العنوان + زر الإضافة للمدير) ─────────
        header = tk.Frame(self.circulars_frame, bg="#f8f9fa", pady=10)
        header.pack(fill="x", padx=15)
        
        tk.Label(header, text="📋 التعاميم والنشرات", font=("Tahoma", 14, "bold"), 
                 bg="#f8f9fa", fg="#1565C0").pack(side="right")
        
        if CURRENT_USER.get("role") == "admin":
            tk.Button(header, text="➕ تعميم جديد", bg="#2E7D32", fg="white", 
                      font=("Tahoma", 10, "bold"), relief="flat", padx=15,
                      command=self._open_new_circular_dialog).pack(side="left")
            
            tk.Button(header, text="🗑️ حذف تعميم", bg="#C62828", fg="white", 
                      font=("Tahoma", 10, "bold"), relief="flat", padx=15,
                      command=self._delete_circular).pack(side="left", padx=8)

        # ─── الجسم الرئيسي (قائمة التعاميم + العرض) ──────────────
        body = tk.Frame(self.circulars_frame, bg="white")
        body.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        # القائمة (الطرف الأيمن)
        list_fr = tk.Frame(body, bg="#f1f3f5", width=350)
        list_fr.pack(side="right", fill="y")
        list_fr.pack_propagate(False)
        
        tk.Label(list_fr, text="آخر التعاميم", font=("Tahoma", 9, "bold"), 
                 bg="#e9ecef", pady=8).pack(fill="x")
        
        cols = ("id", "date", "title", "status")
        self.circ_tree = ttk.Treeview(list_fr, columns=cols, show="headings", selectmode="browse")
        self.circ_tree.heading("id", text="ID")
        self.circ_tree.heading("date", text="التاريخ")
        self.circ_tree.heading("title", text="العنوان")
        self.circ_tree.heading("status", text="الحالة")
        
        self.circ_tree.column("id", width=0, stretch=False)
        self.circ_tree.column("date", width=80, anchor="center")
        self.circ_tree.column("title", width=180, anchor="e")
        self.circ_tree.column("status", width=60, anchor="center")
        
        self.circ_tree.pack(fill="both", expand=True)
        self.circ_tree.bind("<<TreeviewSelect>>", self._on_circular_select)
        
        # منطقة العرض (الطرف الأيسر)
        self.circ_view_fr = tk.Frame(body, bg="white", padx=20, pady=20)
        self.circ_view_fr.pack(side="left", fill="both", expand=True)
        
        self.circ_title_lbl = tk.Label(self.circ_view_fr, text="اختر تعميماً لعرضه", 
                                       font=("Tahoma", 13, "bold"), bg="white", fg="#333")
        self.circ_title_lbl.pack(anchor="e", pady=(0, 5))
        
        self.circ_info_lbl = tk.Label(self.circ_view_fr, text="", font=("Tahoma", 9), 
                                      bg="white", fg="#666")
        self.circ_info_lbl.pack(anchor="e", pady=(0, 15))
        
        tk.Frame(self.circ_view_fr, bg="#eee", height=1).pack(fill="x", pady=(0, 15))
        
        # محتوى النص (باستخدام Text widget)
        self.circ_text = tk.Text(self.circ_view_fr, font=("Tahoma", 11), bg="white", 
                                 relief="flat", height=12, padx=10, pady=10)
        self.circ_text.pack(fill="both", expand=True)
        self.circ_text.config(state="disabled")
        
        # قسم المرفقات
        self.circ_attach_fr = tk.Frame(self.circ_view_fr, bg="#f8f9fa", pady=10, padx=10)
        self.circ_attach_fr.pack(fill="x", pady=(15, 0))
        
        self.attach_btn = tk.Button(self.circ_attach_fr, text="📎 فتح المرفق (PDF/صورة)", 
                                   bg="#0277BD", fg="white", font=("Tahoma", 10, "bold"),
                                   relief="flat", state="disabled", command=self._open_attachment)
        self.attach_btn.pack(side="right")
        
        self._refresh_circulars_list()

    def _refresh_circulars_list(self):
        """تحديث قائمة التعاميم."""
        for i in self.circ_tree.get_children():
            self.circ_tree.delete(i)
            
        circs = get_circulars(username=CURRENT_USER.get("username"), role=CURRENT_USER.get("role"))
        
        for c in circs:
            status = "مقروء" if c.get("is_read") else "جديد"
            if CURRENT_USER.get("role") == "admin":
                status = f"{c.get('read_count', 0)} مشاهدة"
                
            tags = ("new",) if not c.get("is_read") and CURRENT_USER.get("role") != "admin" else ()
            
            self.circ_tree.insert("", "end", values=(c["id"], c["date"], c["title"], status), tags=tags)
        
        self.circ_tree.tag_configure("new", font=("Tahoma", 9, "bold"), foreground="#C62828")

    def _on_circular_select(self, event):
        sel = self.circ_tree.selection()
        if not sel: return
        
        cid = self.circ_tree.item(sel[0])["values"][0]
        # جلب البيانات الكاملة من القائمة (أو إعادة طلبها إذا أردنا)
        circs = get_circulars(username=CURRENT_USER.get("username"), role=CURRENT_USER.get("role"))
        c = next((x for x in circs if x["id"] == cid), None)
        
        if not c: return
        
        self.current_selected_circular = c
        self.circ_title_lbl.config(text=c["title"])
        self.circ_info_lbl.config(text=f"التاريخ: {c['date']}  |  بواسطة: {c['created_by']}")
        
        self.circ_text.config(state="normal")
        self.circ_text.delete("1.0", "end")
        self.circ_text.insert("end", c.get("content", ""))
        self.circ_text.config(state="disabled")
        
        if c.get("attachment_path"):
            self.attach_btn.config(state="normal", bg="#0277BD")
        else:
            self.attach_btn.config(state="disabled", bg="#ccc")
            
        # تحديث حالة القراءة
        if not c.get("is_read") and CURRENT_USER.get("role") != "admin":
            mark_circular_as_read(cid, CURRENT_USER.get("username"))
            # تحديث الحالة في القائمة فوراً
            self.circ_tree.item(sel[0], values=(c["id"], c["date"], c["title"], "مقروء"), tags=())

    def _open_attachment(self):
        c = getattr(self, "current_selected_circular", None)
        if not c or not c.get("attachment_path"): return
        
        path = c["attachment_path"] # مثال: attachments/circulars/file.pdf
        
        from database import get_cloud_client
        client = get_cloud_client()
        
        if client.is_active():
            # في وضع السحاب، نفتح الرابط عبر المتصفح
            url = f"{client.url}/web/api/circulars/attachment/{os.path.basename(path)}"
            webbrowser.open(url)
        else:
            # في الوضع المحلي، نفتح الملف مباشرة
            fpath = os.path.join(DATA_DIR, path)
            if os.path.exists(fpath):
                os.startfile(fpath)
            else:
                messagebox.showerror("خطأ", "لم يتم العثور على الملف.")

    def _open_new_circular_dialog(self):
        """نافذة المدير لإنشاء تعميم جديد."""
        dialog = tk.Toplevel(self.root)
        dialog.title("إرسال تعميم جديد")
        dialog.geometry("500x550")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        
        container = tk.Frame(dialog, padx=20, pady=20)
        container.pack(fill="both", expand=True)
        
        tk.Label(container, text="عنوان التعميم:", font=("Tahoma", 10, "bold")).pack(anchor="e")
        title_var = tk.StringVar()
        tk.Entry(container, textvariable=title_var, font=("Tahoma", 11), justify="right").pack(fill="x", pady=(5, 15))
        
        tk.Label(container, text="نص التعميم / الملاحظات:", font=("Tahoma", 10, "bold")).pack(anchor="e")
        content_txt = tk.Text(container, font=("Tahoma", 10), height=8, padx=5, pady=5)
        content_txt.pack(fill="x", pady=(5, 15))
        
        tk.Label(container, text="الفئة المستهدفة:", font=("Tahoma", 10, "bold")).pack(anchor="e")
        role_var = tk.StringVar(value="all")
        role_combo = ttk.Combobox(container, textvariable=role_var, state="readonly", values=["all", "teacher", "deputy", "counselor"])
        role_combo.pack(fill="x", pady=(5, 15))
        
        tk.Label(container, text="المرفق (PDF أو صورة):", font=("Tahoma", 10, "bold")).pack(anchor="e")
        file_path_var = tk.StringVar()
        file_row = tk.Frame(container)
        file_row.pack(fill="x", pady=(5, 20))
        tk.Entry(file_row, textvariable=file_path_var, font=("Tahoma", 9), state="readonly").pack(side="right", fill="x", expand=True)
        
        def choose_file():
            p = filedialog.askopenfilename(title="اختر ملف المرفق", filetypes=[("Attachment Files", "*.pdf *.png *.jpg *.jpeg")])
            if p: file_path_var.set(p)
            
        tk.Button(file_row, text="اختر ملف...", command=choose_file).pack(side="left")
        
        def save():
            title = title_var.get().strip()
            if not title:
                messagebox.showwarning("تنبيه", "يجب إدخل عنوان للتعميم.")
                return
            
            data = {
                "title": title,
                "content": content_txt.get("1.0", "end").strip(),
                "target_role": role_var.get(),
                "created_by": CURRENT_USER.get("name") or CURRENT_USER.get("username"),
                "date": datetime.datetime.now().strftime("%Y-%m-%d")
            }
            
            fpath = file_path_var.get()
            if fpath:
                # التحقق من حجم الملف (10 ميجابايت)
                if os.path.getsize(fpath) > 10 * 1024 * 1024:
                    messagebox.showerror("خطأ", "حجم الملف كبير جداً (الحد الأقصى 10 ميجا).")
                    return
                
                from database import get_cloud_client
                client = get_cloud_client()
                if not client.is_active():
                    circ_dir = os.path.join(DATA_DIR, "attachments", "circulars")
                    os.makedirs(circ_dir, exist_ok=True)
                    fext = os.path.splitext(fpath)[1]
                    fname = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}{fext}"
                    dest = os.path.join(circ_dir, fname)
                    import shutil
                    shutil.copy2(fpath, dest)
                    data["attachment_path"] = os.path.join("attachments", "circulars", fname)
                else:
                    try:
                        import requests
                        with open(fpath, "rb") as f:
                            files = {"file": f}
                            resp = requests.post(f"{client.url}/web/api/circulars/create", 
                                                data={"title": data["title"], "content": data["content"], 
                                                      "target_role": data["target_role"]},
                                                files=files, headers={"Authorization": f"Bearer {client.token}"})
                        if resp.status_code == 200:
                            messagebox.showinfo("تم", "تم إرسال التعميم بنجاح للسيرفر.")
                            self._refresh_circulars_list()
                            dialog.destroy()
                        else:
                            messagebox.showerror("خطأ", f"فشل الإرسال: {resp.text}")
                        return
                    except Exception as e:
                        messagebox.showerror("خطأ", f"فشل الاتصال: {e}")
                        return
            
            create_circular(data)
            messagebox.showinfo("تم", "تم حفظ التعميم بنجاح.")
            self._refresh_circulars_list()
            dialog.destroy()
            
        tk.Button(container, text="إرسال وحفظ التعميم", bg="#1565C0", fg="white", 
                  font=("Tahoma", 11, "bold"), pady=8, command=save).pack(fill="x")

    def _delete_circular(self):
        """حذف التعميم المحدد من قبل المدير."""
        from database import authenticate
        from constants import CURRENT_USER
        from tkinter import simpledialog
        sel = self.circ_tree.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "يرجى اختيار تعميم لحذفه أولاً.")
            return
        
        cid = self.circ_tree.item(sel[0])["values"][0]
        title = self.circ_tree.item(sel[0])["values"][2]
        
        if not messagebox.askyesno("تأكيد الحذف", f"هل أنت متأكد من حذف التعميم: '{title}'؟\nلا يمكن التراجع عن هذه الخطوة."):
            return

        pw = simpledialog.askstring("تأكيد الهوية", "أدخل كلمة مرور حسابك لتأكيد الحذف:", show="*")
        if not pw: return
        if authenticate(CURRENT_USER.get("username"), pw) is None:
            messagebox.showerror("خطأ", "كلمة المرور غير صحيحة.")
            return
        
        from database import delete_circular
        delete_circular(cid)
        messagebox.showinfo("تم", "تم حذف التعميم بنجاح.")
        self._refresh_circulars_list()
        
        # تصفير منطقة العرض
        self.circ_title_lbl.config(text="اختر تعميماً لعرضه")
        self.circ_info_lbl.config(text="")
        self.circ_text.config(state="normal")
        self.circ_text.delete("1.0", "end")
        self.circ_text.config(state="disabled")
        self.attach_btn.config(state="disabled", bg="#ccc")
