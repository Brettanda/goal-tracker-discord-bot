from __future__ import annotations

import datetime

import discord
import pytest
from cogs.tasks import Task

pytestmark = pytest.mark.asyncio


def boundedIncrement(num: int, _max: int):
    num = num + 1
    if num > _max:
        return 0, True
    return num, False


def boundedDecrement(num: int, _min: int = 0, wrap_to: int = 10):
    num = num - 1
    if num < _min:
        return wrap_to, True
    return num, False


async def test_task_from_past():
    now = discord.utils.utcnow().replace(tzinfo=None)
    hour, wraped = boundedDecrement(now.hour, 0, 23)
    time = datetime.time(hour=hour)
    date = datetime.datetime.combine(now.date() if not wraped else (now - datetime.timedelta(days=1)).date(), time)
    delta = datetime.timedelta(days=1)
    record = {
        "id": None,
        "user_id": 215227961048170496,
        "created": now,
        "name": "test daily task",
        "goal": None,
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
    hour, wraped = boundedDecrement(now.hour, 0, 23)
    time = datetime.time(hour=hour)
    delta = datetime.timedelta(days=1)
    date = datetime.datetime.combine(now.date() if not wraped else (now - delta).date(), time)
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
    hour, wraped = boundedDecrement(now.hour, 0, 23)
    time = datetime.time(hour=hour)
    delta = datetime.timedelta(days=1)
    date = datetime.datetime.combine(now.date() if not wraped else (now - delta).date(), time)
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
    hour, wraped = boundedDecrement(now.hour, 0, 23)
    time = datetime.time(hour=hour)
    delta = datetime.timedelta(hours=1)
    date = datetime.datetime.combine(now.date() if not wraped else (now - delta).date(), time)
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
    hour, wraped = boundedIncrement(time.hour, 23)
    target = datetime.datetime.combine(now.date(), datetime.time(hour=hour)) + delta  # tomorrow
    next_reset = task.next_reset()
    assert next_reset == target


async def test_task_from_future():
    now = discord.utils.utcnow().replace(tzinfo=None)
    hour, wraped = boundedIncrement(now.hour, 23)
    time = datetime.time(hour=hour)
    delta = datetime.timedelta(hours=1)
    date = datetime.datetime.combine(now.date() if not wraped else (now + datetime.timedelta(days=1)).date(), time)
    record = {
        "id": None,
        "user_id": 215227961048170496,
        "created": now,
        "name": "test daily task",
        "goal": None,
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
