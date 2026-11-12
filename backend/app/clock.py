"""Time helpers.

Every timestamp in the database is an INTEGER epoch-milliseconds value in UTC.
SQLite has no timezone type, so storing ints avoids parsing and comparison bugs.
ISO strings are produced only at the API boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone


def now_ms() -> int:
    """Current UTC time as epoch milliseconds."""
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def to_iso(ms: int | None) -> str | None:
    """Convert epoch milliseconds to an ISO-8601 UTC string, or None."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
