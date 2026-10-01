"""SQLite connection, schema, and queries. No Discord imports.

Discord IDs are passed in as ints (as discord.py provides them) and stored as
TEXT per the spec. All timestamps are stored as UTC ISO 8601 strings produced
by to_iso(), so string comparison in SQL matches chronological order.
"""

import sqlite3
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
