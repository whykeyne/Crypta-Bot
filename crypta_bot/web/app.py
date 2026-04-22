from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from ..config import settings
from ..database import init_db

log = logging.getLogger("crypta_dashboard")

BASE_DIR = Path(__file__).resolve().parent
API_BASE = "https://discord.com/api/v10"
ADMINISTRATOR = 0x8
MANAGE_GUILD = 0x20
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def bot_invite_url() -> str:
    if not settings.discord_client_id:
        return "#"
    query = urlencode({
        "client_id": settings.discord_client_id,
        "permissions": str(settings.bot_permissions),
        "scope": "bot applications.commands",
    })
    return f"https://discord.com/oauth2/authorize?{query}"


def create_dashboard(bot) -> FastAPI:
    init_db()
    app = FastAPI(title="Crypta Bot Dashboard")
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax", https_only=False)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    def logged_in(request: Request) -> bool:
        return bool(request.session.get("discord_user") and request.session.get("access_token"))

    async def fetch_discord_identity(access_token: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=20) as client:
            user_resp = await client.get(f"{API_BASE}/users/@me", headers=headers)
            user_resp.raise_for_status()
            guilds_resp = await client.get(f"{API_BASE}/users/@me/guilds", headers=headers)
            guilds_resp.raise_for_status()
        return user_resp.json(), guilds_resp.json()

    def manageable_guilds(discord_guilds: list[dict[str, Any]]) -> list[dict[str, Any]]:
        bot_guild_ids = {g.id for g in bot.guilds}
        items: list[dict[str, Any]] = []
        for guild in discord_guilds:
            try:
                perms = int(guild.get("permissions", 0))
            except Exception:
                perms = 0
            guild_id = int(guild.get("id", 0) or 0)
            if not guild_id or guild_id not in bot_guild_ids:
                continue
            if not (perms & ADMINISTRATOR or perms & MANAGE_GUILD):
                continue
            items.append({
                "id": guild_id,
                "name": guild.get("name", "Unknown guild"),
                "icon": guild.get("icon"),
                "configured": False,
            })
        items.sort(key=lambda item: item["name"].lower())
        return items

    async def load_dashboard_context(request: Request) -> dict[str, Any]:
        access_token = request.session.get("access_token")
        if not access_token:
            return {}
        user, guilds_raw = await fetch_discord_identity(access_token)
        request.session["discord_user"] = user
        guilds = manageable_guilds(guilds_raw)
        selected_id = request.query_params.get("guild")
        selected_guild = None
        guild_settings = None
        for guild in guilds:
            row = await bot.db.get_guild_settings(guild["id"])
            guild["configured"] = bool(row.get("panel_channel_id") or row.get("music_channel_id") or row.get("level_channel_id") or row.get("dashboard_note"))
            if selected_id and str(guild["id"]) == str(selected_id):
                selected_guild = guild
                guild_settings = row
        if selected_guild is None and guilds:
            selected_guild = guilds[0]
            guild_settings = await bot.db.get_guild_settings(selected_guild["id"])
        return {"user": user, "guilds": guilds, "selected_guild": selected_guild, "guild_settings": guild_settings}

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        if not logged_in(request):
            return templates.TemplateResponse(request, "landing.html", {"invite_url": bot_invite_url(), "public_url": settings.dashboard_public_url})
        try:
            ctx = await load_dashboard_context(request)
            return templates.TemplateResponse(request, "dashboard.html", {**ctx, "invite_url": bot_invite_url(), "public_url": settings.dashboard_public_url})
        except Exception:
            log.exception("Dashboard failed to render")
            return HTMLResponse("Internal Server Error", status_code=500)

    @app.get("/login")
    async def login(request: Request):
        if not settings.discord_client_id or not settings.discord_redirect_uri:
            return HTMLResponse("Discord OAuth is not configured yet.", status_code=500)
        state = secrets.token_urlsafe(24)
        request.session["oauth_state"] = state
        query = urlencode({
            "client_id": settings.discord_client_id,
            "redirect_uri": settings.discord_redirect_uri,
            "response_type": "code",
            "scope": "identify guilds",
            "prompt": "none",
            "state": state,
        })
        return RedirectResponse(f"https://discord.com/oauth2/authorize?{query}", status_code=302)

    @app.get("/oauth/callback")
    async def oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
        if error:
            return RedirectResponse(url="/", status_code=303)
        expected_state = request.session.get("oauth_state")
        if not code or not state or state != expected_state:
            return RedirectResponse(url="/", status_code=303)
        data = {
            "client_id": settings.discord_client_id,
            "client_secret": settings.discord_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.discord_redirect_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with httpx.AsyncClient(timeout=20) as client:
            token_resp = await client.post(f"{API_BASE}/oauth2/token", data=data, headers=headers)
            token_resp.raise_for_status()
            token_data = token_resp.json()
        request.session["access_token"] = token_data["access_token"]
        request.session["refresh_token"] = token_data.get("refresh_token")
        user, _ = await fetch_discord_identity(token_data["access_token"])
        request.session["discord_user"] = user
        request.session.pop("oauth_state", None)
        return RedirectResponse(url="/", status_code=303)

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse(url="/", status_code=303)

    @app.post("/guild/{guild_id}")
    async def update_guild(request: Request, guild_id: int, panel_channel_id: int = Form(0), music_channel_id: int = Form(0), level_channel_id: int = Form(0), dashboard_note: str = Form(""), level_enabled: int = Form(0)):
        if not logged_in(request):
            return RedirectResponse(url="/", status_code=303)
        ctx = await load_dashboard_context(request)
        allowed_ids = {guild["id"] for guild in ctx.get("guilds", [])}
        if guild_id not in allowed_ids:
            return HTMLResponse("Forbidden", status_code=403)
        await bot.db.update_guild_settings(guild_id, panel_channel_id=panel_channel_id, music_channel_id=music_channel_id, level_channel_id=level_channel_id, dashboard_note=dashboard_note, level_enabled=level_enabled)
        return RedirectResponse(url=f"/?guild={guild_id}", status_code=303)

    return app
