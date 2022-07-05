from __future__ import annotations

import asyncio
import datetime
import logging
import sys
import traceback
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any, Optional

import aiohttp
import asyncpg
import discord
import pytz
from discord.ext import commands

import cogs
import config
from utils.config import Config
from utils.context import Context
from utils.db import Table
from utils.logging import setup_logging
from utils.time import human_timedelta

if TYPE_CHECKING:
    from cogs.reminder import Reminder


log = logging.getLogger(__name__)


def get_prefix(bot: AutoShardedBot, message: discord.Message):
    if message.guild is not None:
        return commands.when_mentioned_or(bot.prefixes.get(message.guild.id, config.default_prefix))(bot, message)
    return commands.when_mentioned_or(config.default_prefix)(bot, message)


class AutoShardedBot(commands.AutoShardedBot):
    """Friday is a discord bot that is designed to be a flexible and easy to use bot."""

    user: discord.ClientUser
    pool: asyncpg.Pool
    uptime: datetime.datetime
    command_stats: Counter[str]
    socket_stats: Counter[str]
    gateway_handler: Any

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

        # shard_id: List[datetime.datetime]
        # shows the last attempted IDENTIFYs and RESUMEs
        self.resumes: defaultdict[int, list[datetime.datetime]] = defaultdict(list)
        self.identifies: defaultdict[int, list[datetime.datetime]] = defaultdict(list)

        self.spam_control = commands.CooldownMapping.from_cooldown(10, 12.0, commands.BucketType.user)

        log.info(
            f"Cluster Starting {kwargs.get('shard_ids', None)}, {kwargs.get('shard_count', 1)}")

    def __repr__(self) -> str:
        return f"<Friday username=\"{self.user.display_name if self.user else None}\" id={self.user.id if self.user else None}>"

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession()

        self.bot_app_info = await self.application_info()
        self.owner_id = self.bot_app_info.team and self.bot_app_info.team.owner_id or self.bot_app_info.owner.id
        self.owner = self.get_user(self.owner_id) or await self.fetch_user(self.owner_id)

        self.pool = await Table.create_pool(config.postgresql)

        self.prefixes: Config[str] = Config("prefixes.json", loop=self.loop)
        self.timezones: Config[str] = Config("timezones.json", loop=self.loop)
        self.blacklist: Config[bool] = Config("blacklist.json", loop=self.loop)

        for cog in cogs.default:
            path = "cogs."
            try:
                await self.load_extension(f"{path}{cog}")
            except Exception as e:
                log.error(f"Failed to load extenstion {cog} with \n {e}")

        if config.dev_server:
            TESTING_SERVER = discord.Object(id=config.dev_server)
            self.tree.copy_global_to(guild=TESTING_SERVER)
            await self.tree.sync(guild=TESTING_SERVER)

    async def get_context(self, origin: discord.Message | discord.Interaction, /, *, cls=None) -> Context:
        return await super().get_context(origin, cls=cls or Context)

    def _clear_gateway_data(self) -> None:
        one_week_ago = discord.utils.utcnow() - datetime.timedelta(days=7)
        for _, dates in self.identifies.items():
            to_remove = [index for index, dt in enumerate(dates) if dt < one_week_ago]
            for index in reversed(to_remove):
                del dates[index]

        for _, dates in self.resumes.items():
            to_remove = [index for index, dt in enumerate(dates) if dt < one_week_ago]
            for index in reversed(to_remove):
                del dates[index]

    async def before_identify_hook(self, shard_id: int, *, initial: bool):
        self._clear_gateway_data()
        self.identifies[shard_id].append(discord.utils.utcnow())
        await super().before_identify_hook(shard_id, initial=initial)

    async def on_command_error(self, ctx: Context, error: commands.CommandError) -> None:
        if hasattr(ctx.command, 'on_error'):
            return

        # if ctx.cog:
        #   if ctx.cog._get_overridden_method(ctx.cog.cog_command_error) is not None:
        #     return

        # ignored = (commands.CommandNotFound, commands.NotOwner, )
        just_send = (commands.DisabledCommand, commands.MissingPermissions, commands.RoleNotFound, commands.MaxConcurrencyReached, asyncio.TimeoutError, commands.BadArgument, commands.NoPrivateMessage)  # , exceptions.RequiredTier)
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
            log.warning(f"{ctx.guild and ctx.guild.id or 'Private Message'} {ctx.channel} {ctx.author} {error}")
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

    def get_timezone_name(self, user_id: int, guild_id: Optional[int] = None) -> str:
        if guild_id is not None:
            try:
                return self.timezones[user_id]
            except KeyError:
                return self.timezones.get(guild_id, 'UTC')
        return self.timezones.get(user_id, 'UTC')

    def get_timezone(self, user_id: int, guild: Optional[int] = None) -> datetime.tzinfo:
        return pytz.timezone(self.get_timezone_name(user_id, guild))

    async def on_ready(self):
        if not hasattr(self, "uptime"):
            self.uptime = discord.utils.utcnow()

        log.info(f"Apart of {len(self.guilds)} guilds")

    async def on_shard_connect(self, shard_id: int):
        log.info(f"Shard #{shard_id} has connected")

    async def on_shard_ready(self, shard_id: int):
        shard = self.get_shard(shard_id)
        log.info(f"Logged in as #{shard_id} {self.user}! - {shard and shard.latency*1000:,.0f} ms")

    async def on_shard_resumed(self, shard_id: int):
        log.info(f"Shard #{shard_id} has resumed")
        self.resumes[shard_id].append(discord.utils.utcnow())

    async def on_shard_disconnect(self, shard_id: int):
        log.info(f"Shard #{shard_id} has disconnected")

    async def on_shard_reconnect(self, shard_id: int):
        log.info(f"Shard #{shard_id} has reconnected")

    async def on_message(self, msg: discord.Message):
        if msg.author.bot:
            return

        await self.process_commands(msg)

    async def process_commands(self, message: discord.Message) -> None:
        ctx = await self.get_context(message, cls=Context)

        if ctx.command is None:
            return

        current = message.created_at.replace(tzinfo=datetime.timezone.utc).timestamp()
        bucket = self.spam_control.get_bucket(message, current)
        retry_after = bucket and bucket.update_rate_limit(current)
        author_id = message.author.id

        if retry_after and author_id != self.owner_id:
            return

        try:
            await self.invoke(ctx)
        finally:
            await ctx.release()

    async def close(self) -> None:
        await super().close()
        await self.session.close()

    async def start(self, token: str, **kwargs: Any) -> None:
        await super().start(token, reconnect=True)

    @property
    def config(self):
        return __import__('config')

    @property
    def reminder(self) -> Optional[Reminder]:
        return self.get_cog("Reminder")  # type: ignore


async def main(bot):
    async with bot:
        await bot.start(config.token)


def db_init():
    import importlib
    run = asyncio.get_event_loop().run_until_complete
    try:
        run(Table.create_pool(config.postgresql))
    except Exception as e:
        print(e)
        print("Failed to create database pool")
        sys.exit(1)

    for ext in [f"cogs.{e}" for e in cogs.default]:
        try:
            importlib.import_module(ext)
        except Exception:
            print(f"Failed to import {ext}")
            traceback.print_exc()
            sys.exit(1)

    for table in Table.all_tables():
        try:
            run(table.create())
        except Exception:
            print(f"Failed to create table {table}")
            traceback.print_exc()
            sys.exit(1)
    asyncio.get_event_loop().close()


if __name__ == "__main__":
    print(f"Python version: {sys.version}")

    if len(sys.argv) > 1:
        if sys.argv[1] == "--init":
            db_init()

    bot = AutoShardedBot()
    try:
        with setup_logging():
            asyncio.run(main(bot))
    except KeyboardInterrupt:
        asyncio.run(bot.close())
