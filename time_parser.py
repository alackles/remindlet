"""Time and timezone parsing. No Discord imports."""

import re
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import cache
from zoneinfo import ZoneInfo

from dateparser.date import DateDataParser

# Shown when the autocomplete box is empty: the zones this server actually uses.
COMMON_ZONES = (
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "UTC",
)

# US abbreviations follow DST: "EST" in July still means New York wall-clock time.
_ABBREVIATIONS = {
    **dict.fromkeys(("et", "est", "edt"), "America/New_York"),
    **dict.fromkeys(("ct", "cst", "cdt"), "America/Chicago"),
    **dict.fromkeys(("mt", "mst", "mdt"), "America/Denver"),
    **dict.fromkeys(("pt", "pst", "pdt"), "America/Los_Angeles"),
    **dict.fromkeys(("utc", "gmt"), "UTC"),
}

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

_QUALIFIER = re.compile(r"\b(their|my)\s+time\b", re.IGNORECASE)
_OFFSET_SPACING = re.compile(r"\b(utc|gmt)\s*([+-])\s*(\d+)\b", re.IGNORECASE)
_OFFSET = re.compile(r"(?:utc|gmt)([+-])(\d+)", re.IGNORECASE)
_ETC_OFFSET = re.compile(r"Etc/GMT([+-])(\d+)")

# Does the expression say when in the day? A date alone ("friday") doesn't.
_CLOCK_TIME = re.compile(
    r"\d\s*(?:am|pm|a\.m\.|p\.m\.)|\d:\d{2}|\bnoon\b|\bmidnight\b", re.IGNORECASE
)
_RELATIVE_TIME = re.compile(
    r"\d\s*(?:m|mins?|minutes?|h|hrs?|hours?)\b|\ban?\s+(?:hour|minute)\b", re.IGNORECASE
)
_TODAY = re.compile(r"\btoday\b", re.IGNORECASE)

EXAMPLES = "Try `9am`, `tomorrow 3pm`, `friday 9:30am ET`, or `in 2 hours`."


class ParseError(ValueError):
    """Input the user should rephrase. The message is shown to them as-is."""


@dataclass(frozen=True)
class ParsedTime:
    fire_at: datetime  # aware, UTC
    zone: str  # IANA zone the time was given in (reminders.original_tz)


@cache
def _zones() -> dict[str, str]:
    """Selectable IANA zones, keyed by lowercase name.

    Only Area/Location names plus UTC. This drops fixed-offset zones that look
    like regions but ignore daylight saving (EST, MST, Etc/GMT+6) and system
    entries (localtime, Factory).
    """
    names = {
        z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith("Etc/")
    }
    names.add("UTC")
    return {z.lower(): z for z in names}


def _normalize(text: str) -> str:
    return text.strip().replace(" ", "_").lower()


def find_zone(name: str) -> str | None:
    """Return the canonical zone name for case-insensitive input, or None."""
    return _zones().get(_normalize(name))


def suggest_zones(query: str, limit: int = 25) -> list[str]:
    """Zones matching a partial name, best matches first.

    Matches at the start of the full name or of the city part (so "chi" finds
    America/Chicago) rank above matches anywhere else in the name.
    """
    q = _normalize(query)
    if not q:
        return list(COMMON_ZONES)
    zones = _zones()
    starts = sorted(
        z for key, z in zones.items() if key.startswith(q) or key.rsplit("/", 1)[-1].startswith(q)
    )
    contains = sorted(z for key, z in zones.items() if q in key and z not in starts)
    return (starts + contains)[:limit]


def _zone_for_token(token: str) -> str | None:
    """Map one word of a time expression to an IANA zone, if it names one."""
    if zone := _ABBREVIATIONS.get(token.lower()):
        return zone
    if m := _OFFSET.fullmatch(token):
        sign, hours = m.group(1), int(m.group(2))
        if hours == 0:
            return "UTC"
        # IANA's Etc/GMT names invert the sign: UTC-6 is Etc/GMT+6.
        if (sign == "-" and hours <= 12) or (sign == "+" and hours <= 14):
            return f"Etc/GMT{'+' if sign == '-' else '-'}{hours}"
        raise ParseError(f"`{token}` is outside the range of real UTC offsets.")
    if "/" in token:
        return find_zone(token)
    return None


def extract_zone(text: str, *, creator_tz: str, target_tz: str) -> tuple[str, str]:
    """Split a time expression into (IANA zone, remaining time text).

    Handles `my time`, `their time`, and explicit zones. With none of these,
    the creator's zone applies.
    """
    text = _OFFSET_SPACING.sub(r"\1\2\3", text.replace("−", "-"))
    zones: list[str] = []
    for m in _QUALIFIER.finditer(text):
        zones.append(target_tz if m.group(1).lower() == "their" else creator_tz)
    text = _QUALIFIER.sub(" ", text)

    remaining = []
    for token in text.split():
        zone = _zone_for_token(token)
        if zone is None:
            remaining.append(token)
        else:
            zones.append(zone)

    if len(zones) > 1:
        raise ParseError(
            "Give at most one timezone: `my time`, `their time`, or a zone like `ET`."
        )
    return (zones[0] if zones else creator_tz), " ".join(remaining)


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


def _dateparse(text: str, base: datetime) -> datetime | None:
    """Parse with dateparser relative to a naive base; returns naive or None."""
    parser = DateDataParser(
        languages=["en"],
        settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": base},
    )
    return parser.get_date_data(text).date_obj


def parse_when(text: str, *, creator_tz: str, target_tz: str, now: datetime) -> ParsedTime:
    """Turn a time expression like "tomorrow 9am their time" into a fire time.

    Called once per target, since `their time` depends on the target. Raises
    ParseError with a user-facing message if the input can't be used.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    zone, rest = extract_zone(text, creator_tz=creator_tz, target_tz=target_tz)
    if not rest:
        raise ParseError(f"`{text}` doesn't say when. {EXAMPLES}")

    has_clock = bool(_CLOCK_TIME.search(rest))
    if not has_clock and not _RELATIVE_TIME.search(rest):
        raise ParseError(
            f"`{text}` needs a time of day, e.g. `friday 9am` or `in 2 hours`. "
            "(Bare numbers like `9` are ambiguous; use `9am` or `21:00`.)"
        )

    tz = ZoneInfo(zone)
    if has_clock:
        # Wall-clock arithmetic in the target zone; zoneinfo resolves the offset.
        base = now.astimezone(tz).replace(tzinfo=None)
    else:
        # Purely relative ("in 2 hours"): count real elapsed time, immune to DST.
        base = now.astimezone(timezone.utc).replace(tzinfo=None)
    wall = _dateparse(rest, base)
    if wall is None:
        raise ParseError(f"I couldn't understand `{text}`. {EXAMPLES}")
    if wall.tzinfo is not None:
        # dateparser found a zone word we don't support (e.g. "CEST").
        raise ParseError(
            f"I don't recognize the timezone in `{text}`. Use `my time`, `their time`, "
            "a US zone like `ET`, `UTC-6`, or a name like `Europe/London`."
        )

    if not has_clock:
        fire_at = wall.replace(tzinfo=timezone.utc)
    else:
        if wall <= base and wall.date() == base.date() and not _TODAY.search(rest):
            # "9am" said at 10:40 means tomorrow, but "oct 1 2026 9am" stays
            # put. If shifting the base a day shifts the result, no date was given.
            next_day = wall + timedelta(days=1)
            if _dateparse(rest, base + timedelta(days=1)) == next_day:
                wall = next_day
        fire_at = wall.replace(tzinfo=tz).astimezone(timezone.utc)

    if fire_at <= now:
        raise ParseError(f"`{text}` is in the past ({format_in_zone(fire_at, zone)}).")
    return ParsedTime(fire_at=fire_at, zone=zone)


_DURATION_PART = re.compile(
    # Longest unit names first, or "d" would match the start of "days".
    r"(\d+)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m)", re.IGNORECASE
)
_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60}
MAX_SNOOZE = timedelta(days=30)


def parse_duration(text: str) -> timedelta:
    """Parse a snooze length like `15m`, `1h30m`, `90 minutes`, or `1 day`."""
    compact = re.sub(r"\s+", " ", text.strip().lower())
    parts = list(_DURATION_PART.finditer(compact))
    leftover = _DURATION_PART.sub("", compact).replace("and", "").replace(",", "").strip()
    if not parts or leftover:
        raise ParseError(f"`{text}` isn't a duration. Try `15m`, `1h`, `1h30m`, or `1d`.")
    total = timedelta(
        seconds=sum(int(m.group(1)) * _UNIT_SECONDS[m.group(2)[0]] for m in parts)
    )
    if total <= timedelta(0):
        raise ParseError("Snooze for at least a minute.")
    if total > MAX_SNOOZE:
        raise ParseError("Snoozes are capped at 30 days; use `/reschedule` for longer.")
    return total


def format_duration(duration: timedelta) -> str:
    """Compact form for display: `1h`, `1h 30m`, `2d 3h`."""
    minutes = int(duration.total_seconds()) // 60
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{n}{unit}" for n, unit in ((days, "d"), (hours, "h"), (minutes, "m")) if n]
    return " ".join(parts) or "0m"
