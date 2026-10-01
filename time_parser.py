"""Time and timezone parsing. No Discord imports."""

import zoneinfo
from functools import cache

# Shown when the autocomplete box is empty: the zones this server actually uses.
COMMON_ZONES = (
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "UTC",
)


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
