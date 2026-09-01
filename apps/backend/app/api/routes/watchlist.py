from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_watchlist_service
from app.schemas.watchlist import (
    WatchlistAlertAction,
    WatchlistAlertList,
    WatchlistAlertRead,
    WatchlistDashboard,
    WatchlistEntryCreate,
    WatchlistEntryList,
    WatchlistEntryRead,
    WatchlistEntryUpdate,
)
from app.services.watchlist import WatchlistService

router = APIRouter(prefix="/watchlist", tags=["watchlist-alerts"])


@router.get("/dashboard", response_model=WatchlistDashboard)
def dashboard(
    service: Annotated[WatchlistService, Depends(get_watchlist_service)],
) -> WatchlistDashboard:
    return service.dashboard()


@router.get("/entries", response_model=WatchlistEntryList)
def list_entries(
    service: Annotated[WatchlistService, Depends(get_watchlist_service)],
) -> WatchlistEntryList:
    return service.list_entries()


@router.post(
    "/entries", response_model=WatchlistEntryRead, status_code=status.HTTP_201_CREATED
)
def create_entry(
    payload: WatchlistEntryCreate,
    service: Annotated[WatchlistService, Depends(get_watchlist_service)],
) -> WatchlistEntryRead:
    return service.create(payload)


@router.patch("/entries/{entry_id}", response_model=WatchlistEntryRead)
def update_entry(
    entry_id: UUID,
    payload: WatchlistEntryUpdate,
    service: Annotated[WatchlistService, Depends(get_watchlist_service)],
) -> WatchlistEntryRead:
    return service.update(str(entry_id), payload)


@router.get("/alerts", response_model=WatchlistAlertList)
def list_alerts(
    service: Annotated[WatchlistService, Depends(get_watchlist_service)],
    alert_status: Annotated[
        Literal["new", "acknowledged", "resolved", "false_positive"] | None,
        Query(alias="status"),
    ] = None,
) -> WatchlistAlertList:
    return service.list_alerts(alert_status)


@router.post("/alerts/{alert_id}/review", response_model=WatchlistAlertRead)
def review_alert(
    alert_id: UUID,
    payload: WatchlistAlertAction,
    service: Annotated[WatchlistService, Depends(get_watchlist_service)],
) -> WatchlistAlertRead:
    return service.update_alert(str(alert_id), payload)
