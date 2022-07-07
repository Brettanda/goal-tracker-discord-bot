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
    from .tasks import Task  # , TaskTracker


class GoalsTracked(Table):
    id = Column("id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY")
    user_id = Column("user_id bigint NOT NULL")
    created = Column("created timestamp NOT NULL DEFAULT (now() at time zone 'utc')")
    goal = Column("goal text NOT NULL")
    expires = Column("expires timestamp")


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
            titles.append(f"{NUMTOEMOTES[x + 1]} {'~~' if g.completed else ''}{g.goal}{'~~' if g.completed else ''}{expires}")
            values.append(f"Completed: {checks[g.completed]}\n"
                          f"{'Tasks: ' + str(g.goal) if g.goal else ''}")
        return embed(
            title="Your tasks",
            fieldstitle=titles,
            fieldsval=values,
            fieldsin=[False] * len(titles),
            color=MessageColors.music())

    def is_paginating(self) -> bool:
        return True


class Goal:
    __slots__ = ("id", "user_id", "created", "goal", "expires", "tasks",)

    def __init__(self, *, record: asyncpg.Record, tasks: list[Task] = None) -> None:
        self.id: int = record["id"]
        self.user_id: int = record["user_id"]
        self.created: NDT = record["created"]
        self.goal: str = record["goal"]
        self.expires: Optional[NDT] = record["expires"]
        self.tasks = tasks

    @property
    def progress(self) -> float:
        if not self.tasks:
            return 0
        completed = len([t for t in self.tasks if t.completed is True])
        return completed / len(self.tasks)

    @property
    def completed(self) -> bool:
        return self.progress == 1.0

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
            to_return.append(Goal(record=record))
        return sorted(to_return, key=lambda x: x.expires or x.created)

    @commands.Cog.listener()
    async def on_goals_send_reminder_timer_complete(self, timer: Timer):
        ...

    @commands.hybrid_group(fallback="display", invoke_without_command=True, case_insensitive=True)
    async def goals(self, ctx: Context, *, goal: app_commands.Transform[Optional[Goal], GoalConverter] = None):
        """Displays all your goals."""

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
        goal: str
    ):
        await ctx.send((expires and format_dt(expires.dt) or "Never") + f" {ctx._timezone_name}")

    # @goals.command(name="delete",aliases=["remove"])
    # async


async def setup(bot: AutoShardedBot):
    ...
    # await bot.add_cog(GoalTracker(bot))
