"""Reminder firing. No Discord imports: sending is a callback.

The reminders cog calls fire_due() every POLL_SECONDS. The database is the
schedule, so startup recovery needs no special case: the first pass fires
whatever came due while the bot was down.
"""

import logging
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime

import db

log = logging.getLogger(__name__)

# Reminders arrive up to this many seconds after their time.
POLL_SECONDS = 15


async def fire_due(
    conn: sqlite3.Connection,
    fire: Callable[[sqlite3.Row], Awaitable[None]],
    now: datetime,
) -> None:
    for row in db.due_reminders(conn, now):
        # Send first, then mark: a crash in between re-fires on restart
        # (a duplicate) rather than losing the reminder.
        try:
            await fire(row)
        except Exception:
            log.exception("Failed to fire reminder #%s", row["id"])
        db.mark_fired(conn, row["id"])
