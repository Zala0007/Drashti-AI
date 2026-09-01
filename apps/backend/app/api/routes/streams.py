from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_stream_engine, get_stream_processing_service
from app.errors import NotFoundError
from app.schemas.streams import (
    AnalyticsCapabilitiesRead,
    CameraAnalyticsList,
    CameraAnalyticsRead,
    StreamAggregateMetricsRead,
    StreamCapabilitiesRead,
    StreamSessionList,
    StreamSessionRead,
    StreamStartRequest,
    stream_session_read,
)
from app.services.streams import StreamProcessingService
from app.stream_engine import StreamEngine

router = APIRouter(prefix="/streams", tags=["stream-processing"])


@router.get("/analytics/capabilities", response_model=AnalyticsCapabilitiesRead)
def analytics_capabilities(request: Request) -> AnalyticsCapabilitiesRead:
    return AnalyticsCapabilitiesRead.model_validate(
        request.app.state.analytics_worker.capabilities()
    )


@router.get("/analytics", response_model=CameraAnalyticsList)
def analytics_results(request: Request) -> CameraAnalyticsList:
    items = [
        CameraAnalyticsRead.model_validate(item)
        for item in request.app.state.analytics_worker.list()
    ]
    return CameraAnalyticsList(items=items, total=len(items))


@router.get("/{camera_id}/analytics", response_model=CameraAnalyticsRead)
def camera_analytics(camera_id: UUID, request: Request) -> CameraAnalyticsRead:
    result = request.app.state.analytics_worker.get(str(camera_id))
    if result is None:
        raise NotFoundError("camera_analytics", str(camera_id))
    return CameraAnalyticsRead.model_validate(result)


@router.get("/capabilities", response_model=StreamCapabilitiesRead)
def capabilities(
    engine: Annotated[StreamEngine, Depends(get_stream_engine)],
) -> StreamCapabilitiesRead:
    return StreamCapabilitiesRead.model_validate(engine.capabilities())


@router.get("/metrics", response_model=StreamAggregateMetricsRead)
def aggregate_metrics(
    engine: Annotated[StreamEngine, Depends(get_stream_engine)],
) -> StreamAggregateMetricsRead:
    return StreamAggregateMetricsRead.model_validate(engine.metrics())


@router.get("", response_model=StreamSessionList)
def list_streams(
    engine: Annotated[StreamEngine, Depends(get_stream_engine)],
) -> StreamSessionList:
    items = [stream_session_read(item) for item in engine.list()]
    return StreamSessionList(items=items, total=len(items))


@router.post(
    "/{camera_id}/start",
    response_model=StreamSessionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_stream(
    camera_id: UUID,
    service: Annotated[StreamProcessingService, Depends(get_stream_processing_service)],
    payload: StreamStartRequest | None = None,
) -> StreamSessionRead:
    return service.start(str(camera_id), payload or StreamStartRequest())


@router.post("/{camera_id}/stop", response_model=StreamSessionRead)
def stop_stream(
    camera_id: UUID,
    service: Annotated[StreamProcessingService, Depends(get_stream_processing_service)],
) -> StreamSessionRead:
    return service.stop(str(camera_id))


@router.post(
    "/{camera_id}/restart",
    response_model=StreamSessionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def restart_stream(
    camera_id: UUID,
    service: Annotated[StreamProcessingService, Depends(get_stream_processing_service)],
    payload: StreamStartRequest | None = None,
) -> StreamSessionRead:
    return service.restart(str(camera_id), payload or StreamStartRequest())


@router.get("/{camera_id}/health", response_model=StreamSessionRead)
def stream_health(
    camera_id: UUID,
    engine: Annotated[StreamEngine, Depends(get_stream_engine)],
) -> StreamSessionRead:
    return stream_session_read(engine.get(str(camera_id)))


@router.get("/{camera_id}/preview.mjpg")
def stream_preview(
    camera_id: UUID,
    engine: Annotated[StreamEngine, Depends(get_stream_engine)],
) -> StreamingResponse:
    preview_interval = 1 / engine.config.preview_fps

    async def body() -> AsyncIterator[bytes]:
        frame_number = -1
        while True:
            try:
                result = await asyncio.to_thread(
                    engine.latest_jpeg,
                    str(camera_id),
                    after_frame=frame_number,
                    timeout=1.0,
                )
            except NotFoundError:
                return
            if result is None:
                continue
            frame_number, jpeg = result
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(jpeg)}\r\n".encode("ascii")
                + f"X-Frame-Number: {frame_number}\r\n".encode("ascii")
                + b"Cache-Control: no-store\r\n\r\n"
                + jpeg
                + b"\r\n"
            )
            await asyncio.sleep(preview_interval)

    return StreamingResponse(
        body(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "private, no-store, no-cache, must-revalidate",
            "X-Content-Type-Options": "nosniff",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{camera_id}/preview.jpg")
def stream_preview_snapshot(
    camera_id: UUID,
    engine: Annotated[StreamEngine, Depends(get_stream_engine)],
) -> Response:
    # Snapshot requests must never reserve a worker while a camera is still
    # connecting. The wall retries with a staggered timer, leaving request
    # capacity available for registry, health and operator actions.
    result = engine.latest_jpeg(str(camera_id), timeout=0.0)
    if result is None:
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"Cache-Control": "private, no-store, no-cache, must-revalidate"},
        )
    frame_number, jpeg = result
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store, no-cache, must-revalidate",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Number": str(frame_number),
        },
    )
