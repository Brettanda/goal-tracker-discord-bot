"""
Stolen and modified from R. Danny.
:)

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any, Optional, Union

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from index import AutoShardedBot


class ConfirmationView(discord.ui.View):
    def __init__(self, *, timeout: float, author_id: int, reacquire: bool, ctx: Context, delete_after: bool) -> None:
        super().__init__(timeout=timeout)
        self.value: Optional[bool] = None
        self.delete_after: bool = delete_after
        self.author_id: int = author_id
        self.ctx: Context = ctx
        self.reacquire: bool = reacquire
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.author_id:
            return True
        else:
            await interaction.response.send_message('This confirmation dialog is not for you.', ephemeral=True)
            return False

    async def on_timeout(self) -> None:
        # if self.reacquire:
        #     await self.ctx.acquire()
        if self.delete_after and self.message:
            await self.message.delete()

    @discord.ui.button(emoji="\N{HEAVY CHECK MARK}", label='Confirm', custom_id="confirmation_true", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        if self.delete_after:
            await interaction.delete_original_message()
        self.stop()

    @discord.ui.button(emoji="\N{HEAVY MULTIPLICATION X}", label='Cancel', custom_id="confirmation_false", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        if self.delete_after:
            await interaction.delete_original_message()
        self.stop()


class Context(commands.Context):
    channel: Union[discord.VoiceChannel, discord.TextChannel, discord.Thread, discord.DMChannel]
    prefix: str
    command: commands.Command[Any, ..., Any]
    bot: AutoShardedBot

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return "<Context>"

    @discord.utils.cached_property
    def replied_reference(self) -> Optional[discord.MessageReference]:
        ref = self.message.reference
        if ref and ref.resolved and isinstance(ref.resolved, discord.Message):
            return ref.resolved.to_reference()
        return None

    @property
    def session(self) -> ClientSession:
        return self.bot.session

    async def prompt(
          self,
          message: str,
          *,
          timeout: float = 60.0,
          delete_after: bool = True,
          reacquire: bool = True,
          author_id: Optional[int] = None,
          **kwargs
    ) -> Optional[bool]:
        """An interactive reaction confirmation dialog.

        Parameters
        -----------
        message: str
            The message to show along with the prompt.
        timeout: float
            How long to wait before returning.
        delete_after: bool
            Whether to delete the confirmation message after we're done.
        reacquire: bool
            Whether to release the database connection and then acquire it
            again when we're done.
        author_id: Optional[int]
            The member who should respond to the prompt. Defaults to the author of the
            Context's message.
        Returns
        --------
        Optional[bool]
            ``True`` if explicit confirm,
            ``False`` if explicit deny,
            ``None`` if deny due to timeout
        """
        author_id = author_id or self.author.id
        if self.author.bot and author_id == 892865928520413245:
            # unit testing bots can't use interactions :(
            return True
        view = ConfirmationView(
            timeout=timeout,
            delete_after=delete_after,
            reacquire=reacquire,
            ctx=self,
            author_id=author_id
        )
        # kwargs["embed"] = kwargs.pop("embed", embed(title=message))
        view.message = await self.send(view=view, **kwargs)
        await view.wait()
        return view.value

    async def safe_send(self, content: str, *, escape_mentions=True, **kwargs: Any) -> discord.Message:
        if escape_mentions:
            content = discord.utils.escape_mentions(content)

        if len(content) > 2000:
            fp = io.BytesIO(content.encode())
            kwargs.pop("file", None)
            return await self.send(file=discord.File(fp, filename="message_too_long.txt"), **kwargs)
        else:
            return await self.send(content, **kwargs)


class GuildContext(Context):
    author: discord.Member
    guild: discord.Guild
    channel: Union[discord.VoiceChannel, discord.TextChannel, discord.Thread]
    me: discord.Member
    prefix: str
