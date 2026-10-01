"""Message text for confirmations and fired reminders. No Discord imports.

Mentions and timestamps are Discord markup: <@id> renders as @name, <#id> as
#channel, and <t:unix:t> as a time in each viewer's own timezone.
"""

from datetime import datetime, timedelta
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


def confirmation(
    *,
    reminder_id: int,
    target_id: int,
    message: str,
    display: str,
    fire_at: datetime,
    zone: str,
    channel_id: int,
    creator_name: str,
    now: datetime,
) -> str:
    return (
        f'Created reminder #{reminder_id} for {mention(target_id)}: "{message}" — '
        f"{display} {your_time(fire_at)} {short_date(fire_at, zone, now)} "
        f"in <#{channel_id}> (from {creator_name})"
    )


def fired(
    *,
    target_id: int | str,
    message: str,
    creator_name: str,
    display: str,
    fire_at: datetime,
    now: datetime,
) -> str:
    text = f"⏰ {mention(target_id)} — {message} (from {creator_name}, {display}) {your_time(fire_at)}"
    if now - fire_at > LATE_AFTER:
        # "-#" is Discord's small-text markdown.
        text += "\n-# ⚠️ Late: the bot was offline when this was due."
    return text
