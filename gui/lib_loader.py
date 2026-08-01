# -*- coding: utf-8 -*-
"""
gui/lib_loader.py — محمل مكتبات الرسوم والخطوط لضمان التوافق بين ملفات المشروع
"""
from typing import Optional

Figure = None
FigureCanvasTkAgg = None
arabic_reshaper = None
get_display = None
HtmlFrame = None

try:
    from tkinterweb import HtmlFrame as _HtmlFrame
    HtmlFrame = _HtmlFrame
except ImportError:
    pass

try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.figure import Figure as _Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as _FigureCanvasTkAgg
    
    Figure = _Figure
    FigureCanvasTkAgg = _FigureCanvasTkAgg

    # إصلاح بق matplotlib على Windows (Python 3.12+):
    # event.widget يُعاد كـ string بدل widget → AttributeError في scroll_event_windows
    try:
        from matplotlib.backends._backend_tk import FigureCanvasTk as _FigCvTk
        _orig_scroll = _FigCvTk.scroll_event_windows
        def _safe_scroll(self, event):
            try:
                return _orig_scroll(self, event)
            except AttributeError:
                pass
        _FigCvTk.scroll_event_windows = _safe_scroll
    except Exception:
        pass

    # دعم اللغة العربية
    try:
        import arabic_reshaper as _ar
        from bidi.algorithm import get_display as _gd
        arabic_reshaper = _ar
        get_display = _gd
    except:
        pass
except Exception as e:
    # سيتم طباعة الخطأ في نافذة الكونسول للمساعدة في تشخيص نقص المكتبات في EXE
    print(f"[LIB-LOADER] Warning: Matplotlib/Backend not available: {e}")
