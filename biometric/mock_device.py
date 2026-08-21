# -*- coding: utf-8 -*-
"""
mock_device.py — محاكي جهاز بصمة، للاختبار بلا عتاد.

يحقّق واجهة ZKDevice نفسها (test_connection, read_punches) فيمرّ عبره
مسار السحب والمطابقة والتسجيل كاملاً — تماماً كما بنى منافسٌ محاكيَ نور
ليختبر إضافته دون لمس نور. هكذا نتحقّق اليوم أن اللوحة والخيط وقاعدة
التأخر تعمل، ثم لا يبقى عند وصول الجهاز غداً إلا تبديل protocol إلى zk.

مصدر بصماته: قائمة تُحقن عبر feed()، أو توليد من طلاب المدرسة الحاليين
حين mode="students" — فيبدو كأن طلاباً حقيقيين بصموا صباح اليوم.
"""
import datetime

_RIYADH = datetime.timedelta(hours=3)


class MockDevice:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.device_id = str(self.cfg.get("device_id") or "mock")
        self._queue = list(self.cfg.get("punches") or [])

    def feed(self, uid, when_local=None):
        """يحقن بصمة: uid ووقت محلي (افتراضياً الآن بتوقيت الرياض)."""
        if when_local is None:
            when_local = datetime.datetime.utcnow() + _RIYADH
        self._queue.append({
            "uid": str(uid),
            "punch_local": when_local.replace(microsecond=0).isoformat(),
            "punch_utc": (when_local - _RIYADH).replace(
                microsecond=0).isoformat(),
        })

    def seed_from_students(self, count=8, base_time="07:12"):
        """
        يولّد بصمات لأول عدد من طلاب المدرسة عند وقتٍ متأخّر قليلاً —
        فيُنتج تأخراً حقيقياً يسير في مسار الإشعارات كاملاً.
        """
        try:
            from database import load_students
        except Exception:
            return 0
        store = load_students()
        today = (datetime.datetime.utcnow() + _RIYADH).date()
        hh, mm = [int(x) for x in base_time.split(":")]
        n = 0
        for c in store.get("list", []):
            for s in c.get("students", []):
                # كل طالب يبصم بعد الآخر بدقيقة، لتبدو طابوراً واقعياً
                t = datetime.datetime(today.year, today.month, today.day,
                                      hh, mm) + datetime.timedelta(minutes=n)
                self.feed(s["id"], t)
                n += 1
                if n >= count:
                    return n
        return n

    def test_connection(self):
        return {"name": "MOCK-DEVICE", "serial": "MOCK-0001",
                "platform": "simulator", "firmware": "mock-1.0"}

    # ── محاكاة التسجيل ────────────────────────────────────────
    # يُنجح دائماً، فيمرّ عبره مسار صفحة التسجيل كاملاً بلا عتاد.
    def set_user(self, uid, name=""):
        return True

    def start_enroll(self, uid, finger=0):
        return True

    def cancel_capture(self):
        pass

    def enroll_student(self, uid, name="", finger=0):
        return {"ok": True, "stage": "capturing", "mock": True}

    def read_punches(self, after_utc=None):
        after_dt = None
        if after_utc:
            try:
                after_dt = datetime.datetime.fromisoformat(
                    after_utc.replace("Z", ""))
            except Exception:
                after_dt = None
        out = []
        for p in self._queue:
            if after_dt:
                try:
                    if datetime.datetime.fromisoformat(
                            p["punch_utc"]) <= after_dt:
                        continue
                except Exception:
                    pass
            out.append(dict(p))
        return out

    def get_users_and_fingerprints(self):
        try:
            from database import get_fp_enrolled_ids
            enrolled = get_fp_enrolled_ids()
            users_map = {sid: {"uid": 1, "name": f"Mock {sid}", "user_id": sid} for sid in enrolled}
            return users_map, set(enrolled)
        except Exception:
            return {}, set()

    def bulk_upload_students(self, students_list: list) -> tuple:
        return len(students_list), 0

    def delete_user(self, user_id="", uid=0):
        """محاكاة حذف مستخدم — يُنجح دائماً (لا عتاد)."""
        return True
