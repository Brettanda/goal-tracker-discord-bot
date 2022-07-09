from __future__ import annotations

import asyncio
import datetime
import enum
import logging
from typing import TYPE_CHECKING, Literal, Optional, overload

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, menus
from utils import paginator
from utils.cache import cache
from utils.colours import MessageColors
from utils.db import Column, Table
from utils.embed import embed
from utils.fuzzy import autocomplete
from utils.time import ADT, NDT, NT, Interval, TimeOfDay, format_dt

from .goals import Goal, GoalConverter, GoalTracker

if TYPE_CHECKING:
    from index import AutoShardedBot
    from utils.context import Context

    from .reminder import Timer


log = logging.getLogger(__name__)


class TasksTracked(Table):
    id = Column("id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY")
    user_id = Column("user_id bigint NOT NULL")
    created = Column("created timestamp NOT NULL DEFAULT (now() at time zone 'utc')")
    goal = Column("goal bigint CONSTRAINT fk_goal FOREIGN KEY(goal) REFERENCES goalstracked(id) ON DELETE SET NULL")
    name = Column("name text NOT NULL")
    time = Column("time time NOT NULL DEFAULT (now() at time zone 'utc')")
    interval = Column("interval interval NOT NULL DEFAULT '1 day'")
    last_reset = Column("last_reset timestamp NOT NULL DEFAULT (now() at time zone 'utc')")
    reset_datetime = Column("reset_datetime timestamp GENERATED ALWAYS AS (CASE WHEN interval > '1 day' THEN last_reset::date + time::time ELSE last_reset END) STORED")
    remind_me = Column("remind_me boolean NOT NULL DEFAULT false")
    completed = Column("completed boolean NOT NULL DEFAULT false")


# class taskHistory(Table):
#     id = Column("id bigserial PRIMARY KEY NOT NULL")
#     user_id = Column("user_id bigint NOT NULL")
#     created = Column("created timestamp NOT NULL DEFAULT (now() at time zone 'utc')")
#     missed_tasks = Column("missed_tasks bigint NOT NULL DEFAULT 0")
#     completed_tasks = Column("completed_tasks bigint NOT NULL DEFAULT 0")

NUMTOEMOTES = {
    0: "0️⃣",
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
    10: "🔟",
}


class PaginatorSource(menus.ListPageSource):
    def __init__(self, entries: list[Task], *, per_page: int = 10):
        super().__init__(entries, per_page=per_page)

    async def format_page(self, menu: menus.MenuPages, page: list[Task]) -> discord.Embed:
        checks = {
            True: "\N{WHITE HEAVY CHECK MARK}",
            False: "\N{CROSS MARK}"
        }
        titles, values = [], []
        for x, g in enumerate(page):
            titles.append(f"{NUMTOEMOTES[x + 1]} {'~~' if g.completed else ''}{g.name}{'~~' if g.completed else ''} - {format_dt(g.next_reset(),'R')}")
            values.append(f"Repeats every {g.interval}\n"
                          f"Completed: {checks[g.completed]}\n"
                          f"Time of reminder: {g.time}\n"
                          f"{'Goal: ' + str(g.goal) if g.goal else ''}")

        return embed(
            title="Your tasks",
            fieldstitle=titles,
            fieldsval=values,
            fieldsin=[False] * len(titles),
            color=MessageColors.music())

    def is_paginating(self) -> bool:
        return True


class TaskReminders(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(emoji="\N{HEAVY CHECK MARK}", label="Completed", style=discord.ButtonStyle.green, custom_id="task-completed")
    async def completed(self, interaction: discord.Interaction, button: discord.ui.Button):
        pool = interaction.client.pool  # type: ignore
        if interaction.message and interaction.message.embeds[0].footer.text:
            task_id = interaction.message.embeds[0].footer.text.split(' ')[-1]
            await pool.execute("UPDATE taskstracked SET completed = true WHERE id = $1", int(task_id))
            log.info(f"Task {task_id} marked as completed")
        await interaction.response.send_message("Task marked as completed")


class TaskDisplayIntervals(enum.Enum):
    all = "all"
    hourly = "hour"
    daily = "day"
    weekly = "week"
    monthly = "month"


class Task:
    __slots__ = ("id", "user_id", "created", "name", "goal", "time", "interval", "reset_datetime", "completed", "remind_me", "last_reset",)

    def __init__(self, *, record: asyncpg.Record) -> None:
        self.id: int = record["id"]
        self.user_id: int = record["user_id"]
        self.created: NDT = record["created"]
        self.name: str = record["name"]
        self.goal: Optional[int] = record["goal"]
        self.time: NT = record["time"]
        self.interval: datetime.timedelta = record["interval"]
        self.last_reset: NDT = record["last_reset"]
        self.reset_datetime: NDT = record["reset_datetime"]
        self.remind_me: bool = record["remind_me"]
        self.completed: bool = record["completed"]

    @overload
    def next_reset(self, *, aware: Literal[True]) -> ADT:
        ...

    @overload
    def next_reset(self) -> NDT:
        ...

    def next_reset(self, *, aware: bool = False) -> NDT | ADT:
        now: NDT = discord.utils.utcnow().replace(tzinfo=None)  # type: ignore

        if self.reset_datetime > now:
            time = self.reset_datetime
        else:
            time = self.reset_datetime + self.interval

        if aware:
            return time.replace(tzinfo=datetime.timezone.utc)
        return time

    def __repr__(self) -> str:
        return f"<Task id={self.id} name={self.name} interval={self.interval}>"


class TaskConverter(commands.Converter, app_commands.Transformer):
    async def convert(self, ctx: Context, argument: str) -> Task:
        cog: TaskTracker = ctx.cog  # type: ignore
        tasks: list[Task] = await cog.get_tasks(ctx.author.id, connection=ctx.db)

        try:
            return next(g for g in tasks if str(g.id) == argument)
        except StopIteration:
            try:
                return next(g for g in tasks if str(g.name) == argument)
            except StopIteration:
                raise commands.BadArgument("No task found.")

    @classmethod
    async def transform(cls, interaction: discord.Interaction, value: str) -> Task:
        cog: TaskTracker = interaction.client.get_cog("TaskTracker")  # type: ignore
        tasks: list[Task] = await cog.get_tasks(interaction.user.id)

        try:
            return next(g for g in tasks if str(g.id) == value)
        except StopIteration:
            try:
                return next(g for g in tasks if str(g.name) == value)
            except StopIteration:
                raise commands.BadArgument("No task found.")

    @classmethod
    async def autocomplete(cls, interaction: discord.Interaction, value: str) -> list[app_commands.Choice[str | float | int]]:
        cog: TaskTracker = interaction.client.get_cog("TaskTracker")  # type: ignore
        tasks: list[Task] = await cog.get_tasks(interaction.user.id)

        return autocomplete([app_commands.Choice(name=g.name, value=str(g.id)) for g in tasks], value)


class TaskTracker(commands.Cog):
    def __init__(self, bot: AutoShardedBot):
        self.bot: AutoShardedBot = bot

        self.views_loaded = False

    def __repr__(self) -> str:
        return f"<cogs.{self.__cog_name__}>"

    async def cog_load(self) -> None:
        if not self.views_loaded:
            self.views_loaded = True
            self.bot.add_view(TaskReminders())

    @cache()
    async def get_tasks(self, user_id: int, *, connection: asyncpg.Connection = None) -> list[Task]:
        conn = connection or self.bot.pool
        query = "SELECT * FROM taskstracked WHERE user_id = $1"
        records = await conn.fetch(query, user_id)
        to_return = []
        for record in records:
            to_return.append(Task(record=record))
        return sorted(to_return, key=lambda x: x.next_reset())

    @commands.Cog.listener()
    async def on_task_reset_timer_complete(self, timer: Timer):
        user_id, task_id = timer.args
        await self.bot.wait_until_ready()

        async with self.bot.pool.acquire(timeout=300.0) as conn:
            record = await conn.fetchrow("UPDATE taskstracked SET completed = false WHERE id = $1 RETURNING *", task_id)
            self.get_tasks.invalidate(self, user_id)
            if record is None:
                return

            task = Task(record=record)

            record = await conn.fetchrow("UPDATE taskstracked SET last_reset = $1 WHERE id = $2 RETURNING *", task.next_reset(), task.id)
            task = Task(record=record)

            reminder = self.bot.reminder
            while reminder is None:
                await asyncio.sleep(0.5)

            await reminder.create_timer(task.next_reset(aware=True), "task_reset", user_id, task_id, connection=conn)

        if not task.remind_me:
            return

        try:
            user = self.bot.get_user(user_id) or (await self.bot.fetch_user(user_id))
        except discord.HTTPException as e:
            log.error(f"Failed to get user {user_id} for task {task_id}.", exc_info=e)
            return

        try:
            await user.send(embed=embed(
                title=f"Your `{task.name}` has been reset",
                footer=f"Task ID: {task.id}",
                description=f"Don't forget to mark this as completed when you're done :)\n\nYour next reminder is {format_dt(task.next_reset(),style='R')}"),
                view=TaskReminders())
        except discord.Forbidden:
            await self.bot.pool.execute("UPDATE taskstracked SET remind_me = false WHERE id = $1", task.id)
            self.get_tasks.invalidate(self, user_id)
            log.error(f"Couldn't send reminder to {user_id} for task {task_id}")
        except discord.HTTPException as e:
            log.error(f"Failed to send reminder to {user_id} for task {task_id}.", exc_info=e)
            return
        else:
            log.info(f"Sent reminder to {user} for task {task.id}")

    @commands.hybrid_group(fallback="display", invoke_without_command=True, case_insensitive=True)
    async def tasks(self, ctx: Context, *, task: app_commands.Transform[Optional[Task], TaskConverter] = None):
        """Displays all your tasks."""

        if task is not None:
            source = PaginatorSource(entries=[task])
            e = await source.format_page(None, [task])  # type: ignore
            await ctx.send(embed=e)
            return

        tasks = await self.get_tasks(ctx.author.id)

        if len(tasks) == 0:
            return await ctx.send("You don't have any tasks yet", ephemeral=True)

        source = PaginatorSource(entries=tasks)
        pages = paginator.RoboPages(source=source, ctx=ctx, compact=True)

        await pages.start()

    @tasks.command(name="add")
    @app_commands.describe(
        resets_every="How often should this task remind you?",
        goal="If setup, what goal is this apart of?",
        start_time="What time of day should this task begin?",
        task_name="What is your task?",
        remind_me="Should I remind you when this task is due?",
    )
    async def tasks_add(
            self,
            ctx: Context,
            resets_every: Interval,
            start_time: TimeOfDay = None,
            remind_me: bool = False,
            goal: app_commands.Transform[Goal, GoalConverter] = None,
            *,
            task_name: str
    ):
        """Adds a new task."""
        dt_local = start_time and start_time.dt or ctx.message.created_at.astimezone(ctx.timezone)
        dt = dt_local.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        reminder = self.bot.reminder
        if reminder is None:
            return await ctx.send('Sorry, this functionality is currently unavailable. Try again later?', ephemeral=True)

        record = await ctx.db.fetchrow("INSERT INTO taskstracked (user_id, name, interval, last_reset, time, remind_me, goal) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *", ctx.author.id, task_name, resets_every.interval, dt, dt.time(), remind_me, goal)
        task = Task(record=record)
        await reminder.create_timer(task.next_reset(aware=True), "task_reset", ctx.author.id, task.id)
        self.get_tasks.invalidate(self, ctx.author.id)
        await ctx.send(f"Added task `{task_name}`, this task will reset once per `{resets_every.interval}` at `{dt_local}`. The next reset is {format_dt(task.next_reset(), style='R')}", ephemeral=True)

    @tasks.command(name="check", aliases=["done", "complete", "finish"])
    async def tasks_check(self, ctx: Context, task: app_commands.Transform[Task, TaskConverter], check: Optional[bool] = True):
        """Check off a task for the set interval"""
        await ctx.db.execute("UPDATE taskstracked SET completed = $1 WHERE id = $2", check, task.id)
        self.get_tasks.invalidate(self, ctx.author.id)
        await ctx.send(f"task `{task.name}` completed!", ephemeral=True)

    @tasks.command(name="modify", aliases=["change"])
    async def tasks_change(
        self,
        ctx: Context,
        task: app_commands.Transform[Task, TaskConverter],
        resets_every: Interval = None,
        start_time: TimeOfDay = None,
        remind_me: bool = None,
        completed: bool = None,
        task_name: str = None,
        goal: app_commands.Transform[Goal, GoalConverter] = None
    ):
        """Change a task"""
        if resets_every is None and start_time is None and remind_me is None and completed is None and task_name is None and goal is None:
            await ctx.send("Nothing changed", ephemeral=True)
            return

        query = "UPDATE taskstracked SET "
        options = []
        params = []
        x = 1
        if resets_every is not None:
            options.append(f"interval = ${x}")
            params.append(resets_every and resets_every.interval)
            x += 1
        if completed is not None:
            options.append(f"completed = ${x}")
            params.append(completed)
            x += 1
        if start_time is not None:
            options.append(f"time = ${x}")
            params.append(start_time and start_time.time)
            x += 1
        if remind_me is not None:
            options.append(f"remind_me = ${x}")
            params.append(remind_me)
            x += 1
        if goal is not None:
            options.append(f"goal = ${x}")
            params.append(goal and goal.id)
            x += 1
        if task_name is not None:
            options.append(f"name = ${x}")
            params.append(task_name)
            x += 1
        query += ", ".join(options)
        query += f" WHERE id = ${len(options) + 1}"

        await ctx.db.execute(
            query,
            *params,
            task.id
        )
        self.get_tasks.invalidate(self, ctx.author.id)
        goals: Optional[GoalTracker] = self.bot.get_cog("GoalTracker")  # type: ignore
        if goals is not None:
            goals.get_goals.invalidate(goals, ctx.author.id)
        await ctx.send(f"task `{task.name}` changed!", ephemeral=True)

    @tasks.command(name="delete", aliases=["remove"])
    async def tasks_del(self, ctx: Context, task: app_commands.Transform[Task, TaskConverter]):
        """Delete a task"""
        reminder = self.bot.reminder
        if reminder is None:
            return await ctx.send('Sorry, this functionality is currently unavailable. Try again later?', ephemeral=True)

        query = """DELETE FROM taskstracked
                WHERE id = $1 and user_id = $2;"""
        await ctx.db.execute(query, task.id, ctx.author.id)
        query = """DELETE FROM reminders
                WHERE event='task_reset'
                AND extra #>> '{args,0}' = $1 RETURNING id;"""
        timer_id = await ctx.db.fetchval(query, task.id)
        if reminder._current_timer and reminder._current_timer.id == timer_id:
            reminder._task.cancel()
            reminder._task = self.bot.loop.create_task(reminder.dispatch_timers())

        self.get_tasks.invalidate(self, ctx.author.id)
        await ctx.send(f"task `{task.name}` deleted!", ephemeral=True)

    @tasks.command("clear")
    async def tasks_clear(self, ctx: Context):
        """Clear all of your tasks"""
        confirm = await ctx.prompt("Are you sure you want to clear all tasks? This cannot be undone.")
        if not confirm:
            return await ctx.send("Cancelled.", ephemeral=True)

        await ctx.db.execute("DELETE FROM taskstracked WHERE user_id = $1", ctx.author.id)
        self.get_tasks.invalidate(self, ctx.author.id)
        await ctx.send("All tasks cleared!", ephemeral=True)


async def setup(bot: AutoShardedBot):
    await bot.add_cog(TaskTracker(bot))
