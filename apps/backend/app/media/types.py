from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from threading import Event, RLock, Thread
from typing import Any


class MediaSessionState(StrEnum):
    starting = "starting"
    live = "live"
    degraded = "degraded"
    backoff = "backoff"
    stopped = "stopped"
    failed = "failed"
    unavailable = "unavailable"


ACTIVE_STATES = {
    MediaSessionState.starting,
    MediaSessionState.live,
    MediaSessionState.degraded,
    MediaSessionState.backoff,
}


@dataclass(frozen=True, slots=True)
class RuntimeCameraSummary:
    id: str
    camera_code: str
    camera_name: str
    department_name: str
    district: str
    city: str | None


@dataclass(frozen=True, slots=True)
class RuntimeProfileSummary:
    id: str
    name: str
    adapter_kind: str
    stream_role: str
    endpoint_display: str


@dataclass(slots=True)
class RuntimeMetrics:
    frame: int | None = None
    fps: float | None = None
    out_time_ms: int | None = None
    progress_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuntimeSessionSnapshot:
    id: str
    connection_id: str
    state: MediaSessionState
    camera: RuntimeCameraSummary
    profile: RuntimeProfileSummary
    decoder_backend: str
    playlist_url: str | None
    metrics: RuntimeMetrics
    restart_count: int
    started_at: datetime
    state_changed_at: datetime
    last_progress_at: datetime | None
    last_playlist_at: datetime | None
    stopped_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None


@dataclass(slots=True)
class RuntimeSession:
    id: str
    connection_id: str
    camera: RuntimeCameraSummary
    profile: RuntimeProfileSummary
    endpoint: str = field(repr=False)
    session_directory: str = field(repr=False)
    decoder_backend: str = "ffmpeg"
    state: MediaSessionState = MediaSessionState.starting
    metrics: RuntimeMetrics = field(default_factory=RuntimeMetrics)
    restart_count: int = 0
    started_at: datetime | None = None
    state_changed_at: datetime | None = None
    last_progress_at: datetime | None = None
    last_playlist_at: datetime | None = None
    stopped_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    process: Any = field(default=None, repr=False)
    stop_event: Event = field(default_factory=Event, repr=False)
    supervisor_thread: Thread | None = field(default=None, repr=False)
    lock: RLock = field(default_factory=RLock, repr=False)
    stderr_tail: list[str] = field(default_factory=list, repr=False)
    last_progress_monotonic: float | None = field(default=None, repr=False)
    last_playlist_monotonic: float | None = field(default=None, repr=False)
    credential_lease: Any = field(default=None, repr=False)
    generation: int = field(default=0, repr=False)
    playlist_signature: str | None = field(default=None, repr=False)
