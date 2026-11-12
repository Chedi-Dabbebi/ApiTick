"""Dashboard aggregate endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import crud
from ..db import DEMO_USER_ID, get_db
from ..schemas import DashboardSummary, RecentIncident

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary(
    window_hours: int = Query(24, ge=1, le=168, description="Aggregation window in hours"),
    session: Session = Depends(get_db),
) -> DashboardSummary:
    return crud.dashboard_summary(session, DEMO_USER_ID, window_hours=window_hours)


@router.get("/incidents", response_model=list[RecentIncident])
def incidents(
    limit: int = Query(8, ge=1, le=50, description="Maximum incidents to return"),
    session: Session = Depends(get_db),
) -> list[RecentIncident]:
    return crud.dashboard_incidents(session, DEMO_USER_ID, limit=limit)
