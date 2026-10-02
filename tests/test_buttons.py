import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import db
from cogs.reminders import ReminderButton, button_problem, reminder_buttons

CREATOR = 222222222222222222
TARGET = 333333333333333333
T0 = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
T0_UNIX = int(T0.timestamp())


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.set_timezone(conn, CREATOR, "America/New_York")
    db.set_timezone(conn, TARGET, "America/Chicago")
    yield conn
    conn.close()


@pytest.fixture
def fired(conn):
    """A reminder that has fired at T0, as a fresh button would see it."""
    [rid] = db.create_reminders(
        conn, creator_id=CREATOR, channel_id=5, guild_id=6, message="m",
        targets=[db.NewReminder(TARGET, T0, "America/Chicago", "x")],
    )
    db.mark_fired(conn, rid)
    return rid


# --- custom_id round trip ------------------------------------------------------


@pytest.mark.parametrize("action", ["s15", "s60", "done", "cancel"])
def test_custom_id_round_trips_through_template(action):
    button = ReminderButton(12, T0_UNIX, action)
    assert button.custom_id == f"rem:12:{T0_UNIX}:{action}"
    match = ReminderButton.__discord_ui_compiled_template__.fullmatch(button.custom_id)
    assert (int(match["id"]), int(match["at"]), match["action"]) == (12, T0_UNIX, action)


@pytest.mark.parametrize("custom_id", ["rem:12:abc:done", "rem:12:1:delete", "other:12:1:done"])
def test_template_ignores_foreign_ids(custom_id):
    assert ReminderButton.__discord_ui_compiled_template__.fullmatch(custom_id) is None


def test_view_has_spec_buttons_in_order():
    async def build():  # discord.py Views need a running event loop
        return reminder_buttons(12, T0)

    view = asyncio.run(build())
    assert [item.item.label for item in view.children] == ["Snooze 15m", "Snooze 1h", "Done ✓", "Cancel"]
    assert view.timeout is None


# --- Stale buttons -----------------------------------------------------------------


def test_fresh_button_is_live(conn, fired):
    assert button_problem(db.get_reminder(conn, fired), T0_UNIX) is None


def test_missing_reminder():
    assert button_problem(None, T0_UNIX) == "missing"


def test_done_or_cancelled_is_closed(conn, fired):
    db.complete(conn, fired, actor_id=TARGET)
    assert button_problem(db.get_reminder(conn, fired), T0_UNIX) == "closed"


def test_snoozed_since_message_is_moved(conn, fired):
    db.snooze(conn, fired, actor_id=TARGET, duration=timedelta(minutes=15), now=T0)
    assert button_problem(db.get_reminder(conn, fired), T0_UNIX) == "moved"


def test_old_message_after_refire_is_moved(conn, fired):
    # Snoozed, then fired again: the reminder is 'fired' once more, but this
    # button belongs to the earlier firing.
    db.snooze(conn, fired, actor_id=TARGET, duration=timedelta(minutes=15), now=T0)
    db.mark_fired(conn, fired)
    row = db.get_reminder(conn, fired)
    assert button_problem(row, T0_UNIX) == "moved"
    assert button_problem(row, T0_UNIX + 15 * 60) is None  # the new message's buttons


def test_rescheduled_to_future_is_moved(conn, fired):
    db.reschedule(
        conn, fired, actor_id=TARGET, fire_at=T0 + timedelta(days=1),
        original_tz="America/Chicago", original_time_str="x",
    )
    assert button_problem(db.get_reminder(conn, fired), T0_UNIX) == "moved"
