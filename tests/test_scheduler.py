import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import db
import scheduler
from scheduler import Scheduler

CREATOR = 222222222222222222
TARGET = 333333333333333333
T0 = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.set_timezone(conn, CREATOR, "America/New_York")
    db.set_timezone(conn, TARGET, "America/Chicago")
    yield conn
    conn.close()


def add(conn, fire_at):
    [rid] = db.create_reminders(
        conn, creator_id=CREATOR, channel_id=5, guild_id=6, message="m",
        targets=[db.NewReminder(TARGET, fire_at, "America/Chicago", "x")],
    )
    return rid


def status(conn, rid):
    return db.get_reminder(conn, rid)["status"]


async def eventually(condition, timeout=1.0):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


def test_fire_due_fires_overdue_and_due_only(conn):
    # Startup recovery: a reminder that came due while the bot was down fires
    # on the first pass, alongside one due exactly now.
    overdue, due, future = add(conn, T0 - timedelta(hours=3)), add(conn, T0), add(conn, T0 + timedelta(minutes=1))
    fired = []

    async def fire(row):
        fired.append(row["id"])

    asyncio.run(Scheduler(conn, fire, FakeClock(T0)).fire_due())
    assert fired == [overdue, due]
    assert [status(conn, r) for r in (overdue, due, future)] == ["fired", "fired", "pending"]


def test_failed_fire_is_marked_and_does_not_block_others(conn):
    first, second = add(conn, T0 - timedelta(minutes=1)), add(conn, T0)
    fired = []

    async def fire(row):
        if row["id"] == first:
            raise RuntimeError("channel gone")
        fired.append(row["id"])

    asyncio.run(Scheduler(conn, fire, FakeClock(T0)).fire_due())
    assert fired == [second]
    assert status(conn, first) == "fired"  # not retried forever


def test_loop_fires_when_time_arrives(conn, monkeypatch):
    monkeypatch.setattr(scheduler, "MAX_SLEEP", 0.01)
    rid = add(conn, T0 + timedelta(hours=1))
    clock = FakeClock(T0)
    fired = []

    async def fire(row):
        fired.append(row["id"])

    async def scenario():
        s = Scheduler(conn, fire, clock)
        s.start()
        await asyncio.sleep(0.05)
        assert fired == []  # not yet
        clock.now = T0 + timedelta(hours=1)
        await eventually(lambda: fired == [rid])
        await s.stop()

    asyncio.run(scenario())


def test_wake_picks_up_new_reminder_without_waiting(conn):
    # MAX_SLEEP stays at 60s: only wake() can make this fire within the timeout.
    clock = FakeClock(T0)
    fired = []

    async def fire(row):
        fired.append(row["id"])

    async def scenario():
        s = Scheduler(conn, fire, clock)
        s.start()
        await asyncio.sleep(0.02)  # let it go to sleep on an empty schedule
        rid = add(conn, T0)
        s.wake()
        await eventually(lambda: fired == [rid])
        await s.stop()

    asyncio.run(scenario())


def test_reminder_created_during_firing_fires_promptly(conn):
    clock = FakeClock(T0)
    fired = []
    later = []

    async def fire(row):
        fired.append(row["id"])
        if not later:  # while firing the first, a new reminder is created
            later.append(add(conn, T0))
            s.wake()

    async def scenario():
        nonlocal s
        s = Scheduler(conn, fire, clock)
        add(conn, T0)
        s.start()
        await eventually(lambda: len(fired) == 2)
        await s.stop()

    s = None
    asyncio.run(scenario())
    assert fired[1] == later[0]


def test_stop_is_clean(conn):
    async def scenario():
        s = Scheduler(conn, lambda row: asyncio.sleep(0), FakeClock(T0))
        s.start()
        await asyncio.sleep(0.01)
        await s.stop()
        await s.stop()  # idempotent

    asyncio.run(scenario())
