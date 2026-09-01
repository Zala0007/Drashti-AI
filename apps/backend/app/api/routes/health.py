from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.db.session import get_db
from app.schemas.registry import HealthResponse

router = APIRouter(tags=["service-health"])


@router.get("/health", response_model=HealthResponse, summary="Service liveness")
@router.get("/health/live", response_model=HealthResponse, include_in_schema=False)
def liveness() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=get_settings().app_name,
        version=__version__,
        checks={"process": "ok"},
    )


@router.get("/health/ready", response_model=HealthResponse, summary="Database readiness")
def readiness(session: Annotated[Session, Depends(get_db)], response: Response) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="not_ready",
            service=get_settings().app_name,
            version=__version__,
            checks={"database": "failed"},
        )
    return HealthResponse(
        status="ready",
        service=get_settings().app_name,
        version=__version__,
        checks={"database": "ok"},
    )
