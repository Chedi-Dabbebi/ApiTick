"""The demo seed script is part of onboarding, so its data story is tested.

``build_history`` is pure (given a fixed clock and RNG) and imports no network
or database code, so these run in milliseconds.
"""

from __future__ import annotations

import random

from app.clock import now_ms
from scripts.seed_demo import SPECS, build_history

DAY_MS = 86_400_000


def spec(name: str):
    return next(item for item in SPECS if item.name == name)


def test_history_is_deterministic():
    now = now_ms()

    first = build_history(spec("Example site"), now, random.Random("seed"))
    second = build_history(spec("Example site"), now, random.Random("seed"))

    assert first == second


def test_outage_monitor_recovers_with_one_resolved_incident():
    history = build_history(spec("Example site"), now_ms(), random.Random("seed"))

    assert history.status == "up"
    assert len(history.incidents) == 1

    started_at, resolved_at, reason = history.incidents[0]
    assert reason == "timeout"
    assert resolved_at is not None
    assert resolved_at > started_at

    # The incident window matches the failing rows exactly.
    failed = [row.checked_at for row in history.rows if not row.is_success]
    assert failed
    assert min(failed) == started_at
    assert max(failed) < resolved_at


def test_down_monitor_has_one_open_incident_and_ends_down():
    history = build_history(spec("HTTPBin 500"), now_ms(), random.Random("seed"))

    assert history.status == "down"
    assert len(history.incidents) == 1
    assert history.incidents[0][1] is None
    assert history.rows[-1].is_success is False


def test_paused_monitor_stopped_a_day_ago_and_has_no_incidents():
    now = now_ms()
    history = build_history(spec("Docs (paused)"), now, random.Random("seed"))

    assert history.status == "paused"
    assert history.incidents == []
    assert history.rows[-1].checked_at <= now - DAY_MS + 5 * 60_000
    assert history.rows[0].checked_at >= now - 7 * DAY_MS
