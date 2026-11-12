"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db
from .routes import dashboard, monitors


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()

    # Local dev runs the worker as a separate process (python -m app.worker).
    # Single-container deployments (e.g. Render) set RUN_SCHEDULER=1 and must
    # also run uvicorn with exactly one worker, or checks get duplicated.
    task: asyncio.Task[None] | None = None
    if os.getenv("RUN_SCHEDULER") == "1":
        from . import worker

        task = asyncio.create_task(worker.run_forever(), name="monitor-worker")

    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="ApiTick", version="0.1.0", lifespan=lifespan)
app.include_router(monitors.router)
app.include_router(dashboard.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
