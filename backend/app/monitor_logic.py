"""Monitor state transitions after a check.

Pure business logic: takes a persisted Monitor and a CheckResult, writes the
check, updates the denormalised monitor fields, and opens/resolves incidents.
No HTTP, no scheduler — this is the other half of the testable core.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .checker import CheckResult
from .clock import now_ms
from .models import Check, Incident, Monitor


def apply_result(
    session: Session,
    monitor: Monitor,
    result: CheckResult,
    now: int | None = None,
) -> Check:
    """Record one check and apply the resulting status/incident transition.

    Owns its transaction: callers must not hold other work open across this
    call. Returns the persisted Check row.
    """
    now = now_ms() if now is None else now

    check = Check(
        monitor_id=monitor.id,
        checked_at=now,
        is_success=result.is_success,
        status_code=result.status_code,
        response_time_ms=result.response_time_ms,
        error_message=result.error_message,
    )
    session.add(check)

    monitor.last_checked_at = now
    monitor.last_response_time_ms = result.response_time_ms
    monitor.last_status_code = result.status_code
    monitor.next_check_at = now + monitor.check_interval_seconds * 1000

    if result.is_success:
        monitor.current_status = "up"
        _resolve_open_incident(session, monitor.id, now)
    else:
        monitor.current_status = "down"
        _ensure_open_incident(session, monitor.id, now, result.error_message)

    session.commit()
    return check


def _find_open_incident(session: Session, monitor_id: int) -> Incident | None:
    return session.scalar(
        select(Incident).where(
            Incident.monitor_id == monitor_id,
            Incident.resolved_at.is_(None),
        )
    )


def _resolve_open_incident(session: Session, monitor_id: int, now: int) -> None:
    incident = _find_open_incident(session, monitor_id)
    if incident is not None:
        incident.resolved_at = now


def _ensure_open_incident(
    session: Session, monitor_id: int, now: int, reason: str | None
) -> None:
    """Idempotent: consecutive failures reuse the same open incident."""
    if _find_open_incident(session, monitor_id) is None:
        session.add(
            Incident(
                monitor_id=monitor_id,
                started_at=now,
                reason=reason or "check failed",
            )
        )
