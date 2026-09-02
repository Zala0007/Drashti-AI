from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.analytics import AnalyticsConfig, LiveAnalyticsWorker
from app.api.routes import (
    advanced_router,
    ai_showcase_router,
    credentials_router,
    federation_router,
    health_router,
    investigation_router,
    media_router,
    registry_router,
    streams_router,
    visual_intelligence_router,
    watchlist_router,
)
from app.config import Settings, get_settings
from app.db import Base, SessionLocal, engine
from app.errors import RegistryError
from app.federation.security import load_or_create_development_key
from app.media import MediaRuntimeManager, RuntimeConfig
from app.services.live_intelligence import LiveIntelligenceRouter
from app.services.visual_intelligence import GroqVisionProvider, VisualIntelligenceEngine
from app.stream_engine import StreamEngine, StreamEngineConfig

logger = logging.getLogger("drishti.registry")


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": _request_id(request),
            }
        },
        headers={"X-Request-ID": _request_id(request) or ""},
    )


def create_app(
    *,
    settings: Settings | None = None,
    initialize_database: bool | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    if (
        app_settings.app_env == "development"
        and app_settings.federation_auto_development_key
        and not app_settings.federation_encryption_key
    ):
        try:
            local_key = load_or_create_development_key(app_settings.federation_development_key_file)
        except ValueError as exc:
            raise RuntimeError("Local federation encryption key initialization failed") from exc
        app_settings = replace(
            app_settings,
            federation_encryption_key=local_key,
            federation_encryption_key_id="local-development-file-v1",
        )
    should_initialize = (
        app_settings.auto_create_schema if initialize_database is None else initialize_database
    )
    configured_level = getattr(logging, app_settings.log_level, logging.INFO)
    logger.setLevel(configured_level)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=configured_level, format="%(message)s")

    media_runtime = MediaRuntimeManager(
        RuntimeConfig(
            runtime_root=app_settings.federation_runtime_root,
            configured_binary=app_settings.ffmpeg_binary,
            decoder_backend=app_settings.stream_engine_decoder_backend,
            segment_duration_seconds=app_settings.federation_runtime_segment_seconds,
            playlist_window=app_settings.federation_runtime_playlist_window,
            watchdog_seconds=app_settings.federation_runtime_watchdog_seconds,
            max_backoff_seconds=app_settings.federation_runtime_max_backoff_seconds,
            max_restarts=app_settings.federation_runtime_max_restarts,
            stop_timeout_seconds=app_settings.federation_runtime_stop_timeout_seconds,
            max_active_sessions=app_settings.federation_runtime_max_active_sessions,
            credential_resolver_mode=(
                "encrypted_database_profiles"
                if app_settings.federation_encryption_key
                else "fail_closed"
            ),
        )
    )
    stream_engine = StreamEngine(
        StreamEngineConfig(
            configured_binary=app_settings.ffmpeg_binary,
            decoder_backend=app_settings.stream_engine_decoder_backend,
            rtsp_transport=app_settings.stream_engine_rtsp_transport,
            width=app_settings.stream_engine_output_width,
            height=app_settings.stream_engine_output_height,
            decode_fps=app_settings.stream_engine_decode_fps,
            target_fps=app_settings.stream_engine_target_fps,
            buffer_size=app_settings.stream_engine_buffer_size,
            max_frame_age_ms=app_settings.stream_engine_max_frame_age_ms,
            batch_size=app_settings.stream_engine_batch_size,
            batch_timeout_ms=app_settings.stream_engine_batch_timeout_ms,
            health_timeout_seconds=app_settings.stream_engine_health_timeout_seconds,
            http_health_timeout_seconds=(app_settings.stream_engine_http_health_timeout_seconds),
            startup_timeout_seconds=app_settings.stream_engine_startup_timeout_seconds,
            http_startup_timeout_seconds=(app_settings.stream_engine_http_startup_timeout_seconds),
            freeze_threshold_seconds=app_settings.stream_engine_freeze_threshold_seconds,
            max_backoff_seconds=app_settings.stream_engine_max_backoff_seconds,
            stop_timeout_seconds=app_settings.stream_engine_stop_timeout_seconds,
            max_active_sessions=app_settings.stream_engine_max_active_sessions,
            preview_fps=app_settings.stream_engine_preview_fps,
        )
    )
    analytics_worker = LiveAnalyticsWorker(
        stream_engine,
        AnalyticsConfig(
            enabled=(app_settings.live_analytics_enabled and app_settings.app_env != "test"),
            general_model_path=app_settings.live_analytics_general_model,
            plate_model_path=app_settings.live_analytics_plate_model,
            evidence_database=app_settings.ai_showcase_database,
            confidence=app_settings.live_analytics_confidence,
            plate_confidence=app_settings.live_analytics_plate_confidence,
            evidence_interval_seconds=app_settings.live_analytics_evidence_interval_seconds,
            ocr_enabled=app_settings.live_analytics_ocr_enabled,
            ocr_timeout_seconds=app_settings.live_analytics_ocr_timeout_seconds,
            ocr_cooldown_seconds=app_settings.live_analytics_ocr_cooldown_seconds,
            ocr_batch_size=app_settings.live_analytics_ocr_batch_size,
            google_accept_confidence=(
                app_settings.live_analytics_google_accept_confidence
            ),
            groq_ocr_enabled=app_settings.live_analytics_groq_ocr_enabled,
            groq_api_key=app_settings.groq_api_key,
            groq_api_keys=app_settings.groq_api_keys,
            groq_model=app_settings.groq_vision_model,
            groq_timeout_seconds=app_settings.groq_request_timeout,
            groq_max_retries=app_settings.groq_max_retries,
            groq_accept_confidence=(app_settings.live_analytics_groq_accept_confidence),
            groq_minimum_interval_seconds=(
                app_settings.live_analytics_groq_ocr_request_interval_seconds
            ),
        ),
    )
    visual_provider = None
    has_groq_keys = bool(app_settings.groq_api_keys or app_settings.groq_api_key)
    if app_settings.visual_intelligence_enabled and has_groq_keys:
        try:
            visual_provider = GroqVisionProvider(
                api_keys=app_settings.groq_api_keys or (
                    (app_settings.groq_api_key,) if app_settings.groq_api_key else ()
                ),
                model=app_settings.groq_vision_model,
                timeout=app_settings.groq_request_timeout,
                max_retries=app_settings.groq_max_retries,
            )
        except RuntimeError:
            logger.warning(
                "Visual Intelligence provider is unavailable; install backend dependencies"
            )
    live_intelligence = LiveIntelligenceRouter(
        app_settings.ai_showcase_database,
        session_factory=SessionLocal,
        app_env=app_settings.app_env,
        api_prefix=app_settings.api_v1_prefix,
        enabled=app_settings.app_env != "test",
    )
    visual_intelligence = VisualIntelligenceEngine(
        app_settings.ai_showcase_database,
        api_prefix=app_settings.api_v1_prefix,
        provider=visual_provider,
        max_queue_size=app_settings.visual_intelligence_queue_size,
        retry_attempts=max(1, app_settings.groq_max_retries + 1),
        minimum_request_interval_seconds=(
            app_settings.visual_intelligence_request_interval_seconds
        ),
        auto_analyze=(
            app_settings.visual_intelligence_auto_analyze and app_settings.app_env != "test"
        ),
        on_profile_completed=live_intelligence.queue_visual_profile,
    )

    def route_vehicle_evidence(detection_id: int) -> None:
        live_intelligence.queue_vehicle(detection_id)
        if app_settings.visual_intelligence_auto_analyze:
            visual_intelligence.queue_detection(detection_id, raise_if_unavailable=False)

    analytics_worker.set_vehicle_evidence_callback(route_vehicle_evidence)
    analytics_worker.set_plate_evidence_callback(live_intelligence.queue_plate)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if should_initialize:
            # SQLite local/demo convenience only. PostgreSQL deployments run Alembic.
            Base.metadata.create_all(bind=engine)
        media_runtime.startup()
        stream_engine.startup()
        live_intelligence.startup()
        visual_intelligence.startup()
        analytics_worker.startup()
        try:
            yield
        finally:
            analytics_worker.shutdown()
            visual_intelligence.shutdown()
            live_intelligence.shutdown()
            stream_engine.shutdown()
            media_runtime.shutdown()

    application = FastAPI(
        title=app_settings.app_name,
        version=__version__,
        description=(
            "Vendor-neutral camera inventory, health and geospatial discovery API "
            "for the Drishti AI federated CCTV platform."
        ),
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.media_runtime = media_runtime
    application.state.stream_engine = stream_engine
    application.state.analytics_worker = analytics_worker
    application.state.visual_intelligence = visual_intelligence
    application.state.live_intelligence = live_intelligence

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_origins),
        allow_credentials="*" not in app_settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Actor-ID",
            "X-Actor-Role",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID"],
    )

    @application.middleware("http")
    async def attach_request_id(request: Request, call_next: Any) -> Any:
        supplied = request.headers.get("X-Request-ID", "").strip()
        request.state.request_id = (
            supplied if re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", supplied) else str(uuid.uuid4())
        )
        started = time.perf_counter()
        response_status = 500
        try:
            response = await call_next(request)
            response_status = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        finally:
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request.state.request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": response_status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    },
                    separators=(",", ":"),
                )
            )

    @application.exception_handler(RegistryError)
    async def handle_registry_error(request: Request, exc: RegistryError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return _error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=details,
        )

    @application.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message=str(exc.detail),
        )

    @application.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception(
            "database_error request_id=%s error_type=%s",
            _request_id(request),
            type(exc).__name__,
        )
        return _error_response(
            request,
            status_code=503,
            code="DATABASE_UNAVAILABLE",
            message="The registry database is temporarily unavailable",
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unexpected_error request_id=%s error_type=%s",
            _request_id(request),
            type(exc).__name__,
        )
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
        )

    application.include_router(health_router)
    application.include_router(health_router, prefix=app_settings.api_v1_prefix)
    application.include_router(advanced_router, prefix=app_settings.api_v1_prefix)
    application.include_router(ai_showcase_router, prefix=app_settings.api_v1_prefix)
    application.include_router(investigation_router, prefix=app_settings.api_v1_prefix)
    application.include_router(registry_router, prefix=app_settings.api_v1_prefix)
    application.include_router(federation_router, prefix=app_settings.api_v1_prefix)
    application.include_router(credentials_router, prefix=app_settings.api_v1_prefix)
    application.include_router(media_router, prefix=app_settings.api_v1_prefix)
    application.include_router(streams_router, prefix=app_settings.api_v1_prefix)
    application.include_router(visual_intelligence_router, prefix=app_settings.api_v1_prefix)
    application.include_router(watchlist_router, prefix=app_settings.api_v1_prefix)
    return application


app = create_app()
