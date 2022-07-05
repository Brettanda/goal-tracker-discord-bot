from __future__ import annotations

import pytest
from utils.time import (HumanTime, Interval, TimeOfDay, expected_intervals,
                        expected_times_of_day)

pytestmark = pytest.mark.asyncio


async def test_interval():
    for e in expected_intervals:
        interval = Interval(e).interval
        assert interval


async def test_time_of_day():
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


async def test_human_time():
    for e in expected_times_of_day:
        assert HumanTime(e).dt
        assert HumanTime(e).dt_local
