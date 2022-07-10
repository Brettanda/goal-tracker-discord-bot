"""
Stolen and modified from R. Danny.
:)

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING, Any, Literal, Optional, Union

import parsedatetime as pdt
import discord
from dateutil.relativedelta import relativedelta
from discord import app_commands
from .fuzzy import autocomplete
from discord.ext import commands

from .formats import human_join, plural

# Monkey patch mins and secs into the units
units = pdt.pdtLocales['en_US'].units
units['minutes'].append('mins')
units['seconds'].append('secs')

if TYPE_CHECKING:
    from typing_extensions import Self

    from .context import Context


class Aware:
    """timezone aware"""
    def __new__(cls, *args, **kwargs):
        if 'tzinfo' not in kwargs:
            raise TypeError('tzinfo not passed into Aware Datetime (ADT) object')
        return super().__new__(cls, *args, **kwargs)


class Naive:
    """non-aware"""
    def __new__(cls, *args, **kwargs):
        if 'tzinfo' in kwargs:
            raise TypeError('tzinfo passed into Naive Datetime (NDT) object')
        return super().__new__(cls, *args, **kwargs)


class ADT(datetime.datetime, Aware):
    """timezone aware datetime"""
    @classmethod
    def combine(cls, date: datetime.date, time: AT, tzinfo: datetime.tzinfo = None) -> Self:
        return super().combine(date, time, tzinfo)  # type: ignore


class AT(datetime.time, Aware):
    """timezone aware time"""
    pass


class NDT(datetime.datetime, Naive):
    """non-aware datetime"""
    @classmethod
    def combine(cls, date: datetime.date, time: NT) -> Self:
        return super().combine(date, time)  # type: ignore


class NT(datetime.time, Naive):
    """non-aware time"""
    pass


def human_timedelta(dt: datetime.datetime, *, source: Optional[datetime.datetime] = None, accuracy: Optional[int] = 3, brief: bool = False, suffix: bool = True) -> str:
    now = source or datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)

    # This implementation uses relativedelta instead of the much more obvious
    # divmod approach with seconds because the seconds approach is not entirely
    # accurate once you go over 1 week in terms of accuracy since you have to
    # hardcode a month as 30 or 31 days.
    # A query like "11 months" can be interpreted as "!1 months and 6 days"
    if dt > now:
        delta = relativedelta(dt, now)
        output_suffix = ''
    else:
        delta = relativedelta(now, dt)
        output_suffix = ' ago' if suffix else ''

    attrs = [
        ('year', 'y'),
        ('month', 'mo'),
        ('day', 'd'),
        ('hour', 'h'),
        ('minute', 'm'),
        ('second', 's'),
    ]

    output = []
    for attr, brief_attr in attrs:
        elem = getattr(delta, attr + 's')
        if not elem:
            continue

        if attr == 'day':
            weeks = delta.weeks
            if weeks:
                elem -= weeks * 7
                if not brief:
                    output.append(format(plural(weeks), 'week'))
                else:
                    output.append(f'{weeks}w')

        if elem <= 0:
            continue

        if brief:
            output.append(f'{elem}{brief_attr}')
        else:
            output.append(format(plural(elem), attr))

    if accuracy is not None:
        output = output[:accuracy]

    if len(output) == 0:
        return 'now'
    else:
        if not brief:
            return human_join(output, final='and') + output_suffix
        else:
            return ' '.join(output) + output_suffix


expected_intervals = [
    *[f"{plural(x):minute}" for x in range(15, 60)],
    *[f"{plural(x):hour}" for x in range(1, 24)],
    *[f"{plural(x):day}" for x in range(1, 31)],
    *[f"{plural(x):week}" for x in range(1, 5)],
    *[f"{plural(x):month}" for x in range(1, 12)],
    # *[f"{plural(x):year}" for x in range(1, 5)]
]


class Interval(commands.Converter, app_commands.Transformer):
    # (?:(?P<years>[0-9])\s?(?:years?|y))?             # e.g. 2y
    compiled = re.compile(r"""(?:(?P<months>[0-9]{1,2})\s?(?:months?|mo))?     # e.g. 2months
                             (?:(?P<weeks>[0-9]{1,4})\s?(?:weeks?|w))?        # e.g. 10w
                             (?:(?P<days>[0-9]{1,5})\s?(?:days?|d))?          # e.g. 14 d
                             (?:(?P<hours>[0-9]{1,5})\s?(?:hours?|h))?        # e.g. 12h
                             (?:(?P<minutes>[0-9]{1,5})\s?(?:minutes?|m))?    # e.g. 10m
                          """, re.VERBOSE)

    def __init__(self, argument: str, *, _min: int = 0):
        match = self.compiled.fullmatch(argument)
        if match is None or not match.group(0):
            raise commands.BadArgument('invalid time provided')

        data = {k: int(v) for k, v in match.groupdict(default=0).items()}
        now = discord.utils.utcnow()
        interval = (now + relativedelta(**data)) - now
        if interval.total_seconds() < _min:
            raise commands.BadArgument(f'value provided is too small. Min is {_min} seconds.')
        self.interval = interval

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} {self.interval}>'

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        return cls(argument, _min=15 * 60)

    @classmethod
    async def transform(cls, interaction: discord.Interaction, argument: str) -> Self:
        return cls(argument, _min=15 * 60)

    @classmethod
    async def autocomplete(cls, interaction: discord.Interaction, value: int | float | str) -> list[app_commands.Choice[int | float | str]]:
        intervals = sorted(
            expected_intervals,
            key=lambda x: int(x.split(' ')[0])
        )
        choices = [app_commands.Choice(name=i, value=i) for i in intervals]
        return autocomplete(choices, str(value))


class TOD:
    """Time of Day"""

    def __init__(self, twenty_four_hour: bool = False, *, hour: int, minute: int = 0):
        if hour > 24 or hour < 1:
            raise ValueError('hour must be between 0 and 23')
        if minute > 59 or minute < 0:
            raise ValueError('minute must be between 0 and 59')
        self.twenty_four_hour = twenty_four_hour
        self.hour = hour
        self.minute = minute

    @property
    def am_or_pm(self) -> Literal["AM", "PM"]:
        return "PM" if self.hour >= 12 else "AM"

    def __str__(self) -> str:
        if self.twenty_four_hour:
            return f"{self.hour:02d}:{self.minute:02d}"
        hour = self.hour % 12
        hour = hour if hour != 0 else 12
        if self.minute == 0:
            return f"{hour} {self.am_or_pm}"
        return f"{hour}:{self.minute:02d} {self.am_or_pm}"


expected_times_of_day = [
    TOD(hour=hour, minute=minute)
    for minute in range(0, 60)
    for hour in range(1, 24)
]


class TimeOfDay(commands.Converter, app_commands.Transformer):
    calendar = pdt.Calendar(version=pdt.VERSION_CONTEXT_STYLE)

    def __init__(self, argument: str, *, now: ADT = None, timezone: datetime.tzinfo = datetime.timezone.utc):
        more_now: ADT = now or discord.utils.utcnow().astimezone(timezone)  # type: ignore
        dt, status = self.calendar.parseDT(argument, sourceTime=more_now, tzinfo=timezone)
        if not status.hasTime:
            raise commands.BadArgument('invalid time provided, try e.g. "2pm" or "1 hour from now"')

        self.time: AT = dt.time().replace(tzinfo=timezone)
        if dt <= more_now:
            dt = dt + datetime.timedelta(days=1)
        self.dt: ADT = dt

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} time={self.time}>'

    @classmethod
    def now(cls, *, now: ADT = None, timezone: datetime.tzinfo = datetime.timezone.utc):
        return cls(argument='now', now=now, timezone=timezone)

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        now: ADT = ctx.message.created_at.astimezone(ctx.timezone)  # type: ignore
        return cls(argument, now=now, timezone=ctx.timezone)

    @classmethod
    async def transform(cls, interaction: discord.Interaction, argument: str) -> Self:
        timezone = interaction.client.get_timezone(interaction.user.id, interaction.guild_id)  # type: ignore
        now: ADT = interaction.created_at.astimezone(timezone)  # type: ignore
        return cls(argument, now=now, timezone=timezone)

    @classmethod
    async def autocomplete(cls, interaction: discord.Interaction, value: int | float | str) -> list[app_commands.Choice[int | float | str]]:
        choices = [app_commands.Choice(name=str(i), value=str(i)) for i in expected_times_of_day]
        return autocomplete(choices, str(value))


class ShortTime:
    compiled = re.compile("""(?:(?P<years>[0-9])(?:years?|y))?             # e.g. 2y
                             (?:(?P<months>[0-9]{1,2})(?:months?|mo))?     # e.g. 2months
                             (?:(?P<weeks>[0-9]{1,4})(?:weeks?|w))?        # e.g. 10w
                             (?:(?P<days>[0-9]{1,5})(?:days?|d))?          # e.g. 14d
                             (?:(?P<hours>[0-9]{1,5})(?:hours?|h))?        # e.g. 12h
                             (?:(?P<minutes>[0-9]{1,5})(?:minutes?|m))?    # e.g. 10m
                             (?:(?P<seconds>[0-9]{1,5})(?:seconds?|s))?    # e.g. 15s
                          """, re.VERBOSE)

    def __init__(self, argument: str, *, now: Optional[datetime.datetime] = None, timezone: datetime.tzinfo = datetime.timezone.utc):
        match = self.compiled.fullmatch(argument)
        if match is None or not match.group(0):
            raise commands.BadArgument('invalid time provided')

        data = {k: int(v) for k, v in match.groupdict(default=0).items()}
        now = now or datetime.datetime.now(timezone)
        self.dt = (now + relativedelta(**data)).astimezone(datetime.timezone.utc)

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        return cls(argument, now=ctx.message.created_at, timezone=ctx.timezone)


class HumanTime(commands.Converter, app_commands.Transformer):
    calendar = pdt.Calendar(version=pdt.VERSION_CONTEXT_STYLE)

    def __init__(self, argument: str, *, now: Optional[datetime.datetime] = None, timezone: datetime.tzinfo = datetime.timezone.utc):
        now = now or datetime.datetime.utcnow()
        now = now.astimezone(timezone)
        dt, status = self.calendar.parseDT(argument, sourceTime=now, tzinfo=timezone)
        if not status.hasDateOrTime:
            raise commands.BadArgument('invalid time provided, try e.g. "2pm" or "1 hour from now"')

        if not status.hasTime:
            # replace it with the current time
            dt = dt.replace(hour=now.hour, minute=now.minute, second=now.second, microsecond=now.microsecond)

        self.dt_local = dt.replace(tzinfo=timezone)
        self.dt = dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        self._past = self.dt_local < now

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        return cls(argument, now=ctx.message.created_at, timezone=ctx.timezone)

    @classmethod
    async def transform(cls, interaction: discord.Interaction, argument: str) -> Self:
        timezone = interaction.client.get_timezone(interaction.user.id, interaction.guild_id)  # type: ignore
        return cls(argument, now=interaction.created_at, timezone=timezone)

    @classmethod
    async def autocomplete(cls, interaction: discord.Interaction, value: int | float | str) -> list[app_commands.Choice[int | float | str]]:
        choices = [app_commands.Choice(name=str(i), value=str(i)) for i in expected_times_of_day]
        return autocomplete(choices, str(value))


class Time(HumanTime):
    def __init__(self, argument: str, *, now: Optional[datetime.datetime] = None, timezone: datetime.tzinfo = datetime.timezone.utc):
        try:
            o = ShortTime(argument, now=now, timezone=timezone)
        except Exception:
            super().__init__(argument)
        else:
            self.dt = o.dt
            self._past = False


class FutureTime(Time):
    def __init__(self, argument: str, *, now: Optional[datetime.datetime] = None, timezone: datetime.tzinfo = datetime.timezone.utc):
        super().__init__(argument, now=now, timezone=timezone)

        if self._past:
            raise commands.BadArgument('this time is in the past')


class TimeoutTime(FutureTime):
    def __init__(self, argument: str, *, now: Optional[datetime.datetime] = None, timezone: datetime.tzinfo = datetime.timezone.utc):
        super().__init__(argument, now=now, timezone=timezone)

        now = now or datetime.datetime.now(datetime.timezone.utc)

        if self.dt > (now + datetime.timedelta(days=28)):
            raise commands.BadArgument('This time is too far in the future. Must be sooner than 28 days.')


class FriendlyTimeResult:
    dt: ADT
    arg: str

    __slots__ = ('dt', 'arg')

    def __init__(self, dt: ADT):
        self.dt = dt
        self.arg = ""

    async def ensure_constraints(self, ctx: Context, uft: UserFriendlyTime, now: ADT, remaining: str) -> None:
        if self.dt < now:
            raise commands.BadArgument('This time is in the past.')

        if not remaining:
            if uft.default is None:
                raise commands.BadArgument('Missing argument after the time.')
            remaining = uft.default

        if uft.converter is not None:
            self.arg = await uft.converter.convert(ctx, remaining)
        else:
            self.arg = remaining

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} dt={self.dt} arg={self.arg}>"


class UserFriendlyTime(commands.Converter):
    def __init__(self, converter: Optional[Union[type[commands.Converter], commands.Converter]] = None, *, default: Any = None):
        if isinstance(converter, type) and issubclass(converter, commands.Converter):  # type: ignore
            converter = converter()

        if converter is not None and not isinstance(converter, commands.Converter):  # type: ignore
            raise TypeError("converter must be a subclass of Converter")

        self.converter: commands.Converter = converter  # type: ignore  # It doesn't understand this narrowing
        self.default: Any = default

    async def convert(self, ctx: Context, argument: str) -> FriendlyTimeResult:
        try:
            calendar = HumanTime.calendar
            regex = ShortTime.compiled
            now: ADT = ctx.message.created_at.astimezone(ctx.timezone)  # type: ignore

            match = regex.match(argument)
            if match is not None and match.group(0):
                data = {k: int(v) for k, v in match.groupdict(default=0).items()}
                remaining = argument[match.end():].strip()
                later: ADT = now + relativedelta(**data)  # type: ignore
                result = FriendlyTimeResult(later)
                await result.ensure_constraints(ctx, self, now, remaining)
                return result

            # apparently nlp does not like "from now"
            # it likes "from x" in other cases though so let me handle the 'now' case
            if argument.endswith('from now'):
                argument = argument[:-8].strip()

            if argument[0:2] == 'me':
                # starts with "me to", "me in", or "me at "
                if argument[0:6] in ('me to ', 'me in ', 'me at '):
                    argument = argument[6:]

            elements = calendar.nlp(argument, sourceTime=now)
            if elements is None or len(elements) == 0:
                raise commands.BadArgument('Invalid time provided, try e.g. "tomorrow" or "3 days".')

            # handle the following cases:
            # "date time" foo
            # date time foo
            # foo date time

            # first the first two cases:
            dt, status, begin, end, dt_string = elements[0]
            dt = dt.astimezone(ctx.message.created_at.tzinfo)

            if not status.hasDateOrTime:
                raise commands.BadArgument('Invalid time provided, try e.g. "tomorrow" or "3 days".')

            if begin not in (0, 1) and end != len(argument):
                raise commands.BadArgument(
                    'Time is either in an inappropriate location, which '
                    'must be either at the end or beginning of your input, '
                    'or I just flat out did not understand what you meant. Sorry.'
                )

            if not status.hasTime:
                # replace it with the current time
                dt = dt.replace(hour=now.hour, minute=now.minute, second=now.second, microsecond=now.microsecond)

            # if midnight is provided, just default to next day
            if status.accuracy == pdt.pdtContext.ACU_HALFDAY:
                dt = dt.replace(day=now.day + 1)

            result = FriendlyTimeResult(dt.replace(tzinfo=datetime.timezone.utc))
            remaining = ''

            if begin in (0, 1):
                if begin == 1:
                    # check if it's quoted:
                    if argument[0] != '"':
                        raise commands.BadArgument('Expected quote before time input...')

                    if not (end < len(argument) and argument[end] == '"'):
                        raise commands.BadArgument('If the time is quoted, you must unquote it.')

                    remaining = argument[end + 1:].lstrip(' ,.!')
                else:
                    remaining = argument[end:].lstrip(' ,.!')
            elif len(argument) == end:
                remaining = argument[:begin].strip()

            await result.ensure_constraints(ctx, self, now, remaining)
            return result
        except BaseException:
            import traceback

            traceback.print_exc()
            raise


def format_dt(dt: datetime.datetime, style: Optional[str] = None) -> str:
    # The below if statement is the fix for my timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    if style is None:
        return f'<t:{int(dt.timestamp())}>'
    return f'<t:{int(dt.timestamp())}:{style}>'
