"""Dashboard aggregate: counts, availability, percentiles, windowing."""

from __future__ import annotations

from app import crud
from app.checker import CheckResult
from app.clock import now_ms
from app.monitor_logic import apply_result

PUBLIC_URL = "https://1.1.1.1/"


async def create(client, name: str = "monitor") -> int:
    response = await client.post("/api/monitors", json={"name": name, "url": PUBLIC_URL})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_empty_summary(client):
    body = (await client.get("/api/dashboard/summary")).json()

    assert body["total"] == 0
    assert body["availability"] is None
    assert body["window_hours"] == 24
    assert body["monitors"] == []


async def test_counts_availability_and_percentiles(client, session):
    a = await create(client, "a")
    b = await create(client, "b")
    c = await create(client, "c")  # never checked

    now = now_ms()

    monitor_a = crud.get_monitor(session, 1, a)
    apply_result(session, monitor_a, CheckResult(True, 200, 100), now=now - 2_000)
    apply_result(session, monitor_a, CheckResult(False, 500, 10, "HTTP 500"), now=now - 1_000)

    monitor_b = crud.get_monitor(session, 1, b)
    apply_result(session, monitor_b, CheckResult(True, 200, 40), now=now - 2_000)
    apply_result(session, monitor_b, CheckResult(True, 200, 60), now=now - 1_000)

    body = (await client.get("/api/dashboard/summary")).json()

    assert body["total"] == 3
    assert body["up"] == 1  # b
    assert body["down"] == 1  # a (last check failed)
    assert body["unknown"] == 1  # c
    assert body["paused"] == 0
    assert body["availability"] == 75.0  # 3 successes / 4 checks

    rows = {row["id"]: row for row in body["monitors"]}
    assert rows[a]["availability"] == 50.0
    assert rows[a]["p50_ms"] == 10
    assert rows[a]["p95_ms"] == 100
    assert rows[a]["check_interval_seconds"] == 60
    assert rows[b]["availability"] == 100.0
    assert rows[b]["p50_ms"] == 40
    assert rows[c]["availability"] is None
    assert rows[c]["p50_ms"] is None


async def test_paused_monitor_is_excluded_from_fleet_availability(client, session):
    monitor_id = await create(client)
    monitor = crud.get_monitor(session, 1, monitor_id)
    apply_result(session, monitor, CheckResult(True, 200, 10), now=now_ms() - 1_000)

    await client.post(f"/api/monitors/{monitor_id}/pause")
    body = (await client.get("/api/dashboard/summary")).json()

    assert body["paused"] == 1
    assert body["up"] == 0
    assert body["availability"] is None
    # History is still reported per monitor, it just doesn't count fleet-wide.
    assert body["monitors"][0]["availability"] == 100.0


async def test_window_excludes_checks_outside_the_range(client, session):
    monitor_id = await create(client)
    monitor = crud.get_monitor(session, 1, monitor_id)
    apply_result(
        session, monitor, CheckResult(True, 200, 10), now=now_ms() - 48 * 3_600_000
    )

    last_day = (await client.get("/api/dashboard/summary", params={"window_hours": 24})).json()
    assert last_day["monitors"][0]["availability"] is None

    three_days = (await client.get("/api/dashboard/summary", params={"window_hours": 72})).json()
    assert three_days["monitors"][0]["availability"] == 100.0
    assert three_days["window_hours"] == 72


async def test_summary_reports_open_incident_since(client, session):
    monitor_id = await create(client)
    monitor = crud.get_monitor(session, 1, monitor_id)
    started = now_ms() - 5_000
    apply_result(session, monitor, CheckResult(False, 500, 10, "HTTP 500"), now=started)

    body = (await client.get("/api/dashboard/summary")).json()

    assert body["monitors"][0]["open_incident_since"] == started


async def test_invalid_window_is_rejected(client):
    assert (await client.get("/api/dashboard/summary", params={"window_hours": 0})).status_code == 422
    assert (await client.get("/api/dashboard/summary", params={"window_hours": 999})).status_code == 422


async def test_recent_incidents_empty(client):
    assert (await client.get("/api/dashboard/incidents")).json() == []


async def test_recent_incidents_puts_open_first_then_newest(client, session):
    a = await create(client, "api")
    b = await create(client, "web")
    now = now_ms()

    monitor_a = crud.get_monitor(session, 1, a)
    monitor_b = crud.get_monitor(session, 1, b)
    # b fails, then recovers; a stays down.
    apply_result(session, monitor_b, CheckResult(False, 500, 10, "HTTP 500"), now=now - 30_000)
    apply_result(session, monitor_b, CheckResult(True, 200, 10), now=now - 20_000)
    apply_result(session, monitor_a, CheckResult(False, 503, 10, "HTTP 503"), now=now - 10_000)

    body = (await client.get("/api/dashboard/incidents")).json()

    assert [row["monitor_name"] for row in body] == ["api", "web"]
    assert body[0]["monitor_id"] == a
    assert body[0]["resolved_at"] is None
    assert body[0]["reason"] == "HTTP 503"
    assert body[1]["monitor_id"] == b
    assert body[1]["resolved_at"] == now - 20_000


async def test_recent_incidents_respects_limit(client, session):
    first, second = await create(client, "first"), await create(client, "second")
    now = now_ms()
    for offset, monitor_id in enumerate((first, second)):
        monitor = crud.get_monitor(session, 1, monitor_id)
        apply_result(
            session,
            monitor,
            CheckResult(False, 500, 10, "HTTP 500"),
            now=now - (offset + 1) * 10_000,
        )

    body = (await client.get("/api/dashboard/incidents", params={"limit": 1})).json()

    assert len(body) == 1
    assert body[0]["monitor_name"] == "first"
    assert (await client.get("/api/dashboard/incidents", params={"limit": 0})).status_code == 422
