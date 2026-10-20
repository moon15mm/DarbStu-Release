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

    state, new = patch_source(src)
    if state == OK:
        return OK, "مسار نسخة واتساب ويب سليم"
    if state == NOT_AFFECTED:
        return NOT_AFFECTED, "نسخة server.js لا تحمل هذا العطل"
    if state == UNKNOWN:
        return UNKNOWN, "server.js بشكلٍ غير متوقَّع — لم يُلمس"

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
    return FIXED, "أُصلح مسار نسخة واتساب ويب في server.js" + note
