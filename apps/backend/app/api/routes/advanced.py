from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import (
    get_camera_health_ingest_service,
    get_camera_health_service,
    get_case_service,
    get_coverage_service,
    get_reid_ingest_service,
    get_reid_service,
)
from app.schemas.advanced import (
    CaseActivityCreate,
    CaseCreate,
    CaseExportRead,
    CaseList,
    CaseTransition,
    CaseWorkspace,
    CoverageAnalysisRead,
    CoverageRunRequest,
    CoverageWhatIfRead,
    CoverageWhatIfRequest,
    DemoReIDRead,
    EvidenceAttach,
    EvidenceRead,
    HealthAggregateCreate,
    HealthAggregateRead,
    HealthDashboard,
    HealthHistoryRead,
    ReIDMatchRead,
    ReIDQuery,
    ReIDResult,
    ReIDReview,
    VehicleObservationCreate,
    VehicleObservationRead,
)
from app.services import CameraHealthService, CaseService, CoverageService, ReIDService

router = APIRouter(tags=["advanced-intelligence"])


@router.post(
    "/reid/observations",
    response_model=VehicleObservationRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_vehicle_observation(
    payload: VehicleObservationCreate,
    service: Annotated[ReIDService, Depends(get_reid_ingest_service)],
) -> VehicleObservationRead:
    return service.ingest(payload)


@router.post("/reid/investigations/{investigation_id}/rank", response_model=ReIDResult)
def rank_vehicle_matches(
    investigation_id: UUID,
    payload: ReIDQuery,
    service: Annotated[ReIDService, Depends(get_reid_service)],
) -> ReIDResult:
    return service.rank(str(investigation_id), payload)


@router.post("/reid/investigations/{investigation_id}/demo", response_model=DemoReIDRead)
def seed_reid_demo(
    investigation_id: UUID,
    service: Annotated[ReIDService, Depends(get_reid_service)],
) -> DemoReIDRead:
    return service.seed_demo(str(investigation_id))


@router.post("/reid/matches/{match_id}/review", response_model=ReIDMatchRead)
def review_vehicle_match(
    match_id: UUID,
    payload: ReIDReview,
    service: Annotated[ReIDService, Depends(get_reid_service)],
) -> ReIDMatchRead:
    return service.review(str(match_id), payload)


@router.get("/cases", response_model=CaseList)
def list_cases(
    service: Annotated[CaseService, Depends(get_case_service)],
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status_filter: Annotated[
        Literal["open", "active", "on_hold", "closed", "archived"] | None,
        Query(alias="status"),
    ] = None,
    district: Annotated[str | None, Query(max_length=100)] = None,
    assigned_to: Annotated[str | None, Query(max_length=160)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
) -> CaseList:
    return service.list(
        search=search,
        status=status_filter,
        district=district,
        assigned_to=assigned_to,
        page=page,
        page_size=page_size,
    )


@router.post("/cases", response_model=CaseWorkspace, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreate,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> CaseWorkspace:
    return service.create(payload)


@router.get("/cases/{case_id}", response_model=CaseWorkspace)
def get_case(
    case_id: UUID,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> CaseWorkspace:
    return service.workspace(str(case_id))


@router.post("/cases/{case_id}/evidence", response_model=CaseWorkspace)
def attach_evidence(
    case_id: UUID,
    payload: EvidenceAttach,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> CaseWorkspace:
    return service.attach(str(case_id), payload)


@router.get("/cases/{case_id}/evidence/{evidence_id}", response_model=EvidenceRead)
def view_evidence(
    case_id: UUID,
    evidence_id: UUID,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> EvidenceRead:
    return service.view_evidence(str(case_id), str(evidence_id))


@router.post("/cases/{case_id}/activity", response_model=CaseWorkspace)
def add_case_activity(
    case_id: UUID,
    payload: CaseActivityCreate,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> CaseWorkspace:
    return service.record_activity(str(case_id), payload)


@router.post("/cases/{case_id}/transition", response_model=CaseWorkspace)
def transition_case(
    case_id: UUID,
    payload: CaseTransition,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> CaseWorkspace:
    return service.transition(str(case_id), payload)


@router.post("/cases/{case_id}/export", response_model=CaseExportRead)
def export_case(
    case_id: UUID,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> CaseExportRead:
    return service.export(str(case_id))


@router.get("/camera-health/dashboard", response_model=HealthDashboard)
def camera_health_dashboard(
    service: Annotated[CameraHealthService, Depends(get_camera_health_service)],
) -> HealthDashboard:
    return service.dashboard()


@router.get("/camera-health/cameras/{camera_id}/history", response_model=HealthHistoryRead)
def camera_health_history(
    camera_id: UUID,
    service: Annotated[CameraHealthService, Depends(get_camera_health_service)],
    limit: Annotated[int, Query(ge=1, le=672)] = 96,
) -> HealthHistoryRead:
    return service.history(str(camera_id), limit=limit)


@router.post("/camera-health/snapshot", response_model=HealthDashboard)
def capture_camera_health(
    service: Annotated[CameraHealthService, Depends(get_camera_health_service)],
) -> HealthDashboard:
    return service.capture_live_snapshot()


@router.post(
    "/camera-health/aggregates",
    response_model=HealthAggregateRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_camera_health(
    payload: HealthAggregateCreate,
    service: Annotated[CameraHealthService, Depends(get_camera_health_ingest_service)],
) -> HealthAggregateRead:
    return service.ingest(payload)


@router.get("/coverage/latest", response_model=CoverageAnalysisRead)
def latest_coverage_analysis(
    service: Annotated[CoverageService, Depends(get_coverage_service)],
    district: Annotated[str | None, Query(max_length=100)] = None,
) -> CoverageAnalysisRead:
    return service.latest(district)


@router.post("/coverage/analyses", response_model=CoverageAnalysisRead)
def analyze_coverage(
    payload: CoverageRunRequest,
    service: Annotated[CoverageService, Depends(get_coverage_service)],
) -> CoverageAnalysisRead:
    return service.analyze(payload)


@router.post("/coverage/what-if", response_model=CoverageWhatIfRead)
def simulate_camera_failure(
    payload: CoverageWhatIfRequest,
    service: Annotated[CoverageService, Depends(get_coverage_service)],
) -> CoverageWhatIfRead:
    return service.what_if(str(payload.camera_id))
