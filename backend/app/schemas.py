"""Pydantic request/response models (API boundary only)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 86_400


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    check_interval_seconds: int = Field(
        default=60, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )
    expected_body_contains: str | None = Field(default=None, max_length=500)


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    check_interval_seconds: int | None = Field(
        default=None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )
    # Omit to keep the current assertion; send "" (or null) to clear it.
    expected_body_contains: str | None = Field(default=None, max_length=500)


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    expected_body_contains: str | None
    check_interval_seconds: int
    is_active: bool
    current_status: str
    last_checked_at: int | None
    next_check_at: int
    last_response_time_ms: int | None
    last_status_code: int | None
    created_at: int


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    checked_at: int
    is_success: bool
    status_code: int | None
    response_time_ms: int
    error_message: str | None


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    started_at: int
    resolved_at: int | None
    reason: str | None


class RecentIncident(BaseModel):
    """One row of the dashboard's cross-monitor incident list."""

    id: int
    monitor_id: int
    monitor_name: str
    started_at: int
    resolved_at: int | None
    reason: str | None


class MonitorStats(BaseModel):
    """Per-monitor aggregates over a window (detail page).

    Counts are included so the UI can say "3 of 4 checks failed" instead of
    only showing a percentage that hides small samples.
    """

    window_hours: int
    total_checks: int
    successes: int
    availability: float | None
    p50_ms: int | None
    p95_ms: int | None


class SeriesPoint(BaseModel):
    """One chart point: either a single check or a bucket of checks.

    ``t`` is the timestamp of the last check in the bucket, so the point lines
    up with real data. ``failures`` is kept even when the window is dense so the
    chart can mark failing periods without shipping every raw row.
    """

    t: int
    avg_ms: int
    checks: int
    failures: int


class MonitorSummary(BaseModel):
    """One dashboard row. ``availability``/``p50_ms``/``p95_ms`` cover the
    requested window and are ``None`` when no checks were recorded in it."""

    id: int
    name: str
    url: str
    expected_body_contains: str | None
    check_interval_seconds: int
    current_status: str
    is_active: bool
    last_checked_at: int | None
    last_response_time_ms: int | None
    availability: float | None
    p50_ms: int | None
    p95_ms: int | None
    open_incident_since: int | None


class DashboardSummary(BaseModel):
    total: int
    up: int
    down: int
    paused: int
    unknown: int
    availability: float | None
    window_hours: int
    monitors: list[MonitorSummary]
