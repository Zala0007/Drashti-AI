from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from threading import Event, RLock, Thread
from typing import Any

from app.media.credentials import CredentialLease


class ProcessingStreamState(StrEnum):
    created = "created"
    connecting = "connecting"
    connected = "connected"
    streaming = "streaming"
    degraded = "degraded"
    reconnecting = "reconnecting"
    failed = "failed"
    stopped = "stopped"


ACTIVE_PROCESSING_STATES = {
    ProcessingStreamState.connecting,
    ProcessingStreamState.connected,
    ProcessingStreamState.streaming,
    ProcessingStreamState.degraded,
    ProcessingStreamState.reconnecting,
}


@dataclass(frozen=True, slots=True)
class FramePacket:
    camera_id: str
    stream_id: str
    connection_id: str
    frame_number: int
    source_timestamp: datetime | None
    capture_timestamp: datetime
    receive_timestamp: datetime
    width: int
    height: int
    source_fps: float | None
    decoded_fps: float | None
    source_type: str
    health_state: ProcessingStreamState
    pixel_format: str
    payload: bytes = field(repr=False)
    ai_capabilities: tuple[str, ...] = ()
    source_pts_seconds: float | None = None

    def age_ms(self, now: datetime) -> float:
        return max(0.0, (now - self.capture_timestamp).total_seconds() * 1000)


@dataclass(frozen=True, slots=True)
class ProcessingCameraSummary:
    id: str
    camera_code: str
    camera_name: str
    department_id: str
    department_name: str
    district: str
    city: str | None
    latitude: float
    longitude: float
    vendor: str | None
    model: str | None
    camera_type: str
    ai_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcessingProfileSummary:
    id: str
    name: str
    adapter_kind: str
    stream_role: str
    endpoint_display: str


@dataclass(slots=True)
class ProcessingMetrics:
    frames_received: int = 0
    frames_dropped: int = 0
    frames_sampled_out: int = 0
    frames_dispatched: int = 0
    stale_frames_dropped: int = 0
    dropped_due_to_backpressure: int = 0
    reconnect_count: int = 0
    decoder_errors: int = 0
    queue_depth: int = 0
    source_fps: float | None = None
    decoded_fps: float = 0.0
    processing_fps: float = 0.0
    current_frame_age_ms: float | None = None
    average_frame_age_ms: float | None = None
    p95_frame_age_ms: float | None = None
    max_frame_age_ms: float | None = None
    last_frame_at: datetime | None = None
    last_dispatch_at: datetime | None = None
    clock_offset_ms: float | None = None
    resolution: str | None = None
    latency_estimate_ms: float | None = None
    bitrate_kbps: float | None = None
    latest_source_pts_seconds: float | None = None
    pts_timing_active: bool = False
    source_failover_count: int = 0


@dataclass(slots=True)
class ProcessingSourceCandidate:
    profile: ProcessingProfileSummary
    endpoint: str = field(repr=False)
    source_kind: str
    credential_lease: CredentialLease | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ProcessingSessionSnapshot:
    id: str
    camera: ProcessingCameraSummary
    profile: ProcessingProfileSummary
    state: ProcessingStreamState
    decoder_backend: str
    transport: str
    width: int
    height: int
    target_fps: float
    decode_fps: float
    buffer_capacity: int
    max_frame_age_ms: int
    metrics: ProcessingMetrics
    created_at: datetime
    state_changed_at: datetime
    connected_at: datetime | None
    stopped_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    preview_url: str | None


@dataclass(slots=True)
class ProcessingSession:
    id: str
    camera: ProcessingCameraSummary
    profile: ProcessingProfileSummary
    endpoint: str = field(repr=False)
    source_kind: str = "rtsp"
    decoder_backend: str = "ffmpeg"
    transport: str = "tcp"
    width: int = 640
    height: int = 360
    target_fps: float = 10.0
    decode_fps: float = 12.0
    buffer_capacity: int = 2
    max_frame_age_ms: int = 750
    credential_lease: CredentialLease | None = field(default=None, repr=False)
    fallback_sources: list[ProcessingSourceCandidate] = field(default_factory=list, repr=False)
    state: ProcessingStreamState = ProcessingStreamState.created
    metrics: ProcessingMetrics = field(default_factory=ProcessingMetrics)
    created_at: datetime | None = None
    state_changed_at: datetime | None = None
    connected_at: datetime | None = None
    stopped_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    reader_thread: Thread | None = field(default=None, repr=False)
    stop_event: Event = field(default_factory=Event, repr=False)
    lock: RLock = field(default_factory=RLock, repr=False)
    decoder: Any = field(default=None, repr=False)
    decoder_started_monotonic: float | None = field(default=None, repr=False)
    buffer: Any = field(default=None, repr=False)
    last_frame_monotonic: float | None = field(default=None, repr=False)
    last_frame_digest: bytes | None = field(default=None, repr=False)
    identical_since_monotonic: float | None = field(default=None, repr=False)
    age_samples_ms: list[float] = field(default_factory=list, repr=False)
    fps_window_started: float | None = field(default=None, repr=False)
    fps_window_frames: int = field(default=0, repr=False)
    dispatch_window_started: float | None = field(default=None, repr=False)
    dispatch_window_frames: int = field(default=0, repr=False)
    last_source_pts_seconds: float | None = field(default=None, repr=False)
    preview_frame_number: int = field(default=-1, repr=False)
    preview_jpeg: bytes | None = field(default=None, repr=False)
