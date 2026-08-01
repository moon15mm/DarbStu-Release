import datetime, sqlite3, json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from database import get_db
from config_manager import load_config

router = APIRouter()

def _get_current_user(request: Request) -> dict:
    from api.web_routes import _get_current_user as _web_get_user
    return _web_get_user(request)

def _ensure_tables():
    con = get_db(); cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS student_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            points INTEGER NOT NULL,
            reason TEXT,
            author_id TEXT NOT NULL,
            author_name TEXT,
            date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS teacher_points_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            month TEXT NOT NULL,
            extra_points INTEGER NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
    """)
    con.commit(); con.close()

_ensure_tables()

@router.get("/web/api/admin/points-logs-v2")
async def api_admin_points_logs_v2(request: Request):
    user = _get_current_user(request)
    if user.get("role") not in ("admin", "deputy", "staff"):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=403)
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    try:
        cur.execute("SELECT * FROM student_points ORDER BY date DESC, id DESC LIMIT 500")
        logs = [dict(r) for r in cur.fetchall()]
        return {"ok": True, "logs": logs}
    except Exception as e:
        return {"ok": False, "msg": str(e)}
    finally: con.close()

@router.get("/web/api/admin/points-usage-v2")
async def api_admin_points_usage_v2(request: Request):
    user = _get_current_user(request)
    if user.get("role") not in ("admin", "deputy", "staff"):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=403)
    month = request.query_params.get("month", datetime.date.today().isoformat()[:7])
    con = get_db(); con.row_factory = sqlite3.Row; cur = con.cursor()
    try:
        cur.execute("SELECT username, full_name, role FROM users WHERE role IN ('teacher', 'deputy', 'activity_leader', 'counselor')")
        users = [dict(r) for r in cur.fetchall()]
        cfg = load_config(); base_limit = cfg.get("monthly_points_limit", 100)
        usage = []
        for u in users:
            cur.execute("SELECT SUM(points) FROM student_points WHERE author_id = ? AND date LIKE ?", (u['username'], f"{month}%"))
            consumed = cur.fetchone()[0] or 0
            cur.execute("SELECT SUM(extra_points) FROM teacher_points_adjustments WHERE username = ? AND month = ?", (u['username'], month))
            extra = cur.fetchone()[0] or 0
            total_limit = base_limit + extra
            usage.append({
                "username": u['username'],
                "name": u['full_name'] or u['username'],
                "role": u['role'],
                "used": consumed,
                "extra": extra,
                "limit": total_limit,
                "remaining": max(0, total_limit - consumed)
            })
        return {"ok": True, "usage": usage}
    except Exception as e:
        return {"ok": False, "msg": str(e)}
    finally: con.close()

@router.post("/web/api/admin/points-adjust")
async def api_admin_points_adjust(request: Request):
    user = _get_current_user(request)
    if user.get("role") not in ("admin", "deputy"):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=403)
    try:
        data = await request.json()
        u = data.get("username"); p = data.get("points", 0); r = data.get("reason", "")
        m = datetime.date.today().isoformat()[:7]
        con = get_db(); cur = con.cursor()
        cur.execute("INSERT INTO teacher_points_adjustments (username, month, extra_points, reason, created_at) VALUES (?,?,?,?,?)",
                    (u, m, int(p), r, datetime.datetime.now().isoformat()))
        con.commit(); con.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

@router.delete("/web/api/admin/points-delete/{rid}")
async def api_admin_points_delete(request: Request, rid: int):
    user = _get_current_user(request)
    if user.get("role") not in ("admin", "deputy"):
        return JSONResponse({"ok": False, "msg": "غير مصرح"}, status_code=403)
    con = get_db(); cur = con.cursor()
    try:
        cur.execute("DELETE FROM student_points WHERE id = ?", (rid,))
        con.commit(); con.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "msg": str(e)}
