"""Message text for confirmations and fired reminders. No Discord imports.

Mentions and timestamps are Discord markup: <@id> renders as @name, <#id> as
#channel, and <t:unix:t> as a time in each viewer's own timezone.
"""

from datetime import datetime, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

# Fired this long after its time, a reminder is labeled late.
LATE_AFTER = timedelta(minutes=1)


def mention(user_id: int | str) -> str:
    return f"<@{user_id}>"


def your_time(dt: datetime) -> str:
    return f"[your time: <t:{int(dt.timestamp())}:t>]"


def short_date(dt: datetime, zone: str, now: datetime) -> str:
    """"Oct 1", or "Jan 5, 2027" when the year isn't the current one."""
    tz = ZoneInfo(zone)
    local = dt.astimezone(tz)
    text = f"{local:%b} {local.day}"
    if local.year != now.astimezone(tz).year:
        text += f", {local.year}"
    return text


class Created(NamedTuple):
    """One target's line in a creation confirmation."""

    reminder_id: int
    target_id: int
    display: str
    fire_at: datetime
    zone: str


def confirmation(
    *,
    message: str,
    creator_name: str,
    channel_id: int,
    created: list[Created],
    now: datetime,
) -> str:
    """Shared TASK/FROM header, then one line per reminder (times can differ
    per target with `their time`)."""
    lines = [f"Created in <#{channel_id}>", f"TASK: {message}", f"FROM: {creator_name}"]
    lines += [
        f"#{c.reminder_id} {mention(c.target_id)}: {c.display} {your_time(c.fire_at)} "
        f"{short_date(c.fire_at, c.zone, now)}"
        for c in created
    ]
    return "\n".join(lines)


def fired(
    *,
    target_id: int | str,
    message: str,
    creator_name: str,
    display: str,
    fire_at: datetime,
    now: datetime,
) -> str:
    lines = [
        f"⏰ {mention(target_id)}",
        f"TASK: {message}",
        f"FROM: {creator_name}",
        f"AT: {display} {your_time(fire_at)}",
    ]
    if now - fire_at > LATE_AFTER:
        # "-#" is Discord's small-text markdown.
        lines.append("-# ⚠️ Late: the bot was offline when this was due.")
    return "\n".join(lines)
