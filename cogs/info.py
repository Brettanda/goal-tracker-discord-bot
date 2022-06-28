from __future__ import annotations

from typing import TYPE_CHECKING

import discord
import psutil
from discord.ext import commands
from discord.utils import cached_property, oauth_url
from utils.embed import embed
from utils.time import human_timedelta

if TYPE_CHECKING:
    from index import AutoShardedBot
    from utils.context import Context

INVITE_PERMISSIONS = discord.Permissions(
    send_messages=True,
    send_messages_in_threads=True,
    embed_links=True,
    add_reactions=True,
)


class InviteButtons(discord.ui.View):
    def __init__(self, link: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(emoji="\N{HEAVY PLUS SIGN}", label="Invite me!", style=discord.ButtonStyle.link, url=link, row=1))


class Info(commands.Cog):
    def __init__(self, bot: AutoShardedBot):
        self.bot: AutoShardedBot = bot
        self.process = psutil.Process()

    def __repr__(self) -> str:
        return f"<cogs.{self.__cog_name__}>"

    @commands.hybrid_command(name="info", aliases=["about"], help="Displays some information about myself :)")
    async def info(self, ctx: Context):
        uptime = human_timedelta(self.bot.uptime, accuracy=None, brief=True, suffix=False)

        memory_usage = self.process.memory_full_info().uss / 1024**2
        cpu_usage = self.process.cpu_percent() / psutil.cpu_count()

        shard: discord.ShardInfo = self.bot.get_shard(ctx.guild.shard_id)  # type: ignore  # will never be None

        return await ctx.send(
            embed=embed(
                title=f"{self.bot.user.name} - About",
                thumbnail=self.bot.user.display_avatar.url,
                author_icon=self.bot.owner.display_avatar.url,
                author_name=str(self.bot.owner),
                footer="Made with ❤️ and discord.py!",
                fieldstitle=[
                    "Servers joined",
                    "Latency",
                    "Shards",
                    "Uptime",
                    "CPU/RAM",
                    "Existed since"],
                fieldsval=[
                    len(self.bot.guilds),
                    f"{(shard.latency if ctx.guild else self.bot.latency)*1000:,.0f} ms",
                    self.bot.shard_count,
                    uptime,
                    f'{memory_usage:.2f} MiB\n{cpu_usage:.2f}% CPU',
                    f"<t:{int(self.bot.user.created_at.timestamp())}:D>"],
            )
        )

    @commands.hybrid_command(name="ping")
    async def ping(self, ctx: Context):
        """Pong!"""
        shard = ctx.guild and self.bot.get_shard(ctx.guild.shard_id)
        latency = f"{shard.latency*1000:,.0f}" if shard is not None else f"{self.bot.latency*1000:,.0f}"
        await ctx.send(f"Ping!\n⏳ API is {latency}ms")

    def get_bot_uptime(self, *, brief: bool = False) -> str:
        return human_timedelta(self.bot.uptime, accuracy=None, brief=brief, suffix=False)

    @commands.hybrid_command(name="uptime")
    async def uptime(self, ctx: Context):
        """Uptime!"""
        await ctx.send(f"Uptime: **{self.get_bot_uptime}**")

    @cached_property
    def link(self):
        return oauth_url(self.bot.user.id, permissions=INVITE_PERMISSIONS, scopes=["bot", "applications.commands"])

    @commands.hybrid_command("invite", help="Get the invite link to add me to your server")
    async def _invite(self, ctx: Context):
        await ctx.send(embed=embed(title="Invite me :)"), view=InviteButtons(self.link))


async def setup(bot: AutoShardedBot):
    await bot.add_cog(Info(bot))
