# -*- coding: utf-8 -*-
"""
whatsapp_service.py — خدمة إرسال رسائل الواتساب
"""
import requests, os, subprocess, sys, time, threading, base64, random
from constants import BASE_DIR, WHATS_PATH, DATA_DIR
from config_manager import load_config, render_message

# ─── ميزات مكافحة الحظر (Anti-Ban Features) ───
_GREETINGS_BOYS = [
    "عزيزي ولي الأمر،",
    "الأخ الفاضل ولي أمر الطالب،",
    "المحترم ولي أمر الطالب/",
    "نحييكم من إدارة المدرسة،",
    "السلام عليكم ورحمة الله وبركاته،",
    "ولي الأمر الكريم،",
    "إلى ولي أمر الطالب المحترم،",
]

_GREETINGS_GIRLS = [
    "عزيزتي ولية الأمر،",
    "الأخت الفاضلة ولية أمر الطالبة،",
    "المحترمة ولية أمر الطالبة/",
    "نحييكم من إدارة المدرسة،",
    "السلام عليكم ورحمة الله وبركاته،",
    "ولية الأمر الكريمة،",
    "إلى ولية أمر الطالبة المحترمة،",
]

# للتوافق مع أي استخدام مباشر لـ GREETINGS
GREETINGS = _GREETINGS_BOYS

def get_random_greeting():
    try:
        from config_manager import load_config
        pool = _GREETINGS_GIRLS if load_config().get("school_gender") == "girls" else _GREETINGS_BOYS
    except Exception:
        pool = _GREETINGS_BOYS
    return random.choice(pool)

def humanize_message(message: str) -> str:
    """تضيف ترحيباً عشوائياً وتغير بعض الكلمات لجعل الرسالة فريدة."""
    # إذا كانت الرسالة تبدأ بترحيب بالفعل، لا تضف واحداً آخر
    for g in GREETINGS:
        if message.startswith(g):
            return message
    return f"{get_random_greeting()}\n{message}"

def random_delay(min_sec=5, max_sec=15):
    """تأخير عشوائي لمحاكاة السلوك البشري."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)

def check_whatsapp_server_status() -> bool:
    """يفحص إذا كان خادم الواتساب يعمل ويستجيب"""
    try:
        response = requests.get("http://127.0.0.1:3000/status", timeout=5)
        return response.status_code == 200
    except:
        return False

def get_wa_servers() -> list:
    """يُرجع قائمة خوادم واتساب المتاحة (منفذ واحد أو أكثر)."""
    cfg     = load_config()
    servers = cfg.get("wa_servers", [])
    if not servers:
        return [{"port": 3000}]
    return servers

# مؤشر دوري للتناوب بين الخوادم
_WA_SERVER_INDEX = 0

def get_next_wa_server() -> dict:
    """يُرجع الخادم التالي بالتناوب (Round Robin)."""
    global _WA_SERVER_INDEX
    servers = get_wa_servers()
    server  = servers[_WA_SERVER_INDEX % len(servers)]
    _WA_SERVER_INDEX = (_WA_SERVER_INDEX + 1) % len(servers)
    return server

def send_whatsapp_message(phone: str, message_body: str, student_data: dict = None, humanize: bool = False) -> (bool, str):
    if humanize:
        message_body = humanize_message(message_body)
    
    # اختر الخادم التالي بالتناوب
    _srv    = get_next_wa_server()
    _port   = _srv.get("port", 3000)
    API_URL = "http://127.0.0.1:{}/send-message".format(_port)
    
    if not phone:
        msg = "رقم الجوال غير موجود أو فارغ."
        print(f"[WHATSAPP-WARN] {msg}")
        return False, msg

    # تنظيف رقم الهاتف
    cleaned_phone = ''.join(filter(str.isdigit, str(phone)))
    if not cleaned_phone:
        msg = f"رقم الجوال '{phone}' غير صالح."
        print(f"[WHATSAPP-WARN] {msg}")
        return False, msg

    # تحويل التنسيق المحلي إلى دولي
    if len(cleaned_phone) == 10 and cleaned_phone.startswith('05'):
        cleaned_phone = '966' + cleaned_phone[1:]
    elif len(cleaned_phone) == 9 and cleaned_phone.startswith('5'):
        cleaned_phone = '966' + cleaned_phone
    elif len(cleaned_phone) == 12 and cleaned_phone.startswith('966'):
        # الرقم بالفعل بالتنسيق الدولي
        pass
    else:
        msg = f"تنسيق رقم الجوال غير مدعوم: {cleaned_phone}"
        print(f"[WHATSAPP-WARN] {msg}")
        return False, msg

    try:
        print(f"[WHATSAPP] محاولة إرسال إلى: {cleaned_phone}")
        print(f"[WHATSAPP] نص الرسالة: {message_body[:100]}...")

        payload = {
            "number":  cleaned_phone,
            "message": message_body
        }
        # إضافة student_data إذا مُررت (لتفعيل بوت الأعذار)
        if student_data:
            payload["student_data"] = student_data

        response = requests.post(API_URL, json=payload, timeout=30)
        print(f"[WHATSAPP] استجابة الخادم: {response.status_code}")
        
        if response.status_code == 200:
            response_data = response.json()
            if response_data.get('status') == 'success':
                print(f"[WHATSAPP] ✅ تم الإرسال بنجاح إلى {cleaned_phone}")
                return True, "تم الإرسال بنجاح"
            else:
                error_msg = response_data.get('message', response.text)
                print(f"[WHATSAPP] ❌ فشل الإرسال: {error_msg}")
                return False, f"فشل: {error_msg}"
        elif response.status_code == 503:
            error_msg = "الواتساب غير متصل — امسح QR Code أولاً"
            print(f"[WHATSAPP] ❌ {error_msg}")
            return False, error_msg
        else:
            # أظهر رسالة الخطأ التفصيلية من الخادم
            try:
                err_detail = response.json().get('message', response.text)
            except Exception:
                err_detail = response.text
            error_msg = f"HTTP {response.status_code}: {err_detail}"
            print(f"[WHATSAPP] ❌ {error_msg}")
            return False, error_msg
            
    except requests.exceptions.ConnectionError:
        error_msg = "فشل الاتصال بخادم الواتساب. تأكد من تشغيل الخادم."
        print(f"[WHATSAPP] ❌ {error_msg}")
        return False, error_msg
        
    except requests.exceptions.Timeout:
        error_msg = "انتهت مهلة الاتصال بخادم الواتساب."
        print(f"[WHATSAPP] ❌ {error_msg}")
        return False, error_msg
        
    except Exception as e:
        error_msg = f"حدث خطأ غير متوقع: {e}"
        print(f"[WHATSAPP] ❌ {error_msg}")
        return False, error_msg

def send_whatsapp_pdf(phone: str, pdf_bytes: bytes, filename: str, caption: str = "") -> tuple:
    """
    يرسل ملف PDF عبر واتساب - endpoint: /send-document
    """
    _srv    = get_next_wa_server()
    _port   = _srv.get("port", 3000)
    API_URL = "http://127.0.0.1:{}/send-document".format(_port)

    if not phone:
        return False, "رقم الجوال فارغ"

    cleaned_phone = "".join(filter(str.isdigit, str(phone)))
    if len(cleaned_phone) == 10 and cleaned_phone.startswith("05"):
        cleaned_phone = "966" + cleaned_phone[1:]
    elif len(cleaned_phone) == 9 and cleaned_phone.startswith("5"):
        cleaned_phone = "966" + cleaned_phone
    elif not (len(cleaned_phone) == 12 and cleaned_phone.startswith("966")):
        return False, f"تنسيق رقم الجوال غير مدعوم: {cleaned_phone}"

    try:
        b64_data = base64.b64encode(pdf_bytes).decode("utf-8")
        payload = {
            "number":   cleaned_phone,
            "filename": filename,
            "mimetype": "application/pdf",
            "data":     b64_data,
            "caption":  caption,
        }
        response = requests.post(API_URL, json=payload, timeout=60)
        if response.status_code == 200:
            rd = response.json()
            if rd.get("status") == "success":
                return True, "تم ارسال PDF بنجاح"
            return False, rd.get("message", response.text)
        return False, f"HTTP {response.status_code}: {response.text}"
    except requests.exceptions.ConnectionError:
        return False, "فشل الاتصال بخادم الواتساب"
    except Exception as e:
        return False, f"خطأ: {e}"

def start_whatsapp_server():
    """يفتح نافذة خادم الواتساب Node.js."""
    try:
        if not os.path.isdir(WHATS_PATH):
            # messagebox من خيط خلفي لا يرمي استثناءً — بل يتجمّد ويُعلّق
            # الخادم كله، فنفحص الخيط قبل عرض أي نافذة.
            import threading as _th
            if _th.current_thread() is _th.main_thread():
                try:
                    from tkinter import messagebox
                    messagebox.showerror("خطأ", f"المجلد غير موجود:\n{WHATS_PATH}")
                except Exception:
                    pass
            print(f"[WA] المجلد غير موجود: {WHATS_PATH}")
            return
            
        _app_dir = (os.path.dirname(sys.executable)
                    if getattr(sys, 'frozen', False) else BASE_DIR)
        _node_local = os.path.join(_app_dir, "node.exe")
        
        if os.path.isfile(_node_local):
            args = [_node_local, "server.js"]
            use_shell = False
        else:
            args = ["npm", "start"]
            use_shell = True
            
        kwargs = {
            "cwd": WHATS_PATH,
            "shell": use_shell,
            "creationflags": subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            "start_new_session": True
        }
        
        subprocess.Popen(args, **kwargs)
        print("[WA] بدأ تشغيل خادم الواتساب في الخلفية.")

    except Exception as e:
        import threading as _th
        if _th.current_thread() is _th.main_thread():
            try:
                from tkinter import messagebox
                messagebox.showerror("خطأ", f"تعذّر تشغيل السيرفر:\n{e}")
            except Exception:
                pass
        print(f"[WA] تعذّر تشغيل السيرفر: {e}")
