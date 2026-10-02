import asyncio
from datetime import timedelta

import pytest

import db
from cogs.reminders import ReminderButton, button_problem, reminder_buttons
from tests.helpers import T0, TARGET, add

T0_UNIX = int(T0.timestamp())


@pytest.fixture
def fired(conn):
    """A reminder that has fired at T0, as a fresh button would see it."""
    rid = add(conn)
    db.mark_fired(conn, rid)
    return rid


@pytest.mark.parametrize("action", ["s15", "s60", "done", "cancel"])
def test_custom_id_round_trips_through_template(action):
    button = ReminderButton(12, T0_UNIX, action)
    match = ReminderButton.__discord_ui_compiled_template__.fullmatch(button.custom_id)
    assert (int(match["id"]), int(match["at"]), match["action"]) == (12, T0_UNIX, action)


def test_view_has_spec_buttons_in_order():
    async def build():  # discord.py Views need a running event loop
        return reminder_buttons(12, T0)

    view = asyncio.run(build())
    assert [item.item.label for item in view.children] == ["Snooze 15m", "Snooze 1h", "Done ✓", "Cancel"]


# --- Stale buttons -------------------------------------------------------------------


def test_fresh_button_is_live(conn, fired):
    assert button_problem(db.get_reminder(conn, fired), T0_UNIX) is None


def test_missing_reminder():
    assert button_problem(None, T0_UNIX) == "missing"


def test_done_reminder_is_closed(conn, fired):
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
