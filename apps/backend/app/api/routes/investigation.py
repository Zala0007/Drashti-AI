from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_investigation_event_service, get_investigation_service
from app.schemas.investigation import (
    ANPREventCreate,
    DemoScenarioRead,
    DemoScenarioRequest,
    InvestigationCreate,
    InvestigationList,
    InvestigationTransition,
    InvestigationWorkspace,
    PredictionBacktestRead,
)
from app.services.investigation import InvestigationService

router = APIRouter(prefix="/investigations", tags=["special-investigation"])


@router.get("", response_model=InvestigationList)
def list_investigations(
    service: Annotated[InvestigationService, Depends(get_investigation_service)],
) -> InvestigationList:
    return service.list()


@router.post("", response_model=InvestigationWorkspace, status_code=status.HTTP_201_CREATED)
def create_investigation(
    payload: InvestigationCreate,
    service: Annotated[InvestigationService, Depends(get_investigation_service)],
) -> InvestigationWorkspace:
    return service.create(payload)


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
def ingest_anpr_event(
    payload: ANPREventCreate,
    service: Annotated[InvestigationService, Depends(get_investigation_event_service)],
) -> dict[str, Any]:
    return service.ingest_event(payload)


@router.post("/demo-scenario", response_model=DemoScenarioRead)
def seed_demo_scenario(
    payload: DemoScenarioRequest,
    service: Annotated[InvestigationService, Depends(get_investigation_service)],
) -> DemoScenarioRead:
    return service.seed_demo(payload.target_plate)


@router.get("/{case_id}", response_model=InvestigationWorkspace)
def investigation_workspace(
    case_id: UUID,
    service: Annotated[InvestigationService, Depends(get_investigation_service)],
) -> InvestigationWorkspace:
    return service.workspace(str(case_id))


@router.get("/{case_id}/prediction-backtest", response_model=PredictionBacktestRead)
def prediction_backtest(
    case_id: UUID,
    service: Annotated[InvestigationService, Depends(get_investigation_service)],
) -> PredictionBacktestRead:
    return service.backtest(str(case_id))


@router.post("/{case_id}/transition", response_model=InvestigationWorkspace)
def transition_investigation(
    case_id: UUID,
    payload: InvestigationTransition,
    service: Annotated[InvestigationService, Depends(get_investigation_service)],
) -> InvestigationWorkspace:
    return service.transition(str(case_id), payload)
