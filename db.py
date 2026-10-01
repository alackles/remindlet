"""SQLite connection, schema, and queries. No Discord imports.

Discord IDs are passed in as ints (as discord.py provides them) and stored as
TEXT per the spec. All timestamps are stored as UTC ISO 8601 strings produced
by to_iso(), so string comparison in SQL matches chronological order.
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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


def next_fire_at(conn: sqlite3.Connection) -> datetime | None:
    """When the soonest active reminder is due, or None if there are none."""
    row = conn.execute(
        f"SELECT MIN(fire_at) FROM reminders WHERE status IN {ACTIVE}"
    ).fetchone()
    return from_iso(row[0]) if row[0] else None


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
