"""Time and timezone parsing. No Discord imports."""

import re
import zoneinfo
from datetime import datetime
from functools import cache
from zoneinfo import ZoneInfo

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


class ParseError(ValueError):
    """Input the user should rephrase. The message is shown to them as-is."""


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
