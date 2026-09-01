from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, BinaryIO
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_media_runtime_service
from app.schemas.media import (
    RuntimeCapabilitiesRead,
    RuntimeSessionList,
    RuntimeSessionRead,
)
from app.services import MediaRuntimeService

router = APIRouter(prefix="/federation", tags=["media-runtime"])

MEDIA_SECURITY_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/runtime/capabilities", response_model=RuntimeCapabilitiesRead)
def runtime_capabilities(
    service: Annotated[MediaRuntimeService, Depends(get_media_runtime_service)],
) -> RuntimeCapabilitiesRead:
    return service.capabilities()


@router.get("/runtime/sessions", response_model=RuntimeSessionList)
def list_runtime_sessions(
    service: Annotated[MediaRuntimeService, Depends(get_media_runtime_service)],
) -> RuntimeSessionList:
    return service.list_sessions()


@router.post(
    "/connections/{connection_id}/runtime/start",
    response_model=RuntimeSessionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_runtime_session(
    connection_id: UUID,
    service: Annotated[MediaRuntimeService, Depends(get_media_runtime_service)],
) -> RuntimeSessionRead:
    return service.start(str(connection_id))


@router.get("/runtime/sessions/{session_id}", response_model=RuntimeSessionRead)
def get_runtime_session(
    session_id: UUID,
    service: Annotated[MediaRuntimeService, Depends(get_media_runtime_service)],
) -> RuntimeSessionRead:
    return service.get_session(str(session_id))


@router.post("/runtime/sessions/{session_id}/stop", response_model=RuntimeSessionRead)
def stop_runtime_session(
    session_id: UUID,
    service: Annotated[MediaRuntimeService, Depends(get_media_runtime_service)],
) -> RuntimeSessionRead:
    return service.stop(str(session_id))


@router.post(
    "/runtime/sessions/{session_id}/restart",
    response_model=RuntimeSessionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def restart_runtime_session(
    session_id: UUID,
    service: Annotated[MediaRuntimeService, Depends(get_media_runtime_service)],
) -> RuntimeSessionRead:
    return service.restart(str(session_id))


@router.get("/runtime/sessions/{session_id}/playlist.m3u8")
def runtime_playlist(
    session_id: UUID,
    service: Annotated[MediaRuntimeService, Depends(get_media_runtime_service)],
) -> Response:
    return Response(
        content=service.playlist(str(session_id)),
        media_type="application/vnd.apple.mpegurl",
        headers=MEDIA_SECURITY_HEADERS,
    )


@router.get("/runtime/sessions/{session_id}/segments/{asset_name}")
def runtime_segment(
    session_id: UUID,
    asset_name: str,
    service: Annotated[MediaRuntimeService, Depends(get_media_runtime_service)],
) -> StreamingResponse:
    stream, size = service.segment(str(session_id), asset_name)

    def body() -> Iterator[bytes]:
        handle: BinaryIO = stream
        try:
            while chunk := handle.read(64 * 1024):
                yield chunk
        finally:
            handle.close()

    return StreamingResponse(
        body(),
        media_type="video/mp2t",
        headers={**MEDIA_SECURITY_HEADERS, "Content-Length": str(size)},
    )
