from __future__ import annotations

from typing import Optional

import discord
from discord.ext import commands

from ..bot import CryptaBot, RoomState


async def safe_send(interaction: discord.Interaction, content: str, ephemeral: bool = True) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral)


def is_admin(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild or perms.move_members or perms.manage_channels


def format_member(member: discord.Member, leader_id: int) -> str:
    parts: list[str] = []
    if member.id == leader_id:
        parts.append("👑")
    if member.voice and member.voice.mute:
        parts.append("🔇")
    if member.voice and member.voice.deaf:
        parts.append("🎧")
    return (" ".join(parts) + " " if parts else "") + member.mention


class MemberSelect(discord.ui.Select):
    def __init__(self, bot: CryptaBot, room_id: int, action: str, actor_id: int) -> None:
        self.bot = bot
        self.room_id = room_id
        self.action = action
        self.actor_id = actor_id
        channel = self.bot.get_channel(room_id)
        opts: list[discord.SelectOption] = []
        if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            for member in channel.members:
                if member.bot or member.id == actor_id:
                    continue
                opts.append(discord.SelectOption(label=member.display_name[:100], value=str(member.id), emoji="👤"))
        super().__init__(placeholder="Выбери участника", options=opts or [discord.SelectOption(label="Нет доступных", value="0")], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        channel = self.bot.get_channel(self.room_id)
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            await safe_send(interaction, "Комната уже недоступна.")
            return
        if not await ensure_rights(self.bot, interaction, channel):
            return
        target = discord.utils.get(channel.members, id=int(self.values[0]))
        if target is None:
            await safe_send(interaction, "Участник уже вышел.")
            return
        state = await get_or_create_room(self.bot, channel)
        try:
            if self.action == "leader":
                state.leader_id = target.id
                await persist_room(self.bot, state)
                await sync_room_panel(self.bot, channel, force_repost=True)
                await safe_send(interaction, f"👑 Новый лидер: {target.mention}")
            elif self.action == "kick":
                await target.move_to(None, reason=f"Voice kick by {interaction.user}")
                await sync_room_panel(self.bot, channel)
                await safe_send(interaction, f"🚪 {target.mention} отключён от войса")
            elif self.action == "mute":
                await target.edit(mute=True, reason=f"Voice mute by {interaction.user}")
                await sync_room_panel(self.bot, channel)
                await safe_send(interaction, f"🔇 {target.mention} замучен")
            elif self.action == "unmute":
                await target.edit(mute=False, reason=f"Voice unmute by {interaction.user}")
                await sync_room_panel(self.bot, channel)
                await safe_send(interaction, f"🔊 {target.mention} размучен")
            elif self.action == "deafen":
                await target.edit(deafen=True, reason=f"Voice deafen by {interaction.user}")
                await sync_room_panel(self.bot, channel)
                await safe_send(interaction, f"🎧 {target.mention} заглушён")
            elif self.action == "undeafen":
                await target.edit(deafen=False, reason=f"Voice undeafen by {interaction.user}")
                await sync_room_panel(self.bot, channel)
                await safe_send(interaction, f"🎶 {target.mention} звук возвращён")
        except discord.Forbidden:
            await safe_send(interaction, "Боту не хватает прав.")


class MemberActionView(discord.ui.View):
    def __init__(self, bot: CryptaBot, room_id: int, action: str, actor_id: int) -> None:
        super().__init__(timeout=60)
        self.add_item(MemberSelect(bot, room_id, action, actor_id))

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        await safe_send(interaction, f"Ошибка взаимодействия: {error}")


class LimitModal(discord.ui.Modal, title="Лимит комнаты"):
    limit = discord.ui.TextInput(label="Лимит 0-99", default="0", required=True, max_length=2)

    def __init__(self, bot: CryptaBot, room_id: int, current_limit: int) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.room_id = room_id
        self.limit.default = str(current_limit)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        channel = self.bot.get_channel(self.room_id)
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            await safe_send(interaction, "Комната уже недоступна.")
            return
        if not await ensure_rights(self.bot, interaction, channel):
            return
        try:
            value = max(0, min(99, int(str(self.limit))))
        except ValueError:
            await safe_send(interaction, "Нужно ввести число.")
            return
        await channel.edit(user_limit=value, reason=f"Limit by {interaction.user}")
        await sync_room_panel(self.bot, channel)
        await safe_send(interaction, f"🎚️ Лимит установлен: {value}")


class VoicePanelView(discord.ui.View):
    def __init__(self, bot: CryptaBot, room_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.room_id = room_id

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        await safe_send(interaction, f"Ошибка взаимодействия: {error}")

    def _channel(self) -> discord.VoiceChannel | discord.StageChannel | None:
        channel = self.bot.get_channel(self.room_id)
        return channel if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)) else None

    @discord.ui.button(label="Лидер", emoji="👑", style=discord.ButtonStyle.primary, row=0)
    async def leader(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel = self._channel()
        if not channel or not await ensure_rights(self.bot, interaction, channel):
            return
        await interaction.response.send_message("Выбери нового лидера:", ephemeral=True, view=MemberActionView(self.bot, channel.id, "leader", interaction.user.id))

    @discord.ui.button(label="Состав", emoji="👥", style=discord.ButtonStyle.secondary, row=0)
    async def members(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel = self._channel()
        if not channel:
            await safe_send(interaction, "Комната уже недоступна.")
            return
        lines = [m.mention for m in channel.members if not m.bot]
        await safe_send(interaction, "\n".join(lines) or "Пусто")

    @discord.ui.button(label="Онлайн", emoji="📶", style=discord.ButtonStyle.secondary, row=0)
    async def online(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel = self._channel()
        if not channel:
            await safe_send(interaction, "Комната уже недоступна.")
            return
        await safe_send(interaction, f"Сейчас в комнате: {len([m for m in channel.members if not m.bot])}")

    @discord.ui.button(label="Доступ", emoji="🔐", style=discord.ButtonStyle.secondary, row=0)
    async def access(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel = self._channel()
        if not channel or not await ensure_rights(self.bot, interaction, channel):
            return
        overwrite = channel.overwrites_for(channel.guild.default_role)
        locked = overwrite.connect is False
        overwrite.connect = None if locked else False
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrite)
        await sync_room_panel(self.bot, channel)
        await safe_send(interaction, "🔓 Комната открыта" if locked else "🔒 Комната закрыта")

    @discord.ui.button(label="Лимит", emoji="🎚️", style=discord.ButtonStyle.secondary, row=1)
    async def limit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel = self._channel()
        if not channel or not await ensure_rights(self.bot, interaction, channel):
            return
        await interaction.response.send_modal(LimitModal(self.bot, channel.id, channel.user_limit))

    @discord.ui.button(label="Кик", emoji="🚪", style=discord.ButtonStyle.danger, row=1)
    async def kick(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel = self._channel()
        if not channel or not await ensure_rights(self.bot, interaction, channel):
            return
        await interaction.response.send_message("Кого кикнуть?", ephemeral=True, view=MemberActionView(self.bot, channel.id, "kick", interaction.user.id))

    @discord.ui.button(label="Мут", emoji="🔇", style=discord.ButtonStyle.secondary, row=1)
    async def mute(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel = self._channel()
        if not channel or not await ensure_rights(self.bot, interaction, channel):
            return
        await interaction.response.send_message("Кого замутить?", ephemeral=True, view=MemberActionView(self.bot, channel.id, "mute", interaction.user.id))

    @discord.ui.button(label="Звук", emoji="🔊", style=discord.ButtonStyle.success, row=1)
    async def sound(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel = self._channel()
        if not channel or not await ensure_rights(self.bot, interaction, channel):
            return
        await interaction.response.send_message("Что сделать?", ephemeral=True, view=MemberActionView(self.bot, channel.id, "undeafen", interaction.user.id))

    @discord.ui.button(label="Музыка", emoji="🎵", style=discord.ButtonStyle.success, row=2)
    async def music(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel = self._channel()
        if not channel or not await ensure_rights(self.bot, interaction, channel):
            return
        music_cog = self.bot.get_cog("MusicCog")
        if music_cog is None:
            await safe_send(interaction, "Музыкальный модуль ещё не загружен.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await music_cog.open_music_from_voice_panel(interaction, channel)  # type: ignore[attr-defined]

    @discord.ui.button(label="Обновить", emoji="✨", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        channel = self._channel()
        if not channel:
            await safe_send(interaction, "Комната уже недоступна.")
            return
        await sync_room_panel(self.bot, channel)
        await safe_send(interaction, "Панель обновлена")


def build_room_embed(bot: CryptaBot, channel: discord.VoiceChannel | discord.StageChannel, state: RoomState) -> discord.Embed:
    guild = channel.guild
    humans = [m for m in channel.members if not m.bot]
    leader = guild.get_member(state.leader_id)
    leader_text = leader.mention if leader else f"<@{state.leader_id}>"
    member_lines = "\n".join(format_member(m, state.leader_id) for m in humans) or "Пусто"
    overwrite = channel.overwrites_for(guild.default_role)
    locked = overwrite.connect is False
    embed = discord.Embed(title="✦ CRYPTA VOICE SUITE", color=0x181C34)
    embed.description = (
        f"> **Комната:** {channel.mention}\n"
        f"> **Лидер:** {leader_text}\n"
        f"> **Статус:** `{'Закрыта' if locked else 'Открыта'}`\n"
        "> **Музыка:** кнопка снизу подключает бота и открывает отдельную панель"
    )
    embed.add_field(name="Состояние", value=f"Участников: `{len(humans)}`\nЛимит: `{channel.user_limit or '∞'}`", inline=True)
    embed.add_field(name="Кнопки", value="Войс контроль + музыка + уровни", inline=True)
    embed.add_field(name="Участники", value=member_lines[:1024], inline=False)
    embed.set_footer(text=f"room:{channel.id}")
    return embed


async def get_or_create_room(bot: CryptaBot, channel: discord.VoiceChannel | discord.StageChannel) -> RoomState:
    humans = [m for m in channel.members if not m.bot]
    state = bot.room_states.get(channel.id)
    if state is None:
        state = RoomState(guild_id=channel.guild.id, channel_id=channel.id, leader_id=humans[0].id if humans else 0, join_order=[m.id for m in humans])
        bot.room_states[channel.id] = state
    else:
        for member in humans:
            state.add_member(member.id)
        if state.leader_id not in [m.id for m in humans] and humans:
            state.leader_id = state.pick_next_leader([m.id for m in humans]) or humans[0].id
    return state


async def persist_room(bot: CryptaBot, state: RoomState) -> None:
    await bot.db.save_room(state.guild_id, state.channel_id, state.leader_id, state.panel_message_id, state.join_order)


async def get_panel_channel(bot: CryptaBot, guild: discord.Guild) -> discord.TextChannel | None:
    cfg = await bot.db.get_guild_settings(guild.id)
    channel = guild.get_channel(cfg.get("panel_channel_id") or 0)
    if isinstance(channel, discord.TextChannel):
        return channel
    found = discord.utils.get(guild.text_channels, name="voice-control")
    return found if isinstance(found, discord.TextChannel) else None


async def sync_room_panel(bot: CryptaBot, channel: discord.VoiceChannel | discord.StageChannel, force_repost: bool = False) -> None:
    humans = [m for m in channel.members if not m.bot]
    if not humans:
        state = bot.room_states.pop(channel.id, None)
        if state:
            panel_channel = await get_panel_channel(bot, channel.guild)
            if panel_channel and state.panel_message_id:
                try:
                    msg = await panel_channel.fetch_message(state.panel_message_id)
                    await msg.delete()
                except Exception:
                    pass
            await bot.db.delete_room(channel.id)
        return
    state = await get_or_create_room(bot, channel)
    panel_channel = await get_panel_channel(bot, channel.guild)
    if panel_channel is None:
        return
    message = None
    if state.panel_message_id:
        try:
            message = await panel_channel.fetch_message(state.panel_message_id)
        except Exception:
            message = None
    embed = build_room_embed(bot, channel, state)
    view = VoicePanelView(bot, channel.id)
    if message and not force_repost:
        await message.edit(embed=embed, view=view)
    else:
        if message:
            try:
                await message.delete()
            except Exception:
                pass
        msg = await panel_channel.send(embed=embed, view=view)
        state.panel_message_id = msg.id
    await persist_room(bot, state)


async def ensure_rights(bot: CryptaBot, interaction: discord.Interaction, channel: discord.VoiceChannel | discord.StageChannel) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        await safe_send(interaction, "Это доступно только на сервере.")
        return False
    if not user.voice or user.voice.channel != channel:
        await safe_send(interaction, "Нужно быть именно в этом войсе.")
        return False
    if is_admin(user):
        return True
    state = await get_or_create_room(bot, channel)
    if state.leader_id == user.id:
        return True
    await safe_send(interaction, "У тебя нет прав на управление этой комнатой.")
    return False


class VoicePanelCog(commands.Cog):
    def __init__(self, bot: CryptaBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot:
            return
        if before.channel and before.channel != after.channel:
            state = self.bot.room_states.get(before.channel.id)
            if state:
                state.remove_member(member.id)
            await sync_room_panel(self.bot, before.channel)
        if after.channel and before.channel != after.channel:
            state = await get_or_create_room(self.bot, after.channel)
            old_leader = state.leader_id
            state.add_member(member.id)
            humans = [m for m in after.channel.members if not m.bot]
            if len(humans) == 1:
                state.leader_id = member.id
            await persist_room(self.bot, state)
            await sync_room_panel(self.bot, after.channel, force_repost=(old_leader != state.leader_id))


async def setup(bot: CryptaBot) -> None:
    await bot.add_cog(VoicePanelCog(bot))
