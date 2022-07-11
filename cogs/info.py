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

SUPPORT_SERVER_ID = 991443052625412116
SUPPORT_SERVER_INVITE = "https://discord.gg/PSgfZ5MzTg"

INVITE_PERMISSIONS = discord.Permissions(
    send_messages=True,
    embed_links=True,
)


class Info(commands.Cog):
    def __init__(self, bot: AutoShardedBot):
        self.bot: AutoShardedBot = bot
        self.process = psutil.Process()

    def __repr__(self) -> str:
        return f"<cogs.{self.__cog_name__}>"

    async def bot_check(self, ctx: Context) -> bool:
        if ctx.guild is None:
            return True

        return await commands.bot_has_permissions(
                send_messages=True,
                embed_links=True,
        ).predicate(ctx)

    @commands.hybrid_command(name="about", aliases=["info"])
    async def info(self, ctx: Context):
        """Displays some information about myself :)"""
        uptime = human_timedelta(self.bot.uptime, accuracy=None, brief=True, suffix=False)

        memory_usage = self.process.memory_full_info().uss / 1024**2
        cpu_usage = self.process.cpu_percent() / psutil.cpu_count()

        shard: discord.ShardInfo = self.bot.get_shard(ctx.guild.shard_id)  # type: ignore  # will never be None

        return await ctx.send(
            embed=embed(
                title=ctx.lang["info"]["info"]["title"].format(self.bot.user.name),
                thumbnail=self.bot.user.display_avatar.url,
                author_icon=self.bot.owner.display_avatar.url,
                author_name=str(self.bot.owner),
                footer=ctx.lang["info"]["info"]["footer"],
                fieldstitle=ctx.lang["info"]["info"]["titles"],
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
        await ctx.send(ctx.lang["info"]["ping"].format(latency), ephemeral=True)

    @cached_property
    def link(self):
        return oauth_url(self.bot.user.id, permissions=INVITE_PERMISSIONS, scopes=["bot", "applications.commands"])

    @commands.hybrid_command("invite")
    async def invite(self, ctx: Context):
        """Get the invite link to add me to your server"""
        view = discord.ui.View()
        view.add_item(discord.ui.Button(emoji="\N{HEAVY PLUS SIGN}", label=ctx.lang["info"]["invite"], style=discord.ButtonStyle.link, url=self.link))
        await ctx.send(embed=embed(title=ctx.lang["info"]["invite"]), view=view, ephemeral=True)

    @commands.hybrid_command(name="support")
    async def support(self, ctx: Context):
        """Get an invite link to my support server"""
        await ctx.send(SUPPORT_SERVER_INVITE, ephemeral=True)

    @commands.hybrid_command(name="languages")
    async def languages(self, ctx: Context):
        """Get a list of languages I support"""
        crowdin = discord.ui.View()
        crowdin.add_item(discord.ui.Button(label=ctx.lang["info"]["languages"]["page"], url="https://crwd.in/goal-tracker-discord-bot"))
        await ctx.send(ctx.lang["info"]["languages"]["list"].format(self.bot.user.display_name, '\n'.join([n['_lang_name'] for n in self.bot.language_files.values()])), view=crowdin)


async def setup(bot: AutoShardedBot):
    await bot.add_cog(Info(bot))
