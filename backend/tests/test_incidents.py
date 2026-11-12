"""Incident transitions: one open incident per outage, resolved on recovery."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import models
from app.checker import CheckResult
from app.monitor_logic import apply_result


def make_monitor(session, **overrides) -> models.Monitor:
    values = {
        "user_id": 1,
        "name": "demo",
        "url": "https://example.com",
        "check_interval_seconds": 60,
        "next_check_at": 0,
        "created_at": 0,
    }
    values.update(overrides)
    monitor = models.Monitor(**values)
    session.add(monitor)
    session.commit()
    return monitor


def ok(ms: int = 42) -> CheckResult:
    return CheckResult(is_success=True, status_code=200, response_time_ms=ms)


def fail(message: str = "HTTP 500", ms: int = 12) -> CheckResult:
    return CheckResult(is_success=False, status_code=500, response_time_ms=ms, error_message=message)


def incident_count(session) -> int:
    return session.scalar(select(func.count()).select_from(models.Incident)) or 0


def open_incident(session, monitor_id: int) -> models.Incident | None:
    return session.scalar(
        select(models.Incident).where(
            models.Incident.monitor_id == monitor_id,
            models.Incident.resolved_at.is_(None),
        )
    )


def test_success_from_unknown_sets_up_and_opens_nothing(session):
    monitor = make_monitor(session)

    apply_result(session, monitor, ok())

    assert monitor.current_status == "up"
    assert incident_count(session) == 0


def test_failure_from_unknown_sets_down_and_opens_one_incident(session):
    monitor = make_monitor(session)

    apply_result(session, monitor, fail("HTTP 503"), now=1_000)

    assert monitor.current_status == "down"
    incident = open_incident(session, monitor.id)
    assert incident is not None
    assert incident.started_at == 1_000
    assert incident.reason == "HTTP 503"


def test_consecutive_failures_keep_a_single_incident(session):
    monitor = make_monitor(session)

    apply_result(session, monitor, fail(), now=1_000)
    apply_result(session, monitor, fail(), now=2_000)
    apply_result(session, monitor, fail(), now=3_000)

    assert incident_count(session) == 1
    incident = open_incident(session, monitor.id)
    assert incident is not None
    assert incident.started_at == 1_000


def test_recovery_resolves_the_open_incident(session):
    monitor = make_monitor(session)

    apply_result(session, monitor, fail(), now=1_000)
    apply_result(session, monitor, ok(), now=2_000)

    assert monitor.current_status == "up"
    incident = session.scalar(select(models.Incident))
    assert incident is not None
    assert incident.resolved_at == 2_000


def test_second_outage_after_recovery_opens_a_new_incident(session):
    monitor = make_monitor(session)

    apply_result(session, monitor, fail(), now=1_000)
    apply_result(session, monitor, ok(), now=2_000)
    apply_result(session, monitor, fail("timeout"), now=3_000)

    assert incident_count(session) == 2
    current = open_incident(session, monitor.id)
    assert current is not None
    assert current.started_at == 3_000
    assert current.reason == "timeout"


def test_repeated_success_never_opens_an_incident(session):
    monitor = make_monitor(session)

    apply_result(session, monitor, ok(), now=1_000)
    apply_result(session, monitor, ok(), now=2_000)

    assert incident_count(session) == 0
    assert monitor.current_status == "up"


def test_apply_result_updates_denormalised_monitor_fields(session):
    monitor = make_monitor(session, check_interval_seconds=30)

    apply_result(session, monitor, ok(ms=123), now=10_000)

    assert monitor.last_checked_at == 10_000
    assert monitor.last_response_time_ms == 123
    assert monitor.last_status_code == 200
    assert monitor.next_check_at == 10_000 + 30_000


def test_apply_result_persists_the_check_row(session):
    monitor = make_monitor(session)

    apply_result(session, monitor, fail("timeout", ms=9), now=5_000)

    check = session.scalar(select(models.Check))
    assert check is not None
    assert check.monitor_id == monitor.id
    assert check.checked_at == 5_000
    assert check.is_success is False
    assert check.status_code == 500
    assert check.response_time_ms == 9
    assert check.error_message == "timeout"


def test_database_rejects_two_open_incidents_for_one_monitor(session):
    monitor = make_monitor(session)
    session.add(models.Incident(monitor_id=monitor.id, started_at=1))
    session.add(models.Incident(monitor_id=monitor.id, started_at=2))

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()
