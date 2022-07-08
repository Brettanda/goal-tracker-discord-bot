"""
Stolen and modified from R. Danny.
:)

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time as _time
import traceback
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Union

import discord
from discord.ext import commands
from typing_extensions import Annotated
from utils.colours import MessageColors
from utils.context import Context
from utils.embed import embed
from utils import time

if TYPE_CHECKING:
    from index import AutoShardedBot
    from typing_extensions import Self

log = logging.getLogger(__name__)


class PerformanceMocker:
    """A mock object that can also be used in await expressions."""

    def __init__(self):
        self.loop = asyncio.get_running_loop()

    def permissions_for(self, obj: Any) -> discord.Permissions:
        # Lie and say we don't have permissions to embed
        # This makes it so pagination sessions just abruptly end on __init__
        # Most checks based on permission have a bypass for the owner anyway
        # So this lie will not affect the actual command invocation.
        perms = discord.Permissions.all()
        perms.administrator = False
        perms.embed_links = False
        perms.add_reactions = False
        return perms

    def __getattr__(self, attr: str) -> Self:
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Self:
        return self

    def __repr__(self) -> str:
        return '<PerformanceMocker>'

    def __await__(self):
        future: asyncio.Future[Self] = self.loop.create_future()
        future.set_result(self)
        return future.__await__()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> Self:
        return self

    def __len__(self) -> int:
        return 0

    def __bool__(self) -> bool:
        return False


class RawEmoji(commands.Converter):
    reg = re.compile(r"""[^a-zA-Z0-9\s.!@#$%^&*()_+-+,./<>?;':"{}[\]\\|]{1}""")

    async def convert(self, ctx: Context, argument: str):
        try:
            return await commands.EmojiConverter().convert(ctx, argument)
        except commands.BadArgument:
            try:
                emoji = self.reg.match(argument)
                return emoji and emoji[0].strip(" ")
            except TypeError:
                raise commands.BadArgument(f'Could not find an emoji by name {argument!r}.')


class Dev(commands.Cog, command_attrs=dict(hidden=True)):
    """Commands used by and for the developer"""

    def __init__(self, bot: AutoShardedBot) -> None:
        self.bot: AutoShardedBot = bot
        self._last_result: Optional[Any] = None

    def __repr__(self) -> str:
        return f"<cogs.Dev owner={self.bot.owner_id}>"

    async def cog_check(self, ctx: Context) -> bool:
        if not await self.bot.is_owner(ctx.author):
            raise commands.NotOwner()
        return True

    async def cog_command_error(self, ctx: Context, error: commands.CommandError):
        ignore = (commands.MissingRequiredArgument, commands.BadArgument,)
        if isinstance(error, ignore):
            return

        if isinstance(error, commands.CheckFailure):
            log.warning("Someone found a dev command")
        else:
            await ctx.send(f"```py\n{error}\n```")

    def cleanup_code(self, content: str):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith('```') and content.endswith('```'):
            return '\n'.join(content.split('\n')[1:-1])

        # remove `foo`
        return content.strip('` \n')

    async def run_process(self, command: str) -> List[str]:
        try:
            process = await asyncio.create_subprocess_shell(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = await process.communicate()
        except NotImplementedError:
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = await self.bot.loop.run_in_executor(None, process.communicate)

        return [output.decode() for output in result]

    @commands.group(name="dev", invoke_without_command=True, case_insensitive=True)
    async def dev(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @dev.command("chain")
    async def dev_chain(self, ctx: Context, *, commands: str):
        commandlist = commands.split("&&")
        await ctx.message.add_reaction("\N{OK HAND SIGN}")

        for command in commandlist:
            msg = copy.copy(ctx.message)
            msg.content = ctx.prefix + command

            new_ctx = await self.bot.get_context(msg, cls=type(ctx))
            # new_ctx._db = ctx._db

            await new_ctx.reinvoke()

    @dev.command(name="say", rest_is_raw=True,)
    async def say(self, ctx: Context, channel: Optional[discord.TextChannel] = None, *, say: str):
        new_channel = channel or ctx.channel
        try:
            await ctx.message.delete()
        except BaseException:
            pass
        await new_channel.send(f"{say}")

    @dev.command(name="edit")
    async def edit(self, ctx: Context, message: discord.Message, *, edit: str):
        try:
            await ctx.message.delete()
        except BaseException:
            pass
        await message.edit(content=edit)

    @dev.command(name="react")
    async def react(self, ctx: Context, messages: commands.Greedy[discord.Message], reactions: Annotated[Sequence[discord.Emoji], commands.Greedy[RawEmoji]]):
        try:
            await ctx.message.delete()
        except BaseException:
            pass
        for msg in messages:
            for reaction in reactions:
                try:
                    await msg.add_reaction(reaction)
                except BaseException:
                    pass

    @dev.command(name="restart")
    async def restart(self, ctx: Context, force: bool = False):
        stat = await ctx.reply(embed=embed(title="Pending"))
        if len(self.bot.voice_clients) > 0 and force is False:
            await stat.edit(embed=embed(title=f"{len(self.bot.voice_clients)} guilds are playing music"))
            while len(self.bot.voice_clients) > 0:
                await stat.edit(embed=embed(title=f"{len(self.bot.voice_clients)} guilds are playing music"))
                await asyncio.sleep(1)
            await stat.edit(embed=embed(title=f"{len(self.bot.voice_clients)} guilds are playing music"))
        # if len(songqueue) is 0 or force is True:
        try:
            wait = 5
            while wait > 0:
                await stat.edit(embed=embed(title=f"Restarting in {wait} seconds"))
                await asyncio.sleep(1)
                wait = wait - 1
        finally:
            await ctx.message.delete()
            await stat.delete()
            stdout, stderr = await self.run_process("systemctl daemon-reload && systemctl restart goal-tracker.service")
            await ctx.send(f"```sh\n{stdout}\n{stderr}```")

    @dev.group(name="reload", invoke_without_command=True)
    async def reload(self, ctx: Context, *, modules: str):
        mods = [mod.strip("\"") for mod in modules.split(" ")]
        ret = []
        for module in mods:
            if module.startswith("cogs"):
                ret.append((0, module.replace("/", ".")))  # root.count("/") - 1 # if functions moves to cog folder
            elif module.startswith("functions"):
                ret.append((1, module.replace("/", ".")))
            elif module.startswith("spice/cogs") or module.startswith("spice.cogs"):
                ret.append((0, module.replace("/", ".")))
            elif module.startswith("spice/functions") or module.startswith("spice.functions"):
                ret.append((1, module.replace("/", ".")))
            elif module.replace("/", ".") in sys.modules:
                ret.append((1, module.replace("/", ".")))
            elif self.bot.get_cog(module.capitalize()) is not None:
                ret.append((0, "cogs." + module.replace("/", ".")))
            else:
                command = self.bot.get_command(module)
                if command:
                    cog_name: str = command.cog_name  # type: ignore
                    ret.append((0, "cogs." + cog_name.lower()))
                else:
                    ret.append((1, module.replace("/", ".")))

        statuses = []
        for is_func, module in ret:
            if is_func:
                try:
                    actual_module = sys.modules[module]
                except KeyError:
                    statuses.append((":zzz:", module))
                else:
                    try:
                        importlib.reload(actual_module)
                    except Exception:
                        statuses.append((":x:", module))
                    else:
                        statuses.append((":white_check_mark:", module))
            else:
                try:
                    await self.reload_or_load_extention(module)
                except Exception:
                    statuses.append((":x:", module))
                else:
                    statuses.append((":white_check_mark:", module))

        await ctx.send(embed=embed(title="Reloading modules", description="\n".join(f"{status} {module}" for status, module in statuses)))

    _GIT_PULL_REGEX = re.compile(r'\s*(?P<filename>.+?)\s*\|\s*[0-9]+\s*[+-]+')

    def modules_from_git(self, output):
        files = self._GIT_PULL_REGEX.findall(output)
        ret = []
        for file in files:
            root, ext = os.path.splitext(file)
            if ext != ".py":
                continue

            if root.startswith("cogs"):
                ret.append((0, root.replace("/", ".")))  # root.count("/") - 1 # if functions moves to cog folder
            elif root.startswith("utils"):
                ret.append((1, root.replace("/", ".")))

        ret.sort(reverse=True)
        return ret

    async def reload_or_load_extention(self, module):
        try:
            await self.bot.reload_extension(module)
        except commands.ExtensionNotLoaded:
            await self.bot.load_extension(module)

    @reload.command(name="all")
    async def reload_all(self, ctx: Context):
        async with ctx.typing():
            stdout, stderr = await self.run_process("git pull")

        confirm = await ctx.prompt("Would you like to run pip install upgrade?")
        if confirm:
            pstdout, pstderr = await self.run_process("python -m pip install --upgrade pip && python -m pip install -r requirements.txt --upgrade --no-cache-dir")
            if pstderr:
                log.error(pstderr)
            await ctx.safe_send(pstdout)

        modules = self.modules_from_git(stdout)
        mods_text = "\n".join(f"{index}. {module}" for index, (_, module) in enumerate(modules, start=1))
        confirm = await ctx.prompt(f"This will update the following modules, are you sure?\n\n```\n{mods_text or 'NULL'}\n```")
        if not confirm:
            return await ctx.send("Aborting.")

        statuses = []
        for is_func, module in modules:
            if is_func:
                try:
                    actual_module = sys.modules[module]
                except KeyError:
                    statuses.append((":zzz:", module))
                else:
                    try:
                        importlib.reload(actual_module)
                    except Exception:
                        statuses.append((":x:", module))
                    else:
                        statuses.append((":white_check_mark:", module))
            else:
                try:
                    await self.reload_or_load_extention(module)
                except commands.ExtensionError:
                    statuses.append((":x:", module))
                else:
                    statuses.append((":white_check_mark:", module))

        await self.bot.tree.sync()
        await ctx.send(embed=embed(title="Reloading modules", description="\n".join(f"{status} {module}" for status, module in statuses)))
        # async with ctx.typing():
        #   await self.bot.reload_cogs()
        # await ctx.reply(embed=embed(title="All cogs have been reloaded"))

    @reload.command("slash")
    async def reload_slash(self, ctx: Context):
        await self.bot.tree.sync()
        await ctx.send(embed=embed(title="Slash commands reloaded"))

    @reload.command("module")
    async def reload_module(self, ctx: Context, *, module: str):
        try:
            importlib.reload(sys.modules[module])
        except KeyError:
            return await ctx.reply(embed=embed(title=f"Module {module} not found", color=MessageColors.error()))
        except Exception:
            return await ctx.reply(embed=embed(title=f"Failed to reload module {module}", color=MessageColors.error()))
        else:
            await ctx.reply(embed=embed(title=f"Reloaded module {module}"))

    @dev.command(name="load")
    async def load(self, ctx: Context, command: str):
        async with ctx.typing():
            path = "cogs."
            await self.bot.load_extension(f"{path}{command.lower()}")
        await ctx.reply(embed=embed(title=f"Cog *{command}* has been loaded"))

    @dev.command(name="unload")
    async def unload(self, ctx: Context, command: str):
        async with ctx.typing():
            path = "cogs."
            await self.bot.unload_extension(f"{path}{command.lower()}")
        await ctx.reply(embed=embed(title=f"Cog *{command}* has been unloaded"))

    # @reload.error
    # @load.error
    # @unload.error
    # async def reload_error(self, ctx, error):
    #   if not isinstance(error, commands.NotOwner):
    #     await ctx.reply(embed=embed(title=f"Failed to reload *{str(''.join(ctx.message.content.split(ctx.prefix+ctx.command.name+' ')))}*", color=MessageColors.error()))
    #     print(error)
    #     log.error(error)

    @dev.command(name="block")
    async def block(self, ctx: Context, object_id: int):
        await self.bot.blacklist.put(object_id, True)
        await ctx.send(embed=embed(title=f"{object_id} has been blocked"))

    @dev.command(name="unblock")
    async def unblock(self, ctx: Context, object_id: int):
        try:
            await self.bot.blacklist.remove(object_id)
        except KeyError:
            pass
        await ctx.send(embed=embed(title=f"{object_id} has been unblocked"))

    @dev.command(name="log")
    async def log(self, ctx: Context):
        async with ctx.typing():
            thispath = os.getcwd()
            if "\\" in thispath:
                seperator = "\\\\"
            else:
                seperator = "/"
            shutil.copy(f"{thispath}{seperator}logging.log", f"{thispath}{seperator}logging-send.log")
        await ctx.reply(file=discord.File(fp=f"{thispath}{seperator}logging-send.log", filename="logging.log"))

    @dev.command("time")
    async def time(self, ctx: Context, *, _time: Annotated[time.FriendlyTimeResult, time.UserFriendlyTime(commands.clean_content, default="...")]):
        await ctx.send(f"{time.format_dt(_time.dt)} ({time.format_dt(_time.dt, style='R')}) `{time.format_dt(_time.dt)}` `{_time.dt.tzname()}` `{ctx._timezone_name}` {ctx.message.created_at.astimezone(ctx.timezone).strftime('%I:%M:%S %p')}")

    @dev.command(name="sudo")
    async def sudo(self, ctx: Context, channel: Optional[discord.TextChannel], user: Union[discord.Member, discord.User], *, command: str):
        msg = copy.copy(ctx.message)
        new_channel = channel or ctx.channel
        msg.channel = new_channel
        msg.author = user
        msg.content = ctx.prefix + command
        new_ctx = await self.bot.get_context(msg, cls=type(ctx))
        await self.bot.invoke(new_ctx)

    @dev.command(name="do", aliases=["repeat"])
    async def do(self, ctx: Context, times: int, *, command: str):
        msg = copy.copy(ctx.message)
        msg.content = ctx.prefix + command

        new_ctx = await self.bot.get_context(msg, cls=type(ctx))
        # new_ctx._db = ctx._db

        for i in range(times):
            await new_ctx.reinvoke()

    @dev.command(name="eval")
    async def _eval(self, ctx: Context, *, body: str):
        """Evaluates a code"""

        env = {
            'bot': self.bot,
            'ctx': ctx,
            'embed': embed,
            'channel': ctx.channel,
            'author': ctx.author,
            'guild': ctx.guild,
            'message': ctx.message,
            'self': self,
            '_': self._last_result
        }

        env.update(globals())

        body = self.cleanup_code(body)
        stdout = io.StringIO()

        to_compile = f'async def func():\n{textwrap.indent(body, "  ")}'

        try:
            exec(to_compile, env)
        except Exception as e:
            return await ctx.send(f'```py\n{e.__class__.__name__}: {e}\n```')

        func = env['func']
        try:
            # with redirect_stdout(stdout):
            ret = await func()
        except Exception:
            value = stdout.getvalue()
            await ctx.send(f'```py\n{value}{traceback.format_exc()}\n```')
        else:
            value = stdout.getvalue()
            try:
                await ctx.message.add_reaction('\u2705')
            except BaseException:
                pass

            if ret is None:
                if value:
                    await ctx.send(f'```py\n{value}\n```')
            else:
                self._last_result = ret
                await ctx.send(f'```py\n{value}{ret}\n```')

    @dev.command("perf")
    async def perf(self, ctx: Context, *, command: str):
        msg = copy.copy(ctx.message)
        msg.content = ctx.prefix + command

        new_ctx = await self.bot.get_context(msg, cls=type(ctx))
        # new_ctx._db = PerformanceMocker()

        new_ctx._state = PerformanceMocker()  # type: ignore
        new_ctx.channel = PerformanceMocker()  # type: ignore

        if new_ctx.command is None:
            return await ctx.send("Command not found.")

        start = _time.perf_counter()
        try:
            await new_ctx.command.invoke(new_ctx)
        except commands.CommandError:
            end = _time.perf_counter()
            success = False
            try:
                await ctx.send(f"```py\n{traceback.format_exc()}\n```")
            except discord.HTTPException:
                pass
        else:
            end = _time.perf_counter()
            success = True

        lookup = {
            True: ":white_check_mark:",
            False: ":x:",
            None: ":zzz:"
        }

        await ctx.send(f"Status: {lookup.get(success, ':x:')} Time: {(end - start) * 1000:.2f}ms")


async def setup(bot):
    await bot.add_cog(Dev(bot))
