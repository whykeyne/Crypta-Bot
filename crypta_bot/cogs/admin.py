from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import CryptaBot


class AdminCog(commands.Cog):
    def __init__(self, bot: CryptaBot) -> None:
        self.bot = bot

    @app_commands.command(name="setup_voice_panel", description="Задать текстовый канал для панели войсов")
    async def setup_voice_panel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администратор может это использовать.", ephemeral=True)
            return
        await self.bot.db.update_guild_settings(interaction.guild_id, panel_channel_id=channel.id)
        await interaction.response.send_message(f"Панель войсов теперь будет в {channel.mention}", ephemeral=True)

    @app_commands.command(name="setup_music_channel", description="Задать канал для музыкальной панели")
    async def setup_music_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администратор может это использовать.", ephemeral=True)
            return
        await self.bot.db.update_guild_settings(interaction.guild_id, music_channel_id=channel.id)
        await interaction.response.send_message(f"Музыкальная панель теперь будет в {channel.mention}", ephemeral=True)

    @app_commands.command(name="setup_level_channel", description="Задать канал для сообщений о level up")
    async def setup_level_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администратор может это использовать.", ephemeral=True)
            return
        await self.bot.db.update_guild_settings(interaction.guild_id, level_channel_id=channel.id)
        await interaction.response.send_message(f"Канал уровней теперь {channel.mention}", ephemeral=True)


async def setup(bot: CryptaBot) -> None:
    await bot.add_cog(AdminCog(bot))
