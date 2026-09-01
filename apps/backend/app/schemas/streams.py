from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.registry import RegistrySchema


class StreamStartRequest(RegistrySchema):
    connection_id: UUID | None = None
    preferred_adapter: Literal["rtsp", "hls"] | None = None
    target_fps: float | None = Field(default=None, ge=0.1, le=60)
    decode_fps: float | None = Field(default=None, ge=0.5, le=60)
    transport: Literal["tcp", "udp"] | None = None
    max_frame_age_ms: int | None = Field(default=None, ge=50, le=10_000)


class StreamCameraRead(RegistrySchema):
    id: UUID
    camera_code: str
    camera_name: str
    department_id: UUID
    department_name: str
    district: str
    city: str | None
    latitude: float
    longitude: float
    vendor: str | None
    model: str | None
    camera_type: str
    ai_capabilities: list[str]


class StreamProfileRead(RegistrySchema):
    id: UUID
    name: str
    adapter_kind: str
    stream_role: str
    endpoint_display: str


class StreamMetricsRead(RegistrySchema):
    frames_received: int
    frames_dropped: int
    frames_sampled_out: int
    frames_dispatched: int
    stale_frames_dropped: int
    dropped_due_to_backpressure: int
    reconnect_count: int
    decoder_errors: int
    queue_depth: int
    source_fps: float | None
    decoded_fps: float
    processing_fps: float
    current_frame_age_ms: float | None
    average_frame_age_ms: float | None
    p95_frame_age_ms: float | None
    max_frame_age_ms: float | None
    last_frame_at: datetime | None
    last_dispatch_at: datetime | None
    clock_offset_ms: float | None
    resolution: str | None
    latency_estimate_ms: float | None
    bitrate_kbps: float | None
    latest_source_pts_seconds: float | None
    pts_timing_active: bool
    source_failover_count: int


class StreamSessionRead(RegistrySchema):
    id: UUID
    camera: StreamCameraRead
    profile: StreamProfileRead
    state: Literal[
        "created",
        "connecting",
        "connected",
        "streaming",
        "degraded",
        "reconnecting",
        "failed",
        "stopped",
    ]
    decoder_backend: str
    transport: str
    width: int
    height: int
    target_fps: float
    decode_fps: float
    buffer_capacity: int
    max_frame_age_ms: int
    metrics: StreamMetricsRead
    created_at: datetime
    state_changed_at: datetime
    connected_at: datetime | None
    stopped_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    preview_url: str | None


class StreamSessionList(RegistrySchema):
    items: list[StreamSessionRead]
    total: int


class StreamCapabilitiesRead(RegistrySchema):
    available: bool
    decoder_backend: str | None
    decoder_source: str | None
    configured_backend: str
    hardware_decode_active: bool
    hardware_decode_reason: str
    gpu_zero_copy_active: bool
    latest_frame_semantics: bool
    batch_dispatch: bool
    max_active_sessions: int
    supported_source_types: list[str]


class AnalyticsDetectionRead(RegistrySchema):
    kind: Literal["object", "plate"]
    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    plate_text: str | None
    ocr_confidence: float | None
    track_id: int | None = None


class CameraAnalyticsRead(RegistrySchema):
    camera_id: UUID
    stream_id: UUID
    frame_number: int
    observed_at: datetime
    status: str
    model: str
    device: str
    inference_ms: float
    detections: list[AnalyticsDetectionRead]
    routed_modules: list[str]
    error_message: str | None


class CameraAnalyticsList(RegistrySchema):
    items: list[CameraAnalyticsRead]
    total: int


class AnalyticsCapabilitiesRead(RegistrySchema):
    enabled: bool
    status: str
    consumer_attached: bool
    model: str | None
    device: str | None
    reason: str | None
    routes: list[str]


class StreamStateCountsRead(RegistrySchema):
    created: int
    connecting: int
    connected: int
    streaming: int
    degraded: int
    reconnecting: int
    failed: int
    stopped: int


class StreamAggregateMetricsRead(RegistrySchema):
    active_streams: int
    offline_streams: int
    degraded_streams: int
    reconnecting_streams: int
    average_decoded_fps: float
    average_processing_fps: float
    average_latency_ms: float
    total_frames_received: int
    total_frames_dropped: int
    total_reconnects: int
    scheduler_queue_depth: int
    ai_consumer_attached: bool
    worker_cpu_percent: float
    worker_memory_mb: float
    worker_processes: int
    gpu_decode_utilization_percent: float | None
    network_receive_mbps: float | None
    states: StreamStateCountsRead


def stream_session_read(snapshot: object) -> StreamSessionRead:
    return StreamSessionRead.model_validate(snapshot)
