from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import settings
from ..database import init_db

log = logging.getLogger("crypta_dashboard")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def create_dashboard(bot) -> FastAPI:
    init_db()
    app = FastAPI(title="Crypta Bot Dashboard")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    def read_guild_rows() -> list[sqlite3.Row]:
        conn = sqlite3.connect(settings.database_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS guild_settings (guild_id INTEGER PRIMARY KEY, panel_channel_id INTEGER DEFAULT 0, music_channel_id INTEGER DEFAULT 0, level_channel_id INTEGER DEFAULT 0, dashboard_note TEXT DEFAULT '', level_enabled INTEGER DEFAULT 1, level_roles_json TEXT DEFAULT '[]')"
            )
            conn.commit()
            rows = conn.execute("SELECT * FROM guild_settings ORDER BY guild_id").fetchall()
            return rows
        except Exception:
            log.exception("Dashboard failed to read guild settings")
            return []
        finally:
            conn.close()

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        ok = request.cookies.get("crypta_admin") == settings.dashboard_admin_key
        if not ok:
            return templates.TemplateResponse("login.html", {"request": request, "error": None})
        guilds = [dict(row) for row in read_guild_rows()]
        return templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "guilds": guilds, "public_url": settings.dashboard_public_url},
        )

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request, admin_key: str = Form(...)):
        if admin_key != settings.dashboard_admin_key:
            return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный ключ"})
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("crypta_admin", admin_key, httponly=True, samesite="lax")
        return response

    @app.post("/guild/{guild_id}")
    async def update_guild(request: Request, guild_id: int, panel_channel_id: int = Form(0), music_channel_id: int = Form(0), level_channel_id: int = Form(0), dashboard_note: str = Form(""), level_enabled: int = Form(0)):
        if request.cookies.get("crypta_admin") != settings.dashboard_admin_key:
            return RedirectResponse(url="/", status_code=303)
        await bot.db.update_guild_settings(
            guild_id,
            panel_channel_id=panel_channel_id,
            music_channel_id=music_channel_id,
            level_channel_id=level_channel_id,
            dashboard_note=dashboard_note,
            level_enabled=level_enabled,
        )
        return RedirectResponse(url="/", status_code=303)

    return app
