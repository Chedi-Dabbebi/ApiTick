"""Database operations: monitor CRUD, due-monitor selection, dashboard aggregates.

Ownership is enforced here (every lookup takes ``user_id``), so routes cannot
accidentally expose another user's monitors once auth lands.
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from .checker import assert_public_url
from .clock import now_ms
from .models import Check, Incident, Monitor
from .schemas import (
    DashboardSummary,
    MonitorCreate,
    MonitorStats,
    MonitorSummary,
    MonitorUpdate,
    RecentIncident,
    SeriesPoint,
)

DEFAULT_WINDOW_HOURS = 24


def normalize_body_assertion(value: str | None) -> str | None:
    """Blank input means "no assertion", so the database stores NULL, not ""."""
    if value is None:
        return None
    value = value.strip()
    return value or None


# --------------------------------------------------------------------------- #
# Monitors
# --------------------------------------------------------------------------- #
def list_monitors(session: Session, user_id: int) -> list[Monitor]:
    return list(
        session.scalars(
            select(Monitor)
            .where(Monitor.user_id == user_id)
            .order_by(Monitor.created_at, Monitor.id)
        ).all()
    )


def get_monitor(session: Session, user_id: int, monitor_id: int) -> Monitor | None:
    return session.scalar(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user_id)
    )


def create_monitor(session: Session, user_id: int, data: MonitorCreate) -> Monitor:
    """Validate the URL (SSRF guard) and schedule the first check immediately.

    Raises ``BlockedURLError`` if the URL is not a public http(s) endpoint.
    """
    assert_public_url(data.url)

    now = now_ms()
    monitor = Monitor(
        user_id=user_id,
        name=data.name,
        url=data.url,
        expected_body_contains=normalize_body_assertion(data.expected_body_contains),
        check_interval_seconds=data.check_interval_seconds,
        is_active=True,
        current_status="unknown",
        next_check_at=now,
        created_at=now,
    )
    session.add(monitor)
    session.commit()
    return monitor


def update_monitor(session: Session, monitor: Monitor, data: MonitorUpdate) -> Monitor:
    now = now_ms()

    if data.name is not None:
        monitor.name = data.name

    if data.url is not None and data.url != monitor.url:
        assert_public_url(data.url)
        monitor.url = data.url
        # A new target deserves a check right away, and its history is no
        # longer comparable to the old target's.
        monitor.current_status = "unknown"
        monitor.next_check_at = now

    if data.check_interval_seconds is not None:
        monitor.check_interval_seconds = data.check_interval_seconds
        if data.url is None:
            anchor = monitor.last_checked_at or now
            monitor.next_check_at = max(now, anchor + data.check_interval_seconds * 1000)

    # `model_fields_set` distinguishes "omitted" from an explicit null/"".
    # Changing what counts as healthy invalidates the old status, so re-check.
    if "expected_body_contains" in data.model_fields_set:
        assertion = normalize_body_assertion(data.expected_body_contains)
        if assertion != monitor.expected_body_contains:
            monitor.expected_body_contains = assertion
            monitor.current_status = "unknown"
            monitor.next_check_at = now

    session.commit()
    return monitor


def pause_monitor(session: Session, monitor: Monitor) -> Monitor:
    monitor.is_active = False
    monitor.current_status = "paused"
    session.commit()
    return monitor


def resume_monitor(session: Session, monitor: Monitor) -> Monitor:
    monitor.is_active = True
    monitor.current_status = "unknown"
    monitor.next_check_at = now_ms()
    session.commit()
    return monitor


def delete_monitor(session: Session, monitor: Monitor) -> None:
    session.delete(monitor)
    session.commit()


def select_due_monitors(session: Session, now: int | None = None, limit: int = 50) -> list[Monitor]:
    """Monitors whose next check is due, oldest first."""
    return list(
        session.scalars(
            select(Monitor)
            .where(Monitor.is_active.is_(True), Monitor.next_check_at <= (now or now_ms()))
            .order_by(Monitor.next_check_at)
            .limit(limit)
        ).all()
    )


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def list_checks(
    session: Session, monitor_id: int, limit: int = 200, since: int | None = None
) -> list[Check]:
    query = select(Check).where(Check.monitor_id == monitor_id)
    if since is not None:
        query = query.where(Check.checked_at >= since)
    return list(
        session.scalars(query.order_by(Check.checked_at.desc(), Check.id.desc()).limit(limit)).all()
    )


def list_incidents(session: Session, monitor_id: int, limit: int = 100) -> list[Incident]:
    """Open incidents first, then most recent resolved ones."""
    return list(
        session.scalars(
            select(Incident)
            .where(Incident.monitor_id == monitor_id)
            .order_by(Incident.resolved_at.is_(None).desc(), Incident.started_at.desc())
            .limit(limit)
        ).all()
    )


def dashboard_incidents(
    session: Session, user_id: int, limit: int = 8
) -> list[RecentIncident]:
    """Cross-monitor incident feed: open first, then most recently started.

    The dashboard asks for one small list rather than fetching every monitor's
    history, so this joins the monitor name in the same query.
    """
    rows = session.execute(
        select(Incident, Monitor.name)
        .join(Monitor, Incident.monitor_id == Monitor.id)
        .where(Monitor.user_id == user_id)
        .order_by(Incident.resolved_at.is_(None).desc(), Incident.started_at.desc())
        .limit(limit)
    ).all()

    return [
        RecentIncident(
            id=incident.id,
            monitor_id=incident.monitor_id,
            monitor_name=name,
            started_at=incident.started_at,
            resolved_at=incident.resolved_at,
            reason=incident.reason,
        )
        for incident, name in rows
    ]


def monitor_stats(
    session: Session, monitor_id: int, window_hours: int = DEFAULT_WINDOW_HOURS
) -> MonitorStats:
    """Availability and latency percentiles for one monitor over a window."""
    window_start = now_ms() - window_hours * 3_600_000
    rows = session.execute(
        select(Check.is_success, Check.response_time_ms).where(
            Check.monitor_id == monitor_id, Check.checked_at >= window_start
        )
    ).all()

    successes = sum(1 for is_success, _ in rows if is_success)
    times = sorted(response_time_ms for _, response_time_ms in rows)

    return MonitorStats(
        window_hours=window_hours,
        total_checks=len(rows),
        successes=successes,
        availability=_percentage(successes, len(rows)),
        p50_ms=_percentile(times, 50),
        p95_ms=_percentile(times, 95),
    )


def monitor_series(
    session: Session,
    monitor_id: int,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    max_points: int = 300,
) -> list[SeriesPoint]:
    """Chart points for one monitor, bucketed when the window is dense.

    A 7-day window at a 60-second interval holds 10,080 checks. Sending them
    all on every poll is wasteful, and truncating to the newest N would make
    the chart silently show a fraction of the window. Instead the window is cut
    into at most ``max_points`` equal slices and each non-empty slice becomes
    one point with its average latency and failure count.
    """
    window_start = now_ms() - window_hours * 3_600_000
    rows = session.execute(
        select(Check.checked_at, Check.is_success, Check.response_time_ms)
        .where(Check.monitor_id == monitor_id, Check.checked_at >= window_start)
        .order_by(Check.checked_at)
    ).all()

    if not rows:
        return []

    if len(rows) <= max_points:
        return [
            SeriesPoint(
                t=checked_at,
                avg_ms=response_time_ms,
                checks=1,
                failures=0 if is_success else 1,
            )
            for checked_at, is_success, response_time_ms in rows
        ]

    bucket_ms = max(1, math.ceil(window_hours * 3_600_000 / max_points))
    buckets: dict[int, list[tuple[int, bool, int]]] = {}
    for checked_at, is_success, response_time_ms in rows:
        # Anchor at the window start: the window then spans exactly
        # ``max_points`` buckets, whereas epoch-aligned buckets could straddle
        # one more boundary and return max_points + 1.
        index = (checked_at - window_start) // bucket_ms
        buckets.setdefault(index, []).append((checked_at, is_success, response_time_ms))

    points: list[SeriesPoint] = []
    for bucket in buckets.values():
        total_ms = sum(response_time_ms for _, _, response_time_ms in bucket)
        points.append(
            SeriesPoint(
                t=bucket[-1][0],
                avg_ms=round(total_ms / len(bucket)),
                checks=len(bucket),
                failures=sum(1 for _, is_success, _ in bucket if not is_success),
            )
        )
    return points


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
def dashboard_summary(
    session: Session, user_id: int, window_hours: int = DEFAULT_WINDOW_HOURS
) -> DashboardSummary:
    """Counts plus availability/percentiles over the window.

    Aggregation happens in Python: a 7-day window is a few thousand rows at
    most (checks are pruned by the worker), so one round trip is cheaper than
    several dialect-specific aggregate queries. SQLite has no percentile
    function anyway.
    """
    monitors = list_monitors(session, user_id)
    ids = [m.id for m in monitors]

    if ids:
        window_start = now_ms() - window_hours * 3_600_000
        samples = session.execute(
            select(Check.monitor_id, Check.is_success, Check.response_time_ms).where(
                Check.monitor_id.in_(ids), Check.checked_at >= window_start
            )
        ).all()
        open_incidents = dict(
            session.execute(
                select(Incident.monitor_id, Incident.started_at).where(
                    Incident.monitor_id.in_(ids), Incident.resolved_at.is_(None)
                )
            ).all()
        )
    else:
        samples = []
        open_incidents = {}

    by_monitor: dict[int, list[tuple[bool, int]]] = {}
    for monitor_id, is_success, response_time_ms in samples:
        by_monitor.setdefault(monitor_id, []).append((is_success, response_time_ms))

    rows: list[MonitorSummary] = []
    total_checks = 0
    total_successes = 0

    for monitor in monitors:
        monitor_samples = by_monitor.get(monitor.id, [])
        count = len(monitor_samples)
        successes = sum(1 for success, _ in monitor_samples if success)
        times = sorted(ms for _, ms in monitor_samples)

        # Only active monitors contribute to the fleet-wide figure; a paused
        # monitor's old checks would otherwise distort "is everything up now".
        if monitor.is_active:
            total_checks += count
            total_successes += successes

        rows.append(
            MonitorSummary(
                id=monitor.id,
                name=monitor.name,
                url=monitor.url,
                expected_body_contains=monitor.expected_body_contains,
                check_interval_seconds=monitor.check_interval_seconds,
                current_status=monitor.current_status,
                is_active=monitor.is_active,
                last_checked_at=monitor.last_checked_at,
                last_response_time_ms=monitor.last_response_time_ms,
                availability=_percentage(successes, count),
                p50_ms=_percentile(times, 50),
                p95_ms=_percentile(times, 95),
                open_incident_since=open_incidents.get(monitor.id),
            )
        )

    return DashboardSummary(
        total=len(monitors),
        up=sum(1 for m in monitors if m.is_active and m.current_status == "up"),
        down=sum(1 for m in monitors if m.is_active and m.current_status == "down"),
        paused=sum(1 for m in monitors if not m.is_active),
        unknown=sum(1 for m in monitors if m.is_active and m.current_status == "unknown"),
        availability=_percentage(total_successes, total_checks),
        window_hours=window_hours,
        monitors=rows,
    )


def _percentage(successes: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(successes / total * 100, 1)


def _percentile(sorted_values: list[int], p: float) -> int | None:
    """Nearest-rank percentile — good enough for latency, no dependencies."""
    if not sorted_values:
        return None
    rank = math.ceil(p / 100 * len(sorted_values)) - 1
    return sorted_values[max(0, min(rank, len(sorted_values) - 1))]
