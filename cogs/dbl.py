from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Optional, Union

import discord
from discord.ext import commands, tasks
from topgg.webhook import WebhookManager

from utils.context import Context
from utils import cache, time
from utils.embed import embed
if TYPE_CHECKING:
    from cogs.reminder import Timer
    from index import AutoShardedBot

log = logging.getLogger(__name__)

VOTE_ROLE = 995093840702754819
SUPPORT_SERVER_ID = 991443052625412116
VOTE_URL = "https://top.gg/bot/990139482273628251/vote"


# TODO: Add support for voting on discords.com and discordbotlist.com https://cdn.discordapp.com/attachments/892840236781015120/947203621358010428/unknown.png


class TopGG(commands.Cog):
    """Voting for Goal Tracker on Top.gg really helps with getting Goal Tracker to more people because the more votes a bot has the higher ranking it gets.

      To get Goal Tracker higher in the rankings you can vote here
      [top.gg/bot/990139482273628251/vote](https://top.gg/bot/990139482273628251/vote)

      When voting you will receive some cool perks currently including:

        - Better rate limits when chatting with Goal Tracker"""

    def __init__(self, bot: AutoShardedBot):
        self.bot: AutoShardedBot = bot

        self._current_len_guilds = len(self.bot.guilds)

    def __repr__(self) -> str:
        return f"<cogs.{self.__cog_name__}>"

    async def cog_load(self):
        if "dev" in self.bot.user.display_name.lower():
            return
        if not hasattr(self.bot, "topgg_webhook"):
            self.bot.topgg_webhook = WebhookManager(self.bot).dbl_webhook("/dblwebhook", os.environ["DBLWEBHOOKPASS"])
            self.bot.topgg_webhook.run(5000)
        self._update_stats_loop.start()

    async def cog_unload(self):
        self._update_stats_loop.cancel()

    @cache.cache(ignore_kwargs=True)
    async def user_has_voted(self, user_id: int, *, connection=None) -> bool:
        query = """SELECT id
              FROM reminders
              WHERE event = 'vote'
              AND extra #>> '{args,0}' = $1
              ORDER BY expires
              LIMIT 1;"""
        conn = connection or self.bot.pool
        record = await conn.fetchrow(query, str(user_id))
        return True if record else False

    @tasks.loop(minutes=10.0)
    async def _update_stats_loop(self):
        if self._current_len_guilds != len(self.bot.guilds):
            await self.update_stats()

    @commands.hybrid_command()
    async def vote(self, ctx: Context):
        """Get the link to vote for me on Top.gg"""
        query = """SELECT id,expires
              FROM reminders
              WHERE event = 'vote'
              AND extra #>> '{args,0}' = $1
              ORDER BY expires
              LIMIT 1;"""
        record = await ctx.db.fetchrow(query, str(ctx.author.id))
        expires = record["expires"] if record else None
        vote_message = f"Your next vote time is: {time.format_dt(expires, style='R')}" if expires is not None else "You can vote now"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Vote link", url=VOTE_URL, style=discord.ButtonStyle.url))
        await ctx.reply(embed=embed(title="Voting", description=f"{vote_message}\n\nWhen you vote you get:", fieldstitle=["Better rate limiting"], fieldsval=["60 messages/12 hours instead of 30 messages/12 hours."]), view=view)

    @commands.command(extras={"examples": ["test", "upvote"]}, hidden=True)
    @commands.is_owner()
    async def vote_fake(self, ctx: Context, user: Optional[Union[discord.User, discord.Member]] = None, _type: Optional[str] = "test"):
        user = user or ctx.author
        data = {
            "type": _type,
            "user": str(user.id),
            "query": {},
            "bot": self.bot.user.id,
            "is_weekend": False
        }
        self.bot.dispatch("dbl_vote", data)
        await ctx.send("Fake vote sent")

    async def update_stats(self):
        await self.bot.wait_until_ready()
        self._current_len_guilds = len(self.bot.guilds)
        log.info("Updating DBL stats")
        try:
            tasks = [self.bot.session.post(
                f"https://top.gg/api/bots/{self.bot.user.id}/stats",
                headers={"Authorization": self.bot.config.tokentop},
                json={
                    "server_count": len(self.bot.guilds),
                    "shard_count": self.bot.shard_count,
                }
            ),
                self.bot.session.post(
                f"https://discord.bots.gg/api/v1/bots/{self.bot.user.id}/stats",
                headers={"Authorization": self.bot.config.tokendbotsgg},
                json={
                    "guildCount": len(self.bot.guilds),
                    "shardCount": self.bot.shard_count,
                }
            ),
                self.bot.session.post(
                f"https://discordbotlist.com/api/v1/bots/{self.bot.user.id}/stats",
                headers={"Authorization": f'Bot {self.bot.config.tokendbl}'},
                json={
                    "guilds": len(self.bot.guilds),
                    "users": len(self.bot.users),
                }
            )]
            await asyncio.gather(*tasks)
        except Exception as e:
            log.exception('Failed to post server count\n?: ?', type(e).__name__, e)
        else:
            log.info("Server count posted successfully")

    @commands.Cog.listener()
    async def on_vote_timer_complete(self, timer: Timer):
        user_id = timer.args[0]
        await self.bot.wait_until_ready()

        self.user_has_voted.invalidate(self, user_id)

        support_server = self.bot.get_guild(SUPPORT_SERVER_ID)
        role_removed = False
        if support_server:
            member = await self.bot.get_or_fetch_member(support_server, user_id)
            if member is not None:
                try:
                    await member.remove_roles(discord.Object(id=VOTE_ROLE), reason="Top.gg vote expired")
                except discord.HTTPException:
                    pass
                else:
                    role_removed = True
        reminder_sent = False
        try:
            private = await self.bot.fetch_user(user_id)
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Vote link", url=VOTE_URL, style=discord.ButtonStyle.url))
            await private.send(embed=embed(title="Your vote time has refreshed.", description="You can now vote again!"), view=view)
        except discord.HTTPException:
            pass
        else:
            reminder_sent = True

        log.info(f"Vote expired for {user_id}. Reminder sent: {reminder_sent}, role removed: {role_removed}")

    # @commands.Cog.listener()
    # async def on_dbl_test(self, data):
    #   log.info(f"Testing received, {data}")
    #   time = datetime.datetime.now() - datetime.timedelta(hours=11, minutes=59)
    #   await self.on_dbl_vote(data, time)

    @commands.Cog.listener()
    async def on_dbl_vote(self, data: dict):
        fut = time.FutureTime("12h", now=discord.utils.utcnow())
        _type, user = data.get("type", None), data.get("user", None)
        log.info(f'Received an upvote, {data}')
        if _type == "test":
            fut = time.FutureTime("2m", now=discord.utils.utcnow())
        if user is None:
            return
        reminder = self.bot.reminder
        if reminder is None:
            return
        await reminder.create_timer(fut.dt, "vote", user, created=discord.utils.utcnow())
        self.user_has_voted.invalidate(self, int(user, base=10))
        if _type == "test" or int(user, base=10) not in (215227961048170496, 813618591878086707):
            support_server = self.bot.get_guild(SUPPORT_SERVER_ID)
            if not support_server:
                return

            member = await self.bot.get_or_fetch_member(support_server, user)
            if member is not None:
                try:
                    await member.add_roles(discord.Object(id=VOTE_ROLE), reason="Voted on Top.gg")
                except discord.HTTPException:
                    pass
                else:
                    log.info(f"Added vote role to {member.id}")
            log.info(f"Somebody Voted - {_type} (ID: {user})")


async def setup(bot: AutoShardedBot):
    await bot.add_cog(TopGG(bot))
