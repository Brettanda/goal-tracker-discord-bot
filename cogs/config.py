from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import discord
import pytz
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from index import AutoShardedBot
    from utils.context import Context, GuildContext

log = logging.getLogger(__name__)

UPDATES_CHANNEL = 991443053258743962


class Timezone(commands.Converter, app_commands.Transformer):
    async def convert(self, ctx: Context | GuildContext, argument: str) -> pytz.BaseTzInfo:
        try:
            return pytz.timezone(argument)
        except pytz.exceptions.UnknownTimeZoneError:
            raise commands.BadArgument(f"Unknown timezone: {argument}")

    @classmethod
    async def transform(cls, interaction: discord.Interaction, value: str) -> pytz.BaseTzInfo:
        try:
            return pytz.timezone(value)
        except pytz.exceptions.UnknownTimeZoneError:
            raise commands.BadArgument(f"Unknown timezone: {value}")

    @classmethod
    async def autocomplete(cls, interaction: discord.Interaction, value: str) -> list[app_commands.Choice[str]]:
        timezones = pytz.all_timezones
        return [app_commands.Choice(name=timezone, value=timezone) for timezone in timezones if timezone.lower().startswith(value.lower())][:25]


class Config(commands.Cog, command_attrs=dict(extras={"permissions": ["manage_guild"]})):
    def __init__(self, bot: AutoShardedBot):
        self.bot: AutoShardedBot = bot

    def __repr__(self) -> str:
        return f"<cogs.{self.__cog_name__}>"

    async def cog_check(self, ctx: Context | GuildContext) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True

        if ctx.guild is not None and not ctx.author.guild_permissions.manage_guild:  # type: ignore
            raise commands.MissingPermissions(["manage_guild"])
        return True

    @commands.command(name="prefix", extras={"examples": ["?", "gt!"]})
    @commands.has_guild_permissions(manage_guild=True)
    async def prefix(self, ctx: GuildContext, new_prefix: str = None):
        """Sets the prefix for Goal Trackers text commands"""
        if new_prefix is None:
            return await ctx.send(f"Current prefix: `{self.bot.prefixes[ctx.guild.id]}`")
        prefix = new_prefix.lower()
        if len(prefix) > 5:
            return await ctx.send("Can't set a prefix with more than 5 characters")
        await self.bot.prefixes.put(ctx.guild.id, prefix)
        await ctx.send(f"My new prefix is `{prefix}`")

    @commands.hybrid_command(name="usertimezone")
    async def timezone_user(self, ctx: Context, timezone: app_commands.Transform[Optional[pytz.BaseTzInfo], Timezone] = None):
        """Sets the timezone for a specific user."""
        if timezone is None:
            return await ctx.send(f"Current timezone: `{ctx.timezone}`")
        now = ctx.message.created_at.astimezone(timezone).strftime("%I:%M:%S %p")
        await self.bot.timezones.put(ctx.author.id, str(timezone))
        await ctx.send(f"Setting timezone to `{timezone}` where it is currently `{now}`", ephemeral=True)

    @commands.hybrid_command(name="servertimezone", aliases=["guildtimezone"], default_member_permissions=discord.Permissions(manage_guild=True))
    @commands.has_guild_permissions(manage_guild=True)
    async def timezone_guild(self, ctx: GuildContext, timezone: app_commands.Transform[Optional[pytz.BaseTzInfo], Timezone] = None):
        """Sets the default timezone for the server"""
        if timezone is None:
            return await ctx.send(f"Current timezone: `{ctx.timezone}`")
        now = ctx.message.created_at.astimezone(timezone).strftime("%I:%M:%S %p")
        await self.bot.timezones.put(ctx.guild.id, str(timezone))
        await ctx.send(f"Setting timezone to `{timezone}` where it is currently `{now}`", ephemeral=True)

    @commands.hybrid_command("updates")
    @commands.has_permissions(manage_webhooks=True)
    @commands.bot_has_permissions(manage_webhooks=True)
    @commands.has_guild_permissions(manage_guild=True)
    async def updates(self, ctx: GuildContext, channel: discord.TextChannel):
        """Recieve updates on new features and changes for Goal Tracker"""
        updates_channel: discord.TextChannel = self.bot.get_channel(UPDATES_CHANNEL)  # type: ignore

        if updates_channel.id in [w.source_channel and w.source_channel.id for w in await channel.webhooks()]:
            confirm = await ctx.prompt("This channel is already subscribed to updates. Are you sure you want to subscribe again?")
            if not confirm:
                return await ctx.send("Cancelled")

        await updates_channel.follow(destination=channel, reason="Called updates command, for Friday updates")
        await ctx.send("Updates channel followed")


async def setup(bot: AutoShardedBot):
    await bot.add_cog(Config(bot))
