from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from index import AutoShardedBot
    from utils.context import GuildContext

log = logging.getLogger(__name__)

UPDATES_CHANNEL = 991443053258743962


class Config(commands.Cog, command_attrs=dict(extras={"permissions": ["manage_guild"]})):
    def __init__(self, bot: AutoShardedBot):
        self.bot: AutoShardedBot = bot

    def __repr__(self) -> str:
        return f"<cogs.{self.__cog_name__}>"

    async def cog_check(self, ctx: GuildContext) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage("This command can only be used within a guild")

        if await ctx.bot.is_owner(ctx.author):
            return True

        if not ctx.author.guild_permissions.manage_guild:
            raise commands.MissingPermissions(["manage_guild"])
        return True

    @commands.command(name="prefix", extras={"examples": ["?", "gt!"]}, help="Sets the prefix for Fridays commands")
    async def prefix(self, ctx: GuildContext, new_prefix: str = None):
        if new_prefix is None:
            return await ctx.send(f"Current prefix: `{self.bot.prefixes[ctx.guild.id]}`")
        prefix = new_prefix.lower()
        if len(prefix) > 5:
            return await ctx.reply("Can't set a prefix with more than 5 characters")
        await self.bot.prefixes.put(ctx.guild.id, prefix)
        await ctx.reply(f"My new prefix is `{prefix}`")

    @commands.command("updates", help="Recieve updates on new features and changes for Friday")
    @commands.has_permissions(manage_webhooks=True)
    @commands.bot_has_permissions(manage_webhooks=True)
    async def updates(self, ctx: GuildContext, channel: discord.TextChannel):
        updates_channel: discord.TextChannel = self.bot.get_channel(UPDATES_CHANNEL)  # type: ignore

        if updates_channel.id in [w.source_channel and w.source_channel.id for w in await channel.webhooks()]:
            confirm = await ctx.prompt("This channel is already subscribed to updates. Are you sure you want to subscribe again?")
            if not confirm:
                return await ctx.reply("Cancelled")

        await updates_channel.follow(destination=channel, reason="Called updates command, for Friday updates")
        await ctx.reply("Updates channel followed")


async def setup(bot: AutoShardedBot):
    await bot.add_cog(Config(bot))
