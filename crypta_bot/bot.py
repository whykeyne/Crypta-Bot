from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

from .config import settings
from .database import Database
from .web.app import create_dashboard

log = logging.getLogger("crypta_bot")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s")


@dataclass(slots=True)
class RoomState:
    guild_id: int
    channel_id: int
    leader_id: int
    panel_message_id: int = 0
    join_order: list[int] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def add_member(self, member_id: int) -> None:
        if member_id in self.join_order:
            self.join_order.remove(member_id)
        self.join_order.append(member_id)

    def remove_member(self, member_id: int) -> None:
        if member_id in self.join_order:
            self.join_order.remove(member_id)

    def pick_next_leader(self, present_ids: list[int]) -> Optional[int]:
        for member_id in self.join_order:
            if member_id in present_ids:
                return member_id
        return present_ids[0] if present_ids else None


class CryptaBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.voice_states = True
        intents.message_content = True
        super().__init__(command_prefix=settings.bot_prefix, intents=intents, help_command=None)
        self.db = Database(settings.database_path)
        self.room_states: dict[int, RoomState] = {}
        self.music_states: dict[int, object] = {}
        self.voice_sessions: dict[tuple[int, int], datetime] = {}
        self.dashboard_server = None

    async def setup_hook(self) -> None:
        for ext in [
            "crypta_bot.cogs.voice_panel",
            "crypta_bot.cogs.music",
            "crypta_bot.cogs.levels",
            "crypta_bot.cogs.admin",
        ]:
            await self.load_extension(ext)
        app = create_dashboard(self)
        config = __import__("uvicorn").Config(app, host=settings.dashboard_host, port=settings.dashboard_port, log_level="warning")
        self.dashboard_server = __import__("uvicorn").Server(config)
        self.loop.create_task(self.dashboard_server.serve())
        if settings.guild_id:
            guild = discord.Object(id=settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")
        for guild in self.guilds:
            await self.db.ensure_guild(guild.id)
            rows = await self.db.get_rooms(guild.id)
            for row in rows:
                self.room_states[row["channel_id"]] = RoomState(
                    guild_id=guild.id,
                    channel_id=row["channel_id"],
                    leader_id=row["leader_id"],
                    panel_message_id=row["panel_message_id"],
                    join_order=row["join_order_json"],
                )


bot = CryptaBot()
