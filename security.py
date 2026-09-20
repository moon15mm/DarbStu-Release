# -*- coding: utf-8 -*-
"""
security.py — أسرار التثبيت وتجزئة كلمات المرور

⚠️ هذا الملف مستقل تماماً — لا يستورد أي وحدة أخرى من المشروع
   (يستورده setup_wizard قبل الاستيرادات الثقيلة، و database و api).

يوفّر:
  • get_secret(name)   — سر عشوائي فريد لكل جهاز، يُولّد مرة ويُحفظ محلياً
  • hash_password(pw)  — PBKDF2-SHA256 بملح عشوائي لكل مستخدم
  • verify_password()  — يتحقق من الصيغة الجديدة والقديمة (SHA-256) معاً
"""
import os
import sys
import json
import hmac
import datetime
import base64
import hashlib
import secrets
import threading

# ── مجلد التطبيق (نفس منطق constants.BASE_DIR بدون استيراده) ──────
BASE_DIR = (os.path.dirname(sys.executable)
            if getattr(sys, 'frozen', False)
            else os.path.dirname(os.path.abspath(__file__)))

# ملف الأسرار — خارج مجلد data حتى لا يُخدَم عبر HTTP بأي حال
_KEYS_FILE = os.path.join(BASE_DIR, '.darb_keys.json')

# ملف مؤقت تكتبه شاشة الإعداد الأولي بكلمة مرور المدير المختارة
INITIAL_ADMIN_FILE = os.path.join(BASE_DIR, '.darb_init_admin')

_LOCK = threading.Lock()
_CACHE = None


# ══════════════════════════════════════════════════════════════════
#  أسرار التثبيت
# ══════════════════════════════════════════════════════════════════
def _load_keys() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    keys = {}
    try:
        if os.path.exists(_KEYS_FILE):
            with open(_KEYS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                keys = loaded
    except Exception:
        keys = {}
    _CACHE = keys
    return keys


def _save_keys(keys: dict):
    try:
        with open(_KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(keys, f)
        # تقييد الصلاحيات على المالك فقط (يعمل على ويندوز ولينكس)
        try:
            os.chmod(_KEYS_FILE, 0o600)
        except Exception:
            pass
    except Exception:
        # في أسوأ الحالات نبقي السر في الذاكرة لهذه الجلسة فقط
        pass


def get_secret(name: str) -> str:
    """
    يُرجع سراً عشوائياً ثابتاً لهذا التثبيت. يُولَّد عند أول طلب ويُحفظ.
    كل جهاز يحصل على سر مختلف — لا توجد أسرار مشتركة في الكود المصدري.
    """
    with _LOCK:
        keys = _load_keys()
        val = keys.get(name)
        if not val:
            val = secrets.token_urlsafe(48)
            keys[name] = val
            _save_keys(keys)
        return val


def get_jwt_secret() -> str:
    """سر توقيع جلسات لوحة الويب."""
    return get_secret('jwt')


def get_link_secret() -> str:
    """سر اشتقاق رموز روابط الفصول — فريد لكل مدرسة."""
    return get_secret('links')


# ══════════════════════════════════════════════════════════════════
#  رموز روابط الفصول — تتجدّد كل يوم
# ══════════════════════════════════════════════════════════════════
# `/c/1-1` معرّف يُخمَّن: من يعرف نطاق المدرسة يصل لكل فصولها ويُسجّل
# غياباً كاذباً يُشغّل رسائل واتساب لأولياء الأمور. الرمز يمنع ذلك.
#
# يُشتقّ حسابياً من (سرّ المدرسة + الفصل + التاريخ) ولا يُخزَّن: لا جدول
# ينمو، ولا تنظيف، ورمز الأمس يبطل وحده لأنه ببساطة لا يُطابق حساب اليوم.
# ولأنه HMAC، لا يمكن استنتاج رمز الغد من رمز اليوم.

def class_link_token(class_id: str, day: str = '') -> str:
    """رمز اليوم لفصل — ٣٢ حرفاً ست عشرياً."""
    if not day:
        day = _riyadh_day()
    msg = '{}|{}'.format(class_id, day).encode('utf-8')
    return hmac.new(get_link_secret().encode('utf-8'),
                    msg, hashlib.sha256).hexdigest()[:32]


def verify_class_link_token(class_id: str, token: str) -> bool:
    """
    يقبل رمز اليوم ورمز أمس.

    مهلة الأمس ليست تساهلاً: المعلم قد يفتح رابطاً وصله ليلاً بعد منتصف
    الليل، أو يعود لرسالة أمس ليُكمل تسجيلاً. رفضه حينها يُنتج شكوى
    لا أماناً — النافذة تبقى يوماً واحداً على أي حال.
    """
    if not token:
        return False
    today = _riyadh_day()
    yday = (datetime.datetime.strptime(today, '%Y-%m-%d')
            - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    return any(hmac.compare_digest(token, class_link_token(class_id, d))
               for d in (today, yday))


def _riyadh_day() -> str:
    tz = datetime.timezone(datetime.timedelta(hours=3))
    return datetime.datetime.now(datetime.timezone.utc).astimezone(tz).strftime('%Y-%m-%d')


# ══════════════════════════════════════════════════════════════════
#  تجزئة كلمات المرور
# ══════════════════════════════════════════════════════════════════
_PBKDF2_ITERATIONS = 200_000
_PBKDF2_PREFIX     = 'pbkdf2$'


def hash_password(pw: str) -> str:
    """PBKDF2-SHA256 بملح عشوائي — الصيغة: pbkdf2$<iters>$<salt_b64>$<hash_b64>"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, _PBKDF2_ITERATIONS)
    return '{}{}${}${}'.format(
        _PBKDF2_PREFIX,
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def _legacy_sha256(pw: str) -> str:
    return hashlib.sha256(pw.encode('utf-8')).hexdigest()


def verify_password(pw: str, stored: str) -> bool:
    """
    يتحقق من كلمة المرور. يدعم الصيغتين:
      • pbkdf2$...            (الجديدة)
      • 64 حرفاً hex          (القديمة SHA-256 — للتوافق مع قواعد البيانات الحالية)
    """
    if not stored:
        return False
    try:
        if stored.startswith(_PBKDF2_PREFIX):
            _, iters, salt_b64, hash_b64 = stored.split('$', 3)
            dk = hashlib.pbkdf2_hmac(
                'sha256', pw.encode('utf-8'),
                base64.b64decode(salt_b64), int(iters)
            )
            return hmac.compare_digest(dk, base64.b64decode(hash_b64))
        return hmac.compare_digest(_legacy_sha256(pw), stored)
    except Exception:
        return False


def needs_rehash(stored: str) -> bool:
    """True إذا كانت التجزئة بالصيغة القديمة ويجب ترقيتها عند أول دخول ناجح."""
    return bool(stored) and not stored.startswith(_PBKDF2_PREFIX)


def is_default_password(stored: str) -> bool:
    """True إذا كانت كلمة المرور المخزَّنة هي الافتراضية القديمة admin123."""
    return verify_password('admin123', stored)


# ══════════════════════════════════════════════════════════════════
#  كلمة مرور المدير المختارة في شاشة الإعداد الأولي
# ══════════════════════════════════════════════════════════════════
def store_initial_admin_password(pw: str):
    """تكتبها شاشة الإعداد — مجزّأة، وتُستهلك مرة واحدة عند تهيئة قاعدة البيانات."""
    try:
        with open(INITIAL_ADMIN_FILE, 'w', encoding='utf-8') as f:
            f.write(hash_password(pw))
        try:
            os.chmod(INITIAL_ADMIN_FILE, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def consume_initial_admin_password() -> str:
    """يُرجع التجزئة المحفوظة ويحذف الملف، أو '' إن لم توجد."""
    try:
        if not os.path.exists(INITIAL_ADMIN_FILE):
            return ''
        with open(INITIAL_ADMIN_FILE, 'r', encoding='utf-8') as f:
            val = f.read().strip()
        try:
            os.remove(INITIAL_ADMIN_FILE)
        except Exception:
            pass
        return val
    except Exception:
        return ''


# ══════════════════════════════════════════════════════════════════
#  تذكرة إعادة تعيين كلمة مدير المدرسة (موقَّعة من المزوّد)
# ══════════════════════════════════════════════════════════════════
# مدرسةٌ تُنصَّب وتُكتب لها كلمة مرور في شاشة الإعداد، ثم ينساها من نصّبها
# ⇒ لا سبيل لإنقاذها عن بُعد: المدارس بلا بايثون، ولا شيء في أداة الإدارة
# لكلمات المرور، والدخول نفسه هو المعطَّل. (حدث في مدرسة السبطة.)
#
# **التوقيع ضروري لا احتياط**: خادم المدرسة يستمع على شبكتها المحلية،
# فنقطةٌ بلا توقيع يستدعيها أي معلّم على الشبكة فيصير مديراً.
#
# وثلاثة قيود فوق التوقيع، كلٌّ يسدّ ثغرةً مختلفة:
#   • الصلاحية القصيرة — تذكرة مسرَّبة لا تنفع بعد دقائق
#   • الرقم لمرة واحدة — تذكرة مستعملة لا تُعاد
#   • ربط المدرسة     — تذكرة مدرسةٍ لا تعمل في أخرى
_RESET_NONCE_FILE = os.path.join(BASE_DIR, '.darb_reset_used')
_RESET_MAX_AGE_SEC = 15 * 60


def _reset_used_nonces() -> set:
    try:
        if os.path.exists(_RESET_NONCE_FILE):
            with open(_RESET_NONCE_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d, list):
                return set(str(x) for x in d)
    except Exception:
        pass
    return set()


def remember_reset_nonce(nonce: str):
    """يُسجّل التذكرة مستعملةً — يُستدعى بعد نجاح إعادة التعيين."""
    try:
        used = _reset_used_nonces()
        used.add(str(nonce))
        trimmed = list(used)[-500:]     # الصلاحية القصيرة تُغني عن الأقدم
        tmp = _RESET_NONCE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(trimmed, f)
        os.replace(tmp, _RESET_NONCE_FILE)
    except Exception:
        pass


def school_identity() -> str:
    """معرّف هذه المدرسة (نطاق النفق) — تُربط به التذكرة."""
    try:
        p = os.path.join(BASE_DIR, '.darb_tunnel.json')
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return str(json.load(f).get('subdomain') or '').strip()
    except Exception:
        pass
    return ''


def verify_admin_reset_ticket(ticket, signature_b64):
    """
    يتحقق من تذكرة إعادة التعيين. يُرجع (صالحة, السبب_أو_الرقم).

    التذكرة JSON مُرتَّب المفاتيح موقَّع بـEd25519 بمفتاح المزوّد، ولا
    تُقبل إلا بعد اجتياز الفحوص الخمسة كلها.
    """
    try:
        from constants import ADMIN_RESET_PUBKEY
    except Exception:
        return False, 'لا مفتاح تحقق'
    if not ADMIN_RESET_PUBKEY:
        return False, 'لا مفتاح تحقق'
    if not isinstance(ticket, dict) or not signature_b64:
        return False, 'تذكرة ناقصة'

    # ① التوقيع
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
        payload = json.dumps(ticket, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False).encode('utf-8')
        pk = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(ADMIN_RESET_PUBKEY))
        pk.verify(base64.b64decode(signature_b64), payload)
    except Exception:
        return False, 'توقيع غير صالح'

    # ② الغرض — توقيعٌ لغرضٍ آخر لا يُعاد استعماله هنا
    if str(ticket.get('action') or '') != 'reset_admin_password':
        return False, 'غرض غير مطابق'

    # ③ الصلاحية (ونرفض المستقبل البعيد: ساعةٌ مضبوطة خطأً لا تفتح باباً)
    try:
        issued = datetime.datetime.fromisoformat(str(ticket.get('issued')))
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=datetime.timezone.utc)
        age = (datetime.datetime.now(datetime.timezone.utc)
               - issued).total_seconds()
        if age > _RESET_MAX_AGE_SEC or age < -_RESET_MAX_AGE_SEC:
            return False, 'انتهت صلاحية التذكرة'
    except Exception:
        return False, 'تاريخ غير صالح'

    # ④ ربط المدرسة
    mine = school_identity()
    want = str(ticket.get('school') or '').strip()
    if mine and want and mine != want:
        return False, 'التذكرة لمدرسة أخرى'

    # ⑤ لمرة واحدة
    nonce = str(ticket.get('nonce') or '')
    if not nonce:
        return False, 'بلا رقم تعريف'
    if nonce in _reset_used_nonces():
        return False, 'التذكرة مستعملة'

    return True, nonce
