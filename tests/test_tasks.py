from __future__ import annotations

import datetime

import discord
import pytest
from cogs.tasks import Task

pytestmark = pytest.mark.asyncio


async def test_task_from_past():
    now = discord.utils.utcnow().replace(tzinfo=None)
    hour = now.hour - 1 if now.hour - 1 >= 0 else 23
    time = datetime.time(hour=hour)
    date = datetime.datetime.combine(now.date() if hour != 23 else now.date() - datetime.timedelta(days=1), time)
    delta = datetime.timedelta(days=1)
    record = {
        "id": None,
        "user_id": 215227961048170496,
        "created": now,
        "name": "test daily task",
        "time": time,
        "interval": delta,
        "last_reset": date,
        "reset_datetime": date,
        "remind_me": True,
        "completed": False,
    }
    task = Task(record=record)
    assert task.user_id == 215227961048170496
    target = date + delta  # tomorrow
    next_reset = task.next_reset()
    assert next_reset == target


async def test_task_from_past_plus_interval():
    now = discord.utils.utcnow().replace(tzinfo=None)
    hour = now.hour - 1 if now.hour - 1 >= 0 else 23
    time = datetime.time(hour=hour)
    delta = datetime.timedelta(days=1)
    date = datetime.datetime.combine(now.date() if hour != 23 else now.date() - delta, time)
    record = {
        "id": None,
        "user_id": 215227961048170496,
        "created": now - delta,
        "name": "test daily task",
        "time": time,
        "interval": delta,
        "last_reset": date - delta,
        "reset_datetime": date - delta,
        "remind_me": True,
        "completed": False,
    }
    task = Task(record=record)
    assert task.user_id == 215227961048170496
    target = date + delta  # tomorrow
    next_reset = task.next_reset()
    assert next_reset == target


async def test_task_hour_from_past():
    now = discord.utils.utcnow().replace(tzinfo=None)
    hour = now.hour - 1 if now.hour - 1 >= 0 else 23
    time = datetime.time(hour=hour)
    delta = datetime.timedelta(days=1)
    date = datetime.datetime.combine(now.date() if hour != 23 else now.date() - delta, time)
    record = {
        "id": None,
        "user_id": 215227961048170496,
        "created": now,
        "name": "test daily task",
        "time": time,
        "interval": delta,
        "last_reset": date,
        "reset_datetime": date,
        "remind_me": True,
        "completed": False,
    }
    task = Task(record=record)
    assert task.user_id == 215227961048170496
    target = date + delta  # tomorrow
    next_reset = task.next_reset()
    assert next_reset == target


async def test_task_hour_from_past_plus_interval():
    now = discord.utils.utcnow().replace(tzinfo=None)
    hour = now.hour - 1 if now.hour - 1 >= 0 else 23
    time = datetime.time(hour=hour)
    delta = datetime.timedelta(hours=1)
    date = datetime.datetime.combine(now.date() if hour != 23 else now.date() - delta, time)
    record = {
        "id": None,
        "user_id": 215227961048170496,
        "created": now - delta,
        "name": "test daily task",
        "time": time,
        "interval": delta,
        "last_reset": date - delta,
        "reset_datetime": date - delta,
        "remind_me": True,
        "completed": False,
    }
    task = Task(record=record)
    assert task.user_id == 215227961048170496
    target = datetime.datetime.combine(now.date(), datetime.time(hour=time.hour + 1)) + delta  # tomorrow
    next_reset = task.next_reset()
    assert next_reset == target


async def test_task_from_future():
    now = discord.utils.utcnow().replace(tzinfo=None)
    hour = now.hour + 1 if now.hour + 1 < 24 else 0
    time = datetime.time(hour=hour)
    delta = datetime.timedelta(hours=1)
    date = datetime.datetime.combine(now.date() if hour != 0 else now.date() + delta, time)
    record = {
        "id": None,
        "user_id": 215227961048170496,
        "created": now,
        "name": "test daily task",
        "time": time,
        "interval": delta,
        "last_reset": now,
        "reset_datetime": date,
        "remind_me": True,
        "completed": False,
    }
    task = Task(record=record)
    assert task.user_id == 215227961048170496
    target = date
    next_reset = task.next_reset()
    assert next_reset == target
