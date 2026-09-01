from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.dependencies import ActorContext, get_investigator_context
from app.schemas.visual_intelligence import (
    VisualBackfillRequest,
    VisualIntelligenceRead,
    VisualIntelligenceStatus,
    VisualQueueResponse,
    VisualSearchRequest,
    VisualSearchResponse,
)
from app.services.visual_intelligence import VisualIntelligenceEngine

router = APIRouter(prefix="/visual-intelligence", tags=["visual-intelligence"])


def get_visual_engine(request: Request) -> VisualIntelligenceEngine:
    return request.app.state.visual_intelligence


@router.get("/status", response_model=VisualIntelligenceStatus)
def engine_status(
    engine: Annotated[VisualIntelligenceEngine, Depends(get_visual_engine)],
    _: Annotated[ActorContext, Depends(get_investigator_context)],
) -> VisualIntelligenceStatus:
    return engine.status()


@router.post("/search", response_model=VisualSearchResponse)
def visual_search(
    payload: VisualSearchRequest,
    engine: Annotated[VisualIntelligenceEngine, Depends(get_visual_engine)],
    actor: Annotated[ActorContext, Depends(get_investigator_context)],
) -> VisualSearchResponse:
    return engine.search(
        query=payload.query,
        filters=payload.filters,
        page=payload.page,
        page_size=payload.page_size,
        actor_id=actor.actor_id,
    )


@router.get("", response_model=VisualSearchResponse)
def list_intelligence(
    engine: Annotated[VisualIntelligenceEngine, Depends(get_visual_engine)],
    actor: Annotated[ActorContext, Depends(get_investigator_context)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=48)] = 18,
) -> VisualSearchResponse:
    from app.schemas.visual_intelligence import VisualSearchFilters

    return engine.search(
        query="",
        filters=VisualSearchFilters(),
        page=page,
        page_size=page_size,
        actor_id=actor.actor_id,
    )


@router.post("/backfill", response_model=VisualQueueResponse, status_code=status.HTTP_202_ACCEPTED)
def backfill(
    payload: VisualBackfillRequest,
    engine: Annotated[VisualIntelligenceEngine, Depends(get_visual_engine)],
    _: Annotated[ActorContext, Depends(get_investigator_context)],
) -> VisualQueueResponse:
    return engine.backfill(payload.limit, retry_failed=payload.retry_failed)


@router.post(
    "/analyze/{event_id}",
    response_model=VisualQueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def analyze_event(
    event_id: int,
    engine: Annotated[VisualIntelligenceEngine, Depends(get_visual_engine)],
    _: Annotated[ActorContext, Depends(get_investigator_context)],
) -> VisualQueueResponse:
    queued = engine.queue_detection(event_id)
    return VisualQueueResponse(
        queued=int(queued),
        skipped=int(not queued),
        queue_depth=engine.status().queue_depth,
        message="Vehicle crop queued for analysis."
        if queued
        else "This crop is already queued or analyzed.",
    )


@router.get("/{intelligence_id}", response_model=VisualIntelligenceRead)
def visual_profile(
    intelligence_id: int,
    engine: Annotated[VisualIntelligenceEngine, Depends(get_visual_engine)],
    _: Annotated[ActorContext, Depends(get_investigator_context)],
) -> VisualIntelligenceRead:
    return engine.get(intelligence_id)
