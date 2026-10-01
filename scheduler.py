"""Reminder scheduling. No Discord imports: firing is a callback.

The database is the schedule. The loop sleeps until the soonest active
reminder is due, fires everything due, and repeats. Startup recovery needs no
special case: the first pass finds whatever came due while the bot was down.
"""

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import db

log = logging.getLogger(__name__)

# Re-check at least this often, so clock adjustments can't strand a reminder.
MAX_SLEEP = 60.0

FireCallback = Callable[[sqlite3.Row], Awaitable[None]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Scheduler:
    def __init__(
        self,
        conn: sqlite3.Connection,
        fire: FireCallback,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._conn = conn
        self._fire = fire
        self._clock = clock
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="reminder-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def wake(self) -> None:
        """Re-check the schedule now (call after creating or moving a reminder)."""
        self._wake.set()

    async def _run(self) -> None:
        while True:
            # Any reminder a wake() could announce is seen by the queries below.
            self._wake.clear()
            await self.fire_due()
            try:
                await asyncio.wait_for(self._wake.wait(), self._sleep_seconds())
            except TimeoutError:
                pass

    async def fire_due(self) -> None:
        for row in db.due_reminders(self._conn, self._clock()):
            # Send first, then mark: a crash in between re-fires on restart
            # (a duplicate) rather than losing the reminder.
            try:
                await self._fire(row)
            except Exception:
                log.exception("Failed to fire reminder #%s", row["id"])
            db.mark_fired(self._conn, row["id"])

    def _sleep_seconds(self) -> float:
        next_at = db.next_fire_at(self._conn)
        if next_at is None:
            return MAX_SLEEP
        return min(MAX_SLEEP, max(0.0, (next_at - self._clock()).total_seconds()))
