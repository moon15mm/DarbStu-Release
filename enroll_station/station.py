# -*- coding: utf-8 -*-
"""
station.py — مُشغّل أداة تسجيل البصمات المستقلّة.

يبدأ خادماً محلياً على 127.0.0.1 ويفتح المتصفح على واجهة الأداة. لا
مصادقة ولا نفق ولا ترخيص — أداة تشغيل مباشر على لابتوب موصول بالجهاز.

    python -m enroll_station.station

يُحزَّم لاحقاً كـEXE مستقلّ صغير (PyInstaller) لينتقل بين الأجهزة بلا
تثبيت بايثون.
"""
import os
import sys
import threading
import webbrowser

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

HOST = "127.0.0.1"
PORT = 8777


def _open_browser():
    import time
    time.sleep(1.2)
    try:
        webbrowser.open("http://%s:%d/" % (HOST, PORT))
    except Exception:
        pass


def main():
    import uvicorn
    from enroll_station.app import app
    print("=" * 60)
    print("  أداة تسجيل بصمات الطلاب")
    print("  افتح: http://%s:%d/" % (HOST, PORT))
    print("=" * 60)
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
