"""SQLite connection, schema, and queries. No Discord imports.

Discord IDs are passed in as ints (as discord.py provides them) and stored as
TEXT per the spec. All timestamps are stored as UTC ISO 8601 strings produced
by to_iso(), so string comparison in SQL matches chronological order.
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from os import PathLike

SCHEMA_VERSION = 1

# Wrapped in an explicit transaction because executescript() bypasses
# sqlite3's implicit transaction handling.
SCHEMA = f"""
BEGIN;

CREATE TABLE users (
    discord_id TEXT PRIMARY KEY,
    timezone   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE reminders (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id        TEXT NOT NULL REFERENCES users (discord_id),
    target_id         TEXT NOT NULL REFERENCES users (discord_id),
    channel_id        TEXT NOT NULL,
    guild_id          TEXT NOT NULL,
    message           TEXT NOT NULL,
    fire_at           TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'fired', 'snoozed', 'done', 'cancelled')),
    batch_id          TEXT,
    recurrence_rule   TEXT,
    original_tz       TEXT NOT NULL,
    original_time_str TEXT NOT NULL
);

CREATE INDEX reminders_status_fire_at ON reminders (status, fire_at);

CREATE TABLE reminder_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id INTEGER NOT NULL REFERENCES reminders (id),
    action      TEXT NOT NULL
        CHECK (action IN ('created', 'rescheduled', 'snoozed', 'cancelled', 'done', 'fired')),
    actor_id    TEXT,
    reason      TEXT,
    old_fire_at TEXT,
    new_fire_at TEXT,
    timestamp   TEXT NOT NULL
);

PRAGMA user_version = {SCHEMA_VERSION};

COMMIT;
"""


def to_iso(dt: datetime) -> str:
    """Format an aware datetime as a UTC ISO 8601 string for storage."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime; attach a timezone before storing")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def utc_now() -> str:
    return to_iso(datetime.now(timezone.utc))


def from_iso(text: str) -> datetime:
    """Parse a stored timestamp back into an aware UTC datetime."""
    return datetime.fromisoformat(text)


def connect(path: str | PathLike) -> sqlite3.Connection:
    """Open the database, enabling foreign keys and creating the schema if new."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        conn.executescript(SCHEMA)
    elif version != SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(
            f"database schema version {version} does not match code version {SCHEMA_VERSION}"
        )
    return conn


def get_timezone(conn: sqlite3.Connection, discord_id: int) -> str | None:
    row = conn.execute(
        "SELECT timezone FROM users WHERE discord_id = ?", (str(discord_id),)
    ).fetchone()
    return row["timezone"] if row else None


def set_timezone(conn: sqlite3.Connection, discord_id: int, tz: str) -> str | None:
    """Store a user's timezone and return the previous one (None if new)."""
    with conn:
        previous = get_timezone(conn, discord_id)
        conn.execute(
            """
            INSERT INTO users (discord_id, timezone, created_at) VALUES (?, ?, ?)
            ON CONFLICT (discord_id) DO UPDATE SET timezone = excluded.timezone
            """,
            (str(discord_id), tz, utc_now()),
        )
    return previous


# --- Reminders ----------------------------------------------------------------

ACTIVE = ("pending", "snoozed")  # statuses the scheduler still has to fire
OPEN = ("pending", "snoozed", "fired")  # not yet done or cancelled


@dataclass(frozen=True)
class NewReminder:
    """One target's share of a /remind: who, and when in their terms."""

    target_id: int
    fire_at: datetime
    original_tz: str
    original_time_str: str


def _log(conn, reminder_id, action, actor_id, *, reason=None, old=None, new=None):
    conn.execute(
        """
        INSERT INTO reminder_log
            (reminder_id, action, actor_id, reason, old_fire_at, new_fire_at, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (reminder_id, action, actor_id, reason, old, new, utc_now()),
    )


def create_reminders(
    conn: sqlite3.Connection,
    *,
    creator_id: int,
    channel_id: int,
    guild_id: int,
    message: str,
    targets: list[NewReminder],
) -> list[int]:
    """Insert one reminder per target, linked by a batch_id if more than one.

    All-or-nothing: if any insert fails, none are kept. Returns the new IDs in
    the same order as targets.
    """
    batch_id = str(uuid.uuid4()) if len(targets) > 1 else None
    created_at = utc_now()
    ids = []
    with conn:
        for t in targets:
            cur = conn.execute(
                """
                INSERT INTO reminders
                    (creator_id, target_id, channel_id, guild_id, message, fire_at,
                     created_at, batch_id, original_tz, original_time_str)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(creator_id),
                    str(t.target_id),
                    str(channel_id),
                    str(guild_id),
                    message,
                    to_iso(t.fire_at),
                    created_at,
                    batch_id,
                    t.original_tz,
                    t.original_time_str,
                ),
            )
            ids.append(cur.lastrowid)
            _log(conn, cur.lastrowid, "created", str(creator_id))
    return ids


def get_reminder(conn: sqlite3.Connection, reminder_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()


def due_reminders(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    """Active reminders whose fire time has arrived, oldest first."""
    return conn.execute(
        f"""
        SELECT * FROM reminders
        WHERE status IN {ACTIVE} AND fire_at <= ?
        ORDER BY fire_at, id
        """,
        (to_iso(now),),
    ).fetchall()


def mark_fired(conn: sqlite3.Connection, reminder_id: int) -> bool:
    """Move an active reminder to 'fired'. Returns False if it wasn't active."""
    with conn:
        cur = conn.execute(
            f"UPDATE reminders SET status = 'fired' WHERE id = ? AND status IN {ACTIVE}",
            (reminder_id,),
        )
        if cur.rowcount:
            _log(conn, reminder_id, "fired", None)
    return bool(cur.rowcount)


# --- Changing open reminders -------------------------------------------------


class ReminderNotFound(LookupError):
    def __init__(self, reminder_id: int) -> None:
        super().__init__(f"no reminder #{reminder_id}")
        self.reminder_id = reminder_id


class ReminderClosed(ValueError):
    """The reminder is done or cancelled; closed_by is who did it (if logged)."""

    def __init__(self, row: sqlite3.Row, closed_by: str | None) -> None:
        super().__init__(f"reminder #{row['id']} is {row['status']}")
        self.row = row
        self.closed_by = closed_by


def closed_by(conn: sqlite3.Connection, reminder_id: int) -> str | None:
    """Discord ID of whoever marked the reminder done or cancelled it, if anyone."""
    row = conn.execute(
        """
        SELECT actor_id FROM reminder_log
        WHERE reminder_id = ? AND action IN ('done', 'cancelled')
        ORDER BY id DESC LIMIT 1
        """,
        (reminder_id,),
    ).fetchone()
    return row["actor_id"] if row else None


def _change(
    conn: sqlite3.Connection,
    reminder_id: int,
    *,
    status: str,
    action: str,
    actor_id: int,
    reason: str | None = None,
    new_fire_at=None,
    **columns,
) -> sqlite3.Row:
    """Apply one state change to an open reminder, log it, and return the new row.

    new_fire_at is a function of the current row, so snooze can compute from
    the stored time inside the same transaction.
    """
    with conn:
        row = get_reminder(conn, reminder_id)
        if row is None:
            raise ReminderNotFound(reminder_id)
        if row["status"] not in OPEN:
            raise ReminderClosed(row, closed_by(conn, reminder_id))

        old = row["fire_at"]
        new = to_iso(new_fire_at(row)) if new_fire_at else None
        updates = {"status": status, **columns}
        if new:
            updates["fire_at"] = new
        assignments = ", ".join(f"{col} = ?" for col in updates)
        conn.execute(
            f"UPDATE reminders SET {assignments} WHERE id = ? AND status IN {OPEN}",
            (*updates.values(), reminder_id),
        )
        _log(
            conn, reminder_id, action, str(actor_id), reason=reason,
            old=old if new else None, new=new,
        )
    return get_reminder(conn, reminder_id)


def reschedule(
    conn: sqlite3.Connection,
    reminder_id: int,
    *,
    actor_id: int,
    fire_at: datetime,
    original_tz: str,
    original_time_str: str,
    reason: str | None = None,
) -> sqlite3.Row:
    """Move to a new time; the new time's zone becomes the display zone."""
    return _change(
        conn, reminder_id, status="pending", action="rescheduled", actor_id=actor_id,
        reason=reason, new_fire_at=lambda row: fire_at,
        original_tz=original_tz, original_time_str=original_time_str,
    )


def snooze(
    conn: sqlite3.Connection,
    reminder_id: int,
    *,
    actor_id: int,
    duration: timedelta,
    now: datetime,
) -> sqlite3.Row:
    """Push back by duration from the due time or now, whichever is later.

    original_time_str is left as entered at creation; display the new time
    with time_parser.format_in_zone(fire_at, original_tz).
    """
    return _change(
        conn, reminder_id, status="snoozed", action="snoozed", actor_id=actor_id,
        new_fire_at=lambda row: max(from_iso(row["fire_at"]), now) + duration,
    )


def cancel(
    conn: sqlite3.Connection, reminder_id: int, *, actor_id: int, reason: str | None = None
) -> sqlite3.Row:
    return _change(
        conn, reminder_id, status="cancelled", action="cancelled", actor_id=actor_id, reason=reason
    )


def complete(conn: sqlite3.Connection, reminder_id: int, *, actor_id: int) -> sqlite3.Row:
    return _change(conn, reminder_id, status="done", action="done", actor_id=actor_id)


# --- Listing ------------------------------------------------------------------


def list_open(
    conn: sqlite3.Connection,
    guild_id: int,
    *,
    target_id: int | None = None,
    creator_id: int | None = None,
) -> list[sqlite3.Row]:
    """Open reminders in a guild: upcoming first (soonest first), then fired."""
    sql = f"SELECT * FROM reminders WHERE guild_id = ? AND status IN {OPEN}"
    params: list = [str(guild_id)]
    if target_id is not None:
        sql += " AND target_id = ?"
        params.append(str(target_id))
    if creator_id is not None:
        sql += " AND creator_id = ?"
        params.append(str(creator_id))
    sql += " ORDER BY status = 'fired', fire_at, id"
    return conn.execute(sql, params).fetchall()


def open_siblings(conn: sqlite3.Connection, row: sqlite3.Row) -> list[sqlite3.Row]:
    """Other open reminders created in the same /remind as this one."""
    if row["batch_id"] is None:
        return []
    return conn.execute(
        f"""
        SELECT * FROM reminders
        WHERE batch_id = ? AND id != ? AND status IN {OPEN}
        ORDER BY id
        """,
        (row["batch_id"], row["id"]),
    ).fetchall()
