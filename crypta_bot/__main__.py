from __future__ import annotations

from .bot import bot
from .config import settings
from .database import init_db


def main() -> None:
    init_db()
    if not settings.token:
        raise RuntimeError("Не найден TOKEN или DISCORD_TOKEN в .env")
    bot.run(settings.token)


if __name__ == "__main__":
    main()
