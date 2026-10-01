import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import db

ACACIA = 111111111111111111
ELLIOTT = 222222222222222222


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    conn = db.connect(db_path)
    yield conn
    conn.close()


def insert_reminder(conn, creator, target, status="pending"):
    now = db.utc_now()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO reminders (creator_id, target_id, channel_id, guild_id, message,
                                   fire_at, created_at, status, original_tz, original_time_str)
            VALUES (?, ?, '1', '1', 'test', ?, ?, ?, 'America/Chicago', '9am')
            """,
            (str(creator), str(target), now, now, status),
        )
    return cur.lastrowid


def test_new_database_has_schema(conn):
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"users", "reminders", "reminder_log"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_reconnect_does_not_recreate_schema(db_path):
    db.connect(db_path).close()
    db.connect(db_path).close()  # would raise "table already exists" if it re-ran SCHEMA


def test_mismatched_schema_version_refuses_to_open(db_path):
    db.connect(db_path).close()
    raw = sqlite3.connect(db_path)
    raw.execute("PRAGMA user_version = 99")
    raw.close()
    with pytest.raises(RuntimeError, match="version 99"):
        db.connect(db_path)


def test_unknown_user_has_no_timezone(conn):
    assert db.get_timezone(conn, ACACIA) is None


def test_set_timezone_returns_previous(conn):
    assert db.set_timezone(conn, ACACIA, "America/Chicago") is None
    assert db.set_timezone(conn, ACACIA, "America/New_York") == "America/Chicago"
    assert db.get_timezone(conn, ACACIA) == "America/New_York"


def test_update_keeps_original_created_at(conn):
    db.set_timezone(conn, ACACIA, "America/Chicago")
    first = conn.execute("SELECT created_at FROM users").fetchone()[0]
    db.set_timezone(conn, ACACIA, "America/New_York")
    assert conn.execute("SELECT created_at FROM users").fetchone()[0] == first


def test_timezone_survives_reconnect(db_path):
    # The milestone's "survives a restart" criterion, minus Discord.
    conn = db.connect(db_path)
    db.set_timezone(conn, ACACIA, "America/Chicago")
    conn.close()
    conn = db.connect(db_path)
    assert db.get_timezone(conn, ACACIA) == "America/Chicago"
    conn.close()


def test_reminder_requires_creator_and_target_with_timezone(conn):
    db.set_timezone(conn, ACACIA, "America/Chicago")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_reminder(conn, ACACIA, ELLIOTT)
    db.set_timezone(conn, ELLIOTT, "America/New_York")
    assert insert_reminder(conn, ACACIA, ELLIOTT) == 1


def test_invalid_status_rejected(conn):
    db.set_timezone(conn, ACACIA, "America/Chicago")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        insert_reminder(conn, ACACIA, ACACIA, status="sleeping")


def test_to_iso_converts_to_utc():
    chicago = datetime(2026, 10, 1, 9, 0, tzinfo=ZoneInfo("America/Chicago"))
    assert db.to_iso(chicago) == "2026-10-01T14:00:00+00:00"


def test_to_iso_rejects_naive_datetime():
    with pytest.raises(ValueError):
        db.to_iso(datetime(2026, 10, 1, 9, 0))


def test_iso_strings_sort_chronologically():
    base = datetime(2026, 10, 1, 9, 0, tzinfo=ZoneInfo("America/Chicago"))
    times = [base + timedelta(hours=h) for h in (5, -3, 20, 0)]
    times.append(datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc))
    assert sorted(db.to_iso(t) for t in times) == [db.to_iso(t) for t in sorted(times)]
