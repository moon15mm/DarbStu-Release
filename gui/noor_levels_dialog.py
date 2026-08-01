# -*- coding: utf-8 -*-
"""
nooor_levels_dialog — نافذة ترميز صفوف نور.

نور يُصدّر «رقم الصف» كرمز خام (1314، 1518 ...) يختلف بين المدارس
والمسارات، ولا يذكر في الملف ما يقابله من صفوف. كان الحل السابق أن
يحرّر المزوّد ملف JSON يدوياً — وهو حلّ مبرمج لا مستخدم، ولا يظهر
أصلاً في النسخة المبنية بلا نافذة أوامر.

هذه النافذة تعرض كل رمز لم يفهمه النظام ومعه عدد طلابه وفصوله،
ليختار له المزوّد صفّه من قائمة، أو يستبعده إن كانوا منتسبين.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from database import (noor_level_options, set_noor_level_mapping,
                      set_noor_exclude, get_school_stage)

EXCLUDE_LABEL = "🚫 استبعاد (انتساب)"
SKIP_LABEL = "— اتركه كما هو —"


def resolve_noor_levels(parent, unknown: dict) -> bool:
    """
    تعرض نافذة الترميز. تُرجع True إذا غيّر المستخدم شيئاً يستوجب
    إعادة الاستيراد.

    unknown: {"1518": {"name": ..., "count": 12, "sections": ["A","B"]}}
    """
    if not unknown:
        return False

    stage = get_school_stage()
    options = noor_level_options(stage)
    choice_values = [SKIP_LABEL] + [n for _d, n in options] + [EXCLUDE_LABEL]
    name_to_digit = {n: d for d, n in options}

    win = tk.Toplevel(parent)
    win.title("ترميز صفوف نور")
    win.configure(bg="white")
    win.transient(parent)
    win.grab_set()
    win.resizable(True, True)

    hdr = tk.Frame(win, bg="#E65100", height=52)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="🏫 ترميز صفوف نور", bg="#E65100", fg="white",
             font=("Tahoma", 13, "bold")).pack(side="right", padx=16, pady=12)

    tk.Label(win, bg="white", fg="#444", justify="right", anchor="e",
             font=("Tahoma", 10), wraplength=620,
             text=(f"مرحلة المدرسة: {stage}\n"
                   "لم يتعرّف النظام على الرموز التالية في ملف نور. "
                   "اختر لكل رمز صفَّه الصحيح، أو استبعده إن كان طلابه "
                   "منتسبين.\nما تتركه دون اختيار يبقى في مستوى مستقل "
                   "باسم «صف غير معرّف»."),
             ).pack(fill="x", padx=16, pady=(12, 8))

    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=16)

    ttk.Label(body, text="الرمز", font=("Tahoma", 10, "bold"),
              anchor="center", width=12).grid(row=0, column=3, padx=4, pady=6)
    ttk.Label(body, text="الطلاب", font=("Tahoma", 10, "bold"),
              anchor="center", width=8).grid(row=0, column=2, padx=4, pady=6)
    ttk.Label(body, text="الفصول", font=("Tahoma", 10, "bold"),
              anchor="center", width=14).grid(row=0, column=1, padx=4, pady=6)
    ttk.Label(body, text="الصف الصحيح", font=("Tahoma", 10, "bold"),
              anchor="center", width=22).grid(row=0, column=0, padx=4, pady=6)

    rows = []
    for i, code in enumerate(sorted(unknown), start=1):
        info = unknown[code] or {}
        secs = info.get("sections") or []
        tk.Label(body, text=str(code), bg="white", font=("Tahoma", 11, "bold"),
                 fg="#B71C1C", width=12).grid(row=i, column=3, padx=4, pady=3)
        tk.Label(body, text=str(info.get("count", 0)), bg="white",
                 font=("Tahoma", 11), width=8).grid(row=i, column=2, padx=4, pady=3)
        tk.Label(body, text="، ".join(secs) or "—", bg="white",
                 font=("Tahoma", 10), width=14).grid(row=i, column=1, padx=4, pady=3)
        var = tk.StringVar(value=SKIP_LABEL)
        cb = ttk.Combobox(body, textvariable=var, values=choice_values,
                          state="readonly", width=22, justify="right")
        cb.grid(row=i, column=0, padx=4, pady=3)
        rows.append((str(code), var))

    changed = {"v": False}

    def _save():
        used = {}
        for code, var in rows:
            pick = var.get()
            if pick == SKIP_LABEL:
                continue
            if pick == EXCLUDE_LABEL:
                continue
            # صفّان مختلفان لا يصحّ أن يحملا الرمز نفسه
            if pick in used:
                messagebox.showerror(
                    "تعارض",
                    f"الصف «{pick}» مُسنَد لرمزين: {used[pick]} و {code}.\n"
                    "لكل صف رمز واحد — راجع اختيارك.", parent=win)
                return
            used[pick] = code

        for code, var in rows:
            pick = var.get()
            if pick == SKIP_LABEL:
                continue
            if pick == EXCLUDE_LABEL:
                set_noor_exclude(code, True)
            else:
                set_noor_level_mapping(code, name_to_digit[pick], pick)
            changed["v"] = True

        if not changed["v"]:
            messagebox.showinfo("لم يتغيّر شيء",
                                "لم تختر ترميزاً لأي رمز.", parent=win)
            return
        win.destroy()

    btns = tk.Frame(win, bg="white")
    btns.pack(fill="x", padx=16, pady=14)
    ttk.Button(btns, text="💾 حفظ الترميز وإعادة الاستيراد",
               command=_save).pack(side="right", padx=4)
    ttk.Button(btns, text="لاحقاً", command=win.destroy).pack(side="right", padx=4)

    win.update_idletasks()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = win.winfo_width(), win.winfo_height()
        win.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 3}")
    except Exception:
        pass

    parent.wait_window(win)
    return changed["v"]
