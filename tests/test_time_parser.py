from datetime import datetime, timedelta, timezone

import pytest

from time_parser import (
    COMMON_ZONES,
    ParseError,
    extract_zone,
    find_zone,
    format_duration,
    format_in_zone,
    parse_duration,
    parse_when,
    suggest_zones,
    zone_label,
)

CHICAGO = "America/Chicago"
NEW_YORK = "America/New_York"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("America/Chicago", "America/Chicago"),
        ("america/chicago", "America/Chicago"),
        ("  America/New York ", "America/New_York"),
        ("US/Central", "US/Central"),
        ("utc", "UTC"),
    ],
)
def test_find_zone_accepts_iana_names(text, expected):
    assert find_zone(text) == expected


@pytest.mark.parametrize(
    "text",
    ["Chicago", "UTC-6", "CT", "EST", "MST", "Etc/GMT+6", "localtime", "Factory", "", "Mars/Olympus"],
)
def test_find_zone_rejects_everything_else(text):
    assert find_zone(text) is None


def test_suggest_empty_query_gives_common_zones():
    assert suggest_zones("") == list(COMMON_ZONES)


def test_suggest_matches_city_part():
    assert suggest_zones("chicago") == ["America/Chicago"]
    assert "America/New_York" in suggest_zones("new york")


def test_suggest_ranks_prefix_matches_first():
    # "Chile/..." starts with "ch" but sorts after cities like America/Chicago;
    # "Europe/Zurich" only contains "ch" and comes after both.
    results = suggest_zones("ch", limit=200)
    assert results[0] == "America/Chicago"
    assert results.index("Chile/Continental") < results.index("Europe/Zurich")


def test_suggest_respects_limit():
    assert len(suggest_zones("a")) == 25


def test_suggestions_are_all_accepted_by_find_zone():
    for zone in suggest_zones("america", limit=200):
        assert find_zone(zone) == zone


# --- Zone extraction -------------------------------------------------------
# Creator is in New York (Elliott), target in Chicago (Acacia).


@pytest.mark.parametrize(
    "text, zone, rest",
    [
        ("9am", NEW_YORK, "9am"),
        ("9am my time", NEW_YORK, "9am"),
        ("9am their time", CHICAGO, "9am"),
        ("tomorrow 9am THEIR TIME", CHICAGO, "tomorrow 9am"),
        ("their time 9am", CHICAGO, "9am"),
        ("9am ET", NEW_YORK, "9am"),
        ("10:00 AM ET", NEW_YORK, "10:00 AM"),
        ("9am ct", CHICAGO, "9am"),
        ("9am EST", NEW_YORK, "9am"),
        ("9am PDT", "America/Los_Angeles", "9am"),
        ("9am UTC", "UTC", "9am"),
        ("9am GMT", "UTC", "9am"),
        ("9am UTC-6", "Etc/GMT+6", "9am"),
        ("9am UTC - 6", "Etc/GMT+6", "9am"),
        ("9am UTC−6", "Etc/GMT+6", "9am"),
        ("9am utc+2", "Etc/GMT-2", "9am"),
        ("9am UTC+0", "UTC", "9am"),
        ("9am UTC+14", "Etc/GMT-14", "9am"),
        ("9am europe/london", "Europe/London", "9am"),
        ("oct 3 9am", NEW_YORK, "oct 3 9am"),
        ("10/3 9am", NEW_YORK, "10/3 9am"),
    ],
)
def test_extract_zone(text, zone, rest):
    assert extract_zone(text, creator_tz=NEW_YORK, target_tz=CHICAGO) == (zone, rest)


@pytest.mark.parametrize(
    "text",
    ["9am ET their time", "9am ET PT", "9am my time their time", "9am UTC-6 ET"],
)
def test_extract_zone_rejects_more_than_one_zone(text):
    with pytest.raises(ParseError, match="at most one"):
        extract_zone(text, creator_tz=NEW_YORK, target_tz=CHICAGO)


@pytest.mark.parametrize("text", ["9am UTC-13", "9am UTC+15"])
def test_extract_zone_rejects_impossible_offsets(text):
    with pytest.raises(ParseError, match="range"):
        extract_zone(text, creator_tz=NEW_YORK, target_tz=CHICAGO)


# --- Display -----------------------------------------------------------------

JULY = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
JANUARY = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "zone, at, label",
    [
        (NEW_YORK, JULY, "ET"),
        (CHICAGO, JANUARY, "CT"),
        ("US/Central", JULY, "CT"),
        ("UTC", JULY, "UTC"),
        ("Etc/GMT+6", JULY, "UTC-6"),
        ("Etc/GMT-14", JULY, "UTC+14"),
        ("Europe/London", JULY, "BST"),
        ("Europe/London", JANUARY, "GMT"),
    ],
)
def test_zone_label(zone, at, label):
    assert zone_label(zone, at) == label


def test_format_in_zone():
    assert format_in_zone(JULY, NEW_YORK) == "10:00 AM ET"
    assert format_in_zone(JANUARY, CHICAGO) == "9:00 AM CT"
    assert format_in_zone(JULY, "Etc/GMT+6") == "8:00 AM UTC-6"


# --- parse_when --------------------------------------------------------------
# "Now" is Wed Oct 1 2026, 10:40 AM Chicago = 11:40 AM New York = 15:40 UTC.
# Creator is Elliott (New York), target is Acacia (Chicago), as in the spec.

NOW = datetime(2026, 10, 1, 15, 40, tzinfo=timezone.utc)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def parse(text, now=NOW, creator_tz=NEW_YORK, target_tz=CHICAGO):
    return parse_when(text, creator_tz=creator_tz, target_tz=target_tz, now=now)


@pytest.mark.parametrize(
    "text, fire_at, zone, display",
    [
        # Spec examples
        ("9am their time", utc(2026, 10, 2, 14, 0), CHICAGO, "9:00 AM CT"),
        ("9am my time", utc(2026, 10, 2, 13, 0), NEW_YORK, "9:00 AM ET"),
        ("9am UTC-6", utc(2026, 10, 2, 15, 0), "Etc/GMT+6", "9:00 AM UTC-6"),
        ("9am ET", utc(2026, 10, 2, 13, 0), NEW_YORK, "9:00 AM ET"),
        ("10:00 AM ET", utc(2026, 10, 2, 14, 0), NEW_YORK, "10:00 AM ET"),
        # Default zone is the creator's
        ("3pm", utc(2026, 10, 1, 19, 0), NEW_YORK, "3:00 PM ET"),
        ("3pm their time", utc(2026, 10, 1, 20, 0), CHICAGO, "3:00 PM CT"),
        # Natural language with dates
        ("tomorrow 9am", utc(2026, 10, 2, 13, 0), NEW_YORK, "9:00 AM ET"),
        ("9am tomorrow", utc(2026, 10, 2, 13, 0), NEW_YORK, "9:00 AM ET"),
        ("friday 3pm", utc(2026, 10, 2, 19, 0), NEW_YORK, "3:00 PM ET"),
        ("friday at noon", utc(2026, 10, 2, 16, 0), NEW_YORK, "12:00 PM ET"),
        ("oct 3 9am", utc(2026, 10, 3, 13, 0), NEW_YORK, "9:00 AM ET"),
        ("10/3 9:30am", utc(2026, 10, 3, 13, 30), NEW_YORK, "9:30 AM ET"),
        ("in 3 days at 9am", utc(2026, 10, 4, 13, 0), NEW_YORK, "9:00 AM ET"),
        ("jan 5 9am", utc(2027, 1, 5, 14, 0), NEW_YORK, "9:00 AM ET"),
        ("21:00", utc(2026, 10, 2, 1, 0), NEW_YORK, "9:00 PM ET"),
        # Relative
        ("in 2 hours", utc(2026, 10, 1, 17, 40), NEW_YORK, "1:40 PM ET"),
        ("in 15 minutes", utc(2026, 10, 1, 15, 55), NEW_YORK, "11:55 AM ET"),
        ("90m", utc(2026, 10, 1, 17, 10), NEW_YORK, "1:10 PM ET"),
        ("in an hour", utc(2026, 10, 1, 16, 40), NEW_YORK, "12:40 PM ET"),
    ],
)
def test_parse_when(text, fire_at, zone, display):
    result = parse(text)
    assert result.fire_at == fire_at
    assert result.zone == zone
    assert result.display == display


def test_fire_at_is_utc():
    assert parse("3pm").fire_at.tzinfo == timezone.utc


def test_passed_time_today_rolls_to_tomorrow():
    # 11am Chicago hasn't happened yet (it's 10:40 there); 9am has.
    assert parse("11am their time").fire_at == utc(2026, 10, 1, 16, 0)
    assert parse("9am their time").fire_at == utc(2026, 10, 2, 14, 0)


def test_their_time_differs_per_target():
    # Same expression, two targets: each fires at 9 AM in their own zone.
    acacia = parse("9am their time", target_tz=CHICAGO)
    elliott = parse("9am their time", target_tz=NEW_YORK)
    assert acacia.fire_at - elliott.fire_at == timedelta(hours=1)


def test_abbreviation_follows_dst():
    july = utc(2026, 7, 1, 12, 0)  # 8 AM in New York (EDT)
    assert parse("9am EST", now=july).fire_at == utc(2026, 7, 1, 13, 0)


def test_clock_time_across_dst_change_keeps_wall_time():
    # US DST ends Sun Nov 1 2026 at 2 AM. 9 AM before is UTC-5, after is UTC-6.
    sat = utc(2026, 10, 31, 15, 40)  # Sat 10:40 AM CDT
    assert parse("tomorrow 9am", now=sat, creator_tz=CHICAGO).fire_at == utc(2026, 11, 1, 15, 0)


def test_relative_time_across_dst_change_is_real_elapsed_time():
    # 12:30 AM CDT on Nov 1: two real hours later the clock reads 1:30 AM CST.
    night = utc(2026, 11, 1, 5, 30)
    result = parse("in 2 hours", now=night, creator_tz=CHICAGO)
    assert result.fire_at == utc(2026, 11, 1, 7, 30)
    assert result.display == "1:30 AM CT"


@pytest.mark.parametrize("text", ["friday", "tomorrow", "oct 3", "in 3 days", "next week"])
def test_date_without_time_is_rejected(text):
    with pytest.raises(ParseError, match="time of day"):
        parse(text)


@pytest.mark.parametrize("text", ["9", "at 9", "monday at 9"])
def test_bare_number_is_rejected(text):
    with pytest.raises(ParseError, match="ambiguous"):
        parse(text)


@pytest.mark.parametrize(
    "text", ["yesterday 9am", "today 9am", "sept 30 2026 3pm", "9/30/2026 3pm", "oct 1 2026 9am"]
)
def test_past_is_rejected(text):
    with pytest.raises(ParseError, match="in the past"):
        parse(text)


def test_month_day_without_year_means_next_occurrence():
    # Yesterday's date without a year is next year's, like "jan 5" in October.
    assert parse("sept 30 3pm").fire_at == utc(2027, 9, 30, 19, 0)


@pytest.mark.parametrize(
    "text", ["asdf 9am", "next friday 3pm", "9am blorp", "in half an hour", "tonight 9pm-ish"]
)
def test_unparseable_is_rejected(text):
    with pytest.raises(ParseError):
        parse(text)


@pytest.mark.parametrize("text", ["", "   ", "ET", "their time"])
def test_no_time_at_all_is_rejected(text):
    with pytest.raises(ParseError, match="doesn't say when"):
        parse(text)


@pytest.mark.parametrize("text", ["9am CEST", "9am UTC+5:30"])
def test_unsupported_zone_is_rejected(text):
    with pytest.raises(ParseError):
        parse(text)


def test_naive_now_is_a_programming_error():
    with pytest.raises(ValueError, match="aware"):
        parse("9am", now=datetime(2026, 10, 1, 10, 40))


# --- Snooze durations --------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("15m", timedelta(minutes=15)),
        ("1h", timedelta(hours=1)),
        ("2H", timedelta(hours=2)),
        ("1h30m", timedelta(minutes=90)),
        ("1h 30m", timedelta(minutes=90)),
        ("90 minutes", timedelta(minutes=90)),
        ("1 hour and 15 mins", timedelta(minutes=75)),
        ("1d", timedelta(days=1)),
        ("2 days", timedelta(days=2)),
        ("30d", timedelta(days=30)),
    ],
)
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "soon", "15", "1 week", "1h later", "0m", "31d", "-1h"])
def test_parse_duration_rejects(text):
    with pytest.raises(ParseError):
        parse_duration(text)


@pytest.mark.parametrize(
    "duration, text",
    [
        (timedelta(minutes=15), "15m"),
        (timedelta(hours=1), "1h"),
        (timedelta(minutes=90), "1h 30m"),
        (timedelta(days=2, hours=3), "2d 3h"),
    ],
)
def test_format_duration(duration, text):
    assert format_duration(duration) == text
