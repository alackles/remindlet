from datetime import datetime, timedelta, timezone

import pytest

import formatting

TARGET = 333333333333333333
FIRE_AT = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)  # 9 AM Chicago
UNIX = int(FIRE_AT.timestamp())


def test_confirmation_matches_spec_format():
    text = formatting.confirmation(
        reminder_id=12,
        target_id=TARGET,
        message="submit IRB revision",
        display="9:00 AM CT",
        fire_at=FIRE_AT,
        zone="America/Chicago",
        channel_id=42,
        creator_name="Elliott",
        now=FIRE_AT - timedelta(hours=2),
    )
    assert text == (
        f'Created reminder #12 for <@{TARGET}>: "submit IRB revision" — '
        f"9:00 AM CT [your time: <t:{UNIX}:t>] Oct 1 in <#42> (from Elliott)"
    )


def test_fired_matches_spec_format():
    text = formatting.fired(
        target_id=TARGET,
        message="submit IRB revision",
        creator_name="Elliott",
        display="10:00 AM ET",
        fire_at=FIRE_AT,
        now=FIRE_AT + timedelta(seconds=2),
    )
    assert text == (
        f"⏰ <@{TARGET}> — submit IRB revision (from Elliott, 10:00 AM ET) [your time: <t:{UNIX}:t>]"
    )


@pytest.mark.parametrize(
    "delay, late",
    [(timedelta(0), False), (timedelta(seconds=59), False), (timedelta(minutes=5), True)],
)
def test_fired_late_note(delay, late):
    text = formatting.fired(
        target_id=TARGET, message="m", creator_name="E", display="x",
        fire_at=FIRE_AT, now=FIRE_AT + delay,
    )
    assert ("Late" in text) is late


@pytest.mark.parametrize(
    "fire_at, now, expected",
    [
        (FIRE_AT, FIRE_AT, "Oct 1"),
        (datetime(2027, 1, 5, 15, 0, tzinfo=timezone.utc), FIRE_AT, "Jan 5, 2027"),
        # 1 AM UTC on Jan 1 is still Dec 31 in Chicago: same year, no suffix.
        (datetime(2027, 1, 1, 1, 0, tzinfo=timezone.utc), FIRE_AT, "Dec 31"),
    ],
)
def test_short_date(fire_at, now, expected):
    assert formatting.short_date(fire_at, "America/Chicago", now) == expected
