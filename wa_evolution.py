# -*- coding: utf-8 -*-
"""
wa_evolution.py — الإرسال عبر خادم الواتساب السحابي (Evolution API v2) وبوت ردوده.

المدرسة تختار مزوّد الواتساب في إعداداتها (`whatsapp_provider`):
  local      خادم Node على جهاز المدرسة — كما كان حرفاً (الافتراضي)
  evolution  الخادم السحابي على سيرفرنا (https://wa-api.darbstu.com)
  auto       المحلي أولاً، والسحابي حين يتعطّل المحلي أو يبلغ سقفه اليومي

لكل مدرسة جلسة سحابية ومفتاحها الخاص (`darbstu-evo-add` على السيرفر).
المفتاح العام لا يغادر السيرفر، ومفتاح جلسةٍ لا يبلغ جلسة غيرها — تحقّقتُ: 401.

بوت الأعذار والاستئذان: في المحلي يعيش داخل server.js. في السحابي تصل كل
رسالة واردة إلى /api/wa/evolution-webhook/<رمز> عبر نفق المدرسة، فيعالجها
`handle_webhook` هنا بمنطق server.js نفسه (الكلمات، مهلة ٤٨ ساعة، الردود)
— إلا خطأً واحداً لم يُنقل: «لا أوافق» كانت تُقرأ موافقةً لأن فيها «أوافق».
"""
import base64
import datetime
import hmac
import json
import os
import re
import secrets
import struct
import threading
import time

import requests

from constants import DATA_DIR

PROVIDERS = ("local", "evolution", "auto")
DEFAULT_URL = "https://wa-api.darbstu.com"
DEFAULT_INSTANCE = "darbstu_main"
WEBHOOK_PATH = "/api/wa/evolution-webhook/"

# ─── من server.js حرفاً ─────────────────────────────────────────────
DEFAULT_EXCUSE_KEYWORDS = ["عذر", "معذور", "مريض", "مرض", "علاج", "مستشفى",
                           "وفاة", "سفر", "ظروف", "إجازة", "اجازة", "excuse", "1"]
APPROVE_KEYWORDS = ["موافق", "وافق", "اوافق", "أوافق", "ok", "نعم", "تمام", "موافقه", "موافقة"]
REJECT_KEYWORDS = ["رفض", "لا", "مرفوض", "رافض"]
# الرفض يُفحص أولاً: server.js كان يقرأ «لا أوافق» موافقةً (تحتوي «أوافق»)
_NEGATED_APPROVAL = ("لا اوافق", "لا أوافق", "ما اوافق", "ما أوافق", "غير موافق",
                     "مو موافق", "ماني موافق", "لا موافق")
_EXCUSE_WINDOW_H = 48


# ═══════════════════════════════════════════════════════════════════
#  الإعدادات
# ═══════════════════════════════════════════════════════════════════
def _cfg():
    from config_manager import load_config
    return load_config()


def provider(cfg=None) -> str:
    """المزوّد المختار — وأي قيمة غير معروفة تعني المحلي، فلا يتغيّر شيء بخطأ إعداد."""
    try:
        p = str((cfg or _cfg()).get("whatsapp_provider", "local") or "local").strip().lower()
    except Exception:
        return "local"
    return p if p in PROVIDERS else "local"


def settings(cfg=None) -> dict:
    cfg = cfg or _cfg()
    return {
        "url": str(cfg.get("evolution_server_url") or DEFAULT_URL).strip().rstrip("/"),
        "key": str(cfg.get("evolution_api_key") or "").strip(),
        "instance": str(cfg.get("evolution_instance_name") or DEFAULT_INSTANCE).strip(),
    }


def configured(cfg=None) -> bool:
    s = settings(cfg)
    return bool(s["url"] and s["key"] and s["instance"])


def ledger_key(cfg=None) -> str:
    """مفتاح دفتر السقف اليومي للرقم السحابي — رقمٌ آخر غير المحلي، فله سقفه."""
    return "evo:" + settings(cfg)["instance"]


def normalize_number(phone):
    """
    (الرقم بصيغة 9665xxxxxxxx، رسالة خطأ) — القواعد نفسها في المحلي حرفاً.
    """
    if not phone:
        return None, "رقم الجوال غير موجود أو فارغ."
    d = "".join(ch for ch in str(phone) if ch.isdigit())
    if not d:
        return None, f"رقم الجوال '{phone}' غير صالح."
    if len(d) == 10 and d.startswith("05"):
        d = "966" + d[1:]
    elif len(d) == 9 and d.startswith("5"):
        d = "966" + d
    elif not (len(d) == 12 and d.startswith("966")):
        return None, f"تنسيق رقم الجوال غير مدعوم: {d}"
    return d, ""


# ═══════════════════════════════════════════════════════════════════
#  عميل Evolution
# ═══════════════════════════════════════════════════════════════════
class EvolutionError(Exception):
    pass


def _request(method, path, body=None, timeout=30, cfg=None):
    """(رمز الحالة، الجسم مفكوكاً). أخطاء الشبكة تصعد كما هي ليصنّفها المُستدعي."""
    s = settings(cfg)
    if not (s["url"] and s["key"] and s["instance"]):
        raise EvolutionError("إعداد الخادم السحابي ناقص — أدخل الرابط واسم الجلسة والمفتاح")
    r = requests.request(method, s["url"] + path.replace("{i}", s["instance"]),
                         json=body, timeout=timeout,
                         headers={"apikey": s["key"], "Content-Type": "application/json"})
    try:
        data = r.json()
    except Exception:
        data = {"raw": (r.text or "")[:300]}
    return r.status_code, data


_state_cache = {"at": 0.0, "val": None, "sig": None}
_STATE_TTL = 10.0


def state(cfg=None, fresh=False, timeout=8):
    """حالة الجلسة: 'open' متصلة · 'close' · 'connecting' · None تعذّر الوصول."""
    s = settings(cfg)
    sig = (s["url"], s["instance"], s["key"][:6])
    now = time.time()
    if not fresh and _state_cache["sig"] == sig and now - _state_cache["at"] < _STATE_TTL:
        return _state_cache["val"]
    try:
        st, data = _request("GET", "/instance/connectionState/{i}", timeout=timeout, cfg=cfg)
        val = ((data.get("instance") or {}).get("state") if st == 200 else None)
    except Exception:
        val = None
    _state_cache.update(at=now, val=val, sig=sig)
    return val


def fetch_qr(cfg=None) -> dict:
    """رمز الربط للجلسة السحابية: {'state','base64','code','msg'}."""
    try:
        st, data = _request("GET", "/instance/connect/{i}", timeout=20, cfg=cfg)
    except EvolutionError as e:
        return {"state": None, "base64": "", "code": "", "msg": str(e)}
    except Exception as e:
        return {"state": None, "base64": "", "code": "", "msg": f"تعذّر بلوغ الخادم السحابي: {e}"}
    if st == 401:
        return {"state": None, "base64": "", "code": "", "msg": "مفتاح الجلسة غير صحيح لهذه الجلسة"}
    if st == 404:
        return {"state": None, "base64": "", "code": "", "msg": "الجلسة غير موجودة على الخادم السحابي"}
    inst = data.get("instance") if isinstance(data, dict) else None
    if isinstance(inst, dict) and inst.get("state") == "open":
        return {"state": "open", "base64": "", "code": "", "msg": "الجلسة السحابية متصلة"}
    b64 = str(data.get("base64") or "")
    return {"state": "close", "base64": b64, "code": str(data.get("code") or ""),
            "msg": "امسح الرمز من واتساب ← الأجهزة المرتبطة" if b64 else
                   "الخادم لم يُرجع رمزاً بعد — أعد المحاولة بعد ثوانٍ"}


def logout(cfg=None) -> bool:
    try:
        st, _ = _request("DELETE", "/instance/logout/{i}", timeout=20, cfg=cfg)
        _state_cache["at"] = 0.0
        return st in (200, 201)
    except Exception:
        return False


def _classify_failure(st, data):
    """(النوع، رسالة) لردٍّ غير ناجح. 'unavailable' يعني أن شيئاً لم يخرج."""
    txt = json.dumps(data, ensure_ascii=False)
    low = txt.lower()
    if st in (401, 403):
        return "failed", "مفتاح الجلسة السحابية غير صحيح"
    if st == 404:
        return "unavailable", "الجلسة السحابية غير موجودة على الخادم"
    if '"exists": false' in low or '"exists":false' in low:
        return "failed", "الرقم غير مسجّل بالواتساب"
    if "connection closed" in low or "not connected" in low or "close" in low and st >= 400:
        return "unavailable", "الواتساب السحابي غير متصل — امسح QR من تبويب إدارة الواتساب"
    if st >= 500:
        return "unavailable", f"الخادم السحابي: HTTP {st}"
    return "failed", f"فشل الإرسال السحابي: HTTP {st}: {txt[:160]}"


def _post_message(path, body, timeout):
    """(نجح، رسالة، النوع) — النوع: sent · failed · unavailable · unsure."""
    try:
        st, data = _request("POST", path, body=body, timeout=timeout)
    except EvolutionError as e:
        return False, str(e), "unavailable"
    except requests.exceptions.ConnectionError:
        return False, "فشل الاتصال بالخادم السحابي للواتساب", "unavailable"
    except requests.exceptions.Timeout:
        # لا نعرف أخرجت أم لا — «مهلة» تُقرأ «ربما وصلت» فلا تُعاد (انظر alerts_service)
        return False, "انتهت مهلة الاتصال بالخادم السحابي.", "unsure"
    except Exception as e:
        return False, f"حدث خطأ غير متوقع في الإرسال السحابي: {e}", "unsure"
    if st in (200, 201) and isinstance(data, dict) and (data.get("key") or data.get("status")):
        return True, "تم الإرسال بنجاح (سحابي)", "sent"
    kind, msg = _classify_failure(st, data)
    return False, msg, kind


def send_text(number, text, timeout=30):
    return _post_message("/message/sendText/{i}", {"number": number, "text": text}, timeout)


def send_document(number, b64, filename, caption="", mimetype="application/pdf", timeout=90):
    return _post_message("/message/sendMedia/{i}", {
        "number": number, "mediatype": "document", "mimetype": mimetype,
        "caption": caption or "", "media": b64, "fileName": filename or "file.pdf"}, timeout)


# ═══════════════════════════════════════════════════════════════════
#  Webhook — ربط الجلسة بالمدرسة لاستقبال ردود أولياء الأمور
# ═══════════════════════════════════════════════════════════════════
def webhook_token(create=False) -> str:
    """رمزٌ سريّ في رابط الـWebhook — يُولَّد مرةً ويُحفظ في الإعداد."""
    from config_manager import load_config, save_config, invalidate_config_cache
    cfg = load_config()
    tok = str(cfg.get("evolution_webhook_token") or "")
    if not tok and create:
        tok = secrets.token_urlsafe(24)
        cfg["evolution_webhook_token"] = tok
        save_config(cfg)
        invalidate_config_cache()
    return tok


def webhook_url() -> str:
    """رابط الـWebhook العام — نفق المدرسة. بلا نطاق عام لا تبلغه الرسائل الواردة."""
    from constants import public_base_url
    base = public_base_url()
    if not base.startswith("https://"):
        return ""
    return base.rstrip("/") + WEBHOOK_PATH + webhook_token(create=True)


def ensure_webhook() -> tuple:
    """يوجّه الرسائل الواردة لهذه الجلسة إلى المدرسة. (نجح، رسالة)."""
    url = webhook_url()
    if not url:
        return False, ("لا نطاق عام لهذه المدرسة (النفق غير مُجهَّز) — الإرسال يعمل، "
                       "لكن ردود أولياء الأمور لن تصل البوت")
    try:
        st, data = _request("POST", "/webhook/set/{i}", timeout=20, body={"webhook": {
            "enabled": True, "url": url, "byEvents": False, "base64": False,
            "events": ["MESSAGES_UPSERT"]}})
    except Exception as e:
        return False, f"تعذّر ضبط استقبال الردود: {e}"
    if st in (200, 201):
        return True, "ضُبط استقبال ردود أولياء الأمور"
    return False, f"تعذّر ضبط استقبال الردود: HTTP {st}"


# ═══════════════════════════════════════════════════════════════════
#  التفعيل — جلسة هذه المدرسة من سيرفر درب الطلاب، بلا مفتاح يكتبه أحد
# ═══════════════════════════════════════════════════════════════════
# الطلب موقَّع بمفتاح نفق المدرسة الخاص (Ed25519، ولّده السيرفر عند التجهيز)،
# والسيرفر يتحقق بمفتاحها العام. معرّف المدرسة وحده علنيّ فلا يكفي.
# الخادم: tools/server/wa_provision/server.py — والنصّ الموقَّع بالترتيب نفسه.
ACTIVATE_URL = os.environ.get("DARBSTU_WA_ACTIVATE", "https://darbstu.com/api/wa/activate")
ACTIVATE_PURPOSE = "darbstu-wa-activate"
NOT_PROVISIONED = ("هذا الجهاز غير مُجهَّز لدى درب الطلاب (لا معرّف مدرسة أو مفتاح نفق) — "
                   "تواصل مع الدعم، أو أدخل بيانات الجلسة يدوياً")


def _openssh_ed25519_seed(path) -> bytes:
    """بذرة Ed25519 (٣٢ بايت) من مفتاح OpenSSH غير مشفّر — صيغة openssh-key-v1."""
    with open(path, encoding="ascii") as f:
        b64 = "".join(ln.strip() for ln in f if ln.strip() and not ln.startswith("-----"))
    raw = base64.b64decode(b64)
    magic = b"openssh-key-v1\0"
    if not raw.startswith(magic):
        raise ValueError("ليس مفتاح OpenSSH")

    def reader(buf, pos):
        def u32():
            nonlocal pos
            v = struct.unpack(">I", buf[pos:pos + 4])[0]
            pos += 4
            return v

        def string():
            nonlocal pos
            n = u32()
            v = buf[pos:pos + n]
            pos += n
            return v
        return u32, string

    u32, string = reader(raw, len(magic))
    if string() != b"none":                    # التشفير
        raise ValueError("المفتاح محمي بكلمة مرور")
    string(), string()                         # اشتقاق المفتاح وخياراته
    for _ in range(u32()):
        string()                               # المفاتيح العامة
    _, field = reader(string(), 8)             # القسم الخاص بعد checkint ×2
    if field() != b"ssh-ed25519":
        raise ValueError("ليس مفتاح ed25519")
    pub, secret = field(), field()             # العام، ثم البذرة يليها العام
    if len(pub) != 32 or len(secret) != 64 or secret[32:] != pub:
        raise ValueError("مفتاح تالف")
    return secret[:32]


def _activation_body(sid, key_path, now=None, nonce=None) -> dict:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    ts = int(time.time() if now is None else now)
    nonce = nonce or secrets.token_hex(16)
    msg = ("%s\n%s\n%d\n%s" % (ACTIVATE_PURPOSE, sid, ts, nonce)).encode("utf-8")
    key = Ed25519PrivateKey.from_private_bytes(_openssh_ed25519_seed(key_path))
    return {"school_id": sid, "ts": ts, "nonce": nonce,
            "sig": base64.b64encode(key.sign(msg)).decode("ascii")}


def request_session(timeout=45) -> dict:
    """يطلب جلسة هذه المدرسة من السيرفر — لا يحفظ شيئاً. {'ok','msg', وقيم الجلسة}."""
    try:
        import provisioning
        sid = str(provisioning.get_tunnel_settings().get("school_id") or "").strip()
        key_path = provisioning.KEY_FILE
    except Exception:
        sid, key_path = "", ""
    if not sid or not key_path or not os.path.isfile(key_path):
        return {"ok": False, "msg": NOT_PROVISIONED}
    try:
        body = _activation_body(sid, key_path)
    except Exception as e:
        return {"ok": False, "msg": f"تعذّر توقيع الطلب بمفتاح المدرسة: {e}"}
    try:
        from constants import APP_VERSION
        r = requests.post(ACTIVATE_URL, json=body, timeout=timeout,
                          headers={"User-Agent": "DarbStu/" + str(APP_VERSION)})
    except requests.exceptions.RequestException as e:
        return {"ok": False, "msg": f"تعذّر الاتصال بسيرفر درب الطلاب: {e}"}
    try:
        d = r.json()
    except Exception:
        d = {}
    if r.status_code != 200 or not d.get("ok"):
        return {"ok": False, "msg": d.get("msg") or f"رفض سيرفر درب الطلاب الطلب: HTTP {r.status_code}"}
    out = {k: str(d.get(k) or "").strip() for k in
           ("evolution_server_url", "evolution_instance_name", "evolution_api_key")}
    if not all(out.values()):
        return {"ok": False, "msg": "ردٌّ ناقص من سيرفر درب الطلاب"}
    out.update(ok=True, created=bool(d.get("created")))
    return out


def activate(provider_choice=None, timeout=45) -> dict:
    """
    يفعّل الواتساب السحابي لهذه المدرسة: يجلب جلستها، ويحفظها مع المزوّد المختار
    (السحابي إن لم يُختر غيره)، ويضبط استقبال الردود. {'ok','msg','webhook_ok','webhook_msg'}
    """
    res = request_session(timeout=timeout)
    if not res.get("ok"):
        return {"ok": False, "msg": res.get("msg", "")}
    from config_manager import load_config, save_config, invalidate_config_cache
    prov = provider_choice if provider_choice in ("evolution", "auto") else "evolution"
    cfg = load_config()
    cfg.update({"whatsapp_provider": prov,
                "evolution_server_url": res["evolution_server_url"].rstrip("/"),
                "evolution_instance_name": res["evolution_instance_name"],
                "evolution_api_key": res["evolution_api_key"]})
    save_config(cfg)
    invalidate_config_cache()
    _state_cache["at"] = 0.0
    okw, msgw = ensure_webhook()
    return {"ok": True, "created": res["created"], "provider": prov,
            "instance": res["evolution_instance_name"],
            "msg": ("فُعِّل الواتساب السحابي لهذه المدرسة" if res["created"]
                    else "جلسة هذه المدرسة السحابية جاهزة"),
            "webhook_ok": okw, "webhook_msg": msgw}


# ═══════════════════════════════════════════════════════════════════
#  دفتر الطلبات المعلّقة (نظير pending_excuses.json في server.js)
# ═══════════════════════════════════════════════════════════════════
_pending_lock = threading.RLock()


def _pending_path():
    # وقت الاستدعاء لا الاستيراد: مجلد البيانات لكل مرحلة في مدرسة المرحلتين
    import constants
    return os.path.join(getattr(constants, "DATA_DIR", DATA_DIR), "evolution_pending.json")


def load_pending() -> dict:
    with _pending_lock:
        try:
            with open(_pending_path(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}


def save_pending(d: dict):
    with _pending_lock:
        p = _pending_path()
        tmp = p + ".tmp"
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        except Exception as e:
            print(f"[EVO-BOT] تعذّر حفظ الطلبات المعلّقة: {e}")


def record_pending(digits, student_data):
    """كما يفعل server.js بعد إرسالٍ يحمل student_data: يُنتظر ردّ وليّ الأمر."""
    if not (student_data and (student_data.get("student_id") or student_data.get("permission_id"))):
        return
    with _pending_lock:
        d = load_pending()
        d[digits] = dict(student_data, sent_at=datetime.datetime.utcnow().isoformat() + "Z")
        save_pending(d)


def _pending_count(d):
    return len([k for k in d if k != "_lid_map"])


def _find_pending(d, raw):
    raw = re.sub(r"@.+$", "", raw or "")
    if raw in d and raw != "_lid_map":
        return raw, d[raw]
    tail = raw[-8:]
    for k, v in d.items():
        if k == "_lid_map":
            continue
        if tail and (k.endswith(tail) or raw.endswith(k[-8:])):
            return k, v
    lid = (d.get("_lid_map") or {}).get(raw)
    if lid and lid in d:
        return lid, d[lid]
    return None, None


# ═══════════════════════════════════════════════════════════════════
#  البوت المستقبِل
# ═══════════════════════════════════════════════════════════════════
def bot_config() -> dict:
    """حالة البوت وكلماته — الملف نفسه الذي يقرؤه server.js، فالتبديل لا يغيّرها."""
    from whatsapp_service import wa_file
    out = {"bot_enabled": False, "keywords": list(DEFAULT_EXCUSE_KEYWORDS)}
    try:
        with open(wa_file("bot_config.json"), encoding="utf-8") as f:
            raw = f.read().strip()
        if raw:
            d = json.loads(raw)
            if isinstance(d.get("bot_enabled"), bool):
                out["bot_enabled"] = d["bot_enabled"]
            if isinstance(d.get("keywords"), list) and d["keywords"]:
                out["keywords"] = [str(k).strip() for k in d["keywords"] if str(k).strip()]
    except Exception:
        pass
    return out


def write_bot_config(enabled=None, keywords=None) -> bool:
    """يكتب حالة البوت في ملفه مباشرةً — في السحابي لا خادم Node يكتبه."""
    from whatsapp_service import wa_file
    cur = bot_config()
    if isinstance(enabled, bool):
        cur["bot_enabled"] = enabled
    if keywords:
        cur["keywords"] = [str(k).strip() for k in keywords if str(k).strip()]
    p = wa_file("bot_config.json")
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except Exception as e:
        print(f"[EVO-BOT] تعذّر حفظ إعداد البوت: {e}")
        return False


def _is_reject(text_lower):
    if any(n in text_lower for n in _NEGATED_APPROVAL):
        return True
    return any(text_lower == w or text_lower.startswith(w) for w in REJECT_KEYWORDS)


def _message_text(msg: dict) -> str:
    m = msg.get("message") or {}
    return str(m.get("conversation")
               or (m.get("extendedTextMessage") or {}).get("text")
               or (m.get("ephemeralMessage") or {}).get("message", {}).get("conversation")
               or "").strip()


def _sender(key: dict) -> tuple:
    """(المعرّف الذي نردّ إليه، الرقم إن عُرف). LID يُحوَّل برقمه البديل إن أرسله الخادم."""
    jid = str(key.get("remoteJid") or "")
    if jid.endswith("@lid"):
        for k in ("remoteJidAlt", "senderPn", "participantPn", "participantAlt"):
            alt = str(key.get(k) or "")
            if alt and not alt.endswith("@lid"):
                return jid, re.sub(r"@.+$", "", alt)
        return jid, ""
    return jid, re.sub(r"@.+$", "", jid)


def _reply(jid, text):
    # الردّ على وليّ أمرٍ راسلنا — كما في server.js (msg.reply) بلا سقف يومي
    ok, msg, _ = send_text(jid, text, timeout=30)
    if not ok:
        print(f"[EVO-BOT] تعذّر الردّ: {msg}")
    return ok


def handle_webhook(payload: dict, replies=None) -> str:
    """
    يعالج رسالة واردة من Evolution كما يفعل server.js. يُرجع وصفاً قصيراً لما جرى.
    `replies` للاختبار: قائمة تُجمع فيها الردود بدل إرسالها.
    """
    send = (lambda j, t: replies.append((j, t))) if replies is not None else _reply
    if str(payload.get("event") or "").lower().replace("_", ".") != "messages.upsert":
        return "ignored:event"
    data = payload.get("data") or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    key = data.get("key") or {}
    if key.get("fromMe"):
        return "ignored:fromMe"
    jid, phone = _sender(key)
    if jid.endswith("@g.us") or jid == "status@broadcast" or not jid:
        return "ignored:group"

    cfg = bot_config()
    if not cfg["bot_enabled"]:
        return "ignored:bot_off"
    with _pending_lock:
        pend = load_pending()
        if _pending_count(pend) == 0:
            return "ignored:no_pending"
        if jid.endswith("@lid") and phone:
            pend.setdefault("_lid_map", {})[re.sub(r"@.+$", "", jid)] = phone
            save_pending(pend)
        pkey, pdata = (None, None)
        if phone:
            pkey, pdata = _find_pending(pend, phone)
        if not pkey:
            pkey, pdata = _find_pending(pend, jid)
    if not pkey:
        return "ignored:not_pending"

    text = _message_text(data)
    low = text.lower()
    who = phone or re.sub(r"@.+$", "", jid)

    if pdata.get("type") == "permission":
        rej = _is_reject(low)
        app = (not rej) and any(w in low for w in APPROVE_KEYWORDS)
        if not app and not rej:
            send(jid, "للموافقة على استئذان ابنك أرسل: موافق\nللرفض أرسل: رفض")
            return "permission:ask"
        from alerts_service import PERM_APPROVED, PERM_REJECTED, update_permission_status
        status = PERM_APPROVED if app else PERM_REJECTED
        try:
            exit_time = datetime.datetime.now().strftime("%H:%M") if app else None
            update_permission_status(int(pdata.get("permission_id") or 0), status, exit_time)
        except Exception as e:
            print(f"[EVO-BOT] خطأ الاستئذان: {e}")
            send(jid, f"📝 تم استلام ردك: {status} — ستتم المراجعة.")
            return "permission:error"
        name = pdata.get("student_name", "")
        send(jid, (f"✅ تم تسجيل موافقتك\nالطالب: {name}\nيمكنه الخروج الآن.\n\nشكراً."
                   if app else f"❌ تم تسجيل رفضك لاستئذان {name}.\n\nشكراً."))
        with _pending_lock:
            d = load_pending(); d.pop(pkey, None); save_pending(d)
        return "permission:" + ("approved" if app else "rejected")

    # ─── عذر غياب ───────────────────────────────────────────────────
    if not any(str(k).lower() in low for k in cfg["keywords"]):
        send(jid, "للتسجيل كعذر أرسل: عذر أو مريض أو سفر")
        return "excuse:ask"
    try:
        sent = datetime.datetime.fromisoformat(str(pdata.get("sent_at", "")).replace("Z", ""))
        hours = (datetime.datetime.utcnow() - sent).total_seconds() / 3600
    except Exception:
        hours = 0
    if hours > _EXCUSE_WINDOW_H:
        send(jid, "⚠️ انتهت مهلة تقديم العذر (48 ساعة).")
        return "excuse:expired"
    from constants import now_riyadh_date
    from database import insert_excuse, student_has_excuse
    date_str = pdata.get("date") or now_riyadh_date()
    try:
        if not student_has_excuse(pdata.get("student_id", ""), date_str):
            insert_excuse(date_str, pdata.get("student_id", ""), pdata.get("student_name", ""),
                          pdata.get("class_id", ""), pdata.get("class_name", ""), text,
                          source="whatsapp", approved_by=who)
    except Exception as e:
        print(f"[EVO-BOT] خطأ العذر: {e}")
        send(jid, f"📝 تم استلام عذرك للطالب {pdata.get('student_name', '')}.")
        return "excuse:error"
    send(jid, f"✅ تم تسجيل العذر\nالطالب: {pdata.get('student_name', '')}\n"
              f"التاريخ: {date_str}\nالسبب: {text}\n\nشكراً.")
    with _pending_lock:
        d = load_pending(); d.pop(pkey, None); save_pending(d)
    return "excuse:recorded"


def verify_webhook(token: str, payload: dict) -> bool:
    """الرمز في الرابط، ومفتاح الجلسة الذي يرسله Evolution في الجسم — كلاهما."""
    try:
        cfg = _cfg()
        want = str(cfg.get("evolution_webhook_token") or "")
        key = str(cfg.get("evolution_api_key") or "")
        if not want or not hmac.compare_digest(want, str(token or "")):
            return False
        got = str((payload or {}).get("apikey") or "")
        return (not got) or (not key) or hmac.compare_digest(got, key)
    except Exception:
        return False
