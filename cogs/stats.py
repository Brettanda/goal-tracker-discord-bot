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
import gc
import io
import json
import logging
import os
import re
import sys
import textwrap
import traceback
from collections import Counter
from typing import TYPE_CHECKING, Optional, Any, TypedDict
from typing_extensions import Annotated

import asyncpg
import discord
import psutil
from discord.ext import commands, tasks

from utils import time
from utils.db import Table, Column

if TYPE_CHECKING:

    from utils.context import Context
    from index import AutoShardedBot

    class DataCommandsBatchEntry(TypedDict):
        guild: Optional[str]
        channel: str
        author: str
        used: str
        prefix: str
        command: str
        failed: bool

    class DataJoinsBatchEntry(TypedDict):
        guild: str
        time: str
        joined: Optional[bool]
        current_count: int

log = logging.getLogger(__name__)


class GatewayHandler(logging.Handler):
    def __init__(self, cog: Stats):
        self.cog: Stats = cog
        super().__init__(logging.INFO)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return record.name == "discord.gateway" or "Shard ID" in record.msg or "Websocket closed" in record.msg
        except TypeError:
            return False

    def emit(self, record: logging.LogRecord) -> None:
        self.cog.add_record(record)


class Commands(Table):
    id = Column("id bigserial PRIMARY KEY NOT NULL")
    guild_id = Column("guild_id bigint NOT NULL")
    channel_id = Column("channel_id bigint NOT NULL")
    author_id = Column("author_id bigint NOT NULL")
    used = Column("used TIMESTAMP WITH TIME ZONE")
    prefix = Column("prefix text")
    command = Column("command text")
    failed = Column("failed boolean")


class Joined(Table):
    time = Column("time TIMESTAMP WITH TIME ZONE")
    guild_id = Column("guild_id bigint NOT NULL")
    joined = Column("joined boolean DEFAULT NULL")
    current_count = Column("current_count bigint DEFAULT NULL")


class TabularData:
    def __init__(self):
        self._widths = []
        self._columns = []
        self._rows = []

    def set_columns(self, columns):
        self._columns = columns
        self._widths = [len(c) + 2 for c in columns]

    def add_row(self, row):
        rows = [str(r) for r in row]
        self._rows.append(rows)
        for index, element in enumerate(rows):
            width = len(element) + 2
            if width > self._widths[index]:
                self._widths[index] = width

    def add_rows(self, rows):
        for row in rows:
            self.add_row(row)

    def render(self):
        """Renders a table in rST format.
        Example:
        +-------+-----+
        | Name  | Age |
        +-------+-----+
        | Alice | 24  |
        |  Bob  | 19  |
        +-------+-----+
        """

        sep = '+'.join('-' * w for w in self._widths)
        sep = f'+{sep}+'

        to_draw = [sep]

        def get_entry(d):
            elem = '|'.join(f'{e:^{self._widths[i]}}' for i, e in enumerate(d))
            elem = "\\n".join(elem.splitlines())
            return f'|{elem}|'

        to_draw.append(get_entry(self._columns))
        to_draw.append(sep)

        for row in self._rows:
            to_draw.append(get_entry(row))

        to_draw.append(sep)
        return '\n'.join(to_draw)


_INVITE_REGEX = re.compile(r'(?:https?:\/\/)?discord(?:\.gg|\.com|app\.com\/invite)?\/[A-Za-z0-9]+')


def censor_invite(obj, *, _regex=_INVITE_REGEX) -> str:
    return _regex.sub('[censored-invite]', str(obj))


def hex_value(arg) -> int:
    return int(arg, base=16)


def object_at(addr) -> Optional[Any]:
    for o in gc.get_objects():
        if id(o) == addr:
            return o
    return None


class Stats(commands.Cog, command_attrs=dict(hidden=True)):
    def __init__(self, bot: AutoShardedBot):
        self.bot: AutoShardedBot = bot
        self.process = psutil.Process()
        self._batch_commands_lock, self._batch_joins_lock = asyncio.Lock(loop=bot.loop), asyncio.Lock(loop=bot.loop)
        self._data_commands_batch: list[DataCommandsBatchEntry] = []
        self._data_joins_batch: list[DataJoinsBatchEntry] = []
        self.bulk_insert_commands_loop.add_exception_type(asyncpg.PostgresConnectionError)
        self.bulk_insert_commands_loop.start()

        self.bulk_insert_joins_loop.add_exception_type(asyncpg.PostgresConnectionError)
        self.bulk_insert_joins_loop.start()

        self._gateway_queue = asyncio.Queue()
        self.gateway_worker.start()

    def __repr__(self) -> str:
        return f"<cogs.{self.__cog_name__}>"

    async def cog_check(self, ctx: Context) -> bool:
        is_owner = await self.bot.is_owner(ctx.author)
        if not is_owner:
            raise commands.NotOwner()
        if ctx.guild and not ctx.channel.permissions_for(ctx.guild.me).attach_files:
            raise commands.BotMissingPermissions(["attach_files"])
        return True

    async def bulk_insert_commands(self):
        query = """INSERT INTO commands (guild_id, channel_id, author_id, used, prefix, command, failed)
               SELECT x.guild, x.channel, x.author, x.used, x.prefix, x.command, x.failed
               FROM jsonb_to_recordset($1::jsonb) AS
               x(guild TEXT, channel TEXT, author TEXT, used TIMESTAMP, prefix TEXT, command TEXT, failed BOOLEAN)"""

        if self._data_commands_batch:
            await self.bot.pool.execute(query, json.dumps(self._data_commands_batch))
            total = len(self._data_commands_batch)
            if total > 1:
                log.info(f"Inserted {total} commands into the database")
            self._data_commands_batch.clear()

    async def bulk_insert_joins(self):
        query = """INSERT INTO joined (guild_id, joined, current_count, time)
               SELECT x.guild, x.joined, x.current_count, x.time
               FROM jsonb_to_recordset($1::jsonb) AS
               x(guild TEXT, joined BOOLEAN, current_count BIGINT, time TIMESTAMP)"""

        if self._data_joins_batch:
            await self.bot.pool.execute(query, json.dumps(self._data_joins_batch))
            total = len(self._data_joins_batch)
            if total > 1:
                log.info(f"Inserted {total} guild counts into the database")
            self._data_joins_batch.clear()

    def cog_unload(self):
        self.bulk_insert_commands_loop.stop()
        self.bulk_insert_joins_loop.stop()
        self.gateway_worker.cancel()

    @tasks.loop(seconds=10.0)
    async def bulk_insert_commands_loop(self):
        async with self._batch_commands_lock:
            await self.bulk_insert_commands()

    @tasks.loop(seconds=10.0)
    async def bulk_insert_joins_loop(self):
        async with self._batch_joins_lock:
            await self.bulk_insert_joins()

    @tasks.loop(seconds=0.0)
    async def gateway_worker(self):
        record = await self._gateway_queue.get()
        await self.notify_gateway_status(record)

    @discord.utils.cached_property
    def webhook(self):
        wh_id, wh_token = self.bot.config.bot_stat_webhook
        return discord.Webhook.partial(id=wh_id, token=wh_token, session=self.bot.session)

    async def register_command(self, ctx: Context):
        if ctx.command is None:
            return

        command = ctx.command.qualified_name
        self.bot.command_stats[command] += 1
        message = ctx.message
        destination = None
        if ctx.guild is None:
            destination = "Private Message"
            guild_id = None
        else:
            destination = f"#{message.channel} ({message.guild})"
            guild_id = ctx.guild.id

        command_with_args = message.content or f"{ctx.clean_prefix}{command} {' '.join([a for a in ctx.args[2:] if a])}{' ' and ' '.join([str(k) for k in ctx.kwargs.values()])}"
        log.info(f'{message.author} in {destination} [{ctx.lang_code}]: {command_with_args}')
        async with self._batch_commands_lock:
            self._data_commands_batch.append({
                'guild': str(guild_id),
                'channel': str(ctx.channel.id),
                'author': str(ctx.author.id),
                'used': message.created_at.isoformat(),
                'prefix': ctx.prefix,
                'command': command,
                'failed': ctx.command_failed,
            })

    async def register_joins(self, guild: discord.Guild, joined: Optional[bool] = None):
        async with self._batch_joins_lock:
            self._data_joins_batch.append({
                'guild': str(guild.id),
                'time': discord.utils.utcnow().isoformat(),
                'joined': joined,
                'current_count': len(self.bot.guilds),
            })

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        await self.register_command(ctx)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.register_joins(guild, True)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        await self.register_joins(guild, False)

    @commands.Cog.listener()
    async def on_socket_event_type(self, event_type):
        self.bot.socket_stats[event_type] += 1

    @commands.group("commandstats", invoke_without_command=True)
    async def commandstats(self, ctx, limit=20):
        counter = self.bot.command_stats
        width = len(max(counter, key=len))

        if limit > 0:
            common = counter.most_common(limit)
        else:
            common = counter.most_common()[limit:]

        output = '\n'.join(f"{k:<{width}}: {c}" for k, c in common)

        await ctx.send(f"```\n{output}\n```")

    @commands.command("socketstats")
    async def socketstats(self, ctx: Context):
        delta = discord.utils.utcnow() - self.bot.uptime
        minutes = delta.total_seconds() / 60
        total = sum(self.bot.socket_stats.values())
        cpm = total / minutes
        await ctx.send(f"{total:,} socket events observed ({cpm:.2f}/min):\n{self.bot.socket_stats}")

    def censor_object(self, obj):
        if not isinstance(obj, str) and obj.id in self.bot.blacklist:
            return "[censored]"
        return censor_invite(obj)

    medal_lookup = (
          "\N{FIRST PLACE MEDAL}",
          "\N{SECOND PLACE MEDAL}",
          "\N{THIRD PLACE MEDAL}",
          "\N{SPORTS MEDAL}",
          "\N{SPORTS MEDAL}"
    )

    @commandstats.command("global")
    async def commandstats_global(self, ctx: Context):
        query = """SELECT COUNT(*) FROM commands;"""
        total = await ctx.db.fetchrow(query)

        e = discord.Embed(title="Command Stats", colour=discord.Colour.blurple())
        e.description = f"{total[0]:,} commands used."

        query = """SELECT command, COUNT(*) AS "uses"
               FROM commands
               GROUP BY command
               ORDER BY uses DESC
               LIMIT 5;"""

        records = await ctx.db.fetch(query)
        value = "\n".join(f"{self.medal_lookup[i]}: {command} ({uses} uses)" for (i, (command, uses)) in enumerate(records))
        e.add_field(name="Top Commands", value=value, inline=False)

        query = """SELECT guild_id, COUNT(*) AS "uses"
               FROM commands
               GROUP BY guild_id
               ORDER BY uses DESC
               LIMIT 5;"""

        records = await ctx.db.fetch(query)
        value = []
        for (i, (guild_id, uses)) in enumerate(records):
            if guild_id is None:
                guild = "Private Message"
            else:
                guild = self.censor_object(self.bot.get_guild(guild_id.isdigit() and int(guild_id, base=10)) or f"<Unknown {guild_id}>")

            emoji = self.medal_lookup[i]
            value.append(f"{emoji}: {guild} ({uses} uses)")

        e.add_field(name="Top Guilds", value="\n".join(value), inline=False)

        query = """SELECT author_id, COUNT(*) AS "uses"
               FROM commands
               GROUP BY author_id
               ORDER BY "uses" DESC
               LIMIT 5;"""

        records = await ctx.db.fetch(query)
        value = []
        for (i, (author_id, uses)) in enumerate(records):
            user = self.censor_object(self.bot.get_user(author_id.isdigit() and int(author_id, base=10)) or f"<Unknown {author_id}>")
            emoji = self.medal_lookup[i]
            value.append(f"{emoji}: {user} ({uses} uses)")

        e.add_field(name="Top Users", value="\n".join(value), inline=False)
        await ctx.send(embed=e)

    @commandstats.command("today")
    async def commandstats_today(self, ctx: Context):
        query = """SELECT failed, COUNT(*) FROM commands WHERE used > (CURRENT_TIMESTAMP - INTERVAL '1 day') GROUP BY failed;"""
        total = await ctx.db.fetch(query)
        failed, success, question = 0, 0, 0
        for state, count in total:
            if state is False:
                success += count
            elif state is True:
                failed += count
            else:
                question += count

        e = discord.Embed(title="Last 24 Hour Command Stats", colour=discord.Colour.blurple())
        e.description = f"{failed + success + question:,} commands used today." \
                        f"({success} succeeded, {failed} failed, {question} unknown)"

        query = """SELECT command, COUNT(*) AS "uses"
                   FROM commands
                   WHERE used > (CURRENT_TIMESTAMP - INTERVAL '1 day')
                   GROUP BY command
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await ctx.db.fetch(query)
        value = '\n'.join(f'{self.medal_lookup[index]}: {command} ({uses} uses)' for (index, (command, uses)) in enumerate(records))
        e.add_field(name='Top Commands', value=value, inline=False)

        query = """SELECT guild_id, COUNT(*) AS "uses"
                   FROM commands
                   WHERE used > (CURRENT_TIMESTAMP - INTERVAL '1 day')
                   GROUP BY guild_id
                   ORDER BY "uses" DESC
                   LIMIT 5;
                """

        records = await ctx.db.fetch(query)
        value = []
        for (index, (guild_id, uses)) in enumerate(records):
            if guild_id is None:
                guild = 'Private Message'
            else:
                guild = self.censor_object(self.bot.get_guild(guild_id.isdigit() and int(guild_id, base=10)) or f'<Unknown {guild_id}>')
            emoji = self.medal_lookup[index]
            value.append(f'{emoji}: {guild} ({uses} uses)')

        e.add_field(name='Top Guilds', value='\n'.join(value), inline=False)

        query = """SELECT author_id, COUNT(*) AS "uses"
                  FROM commands
                  WHERE used > (CURRENT_TIMESTAMP - INTERVAL '1 day')
                  GROUP BY author_id
                  ORDER BY "uses" DESC
                  LIMIT 5;
              """

        records = await ctx.db.fetch(query)
        value = []
        for (index, (author_id, uses)) in enumerate(records):
            user = self.censor_object(self.bot.get_user(author_id.isdigit() and int(author_id, base=10)) or f'<Unknown {author_id}>')
            emoji = self.medal_lookup[index]
            value.append(f'{emoji}: {user} ({uses} uses)')

        e.add_field(name='Top Users', value='\n'.join(value), inline=False)
        await ctx.send(embed=e)

    @commandstats_today.before_invoke
    @commandstats_global.before_invoke
    async def before_stats_invoke(self, ctx):
        await ctx.trigger_typing()

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        await self.register_command(ctx)

    def add_record(self, record):
        self._gateway_queue.put_nowait(record)

    async def notify_gateway_status(self, record):
        attributes = {
            'INFO': '\N{INFORMATION SOURCE}',
            'WARNING': '\N{WARNING SIGN}'
        }

        emoji = attributes.get(record.levelname, '\N{CROSS MARK}')
        dt = datetime.datetime.utcfromtimestamp(record.created)
        msg = textwrap.shorten(f'{emoji} [{time.format_dt(dt)}] `{record.msg % record.args}`', width=1990)
        await self.webhook.send(msg, username='Gateway', avatar_url='https://i.imgur.com/4PnCKB3.png')

    @commands.command("bothealth")
    async def bothealth(self, ctx: Context):
        """Various bot health monitoring tools."""

        # This uses a lot of private methods because there is no
        # clean way of doing this otherwise.

        HEALTHY = discord.Colour(value=0x43B581)
        UNHEALTHY = discord.Colour(value=0xF04947)
        WARNING = discord.Colour(value=0xF09E47)
        total_warnings = 0

        embed_ = discord.Embed(title='Bot Health Report', colour=HEALTHY)

        # Check the connection pool health.
        pool = self.bot.pool
        total_waiting = len(pool._queue._getters)
        current_generation = pool._generation

        description = [
            f'Total `Pool.acquire` Waiters: {total_waiting}',
            f'Current Pool Generation: {current_generation}',
            f'Connections In Use: {len(pool._holders) - pool._queue.qsize()}'
        ]

        questionable_connections = 0
        connection_value = []
        for index, holder in enumerate(pool._holders, start=1):
            generation = holder._generation
            in_use = holder._in_use is not None
            is_closed = holder._con is None or holder._con.is_closed()
            display = f'gen={holder._generation} in_use={in_use} closed={is_closed}'
            questionable_connections += any((in_use, generation != current_generation))
            connection_value.append(f'<Holder i={index} {display}>')

        joined_value = '\n'.join(connection_value)
        embed_.add_field(name='Connections', value=f'```py\n{joined_value}\n```', inline=False)

        spam_control = self.bot.spam_control
        being_spammed = [
            str(key) for key, value in spam_control._cache.items()
            if value._tokens == 0
        ]

        description.append(f'Current Spammers: {", ".join(being_spammed) if being_spammed else "None"}')
        description.append(f'Questionable Connections: {questionable_connections}')

        total_warnings += questionable_connections
        if being_spammed:
            embed_.colour = WARNING
            total_warnings += 1

        try:
            task_retriever = asyncio.Task.all_tasks
        except AttributeError:
            # future proofing for 3.9 I guess
            task_retriever = asyncio.all_tasks

        all_tasks = task_retriever(loop=self.bot.loop)

        event_tasks = [
            t for t in all_tasks
            if 'Client._run_event' in repr(t) and not t.done()
        ]

        cogs_directory = os.path.dirname(__file__)
        tasks_directory = os.path.join('discord', 'ext', 'tasks', '__init__.py')
        inner_tasks = [
            t for t in all_tasks
            if cogs_directory in repr(t) or tasks_directory in repr(t)
        ]

        bad_inner_tasks = ", ".join(hex(id(t)) for t in inner_tasks if t.done() and t._exception is not None)
        total_warnings += bool(bad_inner_tasks)
        embed_.add_field(name='Inner Tasks', value=f'Total: {len(inner_tasks)}\nFailed: {bad_inner_tasks or "None"}')
        embed_.add_field(name='Events Waiting', value=f'Total: {len(event_tasks)}', inline=False)

        command_waiters = len(self._data_commands_batch)
        is_locked = self._batch_commands_lock.locked()
        description.append(f'Commands Waiting: {command_waiters}, Batch Locked: {is_locked}')

        memory_usage = self.process.memory_full_info().uss / 1024**2
        total_memory = psutil.virtual_memory().total / 1024**2
        memory_percent = self.process.memory_percent()
        cpu_usage = self.process.cpu_percent() / psutil.cpu_count()
        embed_.add_field(name='Process', value=f'{memory_usage:,.2f} MiB/{total_memory/1024:,.2f} GB ({memory_percent:.3f}%)\n{cpu_usage:.3f}% CPU', inline=False)

        global_rate_limit = not self.bot.http._global_over.is_set()
        description.append(f'Global Rate Limit: {global_rate_limit}')

        if command_waiters >= 8:
            total_warnings += 1
            embed_.colour = WARNING

        if global_rate_limit or total_warnings >= 9:
            embed_.colour = UNHEALTHY

        embed_.set_footer(text=f'{total_warnings} warning(s)')
        embed_.description = '\n'.join(description)
        await ctx.send(embed=embed_)

    @commands.command("gateway")
    async def gateway(self, ctx: Context):
        yesterday = discord.utils.utcnow() - datetime.timedelta(days=1)
        identifies = {
            shard_id: sum(1 for dt in dates if dt > yesterday)
            for shard_id, dates in self.bot.identifies.items()
        }

        resumes = {
            shard_id: sum(1 for dt in dates if dt > yesterday)
            for shard_id, dates in self.bot.resumes.items()
        }

        total_identifies = sum(identifies.values())
        builder = [
            f"Total RESUMEs: {sum(resumes.values())}",
            f"Total IDENTIFYs: {total_identifies}",
        ]

        shard_count = len(self.bot.shards)
        if total_identifies > (shard_count * 10):
            issues = 2 + (total_identifies // 10) - shard_count
        else:
            issues = 0

        for shard_id, shard in self.bot.shards.items():
            badge = None
            # Shard WS closed
            # Shard Task failure
            # Shard Task complete (no failure)
            if shard.is_closed():
                badge = ":spider_web:"
                issues += 1
            elif shard._parent._task and shard._parent._task.done():
                exc = shard._parent._task.exception()
                if exc is not None:
                    badge = "\N{FIRE}"
                    issues += 1
                else:
                    badge = "\U0001f504"

            if badge is None:
                badge = "\N{OK HAND SIGN}"

            stats = []
            identify = identifies.get(shard_id, 0)
            resume = resumes.get(shard_id, 0)
            if resume != 0:
                stats.append(f"R: {resume}")
            if identify != 0:
                stats.append(f"ID: {identify}")

            if stats:
                builder.append(f"Shard ID {shard_id}: {badge} ({', '.join(stats)})")
            else:
                builder.append(f"Shard ID {shard_id}: {badge}")
        if issues == 0:
            colour = 0x43B581
        elif issues < len(self.bot.shards) // 4:
            colour = 0xF09E47
        else:
            colour = 0xF04947

        e = discord.Embed(colour=colour, title="Gateway (last 24 hours)")
        e.description = "\n".join(builder)
        e.set_footer(text=f"{issues} warning(s)")
        await ctx.send(embed=e)

    @commands.command(hidden=True, aliases=['cancel_task'])
    @commands.is_owner()
    async def debug_task(self, ctx: Context, memory_id: Annotated[int, hex_value]):
        """Debug a task by a memory location."""
        task = object_at(memory_id)
        if task is None or not isinstance(task, asyncio.Task):
            return await ctx.send(f'Could not find Task object at {hex(memory_id)}.')

        if ctx.invoked_with == 'cancel_task':
            task.cancel()
            return await ctx.send(f'Cancelled task object {task!r}.')

        paginator = commands.Paginator(prefix='```py')
        fp = io.StringIO()
        frames = len(task.get_stack())
        paginator.add_line(f'# Total Frames: {frames}')
        task.print_stack(file=fp)

        for line in fp.getvalue().splitlines():
            paginator.add_line(line)

        for page in paginator.pages:
            await ctx.send(page)

    async def tabulate_query(self, ctx: Context, query: str, *args: Any):
        records = await ctx.db.fetch(query, *args)

        if len(records) == 0:
            return await ctx.send('No results found.')

        headers = list(records[0].keys())
        table = TabularData()
        table.set_columns(headers)
        table.add_rows(list(r.values()) for r in records)
        render = table.render()

        fmt = f'```\n{render}\n```'
        if len(fmt) > 2000:
            fp = io.BytesIO(fmt.encode("utf-8"))
            await ctx.send("Too many results to display.", file=discord.File(fp, filename="query.txt"))
        else:
            await ctx.send(fmt)

    @commands.group("commandhistory", invoke_without_command=True)
    async def command_history(self, ctx: Context):
        query = """SELECT
                 CASE failed
                   WHEN TRUE THEN command || ' [!]'
                   ELSE command
                 END AS "command",
                 to_char(used, 'Mon DD HH12:MI:SS AM') AS "invoked",
                 author_id,
                 guild_id
               FROM commands
               ORDER BY used DESC
               LIMIT 15;"""

        await self.tabulate_query(ctx, query)

    @command_history.command("for")
    async def command_history_for(self, ctx: Context, days: Annotated[int, Optional[int]] = 7, *, command: str):
        query = """SELECT *, t.success + t.failed AS "total"
                FROM (
                  SELECT guild_id,
                         SUM(CASE WHEN failed THEN 0 ELSE 1 END) AS "success",
                         SUM(CASE WHEN failed THEN 1 ELSE 0 END) AS "failed"
                  FROM commands
                  WHERE command=$1
                  AND used > (CURRENT_TIMESTAMP - $2::interval)
                  GROUP BY guild_id
                ) AS t
                ORDER BY "total" DESC
                LIMIT 30;"""

        await self.tabulate_query(ctx, query, command, datetime.timedelta(days=days))

    @command_history.command("guild", aliases=["server"])
    async def command_history_guild(self, ctx: Context, guild_id: int):
        query = """SELECT
                 CASE failed
                   WHEN TRUE THEN command || ' [!]'
                   ELSE command
                 END AS "command",
                 channel_id,
                 author_id,
                 used
               FROM commands
               WHERE guild_id=$1
               ORDER BY used DESC
               LIMIT 15;"""
        await self.tabulate_query(ctx, query, str(guild_id))

    @command_history.command(name='user', aliases=['member'])
    async def command_history_user(self, ctx, user_id: int):
        """Command history for a user."""

        query = """SELECT
                      CASE failed
                          WHEN TRUE THEN command || ' [!]'
                          ELSE command
                      END AS "command",
                      guild_id,
                      used
                  FROM commands
                  WHERE author_id=$1
                  ORDER BY used DESC
                  LIMIT 20;
              """
        await self.tabulate_query(ctx, query, str(user_id))

    @commands.group("commandactivity", invoke_without_command=True)
    async def command_activity(self, ctx: Context):
        # WHERE used > (CURRENT_TIMESTAMP - '1 day'::interval)
        query = """SELECT
                  extract(hour from used) AS "hour",
                  SUM(CASE WHEN failed THEN 0 ELSE 1 END) AS "success"
              FROM commands
              GROUP BY extract(hour from used)
              ORDER BY extract(hour from used);"""
        record = await ctx.db.fetch(query)
        hours = [0] * 24
        for r in record:
            hours[int(r["hour"])] = r["success"]

        graph = ""
        space = 30
        for i, v in enumerate(hours):
            scaled = int(v / max(hours) * space)
            spacer = " " * (space - scaled)
            graph += f"{i+1:02d} | {'#' * min(space,scaled)}{spacer} | {v or ''}\n"
        mid = int(max(hours) / 2)
        graph += f"   0 {'-':->{space/2-len(str(mid))}} {mid} {'-':->{space/2-len(str(mid))}} {max(hours):,}\n"
        graph = graph.strip()

        await ctx.send(f"```\n{graph}\n```")


old_on_error = commands.AutoShardedBot.on_error


async def on_error(self, event: str, *args: Any, **kwargs: Any) -> None:
    (exc_type, exc, tb) = sys.exc_info()
    # Silence command errors that somehow get bubbled up far enough here
    if isinstance(exc, commands.CommandInvokeError):
        return

    e = discord.Embed(title="Event Error", colour=0xa32952)
    e.add_field(name="Event", value=event)
    trace = "".join(traceback.format_exception(exc_type, exc, tb))
    e.description = f"```py\n{trace}\n```"
    e.timestamp = discord.utils.utcnow()

    args_str = ['```py']
    for index, arg in enumerate(args):
        args_str.append(f"[{index}]: {arg!r}")
    args_str.append('```')
    e.add_field(name="Args", value='\n'.join(args_str), inline=False)
    hook = self.get_cog("Stats").webhook
    try:
        await hook.send(embed=e)
    except BaseException:
        pass


async def setup(bot: AutoShardedBot):
    if not hasattr(bot, 'command_stats'):
        bot.command_stats = Counter()

    if not hasattr(bot, "socket_stats"):
        bot.socket_stats = Counter()

    cog = Stats(bot)
    await bot.add_cog(cog)
    bot.gateway_handler = handler = GatewayHandler(cog)
    logging.getLogger().addHandler(handler)
    commands.AutoShardedBot.on_error = on_error


def teardown(bot: AutoShardedBot):
    commands.AutoShardedBot.on_error = old_on_error
    logging.getLogger().removeHandler(bot.gateway_handler)
    del bot.gateway_handler
