from __future__ import annotations

import datetime

import pytest
import pytz
from utils.time import (HumanTime, Interval, TimeOfDay, expected_intervals,
                        expected_times_of_day, ADT)

pytestmark = pytest.mark.asyncio


async def test_interval():
    for e in expected_intervals:
        interval = Interval(e).interval
        assert interval


async def test_time_of_day():
    now: ADT = datetime.datetime.now(tz=datetime.timezone.utc)  # type: ignore
    for e in expected_times_of_day:
        tod = TimeOfDay(str(e), now=now)

        assert tod.time.hour == int(e.hour)
        assert tod.time.minute == int(e.minute)
        assert tod.dt > now


async def test_time_of_day_berlin():
    tz = pytz.timezone("Europe/Berlin")
    now: ADT = datetime.datetime.now(tz=tz)  # type: ignore
    for e in expected_times_of_day:
        tod = TimeOfDay(str(e), now=now, timezone=tz)

        assert tod.time.hour == int(e.hour)
        assert tod.time.minute == int(e.minute)
        assert tod.dt > now


async def test_human_time():
    for e in expected_times_of_day:
        dt = HumanTime(str(e)).dt
        dt_local = HumanTime(str(e)).dt_local
        assert dt.hour == e.hour
        assert dt.minute == e.minute
        assert dt_local.hour == e.hour
        assert dt_local.minute == e.minute


async def test_human_time_berlin():
    tz = pytz.timezone("Europe/Berlin")
    for e in expected_times_of_day:
        dt = HumanTime(str(e), timezone=tz).dt
        dt_local = HumanTime(str(e)).dt_local
        assert dt.hour != e.hour
        assert dt.minute == e.minute
        assert dt_local.hour == e.hour
        assert dt_local.minute == e.minute
