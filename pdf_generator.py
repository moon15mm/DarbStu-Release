# -*- coding: utf-8 -*-
"""
pdf_generator.py — توليد ملفات PDF (جلسات الموجّه، العقود السلوكية، النتائج)
"""
import os, io, base64, datetime, json, sqlite3
from typing import List, Dict, Any, Optional
from constants import BASE_DIR, DATA_DIR, DB_PATH
from config_manager import load_config
from database import get_db

def generate_session_pdf(session_data: dict) -> bytes:
    """
    ينشئ ملف PDF للجلسة الارشادية بتنسيق احترافي.
    يستخدم reportlab مع دعم كامل للنص العربي (arabic_reshaper + bidi).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                    Spacer, Table, TableStyle, HRFlowable)
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    import io as _io

    # ── تسجيل خط يدعم العربية ────────────────────────────────
    _font_name = "Helvetica"
    _font_bold = "Helvetica-Bold"
    _font_candidates = [
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\Arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"C:\Windows\Fonts\times.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    _font_registered = False
    for _fp in _font_candidates:
        if os.path.exists(_fp):
            try:
                # تجنّب إعادة التسجيل إذا سبق تسجيله
                if "DarbFont" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("DarbFont", _fp))
                _font_name = "DarbFont"
                _font_bold = "DarbFont"
                _font_registered = True
                break
            except Exception:
                pass

    # ── دالة معالجة النص العربي (reshape + bidi) ─────────────
    try:
        import arabic_reshaper as _reshaper
        from bidi.algorithm import get_display as _bidi_display
        def _ar(txt):
            if not txt:
                return ""
            txt = str(txt)
            try:
                reshaped = _reshaper.reshape(txt)
                return _bidi_display(reshaped)
            except Exception:
                return txt
    except ImportError:
        # إذا لم تكن المكتبات مثبّتة نُعيد النص كما هو
        def _ar(txt):
            return str(txt) if txt else ""

    # ── جلب إعدادات المدرسة ──────────────────────────────────
    cfg          = load_config()
    school       = cfg.get("school_name", "المدرسة")
    # استخدم اسم الموجّه النشط إذا مُرِّر في session_data، وإلا fallback للإعداد القديم
    counselor_nm = (session_data.get("counselor_name") or
                    cfg.get("counselor1_name") or
                    cfg.get("assistant_name", "الموجه الطلابي"))
    principal_nm = cfg.get("principal_name", "")

    # ── بناء المستند ─────────────────────────────────────────
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm,   bottomMargin=2*cm,
        title="جلسة ارشادية"
    )

    PURPLE = colors.HexColor("#4c1d95")
    BLUE   = colors.HexColor("#1d4ed8")
    LBLUE  = colors.HexColor("#ede9fe")
    GRAY   = colors.HexColor("#6b7280")
    DARK   = colors.HexColor("#1f2937")
    WHITE  = colors.white

    # الأنماط — الاتجاه RIGHT لكن بعد معالجة bidi يُعرض صحيحاً
    st_school = ParagraphStyle("school", fontName=_font_bold, fontSize=15,
                               alignment=TA_CENTER, textColor=PURPLE, spaceAfter=2)
    st_main   = ParagraphStyle("main",   fontName=_font_bold, fontSize=13,
                               alignment=TA_CENTER, textColor=BLUE,   spaceAfter=4)
    st_label  = ParagraphStyle("label",  fontName=_font_bold, fontSize=11,
                               alignment=TA_RIGHT,  textColor=PURPLE,
                               spaceBefore=8, spaceAfter=2)
    st_item   = ParagraphStyle("item",   fontName=_font_name, fontSize=10,
                               alignment=TA_RIGHT,  textColor=DARK,
                               leading=18, spaceAfter=2, rightIndent=12)
    st_note   = ParagraphStyle("note",   fontName=_font_name, fontSize=10,
                               alignment=TA_RIGHT,  textColor=GRAY,
                               leading=16, spaceAfter=4)

    elems = []

    # ── الرأس ────────────────────────────────────────────────
    elems.append(Paragraph(_ar("المملكة العربية السعودية"), st_note))
    elems.append(Paragraph(_ar("وزارة التعليم"), st_note))
    elems.append(Spacer(1, 0.2*cm))
    elems.append(Paragraph(_ar(school), st_school))
    elems.append(Paragraph(_ar("جلسة ارشاد فردي"), st_main))
    elems.append(HRFlowable(width="100%", thickness=2, color=PURPLE, spaceAfter=10))

    # ── بيانات الجلسة (جدول) ─────────────────────────────────
    d = session_data
    info = [
        [_ar(d.get("student_name", "")), _ar("اسم الطالب:")],
        [_ar(d.get("class_name",   "")), _ar("الفصل:")],
        [_ar(d.get("date",         "")), _ar("التاريخ:")],
        [_ar(d.get("title",        "")), _ar("عنوان الجلسة:")],
    ]
    tbl = Table(info, colWidths=[12*cm, 4.5*cm])
    tbl.setStyle(TableStyle([
        ("FONTNAME",      (0,0),(-1,-1), _font_name),
        ("FONTNAME",      (1,0),(1,-1),  _font_bold),
        ("FONTSIZE",      (0,0),(-1,-1), 10),
        ("ALIGN",         (0,0),(-1,-1), "RIGHT"),
        ("TEXTCOLOR",     (1,0),(1,-1),  PURPLE),
        ("TEXTCOLOR",     (0,0),(0,-1),  DARK),
        ("BACKGROUND",    (1,0),(1,-1),  LBLUE),
        ("ROWBACKGROUNDS",(0,0),(-1,-1), [colors.HexColor("#faf5ff"), WHITE]),
        ("GRID",          (0,0),(-1,-1), 0.5, colors.HexColor("#d1d5db")),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
    ]))
    elems.append(tbl)
    elems.append(Spacer(1, 0.5*cm))

    # ── دالة إضافة قسم ───────────────────────────────────────
    def _add_section(title, items):
        if not items:
            return
        elems.append(Paragraph(_ar(title), st_label))
        elems.append(HRFlowable(width="100%", thickness=0.75,
                                color=colors.HexColor("#c4b5fd"), spaceAfter=4))
        for i, item in enumerate(items, 1):
            elems.append(Paragraph(_ar(f"{i}. {item}"), st_item))
        elems.append(Spacer(1, 0.3*cm))

    _add_section("الاهداف:",    d.get("goals",           []))
    _add_section("المداولات:",  d.get("discussions",      []))
    _add_section("التوصيات:",   d.get("recommendations",  []))

    if d.get("notes"):
        elems.append(Paragraph(_ar("ملاحظات اضافية:"), st_label))
        elems.append(HRFlowable(width="100%", thickness=0.75,
                                color=colors.HexColor("#c4b5fd"), spaceAfter=4))
        elems.append(Paragraph(_ar(d["notes"]), st_note))
        elems.append(Spacer(1, 0.3*cm))

    # ── التوقيعات ─────────────────────────────────────────────
    elems.append(Spacer(1, 1.5*cm))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=GRAY, spaceAfter=8))

    sig_counselor = _ar("الموجه الطلابي") + "\n" + _ar(counselor_nm)
    sig_principal = _ar("قائد المدرسة") + ("\n" + _ar(principal_nm) if principal_nm else "")
    sig_tbl = Table([[sig_counselor, sig_principal]], colWidths=[8.25*cm, 8.25*cm])
    sig_tbl.setStyle(TableStyle([
        ("FONTNAME",    (0,0),(-1,-1), _font_bold),
        ("FONTSIZE",    (0,0),(-1,-1), 10),
        ("ALIGN",       (0,0),(-1,-1), "CENTER"),
        ("TEXTCOLOR",   (0,0),(-1,-1), DARK),
        ("TOPPADDING",  (0,0),(-1,-1), 8),
        ("LINEBEFORE",  (1,0),(1,-1),  0.5, GRAY),
    ]))
    elems.append(sig_tbl)

    # ── بناء PDF ─────────────────────────────────────────────
    doc.build(elems)
    return buf.getvalue()


def generate_behavioral_contract_pdf(contract_data: dict) -> bytes:
    """
    ينشئ ملف PDF للعقد السلوكي وفق نموذج وزارة التعليم.
    يستخدم نفس نظام الخطوط والمعالجة العربية المستخدم في generate_session_pdf.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                    Spacer, Table, TableStyle, HRFlowable)
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    import io as _io

    # ── تسجيل خط يدعم العربية (نفس آلية generate_session_pdf) ──
    _font_name = "Helvetica"
    _font_bold = "Helvetica-Bold"
    _font_candidates = [
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\Arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for _fp in _font_candidates:
        if os.path.exists(_fp):
            try:
                if "DarbFont" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("DarbFont", _fp))
                _font_name = "DarbFont"
                _font_bold = "DarbFont"
                break
            except Exception:
                pass

    # ── معالجة النص العربي (reshape + bidi) ─────────────────
    try:
        import arabic_reshaper as _reshaper
        from bidi.algorithm import get_display as _bidi_display
        def _ar(txt):
            if not txt: return ""
            txt = str(txt)
            try:
                return _bidi_display(_reshaper.reshape(txt))
            except Exception:
                return txt
    except ImportError:
        def _ar(txt):
            return str(txt) if txt else ""

    cfg          = load_config()
    school       = contract_data.get("school_name") or cfg.get("school_name", "المدرسة")
    counselor_nm = (contract_data.get("counselor_name") or
                    cfg.get("counselor1_name") or "الموجه الطلابي")

    # ── الألوان وفق نموذج وزارة التعليم ─────────────────────
    TEAL   = colors.HexColor("#0d9488")
    PURPLE = colors.HexColor("#4c1d95")
    LBLUE  = colors.HexColor("#ede9fe")
    LGREEN = colors.HexColor("#ecfdf5")
    LRED   = colors.HexColor("#fff0f0")
    DARK   = colors.HexColor("#1f2937")
    GRAY   = colors.HexColor("#6b7280")
    WHITE  = colors.white
    GREEN  = colors.HexColor("#065f46")
    RED    = colors.HexColor("#991b1b")

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=1.5*cm, bottomMargin=2*cm,
        title="عقد سلوكي"
    )

    # ── أنماط النص ───────────────────────────────────────────
    st_white  = ParagraphStyle("cwhite",  fontName=_font_bold,  fontSize=10,
                               alignment=TA_RIGHT,  textColor=WHITE, leading=16)
    st_school = ParagraphStyle("cschool", fontName=_font_bold,  fontSize=14,
                               alignment=TA_CENTER, textColor=WHITE)
    st_title  = ParagraphStyle("ctitle",  fontName=_font_bold,  fontSize=13,
                               alignment=TA_CENTER, textColor=PURPLE, spaceAfter=4)
    st_intro  = ParagraphStyle("cintro",  fontName=_font_name,  fontSize=10,
                               alignment=TA_RIGHT,  textColor=DARK,   leading=18)
    st_label  = ParagraphStyle("clabel",  fontName=_font_bold,  fontSize=11,
                               alignment=TA_RIGHT,  textColor=PURPLE,
                               spaceBefore=6, spaceAfter=2)
    st_cell   = ParagraphStyle("ccell",   fontName=_font_name,  fontSize=10,
                               alignment=TA_RIGHT,  textColor=DARK,   leading=16)
    st_cell_b = ParagraphStyle("ccellb",  fontName=_font_bold,  fontSize=10,
                               alignment=TA_RIGHT,  textColor=PURPLE, leading=16)
    st_hdr_c  = ParagraphStyle("chdrc",   fontName=_font_bold,  fontSize=10,
                               alignment=TA_CENTER, textColor=WHITE,  leading=16)
    st_note   = ParagraphStyle("cnote",   fontName=_font_name,  fontSize=10,
                               alignment=TA_RIGHT,  textColor=DARK,   leading=16)
    st_bonus  = ParagraphStyle("cbonus",  fontName=_font_bold,  fontSize=10,
                               alignment=TA_RIGHT,  textColor=GREEN,  leading=16)
    st_penal  = ParagraphStyle("cpenal",  fontName=_font_bold,  fontSize=10,
                               alignment=TA_RIGHT,  textColor=RED,    leading=16)

    elems = []
    d = contract_data

    # ═══ رأس الصفحة ══════════════════════════════════════════
    hdr_tbl = Table([[
        Paragraph(_ar("وزارة التعليم"), st_white),
        Paragraph(_ar("الادارة العامة للتعليم  |  مكتب التعليم"), st_white),
    ]], colWidths=[9*cm, 9*cm])
    hdr_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), TEAL),
        ("ALIGN",         (0,0),(0,0),   "LEFT"),
        ("ALIGN",         (1,0),(1,0),   "RIGHT"),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
        ("LEFTPADDING",   (0,0),(-1,-1), 12),
        ("RIGHTPADDING",  (0,0),(-1,-1), 12),
    ]))
    elems.append(hdr_tbl)
    elems.append(Spacer(1, 4))

    school_tbl = Table([[Paragraph(_ar(school), st_school)]], colWidths=[18*cm])
    school_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), PURPLE),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
        ("ALIGN",         (0,0),(-1,-1), "CENTER"),
    ]))
    elems.append(school_tbl)
    elems.append(Spacer(1, 10))

    # ═══ عنوان + مقدمة ═══════════════════════════════════════
    elems.append(Paragraph(_ar("عقد سلوكي"), st_title))
    elems.append(HRFlowable(width="100%", thickness=2, color=PURPLE, spaceAfter=6))
    elems.append(Paragraph(
        _ar("الحمد لله والصلاة والسلام على سيدنا محمد وبعد ... "
            "فقد تم مناقشة العقد السلوكي مع الطالب الموضح بياناته "
            "على ان يقوم بما يوجه اليه من مسؤوليات داخل المدرسة ..."),
        st_intro))
    elems.append(Spacer(1, 8))

    # ═══ بيانات الطالب ═══════════════════════════════════════
    info = [
        [Paragraph(_ar(d.get("student_name", "")), st_cell),
         Paragraph(_ar("الاسم:"),                  st_cell_b)],
        [Paragraph(_ar(d.get("class_name",   "")), st_cell),
         Paragraph(_ar("الصف:"),                   st_cell_b)],
        [Paragraph(_ar(d.get("subject",      "")), st_cell),
         Paragraph(_ar("الموضوع:"),                st_cell_b)],
        [Paragraph(_ar("من  {}  ه    الى  {}  ه".format(
                d.get("period_from","..."), d.get("period_to","..."))),
            st_cell),
         Paragraph(_ar("الفترة:"),                 st_cell_b)],
    ]
    info_tbl = Table(info, colWidths=[13*cm, 5*cm])
    info_tbl.setStyle(TableStyle([
        ("FONTNAME",      (0,0),(-1,-1), _font_name),
        ("FONTSIZE",      (0,0),(-1,-1), 10),
        ("ALIGN",         (0,0),(-1,-1), "RIGHT"),
        ("TEXTCOLOR",     (1,0),(1,-1),  PURPLE),
        ("TEXTCOLOR",     (0,0),(0,-1),  DARK),
        ("BACKGROUND",    (1,0),(1,-1),  LBLUE),
        ("ROWBACKGROUNDS",(0,0),(-1,-1), [colors.HexColor("#faf5ff"), WHITE]),
        ("GRID",          (0,0),(-1,-1), 0.5, colors.HexColor("#d1d5db")),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
    ]))
    elems.append(info_tbl)
    elems.append(Spacer(1, 10))

    elems.append(Paragraph(
        _ar("حيث نوافق نحن الموقعون ادناه على القيام بالمسؤوليات التالية:"),
        st_intro))
    elems.append(Spacer(1, 6))

    # ═══ جدول المسؤوليات / المزايا ═══════════════════════════
    responsibilities = [
        ("سوف يضاف له درجات في السلوك.",
         "الحضور للمدرسة بانتظام."),
        ("سوف يذكر اسمه في الاذاعة المدرسية كطالب متميز.",
         "القيام بالواجبات المنزلية المكلف بها."),
        ("سوف يسلم شهادة تميز سلوكي.",
         "عدم الاعتداء على اي طالب بالمدرسة."),
        ("يكرم في نهاية العام الدراسي.",
         "عدم القيام باي مخالفات داخل المدرسة."),
        ("يتم مساعدته في المواد الدراسية من قبل المعلمين.", ""),
    ]
    main_rows = [
        [Paragraph(_ar("المزايا والتدعيمات:"), st_hdr_c),
         Paragraph(_ar("المسؤوليات:"),          st_hdr_c)],
        [Paragraph(_ar("تحصل على ما يلي:"),    st_hdr_c),
         Paragraph(_ar("اذا قام الطالب بالاعمال الاتية:"), st_hdr_c)],
    ]
    for i, (rew, res) in enumerate(responsibilities):
        pr = "{} - ".format(i+1) if res else ""
        pw = "{} - ".format(i+1) if rew else ""
        main_rows.append([
            Paragraph(_ar("{}{}".format(pw, rew)), st_cell),
            Paragraph(_ar("{}{}".format(pr, res)), st_cell),
        ])
    main_tbl = Table(main_rows, colWidths=[9*cm, 9*cm])
    main_tbl.setStyle(TableStyle([
        ("FONTNAME",      (0,0),(-1,-1), _font_name),
        ("FONTSIZE",      (0,0),(-1,-1), 10),
        ("BACKGROUND",    (0,0),(-1,1),  PURPLE),
        ("TEXTCOLOR",     (0,0),(-1,1),  WHITE),
        ("ROWBACKGROUNDS",(0,2),(-1,-1), [colors.HexColor("#faf5ff"), WHITE]),
        ("TEXTCOLOR",     (0,2),(-1,-1), DARK),
        ("ALIGN",         (0,0),(-1,-1), "RIGHT"),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
        ("BOX",           (0,0),(-1,-1), 0.7, PURPLE),
        ("INNERGRID",     (0,0),(-1,-1), 0.3, GRAY),
        ("LINEBEFORE",    (1,0),(1,-1),  0.5, WHITE),
    ]))
    elems.append(main_tbl)
    elems.append(Spacer(1, 8))

    # ═══ مكافآت إضافية ═══════════════════════════════════════
    bonus_tbl = Table([[Paragraph(_ar(
        "مكافات اضافية: عند استمراره في هذا التميز السلوكي حتى "
        "نهاية العام الدراسي سوف يسلم جائزة قيمة."), st_bonus)]],
        colWidths=[18*cm])
    bonus_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), LGREEN),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
        ("RIGHTPADDING",  (0,0),(-1,-1), 12),
        ("LEFTPADDING",   (0,0),(-1,-1), 12),
        ("BOX",           (0,0),(-1,-1), 0.7, GREEN),
    ]))
    elems.append(bonus_tbl)
    elems.append(Spacer(1, 5))

    # ═══ عقوبات ══════════════════════════════════════════════
    penalty_tbl = Table([[Paragraph(_ar(
        "عقوبات: في حالة عدم الالتزام بما جاء في العقد سوف تلغى "
        "المزايا والتدعيمات ويتخذ في حقه الاجراءات كما جاء في "
        "قواعد السلوك والمواظبة."), st_penal)]],
        colWidths=[18*cm])
    penalty_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), LRED),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
        ("RIGHTPADDING",  (0,0),(-1,-1), 12),
        ("LEFTPADDING",   (0,0),(-1,-1), 12),
        ("BOX",           (0,0),(-1,-1), 0.7, RED),
    ]))
    elems.append(penalty_tbl)
    elems.append(Spacer(1, 6))

    # ═══ ملاحظات إضافية ══════════════════════════════════════
    extra_notes = (d.get("notes") or "").strip()
    if extra_notes:
        elems.append(Paragraph(_ar("ملاحظات:"), st_label))
        elems.append(HRFlowable(width="100%", thickness=0.75,
                                color=colors.HexColor("#c4b5fd"), spaceAfter=4))
        elems.append(Paragraph(_ar(extra_notes), st_note))
        elems.append(Spacer(1, 8))

    # ═══ التوقيعات ═══════════════════════════════════════════
    elems.append(Spacer(1, 1*cm))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=GRAY, spaceAfter=8))
    sig_counselor = _ar("الموجه الطلابي") + "\n" + _ar(counselor_nm)
    sig_student   = _ar("الطالب") + "\n" + _ar(d.get("student_name",""))
    sig_tbl = Table([[sig_counselor, sig_student]], colWidths=[9*cm, 9*cm])
    sig_tbl.setStyle(TableStyle([
        ("FONTNAME",      (0,0),(-1,-1), _font_bold),
        ("FONTSIZE",      (0,0),(-1,-1), 10),
        ("ALIGN",         (0,0),(-1,-1), "CENTER"),
        ("TEXTCOLOR",     (0,0),(-1,-1), DARK),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
        ("LINEBEFORE",    (1,0),(1,-1),  0.5, GRAY),
    ]))
    elems.append(sig_tbl)

    doc.build(elems)
    return buf.getvalue()



def parse_results_pdf(pdf_path: str) -> List[Dict]:
    """يبني فهرساً: رقم هوية → رقم الصفحة، بدون نسخ البيانات."""
    import re as _re
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("يلزم تثبيت pdfplumber: pip install pdfplumber")

    students = []
    abs_path = os.path.abspath(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            try:
                text = page.extract_text() or ""
                # استخرج رقم الهوية فقط
                m_id = _re.search(r'Identity No[.\s]+(\d{8,12})', text)
                if not m_id:
                    continue
                identity = m_id.group(1).strip()

                # استخرج الاسم والفصل من النص
                m_name = _re.search(r'Student Name:\s*(.+?)(?:Section:|$)', text)
                m_sec  = _re.search(r'Section:\s*(\S+)', text)
                student_name = m_name.group(1).strip() if m_name else ""
                section      = m_sec.group(1).strip()  if m_sec  else ""

                # استخراج المعدل — أنماط متعددة لتغطية تنسيقات نور
                # ملاحظة: في PDF نور تظهر قيمة المعدل (مثل 85.11) على سطر
                # Excused Absence بسبب اتجاه النص العربي
                gpa = ""
                for pat in [
                    r'GPA\s*[.:\s]+(\d+\.?\d*)',
                    r'Average\s*[.:\s]+(\d+\.?\d*)',
                    r'Overall\s+Average\s*[.:\s]+(\d+\.?\d*)',
                    r'المعدل\s*[.:\s]+(\d+\.?\d*)',
                    r'Excused Absence[^\n]*?(\d{2,3}\.\d{2})',
                    r'Unexcused Absence[^\n]*?(\d{2,3}\.\d{2})',
                    r'Class Ranking[^\n]*?(\d{2,3}\.\d{2})',
                ]:
                    m_gpa = _re.search(pat, text, _re.IGNORECASE)
                    if m_gpa:
                        gpa = m_gpa.group(1).strip()
                        break

                students.append({
                    "identity_no":  identity,
                    "student_name": student_name,
                    "section":      section,
                    "page_no":      page_num,
                    "pdf_path":     abs_path,
                    "gpa": gpa, "class_rank": "", "section_rank": "",
                    "excused_abs": "", "unexcused_abs": "", "subjects": [],
                })
            except Exception as e:
                print(f"[RESULTS] تحذير — صفحة {page_num+1}: {e}")
                continue

    return students


def _render_pdf_page_as_png(pdf_path: str, page_no: int, dpi: int = 150) -> bytes:
    """يحوّل صفحة من PDF إلى صورة JPEG مباشرة عبر pdfplumber."""
    import pdfplumber, io
    from PIL import Image as _PILImage
    abs_path = os.path.abspath(pdf_path)
    with pdfplumber.open(abs_path) as pdf:
        page = pdf.pages[page_no]
        im = page.to_image(resolution=dpi)
        # تحويل لـ RGB لأن JPEG لا يدعم صيغة Palette
        pil_img = im.original.convert("RGB")
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=92)
        return buf.getvalue()


def _render_page_pillow(pdf_path: str, page_no: int) -> bytes:
    """Alias للتوافق."""
    return _render_pdf_page_as_png(pdf_path, page_no)

def save_results_to_db(students: List[Dict],
                        school_year: str = "") -> tuple:
    """يحفظ فهرس النتائج (رقم هوية ← رقم صفحة) في قاعدة البيانات."""
    import json as _j
    if not school_year:
        school_year = str(datetime.date.today().year)

    # تأكد من وجود الأعمدة الجديدة (ترقية تلقائية)
    con = get_db(); cur = con.cursor()
    existing_cols = {r[1] for r in cur.execute("PRAGMA table_info(student_results)")}
    if "page_no" not in existing_cols:
        cur.execute("ALTER TABLE student_results ADD COLUMN page_no INTEGER NOT NULL DEFAULT 0")
    if "pdf_path" not in existing_cols:
        cur.execute("ALTER TABLE student_results ADD COLUMN pdf_path TEXT NOT NULL DEFAULT ''")
    con.commit()

    inserted = 0
    for s in students:
        subj_json = _j.dumps(s.get("subjects", []), ensure_ascii=False)
        now_ts    = datetime.datetime.utcnow().isoformat()
        cur.execute("""
            INSERT OR REPLACE INTO student_results
            (identity_no, student_name, section, school_year,
             page_no, pdf_path,
             gpa, class_rank, section_rank,
             excused_abs, unexcused_abs, subjects_json, uploaded_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (s["identity_no"], s["student_name"], s["section"],
             school_year, s.get("page_no", 0), s.get("pdf_path", ""),
             s.get("gpa",""), s.get("class_rank",""), s.get("section_rank",""),
             s.get("excused_abs",""), s.get("unexcused_abs",""), subj_json, now_ts))
        if cur.rowcount:
            inserted += 1
    con.commit(); con.close()
    return inserted, 0


def get_student_result(identity_no: str,
                        school_year: str = None) -> Optional[Dict]:
    """يجلب نتيجة طالب بالسجل المدني."""
    import json as _j
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    if school_year:
        cur.execute("""SELECT * FROM student_results
                       WHERE identity_no=? AND school_year=?
                       ORDER BY uploaded_at DESC LIMIT 1""",
                    (identity_no, school_year))
    else:
        cur.execute("""SELECT * FROM student_results
                       WHERE identity_no=?
                       ORDER BY uploaded_at DESC LIMIT 1""",
                    (identity_no,))
    row = cur.fetchone(); con.close()
    if not row: return None
    result = dict(row)
    try:
        result["subjects"] = _j.loads(result["subjects_json"] or "[]")
    except:
        result["subjects"] = []
    return result


def results_portal_html(school_name: str = "") -> str:
    """صفحة بوابة النتائج — الطالب يدخل رقم السجل المدني."""
    if not school_name:
        school_name = load_config().get("school_name", "المدرسة")

    return """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>نتائج الطلاب — {school}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Arial,sans-serif;direction:rtl;background:linear-gradient(135deg,#1565C0 0%,#0D47A1 100%);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:#fff;border-radius:16px;padding:36px;max-width:440px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.25)}}
.logo{{text-align:center;margin-bottom:24px}}
.logo h1{{font-size:22px;color:#1565C0;font-weight:900;margin-bottom:4px}}
.logo p{{color:#5A6A7E;font-size:13px}}
.inp{{width:100%;padding:14px 16px;border:2px solid #E0E7FF;border-radius:10px;font-size:16px;font-family:Arial;direction:rtl;text-align:center;letter-spacing:2px;outline:none;transition:.2s}}
.inp:focus{{border-color:#1565C0;box-shadow:0 0 0 3px rgba(21,101,192,.15)}}
.btn{{width:100%;padding:14px;background:#1565C0;color:#fff;border:none;border-radius:10px;font-size:16px;font-family:Arial;font-weight:700;cursor:pointer;margin-top:12px;transition:.2s}}
.btn:hover{{background:#0D47A1;transform:translateY(-1px)}}
.btn:active{{transform:translateY(0)}}
.err{{background:#FEE2E2;color:#C62828;padding:12px;border-radius:8px;text-align:center;margin-top:12px;font-size:14px;display:none}}
.loading{{text-align:center;color:#1565C0;padding:16px;display:none}}
.hint{{text-align:center;color:#9CA3AF;font-size:12px;margin-top:16px}}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <h1>🎓 {school}</h1>
    <p>بوابة نتائج الطلاب</p>
  </div>
  <label style="display:block;color:#374151;font-size:14px;font-weight:700;margin-bottom:8px">
    رقم السجل المدني / الإقامة
  </label>
  <input class="inp" id="nid" type="text" inputmode="numeric"
         maxlength="10" placeholder="0000000000"
         onkeydown="if(event.key==='Enter')lookup()">
  <button class="btn" onclick="lookup()">🔍 عرض النتيجة</button>
  <div class="err" id="err">رقم الهوية غير موجود أو لم تُرفع النتائج بعد</div>
  <div class="loading" id="loading">⏳ جارٍ البحث...</div>
  <p class="hint">أدخل رقم هويتك الوطنية أو الإقامة للاطلاع على نتيجتك</p>
</div>
<script>
function lookup(){{
  const nid = document.getElementById('nid').value.trim();
  if(nid.length < 9){{ showErr(); return; }}
  document.getElementById('err').style.display='none';
  document.getElementById('loading').style.display='block';
  fetch('/api/results/' + nid)
    .then(r=>r.json())
    .then(d=>{{
      document.getElementById('loading').style.display='none';
      if(d.ok) window.location.href='/results/' + nid;
      else showErr();
    }})
    .catch(()=>{{ document.getElementById('loading').style.display='none'; showErr(); }});
}}
function showErr(){{
  document.getElementById('err').style.display='block';
}}
</script>
</body>
</html>""".format(school=school_name)


def student_result_html(result: Dict, school_name: str = "") -> str:
    """صفحة نتيجة طالب — تعرض صورة الشهادة مباشرة من PDF.
    هذه الدالة محتفظة للتوافق — الـ endpoint الجديد لا يستدعيها."""
    identity_no = result.get("identity_no", "")
    if not school_name:
        school_name = load_config().get("school_name", "المدرسة")
    return """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>نتيجة {name} — {school}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Arial,sans-serif;background:#f0f4f8;min-height:100vh;padding:20px}}
.card{{background:#fff;border-radius:12px;max-width:900px;margin:0 auto;box-shadow:0 4px 20px rgba(0,0,0,.12);overflow:hidden}}
.hdr{{background:#1A237E;color:#fff;padding:16px 20px;text-align:center}}
.hdr h2{{font-size:18px;margin-bottom:4px}}
.hdr p{{font-size:13px;opacity:.85}}
.cert-img{{width:100%;display:block}}
.footer{{text-align:center;padding:12px;color:#666;font-size:12px}}
.back{{display:inline-block;padding:8px 16px;color:#1565C0;font-weight:700;font-size:13px;text-decoration:none}}
@media print{{.no-print{{display:none}}body{{background:#fff;padding:0}}}}
</style>
</head>
<body>
<div style="max-width:900px;margin:0 auto 8px">
  <a href="/results" class="back no-print">← عودة للبحث</a>
  <button onclick="window.print()" class="no-print"
    style="float:left;padding:6px 14px;background:#1565C0;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;margin-top:4px">
    🖨️ طباعة
  </button>
</div>
<div class="card">
  <div class="hdr">
    <h2>🎓 شهادة نتيجة الطالب</h2>
    <p>{school}</p>
  </div>
  <img class="cert-img" src="/api/results-image/{nid}" alt="شهادة الطالب" />
  <div class="footer">هذه الشهادة خاصة بالطالب — رقم الهوية: {nid}</div>
</div>
</body>
</html>""".format(
        name=result.get("student_name",""), school=school_name,
        nid=identity_no)



def generate_academic_inquiry_pdf(inq_data: dict) -> bytes:
    """وينشئ ملف PDF لخطاب الاستفسار الأكاديمي والرد عليه (إذا وجد)"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                    Spacer, Table, TableStyle, HRFlowable)
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    import io as _io

    # ── تسجيل خط يدعم العربية ──
    _font_name = "Helvetica"
    _font_bold = "Helvetica-Bold"
    _font_candidates = [
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\Arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"C:\Windows\Fonts\times.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for _fp in _font_candidates:
        if os.path.exists(_fp):
            try:
                if "DarbFont" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("DarbFont", _fp))
                _font_name = "DarbFont"
                _font_bold = "DarbFont"
                break
            except Exception: pass

    try:
        import arabic_reshaper as _reshaper
        from bidi.algorithm import get_display as _bidi_display
        def _ar(txt):
            if not txt: return ""
            txt = str(txt)
            try: return _bidi_display(_reshaper.reshape(txt))
            except Exception: return txt
    except ImportError:
        def _ar(txt): return str(txt) if txt else ""

    from config_manager import load_config
    import os
    cfg = load_config()
    school = cfg.get("school_name", "المدرسة")
    
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm, title="خطاب استفسار أكاديمي"
    )

    PURPLE = colors.HexColor("#4c1d95")
    BLUE   = colors.HexColor("#1d4ed8")
    LBLUE  = colors.HexColor("#ede9fe")
    GRAY   = colors.HexColor("#6b7280")
    DARK   = colors.HexColor("#1f2937")
    WHITE  = colors.white

    st_school = ParagraphStyle("school", fontName=_font_bold, fontSize=15, alignment=TA_CENTER, textColor=PURPLE, spaceAfter=2)
    st_main   = ParagraphStyle("main", fontName=_font_bold, fontSize=13, alignment=TA_CENTER, textColor=BLUE, spaceAfter=4)
    st_label  = ParagraphStyle("label", fontName=_font_bold, fontSize=11, alignment=TA_RIGHT, textColor=PURPLE, spaceBefore=8, spaceAfter=2)
    st_note   = ParagraphStyle("note", fontName=_font_name, fontSize=10, alignment=TA_RIGHT, textColor=GRAY, leading=16, spaceAfter=4)

    elems = []
    elems.append(Paragraph(_ar("المملكة العربية السعودية"), st_note))
    elems.append(Paragraph(_ar("وزارة التعليم"), st_note))
    elems.append(Spacer(1, 0.2*cm))
    elems.append(Paragraph(_ar(school), st_school))
    elems.append(Paragraph(_ar("خطاب استفسار عن مستوى طالب"), st_main))
    elems.append(HRFlowable(width="100%", thickness=2, color=PURPLE, spaceAfter=10))

    info1 = [
        [_ar(inq_data.get("teacher_name", "")), _ar("المكرم المعلم:")],
        [_ar(inq_data.get("date", "") or inq_data.get("inquiry_date", "")), _ar("تاريخ الخطاب:")],
        [_ar(inq_data.get("subject", "")), _ar("المادة:")],
        [_ar(inq_data.get("student_name", "")), _ar("الطالب:")],
        [_ar(inq_data.get("class_name", "")), _ar("الفصل:")],
    ]
    tbl = Table(info1, colWidths=[12*cm, 4.5*cm])
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0),(-1,-1), _font_name),
        ("FONTNAME", (1,0),(1,-1),  _font_bold),
        ("FONTSIZE", (0,0),(-1,-1), 10),
        ("ALIGN",    (0,0),(-1,-1), "RIGHT"),
        ("TEXTCOLOR", (1,0),(1,-1), PURPLE),
        ("TEXTCOLOR", (0,0),(0,-1), DARK),
        ("BACKGROUND", (1,0),(1,-1), LBLUE),
        ("ROWBACKGROUNDS",(0,0),(-1,-1), [colors.HexColor("#faf5ff"), WHITE]),
        ("GRID", (0,0),(-1,-1), 0.5, colors.HexColor("#d1d5db")),
        ("TOPPADDING", (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("RIGHTPADDING", (0,0),(-1,-1), 8),
    ]))
    elems.append(tbl)
    elems.append(Spacer(1, 0.5*cm))

    # نص الخطاب
    tchr = inq_data.get("teacher_name", "المعلم")
    subj = inq_data.get("subject", ".......")
    cls_name = inq_data.get("class_name", ".......")
    std_name = inq_data.get("student_name", ".......")
    
    elems.append(Paragraph(_ar(f"المكرم / الأستاذ {tchr}         حفظه الله"), ParagraphStyle('tx_intro', fontName=_font_bold, fontSize=12, alignment=TA_RIGHT, leading=18, spaceAfter=8)))
    elems.append(Paragraph(_ar(f"معلم مادة {subj} للصف {cls_name}"), ParagraphStyle('tx_intro_2', fontName=_font_bold, fontSize=12, alignment=TA_RIGHT, leading=18, spaceAfter=15)))
    
    p1 = "لا يخفى علينا أن لكم دوراً مهماً وأساسياً في العملية التعليمية ورفع مستوى الدافعية والتحصيل الدراسي لدى الطلاب، فأنتم تسعون إلى نهضة المجتمع بالتعاون مع المدرسة، فلا يقتصر دوركم على شرح الدرس أو إيصال المعلومة بل هو أيضاً الموجه والمرشد الأمثل للطلاب."
    elems.append(Paragraph(_ar(p1), ParagraphStyle('tx', fontName=_font_name, fontSize=11, alignment=TA_RIGHT, leading=18, spaceAfter=8)))
    
    p2 = f"نأمل منكم التكرم بإفادتنا عن مستوى الطالب ({std_name}) في مادة {subj} بالصف {cls_name}، وذلك لما لهذا الأمر من أهمية في متابعة المستوى التحصيلي للطلاب والذي يؤثر بشكل طردي على المستوى العام في المدرسة وكذلك العلاقة مع البيت."
    elems.append(Paragraph(_ar(p2), ParagraphStyle('tx', fontName=_font_name, fontSize=11, alignment=TA_RIGHT, leading=18, spaceAfter=8)))
    
    p3 = "لذا نرجو التكرم بتوضيح مستوى الطالب في المادة (تحسن ملحوظ / تدني ملحوظ) مع بيان الأسباب وإرفاق الشواهد التي تدعم ذلك."
    elems.append(Paragraph(_ar(p3), ParagraphStyle('tx', fontName=_font_name, fontSize=11, alignment=TA_RIGHT, leading=18, spaceAfter=8)))
    
    p4 = "مع خالص تقديرنا لجهودكم الحثيثة في المدرسة.\nهذا والله يحفظكم ويرعاكم،،"
    elems.append(Paragraph(_ar(p4), ParagraphStyle('tx_end', fontName=_font_name, fontSize=11, alignment=TA_RIGHT, leading=18, spaceAfter=16)))
    elems.append(Spacer(1, 0.5*cm))

    if inq_data.get("status") != "جديد":
        # عرض تصنيف المعلم لمستوى الطالب
        inq_type = inq_data.get("inquiry_type", "")
        if inq_type:
            elems.append(Paragraph(_ar(f"تصنيف المعلم لمستوى الطالب: {inq_type}"), ParagraphStyle('tx_type', fontName=_font_bold, fontSize=12, alignment=TA_RIGHT, leading=18, spaceAfter=8)))
            elems.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#c4b5fd"), spaceAfter=4))
        
        elems.append(Paragraph(_ar("الأسباب والإجراءات المتخذة:"), st_label))
        elems.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#c4b5fd"), spaceAfter=4))
        elems.append(Paragraph(_ar(inq_data.get("reasons", "") or inq_data.get("teacher_reply_reasons", "")), ParagraphStyle('tx2', fontName=_font_name, fontSize=11, alignment=TA_RIGHT, leading=18)))
        elems.append(Spacer(1, 0.5*cm))
        
        elems.append(Paragraph(_ar("الشواهد:"), st_label))
        elems.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#c4b5fd"), spaceAfter=4))
        elems.append(Paragraph(_ar(inq_data.get("evidence_text", "") or inq_data.get("teacher_reply_evidence", "") or inq_data.get("evidence", "")), ParagraphStyle('tx2', fontName=_font_name, fontSize=11, alignment=TA_RIGHT, leading=18)))
        elems.append(Spacer(1, 0.8*cm))
        
        if inq_data.get("evidence_file") or inq_data.get("teacher_reply_evidence_file"):
            elems.append(Paragraph(_ar("مرفق مع الرد صور/ملفات محفوظة في النظام."), st_note))

    elems.append(Spacer(1, 1.5*cm))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=GRAY, spaceAfter=8))

    sig_counselor = _ar("الموجه الطلابي") + "\n" + _ar(inq_data.get("counselor_name", ""))
    sig_teacher = _ar("المعلم") + "\n" + _ar(inq_data.get("teacher_name", ""))
    sig_tbl = Table([[sig_counselor, sig_teacher]], colWidths=[8.25*cm, 8.25*cm])
    sig_tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0),(-1,-1), _font_bold),
        ("FONTSIZE", (0,0),(-1,-1), 10),
        ("ALIGN", (0,0),(-1,-1), "CENTER"),
        ("TEXTCOLOR", (0,0),(-1,-1), DARK),
        ("TOPPADDING", (0,0),(-1,-1), 8),
    ]))
    elems.append(sig_tbl)

    doc.build(elems)
    return buf.getvalue()
