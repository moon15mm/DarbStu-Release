# -*- coding: utf-8 -*-
"""
bus_scheduler.py — إرسال روابط الباصات تلقائياً في الأوقات المحددة
يتحقق كل دقيقة ويتخطى الجمعة والسبت والإجازات الرسمية.
"""
import threading
import datetime

_sent_today: set = set()  # {"{date}_{trip_type}"}


def _send_all_bus_links(trip_type: str):
    """ترسل روابط الباص لجميع السائقين النشطين."""
    try:
        from database import get_all_buses, get_students_in_bus, get_or_create_bus_trip, mark_bus_trip_sent
        from whatsapp_service import send_whatsapp_message
        from config_manager import load_config
        from constants import now_riyadh_date

        cfg      = load_config()
        base_url = cfg.get("public_url", "").rstrip("/")
        date_str = now_riyadh_date()
        buses    = get_all_buses()
        labels   = {"morning": "الذهاب", "afternoon": "العودة"}
        label    = labels.get(trip_type, trip_type)

        for bus in buses:
            if not bus.get("driver_phone"):
                continue
            if not get_students_in_bus(bus["id"]):
                continue
            trip  = get_or_create_bus_trip(bus["id"], date_str, trip_type)
            token = trip["token"]
            url   = f"{base_url}/bus/checkin/{token}"
            msg   = (
                f"🚌 مدرسة الدرب الثانوية\n"
                f"رسالة تسجيل حضور الطلاب\n\n"
                f"الباص: {bus['name']}\n"
                f"رحلة: {label}\n"
                f"التاريخ: {date_str}\n\n"
                f"افتح الرابط لتسجيل الطلاب:\n{url}"
            )
            ok, _ = send_whatsapp_message(bus["driver_phone"], msg)
            if ok:
                mark_bus_trip_sent(trip["id"])
            print(f"[BUS-SCHED] {bus['name']} — {label} — {'✓' if ok else '✗'}")
    except Exception as e:
        print(f"[BUS-SCHED-ERROR] {e}")


def schedule_bus_checkin(root_widget):
    """يُجدول إرسال روابط الباصات عبر Tkinter root.after — يتبع نمط schedule_daily_alerts."""

    def check_and_run():
        try:
            from config_manager import load_config
            from database import is_school_day
            from constants import now_riyadh_date

            cfg = load_config()
            if not cfg.get("bus_schedule_enabled", False):
                root_widget.after(120_000, check_and_run)
                return

            now      = datetime.datetime.now()
            date_str = now_riyadh_date()

            # تخطَّ الجمعة والسبت
            if now.weekday() in {4, 5}:
                root_widget.after(3_600_000, check_and_run)
                return

            # تخطَّ الإجازات الرسمية
            if not is_school_day(date_str):
                root_widget.after(3_600_000, check_and_run)
                return

            morning_time   = cfg.get("bus_morning_time",   "06:30")
            afternoon_time = cfg.get("bus_afternoon_time", "12:30")

            for trip_type, t_str in [("morning", morning_time), ("afternoon", afternoon_time)]:
                t_h, t_m = map(int, t_str.split(":"))
                key = f"{date_str}_{trip_type}"
                if now.hour == t_h and now.minute == t_m and key not in _sent_today:
                    _sent_today.add(key)
                    threading.Thread(
                        target=lambda tt=trip_type: _send_all_bus_links(tt),
                        daemon=True
                    ).start()

        except Exception as e:
            print(f"[BUS-SCHED] {e}")

        root_widget.after(60_000, check_and_run)

    root_widget.after(45_000, check_and_run)  # ابدأ بعد 45 ثانية من تشغيل البرنامج
