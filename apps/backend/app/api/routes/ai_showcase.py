from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.schemas.ai_showcase import AIDetectionPage, AIPlatePage, AIShowcaseOverview
from app.services.ai_showcase import VEHICLE_CLASSES, AIShowcaseStore

router = APIRouter(prefix="/ai", tags=["ai-showcase"])


def get_ai_showcase(request: Request) -> AIShowcaseStore:
    settings = request.app.state.settings
    return AIShowcaseStore(settings.ai_showcase_database, settings.api_v1_prefix)


@router.get("/overview", response_model=AIShowcaseOverview)
def overview(
    store: Annotated[AIShowcaseStore, Depends(get_ai_showcase)],
) -> AIShowcaseOverview:
    return store.overview()


@router.get("/detections", response_model=AIDetectionPage)
def detections(
    store: Annotated[AIShowcaseStore, Depends(get_ai_showcase)],
    query: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    class_name: Annotated[str | None, Query()] = None,
    minimum_confidence: Annotated[float, Query(ge=0, le=1)] = 0.4,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=48)] = 24,
) -> AIDetectionPage:
    selected_class = class_name if class_name in VEHICLE_CLASSES else None
    return store.detections(
        query=query,
        class_name=selected_class,
        minimum_confidence=minimum_confidence,
        page=page,
        page_size=page_size,
    )


@router.get("/detections/{detection_id}/image")
def detection_image(
    detection_id: int,
    store: Annotated[AIShowcaseStore, Depends(get_ai_showcase)],
) -> Response:
    return Response(
        content=store.detection_image(detection_id),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store, no-cache, must-revalidate",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/plates", response_model=AIPlatePage)
def plates(
    store: Annotated[AIShowcaseStore, Depends(get_ai_showcase)],
    query: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=48)] = 18,
) -> AIPlatePage:
    return store.plates(query=query, page=page, page_size=page_size)


@router.get("/plates/{plate_id}/image")
def plate_image(
    plate_id: int,
    store: Annotated[AIShowcaseStore, Depends(get_ai_showcase)],
) -> Response:
    return Response(
        content=store.plate_image(plate_id),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store, no-cache, must-revalidate",
            "X-Content-Type-Options": "nosniff",
        },
    )
