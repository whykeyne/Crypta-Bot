from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from ..bot import CryptaBot


def xp_needed_for_next(level: int) -> int:
    return 8 + level * 4


def level_from_xp(total_xp: int) -> tuple[int, int]:
    level = 0
    remaining = total_xp
    while remaining >= xp_needed_for_next(level):
        remaining -= xp_needed_for_next(level)
        level += 1
    return level, remaining


class LevelsCog(commands.Cog):
    def __init__(self, bot: CryptaBot) -> None:
        self.bot = bot
        self.voice_xp_task.start()

    def cog_unload(self) -> None:
        self.voice_xp_task.cancel()

    @tasks.loop(minutes=1)
    async def voice_xp_task(self) -> None:
        now = datetime.now(timezone.utc)
        for guild in self.bot.guilds:
            cfg = await self.bot.db.get_guild_settings(guild.id)
            if not cfg.get("level_enabled", 1):
                continue
            for channel in guild.voice_channels:
                humans = [m for m in channel.members if not m.bot]
                if not humans:
                    continue
                for member in humans:
                    key = (guild.id, member.id)
                    self.bot.voice_sessions.setdefault(key, now)
                    profile = await self.bot.db.get_member(guild.id, member.id)
                    total_xp = int(profile.get("voice_xp", 0)) + 12
                    total_seconds = int(profile.get("total_voice_seconds", 0)) + 60
                    old_level = int(profile.get("voice_level", 0))
                    new_level, _ = level_from_xp(total_xp)
                    await self.bot.db.update_member_progress(guild.id, member.id, total_xp, new_level, total_seconds)
                    if new_level > old_level:
                        await self.on_level_up(guild, member, new_level, cfg.get("level_channel_id") or 0)

    @voice_xp_task.before_loop
    async def before_xp(self) -> None:
        await self.bot.wait_until_ready()

    async def on_level_up(self, guild: discord.Guild, member: discord.Member, level: int, channel_id: int) -> None:
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        embed = discord.Embed(title="Voice Level Up", description=f"{member.mention} получил **{level} уровень** за активность в войсе.", color=0x6D5EF9)
        embed.add_field(name="Следующий рост", value=f"Для следующего уровня нужно ещё `{xp_needed_for_next(level)}` XP на текущей шкале.")
        await channel.send(embed=embed)

    @commands.command(name="voicelevel")
    async def voicelevel(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        if not ctx.guild:
            return
        member = member or ctx.author
        data = await self.bot.db.get_member(ctx.guild.id, member.id)
        embed = discord.Embed(title="Voice Profile", color=0x6D5EF9)
        embed.description = f"{member.mention}\nУровень: **{data.get('voice_level', 0)}**\nXP: **{data.get('voice_xp', 0)}**\nВремя в войсе: **{data.get('total_voice_seconds', 0) // 60} мин**"
        await ctx.reply(embed=embed)


async def setup(bot: CryptaBot) -> None:
    await bot.add_cog(LevelsCog(bot))
