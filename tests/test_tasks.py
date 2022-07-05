from __future__ import annotations

import datetime

import discord
import pytest
from cogs.tasks import Task

pytestmark = pytest.mark.asyncio


async def test_task_from_past():
    now = discord.utils.utcnow().replace(tzinfo=None)
    time = datetime.time(hour=now.hour - 1)
    date = datetime.datetime.combine(now.date(), time)
    delta = datetime.timedelta(days=1)
    record = {
        "id": 1,
        "user_id": 215227961048170496,
        "created": now,
        "name": "test daily task",
        "goal": None,
        "time": time,
        "interval": delta,
        "remind_me": True,
        "completed": False,
        "last_reset": date
    }
    task = Task(record=record)
    assert task.id == 1
    assert task.user_id == 215227961048170496
    target = date + delta  # tomorrow
    next_reset = task.next_reset()
    assert next_reset == target


async def test_task_from_future():
    now = discord.utils.utcnow().replace(tzinfo=None)
    time = datetime.time(hour=now.hour + 1)
    date = datetime.datetime.combine(now.date(), time)
    delta = datetime.timedelta(days=1)
    record = {
        "id": 1,
        "user_id": 215227961048170496,
        "created": now,
        "name": "test daily task",
        "goal": None,
        "time": time,
        "interval": delta,
        "remind_me": True,
        "completed": False,
        "last_reset": date
    }
    task = Task(record=record)
    assert task.id == 1
    assert task.user_id == 215227961048170496
    target = date
    next_reset = task.next_reset()
    assert next_reset == target
