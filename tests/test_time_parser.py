import pytest

from time_parser import COMMON_ZONES, find_zone, suggest_zones


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
