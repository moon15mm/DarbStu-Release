# -*- coding: utf-8 -*-
"""
gender_ui.py — تأنيث واجهات مدارس البنات.

ألفاظ التذكير مثبَّتة في ~٧٢٠ موضعاً عبر ٤٦ ملفاً (تسميات أزرار،
عناوين أعمدة، أسماء تبويبات، نصوص صفحات الويب). تعديلها واحداً واحداً
عمل هشّ يسقط منه مواضع ويُكسر عند كل إضافة جديدة.

هذه الوحدة تعترض النص عند **لحظة العرض** بدل تعديل مصدره:

  • الويب  — وسيط يؤنّث أجسام استجابات text/html فقط
  • التطبيق — ترقيع لبانيات tkinter/ttk تؤنّث الوسيط text

كلاهما لا يفعل شيئاً إن كانت المدرسة بنين، ولا يمسّ البيانات المخزّنة
إطلاقاً — التحويل عرضٌ لا تخزين، فتغيير نوع المدرسة يبقى ممكناً.
"""
from config_manager import feminize

__all__ = ["feminize_html", "install_web_middleware", "install_tk_patch"]


# ═══════════════════════════════════════════════════════════════
#  الويب
# ═══════════════════════════════════════════════════════════════
def feminize_html(html: str) -> str:
    """
    يؤنّث صفحة HTML كاملة بما فيها السكربتات المضمّنة.

    تأنيث السكربت مقصود لا سهو: بعض الشيفرة تقارن نص عنصر معروض
    بحرفية مكتوبة (`opt.text === 'تحميل الطالب...'`). لو أنّثنا الصفحة
    دون السكربت لاختلف الطرفان وانكسرت المقارنة. التأنيث الموحّد يُبقي
    الطرفين متطابقين.
    """
    return feminize(html)


def install_web_middleware(app) -> bool:
    """يركّب الوسيط على تطبيق FastAPI/Starlette. يُرجع True عند التركيب."""
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response
    except Exception:
        return False

    class _FeminizeMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            resp = await call_next(request)

            ctype = (resp.headers.get("content-type") or "").lower()
            # HTML فقط. تأنيث JSON يفسد البيانات نفسها لا عرضها،
            # وتأنيث الملفات الثنائية يتلفها.
            if "text/html" not in ctype:
                return resp
            # لا نلمس المضغوط — فكّه وإعادة ضغطه ليست مهمة الوسيط
            if resp.headers.get("content-encoding"):
                return resp

            body = b""
            async for chunk in resp.body_iterator:
                body += chunk if isinstance(chunk, bytes) else str(chunk).encode()

            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                return Response(content=body, status_code=resp.status_code,
                                headers=dict(resp.headers),
                                media_type=resp.media_type)

            out = feminize_html(text).encode("utf-8")
            headers = dict(resp.headers)
            headers.pop("content-length", None)   # تغيّر الطول بعد التأنيث
            return Response(content=out, status_code=resp.status_code,
                            headers=headers, media_type=resp.media_type)

    app.add_middleware(_FeminizeMiddleware)
    return True


# ═══════════════════════════════════════════════════════════════
#  واجهة التطبيق (tkinter)
# ═══════════════════════════════════════════════════════════════
_TK_PATCHED = False


def install_tk_patch() -> bool:
    """
    يرقّع بانيات tkinter لتأنيث الوسيط `text` عند إنشاء الأداة.

    يجب أن يُستدعى **قبل** بناء أي تبويب، وإلا بقيت الأدوات المُنشأة
    قبله مذكَّرة.
    """
    global _TK_PATCHED
    if _TK_PATCHED:
        return True
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return False

    def _fem(kw):
        t = kw.get("text")
        if isinstance(t, str) and t:
            kw["text"] = feminize(t)
        return kw

    def _wrap_widget(cls):
        orig_init = cls.__init__
        orig_cfg = cls.configure

        def __init__(self, *a, **kw):
            orig_init(self, *a, **_fem(kw))

        def configure(self, cnf=None, **kw):
            if isinstance(cnf, dict):
                cnf = _fem(dict(cnf))
            return orig_cfg(self, cnf, **_fem(kw))

        cls.__init__ = __init__
        cls.configure = configure
        cls.config = configure

    targets = [tk.Label, tk.Button, tk.Checkbutton, tk.Radiobutton,
               tk.LabelFrame, ttk.Label, ttk.Button, ttk.Checkbutton,
               ttk.Radiobutton, ttk.LabelFrame]
    for c in targets:
        try:
            _wrap_widget(c)
        except Exception:
            pass

    # عناوين أعمدة الجداول
    try:
        _orig_heading = ttk.Treeview.heading

        def heading(self, column, option=None, **kw):
            if isinstance(kw.get("text"), str):
                kw["text"] = feminize(kw["text"])
            return _orig_heading(self, column, option, **kw)

        ttk.Treeview.heading = heading
    except Exception:
        pass

    # أسماء التبويبات
    try:
        _orig_add = ttk.Notebook.add
        _orig_tab = ttk.Notebook.tab

        def add(self, child, **kw):
            if isinstance(kw.get("text"), str):
                kw["text"] = feminize(kw["text"])
            return _orig_add(self, child, **kw)

        def tab(self, tab_id, option=None, **kw):
            if isinstance(kw.get("text"), str):
                kw["text"] = feminize(kw["text"])
            return _orig_tab(self, tab_id, option, **kw)

        ttk.Notebook.add = add
        ttk.Notebook.tab = tab
    except Exception:
        pass

    _TK_PATCHED = True
    return True
