import pytest

import db
from tests.helpers import CREATOR, TARGET


@pytest.fixture
def conn(tmp_path):
    """A fresh database where CREATOR and TARGET have timezones (USER doesn't)."""
    conn = db.connect(tmp_path / "test.db")
    db.set_timezone(conn, CREATOR, "America/New_York")
    db.set_timezone(conn, TARGET, "America/Chicago")
    yield conn
    conn.close()
