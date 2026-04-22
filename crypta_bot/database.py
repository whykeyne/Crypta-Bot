from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import aiosqlite

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    panel_channel_id INTEGER DEFAULT 0,
    music_channel_id INTEGER DEFAULT 0,
    level_channel_id INTEGER DEFAULT 0,
    dashboard_note TEXT DEFAULT '',
    level_enabled INTEGER DEFAULT 1,
    level_roles_json TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS voice_rooms (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER PRIMARY KEY,
    leader_id INTEGER NOT NULL,
    panel_message_id INTEGER DEFAULT 0,
    join_order_json TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS members (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    voice_xp INTEGER DEFAULT 0,
    voice_level INTEGER DEFAULT 0,
    total_voice_seconds INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
"""


def init_db() -> None:
    path = settings.database_path
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(query, params)
            await db.commit()

    async def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(query, params)
            row = await cur.fetchone()
            await cur.close()
            return row

    async def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(query, params)
            rows = await cur.fetchall()
            await cur.close()
            return rows

    async def ensure_guild(self, guild_id: int) -> None:
        await self.execute(
            """
            INSERT INTO guild_settings (guild_id, panel_channel_id, music_channel_id, level_channel_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id) DO NOTHING
            """,
            (
                guild_id,
                settings.default_panel_channel_id,
                settings.default_music_channel_id,
                settings.default_level_channel_id,
            ),
        )

    async def get_guild_settings(self, guild_id: int) -> dict[str, Any]:
        await self.ensure_guild(guild_id)
        row = await self.fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        if row is None:
            return {}
        data = dict(row)
        data["level_roles_json"] = json.loads(data.get("level_roles_json") or "[]")
        return data

    async def update_guild_settings(self, guild_id: int, **values: Any) -> None:
        await self.ensure_guild(guild_id)
        keys = []
        params: list[Any] = []
        for key, value in values.items():
            if key == "level_roles_json" and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            keys.append(f"{key} = ?")
            params.append(value)
        params.append(guild_id)
        await self.execute(f"UPDATE guild_settings SET {', '.join(keys)} WHERE guild_id = ?", tuple(params))

    async def save_room(self, guild_id: int, channel_id: int, leader_id: int, panel_message_id: int, join_order: list[int]) -> None:
        await self.execute(
            """
            INSERT INTO voice_rooms (guild_id, channel_id, leader_id, panel_message_id, join_order_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                guild_id=excluded.guild_id,
                leader_id=excluded.leader_id,
                panel_message_id=excluded.panel_message_id,
                join_order_json=excluded.join_order_json
            """,
            (guild_id, channel_id, leader_id, panel_message_id, json.dumps(join_order)),
        )

    async def delete_room(self, channel_id: int) -> None:
        await self.execute("DELETE FROM voice_rooms WHERE channel_id = ?", (channel_id,))

    async def get_rooms(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.fetchall("SELECT * FROM voice_rooms WHERE guild_id = ?", (guild_id,))
        items: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["join_order_json"] = json.loads(data.get("join_order_json") or "[]")
            items.append(data)
        return items

    async def ensure_member(self, guild_id: int, user_id: int) -> None:
        await self.execute(
            """
            INSERT INTO members (guild_id, user_id, voice_xp, voice_level, total_voice_seconds)
            VALUES (?, ?, 0, 0, 0)
            ON CONFLICT(guild_id, user_id) DO NOTHING
            """,
            (guild_id, user_id),
        )

    async def get_member(self, guild_id: int, user_id: int) -> dict[str, Any]:
        await self.ensure_member(guild_id, user_id)
        row = await self.fetchone("SELECT * FROM members WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        return dict(row) if row else {}

    async def update_member_progress(self, guild_id: int, user_id: int, voice_xp: int, voice_level: int, total_voice_seconds: int) -> None:
        await self.execute(
            """
            UPDATE members
            SET voice_xp = ?, voice_level = ?, total_voice_seconds = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (voice_xp, voice_level, total_voice_seconds, guild_id, user_id),
        )
