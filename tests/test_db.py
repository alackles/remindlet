import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import db

USER = 111111111111111111
CREATOR = 222222222222222222
TARGET = 333333333333333333


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
    assert db.get_timezone(conn, USER) is None


def test_set_timezone_returns_previous(conn):
    assert db.set_timezone(conn, USER, "America/Chicago") is None
    assert db.set_timezone(conn, USER, "America/New_York") == "America/Chicago"
    assert db.get_timezone(conn, USER) == "America/New_York"


def test_update_keeps_original_created_at(conn):
    db.set_timezone(conn, USER, "America/Chicago")
    first = conn.execute("SELECT created_at FROM users").fetchone()[0]
    db.set_timezone(conn, USER, "America/New_York")
    assert conn.execute("SELECT created_at FROM users").fetchone()[0] == first


def test_timezone_survives_reconnect(db_path):
    # The milestone's "survives a restart" criterion, minus Discord.
    conn = db.connect(db_path)
    db.set_timezone(conn, USER, "America/Chicago")
    conn.close()
    conn = db.connect(db_path)
    assert db.get_timezone(conn, USER) == "America/Chicago"
    conn.close()


def test_reminder_requires_creator_and_target_with_timezone(conn):
    db.set_timezone(conn, CREATOR, "America/Chicago")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_reminder(conn, CREATOR, TARGET)
    db.set_timezone(conn, TARGET, "America/New_York")
    assert insert_reminder(conn, CREATOR, TARGET) == 1


def test_invalid_status_rejected(conn):
    db.set_timezone(conn, CREATOR, "America/Chicago")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        insert_reminder(conn, CREATOR, CREATOR, status="sleeping")


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


# --- Reminders ---------------------------------------------------------------

T0 = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def people(conn):
    db.set_timezone(conn, CREATOR, "America/New_York")
    db.set_timezone(conn, TARGET, "America/Chicago")


def new(target, fire_at=T0, tz="America/Chicago", display="10:00 AM CT"):
    return db.NewReminder(target, fire_at, tz, display)


def create(conn, *targets):
    return db.create_reminders(
        conn, creator_id=CREATOR, channel_id=5, guild_id=6, message="do the thing",
        targets=list(targets),
    )


def actions(conn, reminder_id):
    rows = conn.execute(
        "SELECT action, actor_id FROM reminder_log WHERE reminder_id = ? ORDER BY id",
        (reminder_id,),
    )
    return [tuple(r) for r in rows]


def test_create_single_reminder(conn, people):
    [rid] = create(conn, new(TARGET))
    row = db.get_reminder(conn, rid)
    assert row["creator_id"] == str(CREATOR)
    assert row["target_id"] == str(TARGET)
    assert row["channel_id"] == "5"
    assert row["status"] == "pending"
    assert row["batch_id"] is None
    assert db.from_iso(row["fire_at"]) == T0
    assert (row["original_tz"], row["original_time_str"]) == ("America/Chicago", "10:00 AM CT")
    assert actions(conn, rid) == [("created", str(CREATOR))]


def test_multi_target_shares_batch_id_but_keeps_own_times(conn, people):
    later = T0 + timedelta(hours=1)
    ids = create(conn, new(TARGET), new(CREATOR, later, "America/New_York", "11:00 AM ET"))
    a, b = (db.get_reminder(conn, i) for i in ids)
    assert a["batch_id"] is not None and a["batch_id"] == b["batch_id"]
    assert a["id"] != b["id"]
    assert db.from_iso(b["fire_at"]) == later


def test_create_is_all_or_nothing(conn):
    db.set_timezone(conn, CREATOR, "America/New_York")  # TARGET has no timezone
    with pytest.raises(sqlite3.IntegrityError):
        create(conn, new(CREATOR), new(TARGET))
    assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM reminder_log").fetchone()[0] == 0


def test_due_reminders(conn, people):
    late, now_, future = create(
        conn, new(TARGET, T0 - timedelta(hours=1)), new(TARGET, T0), new(TARGET, T0 + timedelta(seconds=1))
    )
    assert [r["id"] for r in db.due_reminders(conn, T0)] == [late, now_]


def test_snoozed_reminders_are_still_due(conn, people):
    [rid] = create(conn, new(TARGET))
    conn.execute("UPDATE reminders SET status = 'snoozed' WHERE id = ?", (rid,))
    assert [r["id"] for r in db.due_reminders(conn, T0)] == [rid]


@pytest.mark.parametrize("status", ["fired", "done", "cancelled"])
def test_inactive_reminders_are_never_due(conn, people, status):
    [rid] = create(conn, new(TARGET))
    conn.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, rid))
    assert db.due_reminders(conn, T0) == []


def test_mark_fired_logs_once(conn, people):
    [rid] = create(conn, new(TARGET))
    assert db.mark_fired(conn, rid) is True
    assert db.mark_fired(conn, rid) is False
    assert db.get_reminder(conn, rid)["status"] == "fired"
    assert actions(conn, rid) == [("created", str(CREATOR)), ("fired", None)]


def test_reminders_survive_reconnect(db_path):
    conn = db.connect(db_path)
    db.set_timezone(conn, CREATOR, "America/New_York")
    db.set_timezone(conn, TARGET, "America/Chicago")
    [rid] = create(conn, new(TARGET))
    conn.close()
    conn = db.connect(db_path)
    assert [r["id"] for r in db.due_reminders(conn, T0)] == [rid]
    conn.close()


# --- Changing open reminders ---------------------------------------------------

ACTOR = USER  # anyone can change anyone's reminder


def log_rows(conn, rid):
    return conn.execute(
        "SELECT action, actor_id, reason, old_fire_at, new_fire_at FROM reminder_log "
        "WHERE reminder_id = ? ORDER BY id",
        (rid,),
    ).fetchall()


def test_reschedule_moves_time_and_display_zone(conn, people):
    [rid] = create(conn, new(TARGET))
    db.mark_fired(conn, rid)  # fired reminders are still open
    later = T0 + timedelta(days=1)
    row = db.reschedule(
        conn, rid, actor_id=ACTOR, fire_at=later, original_tz="America/New_York",
        original_time_str="11:00 AM ET", reason="sick",
    )
    assert row["status"] == "pending"
    assert db.from_iso(row["fire_at"]) == later
    assert (row["original_tz"], row["original_time_str"]) == ("America/New_York", "11:00 AM ET")
    last = log_rows(conn, rid)[-1]
    assert tuple(last) == ("rescheduled", str(ACTOR), "sick", db.to_iso(T0), db.to_iso(later))


def test_snooze_pending_counts_from_due_time(conn, people):
    [rid] = create(conn, new(TARGET, T0 + timedelta(hours=2)))
    row = db.snooze(conn, rid, actor_id=ACTOR, duration=timedelta(hours=1), now=T0)
    assert row["status"] == "snoozed"
    assert db.from_iso(row["fire_at"]) == T0 + timedelta(hours=3)
    assert row["original_time_str"] == "10:00 AM CT"  # creation display kept


def test_snooze_fired_counts_from_now(conn, people):
    [rid] = create(conn, new(TARGET))
    db.mark_fired(conn, rid)
    now = T0 + timedelta(minutes=40)
    row = db.snooze(conn, rid, actor_id=ACTOR, duration=timedelta(minutes=15), now=now)
    assert db.from_iso(row["fire_at"]) == now + timedelta(minutes=15)
    assert log_rows(conn, rid)[-1]["action"] == "snoozed"


def test_snoozed_reminder_fires_again(conn, people):
    [rid] = create(conn, new(TARGET))
    db.mark_fired(conn, rid)
    db.snooze(conn, rid, actor_id=ACTOR, duration=timedelta(hours=1), now=T0)
    assert [r["id"] for r in db.due_reminders(conn, T0 + timedelta(hours=1))] == [rid]


def test_cancel_and_complete_close_the_reminder(conn, people):
    a, b = create(conn, new(TARGET), new(TARGET))
    assert db.cancel(conn, a, actor_id=ACTOR, reason="not needed")["status"] == "cancelled"
    assert db.complete(conn, b, actor_id=TARGET)["status"] == "done"
    assert db.due_reminders(conn, T0) == []
    assert tuple(log_rows(conn, a)[-1]) == ("cancelled", str(ACTOR), "not needed", None, None)


@pytest.mark.parametrize(
    "close, closer",
    [
        (lambda c, r: db.cancel(c, r, actor_id=ACTOR), ACTOR),
        (lambda c, r: db.complete(c, r, actor_id=TARGET), TARGET),
    ],
)
def test_closed_reminder_is_left_alone(conn, people, close, closer):
    # Callers check first; the status guard makes a slip a no-op, not a reopen.
    [rid] = create(conn, new(TARGET))
    close(conn, rid)
    before = (tuple(db.get_reminder(conn, rid)), len(log_rows(conn, rid)))
    db.reschedule(conn, rid, actor_id=ACTOR, fire_at=T0, original_tz="UTC", original_time_str="x")
    db.snooze(conn, rid, actor_id=ACTOR, duration=timedelta(hours=1), now=T0)
    db.cancel(conn, rid, actor_id=ACTOR)
    db.complete(conn, rid, actor_id=ACTOR)
    assert (tuple(db.get_reminder(conn, rid)), len(log_rows(conn, rid))) == before
    assert db.closed_by(conn, rid) == str(closer)


def test_closed_by_is_none_while_open(conn, people):
    [rid] = create(conn, new(TARGET))
    assert db.closed_by(conn, rid) is None


# --- Listing --------------------------------------------------------------------


def test_list_open_upcoming_then_fired(conn, people):
    fired_early = create(conn, new(TARGET, T0 - timedelta(hours=5)))[0]
    later = create(conn, new(TARGET, T0 + timedelta(hours=2)))[0]
    sooner = create(conn, new(TARGET, T0 + timedelta(hours=1)))[0]
    done = create(conn, new(TARGET, T0))[0]
    db.mark_fired(conn, fired_early)
    db.complete(conn, done, actor_id=TARGET)
    assert [r["id"] for r in db.list_open(conn, 6)] == [sooner, later, fired_early]


def test_list_open_filters(conn, people):
    to_target = create(conn, new(TARGET))[0]
    to_creator = create(conn, new(CREATOR))[0]
    db.set_timezone(conn, USER, "UTC")
    from_user = db.create_reminders(
        conn, creator_id=USER, channel_id=5, guild_id=6, message="m", targets=[new(TARGET)]
    )[0]
    ids = lambda rows: sorted(r["id"] for r in rows)
    assert ids(db.list_open(conn, 6, target_id=TARGET)) == [to_target, from_user]
    assert ids(db.list_open(conn, 6, creator_id=CREATOR)) == [to_target, to_creator]
    assert ids(db.list_open(conn, 6, target_id=TARGET, creator_id=USER)) == [from_user]
    assert db.list_open(conn, 999) == []  # other guilds


def test_open_siblings(conn, people):
    a, b, c = create(conn, new(TARGET), new(CREATOR), new(TARGET))
    [single] = create(conn, new(TARGET))
    assert [r["id"] for r in db.open_siblings(conn, db.get_reminder(conn, a))] == [b, c]
    db.cancel(conn, c, actor_id=ACTOR)
    assert [r["id"] for r in db.open_siblings(conn, db.get_reminder(conn, a))] == [b]
    assert db.open_siblings(conn, db.get_reminder(conn, single)) == []
