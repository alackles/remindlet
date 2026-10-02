import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import db
from tests.helpers import CREATOR, T0, TARGET, USER, add

ACTOR = USER  # anyone can change anyone's reminder


def batch(conn, *targets):
    """One /remind with several targets: (target_id, fire_at) pairs."""
    return db.create_reminders(
        conn, creator_id=CREATOR, channel_id=5, guild_id=6, message="do the thing",
        targets=[db.NewReminder(t, at, "America/Chicago") for t, at in targets],
    )


def log_rows(conn, rid):
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT action, actor_id, reason, old_fire_at, new_fire_at FROM reminder_log "
            "WHERE reminder_id = ? ORDER BY id",
            (rid,),
        )
    ]


# --- Storage ---------------------------------------------------------------------


def test_set_timezone_returns_previous(conn):
    assert db.get_timezone(conn, USER) is None
    assert db.set_timezone(conn, USER, "America/Chicago") is None
    assert db.set_timezone(conn, USER, "America/New_York") == "America/Chicago"
    assert db.get_timezone(conn, USER) == "America/New_York"


def test_data_survives_reconnect(tmp_path):
    # Milestones 1 and 3: timezones and pending reminders outlive a restart.
    path = tmp_path / "test.db"
    conn = db.connect(path)
    db.set_timezone(conn, CREATOR, "America/New_York")
    db.set_timezone(conn, TARGET, "America/Chicago")
    rid = add(conn)
    conn.close()
    conn = db.connect(path)
    assert db.get_timezone(conn, TARGET) == "America/Chicago"
    assert [r["id"] for r in db.due_reminders(conn, T0)] == [rid]
    conn.close()


def test_migrates_version_1_snoozed_to_pending(tmp_path):
    # Build a version-1 database: same tables, but 'snoozed' was a status.
    path = tmp_path / "v1.db"
    v1 = sqlite3.connect(path)
    v1.executescript(
        db.SCHEMA.replace("'pending', 'fired', 'done'", "'pending', 'fired', 'snoozed', 'done'")
        .replace(f"user_version = {db.SCHEMA_VERSION}", "user_version = 1")
    )
    v1.execute("INSERT INTO users VALUES ('1', 'UTC', 'x')")
    v1.execute(
        "INSERT INTO reminders (creator_id, target_id, channel_id, guild_id, message, fire_at,"
        " created_at, status, original_tz, original_time_str)"
        " VALUES ('1', '1', '5', '6', 'm', ?, 'x', 'snoozed', 'UTC', 'x')",
        (db.to_iso(T0),),
    )
    v1.execute("INSERT INTO reminder_log (reminder_id, action, timestamp) VALUES (1, 'snoozed', 'x')")
    v1.commit()
    v1.close()

    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert db.get_reminder(conn, 1)["status"] == "pending"
    assert [r["id"] for r in db.due_reminders(conn, T0)] == [1]  # still scheduled
    assert len(log_rows(conn, 1)) == 1  # history kept
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE reminders SET status = 'snoozed' WHERE id = 1")
    conn.close()


def test_to_iso_stores_utc():
    chicago = datetime(2026, 10, 1, 9, 0, tzinfo=ZoneInfo("America/Chicago"))
    assert db.to_iso(chicago) == "2026-10-01T14:00:00+00:00"


# --- Creating ----------------------------------------------------------------------


def test_create_single_reminder(conn):
    rid = add(conn)
    row = db.get_reminder(conn, rid)
    assert (row["creator_id"], row["target_id"], row["status"]) == (str(CREATOR), str(TARGET), "pending")
    assert row["batch_id"] is None
    assert db.from_iso(row["fire_at"]) == T0
    assert row["original_time_str"] == "10:00 AM CT"  # filled in by db
    assert log_rows(conn, rid) == [("created", str(CREATOR), None, None, None)]


def test_multi_target_shares_batch_id_but_keeps_own_times(conn):
    later = T0 + timedelta(hours=1)
    a, b = (db.get_reminder(conn, i) for i in batch(conn, (TARGET, T0), (CREATOR, later)))
    assert a["batch_id"] is not None and a["batch_id"] == b["batch_id"]
    assert db.from_iso(b["fire_at"]) == later


def test_create_requires_timezones_and_is_all_or_nothing(conn):
    # USER has no timezone, so the database refuses, and TARGET's half isn't kept.
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        batch(conn, (TARGET, T0), (USER, T0))
    assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM reminder_log").fetchone()[0] == 0


# --- Firing ------------------------------------------------------------------------


def test_due_reminders(conn):
    late, now_, _future = (add(conn, T0 + timedelta(seconds=s)) for s in (-3600, 0, 1))
    assert [r["id"] for r in db.due_reminders(conn, T0)] == [late, now_]


@pytest.mark.parametrize("status", ["fired", "done", "cancelled"])
def test_inactive_reminders_are_never_due(conn, status):
    rid = add(conn)
    conn.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, rid))
    assert db.due_reminders(conn, T0) == []


# --- Changing open reminders -----------------------------------------------------------


def test_reschedule_moves_time_and_display_zone(conn):
    rid = add(conn)
    db.mark_fired(conn, rid)  # fired reminders are still open
    later = T0 + timedelta(days=1)
    row = db.reschedule(
        conn, rid, actor_id=ACTOR, fire_at=later, original_tz="America/New_York", reason="sick",
    )
    assert (row["status"], row["original_tz"], row["original_time_str"]) == (
        "pending", "America/New_York", "11:00 AM ET"
    )
    assert db.from_iso(row["fire_at"]) == later
    assert log_rows(conn, rid)[-1] == ("rescheduled", str(ACTOR), "sick", db.to_iso(T0), db.to_iso(later))


def test_snooze_pending_counts_from_due_time(conn):
    rid = add(conn, T0 + timedelta(hours=2))
    row = db.snooze(conn, rid, actor_id=ACTOR, duration=timedelta(hours=1), now=T0)
    assert row["status"] == "pending"
    assert db.from_iso(row["fire_at"]) == T0 + timedelta(hours=3)


def test_snooze_fired_counts_from_now_and_fires_again(conn):
    rid = add(conn)
    db.mark_fired(conn, rid)
    now = T0 + timedelta(minutes=40)
    row = db.snooze(conn, rid, actor_id=ACTOR, duration=timedelta(minutes=15), now=now)
    assert db.from_iso(row["fire_at"]) == now + timedelta(minutes=15)
    assert [r["id"] for r in db.due_reminders(conn, now + timedelta(minutes=15))] == [rid]


def test_cancel_and_complete_close_the_reminder(conn):
    a, b = add(conn), add(conn)
    assert db.cancel(conn, a, actor_id=ACTOR, reason="not needed")["status"] == "cancelled"
    assert db.complete(conn, b, actor_id=TARGET)["status"] == "done"
    assert db.due_reminders(conn, T0) == []
    assert log_rows(conn, a)[-1] == ("cancelled", str(ACTOR), "not needed", None, None)


def test_closed_reminder_is_left_alone(conn):
    # Callers check first; the status guard makes a slip a no-op, not a reopen.
    rid = add(conn)
    assert db.closed_by(conn, rid) is None
    db.complete(conn, rid, actor_id=TARGET)
    before = (tuple(db.get_reminder(conn, rid)), len(log_rows(conn, rid)))
    db.reschedule(conn, rid, actor_id=ACTOR, fire_at=T0, original_tz="UTC")
    db.snooze(conn, rid, actor_id=ACTOR, duration=timedelta(hours=1), now=T0)
    db.cancel(conn, rid, actor_id=ACTOR)
    assert (tuple(db.get_reminder(conn, rid)), len(log_rows(conn, rid))) == before
    assert db.closed_by(conn, rid) == str(TARGET)


# --- Listing ----------------------------------------------------------------------------


def test_list_open_upcoming_then_fired(conn):
    fired_early, later, sooner, done = (add(conn, T0 + timedelta(hours=h)) for h in (-5, 2, 1, 0))
    db.mark_fired(conn, fired_early)
    db.complete(conn, done, actor_id=TARGET)
    assert [r["id"] for r in db.list_open(conn, 6)] == [sooner, later, fired_early]


def test_list_open_filters(conn):
    to_target, to_creator = add(conn), add(conn, target=CREATOR)
    db.set_timezone(conn, USER, "UTC")
    [from_user] = db.create_reminders(
        conn, creator_id=USER, channel_id=5, guild_id=6, message="m",
        targets=[db.NewReminder(TARGET, T0, "UTC")],
    )
    ids = lambda rows: sorted(r["id"] for r in rows)
    assert ids(db.list_open(conn, 6, target_id=TARGET)) == [to_target, from_user]
    assert ids(db.list_open(conn, 6, creator_id=CREATOR)) == [to_target, to_creator]
    assert ids(db.list_open(conn, 6, target_id=TARGET, creator_id=USER)) == [from_user]
    assert db.list_open(conn, 999) == []  # other guilds


def test_open_siblings(conn):
    a, b, c = batch(conn, (TARGET, T0), (CREATOR, T0), (TARGET, T0))
    single = add(conn)
    assert [r["id"] for r in db.open_siblings(conn, db.get_reminder(conn, a))] == [b, c]
    db.cancel(conn, c, actor_id=ACTOR)
    assert [r["id"] for r in db.open_siblings(conn, db.get_reminder(conn, a))] == [b]
    assert db.open_siblings(conn, db.get_reminder(conn, single)) == []
