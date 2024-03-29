"""
Stolen and modified from R. Danny.
:)

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import textwrap
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, menus
from typing_extensions import Annotated
from utils.cache import cache
from utils import paginator
from utils import time, db
from utils.embed import embed
from utils.time import ADT, NDT
from utils.fuzzy import autocomplete
from utils.context import Context

if TYPE_CHECKING:
    from index import AutoShardedBot
    from typing_extensions import Self

log = logging.getLogger(__name__)


class Reminders(db.Table):
    id = db.Column("id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY")
    expires = db.Column("expires timestamp NOT NULL")
    created = db.Column("created timestamp NOT NULL DEFAULT (now() at time zone 'utc')")
    event = db.Column("event text")
    extra = db.Column("extra jsonb DEFAULT '{}'::jsonb")


class PaginatorSource(menus.ListPageSource):
    def __init__(self, entries: list[asyncpg.Record], *, per_page: int = 10, title: str = "Reminders"):
        self.title = title
        super().__init__(entries, per_page=per_page)

    async def format_page(self, menu: menus.MenuPages, page: list[asyncpg.Record]) -> discord.Embed:
        titles, values = [], []

        for _id, expires, _, _, extra in page:
            message = extra["args"][2]
            shorten = textwrap.shorten(message, width=512)
            titles.append(f"{_id}: {time.format_dt(expires, style='R')}")
            values.append(f"{shorten}")
        return embed(
            title=self.title,
            fieldstitle=titles,
            fieldsval=values,
            fieldsin=[False] * len(titles),
            footer=f"{menu.current_page}/{self.get_max_pages()} pages"
        )

    def is_paginating(self) -> bool:
        return True


class Timer:
    __slots__ = ("args", "kwargs", "event", "id", "created_at", "expires",)

    def __init__(self, *, record: asyncpg.Record):
        self.id: int = record["id"]

        extra = record["extra"]
        self.args: Sequence[Any] = extra.get("args", [])
        self.kwargs: dict[str, Any] = extra.get("kwargs", {})
        self.event: str = record["event"]
        self.created_at: NDT = record["created"]
        self.expires: NDT = record["expires"]

    @classmethod
    def temporary(
            cls,
            *,
            expires: NDT,
            created: NDT,
            event: str,
            args: Sequence[Any],
            kwargs: Dict[str, Any]
    ) -> Self:
        pseudo = {
            "id": None,
            "extra": {"args": args, "kwargs": kwargs},
            "event": event,
            "created": created,
            "expires": expires,
        }
        return cls(record=pseudo)

    def __eq__(self, other: object) -> bool:
        try:
            return self.id == other.id  # type: ignore
        except AttributeError:
            return False

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def human_delta(self) -> str:
        return time.format_dt(self.created_at, style="R")

    @property
    def author_id(self) -> Optional[int]:
        if self.args:
            return int(self.args[0])
        return None

    def __repr__(self) -> str:
        return f"<Timer created={self.created_at} expires={self.expires} event={self.event}>"


class ReminderConverter(commands.Converter, app_commands.Transformer):
    async def convert(self, ctx: Context, argument: str) -> Timer:
        cog: Reminder = ctx.cog  # type: ignore
        records: list[asyncpg.Record] = await cog.get_records(ctx.author.id, connection=ctx.db)
        timers = [Timer(record=record) for record in records]

        try:
            return next(g for g in timers if str(g.id) == argument)
        except StopIteration:
            raise commands.BadArgument(ctx.lang["reminder"]["not_found"])

    @classmethod
    async def transform(cls, interaction: discord.Interaction, value: str) -> Timer:
        ctx: Context = await Context.from_interaction(interaction)
        cog: Reminder = interaction.client.get_cog("Reminder")  # type: ignore
        records: list[asyncpg.Record] = await cog.get_records(ctx.author.id, connection=ctx.db)
        timers = [Timer(record=record) for record in records]

        try:
            return next(g for g in timers if str(g.id) == value)
        except StopIteration:
            raise commands.BadArgument(ctx.lang["reminder"]["not_found"])

    @classmethod
    async def autocomplete(cls, interaction: discord.Interaction, value: str) -> list[app_commands.Choice[str | float | int]]:
        cog: Reminder = interaction.client.get_cog("Reminder")  # type: ignore
        records: list[asyncpg.Record] = await cog.get_records(interaction.user.id)
        timers = [Timer(record=record) for record in records]

        return autocomplete([app_commands.Choice(name=g.args[2], value=str(g.id)) for g in timers], value)


class Reminder(commands.Cog):
    """Set reminders for yourself"""

    def __init__(self, bot: AutoShardedBot):
        self.bot: AutoShardedBot = bot
        self._have_data = asyncio.Event()
        self._current_timer: Optional[Timer] = None

    def __repr__(self) -> str:
        return f"<cogs.{self.__cog_name__}>"

    async def cog_load(self) -> None:
        self._task = self.bot.loop.create_task(self.dispatch_timers())

    async def cog_unload(self) -> None:
        self._task.cancel()

    async def cog_command_error(self, ctx: Context, error: commands.CommandError):
        if isinstance(error, commands.TooManyArguments):
            await ctx.send(f'You called the {ctx.command.name} command with too many arguments.', ephemeral=True)

    @cache()
    async def get_records(self, user_id: int, *, connection: asyncpg.Connection = None) -> list[asyncpg.Record]:
        conn = connection or self.bot.pool
        query = """SELECT *
              FROM reminders
              WHERE event = 'reminder'
              AND extra #>> '{args,0}' = $1
              ORDER BY expires;"""
        return await conn.fetch(query, str(user_id))

    async def get_active_timer(self, *, connection: Optional[asyncpg.Connection] = None, days: int = 7) -> Optional[Timer]:
        query = "SELECT * FROM reminders WHERE expires < (CURRENT_DATE + $1::interval) ORDER BY expires LIMIT 1;"
        con = connection or self.bot.pool

        record = await con.fetchrow(query, datetime.timedelta(days=days))
        log.debug(f"PostgreSQL Query: \"{query}\" + {datetime.timedelta(days=days)}")
        return Timer(record=record) if record else None

    async def wait_for_active_timer(self, *, connection: Optional[asyncpg.Connection] = None, days: int = 7) -> Timer:
        async with db.MaybeAcquire(connection=connection, pool=self.bot.pool) as con:
            timer = await self.get_active_timer(connection=con, days=days)
            if timer is not None:
                self._have_data.set()
                return timer

            self._have_data.clear()
            self._current_timer = None
            await self._have_data.wait()
            return await self.get_active_timer(connection=con, days=days)  # type: ignore

    async def call_timer(self, timer: Timer) -> None:
        await self.bot.pool.execute("DELETE FROM reminders WHERE id=$1;", timer.id)

        self.bot.dispatch(f"{timer.event}_timer_complete", timer)

    async def dispatch_timers(self) -> None:
        try:
            while not self.bot.is_closed():
                timer = self._current_timer = await self.wait_for_active_timer(days=40)
                now: NDT = datetime.datetime.utcnow()  # type: ignore

                if timer.expires >= now:
                    to_sleep = (timer.expires - now).total_seconds()
                    await asyncio.sleep(to_sleep)
                await self.call_timer(timer)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError as e:
            raise e
        except (OSError, discord.ConnectionClosed, asyncpg.PostgresConnectionError):
            self._task.cancel()
            self._task = self.bot.loop.create_task(self.dispatch_timers())

    async def short_timer_optimisation(self, seconds: float, timer: Timer) -> None:
        await asyncio.sleep(seconds)
        event_name = f'{timer.event}_timer_complete'
        self.bot.dispatch(event_name, timer)

    async def create_timer(self, when: NDT | ADT, event: str, *args: Any, **kwargs: Any) -> Timer:
        try:
            connection = kwargs.pop('connection')
        except KeyError:
            connection = self.bot.pool

        try:
            now = kwargs.pop('created')
        except KeyError:
            now = discord.utils.utcnow()  # type: ignore

        when_to: NDT = when.astimezone(datetime.timezone.utc).replace(tzinfo=None)  # type: ignore
        now: NDT = now.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        timer = Timer.temporary(event=event, args=args, kwargs=kwargs, expires=when_to, created=now)
        delta = (when_to - now).total_seconds()
        if delta <= 60:
            # a shortcut for small timers
            self.bot.loop.create_task(self.short_timer_optimisation(delta, timer))
            return timer

        query = """INSERT INTO reminders (event, extra, expires, created)
                  VALUES ($1, $2::jsonb, $3, $4)
                  RETURNING id;
              """

        row = await connection.fetchrow(query, event, {"args": args, "kwargs": kwargs}, when_to, now)
        log.debug(f"PostgreSQL Query: \"{query}\" + {event, {'args': args, 'kwargs': kwargs}, when_to, now}")
        timer.id = row[0]

        if delta <= (86400 * 40):  # 40 days
            self._have_data.set()

        if self._current_timer and when_to < self._current_timer.expires:
            self._task.cancel()
            self._task = self.bot.loop.create_task(self.dispatch_timers())

        return timer

    @commands.hybrid_group("reminder", fallback="set", aliases=["timer", "remind"], extras={"examples": ["20m go buy food", "do something in 20m", "jan 1st happy new years"]}, usage="<when> <message>", invoke_without_command=True)
    async def reminder(self, ctx: Context, *, when: Annotated[time.FriendlyTimeResult, time.UserFriendlyTime(commands.clean_content, default="...")], reminder: str = None):
        """ Create a reminder for a certain time in the future. """
        await self.create_timer(
            when.dt,
            "reminder",
            ctx.author.id,
            ctx.channel.id,
            reminder or when.arg,
            connection=ctx.pool,
            created=ctx.message.created_at,
            message_id=ctx.interaction is None and ctx.message.id
        )
        self.get_records.invalidate(self, ctx.author.id)
        await ctx.send(ctx.lang["reminder"]["set"].format(time.format_dt(when.dt, style='R'), reminder or when.arg))

    @reminder.command("list", ignore_extra=False)
    async def reminder_list(self, ctx: Context):
        """ List all reminders. """
        records = await self.get_records(ctx.author.id, connection=ctx.db)

        if len(records) == 0:
            return await ctx.send(ctx.lang["reminder"]["empty"], ephemeral=True)

        source = PaginatorSource(entries=records, title=ctx.lang["reminder"]["list_title"])
        pages = paginator.RoboPages(source=source, ctx=ctx, compact=True)

        await pages.start()

    @reminder.command("delete", aliases=["remove", "cancel"], extras={"examples": ["1", "200"]}, ignore_extra=False)
    async def reminder_delete(self, ctx: Context, *, reminder: app_commands.Transform[Timer, ReminderConverter]):
        """ Delete a reminder. """
        query = """DELETE FROM reminders
              WHERE id=$1
              AND event='reminder'
              AND extra #>> '{args,0}' = $2;"""

        status = await ctx.db.execute(query, reminder.id, str(ctx.author.id))
        if status == "DELETE 0":
            return await ctx.send(ctx.lang["reminder"]["delete"]["missing"], ephemeral=True)

        if self._current_timer and self._current_timer.id == reminder.id:
            self._task.cancel()
            self._task = self.bot.loop.create_task(self.dispatch_timers())
        self.get_records.invalidate(self, ctx.author.id)

        await ctx.send(ctx.lang["reminder"]["delete"]["deleted"])

    @reminder.command("clear", ignore_extra=False)
    async def reminder_clear(self, ctx: Context):
        """ Delete all your reminders. """
        query = """SELECT COUNT(*)
              FROM reminders
              WHERE event='reminder'
              AND extra #>> '{args,0}' = $1;"""

        author_id = str(ctx.author.id)
        total = await ctx.db.fetchrow(query, author_id)
        total = total[0]
        if total == 0:
            return await ctx.send(ctx.lang["reminder"]["empty"], ephemeral=True)

        confirm = await ctx.prompt(ctx.lang["reminder"]["clear"]["prompt"].format(f"{time.plural(total):reminder}"))
        if not confirm:
            return await ctx.send(ctx.lang["reminder"]["clear"]["cancelled"], ephemeral=True)

        query = """DELETE FROM reminders WHERE event = 'reminder' AND extra #>> '{args,0}' = $1;"""
        await ctx.db.execute(query, author_id)

        if self._current_timer and self._current_timer.author_id == ctx.author.id:
            self._task.cancel()
            self._task = self.bot.loop.create_task(self.dispatch_timers())
        self.get_records.invalidate(self, ctx.author.id)

        await ctx.send(ctx.lang["reminder"]["clear"]["success"].format(f"{time.plural(total):reminder}"))

    @commands.Cog.listener()
    async def on_reminder_timer_complete(self, timer: Timer):
        author_id, channel_id, message = timer.args
        self.get_records.invalidate(self, author_id)

        try:
            channel = self.bot.get_channel(channel_id) or (await self.bot.fetch_channel(channel_id))
        except discord.HTTPException:
            return

        guild_id = channel.guild.id if isinstance(channel, (discord.TextChannel, discord.Thread)) else "@me"
        message_id = timer.kwargs.get('message_id')
        view = discord.utils.MISSING

        if message_id:
            url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Go to original message", url=url))

        try:
            await channel.send(f"<@{author_id}>", embed=embed(title=f"Reminder {timer.human_delta}", description=f"{message}"), view=view)  # type: ignore
        except discord.HTTPException:
            return


async def setup(bot: AutoShardedBot):
    await bot.add_cog(Reminder(bot))
