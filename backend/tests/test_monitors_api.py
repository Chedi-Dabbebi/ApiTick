"""Monitor API: validation, CRUD, pause/resume, history endpoints."""

from __future__ import annotations

import pytest

from app import crud
from app.checker import CheckResult
from app.clock import now_ms
from app.models import Check
from app.monitor_logic import apply_result

PUBLIC_URL = "https://1.1.1.1/"  # numeric address: validates offline, no DNS


async def create_monitor(client, **overrides) -> dict:
    payload = {"name": "Cloudflare DNS", "url": PUBLIC_URL, "check_interval_seconds": 30}
    payload.update(overrides)
    response = await client.post("/api/monitors", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_create_monitor_returns_201_and_schedules_first_check(client):
    body = await create_monitor(client)

    assert body["name"] == "Cloudflare DNS"
    assert body["current_status"] == "unknown"
    assert body["is_active"] is True
    assert body["next_check_at"] == body["created_at"]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "local", "url": "http://127.0.0.1:8000/"},
        {"name": "metadata", "url": "http://169.254.169.254/latest/meta-data/"},
        {"name": "file", "url": "file:///etc/passwd"},
        {"name": "no scheme", "url": "example.com"},
    ],
)
async def test_create_monitor_rejects_non_public_urls(client, payload):
    response = await client.post("/api/monitors", json=payload)
    assert response.status_code == 422
    assert "detail" in response.json()


@pytest.mark.parametrize("interval", [0, 5, 90_000])
async def test_create_monitor_rejects_out_of_range_interval(client, interval):
    response = await client.post(
        "/api/monitors",
        json={"name": "x", "url": PUBLIC_URL, "check_interval_seconds": interval},
    )
    assert response.status_code == 422


async def test_create_monitor_rejects_empty_name(client):
    response = await client.post("/api/monitors", json={"name": "", "url": PUBLIC_URL})
    assert response.status_code == 422


async def test_list_and_get_monitor(client):
    created = await create_monitor(client)

    listing = await client.get("/api/monitors")
    assert listing.status_code == 200
    assert [m["id"] for m in listing.json()] == [created["id"]]

    single = await client.get(f"/api/monitors/{created['id']}")
    assert single.status_code == 200
    assert single.json()["url"] == PUBLIC_URL


async def test_get_unknown_monitor_is_404(client):
    response = await client.get("/api/monitors/999")
    assert response.status_code == 404


async def test_patch_updates_name_without_touching_url(client):
    created = await create_monitor(client)

    response = await client.patch(f"/api/monitors/{created['id']}", json={"name": "renamed"})

    assert response.status_code == 200
    assert response.json()["name"] == "renamed"
    assert response.json()["url"] == PUBLIC_URL


async def test_patch_interval_reschedules_next_check(client):
    created = await create_monitor(client)

    response = await client.patch(
        f"/api/monitors/{created['id']}", json={"check_interval_seconds": 120}
    )

    body = response.json()
    assert body["check_interval_seconds"] == 120
    assert body["last_checked_at"] is None
    # Never checked, so the next check is one full interval from now.
    assert body["next_check_at"] - created["created_at"] >= 119_000


async def test_patch_url_resets_status_and_schedules_now(client):
    created = await create_monitor(client)

    response = await client.patch(
        f"/api/monitors/{created['id']}", json={"url": "https://8.8.8.8/"}
    )

    body = response.json()
    assert body["url"] == "https://8.8.8.8/"
    assert body["current_status"] == "unknown"


async def test_patch_rejects_private_url(client):
    created = await create_monitor(client)

    response = await client.patch(
        f"/api/monitors/{created['id']}", json={"url": "http://192.168.1.1/"}
    )

    assert response.status_code == 422


async def test_create_monitor_stores_body_assertion(client):
    body = await create_monitor(client, expected_body_contains='"status":"ok"')

    assert body["expected_body_contains"] == '"status":"ok"'


async def test_create_monitor_normalizes_blank_body_assertion(client):
    body = await create_monitor(client, expected_body_contains="   ")

    assert body["expected_body_contains"] is None


async def test_create_monitor_rejects_overlong_body_assertion(client):
    response = await client.post(
        "/api/monitors",
        json={"name": "x", "url": PUBLIC_URL, "expected_body_contains": "x" * 501},
    )

    assert response.status_code == 422


async def test_patch_body_assertion_resets_status_and_schedules_now(client, session):
    created = await create_monitor(client)
    monitor = crud.get_monitor(session, 1, created["id"])
    apply_result(session, monitor, CheckResult(True, 200, 10))
    assert monitor.current_status == "up"

    response = await client.patch(
        f"/api/monitors/{created['id']}", json={"expected_body_contains": "healthy"}
    )

    body = response.json()
    assert body["expected_body_contains"] == "healthy"
    assert body["current_status"] == "unknown"
    assert body["next_check_at"] >= created["created_at"]


@pytest.mark.parametrize("value", ["", None])
async def test_patch_blank_body_assertion_clears_it(client, value):
    created = await create_monitor(client, expected_body_contains="healthy")

    response = await client.patch(
        f"/api/monitors/{created['id']}", json={"expected_body_contains": value}
    )

    assert response.status_code == 200
    assert response.json()["expected_body_contains"] is None


async def test_patch_omitting_body_assertion_keeps_it(client):
    created = await create_monitor(client, expected_body_contains="healthy")

    response = await client.patch(f"/api/monitors/{created['id']}", json={"name": "renamed"})

    assert response.json()["expected_body_contains"] == "healthy"


async def test_pause_then_resume(client):
    created = await create_monitor(client)

    paused = await client.post(f"/api/monitors/{created['id']}/pause")
    assert paused.status_code == 200
    assert paused.json()["is_active"] is False
    assert paused.json()["current_status"] == "paused"

    resumed = await client.post(f"/api/monitors/{created['id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["is_active"] is True
    assert resumed.json()["current_status"] == "unknown"


async def test_delete_monitor_and_its_history(client, session):
    created = await create_monitor(client)
    monitor = crud.get_monitor(session, 1, created["id"])
    apply_result(session, monitor, CheckResult(True, 200, 20))

    response = await client.delete(f"/api/monitors/{created['id']}")
    assert response.status_code == 204

    assert (await client.get(f"/api/monitors/{created['id']}")).status_code == 404
    assert crud.list_checks(session, created["id"]) == []


async def test_checks_endpoint_returns_newest_first(client, session):
    created = await create_monitor(client)
    monitor = crud.get_monitor(session, 1, created["id"])
    apply_result(session, monitor, CheckResult(True, 200, 50), now=1_000)
    apply_result(session, monitor, CheckResult(False, 500, 10, "HTTP 500"), now=2_000)

    response = await client.get(f"/api/monitors/{created['id']}/checks")

    assert response.status_code == 200
    checks = response.json()
    assert [c["checked_at"] for c in checks] == [2_000, 1_000]
    assert checks[0]["error_message"] == "HTTP 500"


async def test_checks_endpoint_supports_limit_and_since(client, session):
    created = await create_monitor(client)
    monitor = crud.get_monitor(session, 1, created["id"])
    for i in range(5):
        apply_result(session, monitor, CheckResult(True, 200, 10 + i), now=1_000 * (i + 1))

    limited = await client.get(f"/api/monitors/{created['id']}/checks", params={"limit": 2})
    assert len(limited.json()) == 2

    recent = await client.get(f"/api/monitors/{created['id']}/checks", params={"since": 4_000})
    assert [c["checked_at"] for c in recent.json()] == [5_000, 4_000]


async def test_incidents_endpoint_lists_open_incident(client, session):
    created = await create_monitor(client)
    monitor = crud.get_monitor(session, 1, created["id"])
    apply_result(session, monitor, CheckResult(False, 500, 10, "HTTP 500"), now=1_000)

    response = await client.get(f"/api/monitors/{created['id']}/incidents")

    assert response.status_code == 200
    incidents = response.json()
    assert len(incidents) == 1
    assert incidents[0]["started_at"] == 1_000
    assert incidents[0]["resolved_at"] is None


async def test_history_endpoints_404_for_unknown_monitor(client):
    assert (await client.get("/api/monitors/999/checks")).status_code == 404
    assert (await client.get("/api/monitors/999/incidents")).status_code == 404
    assert (await client.get("/api/monitors/999/stats")).status_code == 404
    assert (await client.get("/api/monitors/999/series")).status_code == 404


async def test_stats_are_none_before_any_checks(client):
    created = await create_monitor(client)

    body = (await client.get(f"/api/monitors/{created['id']}/stats")).json()

    assert body == {
        "window_hours": 24,
        "total_checks": 0,
        "successes": 0,
        "availability": None,
        "p50_ms": None,
        "p95_ms": None,
    }


async def test_stats_compute_availability_and_percentiles(client, session):
    created = await create_monitor(client)
    monitor = crud.get_monitor(session, 1, created["id"])
    now = now_ms()
    apply_result(session, monitor, CheckResult(True, 200, 100), now=now - 3_000)
    apply_result(session, monitor, CheckResult(True, 200, 200), now=now - 2_000)
    apply_result(session, monitor, CheckResult(False, 500, 10, "HTTP 500"), now=now - 1_000)

    body = (await client.get(f"/api/monitors/{created['id']}/stats")).json()

    assert body["total_checks"] == 3
    assert body["successes"] == 2
    assert body["availability"] == 66.7
    assert body["p50_ms"] == 100
    assert body["p95_ms"] == 200


async def test_stats_window_excludes_older_checks(client, session):
    created = await create_monitor(client)
    monitor = crud.get_monitor(session, 1, created["id"])
    apply_result(
        session, monitor, CheckResult(True, 200, 10), now=now_ms() - 48 * 3_600_000
    )

    day = (await client.get(f"/api/monitors/{created['id']}/stats?window_hours=24")).json()
    week = (await client.get(f"/api/monitors/{created['id']}/stats?window_hours=168")).json()

    assert day["availability"] is None
    assert day["total_checks"] == 0
    assert week["availability"] == 100.0
    assert week["window_hours"] == 168


async def test_stats_reject_invalid_window(client):
    created = await create_monitor(client)
    response = await client.get(f"/api/monitors/{created['id']}/stats?window_hours=0")
    assert response.status_code == 422


async def test_series_is_empty_before_any_checks(client):
    created = await create_monitor(client)

    response = await client.get(f"/api/monitors/{created['id']}/series")

    assert response.status_code == 200
    assert response.json() == []


async def test_series_returns_one_point_per_check_when_sparse(client, session):
    created = await create_monitor(client)
    monitor = crud.get_monitor(session, 1, created["id"])
    now = now_ms()
    apply_result(session, monitor, CheckResult(True, 200, 100), now=now - 3_000)
    apply_result(session, monitor, CheckResult(True, 200, 300), now=now - 2_000)
    apply_result(session, monitor, CheckResult(False, 500, 10, "HTTP 500"), now=now - 1_000)

    body = (await client.get(f"/api/monitors/{created['id']}/series")).json()

    assert [point["t"] for point in body] == [now - 3_000, now - 2_000, now - 1_000]
    assert [point["avg_ms"] for point in body] == [100, 300, 10]
    assert [point["failures"] for point in body] == [0, 0, 1]
    assert all(point["checks"] == 1 for point in body)


async def test_series_buckets_dense_windows_and_preserves_failures(client, session):
    created = await create_monitor(client)
    now = now_ms()
    span = 23 * 3_600_000
    rows = [
        Check(
            monitor_id=created["id"],
            checked_at=now - span + i * (span // 600),
            is_success=(i % 10 != 0),
            status_code=200 if i % 10 != 0 else 500,
            response_time_ms=100 + i,
            error_message=None if i % 10 != 0 else "HTTP 500",
        )
        for i in range(600)
    ]
    session.add_all(rows)
    session.commit()

    response = await client.get(
        f"/api/monitors/{created['id']}/series?window_hours=24&max_points=10"
    )
    body = response.json()

    assert response.status_code == 200
    assert 1 < len(body) <= 10
    # Bucketing must not lose samples or failures.
    assert sum(point["checks"] for point in body) == 600
    assert sum(point["failures"] for point in body) == 60
    assert all(point["checks"] >= 1 for point in body)


async def test_series_rejects_invalid_max_points(client):
    created = await create_monitor(client)
    response = await client.get(f"/api/monitors/{created['id']}/series?max_points=5")
    assert response.status_code == 422
