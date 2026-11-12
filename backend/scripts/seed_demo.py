"""Seed a deterministic demo dataset into the local database.

    cd backend
    .venv\\Scripts\\python.exe scripts\\seed_demo.py
    .venv\\Scripts\\python.exe scripts\\seed_demo.py --reset

Four monitors get seven days of generated check history: a healthy service, a
recovered outage, an ongoing failure and a paused monitor. No network access is
used -- the rows are written directly, so the demo works offline and produces
the same chart on every machine.

The script is idempotent: if the demo monitors already exist it does nothing.
``--reset`` deletes monitors whose names match the demo set (checks and
incidents cascade) and rebuilds them. Your own monitors are left alone.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NamedTuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, insert, select

from app.clock import now_ms
from app.db import DEMO_USER_ID, SessionLocal, init_db
from app.models import Check, Incident, Monitor

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
HISTORY_DAYS = 7
RNG_SEED = 20261112


@dataclass(frozen=True)
class Spec:
    name: str
    url: str
    interval_seconds: int
    baseline_ms: int
    jitter_ms: int
    kind: Literal["healthy", "outage", "down", "paused"]


SPECS: tuple[Spec, ...] = (
    Spec("Example site", "https://example.com", 60, 180, 40, "outage"),
    Spec("GitHub API", "https://api.github.com", 300, 120, 25, "healthy"),
    Spec("HTTPBin 500", "https://httpbin.org/status/500", 120, 90, 30, "down"),
    Spec("Docs (paused)", "https://developer.mozilla.org", 300, 240, 60, "paused"),
)


class Row(NamedTuple):
    checked_at: int
    is_success: bool
    status_code: int | None
    response_time_ms: int
    error_message: str | None


class History(NamedTuple):
    rows: list[Row]
    incidents: list[tuple[int, int | None, str]]
    status: str


def build_history(spec: Spec, now: int, rng: random.Random) -> History:
    """Generate one monitor's checks plus the incidents implied by them."""
    step = spec.interval_seconds * 1000
    end = now // step * step
    start = end - HISTORY_DAYS * DAY_MS + step

    outage_start = outage_end = down_start = pause_at = None
    if spec.kind == "outage":
        # A 20-minute timeout two days ago, recovered since.
        outage_start = (now - 2 * DAY_MS - 25 * 60_000) // step * step
        outage_end = outage_start + 20 * 60_000
    elif spec.kind == "down":
        down_start = (now - 3 * HOUR_MS) // step * step
    elif spec.kind == "paused":
        pause_at = (now - DAY_MS) // step * step

    stop = pause_at if pause_at is not None else end
    rows: list[Row] = []

    for checked_at in range(start, stop + 1, step):
        if outage_start is not None and outage_start <= checked_at < outage_end:
            rows.append(Row(checked_at, False, None, 10_000, "timeout"))
        elif down_start is not None and checked_at >= down_start:
            latency = spec.baseline_ms + rng.randint(0, spec.jitter_ms)
            rows.append(Row(checked_at, False, 500, latency, "HTTP 500"))
        else:
            latency = spec.baseline_ms + rng.randint(-spec.jitter_ms, spec.jitter_ms)
            if rng.random() < 0.01:  # occasional spike, visible on the chart
                latency *= rng.randint(3, 6)
            rows.append(Row(checked_at, True, 200, max(1, latency), None))

    if not rows:
        raise SystemExit(f"no checks generated for {spec.name!r} -- check the spec")

    # Incidents are just contiguous failure runs; this mirrors what
    # monitor_logic.apply_result() would have opened at the time.
    incidents: list[tuple[int, int | None, str]] = []
    open_run: tuple[int, str] | None = None
    for row in rows:
        if not row.is_success:
            if open_run is None:
                open_run = (row.checked_at, row.error_message or "check failed")
        elif open_run is not None:
            incidents.append((open_run[0], row.checked_at, open_run[1]))
            open_run = None
    if open_run is not None:
        incidents.append((open_run[0], None, open_run[1]))

    if spec.kind == "paused":
        status = "paused"
    else:
        status = "up" if rows[-1].is_success else "down"

    return History(rows, incidents, status)


def seed(reset: bool) -> int:
    init_db()
    names = [spec.name for spec in SPECS]

    with SessionLocal() as session:
        existing = list(
            session.scalars(
                select(Monitor).where(
                    Monitor.user_id == DEMO_USER_ID, Monitor.name.in_(names)
                )
            ).all()
        )

        if existing and not reset:
            print("Demo data already present:")
            for monitor in existing:
                print(f"  {monitor.id:>3}  {monitor.name}")
            print("Re-run with --reset to delete and rebuild it.")
            return 0

        if existing:
            session.execute(
                delete(Monitor).where(
                    Monitor.user_id == DEMO_USER_ID, Monitor.name.in_(names)
                )
            )
            session.commit()
            print(f"Deleted {len(existing)} existing demo monitor(s).")

        now = now_ms()
        print(f"\nSeeding {HISTORY_DAYS} days of history:\n")

        for spec in SPECS:
            rng = random.Random(f"{RNG_SEED}:{spec.name}")
            history = build_history(spec, now, rng)
            last = history.rows[-1]
            active = spec.kind != "paused"

            monitor = Monitor(
                user_id=DEMO_USER_ID,
                name=spec.name,
                url=spec.url,
                check_interval_seconds=spec.interval_seconds,
                is_active=active,
                current_status=history.status,
                last_checked_at=last.checked_at,
                last_response_time_ms=last.response_time_ms,
                last_status_code=last.status_code,
                # Active monitors look like they just ran; the paused one keeps
                # whatever schedule it had when it stopped.
                next_check_at=(
                    now + spec.interval_seconds * 1000
                    if active
                    else last.checked_at + spec.interval_seconds * 1000
                ),
                created_at=history.rows[0].checked_at,
            )
            session.add(monitor)
            session.flush()  # assigns monitor.id

            session.execute(
                insert(Check),
                [
                    {
                        "monitor_id": monitor.id,
                        "checked_at": row.checked_at,
                        "is_success": row.is_success,
                        "status_code": row.status_code,
                        "response_time_ms": row.response_time_ms,
                        "error_message": row.error_message,
                    }
                    for row in history.rows
                ],
            )
            session.add_all(
                Incident(
                    monitor_id=monitor.id,
                    started_at=started_at,
                    resolved_at=resolved_at,
                    reason=reason,
                )
                for started_at, resolved_at, reason in history.incidents
            )
            session.commit()

            successes = sum(1 for row in history.rows if row.is_success)
            availability = successes / len(history.rows) * 100
            print(
                f"  {monitor.id:>3}  {spec.name:<16} {len(history.rows):>6} checks"
                f"  {availability:>5.1f}% up  {len(history.incidents)} incident(s)"
            )

    print("\nDashboard: http://localhost:5173/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed deterministic demo monitors and check history."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the demo monitors (and their history) before seeding",
    )
    return seed(parser.parse_args().reset)


if __name__ == "__main__":
    raise SystemExit(main())
