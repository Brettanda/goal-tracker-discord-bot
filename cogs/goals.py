from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from index import AutoShardedBot
    from utils.context import Context


class Goals(commands.Cog):
    def __init__(self, bot: AutoShardedBot):
        self.bot: AutoShardedBot = bot

    def __repr__(self) -> str:
        return f"<cogs.{self.__cog_name__}>"

    @commands.hybrid_group(fallback="get", invoke_without_command=True, case_insensitive=True)
    async def goals(self, ctx: Context):
        await ctx.send("This is the goals command")

    @goals.command(name="add")
    async def goals_add(self, ctx: Context):
        ...


async def setup(bot: AutoShardedBot):
    await bot.add_cog(Goals(bot))
