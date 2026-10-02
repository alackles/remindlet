import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import db
from scheduler import fire_due

CREATOR = 222222222222222222
TARGET = 333333333333333333
T0 = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


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


def test_fires_overdue_and_due_only(conn):
    # Startup recovery: a reminder that came due while the bot was down fires
    # on the first pass, alongside one due exactly now.
    overdue, due, future = add(conn, T0 - timedelta(hours=3)), add(conn, T0), add(conn, T0 + timedelta(minutes=1))
    fired = []

    async def fire(row):
        fired.append(row["id"])

    asyncio.run(fire_due(conn, fire, T0))
    assert fired == [overdue, due]
    assert [status(conn, r) for r in (overdue, due, future)] == ["fired", "fired", "pending"]


def test_failed_fire_is_marked_and_does_not_block_others(conn):
    first, second = add(conn, T0 - timedelta(minutes=1)), add(conn, T0)
    fired = []

    async def fire(row):
        if row["id"] == first:
            raise RuntimeError("channel gone")
        fired.append(row["id"])

    asyncio.run(fire_due(conn, fire, T0))
    assert fired == [second]
    assert status(conn, first) == "fired"  # not retried forever
