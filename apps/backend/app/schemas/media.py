from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.schemas.registry import RegistrySchema


class RuntimeSupervisionRead(RegistrySchema):
    watchdog_seconds: float
    max_backoff_seconds: float
    max_restarts: int


class RuntimeCapabilitiesRead(RegistrySchema):
    available: bool
    binary_source: Literal["configured", "path", "imageio_ffmpeg", "unavailable"]
    supported_adapter_kinds: list[str]
    unsupported_adapter_kinds: list[str]
    output_protocol: Literal["hls"]
    segment_duration_seconds: int
    playlist_window: int
    decoder_backend: str
    hardware_decode_active: bool
    hardware_decode_reason: str
    video_processing_mode: Literal[
        "software_h264_transcode", "nvdec_decode_software_h264_transcode"
    ]
    max_active_sessions: int
    credential_resolver_mode: str
    network_handoff: dict[str, str]
    active_sessions: int
    supervision: RuntimeSupervisionRead
    boundary: Literal["process_local_poc"]


class RuntimeCameraRead(RegistrySchema):
    id: UUID
    camera_code: str
    camera_name: str
    department_name: str
    district: str
    city: str | None


class RuntimeProfileRead(RegistrySchema):
    id: UUID
    name: str
    adapter_kind: str
    stream_role: str
    endpoint_display: str


class RuntimeMetricsRead(RegistrySchema):
    frame: int | None
    fps: float | None
    out_time_ms: int | None
    progress_at: datetime | None


class RuntimeSessionRead(RegistrySchema):
    id: UUID
    connection_id: UUID
    state: Literal["starting", "live", "degraded", "backoff", "stopped", "failed", "unavailable"]
    camera: RuntimeCameraRead
    profile: RuntimeProfileRead
    decoder_backend: str
    playlist_url: str | None
    metrics: RuntimeMetricsRead
    restart_count: int
    started_at: datetime
    state_changed_at: datetime
    last_progress_at: datetime | None
    last_playlist_at: datetime | None
    stopped_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None


class RuntimeSessionList(RegistrySchema):
    items: list[RuntimeSessionRead]
    total: int


def runtime_session_read(snapshot: Any) -> RuntimeSessionRead:
    return RuntimeSessionRead.model_validate(snapshot)
