from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from utils.time import TimeOfDay, Interval, HumanTime, expected_times_of_day, expected_intervals


if TYPE_CHECKING:
    ...

pytestmark = pytest.mark.asyncio


async def test_interval(event_loop):
    for e in expected_intervals:
        interval = Interval(e).interval
        assert interval


async def test_time_of_day(event_loop):
    for e in expected_times_of_day:
        time = TimeOfDay(e).time
        if ":" in e:
            split = e.split(":")
            split = [split[0], *split[1].split(" ")]
        else:
            split = e.split(" ")

        hour = split[0]
        if split[-1].lower() == "pm":
            hour = str(int(hour) + 12)
        if int(hour) == 12 or int(hour) == 24:
            hour = str(int(hour) - 12)
        assert time.hour == int(hour)

        if len(split) > 2:
            minute = split[1]
            assert time.minute == int(minute)


async def test_human_time(event_loop):
    for e in expected_times_of_day:
        assert HumanTime(e).dt
        assert HumanTime(e).dt_local
