from __future__ import annotations

import random

import discord
from discord.ext import commands

from ..bot import CryptaBot
from ..services.music_service import MusicState, extract_track
from .voice_panel import safe_send


def queue_preview(state: MusicState, limit: int = 6) -> str:
    if not state.queue:
        return "Очередь пуста"
    lines = []
    for idx, track in enumerate(list(state.queue)[:limit], start=1):
        lines.append(f"`{idx}.` {track.title}")
    if len(state.queue) > limit:
        lines.append(f"… и ещё {len(state.queue) - limit}")
    return "\n".join(lines)


class AddTrackModal(discord.ui.Modal, title="Добавить трек"):
    query = discord.ui.TextInput(label="Название трека или ссылка", placeholder="Например: Drake Gods Plan", required=True, max_length=300)

    def __init__(self, cog: "MusicCog", guild_id: int) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.cog.ensure_music_control(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        state = self.cog.state_for(self.guild_id)
        track, error = await self.cog.bot.loop.run_in_executor(None, extract_track, str(self.query).strip(), interaction.user.id)
        if error or not track:
            await interaction.followup.send(error or "Не удалось загрузить трек.", ephemeral=True)
            return
        await state.enqueue(track)
        vc = state.voice_client()
        if vc and not vc.is_playing() and not vc.is_paused() and state.current is None:
            await state.play_next(on_next=self.cog.update_music_panel)
        await self.cog.update_music_panel(state)
        await interaction.followup.send(f"🎵 Добавлено: **{track.title}**", ephemeral=True)


class MusicPanelView(discord.ui.View):
    def __init__(self, cog: "MusicCog", guild_id: int) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        await safe_send(interaction, f"Ошибка взаимодействия: {error}")

    @discord.ui.button(label="Добавить", emoji="🎵", style=discord.ButtonStyle.primary, row=0)
    async def add(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.cog.ensure_music_control(interaction):
            return
        await interaction.response.send_modal(AddTrackModal(self.cog, self.guild_id))

    @discord.ui.button(label="Пауза", emoji="⏯️", style=discord.ButtonStyle.secondary, row=0)
    async def pause(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.cog.ensure_music_control(interaction):
            return
        state = self.cog.state_for(self.guild_id)
        vc = state.voice_client()
        if vc and vc.is_playing():
            vc.pause()
            msg = "⏸️ Музыка поставлена на паузу"
        elif vc and vc.is_paused():
            vc.resume()
            msg = "▶️ Музыка продолжена"
        else:
            msg = "Сейчас ничего не играет"
        await self.cog.update_music_panel(state)
        await safe_send(interaction, msg)

    @discord.ui.button(label="Скип", emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.cog.ensure_music_control(interaction):
            return
        state = self.cog.state_for(self.guild_id)
        ok = await state.skip()
        await self.cog.update_music_panel(state)
        await safe_send(interaction, "⏭️ Трек пропущен" if ok else "Сейчас ничего не играет")

    @discord.ui.button(label="Стоп", emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.cog.ensure_music_control(interaction):
            return
        state = self.cog.state_for(self.guild_id)
        await state.stop()
        await self.cog.update_music_panel(state)
        await safe_send(interaction, "⏹️ Музыка остановлена")

    @discord.ui.button(label="Очередь", emoji="📜", style=discord.ButtonStyle.secondary, row=1)
    async def queue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.cog.state_for(self.guild_id)
        await safe_send(interaction, queue_preview(state))

    @discord.ui.button(label="Loop", emoji="🔁", style=discord.ButtonStyle.success, row=1)
    async def loop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.cog.ensure_music_control(interaction):
            return
        state = self.cog.state_for(self.guild_id)
        state.loop_enabled = not state.loop_enabled
        await self.cog.update_music_panel(state)
        await safe_send(interaction, f"Loop: {'включён' if state.loop_enabled else 'выключен'}")

    @discord.ui.button(label="Shuffle", emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.cog.ensure_music_control(interaction):
            return
        state = self.cog.state_for(self.guild_id)
        items = list(state.queue)
        random.shuffle(items)
        state.queue.clear()
        state.queue.extend(items)
        await self.cog.update_music_panel(state)
        await safe_send(interaction, "🔀 Очередь перемешана")

    @discord.ui.button(label="Clear", emoji="🧹", style=discord.ButtonStyle.secondary, row=1)
    async def clear(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.cog.ensure_music_control(interaction):
            return
        state = self.cog.state_for(self.guild_id)
        state.queue.clear()
        await self.cog.update_music_panel(state)
        await safe_send(interaction, "🧹 Очередь очищена")


class MusicCog(commands.Cog):
    def __init__(self, bot: CryptaBot) -> None:
        self.bot = bot

    def state_for(self, guild_id: int) -> MusicState:
        state = self.bot.music_states.get(guild_id)
        if not isinstance(state, MusicState):
            state = MusicState(self.bot, guild_id)
            self.bot.music_states[guild_id] = state
        return state

    async def get_music_text_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cfg = await self.bot.db.get_guild_settings(guild.id)
        channel = guild.get_channel(cfg.get("music_channel_id") or 0)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def ensure_music_control(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await safe_send(interaction, "Это доступно только на сервере.")
            return False
        state = self.state_for(interaction.guild.id)
        if not state.voice_channel_id:
            await safe_send(interaction, "Музыка ещё не привязана к войсу.")
            return False
        voice = interaction.user.voice
        if not voice or voice.channel is None or voice.channel.id != state.voice_channel_id:
            await safe_send(interaction, "Управлять музыкой могут только участники того войса, где играет бот.")
            return False
        return True

    async def build_music_embed(self, state: MusicState) -> discord.Embed:
        guild = self.bot.get_guild(state.guild_id)
        current = state.current.title if state.current else "Ничего не играет"
        embed = discord.Embed(title="✦ CRYPTA MUSIC PANEL", color=0x131C39)
        embed.description = f"> **Сейчас:** {current}\n> **Очередь:** `{len(state.queue)}`\n> **Loop:** `{'On' if state.loop_enabled else 'Off'}`\n> **Громкость:** `{int(state.volume * 100)}%`"
        embed.add_field(name="Очередь", value=queue_preview(state), inline=False)
        if guild and guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        return embed

    async def update_music_panel(self, state: MusicState) -> None:
        guild = self.bot.get_guild(state.guild_id)
        if guild is None:
            return
        channel = await self.get_music_text_channel(guild)
        if channel is None:
            return
        embed = await self.build_music_embed(state)
        view = MusicPanelView(self, state.guild_id)
        if state.music_panel_message_id:
            try:
                msg = await channel.fetch_message(state.music_panel_message_id)
                await msg.edit(embed=embed, view=view)
                return
            except Exception:
                pass
        msg = await channel.send(embed=embed, view=view)
        state.music_panel_message_id = msg.id
        state.music_panel_channel_id = channel.id

    async def open_music_from_voice_panel(self, interaction: discord.Interaction, voice_channel: discord.VoiceChannel | discord.StageChannel) -> None:
        state = self.state_for(interaction.guild_id)
        try:
            await state.connect_to(voice_channel)
        except Exception as exc:
            await interaction.followup.send(f"Ошибка подключения к войсу: {exc}", ephemeral=True)
            return
        await self.update_music_panel(state)
        await interaction.followup.send("🎵 Бот подключился. Музыкальная панель отправлена в выбранный канал.", ephemeral=True)

    @commands.command(name="play")
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            await ctx.reply("Сначала зайди в голосовой канал.")
            return
        state = self.state_for(ctx.guild.id)
        await state.connect_to(ctx.author.voice.channel)
        track, error = await self.bot.loop.run_in_executor(None, extract_track, query, ctx.author.id)
        if error or not track:
            await ctx.reply(error or "Не удалось найти трек.")
            return
        await state.enqueue(track)
        if state.current is None and state.voice_client() and not state.voice_client().is_playing():
            await state.play_next(on_next=self.update_music_panel)
        await self.update_music_panel(state)
        await ctx.reply(f"🎵 Добавлено: **{track.title}**")

    @commands.command(name="queue")
    async def queue_cmd(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.state_for(ctx.guild.id)
        await ctx.reply(queue_preview(state))

    @commands.command(name="remove")
    async def remove_cmd(self, ctx: commands.Context, index: int) -> None:
        if not ctx.guild:
            return
        state = self.state_for(ctx.guild.id)
        items = list(state.queue)
        if not 1 <= index <= len(items):
            await ctx.reply("Такого номера нет в очереди.")
            return
        removed = items.pop(index - 1)
        state.queue.clear()
        state.queue.extend(items)
        await self.update_music_panel(state)
        await ctx.reply(f"Удалено: **{removed.title}**")

    @commands.command(name="nowplaying")
    async def nowplaying(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.state_for(ctx.guild.id)
        await ctx.reply(state.current.title if state.current else "Сейчас ничего не играет")


async def setup(bot: CryptaBot) -> None:
    await bot.add_cog(MusicCog(bot))
