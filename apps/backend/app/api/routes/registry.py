from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile, status

from app.api.dependencies import get_camera_filters, get_registry_service
from app.repositories import CameraFilters
from app.schemas.registry import (
    AuditList,
    CameraCreate,
    CameraFilterOptions,
    CameraList,
    CameraRead,
    CameraStatistics,
    CameraUpdate,
    DepartmentCreate,
    DepartmentList,
    DepartmentRead,
    DepartmentUpdate,
    DuplicateMode,
    GeoJSONFeatureCollection,
    HeartbeatRequest,
    ImportResponse,
    RetirementRequest,
)
from app.services import RegistryService

router = APIRouter()


@router.get("/departments", response_model=DepartmentList, tags=["departments"])
def list_departments(
    service: Annotated[RegistryService, Depends(get_registry_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    search: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    include_inactive: bool = False,
) -> DepartmentList:
    return service.list_departments(
        page=page,
        page_size=page_size,
        search=search,
        include_inactive=include_inactive,
    )


@router.post(
    "/departments",
    response_model=DepartmentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["departments"],
)
def create_department(
    payload: DepartmentCreate,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> DepartmentRead:
    return service.create_department(payload)


@router.get("/departments/{department_id}", response_model=DepartmentRead, tags=["departments"])
def get_department(
    department_id: UUID,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> DepartmentRead:
    return service.get_department(str(department_id))


@router.patch("/departments/{department_id}", response_model=DepartmentRead, tags=["departments"])
def update_department(
    department_id: UUID,
    payload: DepartmentUpdate,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> DepartmentRead:
    return service.update_department(str(department_id), payload)


# Static camera routes must be declared before /cameras/{camera_id}.
@router.get(
    "/cameras/filter-options",
    response_model=CameraFilterOptions,
    tags=["camera-registry", "gis"],
)
def camera_filter_options(
    service: Annotated[RegistryService, Depends(get_registry_service)],
    include_retired: bool = False,
) -> CameraFilterOptions:
    return service.filter_options(include_retired=include_retired)


@router.get("/cameras/statistics", response_model=CameraStatistics, tags=["camera-registry"])
def camera_statistics(
    service: Annotated[RegistryService, Depends(get_registry_service)],
    filters: Annotated[CameraFilters, Depends(get_camera_filters)],
) -> CameraStatistics:
    return service.statistics(filters=filters)


@router.get(
    "/cameras/geojson",
    response_model=GeoJSONFeatureCollection,
    tags=["camera-registry", "gis"],
)
def camera_geojson(
    service: Annotated[RegistryService, Depends(get_registry_service)],
    filters: Annotated[CameraFilters, Depends(get_camera_filters)],
    limit: Annotated[int, Query(ge=1, le=10_000)] = 5_000,
) -> GeoJSONFeatureCollection:
    return service.geojson(filters=filters, limit=limit)


@router.post("/cameras/import", response_model=ImportResponse, tags=["camera-registry"])
async def import_cameras(
    service: Annotated[RegistryService, Depends(get_registry_service)],
    file: Annotated[UploadFile, File(description="UTF-8 CSV, maximum 10 MiB")],
    on_duplicate: DuplicateMode = DuplicateMode.skip,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=200)
    ] = None,
) -> ImportResponse:
    content = await file.read(10 * 1024 * 1024 + 1)
    return service.import_csv(
        content=content,
        supplied_idempotency_key=idempotency_key,
        on_duplicate=on_duplicate,
    )


@router.get("/cameras", response_model=CameraList, tags=["camera-registry"])
def list_cameras(
    service: Annotated[RegistryService, Depends(get_registry_service)],
    filters: Annotated[CameraFilters, Depends(get_camera_filters)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> CameraList:
    return service.list_cameras(filters=filters, page=page, page_size=page_size)


@router.post(
    "/cameras",
    response_model=CameraRead,
    status_code=status.HTTP_201_CREATED,
    tags=["camera-registry"],
)
def create_camera(
    payload: CameraCreate,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> CameraRead:
    return service.create_camera(payload)


@router.get("/cameras/{camera_id}", response_model=CameraRead, tags=["camera-registry"])
def get_camera(
    camera_id: UUID,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> CameraRead:
    return service.get_camera(str(camera_id))


@router.patch("/cameras/{camera_id}", response_model=CameraRead, tags=["camera-registry"])
def update_camera(
    camera_id: UUID,
    payload: CameraUpdate,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> CameraRead:
    return service.update_camera(str(camera_id), payload)


@router.post("/cameras/{camera_id}/retire", response_model=CameraRead, tags=["camera-registry"])
def retire_camera(
    camera_id: UUID,
    payload: RetirementRequest,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> CameraRead:
    return service.retire_camera(str(camera_id), reason=payload.reason)


@router.post("/cameras/{camera_id}/heartbeat", response_model=CameraRead, tags=["camera-health"])
def camera_heartbeat(
    camera_id: UUID,
    payload: HeartbeatRequest,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> CameraRead:
    return service.record_heartbeat(str(camera_id), payload)


@router.get("/cameras/{camera_id}/audit", response_model=AuditList, tags=["audit"])
def camera_audit(
    camera_id: UUID,
    service: Annotated[RegistryService, Depends(get_registry_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditList:
    return service.camera_audit(str(camera_id), page=page, page_size=page_size)
