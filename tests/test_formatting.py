from datetime import datetime, timedelta, timezone

import pytest

import formatting

TARGET = 333333333333333333
FIRE_AT = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)  # 9 AM Chicago
UNIX = int(FIRE_AT.timestamp())


TARGET2 = 444444444444444444
FIRE_AT2 = FIRE_AT + timedelta(hours=1)  # 10 AM Chicago = 11 AM New York


def test_confirmation_single_target():
    text = formatting.confirmation(
        message="submit IRB revision",
        creator_name="Elliott",
        channel_id=42,
        created=[formatting.Created(12, TARGET, "9:00 AM CT", FIRE_AT, "America/Chicago")],
        now=FIRE_AT - timedelta(hours=2),
    )
    assert text == (
        "Created in <#42>\n"
        "TASK: submit IRB revision\n"
        "FROM: Elliott\n"
        f"#12 <@{TARGET}>: 9:00 AM CT [your time: <t:{UNIX}:t>] Oct 1"
    )


def test_confirmation_multi_target_has_one_line_each():
    text = formatting.confirmation(
        message="submit IRB revision",
        creator_name="Elliott",
        channel_id=42,
        created=[
            formatting.Created(12, TARGET, "9:00 AM CT", FIRE_AT, "America/Chicago"),
            formatting.Created(13, TARGET2, "11:00 AM ET", FIRE_AT2, "America/New_York"),
        ],
        now=FIRE_AT - timedelta(hours=2),
    )
    assert text.splitlines()[1:] == [
        "TASK: submit IRB revision",
        "FROM: Elliott",
        f"#12 <@{TARGET}>: 9:00 AM CT [your time: <t:{UNIX}:t>] Oct 1",
        f"#13 <@{TARGET2}>: 11:00 AM ET [your time: <t:{int(FIRE_AT2.timestamp())}:t>] Oct 1",
    ]


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
        f"⏰ <@{TARGET}>\n"
        "TASK: submit IRB revision\n"
        "FROM: Elliott\n"
        f"AT: 10:00 AM ET [your time: <t:{UNIX}:t>]"
    )


def test_fired_late_note_is_last_line():
    text = formatting.fired(
        target_id=TARGET, message="m", creator_name="E", display="x",
        fire_at=FIRE_AT, now=FIRE_AT + timedelta(hours=1),
    )
    assert text.splitlines()[-1].startswith("-# ⚠️ Late")


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
