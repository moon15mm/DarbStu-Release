# -*- coding: utf-8 -*-
"""
api/app.py — إنشاء تطبيق FastAPI وإضافة الـ Middleware والـ Routers
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI()

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    # التفاصيل الكاملة في سجل الخادم فقط — لا تُعاد للعميل حتى لا تكشف
    # مسارات الملفات وبنية قاعدة البيانات لمن يصل عبر النفق.
    print(f"[API-ERROR] {request.url}: {exc}")
    traceback.print_exc()
    return JSONResponse({"detail": "حدث خطأ داخلي في الخادم"}, status_code=500)

class RemoveCSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:;"
        )
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

app.add_middleware(RemoveCSPMiddleware)

# تأنيث صفحات مدارس البنات — يعمل على HTML فقط ولا يفعل شيئاً في
# مدارس البنين. انظر gender_ui.py.
try:
    from gender_ui import install_web_middleware as _install_fem
    _install_fem(app)
except Exception as _e:
    print(f"[GENDER-UI] تعذّر تركيب وسيط التأنيث: {_e}")

# ── تسجيل الـ Routers مباشرة عند استيراد هذا الملف ──
from api.mobile_routes    import router as _mobile_router
from api.misc_routes      import router as _misc_router
from api.web_routes       import router as _web_router
from api.points_api       import router as _points_router
from api.bus_routes       import router as _bus_router
app.include_router(_mobile_router)
app.include_router(_misc_router)
app.include_router(_web_router)
app.include_router(_points_router)
app.include_router(_bus_router)

# ── خدمة الملفات الثابتة ──
# لا يُخدَم مجلد data كاملاً: فهو يحوي config.json (وفيه cloud_token وأرقام
# الجوالات) و students.json و saved_login.json و backups/*.zip.
# نكشف فقط المجلدين اللذين تُبنى منهما روابط عامة في الواجهة:
#   /data/attachments/circulars/...  (مرفقات التعاميم)
#   /data/school_stories/...         (صور قصص المدرسة)
from constants import DATA_DIR
import os
os.makedirs(DATA_DIR, exist_ok=True)

_PUBLIC_SUBDIRS = ("attachments", "school_stories")
for _sub in _PUBLIC_SUBDIRS:
    _path = os.path.join(DATA_DIR, _sub)
    os.makedirs(_path, exist_ok=True)
    app.mount(f"/data/{_sub}", StaticFiles(directory=_path), name=f"data_{_sub}")

def register_routers():
    """متوافق مع الاستدعاء القديم — الـ Routers مُسجَّلة مسبقاً."""
    pass
