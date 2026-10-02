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
        created=[formatting.Created(12, TARGET, FIRE_AT, "America/Chicago")],
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
            formatting.Created(12, TARGET, FIRE_AT, "America/Chicago"),
            formatting.Created(13, TARGET2, FIRE_AT2, "America/New_York"),
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
        fire_at=FIRE_AT,
        zone="America/New_York",
        now=FIRE_AT + timedelta(seconds=2),
    )
    assert text == (
        f"⏰ <@{TARGET}>\n"
        "TASK: submit IRB revision\n"
        "FROM: Elliott\n"
        f"AT: 10:00 AM ET [your time: <t:{UNIX}:t>] Oct 1"
    )


def test_fired_late_note_is_last_line():
    text = formatting.fired(
        target_id=TARGET, message="m", creator_name="E", zone="America/Chicago",
        fire_at=FIRE_AT, now=FIRE_AT + timedelta(hours=1),
    )
    assert text.splitlines()[-1].startswith("-# ⚠️ Late")


@pytest.mark.parametrize(
    "delay, late",
    [(timedelta(0), False), (timedelta(seconds=59), False), (timedelta(minutes=5), True)],
)
def test_fired_late_note(delay, late):
    text = formatting.fired(
        target_id=TARGET, message="m", creator_name="E", zone="America/Chicago",
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


# --- Audit notes -----------------------------------------------------------------


def test_reschedule_note_matches_spec():
    text = formatting.audit_note(
        header="🔄 acacia rescheduled reminder #14",
        target_id=TARGET,
        message="do the thing",
        fire_at=FIRE_AT,
        zone="America/Chicago",
        now=FIRE_AT - timedelta(hours=2),
        reason="need more time",
        siblings=[("elliott", 15)],
    )
    assert text.splitlines() == [
        "🔄 acacia rescheduled reminder #14",
        f"FOR: <@{TARGET}>",
        "TASK: do the thing",
        f"AT: 9:00 AM CT [your time: <t:{UNIX}:t>] Oct 1",
        "REASON: need more time",
        "ALSO: elliott's copy #15 is still active",
    ]


def test_note_without_time_reason_or_siblings():
    text = formatting.audit_note(
        header="✅ acacia completed reminder #12", target_id=TARGET, message="submit IRB revision"
    )
    assert text.splitlines() == [
        "✅ acacia completed reminder #12",
        f"FOR: <@{TARGET}>",
        "TASK: submit IRB revision",
    ]


# --- /list ---------------------------------------------------------------------------


def row(rid, status="pending", fire_at=FIRE_AT, message="m"):
    return {
        "id": rid, "status": status, "fire_at": fire_at.isoformat(), "original_tz": "America/Chicago",
        "target_id": TARGET, "creator_id": 222, "channel_id": 42, "message": message,
    }


def test_list_sections_and_entry_format():
    text = formatting.reminder_list(
        [row(12), row(9, status="fired", fire_at=FIRE_AT - timedelta(days=1))],
        title="", now=FIRE_AT - timedelta(hours=1),
    )
    yesterday = int((FIRE_AT - timedelta(days=1)).timestamp())
    assert text.splitlines() == [
        "**Open reminders**",
        "",
        "**Upcoming**",
        f"#12 <@{TARGET}>: 9:00 AM CT [your time: <t:{UNIX}:t>] Oct 1",
        "-# TASK: m · FROM: <@222> · in <#42>",
        "",
        "**Fired, not marked done**",
        f"#9 <@{TARGET}>: was due 9:00 AM CT [your time: <t:{yesterday}:t>] Sep 30",
        "-# TASK: m · FROM: <@222> · in <#42>",
    ]


def test_list_omits_empty_section():
    text = formatting.reminder_list([row(12)], title="", now=FIRE_AT)
    assert "Fired" not in text


def test_empty_list_mentions_filters():
    assert formatting.reminder_list([], title=f" for <@{TARGET}>", now=FIRE_AT) == (
        f"No open reminders for <@{TARGET}>."
    )


def test_long_list_is_cut_with_count():
    rows = [row(i, message="x" * 150) for i in range(1, 41)]
    text = formatting.reminder_list(rows, title="", now=FIRE_AT)
    assert len(text) <= 2000
    shown = text.count("\n#")
    assert shown > 0
    assert text.endswith(f"…and {40 - shown} more. Narrow it with `who:` or `from:`.")


def test_fired_shows_year_when_not_current():
    next_year = datetime(2027, 1, 5, 15, 0, tzinfo=timezone.utc)
    text = formatting.fired(
        target_id=TARGET, message="m", creator_name="E", fire_at=next_year,
        zone="America/Chicago", now=datetime(2026, 12, 31, 15, 0, tzinfo=timezone.utc),
    )
    assert text.splitlines()[3].endswith("Jan 5, 2027")


def test_dm_fallback_line():
    assert formatting.dm_fallback(42, "Research Server") == (
        "-# Sent by DM: I can't post in <#42> (Research Server) anymore."
    )
    assert formatting.dm_fallback(42, None) == "-# Sent by DM: I can't post in <#42> anymore."
