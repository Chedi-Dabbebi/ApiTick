"""Monitor CRUD, pause/resume, and per-monitor history endpoints.

v1 is single-user: every query is scoped to ``DEMO_USER_ID``. When auth is
added, replace that constant with the authenticated user's id — the ownership
checks already exist in crud.get_monitor().
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import crud
from ..checker import BlockedURLError
from ..db import DEMO_USER_ID, get_db
from ..models import Monitor
from ..schemas import (
    CheckOut,
    IncidentOut,
    MonitorCreate,
    MonitorOut,
    MonitorStats,
    MonitorUpdate,
    SeriesPoint,
)

router = APIRouter(prefix="/api/monitors", tags=["monitors"])


def _get_or_404(session: Session, monitor_id: int) -> Monitor:
    monitor = crud.get_monitor(session, DEMO_USER_ID, monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return monitor


@router.get("", response_model=list[MonitorOut])
def list_monitors(session: Session = Depends(get_db)) -> list[Monitor]:
    return crud.list_monitors(session, DEMO_USER_ID)


@router.post("", response_model=MonitorOut, status_code=201)
def create_monitor(payload: MonitorCreate, session: Session = Depends(get_db)) -> Monitor:
    try:
        return crud.create_monitor(session, DEMO_USER_ID, payload)
    except BlockedURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{monitor_id}", response_model=MonitorOut)
def get_monitor(monitor_id: int, session: Session = Depends(get_db)) -> Monitor:
    return _get_or_404(session, monitor_id)


@router.patch("/{monitor_id}", response_model=MonitorOut)
def update_monitor(
    monitor_id: int, payload: MonitorUpdate, session: Session = Depends(get_db)
) -> Monitor:
    monitor = _get_or_404(session, monitor_id)
    try:
        return crud.update_monitor(session, monitor, payload)
    except BlockedURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: int, session: Session = Depends(get_db)) -> Response:
    monitor = _get_or_404(session, monitor_id)
    crud.delete_monitor(session, monitor)
    return Response(status_code=204)


@router.post("/{monitor_id}/pause", response_model=MonitorOut)
def pause_monitor(monitor_id: int, session: Session = Depends(get_db)) -> Monitor:
    return crud.pause_monitor(session, _get_or_404(session, monitor_id))


@router.post("/{monitor_id}/resume", response_model=MonitorOut)
def resume_monitor(monitor_id: int, session: Session = Depends(get_db)) -> Monitor:
    return crud.resume_monitor(session, _get_or_404(session, monitor_id))


@router.get("/{monitor_id}/checks", response_model=list[CheckOut])
def list_checks(
    monitor_id: int,
    limit: int = Query(200, ge=1, le=1000),
    since: int | None = Query(None, description="Only checks at or after this epoch-ms time"),
    session: Session = Depends(get_db),
):
    _get_or_404(session, monitor_id)
    return crud.list_checks(session, monitor_id, limit=limit, since=since)


@router.get("/{monitor_id}/incidents", response_model=list[IncidentOut])
def list_incidents(
    monitor_id: int,
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db),
):
    _get_or_404(session, monitor_id)
    return crud.list_incidents(session, monitor_id, limit=limit)


@router.get("/{monitor_id}/series", response_model=list[SeriesPoint])
def monitor_series(
    monitor_id: int,
    window_hours: int = Query(24, ge=1, le=168, description="Aggregation window in hours"),
    max_points: int = Query(300, ge=10, le=1000, description="Maximum chart points"),
    session: Session = Depends(get_db),
):
    _get_or_404(session, monitor_id)
    return crud.monitor_series(
        session, monitor_id, window_hours=window_hours, max_points=max_points
    )


@router.get("/{monitor_id}/stats", response_model=MonitorStats)
def monitor_stats(
    monitor_id: int,
    window_hours: int = Query(24, ge=1, le=168, description="Aggregation window in hours"),
    session: Session = Depends(get_db),
):
    _get_or_404(session, monitor_id)
    return crud.monitor_stats(session, monitor_id, window_hours=window_hours)
