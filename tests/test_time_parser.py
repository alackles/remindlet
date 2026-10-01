from datetime import datetime, timezone

import pytest

from time_parser import (
    COMMON_ZONES,
    ParseError,
    extract_zone,
    find_zone,
    format_in_zone,
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
