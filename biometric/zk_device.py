# -*- coding: utf-8 -*-
"""
zk_device.py — عميل ZKTeco بنفس آلية مشروع MB2000.

الأولوية في الاتصال:
1. استخدام مكتبة pyzk بـ ommit_ping=True (تجاوز Ping).
2. جرب TCP ثم UDP تلقائياً.
3. الطبقة الاحتياطية: السوكيت المباشر.
"""
import datetime
import os
import socket
import struct
import sys
import time

PORT = 4370
_TCP_MAGIC = (0x5050, 0x827D)
_RIYADH = datetime.timedelta(hours=3)

# ثوابت أوامر ZKTeco
CMD_CONNECT = 1000
CMD_EXIT = 1001
CMD_ENABLEDEVICE = 1002
CMD_DISABLEDEVICE = 1003
CMD_AUTH = 1102


def _make_packet(command, session=0, reply=0, data=b''):
    buf = struct.pack('<4H', command, 0, session, reply) + data
    s, i, n = 0, 0, len(buf)
    while n > 1:
        s += struct.unpack('<H', buf[i:i+2])[0]
        i += 2
        n -= 2
        s = s if s <= 0xFFFF else s - 0xFFFF
    if n:
        s += buf[-1]
    while s > 0xFFFF:
        s -= 0xFFFF
    s = ~s
    while s < 0:
        s += 0xFFFF
    return struct.pack('<4H', command, s & 0xFFFF, session, reply) + data


# ── قاموس وترجمة الأسماء العربية بنفس آلية مشروع MB2000 ──────────────────────
ARABIC_NAME_MAP = {
    "عمر": "Omar", "يوسف": "Yousef", "صالح": "Saleh", "سلطان": "Sultan", "خالد": "Khaled",
    "محمد": "Muhammad", "عبدالله": "Abdullah", "عبدالرحمن": "Abdulrahman", "عبدالعزيز": "Abdulaziz",
    "سعد": "Saad", "حسن": "Hassan", "فهد": "Fahad", "علي": "Ali", "سعيد": "Saeed",
    "أحمد": "Ahmad", "احمد": "Ahmad", "إبراهيم": "Ibrahim", "ابراهيم": "Ibrahim",
    "فيصل": "Faisal", "راكان": "Rakan", "زياد": "Ziyad", "تركي": "Turki", "وليد": "Waleed",
    "ماجد": "Majed", "نايف": "Naif", "بندر": "Bandar", "مشعل": "Meshal", "معاذ": "Moath",
    "سلمان": "Salman", "حمد": "Hamad", "أنس": "Anas", "انس": "Anas", "يزيد": "Yazeed",
    "سعود": "Saud", "طلال": "Talal", "راشد": "Rashed", "نواف": "Nawaf", "ناصر": "Nasser",
    "الخالدي": "Al-Khaldi", "المالكي": "Al-Malki", "المطيري": "Al-Mutairi", "العتيبي": "Al-Otaibi",
    "السبيعي": "Al-Subaie", "الغامدي": "Al-Ghamdi", "الجهني": "Al-Juhani", "الحربي": "Al-Harbi",
    "الرشيدي": "Al-Rashidi", "العنزي": "Al-Anazi", "الشمري": "Al-Shammari", "الأحمدي": "Al-Ahmadi",
    "الاحمدي": "Al-Ahmadi", "البقمي": "Al-Bqami", "الزهراني": "Al-Zahrani", "الشهري": "Al-Shehri",
    "الدوسري": "Al-Dawsari", "العمري": "Al-Omari", "القحطاني": "Al-Qahtani",
    # أسماء إضافية
    "عبدالكريم": "Abdulkarim", "عبدالواحد": "Abdulwahid", "عبدالمجيد": "Abdulmajid",
    "ياسر": "Yaser", "بدر": "Badr", "رشيد": "Rashid", "مبارك": "Mubarak",
    "جاسم": "Jasim", "جابر": "Jaber", "هاني": "Hani", "عادل": "Adel",
    "وائل": "Wail", "أيمن": "Ayman", "سامي": "Sami", "امين": "Amin", "أمين": "Amin",
    "كريم": "Karim", "منصور": "Mansoor", "غانم": "Ghanem", "ساعد": "Saed",
    "القرني": "Al-Qarni", "السعدي": "Al-Saadi", "العسيري": "Al-Asiri",
    "البلوي": "Al-Balawi", "المزروعي": "Al-Mazroui", "الرويلي": "Al-Ruwaili",
    "الثبيتي": "Al-Thubayti", "العصيمي": "Al-Osaimi", "الصاعدي": "Al-Saedi",
    "بن": "Bin", "آل": "Al",
}

_CHAR_MAP = {
    'أ': 'A', 'إ': 'I', 'آ': 'A', 'ا': 'A', 'ب': 'B', 'ت': 'T', 'ث': 'Th',
    'ج': 'J', 'ح': 'H', 'خ': 'Kh', 'د': 'D', 'ذ': 'Dh', 'ر': 'R', 'ز': 'Z',
    'س': 'S', 'ش': 'Sh', 'ص': 'S', 'ض': 'D', 'ط': 'T', 'ظ': 'Z', 'ع': 'A',
    'غ': 'Gh', 'ف': 'F', 'ق': 'Q', 'ك': 'K', 'ل': 'L', 'م': 'M', 'ن': 'N',
    'ه': 'H', 'و': 'W', 'ي': 'Y', 'ى': 'a', 'ئ': 'Y', 'ء': '', 'ة': 'h',
}


def transliterate_arabic_name(name: str) -> str:
    """ترجمة اسم طالب عربي لإنجليزي لعرضه على شاشة جهاز ZKTeco (آلية MB2000)."""
    if not name:
        return ""
    words = name.strip().split()
    translated = []
    for w in words:
        w = w.strip()
        if not w:
            continue
        if w in ARABIC_NAME_MAP:
            translated.append(ARABIC_NAME_MAP[w])
        else:
            result = "".join(_CHAR_MAP.get(c, c) for c in w)
            translated.append(result.capitalize())

    if len(translated) >= 3:
        first = translated[0]
        last = translated[-1]
        middles = " ".join(m[0] + "." for m in translated[1:-1] if m)
        full = f"{first} {middles} {last}"
    else:
        full = " ".join(translated)

    return full[:24]

# ── إضافة مسارات pyzk للـ sys.path ──────────────────────────────────────────
def _inject_pyzk_paths():
    """يُضيف مواقع pyzk المحتملة إلى sys.path مرة واحدة."""
    import os, sys, shutil

    candidates = []
    # user AppData (pip install --user)
    for ver in ["Python311", "Python310", "Python39", "Python312", "Python38"]:
        candidates.append(
            os.path.join(os.environ.get("APPDATA", ""), "Python", ver, "site-packages")
        )
    # Python مثبّت على مستوى النظام
    for root in [r"C:\Python311", r"C:\Python310", r"C:\Python39",
                 r"C:\Program Files\Python311", r"C:\Program Files\Python310"]:
        candidates.append(os.path.join(root, "Lib", "site-packages"))

    # _internal بجانب الـ EXE
    exe_dir = os.path.dirname(sys.executable)
    _internal = os.path.join(exe_dir, "_internal")
    candidates.append(_internal)
    candidates.append(exe_dir)

    # مجلد التطبيق نفسه (للتشغيل من المصدر)
    app_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(os.path.dirname(app_dir), "_internal"))
    candidates.append(app_dir)

    # إضافة كل مسار صالح
    for c in candidates:
        zk_mod = os.path.join(c, "zk", "__init__.py")
        if os.path.isfile(zk_mod) and c not in sys.path:
            sys.path.insert(0, c)

    # إذا وُجد _internal/zk ولكن base.py غائب، انسخه من AppData
    internal_zk = os.path.join(_internal, "zk")
    internal_base = os.path.join(internal_zk, "base.py")
    if os.path.isdir(internal_zk) and not os.path.isfile(internal_base):
        for ver in ["Python311", "Python310", "Python39", "Python312", "Python38"]:
            src_base = os.path.join(
                os.environ.get("APPDATA", ""),
                "Python", ver, "site-packages", "zk", "base.py"
            )
            if os.path.isfile(src_base):
                try:
                    shutil.copy2(src_base, internal_base)
                except Exception:
                    pass
                break

_inject_pyzk_paths()

# ── محاولة استيراد pyzk ──────────────────────────────────────────────────────
_HAS_PYZK = False
try:
    from zk import ZK as _ZK
    _HAS_PYZK = True
except ImportError:
    _ZK = None


def _ensure_pyzk() -> bool:
    global _HAS_PYZK, _ZK
    if _HAS_PYZK:
        return True
    try:
        import subprocess
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyzk", "zk", "--user"],
            capture_output=True, timeout=40
        )
    except Exception:
        pass
    # إعادة إضافة المسارات بعد التثبيت
    _inject_pyzk_paths()
    try:
        from zk import ZK as _ZK_new
        _ZK = _ZK_new
        _HAS_PYZK = True
        return True
    except ImportError:
        return False


# ── أخطاء ───────────────────────────────────────────────────────────────────
class ZKError(Exception):
    pass


# ── ZKDevice ─────────────────────────────────────────────────────────────────
class ZKDevice:
    """
    كائن جهاز ZK بآلية MB2000 (pyzk + ommit_ping=True + fallback سوكيت).
    """

    def __init__(self, cfg: dict, timeout: int = 5):
        self.ip = (cfg.get("ip") or "").strip()
        self.port = int(cfg.get("port") or PORT)
        self.comm_key = int(cfg.get("comm_key") or 0)
        self.device_id = str(cfg.get("device_id") or self.ip)
        self.protocol = str(cfg.get("protocol") or "zk").lower()
        self.timeout = timeout

        self._zk_inst = None   # كائن pyzk ZK
        self.conn = None        # الاتصال المفتوح pyzk
        self._sock = None       # سوكيت احتياطي
        self._session = 0
        self._reply = 0
        self._is_udp = "udp" in self.protocol

    # ── الاتصال (آلية MB2000 المباشرة الموثوقة) ───────────────────────────────
    def connect(self):
        if not self.ip:
            raise ZKError("لا عنوان IP للجهاز")

        _ensure_pyzk()

        if not (_HAS_PYZK and _ZK is not None):
            raise ZKError(
                "مكتبة pyzk غير متاحة — تحقق من التثبيت.\n"
                "افتح CMD وشغّل: pip install pyzk"
            )

        if self.conn:
            return True

        force_udp = "udp" in self.protocol
        try:
            self._zk_inst = _ZK(
                self.ip,
                port=self.port,
                timeout=self.timeout,
                password=self.comm_key,
                force_udp=force_udp,
                ommit_ping=True
            )
            self.conn = self._zk_inst.connect()
            self._is_udp = force_udp
            return True
        except Exception as e:
            self.conn = None
            self._zk_inst = None
            raise ZKError(f"تعذّر الاتصال بالجهاز: {e}")

    def disconnect(self):
        if self.conn:
            try:
                self.conn.enable_device()
            except Exception:
                pass
            try:
                self.conn.disconnect()
            except Exception:
                pass
            self.conn = None
            self._zk_inst = None
        self._native_disconnect()

    # ── معلومات الجهاز ───────────────────────────────────────────────────────
    def info(self) -> dict:
        if self.conn:
            try:
                return {
                    "name": str(self.conn.get_device_name() or "ZKTeco"),
                    "serial": str(self.conn.get_serialnumber() or "N/A"),
                    "firmware": str(self.conn.get_firmware_version() or "N/A"),
                    "platform": str(self.conn.get_platform() or "ZKTeco"),
                }
            except Exception:
                pass
        return self._native_info()

    def test_connection(self) -> dict:
        """فحص الاتصال الفوري ويُرجع dict بمعلومات الجهاز."""
        self.connect()
        try:
            return self.info()
        finally:
            self.disconnect()

    # ── سحب البصمات ──────────────────────────────────────────────────────────
    def read_punches(self, after_utc=None) -> list:
        self.connect()
        try:
            after_dt = None
            if after_utc:
                try:
                    after_dt = datetime.datetime.fromisoformat(
                        after_utc.replace("Z", ""))
                except Exception:
                    pass

            attendance = self.conn.get_attendance()
            out = []
            for att in attendance:
                local_dt = att.timestamp
                punch_utc = local_dt - _RIYADH
                if after_dt and punch_utc <= after_dt:
                    continue
                out.append({
                    "uid": str(att.user_id).strip(),
                    "punch_utc": punch_utc.isoformat(timespec="seconds"),
                    "punch_local": local_dt.isoformat(timespec="seconds"),
                })
            return out
        finally:
            self.disconnect()

    # ── رفع مستخدم ───────────────────────────────────────────────────────────
    def set_user(self, uid, name="") -> bool:
        """يرفع مستخدم (رقم أكاديمي + اسم) للجهاز باستخدام pyzk."""
        self.conn.set_user(
            uid=int(uid) & 0xFFFF,
            name=(name or str(uid))[:24],
            privilege=0,
            password='',
            group_id='',
            user_id=str(uid)
        )
        return True

    def _get_device_uid(self, user_id_str: str) -> int:
        """يبحث عن uid الجهاز الداخلي من رقم المستخدم (الرقم الأكاديمي)."""
        try:
            users = self.conn.get_users()
            for u in users:
                if str(u.user_id).strip() == user_id_str:
                    return u.uid
        except Exception:
            pass
        # إذا لم يوجد، استخدم الرقم مباشرةً
        try:
            return int(user_id_str) & 0xFFFF
        except Exception:
            return 1

    def _delete_fingerprints(self, uid_int: int):
        """يحذف قوالب البصمة القديمة قبل إعادة التسجيل (آلية MB2000)."""
        if not hasattr(self.conn, 'delete_user_template'):
            return
        for fid in range(10):
            try:
                self.conn.delete_user_template(uid=uid_int, temp_id=fid)
            except Exception:
                pass

    def start_enroll(self, uid, finger=0) -> bool:
        """يأمر الجهاز ببدء التقاط بصمة المستخدم."""
        return self.conn.enroll_user(
            uid=int(uid) & 0xFFFF,
            temp_id=int(finger),
            user_id=str(uid)
        )

    def enroll_student(self, uid, name="", finger=0) -> dict:
        """تسجيل بصمة طالب — آلية سريعة وموثوقة (MB2000)."""
        eng_name = transliterate_arabic_name(name) if name else str(uid)
        uid_str = str(uid).strip()
        try:
            uid_num = int(uid_str) & 0xFFFF
        except Exception:
            uid_num = 1

        self.connect()
        try:
            # 1. إلغاء أي التقاط سابق معلق على الحساس
            if hasattr(self.conn, 'cancel_capture'):
                try:
                    self.conn.cancel_capture()
                except Exception:
                    pass

            # 2. إنشاء/تحديث المستخدم بالاسم الإنجليزي
            self.set_user(uid_str, eng_name)

            # 3. مسح القالب السابق لهذا الإصبع إن وجد لإتاحة إعادة التسجيل
            if hasattr(self.conn, 'delete_user_template'):
                try:
                    self.conn.delete_user_template(uid=uid_num, temp_id=int(finger))
                except Exception:
                    pass

            # 4. تفعيل وضع التقاط البصمة على الجهاز
            self.conn.enroll_user(
                uid=uid_num,
                temp_id=int(finger),
                user_id=uid_str
            )
            return {"ok": True, "stage": "capturing", "name_on_device": eng_name}
        except Exception as e:
            return {"ok": False, "stage": "enroll", "error": str(e)}
        finally:
            self.disconnect()

    def bulk_upload_students(self, students_list: list) -> tuple:
        """
        يرفع قائمة طلاب (رقم أكاديمي + اسم) دفعة واحدة إلى جهاز البصمة (مستنسخ من MB2000).
        students_list: [{"academic_no": "1001", "name": "عمر الخالدي"}, ...]
        """
        self.connect()
        success_count = 0
        fail_count = 0
        try:
            try:
                self.conn.disable_device()
            except Exception:
                pass

            for std in students_list:
                acc_no = str(std.get("academic_no", "")).strip()
                name = std.get("name", "")
                if acc_no:
                    try:
                        eng_name = transliterate_arabic_name(name) if name else acc_no
                        self.set_user(acc_no, eng_name)
                        success_count += 1
                    except Exception as e:
                        fail_count += 1
                        print(f"[ZKDevice] bulk_upload error for {acc_no}: {e}")

            try:
                self.conn.enable_device()
            except Exception:
                pass

            return success_count, fail_count
        finally:
            self.disconnect()

    def get_users_and_fingerprints(self):
        """
        يجلب من الجهاز مباشرة:
        - قاموس المستخدمين المسجلين: {user_id_str: {uid, name, ...}}
        - مجموعة المعرفات التي تملك قوالب بصمة مسجلة فعلياً: set of user_id_str
        (مستنسخ من مشروع MB2000).
        """
        self.connect()
        try:
            users_map = {}
            fp_user_ids = set()
            try:
                users = self.conn.get_users()
                for u in users:
                    user_id_str = str(u.user_id).strip()
                    users_map[user_id_str] = {
                        "uid": u.uid,
                        "name": u.name,
                        "user_id": user_id_str,
                        "card": getattr(u, 'card', 0),
                        "privilege": getattr(u, 'privilege', 0)
                    }
            except Exception as e:
                print(f"[ZKDevice] Error fetching users: {e}")

            try:
                templates = self.conn.get_templates()
                for t in templates:
                    if hasattr(t, 'user_id') and t.user_id:
                        fp_user_ids.add(str(t.user_id).strip())
                    elif hasattr(t, 'uid'):
                        for uid_str, udata in users_map.items():
                            if udata.get("uid") == t.uid:
                                fp_user_ids.add(uid_str)
                                break
            except Exception as e:
                print(f"[ZKDevice] Error fetching templates: {e}")

            return users_map, fp_user_ids
        finally:
            self.disconnect()

    def delete_user(self, user_id="", uid=0):
        """
        يحذف مستخدماً من الجهاز نهائياً — مع بصماته. بالرقم (user_id) أو
        بالمعرّف الداخلي (uid). يعطّل الجهاز أثناء العملية ثم يُعيد تفعيله
        (كالرفع). يُرجع True عند النجاح. يخدم تنظيف مستخدمي الاختبار وأيّ
        إلغاء تسجيل كامل مستقبلاً (بخلاف _delete_fingerprints الذي يبقي
        المستخدم ويحذف قوالبه فقط).
        """
        self.connect()
        try:
            try:
                self.conn.disable_device()
            except Exception:
                pass
            self.conn.delete_user(uid=int(uid or 0), user_id=str(user_id or ""))
            return True
        finally:
            try:
                self.conn.enable_device()
            except Exception:
                pass
            self.disconnect()

    # ══════════════════════════════════════════════════════════════════════════
    # الطبقة الاحتياطية — سوكيت مباشر
    # ══════════════════════════════════════════════════════════════════════════
    def _native_connect(self):
        if "udp" in self.protocol:
            return self._connect_udp()
        elif "tcp" in self.protocol:
            return self._connect_tcp()
        else:
            try:
                return self._connect_tcp()
            except Exception as e1:
                self._native_disconnect()
                try:
                    return self._connect_udp()
                except Exception as e2:
                    raise ZKError(
                        "فشل TCP (%s) وUDP (%s)" % (e1, e2))

    def _connect_tcp(self):
        self._is_udp = False
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.ip, self.port))
        self._session = 0; self._reply = 0
        cmd, _ = self._send_native(1000)  # CMD_CONNECT
        if cmd == 2005:   # CMD_ACK_UNAUTH
            if not self._auth_native():
                raise ZKError("رمز الاتصال Comm Key غير صحيح")
        elif cmd != 2000:  # CMD_ACK_OK
            raise ZKError("رفض TCP (ردّ %s)" % cmd)
        return True

    def _connect_udp(self):
        self._is_udp = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self.timeout)
        self._session = 0; self._reply = 0
        cmd, _ = self._send_native(1000)
        if cmd == 2005:
            if not self._auth_native():
                raise ZKError("رمز الاتصال Comm Key غير صحيح")
        elif cmd != 2000:
            raise ZKError("رفض UDP (ردّ %s)" % cmd)
        return True

    def _auth_native(self) -> bool:
        from struct import pack, unpack
        key = self.comm_key
        session = self._session
        k = 0
        for i in range(32):
            k = (k << 1 | 1) if (key & (1 << i)) else (k << 1)
        k += session
        k = pack(b'I', k & 0xFFFFFFFF)
        k = unpack(b'BBBB', k)
        k = pack(b'BBBB',
                 k[0] ^ ord('Z'), k[1] ^ ord('K'),
                 k[2] ^ ord('S'), k[3] ^ ord('O'))
        k = unpack(b'HH', k)
        k = pack(b'HH', k[1], k[0])
        B = 0xff & 50
        k = unpack(b'BBBB', k)
        k = pack(b'BBBB', k[0] ^ B, k[1] ^ B, B, k[3] ^ B)
        cmd, _ = self._send_native(1102, k)
        return cmd == 2000

    def _native_disconnect(self):
        try:
            if self._sock:
                self._send_native(1001)
        except Exception:
            pass
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None

    def _make_packet(self, command, data=b''):
        buf = struct.pack('<4H', command, 0, self._session, self._reply) + data
        s, i, n = 0, 0, len(buf)
        while n > 1:
            s += struct.unpack('<H', buf[i:i+2])[0]
            i += 2; n -= 2
            s = s if s <= 0xFFFF else s - 0xFFFF
        if n:
            s += buf[-1]
        while s > 0xFFFF:
            s -= 0xFFFF
        s = ~s
        while s < 0:
            s += 0xFFFF
        return struct.pack('<4H', command, s & 0xFFFF, self._session, self._reply) + data

    def _send_native(self, command, data=b''):
        self._reply = (self._reply + 1) & 0xFFFF
        pkt = self._make_packet(command, data)
        if self._is_udp:
            self._sock.sendto(pkt, (self.ip, self.port))
            try:
                raw, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                return None, b''
        else:
            self._sock.send(struct.pack('<HHI', 0x5050, 0x827D, len(pkt)) + pkt)
            head = self._recv_exact(8)
            if not head:
                return None, b''
            m1, m2, size = struct.unpack('<HHI', head)
            raw = self._recv_exact(size)
        if len(raw) < 8:
            return None, b''
        cmd, _chk, sess, rep = struct.unpack('<4H', raw[:8])
        self._session, self._reply = sess, rep
        return cmd, raw[8:]

    def _recv_exact(self, n):
        out = b''
        while len(out) < n:
            try:
                chunk = self._sock.recv(n - len(out))
            except socket.timeout:
                break
            if not chunk:
                break
            out += chunk
        return out

    def _native_info(self) -> dict:
        out = {}
        for label, key in [("name", "~DeviceName"),
                            ("serial", "~SerialNumber"),
                            ("platform", "~Platform"),
                            ("firmware", "FirmVer")]:
            try:
                cmd, data = self._send_native(11, key.encode() + b'\x00')
                if cmd == 2000:
                    txt = data.split(b'\x00')[0].decode('utf-8', 'replace')
                    out[label] = txt.split('=', 1)[1] if '=' in txt else txt
                else:
                    out[label] = None
            except Exception:
                out[label] = None
        return out

    def _native_read_punches(self, after_dt=None) -> list:
        cmd, data = self._send_native(13)   # CMD_ATTLOG_RRQ
        raw = b''
        if cmd == 2000:
            raw = data
        elif cmd == 1500:  # CMD_PREPARE_DATA
            total = struct.unpack('<I', data[:4])[0] if len(data) >= 4 else 0
            buf = b''
            while len(buf) < total:
                c, d = self._recv_packet_udp() if self._is_udp else self._recv_tcp_packet()
                if c == 1501:
                    buf += d
                elif c in (2000, None):
                    break
            raw = buf

        out = []
        rec = 40
        start = 4 if len(raw) % rec == 4 else 0
        for off in range(start, len(raw) - rec + 1, rec):
            chunk = raw[off:off + rec]
            uid = struct.unpack('<H', chunk[0:2])[0]
            ts = struct.unpack('<I', chunk[27:31])[0]
            local = _decode_zk_time(ts)
            if local is None:
                continue
            punch_utc = local - _RIYADH
            if after_dt and punch_utc <= after_dt:
                continue
            out.append({
                "uid": str(uid),
                "punch_utc": punch_utc.isoformat(timespec="seconds"),
                "punch_local": local.isoformat(timespec="seconds"),
            })
        return out

    def _recv_packet_udp(self):
        try:
            raw, _ = self._sock.recvfrom(4096)
        except socket.timeout:
            return None, b''
        if len(raw) < 8:
            return None, b''
        cmd, _chk, sess, rep = struct.unpack('<4H', raw[:8])
        self._session, self._reply = sess, rep
        return cmd, raw[8:]

    def _recv_tcp_packet(self):
        head = self._recv_exact(8)
        if not head:
            return None, b''
        _m1, _m2, size = struct.unpack('<HHI', head)
        body = self._recv_exact(size)
        if len(body) < 8:
            return None, b''
        cmd, _chk, sess, rep = struct.unpack('<4H', body[:8])
        self._session, self._reply = sess, rep
        return cmd, body[8:]

    def _native_set_user(self, uid, name="") -> bool:
        try:
            internal = int(uid) & 0xFFFF
        except Exception:
            internal = 1
        uid_str = str(uid)
        nm = (name or uid_str).encode("utf-8", "replace")[:24]
        rec = struct.pack('<HB', internal, 0) + b'\x00' * 8
        rec += nm + b'\x00' * (24 - len(nm))
        rec += b'\x00' * 9
        card = uid_str.encode()[:24]
        rec += card + b'\x00' * (24 - len(card))
        cmd, _ = self._send_native(8, rec)  # CMD_USER_WRQ
        if cmd == 2000:
            self._send_native(1013)  # CMD_REFRESHDATA
            return True
        return False

    def _native_start_enroll(self, uid, finger=0) -> bool:
        uid_str = str(uid).encode()[:24]
        data = uid_str + b'\x00' * (24 - len(uid_str)) + \
            struct.pack('<B', int(finger) & 0xFF) + b'\x01'
        cmd, _ = self._send_native(61, data)  # CMD_STARTENROLL
        return cmd == 2000


def _decode_zk_time(val: int):
    try:
        s = val % 60; val //= 60
        mi = val % 60; val //= 60
        h = val % 24; val //= 24
        d = val % 31 + 1; val //= 31
        mo = val % 12 + 1; val //= 12
        y = val + 2000
        return datetime.datetime(y, mo, d, h, mi, s)
    except Exception:
        return None
