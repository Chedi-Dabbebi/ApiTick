"""Background checker.

One asyncio loop that every TICK_SECONDS selects the monitors whose
``next_check_at`` has passed and probes them concurrently. No APScheduler:
there is nothing to schedule per monitor, so a job queue would only add a
duplicate-scheduler failure mode under ``uvicorn --reload``.

Run as its own process during local development:

    cd backend
    python -m app.worker

Or in-process for single-container deploys with RUN_SCHEDULER=1 (uvicorn must
run with one worker).
"""

from __future__ import annotations

import asyncio
import logging
import sys

import httpx
from sqlalchemy import delete

from .checker import DEFAULT_TIMEOUT, check_endpoint
from .clock import now_ms
from .crud import select_due_monitors
from .db import SessionLocal, init_db
from .models import Check, Monitor
from .monitor_logic import apply_result

log = logging.getLogger("apitick.worker")

TICK_SECONDS = 5
BATCH_SIZE = 50
CONCURRENCY = 10
CHECK_RETENTION_DAYS = 7
PRUNE_EVERY_SECONDS = 3600
USER_AGENT = "ApiTick/0.1"

_last_prune_ms = 0


def due_monitor_ids(now: int | None = None, limit: int = BATCH_SIZE) -> list[int]:
    """Ids of active monitors that are due. Short session, closed immediately."""
    with SessionLocal() as session:
        return [m.id for m in select_due_monitors(session, now=now, limit=limit)]


async def check_monitor(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, monitor_id: int
) -> None:
    async with semaphore:
        # Read the target in one short session, then release the connection.
        with SessionLocal() as session:
            monitor = session.get(Monitor, monitor_id)
            if monitor is None or not monitor.is_active:
                return
            url = monitor.url
            expected_body_contains = monitor.expected_body_contains

        # The HTTP request happens with no database session open.
        result = await check_endpoint(url, client, expected_body_contains)

        with SessionLocal() as session:
            monitor = session.get(Monitor, monitor_id)
            if monitor is None or not monitor.is_active:
                return
            apply_result(session, monitor, result)
            log.info(
                "monitor %s %s (%dms)%s",
                monitor_id,
                "up" if result.is_success else "DOWN",
                result.response_time_ms,
                f" - {result.error_message}" if result.error_message else "",
            )


async def run_once(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, now: int | None = None
) -> int:
    """Check every due monitor. Returns how many were attempted."""
    ids = due_monitor_ids(now=now)
    if not ids:
        return 0

    outcomes = await asyncio.gather(
        *(check_monitor(client, semaphore, monitor_id) for monitor_id in ids),
        return_exceptions=True,
    )
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            log.error("check raised unexpectedly", exc_info=outcome)

    return len(ids)


def prune_old_checks(now: int | None = None, *, force: bool = False) -> int:
    """Drop checks older than the retention window (at most hourly)."""
    global _last_prune_ms
    now = now_ms() if now is None else now

    if not force and now - _last_prune_ms < PRUNE_EVERY_SECONDS * 1000:
        return 0

    cutoff = now - CHECK_RETENTION_DAYS * 86_400_000
    with SessionLocal() as session:
        deleted = session.execute(delete(Check).where(Check.checked_at < cutoff)).rowcount or 0
        session.commit()

    _last_prune_ms = now
    if deleted:
        log.info("pruned %d checks older than %d days", deleted, CHECK_RETENTION_DAYS)
    return deleted


async def run_forever(tick_seconds: float = TICK_SECONDS) -> None:
    init_db()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    log.info("worker starting (tick=%ss, concurrency=%d)", tick_seconds, CONCURRENCY)

    async with make_client() as client:
        while True:
            try:
                checked = await run_once(client, semaphore)
                if checked:
                    log.info("checked %d monitor(s)", checked)
                prune_old_checks()
            except Exception:
                # A single bad monitor must never stop the loop.
                log.exception("worker tick failed")

            await asyncio.sleep(tick_seconds)


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
    )


async def run_once_cli() -> None:
    """One tick, then exit. Useful for manual checks and cron-style deploys."""
    init_db()
    async with make_client() as client:
        checked = await run_once(client, asyncio.Semaphore(CONCURRENCY))
    log.info("checked %d monitor(s)", checked)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    try:
        if "--once" in sys.argv[1:]:
            asyncio.run(run_once_cli())
        else:
            asyncio.run(run_forever())
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    main()
