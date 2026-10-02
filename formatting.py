"""Message text for every bot post: confirmations, fired reminders, audit
notes, and /list. No Discord imports.

Mentions and timestamps are Discord markup: <@id> renders as @name, <#id> as
#channel, and <t:unix:t> as a time in each viewer's own timezone.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

# Fired this long after its time, a reminder is labeled late.
LATE_AFTER = timedelta(minutes=1)

# Discord's message limit is 2000 characters; leave room for the overflow line.
LIST_BUDGET = 1900

_LABELS = {
    "America/New_York": "ET",
    "US/Eastern": "ET",
    "America/Chicago": "CT",
    "US/Central": "CT",
    "America/Denver": "MT",
    "US/Mountain": "MT",
    "America/Los_Angeles": "PT",
    "US/Pacific": "PT",
    "UTC": "UTC",
}

_ETC_OFFSET = re.compile(r"Etc/GMT([+-])(\d+)")


def zone_label(zone: str, at: datetime) -> str:
    """Short label for display: "CT" for America/Chicago, "UTC-6" for Etc/GMT+6."""
    if label := _LABELS.get(zone):
        return label
    if m := _ETC_OFFSET.fullmatch(zone):
        return f"UTC{'-' if m.group(1) == '+' else '+'}{m.group(2)}"
    return at.astimezone(ZoneInfo(zone)).strftime("%Z")


def format_in_zone(dt: datetime, zone: str) -> str:
    """Format an aware datetime as a labeled local time, e.g. "9:00 AM CT"."""
    local = dt.astimezone(ZoneInfo(zone))
    return f"{local.strftime('%I:%M %p').lstrip('0')} {zone_label(zone, local)}"


def format_duration(duration: timedelta) -> str:
    """Compact form for display: `1h`, `1h 30m`, `2d 3h`."""
    minutes = int(duration.total_seconds()) // 60
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{n}{unit}" for n, unit in ((days, "d"), (hours, "h"), (minutes, "m")) if n]
    return " ".join(parts) or "0m"


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


def when(fire_at: datetime, zone: str, now: datetime) -> str:
    """The one way a reminder's time is shown: "9:00 AM CT [your time: …] Oct 1"."""
    return f"{format_in_zone(fire_at, zone)} {your_time(fire_at)} {short_date(fire_at, zone, now)}"


class Created(NamedTuple):
    """One target's line in a creation confirmation."""

    reminder_id: int
    target_id: int
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
        f"#{c.reminder_id} {mention(c.target_id)}: {when(c.fire_at, c.zone, now)}"
        for c in created
    ]
    return "\n".join(lines)


def fired(
    *,
    target_id: int | str,
    message: str,
    creator_name: str,
    fire_at: datetime,
    zone: str,
    now: datetime,
) -> str:
    lines = [
        f"⏰ {mention(target_id)}",
        f"TASK: {message}",
        f"FROM: {creator_name}",
        f"AT: {when(fire_at, zone, now)}",
    ]
    if now - fire_at > LATE_AFTER:
        # "-#" is Discord's small-text markdown.
        lines.append("-# ⚠️ Late: the bot was offline when this was due.")
    return "\n".join(lines)


def audit_note(
    *,
    header: str,
    target_id: int | str,
    message: str,
    fire_at: datetime | None = None,
    zone: str | None = None,
    now: datetime | None = None,
    reason: str | None = None,
    siblings: Sequence[tuple[str, int]] = (),
) -> str:
    """A reschedule/snooze/cancel/done note. AT appears when fire_at is given
    (with zone and now);
    siblings are (target name, reminder id) pairs for the ALSO lines."""
    lines = [header, f"FOR: {mention(target_id)}", f"TASK: {message}"]
    if fire_at is not None:
        lines.append(f"AT: {when(fire_at, zone, now)}")
    if reason:
        lines.append(f"REASON: {reason}")
    lines += [f"ALSO: {name}'s copy #{rid} is still active" for name, rid in siblings]
    return "\n".join(lines)


def _list_entry(row: Mapping[str, Any], now: datetime) -> str:
    fire_at = datetime.fromisoformat(row["fire_at"])
    zone = row["original_tz"]
    shown = when(fire_at, zone, now)
    if row["status"] == "fired":
        shown = f"was due {shown}"
    return (
        f"#{row['id']} {mention(row['target_id'])}: {shown}\n"
        f"-# TASK: {row['message']} · FROM: {mention(row['creator_id'])} · in <#{row['channel_id']}>"
    )


def reminder_list(rows: Sequence[Mapping[str, Any]], *, title: str, now: datetime) -> str:
    """/list output: upcoming, then fired-but-not-done, cut to fit one message.

    rows must already be in display order (db.list_open's order).
    """
    if not rows:
        return f"No open reminders{title}."
    upcoming = [r for r in rows if r["status"] != "fired"]
    fired = [r for r in rows if r["status"] == "fired"]
    out = f"**Open reminders{title}**"
    shown = 0
    for heading, section in (("Upcoming", upcoming), ("Fired, not marked done", fired)):
        if not section:
            continue
        block = f"\n\n**{heading}**"
        for row in section:
            entry = "\n" + _list_entry(row, now)
            if len(out) + len(block) + len(entry) > LIST_BUDGET:
                return out + block + f"\n\n…and {len(rows) - shown} more. Narrow it with `who:` or `from:`."
            block += entry
            shown += 1
        out += block
    return out


def dm_fallback(channel_id: int | str, guild_name: str | None) -> str:
    """Last line of a reminder delivered by DM because its channel is unreachable."""
    where = f"<#{channel_id}>" + (f" ({guild_name})" if guild_name else "")
    return f"-# Sent by DM: I can't post in {where} anymore."
