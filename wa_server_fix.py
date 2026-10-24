# -*- coding: utf-8 -*-
"""
wa_server_fix.py — يُصلح server.js في مدرسة قائمة. المكتبة القياسية وحدها.

العطل (ثانوية الشقيق، لم تخرج منها رسالة واحدة منذ التنصيب):
من ١٥ سبتمبر ٢٠٢٦ صار server.js يعطي LocalWebCache مسار **ملف** النسخة
(.wa-version.html)، والمكتبة تريد **مجلداً** تقرأ منه `<webVersion>.html`.
فالنسخة المحفوظة لا تُقرأ أبداً، وبعد «مصادق» تحاول المكتبة إنشاء مجلدٍ في
مسار الملف فتسقط بـ EEXIST قبل تحميل دوال الإرسال. يبقى الخادم «متصلاً»
وتفشل كل رسالة بـ «Cannot read properties of undefined (reading 'getChat')»،
وإعادة التشغيل لا تُجدي لأن السقوط نفسه يتكرر في كل تشغيل.
أُعيد إنتاجه بـ node.exe المدارس (v20.19.1) ومكتبتها (1.34.7) حرفياً.

server.js لا يصله التحديث (المُحدِّث يحمي مجلد الواتساب)، فيُصلحه من يصلهم:
whatsapp_service قبل كل تشغيل للخادم، وأداة FixWhatsApp.exe يدوياً.

الإصلاح نصّي ضيّق: يُطبَّق كاملاً أو لا يُطبَّق، ونسخةٌ احتياطية قبل الكتابة،
و`node --check` على الناتج قبل أن يحلّ محلّ الأصل. لا يرفع استثناءً أبداً.

والعلّة الثانية (٢٤ أكتوبر ٢٠٢٦): «لا أوافق» على طلب الاستئذان كانت تُسجَّل
موافقةً — انظر `patch_permission`. والرقعتان مستقلتان: كلٌّ تُطبَّق إن لزمت.
"""
import os
import re
import subprocess
import sys

# ما يُستبدل. المسافات مرنة؛ الأسماء حرفية كما في server.js منذ ١٥ سبتمبر.
_BROKEN_CACHE = re.compile(r"\{\s*type:\s*'local',\s*path:\s*WAVER_FILE\s*\}")
_BROKEN_USE = re.compile(r"if\s*\(\s*wv\s*\)\s*clientOpts\.webVersionCache\s*=\s*wv\s*;")

# المجلد مجلدُ الملف، والنسخة اسمُه بلا امتداد ⇒ تقرأ المكتبة الملف نفسه.
_FIXED_CACHE = "{ type: 'local', path: path.dirname(WAVER_FILE) }"
_FIXED_USE = ("if (wv) { clientOpts.webVersionCache = wv; "
              "clientOpts.webVersion = path.basename(WAVER_FILE, '.html'); }")

BACKUP_SUFFIX = ".bak-cachefix"

OK = "ok"                      # مُصلَح من قبل
FIXED = "fixed"                # أُصلح الآن
NOT_AFFECTED = "not_affected"  # نسخة أقدم من العطل (تثبيت بالرابط) — لا تُلمس
UNKNOWN = "unknown"            # فيه أثر العطل لكن بشكل لا نعرفه — لا نخمّن
FAILED = "failed"              # تعذّرت القراءة أو الكتابة أو فشل فحص الناتج

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def patch_source(src):
    """يُرجع (الحالة، النص المُصلَح أو None). لا يلمس القرص."""
    n_cache = len(_BROKEN_CACHE.findall(src))
    n_use = len(_BROKEN_USE.findall(src))
    if n_cache == 0 and n_use == 0:
        if _FIXED_CACHE in src and _FIXED_USE in src:
            return OK, None
        return NOT_AFFECTED, None
    # نصفُ إصلاح أسوأ من لا إصلاح: المسار يصير مجلداً والنسخة تبقى غائبة.
    if n_cache < 1 or n_use != 1:
        return UNKNOWN, None
    new = _BROKEN_CACHE.sub(_FIXED_CACHE, src)
    new = _BROKEN_USE.sub(_FIXED_USE, new)
    return FIXED, new


# ── العلّة الثانية: «لا أوافق» كانت تُسجَّل موافقةً على الاستئذان ─────────
# الموافقة تُفحص بـ«تحتوي» والرفض بـ«يبدأ بـ»، وإن اجتمعا غلبت الموافقة:
# «لا أوافق» تحتوي «أوافق» ⇒ موافق، فيُسمح للطالب بالخروج ووليّ أمره رفض.
# الإصلاح: الرفض أولاً، والنفي الصريح للموافقة رفض. (أُصلح ٢٤ أكتوبر ٢٠٢٦)
_BROKEN_PERM = re.compile(
    r"const\s+isApprove\s*=\s*APPROVE_KEYWORDS\.some\(\s*w\s*=>\s*textLower\.includes\(w\)\s*\);\s*"
    r"const\s+isReject\s*=\s*REJECT_KEYWORDS\.some\(\s*w\s*=>\s*"
    r"textLower\s*===\s*w\s*\|\|\s*textLower\.startsWith\(w\)\s*\);")
_FIXED_PERM_MARK = "NEGATED_APPROVAL"
_FIXED_PERM = (
    "// الرفض أولاً: «لا أوافق» تحتوي «أوافق» فكانت تُقرأ موافقةً (أُصلح ٢٤ أكتوبر ٢٠٢٦)\n"
    "        const NEGATED_APPROVAL = ['لا اوافق', 'لا أوافق', 'ما اوافق', 'ما أوافق',\n"
    "            'غير موافق', 'مو موافق', 'ماني موافق', 'لا موافق'];\n"
    "        const isReject  = NEGATED_APPROVAL.some(w => textLower.includes(w)) ||\n"
    "            REJECT_KEYWORDS.some(w => textLower === w || textLower.startsWith(w));\n"
    "        const isApprove = !isReject && APPROVE_KEYWORDS.some(w => textLower.includes(w));")


def patch_permission(src):
    """(الحالة، النص المُصلَح أو None) لعلّة «لا أوافق» — لا يلمس القرص."""
    n = len(_BROKEN_PERM.findall(src))
    if n == 0:
        return (OK if _FIXED_PERM_MARK in src else NOT_AFFECTED), None
    if n != 1:
        return UNKNOWN, None
    return FIXED, _BROKEN_PERM.sub(lambda m: _FIXED_PERM, src)


def needs_fix(src):
    """أسماء الإصلاحات التي يحتاجها هذا الملف — فارغة إن كان سليماً."""
    out = []
    if patch_source(src)[0] == FIXED:
        out.append("مسار نسخة واتساب ويب")
    if patch_permission(src)[0] == FIXED:
        out.append("ردّ «لا أوافق» على الاستئذان")
    return out


def _node_check(js_path, node):
    """True سليم، False معطوب، None لا node للفحص."""
    if not node or not os.path.isfile(node):
        return None
    try:
        r = subprocess.run([node, "--check", js_path], capture_output=True,
                           timeout=60, creationflags=_CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def fix_file(js_path, node=None):
    """
    يُصلح server.js في مكانه إن كان مصاباً. يُرجع (الحالة، وصفاً بالعربية).
    `node`: مسار node.exe لفحص الناتج قبل اعتماده — بدونه يُكتب بلا فحص.
    """
    try:
        with open(js_path, "r", encoding="utf-8", newline="") as f:
            src = f.read()
    except Exception as e:
        return FAILED, "تعذّرت قراءة server.js (%s)" % e

    state, new_cache = patch_source(src)
    cur = new_cache if state == FIXED else src
    st_perm, new_perm = patch_permission(cur)
    if st_perm == FIXED:
        cur = new_perm
    done = [d for st, d in ((state, "مسار نسخة واتساب ويب"),
                            (st_perm, "ردّ «لا أوافق» على الاستئذان")) if st == FIXED]
    if not done:
        # لا تغيير — الحالة كما كانت لإصلاح المسار
        if state == OK:
            return OK, "مسار نسخة واتساب ويب سليم"
        if state == NOT_AFFECTED:
            return NOT_AFFECTED, "نسخة server.js لا تحمل هذا العطل"
        return UNKNOWN, "server.js بشكلٍ غير متوقَّع — لم يُلمس"
    new = cur

    folder = os.path.dirname(os.path.abspath(js_path))
    tmp = os.path.join(folder, "server.cachefix-tmp.js")   # .js كي يفحصه node
    try:
        bak = js_path + BACKUP_SUFFIX
        if not os.path.exists(bak):          # الأصل الأول يبقى، لا يُكتب فوقه
            with open(bak, "w", encoding="utf-8", newline="") as f:
                f.write(src)
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(new)
        checked = _node_check(tmp, node)
        if checked is False:
            os.remove(tmp)
            return FAILED, "الناتج لم يجتز فحص node — بقي server.js كما هو"
        os.replace(tmp, js_path)
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return FAILED, "تعذّرت كتابة server.js (%s)" % e
    note = "" if checked else " (بلا فحص node)"
    return FIXED, "أُصلح في server.js: " + "، ".join(done) + note
