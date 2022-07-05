from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Optional

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands
from utils.cache import cache
from utils.db import Column, Table
from utils.fuzzy import autocomplete
from utils.time import HumanTime, format_dt

if TYPE_CHECKING:
    from index import AutoShardedBot
    from typing_extensions import Self
    from utils.context import Context

    from .reminder import Timer
    from .tasks import Task, TaskTracker


class GoalsTracked(Table):
    id = Column("id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY")
    user_id = Column("user_id bigint NOT NULL")
    created = Column("created timestamp NOT NULL DEFAULT (now() at time zone 'utc')")
    goal = Column("goal text NOT NULL")
    completed = Column("completed boolean NOT NULL DEFAULT false")


class Goal:
    __slots__ = ("id", "user_id", "created", "goal", "completed",)

    id: int
    user_id: int
    created: datetime.datetime
    goal: str
    completed: bool

    @classmethod
    async def from_record(cls, record: asyncpg.Record) -> Self:
        self = cls()

        self.id = record["id"]
        self.user_id = record["user_id"]
        self.created = record["created"]
        self.goal = record["goal"]
        self.completed = record["completed"]

        return self

    def __repr__(self) -> str:
        return f"<Goal id={self.id} goal={self.goal}>"


class GoalConverter(commands.Converter, app_commands.Transformer):
    async def convert(self, ctx: Context, argument: str) -> Goal:
        cog: GoalTracker = ctx.cog  # type: ignore
        goals: list[Goal] = await cog.get_goals(ctx.author.id, connection=ctx.db)

        try:
            return next(g for g in goals if str(g.id) == argument)
        except StopIteration:
            try:
                return next(g for g in goals if str(g.goal) == argument)
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
                return next(g for g in goals if str(g.goal) == value)
            except StopIteration:
                raise commands.BadArgument("No goal found.")

    @classmethod
    async def autocomplete(cls, interaction: discord.Interaction, value: str) -> list[app_commands.Choice[str | float | int]]:
        cog: GoalTracker = interaction.client.get_cog("GoalTracker")  # type: ignore
        goals: list[Goal] = await cog.get_goals(interaction.user.id)

        return autocomplete([app_commands.Choice(name=g.goal, value=str(g.id)) for g in goals], value)


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
        for record in records:
            to_return.append(await Goal.from_record(record))
        return to_return

    async def get_goal_tasks(self, goal: Goal) -> list[Task]:
        task_cog: Optional[TaskTracker] = self.bot.get_cog("TaskTracker")  # type: ignore
        if task_cog is None:
            raise commands.CommandError("Tasks cog not loaded")

        tasks = await task_cog.get_tasks(goal.user_id)
        new_tasks = []
        for t in tasks:
            if t.goal == goal.id:
                new_tasks.append(t)

        return new_tasks

    def get_goal_tasks_progress(self, tasks: list[Task], *, goal_id: Optional[int] = None) -> float:
        if goal_id is not None:
            for t in tasks:
                if t.goal != goal_id:
                    raise ValueError("Tasks do not belong to goal")

        total = len(tasks)
        completed = 0
        for t in tasks:
            if t.completed:
                completed += 1

        return completed / total

    @commands.Cog.listener()
    async def on_goals_send_reminder_timer_complete(self, timer: Timer):
        ...

    @commands.hybrid_group(fallback="get", invoke_without_command=True, case_insensitive=True)
    async def goals(self, ctx: Context):
        await ctx.send("This is the goals command")

    @goals.command(name="add")
    async def goals_add(self, ctx: Context, when_to_complete: HumanTime = None, *, goal: str):
        await ctx.send((when_to_complete and format_dt(when_to_complete.dt) or "Never") + f" {ctx._timezone_name}")

    # @goals.command(name="delete",aliases=["remove"])
    # async


async def setup(bot: AutoShardedBot):
    await bot.add_cog(GoalTracker(bot))
