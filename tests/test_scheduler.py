import asyncio
from datetime import timedelta

import db
from scheduler import fire_due
from tests.helpers import T0, add


def run(conn, fail_ids=()):
    """Run one polling pass; return the IDs that were sent successfully."""
    sent = []

    async def fire(row):
        if row["id"] in fail_ids:
            raise RuntimeError("channel gone")
        sent.append(row["id"])

    asyncio.run(fire_due(conn, fire, T0))
    return sent


def status(conn, rid):
    return db.get_reminder(conn, rid)["status"]


def test_fires_overdue_and_due_only(conn):
    # Startup recovery: a reminder that came due while the bot was down fires
    # on the first pass, alongside one due exactly now.
    overdue, due, future = (add(conn, T0 + timedelta(minutes=m)) for m in (-180, 0, 1))
    assert run(conn) == [overdue, due]
    assert [status(conn, r) for r in (overdue, due, future)] == ["fired", "fired", "pending"]


def test_failed_fire_is_marked_and_does_not_block_others(conn):
    first, second = add(conn, T0 - timedelta(minutes=1)), add(conn, T0)
    assert run(conn, fail_ids={first}) == [second]
    assert status(conn, first) == "fired"  # not retried forever
