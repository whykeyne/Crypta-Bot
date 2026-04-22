from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Optional

import discord

from ..config import settings

try:
    import yt_dlp
except Exception:  # pragma: no cover
    yt_dlp = None


@dataclass(slots=True)
class Track:
    title: str
    stream_url: str
    webpage_url: str
    duration: int
    requester_id: int
    thumbnail: str | None = None
    source_name: str = "unknown"


class MusicState:
    def __init__(self, bot: discord.Client, guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.volume = settings.default_volume
        self.loop_enabled = False
        self.music_panel_channel_id = 0
        self.music_panel_message_id = 0
        self.voice_channel_id = 0
        self.lock = asyncio.Lock()

    def voice_client(self) -> discord.VoiceClient | None:
        guild = self.bot.get_guild(self.guild_id)
        return guild.voice_client if guild else None

    async def connect_to(self, channel: discord.VoiceChannel | discord.StageChannel) -> discord.VoiceClient:
        existing = self.voice_client()
        if existing and existing.is_connected():
            if existing.channel != channel:
                await existing.move_to(channel)
            self.voice_channel_id = channel.id
            return existing
        vc = await channel.connect()
        self.voice_channel_id = channel.id
        return vc

    async def enqueue(self, track: Track) -> None:
        self.queue.append(track)

    async def skip(self) -> bool:
        vc = self.voice_client()
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            return True
        return False

    async def stop(self) -> None:
        self.queue.clear()
        self.current = None
        vc = self.voice_client()
        if vc and vc.is_connected():
            vc.stop()
            await vc.disconnect(force=True)

    async def play_next(self, on_next: callable | None = None) -> None:
        async with self.lock:
            vc = self.voice_client()
            if not vc or not vc.is_connected():
                self.current = None
                return
            if self.loop_enabled and self.current:
                self.queue.appendleft(self.current)
            if not self.queue:
                self.current = None
                if on_next:
                    await on_next(self)
                return
            track = self.queue.popleft()
            self.current = track
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(
                    track.stream_url,
                    executable=settings.ffmpeg_path,
                    before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                ),
                volume=self.volume,
            )

            def after_play(error: Exception | None) -> None:
                if error:
                    print(f"Music error guild={self.guild_id}: {error}")
                asyncio.run_coroutine_threadsafe(self.play_next(on_next=on_next), self.bot.loop)

            vc.play(source, after=after_play)
            if on_next:
                await on_next(self)


def pick_best_audio(info: dict) -> str | None:
    formats = info.get("formats") or []
    audio_only = [f for f in formats if f.get("acodec") not in (None, "none")]
    direct = [f for f in audio_only if f.get("vcodec") in (None, "none") and f.get("url")]
    if direct:
        direct.sort(key=lambda f: (f.get("abr") or 0, f.get("asr") or 0), reverse=True)
        return direct[0].get("url")
    with_video = [f for f in audio_only if f.get("url")]
    if with_video:
        with_video.sort(key=lambda f: (f.get("abr") or 0, f.get("tbr") or 0), reverse=True)
        return with_video[0].get("url")
    return info.get("url")


def _ydl_opts(default_search: str) -> dict:
    opts = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "source_address": "0.0.0.0",
        "extract_flat": False,
        "default_search": default_search,
    }
    if settings.cookie_file:
        opts["cookiefile"] = settings.cookie_file
    return opts


def extract_track(query: str, requester_id: int) -> tuple[Track | None, str | None]:
    if yt_dlp is None:
        return None, "yt-dlp не установлен."

    attempts = [
        ("ytsearch1", "youtube"),
        ("scsearch1", "soundcloud"),
        ("auto", "generic"),
    ]
    if query.startswith("http://") or query.startswith("https://"):
        attempts = [("auto", "direct")]

    errors: list[str] = []
    for search_mode, source_name in attempts:
        try:
            with yt_dlp.YoutubeDL(_ydl_opts(search_mode)) as ydl:
                info = ydl.extract_info(query, download=False)
            if info and "entries" in info:
                info = next((entry for entry in info["entries"] if entry), None)
            if not info:
                errors.append(f"{source_name}: пустой ответ")
                continue
            stream_url = pick_best_audio(info)
            if not stream_url:
                errors.append(f"{source_name}: нет аудио потока")
                continue
            return Track(
                title=info.get("title") or "Unknown title",
                stream_url=stream_url,
                webpage_url=info.get("webpage_url") or info.get("original_url") or query,
                duration=int(info.get("duration") or 0),
                requester_id=requester_id,
                thumbnail=info.get("thumbnail"),
                source_name=source_name,
            ), None
        except Exception as exc:  # pragma: no cover
            errors.append(f"{source_name}: {exc}")
    return None, "Не удалось получить трек: " + " | ".join(errors[:3])
