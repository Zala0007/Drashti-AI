from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import (
    get_connection_filters,
    get_federation_service,
    get_government_feed_service,
)
from app.repositories import ConnectionFilters
from app.schemas.federation import (
    AdapterList,
    ConnectionAuditList,
    ConnectionCreate,
    ConnectionList,
    ConnectionRead,
    ConnectionStatistics,
    ConnectionUpdate,
)
from app.schemas.government_feeds import (
    GovernmentFeedCatalogueRead,
    GovernmentFeedSyncRead,
    GovernmentFeedSyncRequest,
)
from app.services import FederationService, GovernmentFeedService

router = APIRouter(prefix="/federation", tags=["federation"])


@router.get(
    "/catalogues/government-feeds",
    response_model=GovernmentFeedCatalogueRead,
)
def government_feed_catalogue(
    service: Annotated[GovernmentFeedService, Depends(get_government_feed_service)],
) -> GovernmentFeedCatalogueRead:
    return service.catalogue()


@router.post(
    "/catalogues/government-feeds/sync",
    response_model=GovernmentFeedSyncRead,
    status_code=status.HTTP_200_OK,
)
def sync_government_feeds(
    payload: GovernmentFeedSyncRequest,
    service: Annotated[GovernmentFeedService, Depends(get_government_feed_service)],
) -> GovernmentFeedSyncRead:
    return service.sync(payload)


@router.get("/adapters", response_model=AdapterList)
def list_adapters(
    service: Annotated[FederationService, Depends(get_federation_service)],
) -> AdapterList:
    return service.adapters_list()


# Static connection routes are deliberately registered before the UUID route.
@router.get("/connections/statistics", response_model=ConnectionStatistics)
def connection_statistics(
    service: Annotated[FederationService, Depends(get_federation_service)],
    filters: Annotated[ConnectionFilters, Depends(get_connection_filters)],
) -> ConnectionStatistics:
    return service.statistics(filters=filters)


@router.get("/connections", response_model=ConnectionList)
def list_connections(
    service: Annotated[FederationService, Depends(get_federation_service)],
    filters: Annotated[ConnectionFilters, Depends(get_connection_filters)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> ConnectionList:
    return service.list_connections(filters=filters, page=page, page_size=page_size)


@router.post(
    "/connections",
    response_model=ConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_connection(
    payload: ConnectionCreate,
    service: Annotated[FederationService, Depends(get_federation_service)],
) -> ConnectionRead:
    return service.create_connection(payload)


@router.get("/connections/{connection_id}", response_model=ConnectionRead)
def get_connection(
    connection_id: UUID,
    service: Annotated[FederationService, Depends(get_federation_service)],
) -> ConnectionRead:
    return service.get_connection(str(connection_id))


@router.patch("/connections/{connection_id}", response_model=ConnectionRead)
def update_connection(
    connection_id: UUID,
    payload: ConnectionUpdate,
    service: Annotated[FederationService, Depends(get_federation_service)],
) -> ConnectionRead:
    return service.update_connection(str(connection_id), payload)


@router.post("/connections/{connection_id}/probe", response_model=ConnectionRead)
def probe_connection(
    connection_id: UUID,
    service: Annotated[FederationService, Depends(get_federation_service)],
) -> ConnectionRead:
    return service.probe_connection(str(connection_id))


@router.post("/connections/{connection_id}/enable", response_model=ConnectionRead)
def enable_connection(
    connection_id: UUID,
    service: Annotated[FederationService, Depends(get_federation_service)],
) -> ConnectionRead:
    return service.set_enabled(str(connection_id), enabled=True)


@router.post("/connections/{connection_id}/disable", response_model=ConnectionRead)
def disable_connection(
    connection_id: UUID,
    service: Annotated[FederationService, Depends(get_federation_service)],
) -> ConnectionRead:
    return service.set_enabled(str(connection_id), enabled=False)


@router.get("/connections/{connection_id}/audit", response_model=ConnectionAuditList)
def connection_audit(
    connection_id: UUID,
    service: Annotated[FederationService, Depends(get_federation_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ConnectionAuditList:
    return service.connection_audit(str(connection_id), page=page, page_size=page_size)
