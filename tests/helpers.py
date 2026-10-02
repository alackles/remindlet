"""Shared test data: fake users by role (snowflake-sized IDs) and a reminder factory."""

from datetime import datetime, timezone

import db

USER = 111111111111111111  # no timezone set
CREATOR = 222222222222222222  # America/New_York (set by the conn fixture)
TARGET = 333333333333333333  # America/Chicago (set by the conn fixture)
T0 = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)  # 10 AM Chicago


def add(conn, fire_at=T0, target=TARGET):
    """Create one reminder from CREATOR and return its ID."""
    [rid] = db.create_reminders(
        conn, creator_id=CREATOR, channel_id=5, guild_id=6, message="do the thing",
        targets=[db.NewReminder(target, fire_at, "America/Chicago", "10:00 AM CT")],
    )
    return rid
