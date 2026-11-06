import pytest

from config import parse_ids


def test_parse_ids():
    assert parse_ids("111, 222,") == [111, 222]  # spaces and a trailing comma are fine
    assert parse_ids("") == []
    with pytest.raises(ValueError):
        parse_ids("111, my-server")
