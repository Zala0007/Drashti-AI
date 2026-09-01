from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_origins(value: str | None) -> tuple[str, ...]:
    if not value:
        return ("http://localhost:3000", "http://localhost:5173")
    value = value.strip()
    if value.startswith("["):
        parsed = json.loads(value)
        return tuple(str(item) for item in parsed)
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _as_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _as_probe_timeout(value: str | None) -> float:
    try:
        timeout = float(value or "5")
    except ValueError as exc:
        raise ValueError("FEDERATION_PROBE_TIMEOUT_SECONDS must be numeric") from exc
    if not math.isfinite(timeout) or not 0.25 <= timeout <= 30:
        raise ValueError("FEDERATION_PROBE_TIMEOUT_SECONDS must be between 0.25 and 30")
    return timeout


def _as_bounded_float(
    value: str | None, *, default: float, minimum: float, maximum: float, name: str
) -> float:
    try:
        parsed = float(value) if value is not None else default
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _as_bounded_int(
    value: str | None, *, default: int, minimum: int, maximum: int, name: str
) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Drishti AI Camera Registry"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./drishti_registry.db"
    db_echo: bool = False
    log_level: str = "INFO"
    auto_create_schema: bool = True
    cors_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://localhost:5173",
    )
    federation_encryption_key: str | None = None
    federation_encryption_key_id: str = "local-development-key"
    federation_auto_development_key: bool = True
    federation_development_key_file: str = "./.runtime/secrets/federation.key"
    federation_allowed_cidrs: tuple[str, ...] = ()
    federation_probe_timeout_seconds: float = 5.0
    federation_media_root: str = "./media"
    ffmpeg_binary: str | None = None
    federation_runtime_root: str = "./.runtime/media"
    federation_runtime_segment_seconds: int = 2
    federation_runtime_playlist_window: int = 6
    federation_runtime_watchdog_seconds: float = 12.0
    federation_runtime_max_backoff_seconds: float = 30.0
    federation_runtime_max_restarts: int = 8
    federation_runtime_stop_timeout_seconds: float = 5.0
    federation_runtime_max_active_sessions: int = 8
    government_feed_catalogue_url: str | None = None
    government_feed_rtsp_hosts: tuple[str, ...] = ()
    government_feed_catalogue_timeout_seconds: float = 10.0
    government_feed_catalogue_max_items: int = 100
    government_feed_fallback_latitude: float = 22.2587
    government_feed_fallback_longitude: float = 71.1924
    ai_showcase_database: str = "./AI-Features/crops.db"
    live_analytics_enabled: bool = True
    live_analytics_general_model: str = "./AI-Features/models/yolo26n.pt"
    live_analytics_plate_model: str = "./AI-Features/models/license_plate_detector.pt"
    live_analytics_confidence: float = 0.4
    live_analytics_plate_confidence: float = 0.35
    live_analytics_evidence_interval_seconds: float = 2.0
    live_analytics_ocr_enabled: bool = True
    live_analytics_ocr_timeout_seconds: float = 8.0
    live_analytics_ocr_cooldown_seconds: float = 4.0
    live_analytics_ocr_batch_size: int = 8
    live_analytics_google_accept_confidence: float = 0.86
    live_analytics_groq_ocr_enabled: bool = True
    live_analytics_groq_accept_confidence: float = 0.82
    live_analytics_groq_ocr_request_interval_seconds: float = 0.5
    groq_api_key: str | None = None
    groq_vision_model: str = "qwen/qwen3.6-27b"
    groq_request_timeout: float = 45.0
    groq_max_retries: int = 2
    visual_intelligence_enabled: bool = True
    visual_intelligence_auto_analyze: bool = True
    visual_intelligence_queue_size: int = 64
    visual_intelligence_request_interval_seconds: float = 2.0
    stream_engine_decoder_backend: str = "auto"
    stream_engine_rtsp_transport: str = "tcp"
    stream_engine_output_width: int = 640
    stream_engine_output_height: int = 360
    stream_engine_decode_fps: float = 12.0
    stream_engine_target_fps: float = 10.0
    stream_engine_buffer_size: int = 2
    stream_engine_max_frame_age_ms: int = 750
    stream_engine_batch_size: int = 8
    stream_engine_batch_timeout_ms: int = 40
    stream_engine_health_timeout_seconds: float = 5.0
    stream_engine_http_health_timeout_seconds: float = 30.0
    stream_engine_startup_timeout_seconds: float = 15.0
    stream_engine_http_startup_timeout_seconds: float = 30.0
    stream_engine_freeze_threshold_seconds: float = 10.0
    stream_engine_max_backoff_seconds: float = 30.0
    stream_engine_stop_timeout_seconds: float = 5.0
    stream_engine_max_active_sessions: int = 32
    stream_engine_preview_fps: float = 6.0

    @classmethod
    def from_env(cls) -> Settings:
        database_url = os.getenv("DATABASE_URL", "sqlite:///./drishti_registry.db")
        default_auto_create = database_url.startswith("sqlite")
        return cls(
            app_name=os.getenv("APP_NAME", "Drishti AI Camera Registry"),
            app_env=os.getenv("APP_ENV", "development"),
            api_v1_prefix=os.getenv("API_V1_PREFIX", "/api/v1"),
            database_url=database_url,
            db_echo=_as_bool(os.getenv("DB_ECHO"), False),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            auto_create_schema=_as_bool(os.getenv("AUTO_CREATE_SCHEMA"), default_auto_create),
            cors_origins=_as_origins(os.getenv("CORS_ORIGINS")),
            federation_encryption_key=(os.getenv("FEDERATION_ENCRYPTION_KEY", "").strip() or None),
            federation_encryption_key_id=(
                os.getenv("FEDERATION_ENCRYPTION_KEY_ID", "local-development-key").strip()
                or "local-development-key"
            ),
            federation_auto_development_key=_as_bool(
                os.getenv("FEDERATION_AUTO_DEVELOPMENT_KEY"), True
            ),
            federation_development_key_file=(
                os.getenv(
                    "FEDERATION_DEVELOPMENT_KEY_FILE",
                    "./.runtime/secrets/federation.key",
                ).strip()
                or "./.runtime/secrets/federation.key"
            ),
            federation_allowed_cidrs=_as_csv(os.getenv("FEDERATION_ALLOWED_CIDRS")),
            federation_probe_timeout_seconds=_as_probe_timeout(
                os.getenv("FEDERATION_PROBE_TIMEOUT_SECONDS")
            ),
            federation_media_root=os.getenv("FEDERATION_MEDIA_ROOT", "./media").strip()
            or "./media",
            ffmpeg_binary=os.getenv("FFMPEG_BINARY", "").strip() or None,
            federation_runtime_root=os.getenv("FEDERATION_RUNTIME_ROOT", "./.runtime/media").strip()
            or "./.runtime/media",
            federation_runtime_segment_seconds=_as_bounded_int(
                os.getenv("FEDERATION_RUNTIME_SEGMENT_SECONDS"),
                default=2,
                minimum=1,
                maximum=10,
                name="FEDERATION_RUNTIME_SEGMENT_SECONDS",
            ),
            federation_runtime_playlist_window=_as_bounded_int(
                os.getenv("FEDERATION_RUNTIME_PLAYLIST_WINDOW"),
                default=6,
                minimum=3,
                maximum=30,
                name="FEDERATION_RUNTIME_PLAYLIST_WINDOW",
            ),
            federation_runtime_watchdog_seconds=_as_bounded_float(
                os.getenv("FEDERATION_RUNTIME_WATCHDOG_SECONDS"),
                default=12.0,
                minimum=3.0,
                maximum=120.0,
                name="FEDERATION_RUNTIME_WATCHDOG_SECONDS",
            ),
            federation_runtime_max_backoff_seconds=_as_bounded_float(
                os.getenv("FEDERATION_RUNTIME_MAX_BACKOFF_SECONDS"),
                default=30.0,
                minimum=1.0,
                maximum=300.0,
                name="FEDERATION_RUNTIME_MAX_BACKOFF_SECONDS",
            ),
            federation_runtime_max_restarts=_as_bounded_int(
                os.getenv("FEDERATION_RUNTIME_MAX_RESTARTS"),
                default=8,
                minimum=0,
                maximum=100,
                name="FEDERATION_RUNTIME_MAX_RESTARTS",
            ),
            federation_runtime_stop_timeout_seconds=_as_bounded_float(
                os.getenv("FEDERATION_RUNTIME_STOP_TIMEOUT_SECONDS"),
                default=5.0,
                minimum=0.5,
                maximum=30.0,
                name="FEDERATION_RUNTIME_STOP_TIMEOUT_SECONDS",
            ),
            federation_runtime_max_active_sessions=_as_bounded_int(
                os.getenv("FEDERATION_RUNTIME_MAX_ACTIVE_SESSIONS"),
                default=8,
                minimum=1,
                maximum=256,
                name="FEDERATION_RUNTIME_MAX_ACTIVE_SESSIONS",
            ),
            government_feed_catalogue_url=(
                os.getenv("GOVERNMENT_FEED_CATALOGUE_URL", "").strip() or None
            ),
            government_feed_rtsp_hosts=_as_csv(os.getenv("GOVERNMENT_FEED_RTSP_HOSTS")),
            government_feed_catalogue_timeout_seconds=_as_bounded_float(
                os.getenv("GOVERNMENT_FEED_CATALOGUE_TIMEOUT_SECONDS"),
                default=10.0,
                minimum=1.0,
                maximum=30.0,
                name="GOVERNMENT_FEED_CATALOGUE_TIMEOUT_SECONDS",
            ),
            government_feed_catalogue_max_items=_as_bounded_int(
                os.getenv("GOVERNMENT_FEED_CATALOGUE_MAX_ITEMS"),
                default=100,
                minimum=1,
                maximum=500,
                name="GOVERNMENT_FEED_CATALOGUE_MAX_ITEMS",
            ),
            government_feed_fallback_latitude=_as_bounded_float(
                os.getenv("GOVERNMENT_FEED_FALLBACK_LATITUDE"),
                default=22.2587,
                minimum=-90,
                maximum=90,
                name="GOVERNMENT_FEED_FALLBACK_LATITUDE",
            ),
            government_feed_fallback_longitude=_as_bounded_float(
                os.getenv("GOVERNMENT_FEED_FALLBACK_LONGITUDE"),
                default=71.1924,
                minimum=-180,
                maximum=180,
                name="GOVERNMENT_FEED_FALLBACK_LONGITUDE",
            ),
            ai_showcase_database=(
                os.getenv("AI_SHOWCASE_DATABASE", "./AI-Features/crops.db").strip()
                or "./AI-Features/crops.db"
            ),
            live_analytics_enabled=_as_bool(os.getenv("LIVE_ANALYTICS_ENABLED"), True),
            live_analytics_general_model=(
                os.getenv("LIVE_ANALYTICS_GENERAL_MODEL", "./AI-Features/models/yolo26n.pt").strip()
                or "./AI-Features/models/yolo26n.pt"
            ),
            live_analytics_plate_model=(
                os.getenv(
                    "LIVE_ANALYTICS_PLATE_MODEL",
                    "./AI-Features/models/license_plate_detector.pt",
                ).strip()
                or "./AI-Features/models/license_plate_detector.pt"
            ),
            live_analytics_confidence=_as_bounded_float(
                os.getenv("LIVE_ANALYTICS_CONFIDENCE"),
                default=0.4,
                minimum=0.05,
                maximum=1.0,
                name="LIVE_ANALYTICS_CONFIDENCE",
            ),
            live_analytics_plate_confidence=_as_bounded_float(
                os.getenv("LIVE_ANALYTICS_PLATE_CONFIDENCE"),
                default=0.35,
                minimum=0.05,
                maximum=1.0,
                name="LIVE_ANALYTICS_PLATE_CONFIDENCE",
            ),
            live_analytics_evidence_interval_seconds=_as_bounded_float(
                os.getenv("LIVE_ANALYTICS_EVIDENCE_INTERVAL_SECONDS"),
                default=2.0,
                minimum=0.1,
                maximum=300.0,
                name="LIVE_ANALYTICS_EVIDENCE_INTERVAL_SECONDS",
            ),
            live_analytics_ocr_enabled=_as_bool(os.getenv("LIVE_ANALYTICS_OCR_ENABLED"), True),
            live_analytics_ocr_timeout_seconds=_as_bounded_float(
                os.getenv("LIVE_ANALYTICS_OCR_TIMEOUT_SECONDS"),
                default=8.0,
                minimum=1.0,
                maximum=60.0,
                name="LIVE_ANALYTICS_OCR_TIMEOUT_SECONDS",
            ),
            live_analytics_ocr_cooldown_seconds=_as_bounded_float(
                os.getenv("LIVE_ANALYTICS_OCR_COOLDOWN_SECONDS"),
                default=4.0,
                minimum=0.5,
                maximum=300.0,
                name="LIVE_ANALYTICS_OCR_COOLDOWN_SECONDS",
            ),
            live_analytics_ocr_batch_size=_as_bounded_int(
                os.getenv("LIVE_ANALYTICS_OCR_BATCH_SIZE"),
                default=8,
                minimum=1,
                maximum=16,
                name="LIVE_ANALYTICS_OCR_BATCH_SIZE",
            ),
            live_analytics_google_accept_confidence=_as_bounded_float(
                os.getenv("LIVE_ANALYTICS_GOOGLE_ACCEPT_CONFIDENCE"),
                default=0.86,
                minimum=0.0,
                maximum=1.0,
                name="LIVE_ANALYTICS_GOOGLE_ACCEPT_CONFIDENCE",
            ),
            live_analytics_groq_ocr_enabled=_as_bool(
                os.getenv("LIVE_ANALYTICS_GROQ_OCR_ENABLED"), True
            ),
            live_analytics_groq_accept_confidence=_as_bounded_float(
                os.getenv("LIVE_ANALYTICS_GROQ_ACCEPT_CONFIDENCE"),
                default=0.82,
                minimum=0.0,
                maximum=1.0,
                name="LIVE_ANALYTICS_GROQ_ACCEPT_CONFIDENCE",
            ),
            live_analytics_groq_ocr_request_interval_seconds=_as_bounded_float(
                os.getenv("LIVE_ANALYTICS_GROQ_OCR_REQUEST_INTERVAL_SECONDS"),
                default=0.5,
                minimum=0.0,
                maximum=60.0,
                name="LIVE_ANALYTICS_GROQ_OCR_REQUEST_INTERVAL_SECONDS",
            ),
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip() or None,
            groq_vision_model=(
                os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b").strip() or "qwen/qwen3.6-27b"
            ),
            groq_request_timeout=_as_bounded_float(
                os.getenv("GROQ_REQUEST_TIMEOUT"),
                default=45.0,
                minimum=5.0,
                maximum=180.0,
                name="GROQ_REQUEST_TIMEOUT",
            ),
            groq_max_retries=_as_bounded_int(
                os.getenv("GROQ_MAX_RETRIES"),
                default=2,
                minimum=0,
                maximum=5,
                name="GROQ_MAX_RETRIES",
            ),
            visual_intelligence_enabled=_as_bool(os.getenv("VISUAL_INTELLIGENCE_ENABLED"), True),
            visual_intelligence_auto_analyze=_as_bool(
                os.getenv("VISUAL_INTELLIGENCE_AUTO_ANALYZE"), True
            ),
            visual_intelligence_queue_size=_as_bounded_int(
                os.getenv("VISUAL_INTELLIGENCE_QUEUE_SIZE"),
                default=64,
                minimum=1,
                maximum=500,
                name="VISUAL_INTELLIGENCE_QUEUE_SIZE",
            ),
            visual_intelligence_request_interval_seconds=_as_bounded_float(
                os.getenv("VISUAL_INTELLIGENCE_REQUEST_INTERVAL_SECONDS"),
                default=2.0,
                minimum=0.0,
                maximum=60.0,
                name="VISUAL_INTELLIGENCE_REQUEST_INTERVAL_SECONDS",
            ),
            stream_engine_decoder_backend=(
                os.getenv("STREAM_ENGINE_DECODER_BACKEND", "auto").strip().lower() or "auto"
            ),
            stream_engine_rtsp_transport=(
                os.getenv("STREAM_ENGINE_RTSP_TRANSPORT", "tcp").strip().lower() or "tcp"
            ),
            stream_engine_output_width=_as_bounded_int(
                os.getenv("STREAM_ENGINE_OUTPUT_WIDTH"),
                default=640,
                minimum=160,
                maximum=3840,
                name="STREAM_ENGINE_OUTPUT_WIDTH",
            ),
            stream_engine_output_height=_as_bounded_int(
                os.getenv("STREAM_ENGINE_OUTPUT_HEIGHT"),
                default=360,
                minimum=90,
                maximum=2160,
                name="STREAM_ENGINE_OUTPUT_HEIGHT",
            ),
            stream_engine_decode_fps=_as_bounded_float(
                os.getenv("STREAM_ENGINE_DECODE_FPS"),
                default=12.0,
                minimum=0.5,
                maximum=60.0,
                name="STREAM_ENGINE_DECODE_FPS",
            ),
            stream_engine_target_fps=_as_bounded_float(
                os.getenv("STREAM_ENGINE_TARGET_FPS"),
                default=10.0,
                minimum=0.1,
                maximum=60.0,
                name="STREAM_ENGINE_TARGET_FPS",
            ),
            stream_engine_buffer_size=_as_bounded_int(
                os.getenv("STREAM_ENGINE_BUFFER_SIZE"),
                default=2,
                minimum=1,
                maximum=3,
                name="STREAM_ENGINE_BUFFER_SIZE",
            ),
            stream_engine_max_frame_age_ms=_as_bounded_int(
                os.getenv("STREAM_ENGINE_MAX_FRAME_AGE_MS"),
                default=750,
                minimum=50,
                maximum=10000,
                name="STREAM_ENGINE_MAX_FRAME_AGE_MS",
            ),
            stream_engine_batch_size=_as_bounded_int(
                os.getenv("STREAM_ENGINE_BATCH_SIZE"),
                default=8,
                minimum=1,
                maximum=64,
                name="STREAM_ENGINE_BATCH_SIZE",
            ),
            stream_engine_batch_timeout_ms=_as_bounded_int(
                os.getenv("STREAM_ENGINE_BATCH_TIMEOUT_MS"),
                default=40,
                minimum=1,
                maximum=1000,
                name="STREAM_ENGINE_BATCH_TIMEOUT_MS",
            ),
            stream_engine_health_timeout_seconds=_as_bounded_float(
                os.getenv("STREAM_ENGINE_HEALTH_TIMEOUT_SECONDS"),
                default=5.0,
                minimum=1.0,
                maximum=120.0,
                name="STREAM_ENGINE_HEALTH_TIMEOUT_SECONDS",
            ),
            stream_engine_http_health_timeout_seconds=_as_bounded_float(
                os.getenv("STREAM_ENGINE_HTTP_HEALTH_TIMEOUT_SECONDS"),
                default=30.0,
                minimum=5.0,
                maximum=180.0,
                name="STREAM_ENGINE_HTTP_HEALTH_TIMEOUT_SECONDS",
            ),
            stream_engine_startup_timeout_seconds=_as_bounded_float(
                os.getenv("STREAM_ENGINE_STARTUP_TIMEOUT_SECONDS"),
                default=15.0,
                minimum=5.0,
                maximum=180.0,
                name="STREAM_ENGINE_STARTUP_TIMEOUT_SECONDS",
            ),
            stream_engine_http_startup_timeout_seconds=_as_bounded_float(
                os.getenv("STREAM_ENGINE_HTTP_STARTUP_TIMEOUT_SECONDS"),
                default=30.0,
                minimum=5.0,
                maximum=180.0,
                name="STREAM_ENGINE_HTTP_STARTUP_TIMEOUT_SECONDS",
            ),
            stream_engine_freeze_threshold_seconds=_as_bounded_float(
                os.getenv("STREAM_ENGINE_FREEZE_THRESHOLD_SECONDS"),
                default=10.0,
                minimum=2.0,
                maximum=300.0,
                name="STREAM_ENGINE_FREEZE_THRESHOLD_SECONDS",
            ),
            stream_engine_max_backoff_seconds=_as_bounded_float(
                os.getenv("STREAM_ENGINE_MAX_BACKOFF_SECONDS"),
                default=30.0,
                minimum=1.0,
                maximum=300.0,
                name="STREAM_ENGINE_MAX_BACKOFF_SECONDS",
            ),
            stream_engine_stop_timeout_seconds=_as_bounded_float(
                os.getenv("STREAM_ENGINE_STOP_TIMEOUT_SECONDS"),
                default=5.0,
                minimum=0.5,
                maximum=30.0,
                name="STREAM_ENGINE_STOP_TIMEOUT_SECONDS",
            ),
            stream_engine_max_active_sessions=_as_bounded_int(
                os.getenv("STREAM_ENGINE_MAX_ACTIVE_SESSIONS"),
                default=32,
                minimum=1,
                maximum=256,
                name="STREAM_ENGINE_MAX_ACTIVE_SESSIONS",
            ),
            stream_engine_preview_fps=_as_bounded_float(
                os.getenv("STREAM_ENGINE_PREVIEW_FPS"),
                default=6.0,
                minimum=0.2,
                maximum=10.0,
                name="STREAM_ENGINE_PREVIEW_FPS",
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
