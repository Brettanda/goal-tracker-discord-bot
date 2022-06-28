from __future__ import annotations

import asyncio
import datetime
import logging
import sys
import traceback
from typing import TYPE_CHECKING, Any, Optional

import aiohttp
import discord
from discord.ext import commands

import cogs
import config
from utils.config import Config
from utils.logging import setup_logging
from utils.time import human_timedelta

if TYPE_CHECKING:
    from utils.context import Context


log = logging.getLogger(__name__)


def get_prefix(bot: AutoShardedBot, message: discord.Message):
    if message.guild is not None:
        return commands.when_mentioned_or(bot.prefixes.get(message.guild.id, "?"))(bot, message)
    return commands.when_mentioned_or("?")(bot, message)


class AutoShardedBot(commands.AutoShardedBot):
    """Friday is a discord bot that is designed to be a flexible and easy to use bot."""

    user: discord.ClientUser
    uptime: datetime.datetime

    def __init__(self, **kwargs):
        super().__init__(
            command_prefix=get_prefix,
            strip_after_prefix=True,
            case_insensitive=True,
            intents=discord.Intents(
                guilds=True,
                messages=True,
                message_content=True
            ),
            chunk_guilds_at_startup=False,
            **kwargs
        )

        self.ready = False

        log.info(
            f"Cluster Starting {kwargs.get('shard_ids', None)}, {kwargs.get('shard_count', 1)}")

    def __repr__(self) -> str:
        return f"<Friday username=\"{self.user.display_name if self.user else None}\" id={self.user.id if self.user else None}>"

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession()

        self.bot_app_info = await self.application_info()
        self.owner_id = self.bot_app_info.team and self.bot_app_info.team.owner_id or self.bot_app_info.owner.id

        self.prefixes: Config[str] = Config("prefixes.json", loop=self.loop)

        for cog in cogs.default:
            path = "cogs."
            try:
                await self.load_extension(f"{path}{cog}")
            except Exception as e:
                log.error(f"Failed to load extenstion {cog} with \n {e}")

    @property
    def owner(self) -> discord.User:
        return self.bot_app_info.owner

    async def on_command_error(self, ctx: Context, error: commands.CommandError) -> None:
        if hasattr(ctx.command, 'on_error'):
            return

        # if ctx.cog:
        #   if ctx.cog._get_overridden_method(ctx.cog.cog_command_error) is not None:
        #     return

        # ignored = (commands.CommandNotFound, commands.NotOwner, )
        just_send = (commands.DisabledCommand, commands.MissingPermissions, commands.RoleNotFound, commands.MaxConcurrencyReached, asyncio.TimeoutError, commands.BadArgument)  # , exceptions.RequiredTier)
        error = getattr(error, 'original', error)

        # if isinstance(error, ignored) or (hasattr(error, "log") and error and error.log is False):
        #     log.warning("Ignored error called: {}".format(error))
        #     return

        if isinstance(error, just_send):
            await ctx.send(str(error), ephemeral=True)
        elif isinstance(error, commands.BotMissingPermissions):
            if "embed_links" in error.missing_permissions:
                await ctx.send(str(error), ephemeral=True)
            else:
                await ctx.send(str(error), ephemeral=True)
        elif isinstance(error, commands.BadUnionArgument) and "into Member or User." in str(error):
            await ctx.send("Invalid user. Please mention a user or provide a user ID.")
        elif isinstance(error, (commands.MissingRequiredArgument, commands.TooManyArguments)):
            await ctx.send_help(ctx.command)
        elif isinstance(error, commands.CommandOnCooldown):
            retry_after = discord.utils.utcnow() + datetime.timedelta(seconds=error.retry_after)
            await ctx.send(f"This command is on a cooldown, and will be available in `{human_timedelta(retry_after)}` or <t:{int(retry_after.timestamp())}:R>", ephemeral=True)
        # elif isinstance(error, (exceptions.RequiredTier, exceptions.NotInSupportServer)):
        #     await ctx.send(str(error), ephemeral=True)
        elif isinstance(error, commands.CheckFailure):
            log.warn(f"{ctx.guild and ctx.guild.id or 'Private Message'} {ctx.channel} {ctx.author} {error}")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("This command does not work in non-server text channels", ephemeral=True)
        elif isinstance(error, OverflowError):
            await ctx.send("An arguments number is too large.", ephemeral=True)
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            if not isinstance(original, discord.HTTPException):
                print(f"In {ctx.command.qualified_name}:", file=sys.stderr)
                traceback.print_tb(original.__traceback__)
                log.error(f"{original.__class__.__name__}: {original}", sys.stderr.readline)
        else:
            if error:
                log.error('Ignoring exception in command {}:'.format(ctx.command), exc_info=(type(error), error, error.__traceback__))
            # if not self.prod and not self.canary:
            #     return
            # try:
            #     await self.log_errors.safe_send(username=self.user.name, avatar_url=self.bot.user.display_avatar.url, content=f"Ignoring exception in command {ctx.command}:\n{''.join(traceback.format_exception(type(error), error, error.__traceback__))}")
            # except Exception as e:
            #     log.error(f"ERROR while ignoring exception in command {ctx.command}: {e}")
            # else:
            #     log.info("ERROR sent")

    async def on_ready(self):
        if not hasattr(self, "uptime"):
            self.uptime = discord.utils.utcnow()

        log.info(f"Logged in as #{self.user}")

    async def on_message(self, msg: discord.Message):
        if msg.author.bot:
            return

        await self.process_commands(msg)

    async def close(self) -> None:
        await super().close()
        await self.session.close()

    async def start(self, token: str, **kwargs: Any) -> None:
        await super().start(token, reconnect=True)

    @property
    def config(self):
        return __import__('config')


async def main(bot):
    async with bot:
        await bot.start(config.token)

if __name__ == "__main__":
    print(f"Python version: {sys.version}")

    bot = AutoShardedBot()
    try:
        with setup_logging():
            asyncio.run(main(bot))
    except KeyboardInterrupt:
        asyncio.run(bot.close())
