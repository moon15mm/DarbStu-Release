# -*- coding: utf-8 -*-
"""
report_builder.py — بناء تقارير HTML والتقارير المتقدمة
"""
import datetime, os, base64, json, io, csv, sqlite3
import pandas as pd
from tkinter import messagebox
from typing import List, Dict, Any, Optional
from constants import DB_PATH, DATA_DIR, TZ_OFFSET, BACKUP_DIR, now_riyadh_date
from config_manager import load_config, logo_img_tag_from_config, get_terms
from database import (get_db, query_absences, _apply_class_name_fix,
                      query_tardiness, query_excuses, load_students, load_teachers,
                      get_cloud_client)

def build_daily_report_df(date_str):
    rows = _apply_class_name_fix(query_absences(date_filter=date_str))
    if not rows: return pd.DataFrame(columns=["date","class_id","class_name","student_id","student_name","teacher_name","period"])
    return pd.DataFrame(rows).sort_values(["class_id","student_name"])

def build_total_absences_with_dates_by_class() -> dict:
    rows = _apply_class_name_fix(query_absences())
    if not rows: return {}
    df = pd.DataFrame(rows)
    def to_ddmm(s):
        try: y, m, d = str(s).split("-"); return f"{int(d):02d}/{int(m):02d}"
        except Exception: return str(s)
    df["ddmm"] = df["date"].apply(to_ddmm)
    grp = df.groupby(["class_id","class_name","student_id","student_name"])["ddmm"].apply(lambda s: ", ".join(sorted(set(s)))).reset_index()
    counts = df.groupby(["class_id","class_name","student_id","student_name"])["date"].count().reset_index(name="total")
    merged = pd.merge(grp, counts, on=["class_id","class_name","student_id","student_name"], how="left")
    out = {}
    for (cid, cname), g in merged.sort_values(["class_id","student_name","student_id"]).groupby(["class_id","class_name"]):
        out[cid] = {"class_name": cname, "rows": g.to_dict('records')}
    return out

def compute_today_metrics(date_str: Optional[str] = None) -> Dict[str, Any]:
    date_str = date_str or now_riyadh_date()
    
    client = get_cloud_client()
    if client.is_active():
        # Fetch pre-calculated metrics from server to ensure accuracy and speed
        res = client.get("/web/api/analytics/dashboard", params={"date": date_str})
        if res.get("ok"):
            return res.get("metrics", {})

    # المصدر الموحّد: الخلطة الذكية تدمج البصمة + روابط المعلمين + اليدوي.
    # بلا جهاز بصمة مُفعّل تُعطي الأرقام القديمة نفسها تماماً (الغائب = من
    # له سجل غياب)؛ وبتفعيله يُعاد تصنيف من بصم ثم سُجّل غائباً كـ«هروب» لا
    # غياباً، وفي الوضع الأساسي يُحسب من لم يبصم غائباً. انظر attendance_blend.
    try:
        from attendance_blend import blend_metrics
        return blend_metrics(date_str)
    except Exception:
        # سقوطٌ آمن للحساب المباشر إن تعذّرت الخلطة لأي سبب — لا تُترك
        # اللوحة فارغة. الغياب = من له سجل غياب اليوم.
        import traceback
        traceback.print_exc()

    from database import get_exempted_students
    exempted_ids = {str(e["student_id"]) for e in get_exempted_students()}

    store = load_students()
    total_students = len({s["id"] for c in store["list"] for s in c["students"] if str(s["id"]) not in exempted_ids})

    rows_today = _apply_class_name_fix(query_absences(date_filter=date_str))
    absent_ids_today = {str(r["student_id"]) for r in rows_today}
    total_absent = len(absent_ids_today)

    absent_by_class = {}
    for r in rows_today:
        absent_by_class.setdefault(r["class_id"], set()).add(str(r["student_id"]))

    by_class = []
    for c in store["list"]:
        cid, cname = c["id"], c["name"]
        class_students = [s for s in c.get("students", []) if str(s["id"]) not in exempted_ids]
        class_total = len(class_students)
        if class_total == 0 and len(c.get("students", [])) > 0:
            # All students in this class are exempted? skip or show 0
            continue

        class_absent = len(absent_by_class.get(cid, set()))
        by_class.append({
            "class_id": cid,
            "class_name": cname,
            "total": class_total,
            "absent": class_absent,
            "present": max(class_total - class_absent, 0)
        })

    by_class.sort(key=lambda x: x["class_id"])
    return {
        "date": date_str,
        "totals": {
            "students": total_students,
            "absent": total_absent,
            "present": max(total_students - total_absent, 0)
        },
        "by_class": by_class
    }
    

def generate_report_html(title: str, subtitle: str, data_by_class: Dict[str, List[List[str]]], stats: Dict[str, Any], headers: List[str]) -> str:
    """
    ينشئ كود HTML لتقرير غياب قابل للطباعة باستخدام جدول نظيف (RTL).
    """
    cfg = load_config()
    school_name = cfg.get("school_name", "المدرسة")
    logo_html = logo_img_tag_from_config(cfg)

    table_header_html = "".join(f"<th>{h}</th>" for h in headers)
    cols_count = len(headers)

    table_rows_html = ""
    for class_name, students in data_by_class.items():
        table_rows_html += f'<tr class="class-header"><td colspan="{cols_count}">{class_name}</td></tr>'
        for student_row in students:
            table_rows_html += "<tr>"
            for cell in student_row:
                table_rows_html += f"<td>{cell}</td>"
            table_rows_html += "</tr>"

    style_css = """
        @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap' );
        body { font-family: 'Cairo', sans-serif; margin: 0; background-color: #f4f4f4; }
        .page { width: 297mm; min-height: 210mm; padding: 15mm; margin: 10mm auto; border: 1px #D3D3D3 solid; background: white; box-shadow: 0 0 5px rgba(0,0,0,0.1); }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #007bff; padding-bottom: 10px; }
        .report-title { text-align: center; margin: 20px 0; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            font-size: 11px;
            table-layout: fixed;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 6px;
            text-align: center;
            word-wrap: break-word;
        }
        thead tr { background-color: #007bff; color: white; }
        th { font-size: 10px; }
        .class-header td { background-color: #f2f2f2; font-weight: bold; color: #333; }
        th:nth-child(1), td:nth-child(1) { width: 3%; }
        th:nth-child(2), td:nth-child(2) { width: 8%; }
        th:nth-child(3), td:nth-child(3) { width: 20%; text-align: right; }
        tr td:nth-child(n+4) { color: red; font-weight: bold; }
        tr td:last-child { background-color: #f8f9fa; font-weight: bold; }
        .stats { margin-top: 20px; padding: 15px; background-color: #e9ecef; border-radius: 5px; }
        @media print {
            body, .page { margin: 0; box-shadow: none; border: none; }
            .page { width: 100%; min-height: auto; }
        }
    """

    return f"""\n<!DOCTYPE html>\n<html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>{title} - {school_name}</title>
        <style>{style_css}</style>
    </head>
    <body>
        <div class="page">
            <div class="header">
                <div>{logo_html}</div>
                <div>
                    <div style="font-weight:bold">{school_name}</div>
                </div>
                <div></div>
            </div>
            <div class="report-title">
                <h2>{title}</h2>
                <p>{subtitle}</p>
            </div>
            <table>
                <thead><tr>{table_header_html}</tr></thead>
                <tbody>{table_rows_html}</tbody>
            </table>
            <div class="stats">
                <div><b>إجمالي السجلات:</b> {stats.get('total_absences', 0)}</div>
                <div><b>عدد الطلاب الفريدين:</b> {stats.get('total_unique_students', 0)}</div>
                <div><b>عدد الفصول:</b> {stats.get('total_classes', 0)}</div>
            </div>
            <div class="footer" style="margin-top:20px; font-size:12px; color:#666;">
                تم إنشاء التقرير بواسطة نظام الغياب.
            </div>
        </div>
    </body>
    </html>
    """


def query_absences_in_range(start_date: str, end_date: str, class_id: Optional[str] = None):
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    q, params = "SELECT * FROM absences WHERE date BETWEEN ? AND ?", [start_date, end_date]
    if class_id: q += " AND class_id = ?"; params.append(class_id)
    
    # استبعاد المستثنين
    q += " AND student_id NOT IN (SELECT student_id FROM exempted_students)"
    
    cur.execute(q + " ORDER BY date, class_id, student_name", params)
    rows = [dict(r) for r in cur.fetchall()]; con.close()
    return _apply_class_name_fix(rows)

def generate_daily_report(date_str: str, class_id: Optional[str] = None) -> str:
    absences = query_absences_in_range(date_str, date_str, class_id)
    if not absences: return "<html><body><h2>لا توجد بيانات غياب لهذا اليوم.</h2></body></html>"
    data_by_class = {}
    for i, r in enumerate(sorted(absences, key=lambda x: (x['class_name'], x['student_name']))):
        class_name = r.get('class_name', 'غير محدد')
        if class_name not in data_by_class: data_by_class[class_name] = []
        student_row = [i + 1, r.get('student_id', ''), r.get('student_name', ''), r.get('period', '')]
        data_by_class[class_name].append(student_row)
    stats = {"total_absences": len(absences), "total_unique_students": len(set(r['student_id'] for r in absences)), "total_classes": len(data_by_class)}
    title = f"تقرير الغياب اليومي لفصل: {list(data_by_class.keys())[0]}" if class_id and data_by_class else "تقرير الغياب اليومي للمدرسة"
    headers = ["م", "رقم الطالب", "اسم الطالب", "الحصة"]
    return generate_report_html(title, f"لتاريخ: {date_str}", data_by_class, stats, headers=headers)

def generate_monthly_report(date_str: str, class_id: Optional[str] = None) -> str:
    try:
        report_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return "<html><body><h2>صيغة التاريخ غير صالحة.</h2></body></html>"
    
    start_of_month = report_date.replace(day=1)
    next_month_start = (start_of_month + datetime.timedelta(days=32)).replace(day=1)
    end_of_month = next_month_start - datetime.timedelta(days=1)
    
    work_days = []
    current_day = start_of_month
    while current_day <= end_of_month:
        if current_day.weekday() not in [4, 5]:
            work_days.append(current_day)
        current_day += datetime.timedelta(days=1)
        
    if not work_days:
        return "<html><body><h2>لا توجد أيام عمل في هذا الشهر.</h2></body></html>"
    
    absences = query_absences_in_range(start_of_month.isoformat(), end_of_month.isoformat(), class_id)
    
    if not absences:
        return f"<html><body><h2>لا توجد بيانات غياب لشهر {start_of_month.strftime('%Y-%m')}.</h2></body></html>"

    student_summary = {}
    for r in absences:
        sid = r['student_id']
        if sid not in student_summary:
            student_summary[sid] = {
                'student_id': sid,
                'student_name': r['student_name'],
                'class_name': r.get('class_name', 'غير محدد'),
                'dates': set(),
                'total_count': 0
            }
        student_summary[sid]['dates'].add(r['date'])
        student_summary[sid]['total_count'] += 1

    data_by_class = {}
    sorted_students = sorted(student_summary.values(), key=lambda x: (x['class_name'], x['student_name']))
    
    for i, data in enumerate(sorted_students):
        class_name = data['class_name']
        if class_name not in data_by_class:
            data_by_class[class_name] = []
            
        student_row = [i + 1, data['student_id'], data['student_name']]
        
        day_marks = ['X' if d.isoformat() in data['dates'] else '' for d in work_days]
        student_row.extend(day_marks)
        
        student_row.append(data['total_count'])
        
        data_by_class[class_name].append(student_row)
        
    headers = ["م", "رقم الطالب", "اسم الطالب"] + [d.strftime('%d') for d in work_days] + ["المجموع"]
    stats = {
        "total_absences": len(absences),
        "total_unique_students": len(student_summary),
        "total_classes": len(data_by_class)
    }
    
    title = "تقرير الغياب الشهري للمدرسة"
    if class_id and data_by_class:
        title = f"تقرير الغياب الشهري لفصل: {list(data_by_class.keys())[0]}"
        
    month_name = start_of_month.strftime("%B")
    year = start_of_month.year
    subtitle = f"لشهر {month_name} {year}"
    
    return generate_report_html(title, subtitle, data_by_class, stats, headers=headers)


def generate_weekly_report(date_str: str, class_id: Optional[str] = None) -> str:
    try: report_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError: return "<html><body><h2>صيغة التاريخ غير صالحة.</h2></body></html>"
    start_of_week = report_date - datetime.timedelta(days=report_date.weekday())
    end_of_week = start_of_week + datetime.timedelta(days=6)
    start_str, end_str = start_of_week.isoformat(), end_of_week.isoformat()
    absences = query_absences_in_range(start_str, end_str, class_id)
    if not absences: return f"<html><body><h2>لا توجد بيانات غياب للأسبوع من {start_str} إلى {end_str}.</h2></body></html>"
    data_by_class = {}
    student_summary = {}
    for r in absences:
        sid = r['student_id']
        if sid not in student_summary:
            student_summary[sid] = {'student_id': sid, 'student_name': r['student_name'], 'class_name': r.get('class_name', 'غير محدد'), 'absence_count': 0, 'absence_dates': set()}
        student_summary[sid]['absence_count'] += 1
        student_summary[sid]['absence_dates'].add(r['date'])
    sorted_summary = sorted(student_summary.values(), key=lambda x: (x['class_name'], x['student_name']))
    for i, summary in enumerate(sorted_summary):
        class_name = summary['class_name']
        if class_name not in data_by_class: data_by_class[class_name] = []
        student_row = [i + 1, summary['student_id'], summary['student_name'], summary['absence_count'], ", ".join(sorted(list(summary['absence_dates'])))]
        data_by_class[class_name].append(student_row)
    stats = {"total_absences": len(absences), "total_unique_students": len(student_summary), "total_classes": len(data_by_class)}
    title = "التقرير الأسبوعي لغياب المدرسة"
    if class_id and data_by_class: title = f"التقرير الأسبوعي لغياب فصل: {list(data_by_class.keys())[0]}"
    subtitle = f"للأسبوع من {start_str} إلى {end_str}"
    headers = ["م", "رقم الطالب", "اسم الطالب", "عدد أيام الغياب", "التواريخ"]
    return generate_report_html(title, subtitle, data_by_class, stats, headers=headers)

def generate_student_report(student_id: str) -> str:
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    cur.execute("SELECT * FROM absences WHERE student_id = ? ORDER BY date DESC", [student_id])
    absences = [dict(r) for r in cur.fetchall()]; con.close()
    absences = _apply_class_name_fix(absences)

    if not absences:
        return "<html><body><h2>لا توجد سجلات غياب لهذا الطالب.</h2></body></html>"

    student_info = absences[0]
    student_name = student_info.get('student_name')
    class_name = student_info.get('class_name')

    report_rows = []
    for i, r in enumerate(absences):
        row = [
            i + 1,
            r.get('date'),
            r.get('class_name'),
            r.get('teacher_name', 'غير مسجل'),
            r.get('period', '-')
        ]
        report_rows.append(row)
    
    data_by_class = { "سجل الغياب": report_rows }

    total_absences = len(absences)
    periods = [r.get('period') for r in absences if r.get('period')]
    most_frequent_period = max(set(periods), key=periods.count) if periods else "N/A"
    
    stats = {
        "total_absences": total_absences,
        "most_frequent_period": most_frequent_period,
        "total_unique_students": 1,
        "total_classes": 1
    }

    title = f"تقرير الغياب المفصّل للطالب: {student_name}"
    subtitle = f"الرقم الأكاديمي: {student_id} | الفصل: {class_name}"
    headers = ["م", "التاريخ", "الفصل الدراسي", "المعلم", "الحصة"]
    
    report_html = generate_report_html(title, subtitle, data_by_class, stats, headers)
    custom_stats_html = f"""\n<div class="stats">
        <h3>ملخص إحصائي للطالب</h3>
        <p><strong>إجمالي أيام الغياب المسجلة:</strong> {stats.get('total_absences', 0)}</p>
        <p><strong>الحصة الأكثر غياباً (إن وجدت):</strong> {stats.get('most_frequent_period', 'لا يوجد')}</p>
    </div>
    """
    report_html = report_html.replace('<div class="stats">', custom_stats_html, 1)

    return report_html

#*****////////////////

def export_to_noor_excel(date_str: str, output_path: str):
    """
    تصدير غياب يوم معين إلى ملف Excel متوافق مع نظام نور المركزي.
    """
    # جلب الغيابات من قاعدة البيانات
    absences = query_absences(date_filter=date_str)
    if not absences:
        # تُستدعى من /web/api/noor-export أيضاً — نافذة حوار من خيط
        # الخادم تُجمّد الموقع بالكامل.
        import threading as _th
        if _th.current_thread() is _th.main_thread():
            messagebox.showinfo("تنبيه", "لا توجد غيابات لهذا اليوم.")
        else:
            print("[NOOR-EXPORT] لا توجد غيابات لهذا اليوم")
        return

    # تحويل إلى صيغة نور
    rows = []
    for r in absences:
        rows.append({
            "الرقم المدني أو الأكاديمي": r["student_id"],
            "التاريخ الميلادي": r["date"],  # يجب أن يكون YYYY-MM-DD
            "نوع الغياب": "غياب مباشر",
            "السبب": "",
            "اليوم الدراسي": "نعم",
            "الحصة": r.get("period", "كل اليوم")
        })

    # إنشاء DataFrame
    df = pd.DataFrame(rows)

    # التأكد من ترتيب الأعمدة كما في نور
    columns_order = [
        "الرقم المدني أو الأكاديمي",
        "التاريخ الميلادي",
        "نوع الغياب",
        "السبب",
        "اليوم الدراسي",
        "الحصة"
    ]
    df = df[columns_order]

    # حفظ كـ Excel
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name="غياب مباشر", index=False)
        
def get_live_monitor_status(date_str: str) -> List[Dict[str, Any]]:
    absences = query_absences(date_filter=date_str)
    
    recorded_slots = {}
    for r in absences:
        period = r.get('period')
        class_id = r.get('class_id')
        teacher_name = r.get('teacher_name')
        if period and class_id and teacher_name:
            recorded_slots[(period, class_id)] = teacher_name
            
    status_data = []
    all_classes = sorted(load_students()['list'], key=lambda x: x['id'])
    
    for period in range(1, 8):
        period_status = {'period': period, 'classes': []}
        for cls in all_classes:
            class_id = cls['id']
            slot_info = recorded_slots.get((period, class_id))
            
            if slot_info:
                status = {
                    'class_id': class_id,
                    'class_name': cls['name'],
                    'status': 'done',
                    'teacher_name': slot_info
                }
            else:
                status = {
                    'class_id': class_id,
                    'class_name': cls['name'],
                    'status': 'pending',
                    'teacher_name': 'بانتظار التسجيل'
                }
            period_status['classes'].append(status)
        status_data.append(period_status)
        
    return status_data

def generate_monitor_table_html(status_data: List[Dict[str, Any]]) -> str:
    if not status_data:
        return "<h3>لا توجد بيانات لعرضها</h3>"
    classes = status_data[0]['classes']
    class_headers_html = "".join(f"<th>{c['class_name']}</th>" for c in classes)
    table_rows_html = ""
    for period_data in status_data:
        row_html = f"<tr><td class='period-header'>الحصة {period_data['period']}</td>"
        for class_status in period_data['classes']:
            status_class = class_status['status']
            icon = '✔' if status_class == 'done' else '✖'
            teacher_name = class_status['teacher_name']
            row_html += f"""\n<td class='cell {status_class}'>\n<span class='status-icon'>{icon}</span>\n<span class='teacher-name'>{teacher_name}</span>\n</td>\n"""
        row_html += "</tr>"
        table_rows_html += row_html
    return f"""\n<!DOCTYPE html>\n<html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>مراقبة مدمجة</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap' );
            body {{ font-family: 'Cairo', sans-serif; background-color: #f4f7f6; margin: 0; padding: 10px; }}
            #last-update {{ text-align: center; color: #888; margin-bottom: 10px; font-size: 12px;}}
            table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
            th, td {{ border: 1px solid #ddd; text-align: center; vertical-align: middle; }}
            th {{ background-color: #e9ecef; padding: 10px; font-size: 12px; }}
            .period-header {{ font-weight: bold; font-size: 14px; width: 100px; }}
            .cell {{ height: 80px; padding: 8px; }}
            .cell.pending {{ background-color: #fff1f2; }}
            .cell.done {{ background-color: #f0fdf4; }}
            .teacher-name {{ font-weight: bold; font-size: 12px; display: block; }}
            .status-icon {{ font-size: 20px; }}
            .pending .status-icon {{ color: #c53030; }}
            .done .status-icon {{ color: #2f855a; }}
            .pending .teacher-name {{ color: #9f1239; }}
            .done .teacher-name {{ color: #166534; }}
        </style>
    </head>
    <body>
        <p id="last-update"></p>
        <table>
            <thead><tr><th class="period-header">الحصة</th>{class_headers_html}</tr></thead>
            <tbody>{table_rows_html}</tbody>
        </table>
    </body>
    </html>
    """

# ===================== FastAPI =====================

def generate_term_report_html(month_from: str = None, month_to: str = None) -> str:
    cfg       = load_config()
    school    = cfg.get("school_name","المدرسة")
    threshold = cfg.get("alert_absence_threshold",5)
    today     = now_riyadh_date()
    if not month_from or not month_to:
        now2      = datetime.datetime.now()
        month_to  = now2.strftime("%Y-%m")
        month_from= (now2-datetime.timedelta(days=120)).strftime("%Y-%m")

    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()

    cur.execute("""SELECT COUNT(DISTINCT date) as days,
                          COUNT(*) as total
                   FROM absences
                   WHERE substr(date,1,7)>=? AND substr(date,1,7)<=?
                   AND student_id NOT IN (SELECT student_id FROM exempted_students)""",
                (month_from, month_to))
    totals = dict(cur.fetchone() or {})

    cur.execute("""SELECT student_id, MAX(student_name) as name,
                          MAX(class_name) as class_name,
                          COUNT(DISTINCT date) as days,
                          MAX(date) as last_date
                   FROM absences
                   WHERE substr(date,1,7)>=? AND substr(date,1,7)<=?
                   AND student_id NOT IN (SELECT student_id FROM exempted_students)
                   GROUP BY student_id
                   ORDER BY days DESC LIMIT 30""", (month_from,month_to))
    top_abs = [dict(r) for r in cur.fetchall()]
    at_risk = [s for s in top_abs if s["days"] >= threshold]

    cur.execute("""SELECT class_id, MAX(class_name) as cn,
                          COUNT(DISTINCT student_id) as stu,
                          COUNT(DISTINCT date||student_id) as abs
                   FROM absences
                   WHERE substr(date,1,7)>=? AND substr(date,1,7)<=?
                   AND student_id NOT IN (SELECT student_id FROM exempted_students)
                   GROUP BY class_id ORDER BY abs DESC""", (month_from,month_to))
    cls_stats = [dict(r) for r in cur.fetchall()]

    cur.execute("""SELECT COUNT(*) as c FROM tardiness 
                   WHERE substr(date,1,7)>=? AND substr(date,1,7)<=?
                   AND student_id NOT IN (SELECT student_id FROM exempted_students)""",
                (month_from,month_to))
    tard_cnt = (cur.fetchone() or {"c":0})["c"]

    cur.execute("SELECT COUNT(*) as c FROM excuses WHERE substr(date,1,7)>=? AND substr(date,1,7)<=?",
                (month_from,month_to))
    exc_cnt = (cur.fetchone() or {"c":0})["c"]
    con.close()

    at_risk_rows = ""
    for i,s in enumerate(at_risk[:20],1):
        color = "#C62828" if s["days"]>=threshold*2 else "#E65100"
        at_risk_rows += "<tr><td>{}</td><td>{}</td><td>{}</td><td style='color:{};font-weight:bold'>{}</td><td>{}</td></tr>".format(
            i,s["name"],s["class_name"],color,s["days"],s["last_date"])

    cls_rows = ""
    for c in cls_stats:
        avg = round(c["abs"]/max(c["stu"],1),1)
        cls_rows += "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            c["cn"],c["stu"],c["abs"],avg)

    return """<!DOCTYPE html><html lang="ar" dir="rtl">
<head><meta charset="UTF-8"><title>تقرير الفصل — {school}</title>
<style>
body{{font-family:Arial,sans-serif;direction:rtl;padding:20px;color:#1a1a2e}}
h1{{color:#1565C0;text-align:center;border-bottom:3px solid #1565C0;padding-bottom:12px}}
.cards{{display:flex;gap:12px;margin:16px 0;flex-wrap:wrap}}
.card{{flex:1;min-width:120px;background:#F5F7FA;border-radius:8px;padding:12px;text-align:center;border:1px solid #DDE3EA}}
.card .v{{font-size:24px;font-weight:900;color:#1565C0}}
.card.r .v{{color:#C62828}}.card.w .v{{color:#E65100}}.card.g .v{{color:#2E7D32}}
h2{{color:#1565C0;margin:20px 0 8px;border-right:4px solid #1565C0;padding-right:8px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#1565C0;color:#fff;padding:8px;text-align:center}}
td{{padding:7px;border-bottom:1px solid #EEE;text-align:center}}
.footer{{text-align:center;color:#9CA3AF;margin-top:24px;font-size:11px}}
@media print{{.no-print{{display:none}}}}
</style></head><body>
<h1>تقرير نهاية الفصل الدراسي — {school}</h1>
<p style="text-align:center;color:#5A6A7E">الفترة: {mf} إلى {mt} | تاريخ الإصدار: {today}</p>
<div class="no-print" style="text-align:center;margin:12px 0">
<button onclick="window.print()" style="padding:8px 20px;background:#1565C0;color:#fff;border:none;border-radius:6px;font-size:14px;cursor:pointer">🖨️ طباعة</button></div>
<div class="cards">
<div class="card"><div class="v">{days}</div><div>أيام دراسة</div></div>
<div class="card r"><div class="v">{total}</div><div>إجمالي الغياب</div></div>
<div class="card w"><div class="v">{tard}</div><div>حالات التأخر</div></div>
<div class="card g"><div class="v">{exc}</div><div>الأعذار</div></div>
<div class="card r"><div class="v">{risk}</div><div>عالي الخطورة +{thr} يوم</div></div>
</div>
<h2>الطلاب عالي الخطورة</h2>
<table><tr><th>#</th><th>الطالب</th><th>الفصل</th><th>أيام الغياب</th><th>آخر غياب</th></tr>
{at_risk_rows}</table>
<h2>إحصائيات الفصول</h2>
<table><tr><th>الفصل</th><th>الطلاب</th><th>إجمالي الغياب</th><th>متوسط/طالب</th></tr>
{cls_rows}</table>
<div class="footer">DarbStu — {school} — {today}</div>
</body></html>""".format(
        school=school, mf=month_from, mt=month_to, today=today,
        days=totals.get("days",0), total=totals.get("total",0),
        tard=tard_cnt, exc=exc_cnt, risk=len(at_risk), thr=threshold,
        at_risk_rows=at_risk_rows, cls_rows=cls_rows)


# ═══════════════════════════════════════════════════════════════
# الإشعارات الذكية المحسّنة — أنماط الغياب المشبوهة
# ═══════════════════════════════════════════════════════════════

def detect_suspicious_patterns(months_back: int = 2) -> List[Dict]:
    """
    يكتشف أنماط الغياب المشبوهة:
    ١. الغياب يوم الأحد باستمرار (بداية الأسبوع)
    ٢. الغياب يوم الخميس باستمرار (نهاية الأسبوع)
    ٣. غياب أكثر من 30% من فصل في نفس اليوم
    """
    since = (datetime.date.today() - datetime.timedelta(days=months_back*30)).isoformat()
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()

    results = []

    # ─ نمط ١ و٢: طالب يغيب نفس اليوم باستمرار
    cur.execute("""SELECT student_id, MAX(student_name) as name,
                          MAX(class_name) as class_name,
                          date
                   FROM absences 
                   WHERE date >= ?
                   AND student_id NOT IN (SELECT student_id FROM exempted_students)
                   GROUP BY student_id, date""", (since,))
    all_abs = cur.fetchall()

    from collections import defaultdict
    student_days = defaultdict(lambda: defaultdict(int))
    student_info = {}
    for r in all_abs:
        try:
            dt  = datetime.date.fromisoformat(r["date"])
            dow = (dt.weekday() + 1) % 7  # 0=Sunday
            student_days[r["student_id"]][dow] += 1
            student_info[r["student_id"]] = {
                "name": r["name"], "class_name": r["class_name"]}
        except: pass

    DAY_NAMES = {0:"الأحد", 1:"الاثنين", 2:"الثلاثاء",
                 3:"الأربعاء", 4:"الخميس"}

    for sid, days in student_days.items():
        for dow, count in days.items():
            if dow in (0, 4) and count >= 3:  # أحد أو خميس ≥ 3 مرات
                results.append({
                    "type":       "repeated_day",
                    "student_id": sid,
                    "name":       student_info[sid]["name"],
                    "class_name": student_info[sid]["class_name"],
                    "day":        DAY_NAMES.get(dow, ""),
                    "count":      count,
                    "desc": "يغيب يوم {} بشكل متكرر ({} مرة)".format(
                        DAY_NAMES.get(dow,""), count),
                })

    # ─ نمط ٣: غياب جماعي — أكثر من 30% من فصل في نفس اليوم
    cur.execute("""SELECT date, class_id, MAX(class_name) as cn,
                          COUNT(DISTINCT student_id) as absent_count
                   FROM absences 
                   WHERE date >= ?
                   AND student_id NOT IN (SELECT student_id FROM exempted_students)
                   GROUP BY date, class_id
                   HAVING absent_count >= 5""", (since,))
    mass_abs = cur.fetchall()

    # عدد طلاب كل فصل
    store = load_students()
    cls_size = {c["id"]: len(c["students"]) for c in store["list"]}

    for r in mass_abs:
        total = cls_size.get(r["class_id"], 0)
        if total > 0:
            pct = r["absent_count"] / total * 100
            if pct >= 30:
                results.append({
                    "type":       "mass_absence",
                    "class_id":   r["class_id"],
                    "class_name": r["cn"],
                    "date":       r["date"],
                    "count":      r["absent_count"],
                    "pct":        round(pct, 1),
                    "desc": "غياب جماعي: {}% من {} بتاريخ {}".format(
                        round(pct,1), r["cn"], r["date"]),
                })

    con.close()
    return results


# ═══════════════════════════════════════════════════════════════
# لوحة ولي الأمر — رابط شخصي لكل ولي
# ═══════════════════════════════════════════════════════════════

def parent_portal_html(student_id: str) -> str:
    """صفحة HTML شخصية لولي الأمر — تعرض سجل ابنه فقط."""
    store = load_students()
    student = None
    cls_name = ""
    for cls in store["list"]:
        for s in cls["students"]:
            if s["id"] == student_id:
                student  = s
                cls_name = cls["name"]
                break

    if not student:
        return "<h2>الطالب غير موجود</h2>"

    cfg       = load_config()
    school    = cfg.get("school_name","المدرسة")
    threshold = cfg.get("alert_absence_threshold",5)
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()

    cur.execute("""SELECT date, period FROM absences
                   WHERE student_id=? ORDER BY date DESC LIMIT 30""",
                (student_id,))
    abs_rows = cur.fetchall()

    cur.execute("""SELECT substr(date,1,7) as m, COUNT(DISTINCT date) as d
                   FROM absences WHERE student_id=?
                   GROUP BY m ORDER BY m DESC LIMIT 6""", (student_id,))
    monthly = cur.fetchall()

    cur.execute("""SELECT date, minutes_late FROM tardiness
                   WHERE student_id=? ORDER BY date DESC LIMIT 20""",
                (student_id,))
    tard_rows = cur.fetchall()

    cur.execute("""SELECT date, reason, status FROM permissions
                   WHERE student_id=? ORDER BY date DESC LIMIT 10""",
                (student_id,))
    perm_rows = cur.fetchall()
    con.close()

    total_abs = len(set(r["date"] for r in abs_rows))
    abs_color = "#C62828" if total_abs >= threshold else "#1565C0"

    abs_html = "".join(
        "<tr><td>{}</td><td>الحصة {}</td></tr>".format(r["date"], r["period"] or "—")
        for r in abs_rows)

    tard_html = "".join(
        "<tr><td>{}</td><td>{} دقيقة</td></tr>".format(r["date"], r["minutes_late"])
        for r in tard_rows)

    perm_html = "".join(
        "<tr><td>{}</td><td>{}</td><td style='color:{}'>{}</td></tr>".format(
            r["date"], r["reason"] or "—",
            "#2E7D32" if r["status"]=="موافق" else "#C62828",
            r["status"])
        for r in perm_rows)

    monthly_bars = ""
    max_days = max((r["d"] for r in monthly), default=1)
    for r in reversed(list(monthly)):
        pct = int(r["d"] / max_days * 100)
        color = "#C62828" if r["d"] >= threshold else "#1565C0"
        monthly_bars += """
        <div style="display:flex;align-items:center;gap:8px;margin:4px 0">
          <span style="width:60px;font-size:12px">{m}</span>
          <div style="background:{c};height:18px;width:{p}%;min-width:4px;border-radius:3px"></div>
          <span style="font-size:12px;font-weight:bold;color:{c}">{d} يوم</span>
        </div>""".format(m=r["m"], c=color, p=pct, d=r["d"])

    return """<!DOCTYPE html><html lang="ar" dir="rtl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>سجل {name} — {school}</title>
<style>
body{{font-family:Arial,sans-serif;direction:rtl;margin:0;background:#F5F7FA;color:#1a1a2e}}
.hdr{{background:#1565C0;color:#fff;padding:16px;text-align:center}}
.hdr h1{{margin:0;font-size:20px}}.hdr p{{margin:4px 0;opacity:.85;font-size:13px}}
.cards{{display:flex;gap:10px;padding:12px;flex-wrap:wrap}}
.card{{flex:1;min-width:100px;background:#fff;border-radius:8px;padding:12px;
       text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.card .v{{font-size:26px;font-weight:900}}.card .l{{font-size:11px;color:#5A6A7E;margin-top:4px}}
.section{{background:#fff;margin:8px 12px;border-radius:8px;padding:12px;
           box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.section h2{{font-size:14px;color:#1565C0;margin:0 0 10px;
             border-right:3px solid #1565C0;padding-right:8px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#E3F2FD;padding:7px;text-align:center;color:#1565C0}}
td{{padding:6px 8px;border-bottom:1px solid #EEE;text-align:center}}
</style></head>
<body>
<div class="hdr">
  <h1>{name}</h1>
  <p>{cls_name} — {school}</p>
</div>
<div class="cards">
  <div class="card"><div class="v" style="color:{abs_color}">{total_abs}</div>
    <div class="l">أيام الغياب</div></div>
  <div class="card"><div class="v" style="color:#E65100">{tard_cnt}</div>
    <div class="l">حالات التأخر</div></div>
  <div class="card"><div class="v" style="color:#0277BD">{perm_cnt}</div>
    <div class="l">طلبات استئذان</div></div>
</div>
<div class="section">
  <h2>الغياب الشهري</h2>
  {monthly_bars}
</div>
<div class="section">
  <h2>سجل الغياب (آخر 30)</h2>
  <table><tr><th>التاريخ</th><th>الحصة</th></tr>{abs_html}</table>
</div>
{tard_section}
{perm_section}
<p style="text-align:center;color:#9CA3AF;font-size:11px;padding:12px">
{school} — تم إنشاء هذه الصفحة تلقائياً</p>
</body></html>""".format(
        name=student["name"], school=school, cls_name=cls_name,
        abs_color=abs_color, total_abs=total_abs,
        tard_cnt=len(tard_rows), perm_cnt=len(perm_rows),
        monthly_bars=monthly_bars, abs_html=abs_html or "<tr><td colspan='2'>لا يوجد غياب</td></tr>",
        tard_section='<div class="section"><h2>سجل التأخر</h2><table><tr><th>التاريخ</th><th>الدقائق</th></tr>{}</table></div>'.format(tard_html) if tard_rows else "",
        perm_section='<div class="section"><h2>طلبات الاستئذان</h2><table><tr><th>التاريخ</th><th>السبب</th><th>الحالة</th></tr>{}</table></div>'.format(perm_html) if perm_rows else "",
    )


# ═══════════════════════════════════════════════════════════════
# نشر نتائج الطلاب من PDF
# ═══════════════════════════════════════════════════════════════

