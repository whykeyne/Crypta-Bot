from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(slots=True)
class Settings:
    token: str = os.getenv("TOKEN") or os.getenv("DISCORD_TOKEN", "")
    guild_id: int = int(os.getenv("GUILD_ID", "0") or 0)
    default_panel_channel_id: int = int(os.getenv("DEFAULT_PANEL_CHANNEL_ID", "0") or 0)
    default_music_channel_id: int = int(os.getenv("DEFAULT_MUSIC_CHANNEL_ID", "0") or 0)
    default_level_channel_id: int = int(os.getenv("DEFAULT_LEVEL_CHANNEL_ID", "0") or 0)
    dashboard_host: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    dashboard_port: int = int(os.getenv("DASHBOARD_PORT", os.getenv("PORT", "8000")) or 8000)
    dashboard_public_url: str = os.getenv("DASHBOARD_PUBLIC_URL", "http://localhost:8000")
    dashboard_admin_key: str = os.getenv("DASHBOARD_ADMIN_KEY", "change_me_please")
    database_path: Path = Path(
        os.getenv(
            "DATABASE_PATH",
            "/app/data/crypta_bot.db" if (os.getenv("RAILWAY_PROJECT_ID") or os.getenv("RAILWAY_ENVIRONMENT_ID")) else "data/crypta_bot.db",
        )
    )
    cookie_file: str = os.getenv("COOKIE_FILE", "cookies.txt")
    ffmpeg_path: str = os.getenv("FFMPEG_PATH", "ffmpeg")
    default_volume: float = float(os.getenv("DEFAULT_VOLUME", "0.55") or 0.55)
    control_channel_name: str = os.getenv("CONTROL_CHANNEL_NAME", "voice-control")
    bot_prefix: str = os.getenv("BOT_PREFIX", "!")


settings = Settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
