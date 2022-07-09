from __future__ import annotations

from typing import TYPE_CHECKING, Optional

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
from utils.time import NDT, HumanTime, format_dt

if TYPE_CHECKING:
    from index import AutoShardedBot
    from utils.context import Context

    from .reminder import Timer
    from .tasks import Task, TaskTracker


class GoalsTracked(Table):
    id = Column("id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY")
    user_id = Column("user_id bigint NOT NULL")
    created = Column("created timestamp NOT NULL DEFAULT (now() at time zone 'utc')")
    name = Column("name text NOT NULL")
    expires = Column("expires timestamp")


def bar(*, iteration: int = 0, total: int = 0, length: int = 25, decimals: int = 1, fill: str = "█") -> str:
    percent = ("{0:." + str(decimals if iteration != total else 0) + "f}").format(100 * (iteration / float(max(total, 1))))
    filledLength = int(length * iteration // max(total, 1))
    bar = fill * filledLength + '░' * (length - filledLength)
    return f"\r |{bar}| {percent}% ({iteration}/{total})"


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
    def __init__(self, entries: list[Goal], *, per_page: int = 10):
        super().__init__(entries, per_page=per_page)

    async def format_page(self, menu: menus.MenuPages, page: list[Goal]) -> discord.Embed:
        checks = {
            True: "\N{WHITE HEAVY CHECK MARK}",
            False: "\N{CROSS MARK}"
        }
        titles, values = [], []
        for x, g in enumerate(page):
            expires = f" - {format_dt(g.expires,'R')}" if g.expires else ""
            titles.append(f"{NUMTOEMOTES[x + 1]} {'~~' if g.completed else ''}{g.name}{'~~' if g.completed else ''}{expires}")
            tasks_list = 'Tasks: ```\n' + "\n".join([t.name for t in g.tasks]) + "\n```" if g.tasks is not None else ''
            values.append(f"Completed: {checks[g.is_completed()]}\n"
                          f"{tasks_list}"
                          f"{bar(iteration=g.completed, total=len(g.tasks)) if g.tasks else ''}")
        return embed(
            title="Your goals",
            fieldstitle=titles,
            fieldsval=values,
            fieldsin=[False] * len(titles),
            color=MessageColors.music())

    def is_paginating(self) -> bool:
        return True


class Goal:
    __slots__ = ("id", "user_id", "created", "name", "expires", "tasks",)

    def __init__(self, *, record: asyncpg.Record, tasks: list[Task] = None) -> None:
        self.id: int = record["id"]
        self.user_id: int = record["user_id"]
        self.created: NDT = record["created"]
        self.name: str = record["name"]
        self.expires: Optional[NDT] = record["expires"]
        self.tasks = tasks

    @property
    def progress(self) -> float:
        if not self.tasks:
            return 0.0
        return self.completed / len(self.tasks)

    @property
    def completed(self) -> int:
        if not self.tasks:
            return 0
        return len([t for t in self.tasks if t.completed is True])

    def is_completed(self) -> bool:
        return self.progress == 1.0

    def __repr__(self) -> str:
        return f"<Goal id={self.id} name={self.name}>"


class GoalConverter(commands.Converter, app_commands.Transformer):
    async def convert(self, ctx: Context, argument: str) -> Goal:
        cog: GoalTracker = ctx.cog  # type: ignore
        goals: list[Goal] = await cog.get_goals(ctx.author.id, connection=ctx.db)

        try:
            return next(g for g in goals if str(g.id) == argument)
        except StopIteration:
            try:
                return next(g for g in goals if str(g.name) == argument)
            except StopIteration:
                raise commands.BadArgument("No goal found.")

    @classmethod
    async def transform(cls, interaction: discord.Interaction, value: str) -> Goal:
        cog: GoalTracker = interaction.client.get_cog("GoalTracker")  # type: ignore
        goals: list[Goal] = await cog.get_goals(interaction.user.id)

        try:
            return next(g for g in goals if str(g.id) == value)
        except StopIteration:
            try:
                return next(g for g in goals if str(g.name) == value)
            except StopIteration:
                raise commands.BadArgument("No goal found.")

    @classmethod
    async def autocomplete(cls, interaction: discord.Interaction, value: str) -> list[app_commands.Choice[str | float | int]]:
        cog: GoalTracker = interaction.client.get_cog("GoalTracker")  # type: ignore
        goals: list[Goal] = await cog.get_goals(interaction.user.id)

        return autocomplete([app_commands.Choice(name=g.name, value=str(g.id)) for g in goals], value)


class GoalTracker(commands.Cog):
    def __init__(self, bot: AutoShardedBot):
        self.bot: AutoShardedBot = bot

    def __repr__(self) -> str:
        return f"<cogs.{self.__cog_name__}>"

    @cache()
    async def get_goals(self, user_id: int, *, connection: asyncpg.Connection = None) -> list[Goal]:
        conn = connection or self.bot.pool
        query = "SELECT * FROM goalstracked WHERE user_id = $1"
        records = await conn.fetch(query, user_id)
        to_return = []
        tasktracker: Optional[TaskTracker] = self.bot.get_cog("TaskTracker")  # type: ignore
        tasks = tasktracker and await tasktracker.get_tasks(user_id, connection=conn)
        for record in records:
            goal_tasks = tasks and [t for t in tasks if t.goal == record["id"]]
            to_return.append(Goal(record=record, tasks=goal_tasks))
        return sorted(to_return, key=lambda x: x.expires or x.created)

    @commands.Cog.listener()
    async def on_goal_expires_timer_complete(self, timer: Timer):
        author_id, goal_id = timer.args
        await self.bot.wait_until_ready()

        goals = await self.get_goals(author_id)
        goal: Optional[Goal] = next(g for g in goals if g.id == goal_id)
        if goal is None:
            return

    @commands.hybrid_group(fallback="display", invoke_without_command=True, case_insensitive=True)
    async def goals(self, ctx: Context, *, goal: app_commands.Transform[Optional[Goal], GoalConverter] = None):
        """Displays all or one of your goals."""

        if goal is not None:
            source = PaginatorSource(entries=[goal])
            e = await source.format_page(None, [goal])  # type: ignore
            await ctx.send(embed=e)
            return

        goals = await self.get_goals(ctx.author.id)

        if len(goals) == 0:
            return await ctx.send("You don't have any goals yet", ephemeral=True)

        source = PaginatorSource(entries=goals)
        pages = paginator.RoboPages(source=source, ctx=ctx, compact=True)

        await pages.start()

    @goals.command(name="add")
    async def goals_add(
        self,
        ctx: Context,
        expires: HumanTime = None,
        *,
        name: str
    ):
        """Add a goal for your tasks"""
        reminder = self.bot.reminder
        if reminder is None and expires is not None:
            return await ctx.send('Sorry, this functionality is currently unavailable. Try again later?', ephemeral=True)
        query = "INSERT INTO goalstracked (user_id, name, expires) VALUES ($1, $2, $3) RETURNING *"
        record = await ctx.db.fetchrow(query, ctx.author.id, name, expires)
        goal = Goal(record=record)
        if reminder and goal.expires:
            await reminder.create_timer(goal.expires, "goal_expires", ctx.author.id, goal.id)
        await ctx.send(f"Added goal {goal.name}", ephemeral=True)

    @goals.command(name="modify")
    async def goals_modify(
        self,
        ctx: Context,
        goal: app_commands.Transform[Goal, GoalConverter],
        expires: HumanTime = None,
        name: str = None
    ):
        """ Modify and existing goal """
        if expires is None and name is None:
            await ctx.send("Nothing changed", ephemeral=True)
            return

        query = "UPDATE goalstracked SET "
        options = []
        params = []
        x = 1
        if expires is not None:
            options.append(f"expires = ${x}")
            params.append(expires and expires.dt)
            x += 1
        if name is not None:
            options.append(f"name = ${x}")
            params.append(name)
            x += 1
        query += ", ".join(options)
        query += f" WHERE id = ${len(options) + 1}"

        await ctx.db.execute(
            query,
            *params,
            goal.id
        )
        self.get_goals.invalidate(self, ctx.author.id)
        await ctx.send(f"Goal `{goal.name}` changed!", ephemeral=True)

    @goals.command(name="delete", aliases=["remove"])
    async def goals_delete(self, ctx: Context, goal: app_commands.Transform[Goal, GoalConverter]):
        """Delete a goal"""
        reminder = self.bot.reminder
        if reminder is None:
            return await ctx.send('Sorry, this functionality is currently unavailable. Try again later?', ephemeral=True)

        query = """DELETE FROM goalstracked
                WHERE id = $1 and user_id = $2;"""
        await ctx.db.execute(query, goal.id, ctx.author.id)

        query = """DELETE FROM reminders
                WHERE event='goal_complete'
                AND extra #>> '{args,0}' = $1 RETURNING id;"""
        timer_id = await ctx.db.fetchval(query, str(goal.id))
        if reminder._current_timer and reminder._current_timer.id == timer_id:
            reminder._task.cancel()
            reminder._task = self.bot.loop.create_task(reminder.dispatch_timers())

        self.get_goals.invalidate(self, ctx.author.id)
        await ctx.send(f"Goal `{goal.name}` deleted!", ephemeral=True)

    @goals.command("clear")
    async def tasks_clear(self, ctx: Context):
        """Clear all of your goals"""
        confirm = await ctx.prompt("Are you sure you want to clear all goals? This cannot be undone.")
        if not confirm:
            return await ctx.send("Cancelled.", ephemeral=True)

        await ctx.db.execute("DELETE FROM goalstracked WHERE user_id = $1", ctx.author.id)
        self.get_goals.invalidate(self, ctx.author.id)
        await ctx.send("All goals cleared!", ephemeral=True)


async def setup(bot: AutoShardedBot):
    await bot.add_cog(GoalTracker(bot))
