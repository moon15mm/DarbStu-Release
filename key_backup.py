# -*- coding: utf-8 -*-
"""
key_backup.py — نسخ احتياطي مشفَّر لمفاتيح خادم DarbStu.

مفتاحان لا ثالث لهما على الخادم، وضياع أيٍّ منهما لا يُصلَح عن بُعد:

  • update_ed25519.key   — يوقّع التحديثات. المفتاح العام محفور في كل
    نسخة مثبَّتة، فالمفتاح الجديد تَرفضه كل المدارس، وتنقطع قناة
    التحديث نهائياً حتى تُعيد التنصيب يدوياً في كل مدرسة.
  • license_ed25519.key  — يوقّع تذاكر الترخيص. ضياعه أسوأ: تتوقف
    المدارس عند انتهاء اشتراكاتها ولا يمكن تجديدها.

**النسخة نفسها سرّ.** من يملك مفتاح التحديث يوقّع تحديثاً خبيثاً تقبله
كل المدارس. لذلك التشفير هنا **إلزامي لا خياري**، خاصة أن جهاز التطوير
سبق أن نُفِّذت عليه حزمة npm خبيثة.

الصيغتان مختلفتان (خام base64 مقابل PEM) فتُعامَل المفاتيح كبايتات
معتمة، ويُشتقّ منها المفتاح العام للتحقق من سلامة النسخة.
"""
import base64
import datetime
import json
import os
import subprocess

KEY_DIR = "/etc/darbstu"
KEYS = ("update_ed25519.key", "license_ed25519.key")
_PBKDF2_ITERS = 200_000
_MAGIC = "darbstu-key-backup-v1"

_NO_WINDOW = (dict(creationflags=subprocess.CREATE_NO_WINDOW)
              if os.name == "nt" else {})


def _find_ssh(name="ssh") -> str:
    import shutil
    exe = name + (".exe" if os.name == "nt" else "")
    for p in (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "System32", "OpenSSH", exe),
              os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                           "Git", "usr", "bin", exe)):
        if os.path.isfile(p):
            return p
    return shutil.which(name) or name


# ───────────────────────────────────────────────────────────────
#  التشفير
# ───────────────────────────────────────────────────────────────
def _fernet(passphrase: str, salt: bytes):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=_PBKDF2_ITERS)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(passphrase.encode())))


# ───────────────────────────────────────────────────────────────
#  اشتقاق المفتاح العام — للتحقق من صلاحية النسخة
# ───────────────────────────────────────────────────────────────
def public_of(name: str, raw: bytes) -> str:
    """
    يشتقّ المفتاح العام (base64) من المفتاح الخاص.

    نسخة احتياطية لا يُشتقّ منها مفتاح عام صحيح = ملف تالف. الفحص هنا
    يمنع اكتشاف ذلك بعد ضياع الأصل، حين لا ينفع الاكتشاف.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    txt = raw.strip()
    if txt.startswith(b"-----BEGIN"):
        sk = serialization.load_pem_private_key(txt, password=None)
    else:
        sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(txt))
    return base64.b64encode(sk.public_key().public_bytes_raw()).decode()


# ───────────────────────────────────────────────────────────────
#  الجلب من الخادم
# ───────────────────────────────────────────────────────────────
def fetch_keys(ssh_host: str = "backup-server", timeout: int = 60) -> dict:
    """يقرأ المفاتيح من الخادم إلى الذاكرة — لا تُكتب على القرص أبداً."""
    ssh = _find_ssh("ssh")
    out = {}
    for name in KEYS:
        r = subprocess.run(
            [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
             ssh_host, f"cat {KEY_DIR}/{name}"],
            capture_output=True, timeout=timeout, **_NO_WINDOW)
        if r.returncode != 0 or not r.stdout.strip():
            err = (r.stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"تعذّر قراءة {name}: {err[:120]}")
        out[name] = r.stdout
    return out


# ───────────────────────────────────────────────────────────────
#  النسخ
# ───────────────────────────────────────────────────────────────
def backup(dest_path: str, passphrase: str,
           ssh_host: str = "backup-server") -> dict:
    """
    يأخذ نسخة مشفَّرة من المفتاحين ويتحقق من صلاحيتها قبل الحفظ.
    يُرجع تقريراً فيه بصمات المفاتيح العامة.
    """
    if not passphrase or len(passphrase) < 8:
        raise ValueError("كلمة السرّ قصيرة — ثمانية أحرف على الأقل.")

    keys = fetch_keys(ssh_host)

    pubs = {}
    for name, raw in keys.items():
        pubs[name] = public_of(name, raw)      # يرفع استثناءً إن كان تالفاً

    payload = {
        "magic": _MAGIC,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "host": ssh_host,
        "publics": pubs,
        "keys": {n: base64.b64encode(v).decode() for n, v in keys.items()},
    }

    salt = os.urandom(16)
    token = _fernet(passphrase, salt).encrypt(
        json.dumps(payload, ensure_ascii=False).encode())

    envelope = {
        "magic": _MAGIC,
        "kdf": {"name": "pbkdf2-sha256", "iterations": _PBKDF2_ITERS,
                "salt": base64.b64encode(salt).decode()},
        "created": payload["created"],
        "publics": pubs,          # علنية بطبيعتها — تُعرَّف النسخة بلا فكّها
        "data": token.decode(),
    }

    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    tmp = dest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)
    os.replace(tmp, dest_path)

    # قراءة فورية بنفس كلمة السرّ: نسخة لا تُفكّ لا قيمة لها
    check = verify(dest_path, passphrase)
    return {"path": dest_path, "publics": pubs,
            "created": payload["created"], "verified": check["ok"]}


def verify(path: str, passphrase: str) -> dict:
    """يفكّ النسخة ويتأكد أن المفاتيح داخلها سليمة ومطابقة."""
    with open(path, encoding="utf-8") as f:
        env = json.load(f)
    if env.get("magic") != _MAGIC:
        raise ValueError("الملف ليس نسخة مفاتيح DarbStu.")
    salt = base64.b64decode(env["kdf"]["salt"])
    try:
        data = _fernet(passphrase, salt).decrypt(env["data"].encode())
    except Exception:
        raise ValueError("كلمة السرّ غير صحيحة، أو الملف تالف.")
    payload = json.loads(data)

    results = {}
    for name, b64 in payload["keys"].items():
        raw = base64.b64decode(b64)
        derived = public_of(name, raw)
        expected = env["publics"].get(name)
        results[name] = {"public": derived, "matches": derived == expected,
                         "size": len(raw)}
    ok = all(r["matches"] for r in results.values()) and len(results) == len(KEYS)
    return {"ok": ok, "created": env.get("created"), "keys": results}


def restore(path: str, passphrase: str,
            ssh_host: str = "backup-server") -> dict:
    """
    يُعيد المفاتيح إلى الخادم. **يستبدل الموجود** — لا يُستدعى إلا بعد
    تأكيد صريح من المستخدم.
    """
    chk = verify(path, passphrase)
    if not chk["ok"]:
        raise ValueError("النسخة تالفة — أُوقف الاسترجاع.")

    with open(path, encoding="utf-8") as f:
        env = json.load(f)
    salt = base64.b64decode(env["kdf"]["salt"])
    payload = json.loads(_fernet(passphrase, salt).decrypt(env["data"].encode()))

    ssh = _find_ssh("ssh")
    done = []
    for name, b64 in payload["keys"].items():
        raw = base64.b64decode(b64)
        # يُكتب بصلاحيات 600 من البداية — لا لحظة يكون فيها مقروءاً
        cmd = (f"install -m 600 /dev/null {KEY_DIR}/{name} && "
               f"base64 -d > {KEY_DIR}/{name} && chmod 600 {KEY_DIR}/{name}")
        r = subprocess.run(
            [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
             ssh_host, cmd],
            input=b64.encode(), capture_output=True, timeout=60, **_NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError(
                f"فشل استرجاع {name}: "
                f"{(r.stderr or b'').decode('utf-8', 'replace')[:120]}")
        done.append(name)
    return {"restored": done}
