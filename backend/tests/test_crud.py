"""CRUD-level behaviour: due-monitor selection and scheduling side effects."""

from __future__ import annotations

from app import crud, models
from app.clock import now_ms
from app.schemas import MonitorCreate, MonitorUpdate


def make(session, **overrides) -> models.Monitor:
    values = {
        "user_id": 1,
        "name": "m",
        "url": "https://1.1.1.1/",
        "check_interval_seconds": 60,
        "next_check_at": 0,
        "created_at": 0,
    }
    values.update(overrides)
    monitor = models.Monitor(**values)
    session.add(monitor)
    session.commit()
    return monitor


def test_due_selection_skips_future_and_paused_monitors(session):
    make(session, name="later", next_check_at=2_000)
    due = make(session, name="due", next_check_at=100)
    make(session, name="paused", next_check_at=0, is_active=False)

    result = crud.select_due_monitors(session, now=1_000)

    assert [m.id for m in result] == [due.id]


def test_due_selection_is_ordered_by_next_check(session):
    second = make(session, name="second", next_check_at=200)
    first = make(session, name="first", next_check_at=100)

    result = crud.select_due_monitors(session, now=1_000)

    assert [m.id for m in result] == [first.id, second.id]


def test_due_selection_respects_limit(session):
    for i in range(5):
        make(session, name=f"m{i}", next_check_at=100 + i)

    result = crud.select_due_monitors(session, now=1_000, limit=2)

    assert len(result) == 2


def test_create_monitor_schedules_immediately_and_validates_url(session):
    monitor = crud.create_monitor(
        session,
        1,
        MonitorCreate(name="x", url="https://8.8.8.8/", check_interval_seconds=45),
    )

    assert monitor.next_check_at == monitor.created_at
    assert monitor.current_status == "unknown"
    assert monitor.is_active is True


def test_update_interval_reschedules_from_last_check(session):
    last_check = now_ms() - 10_000
    monitor = make(session, last_checked_at=last_check, next_check_at=last_check + 60_000)

    crud.update_monitor(session, monitor, MonitorUpdate(check_interval_seconds=120))

    assert monitor.next_check_at == last_check + 120_000


def test_update_interval_never_schedules_in_the_past(session):
    monitor = make(session, last_checked_at=0, next_check_at=0)

    before = now_ms()
    crud.update_monitor(session, monitor, MonitorUpdate(check_interval_seconds=10))

    assert monitor.next_check_at >= before


def test_update_url_resets_status_and_schedules_now(session):
    monitor = make(session, current_status="down", next_check_at=999_999)

    before = now_ms()
    crud.update_monitor(session, monitor, MonitorUpdate(url="https://1.1.1.1/other"))

    assert monitor.url == "https://1.1.1.1/other"
    assert monitor.current_status == "unknown"
    assert monitor.next_check_at >= before


def test_update_body_assertion_resets_status_and_schedules_now(session):
    monitor = make(session, current_status="up", next_check_at=999_999)

    before = now_ms()
    crud.update_monitor(session, monitor, MonitorUpdate(expected_body_contains="healthy"))

    assert monitor.expected_body_contains == "healthy"
    assert monitor.current_status == "unknown"
    assert monitor.next_check_at >= before


def test_update_same_body_assertion_does_not_reschedule(session):
    monitor = make(
        session,
        current_status="up",
        next_check_at=999_999,
        expected_body_contains="healthy",
    )

    crud.update_monitor(session, monitor, MonitorUpdate(expected_body_contains=" healthy "))

    assert monitor.current_status == "up"
    assert monitor.next_check_at == 999_999


def test_update_blank_body_assertion_clears_it(session):
    monitor = make(
        session,
        current_status="up",
        next_check_at=999_999,
        expected_body_contains="healthy",
    )

    crud.update_monitor(session, monitor, MonitorUpdate(expected_body_contains="  "))

    assert monitor.expected_body_contains is None
    assert monitor.current_status == "unknown"


def test_pause_and_resume(session):
    monitor = make(session, current_status="up", next_check_at=0)

    crud.pause_monitor(session, monitor)
    assert monitor.is_active is False
    assert monitor.current_status == "paused"

    before = now_ms()
    crud.resume_monitor(session, monitor)
    assert monitor.is_active is True
    assert monitor.current_status == "unknown"
    assert monitor.next_check_at >= before


def test_list_checks_newest_first_and_since_filter(session):
    monitor = make(session)
    for i in range(3):
        session.add(
            models.Check(
                monitor_id=monitor.id,
                checked_at=(i + 1) * 1_000,
                is_success=True,
                status_code=200,
                response_time_ms=10,
            )
        )
    session.commit()

    newest = crud.list_checks(session, monitor.id)
    assert [c.checked_at for c in newest] == [3_000, 2_000, 1_000]

    recent = crud.list_checks(session, monitor.id, since=2_000)
    assert [c.checked_at for c in recent] == [3_000, 2_000]
