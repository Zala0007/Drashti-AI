from __future__ import annotations

import hashlib
import io
import json
import logging
import random
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

import psutil
from PIL import Image

from app.errors import ConflictError, NotFoundError, RegistryError
from app.media.binary import BinaryResolution, resolve_ffmpeg_binary
from app.media.credentials import CredentialLease
from app.media.hardware import HardwareDecodeCapability, detect_nvdec
from app.stream_engine.buffer import LatestFrameBuffer
from app.stream_engine.decoder import DecodedFrame, DecoderConfig, FFmpegRawDecoder
from app.stream_engine.scheduler import FrameBatch, FrameScheduler
from app.stream_engine.types import (
    ACTIVE_PROCESSING_STATES,
    FramePacket,
    ProcessingCameraSummary,
    ProcessingProfileSummary,
    ProcessingSession,
    ProcessingSessionSnapshot,
    ProcessingSourceCandidate,
    ProcessingStreamState,
)

logger = logging.getLogger("drishti.stream_engine")


class FrameDecoder(Protocol):
    backend: str

    def open(self, endpoint: str) -> None: ...

    def read_frame(self) -> bytes | DecodedFrame: ...

    def close(self) -> None: ...

    @property
    def safe_error(self) -> tuple[str, str]: ...


@dataclass(frozen=True, slots=True)
class StreamEngineConfig:
    configured_binary: str | None = None
    decoder_backend: str = "auto"
    rtsp_transport: str = "tcp"
    width: int = 640
    height: int = 360
    decode_fps: float = 12.0
    target_fps: float = 10.0
    buffer_size: int = 2
    max_frame_age_ms: int = 750
    batch_size: int = 8
    batch_timeout_ms: int = 40
    health_timeout_seconds: float = 5.0
    http_health_timeout_seconds: float = 30.0
    startup_timeout_seconds: float = 15.0
    http_startup_timeout_seconds: float = 30.0
    freeze_threshold_seconds: float = 10.0
    max_backoff_seconds: float = 30.0
    stop_timeout_seconds: float = 5.0
    max_active_sessions: int = 32
    preview_fps: float = 6.0

    def __post_init__(self) -> None:
        if self.decoder_backend not in {"auto", "nvdec", "ffmpeg"}:
            raise ValueError("STREAM_ENGINE_DECODER_BACKEND must be auto, nvdec, or ffmpeg")
        if self.rtsp_transport not in {"tcp", "udp"}:
            raise ValueError("STREAM_ENGINE_RTSP_TRANSPORT must be tcp or udp")
        if not 1 <= self.buffer_size <= 3:
            raise ValueError("STREAM_ENGINE_BUFFER_SIZE must be between 1 and 3")
        if min(self.width, self.height, self.batch_size, self.max_active_sessions) < 1:
            raise ValueError("Stream engine dimensions and capacities must be positive")
        if min(self.decode_fps, self.target_fps, self.preview_fps) <= 0:
            raise ValueError("Stream engine FPS settings must be positive")
        if (
            min(
                self.max_frame_age_ms,
                self.batch_timeout_ms,
                self.health_timeout_seconds,
                self.http_health_timeout_seconds,
                self.startup_timeout_seconds,
                self.http_startup_timeout_seconds,
                self.freeze_threshold_seconds,
                self.max_backoff_seconds,
                self.stop_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("Stream engine deadlines and timeouts must be positive")


DecoderFactory = Callable[[ProcessingSession, DecoderConfig, BinaryResolution], FrameDecoder]
HardwareDetector = Callable[[BinaryResolution | None], HardwareDecodeCapability]


class StreamEngine:
    """One processing unit for independently supervised camera sessions."""

    def __init__(
        self,
        config: StreamEngineConfig,
        *,
        decoder_factory: DecoderFactory | None = None,
        binary_resolver: Callable[[str | None], BinaryResolution | None] = resolve_ffmpeg_binary,
        hardware_detector: HardwareDetector = detect_nvdec,
        monotonic: Callable[[], float] = time.monotonic,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.config = config
        self.decoder_factory = decoder_factory or self._default_decoder
        self.binary_resolver = binary_resolver
        self.hardware_detector = hardware_detector
        self.monotonic = monotonic
        self.jitter = jitter
        self._binary: BinaryResolution | None = None
        self._hardware_decode = HardwareDecodeCapability(False, "ffmpeg", "not_probed")
        self._nvdec_fallback_sessions: set[str] = set()
        self._sessions: dict[str, ProcessingSession] = {}
        self._active_by_camera: dict[str, str] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._resource_process = psutil.Process()
        self._resource_lock = threading.Lock()
        self._resource_tick = self.monotonic()
        initial_times = self._resource_process.cpu_times()
        self._resource_cpu_seconds = initial_times.user + initial_times.system
        self.scheduler = FrameScheduler(
            self._active_sessions,
            batch_size=config.batch_size,
            batch_timeout_ms=config.batch_timeout_ms,
        )

    def _default_decoder(
        self,
        session: ProcessingSession,
        config: DecoderConfig,
        binary: BinaryResolution,
    ) -> FrameDecoder:
        use_nvdec = (
            self._hardware_decode.available and session.id not in self._nvdec_fallback_sessions
        )
        return FFmpegRawDecoder(
            binary=binary,
            config=config,
            source_kind=session.source_kind,
            hardware_decode=use_nvdec,
        )

    def startup(self) -> None:
        self._binary = self.binary_resolver(self.config.configured_binary)
        if self.config.decoder_backend == "ffmpeg":
            self._hardware_decode = HardwareDecodeCapability(
                False, "ffmpeg", "disabled_by_configuration"
            )
        else:
            self._hardware_decode = self.hardware_detector(self._binary)
        self._stop.clear()
        self.scheduler.startup()
        if not self._monitor_thread or not self._monitor_thread.is_alive():
            self._monitor_thread = threading.Thread(
                target=self._monitor,
                name="drishti-stream-health-monitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            camera_ids = list(self._active_by_camera)
        stop_threads: list[threading.Thread] = []
        for camera_id in camera_ids:
            thread = threading.Thread(
                target=self._stop_if_active,
                args=(camera_id,),
                name=f"drishti-stop-{camera_id[:12]}",
                daemon=True,
            )
            stop_threads.append(thread)
            thread.start()
        for thread in stop_threads:
            thread.join(timeout=self.config.stop_timeout_seconds * 3 + 2)
            if thread.is_alive():
                logger.error(
                    json.dumps(
                        {
                            "event": "stream_shutdown_timeout",
                            "component": "stream_session_manager",
                            "thread": thread.name,
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                        separators=(",", ":"),
                    )
                )
        self.scheduler.shutdown(self.config.stop_timeout_seconds)
        if self._monitor_thread and self._monitor_thread is not threading.current_thread():
            self._monitor_thread.join(timeout=self.config.stop_timeout_seconds)
        self._monitor_thread = None

    def _stop_if_active(self, camera_id: str) -> None:
        try:
            self.stop(camera_id)
        except NotFoundError:
            return

    def capabilities(self) -> dict[str, object]:
        binary = self._binary or self.binary_resolver(self.config.configured_binary)
        return {
            "available": binary is not None,
            "decoder_backend": self._hardware_decode.backend if binary else None,
            "decoder_source": binary.source if binary else None,
            "configured_backend": self.config.decoder_backend,
            "hardware_decode_active": self._hardware_decode.available,
            "hardware_decode_reason": self._hardware_decode.reason,
            "gpu_zero_copy_active": False,
            "latest_frame_semantics": True,
            "batch_dispatch": True,
            "max_active_sessions": self.config.max_active_sessions,
            "supported_source_types": ["rtsp", "onvif", "hls", "mjpeg", "recorded_file"],
        }

    def _active_sessions(self) -> list[ProcessingSession]:
        with self._lock:
            ids = list(self._active_by_camera.values())
            return [self._sessions[item] for item in ids if item in self._sessions]

    def _set_state(
        self,
        session: ProcessingSession,
        state: ProcessingStreamState,
        *,
        error: tuple[str, str] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with session.lock:
            if session.state == state and error is None:
                return
            previous = session.state
            session.state = state
            session.state_changed_at = now
            if state == ProcessingStreamState.connected and session.connected_at is None:
                session.connected_at = now
            if state == ProcessingStreamState.stopped:
                session.stopped_at = now
            if error:
                session.last_error_code, session.last_error_message = error
            elif state in {
                ProcessingStreamState.connected,
                ProcessingStreamState.streaming,
            }:
                session.last_error_code = None
                session.last_error_message = None
        logger.info(
            json.dumps(
                {
                    "event": "stream_state_changed",
                    "component": "stream_session_manager",
                    "camera_id": session.camera.id,
                    "stream_id": session.id,
                    "previous_state": previous,
                    "state": state,
                    "error_code": error[0] if error else None,
                    "timestamp": now.isoformat(),
                },
                separators=(",", ":"),
            )
        )

    def start(
        self,
        *,
        camera: ProcessingCameraSummary,
        profile: ProcessingProfileSummary,
        endpoint: str,
        source_kind: str,
        credential_lease: CredentialLease | None = None,
        target_fps: float | None = None,
        decode_fps: float | None = None,
        transport: str | None = None,
        max_frame_age_ms: int | None = None,
        fallback_sources: list[ProcessingSourceCandidate] | None = None,
    ) -> ProcessingSessionSnapshot:
        selected_target_fps = target_fps or self.config.target_fps
        selected_decode_fps = decode_fps or self.config.decode_fps
        selected_transport = transport or self.config.rtsp_transport
        selected_age = max_frame_age_ms or self.config.max_frame_age_ms
        if selected_transport not in {"tcp", "udp"}:
            raise RegistryError(
                code="STREAM_TRANSPORT_INVALID",
                message="RTSP transport must be tcp or udp",
                status_code=422,
            )
        if not 0.1 <= selected_target_fps <= 60 or not 0.5 <= selected_decode_fps <= 60:
            raise RegistryError(
                code="STREAM_FPS_INVALID",
                message="Stream FPS overrides are outside the supported range",
                status_code=422,
            )
        with self._lock:
            self._prune_history_locked()
            existing = self._active_by_camera.get(camera.id)
            if existing:
                raise ConflictError(
                    "STREAM_SESSION_ACTIVE",
                    "This camera already has an active processing session",
                    {"stream_id": existing},
                )
            if len(self._active_by_camera) >= self.config.max_active_sessions:
                raise RegistryError(
                    code="STREAM_CAPACITY_EXCEEDED",
                    message="This processing node has reached its configured stream capacity",
                    status_code=429,
                )
            now = datetime.now(UTC)
            stream_id = str(uuid.uuid4())
            session = ProcessingSession(
                id=stream_id,
                camera=camera,
                profile=profile,
                endpoint=endpoint,
                source_kind=source_kind,
                transport=selected_transport,
                width=self.config.width,
                height=self.config.height,
                target_fps=selected_target_fps,
                decode_fps=selected_decode_fps,
                buffer_capacity=self.config.buffer_size,
                max_frame_age_ms=selected_age,
                credential_lease=credential_lease,
                fallback_sources=list(fallback_sources or []),
                created_at=now,
                state_changed_at=now,
                buffer=LatestFrameBuffer(self.config.buffer_size),
            )
            session.decoder_backend = (
                self._hardware_decode.backend if self._hardware_decode.available else "ffmpeg"
            )
            session.metrics.resolution = f"{session.width}x{session.height}"
            self._sessions[stream_id] = session
            self._active_by_camera[camera.id] = stream_id
        if self._binary is None:
            self._set_state(
                session,
                ProcessingStreamState.failed,
                error=("FFMPEG_UNAVAILABLE", "FFmpeg is not available on this processing node"),
            )
            self._release_sensitive_source(session)
            return self.snapshot(session)
        self._set_state(session, ProcessingStreamState.connecting)
        thread = threading.Thread(
            target=self._reader_loop,
            args=(session,),
            name=f"drishti-stream-{stream_id[:8]}",
            daemon=True,
        )
        session.reader_thread = thread
        thread.start()
        return self.snapshot(session)

    def _prune_history_locked(self) -> None:
        history_limit = max(100, self.config.max_active_sessions * 4)
        stopped = sorted(
            (
                item
                for item in self._sessions.values()
                if item.state == ProcessingStreamState.stopped
            ),
            key=lambda item: item.stopped_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        for session in stopped[history_limit:]:
            self._sessions.pop(session.id, None)

    def _reader_loop(self, session: ProcessingSession) -> None:
        failure_count = 0
        frame_number = 0
        while not session.stop_event.is_set():
            self._set_state(
                session,
                ProcessingStreamState.connecting
                if failure_count == 0
                else ProcessingStreamState.reconnecting,
            )
            binary = self._binary
            if binary is None:
                self._set_state(
                    session,
                    ProcessingStreamState.failed,
                    error=("FFMPEG_UNAVAILABLE", "FFmpeg is not available on this processing node"),
                )
                break
            read_timeout_seconds = (
                max(
                    self.config.http_startup_timeout_seconds,
                    self.config.http_health_timeout_seconds,
                )
                if session.source_kind in {"hls", "mjpeg"}
                else max(
                    self.config.startup_timeout_seconds,
                    self.config.health_timeout_seconds,
                )
            )
            decoder_config = DecoderConfig(
                width=session.width,
                height=session.height,
                decode_fps=session.decode_fps,
                rtsp_transport=session.transport,
                read_timeout_seconds=read_timeout_seconds,
                stop_timeout_seconds=self.config.stop_timeout_seconds,
            )
            decoder: FrameDecoder | None = None
            failed_over = False
            reconnect_error: tuple[str, str] | None = None
            try:
                decoder = self.decoder_factory(session, decoder_config, binary)
                with session.lock:
                    session.decoder = decoder
                    session.decoder_backend = decoder.backend
                decoder.open(session.endpoint)
                with session.lock:
                    session.decoder_started_monotonic = self.monotonic()
                    session.last_frame_monotonic = None
                    session.last_frame_digest = None
                    session.identical_since_monotonic = None
                    session.last_source_pts_seconds = None
                self._set_state(session, ProcessingStreamState.connected)
                while not session.stop_event.is_set():
                    decoded = decoder.read_frame()
                    if isinstance(decoded, DecodedFrame):
                        payload = decoded.payload
                        source_pts_seconds = decoded.source_pts_seconds
                    else:
                        payload = decoded
                        source_pts_seconds = None
                    received_at = datetime.now(UTC)
                    tick = self.monotonic()
                    frame_number += 1
                    frozen = False
                    with session.lock:
                        session.last_frame_monotonic = tick
                        frozen = self._observe_freeze(
                            session,
                            payload,
                            tick,
                            source_pts_seconds,
                        )
                        health_state = session.state
                        packet = FramePacket(
                            camera_id=session.camera.id,
                            stream_id=session.id,
                            connection_id=session.profile.id,
                            frame_number=frame_number,
                            source_timestamp=None,
                            capture_timestamp=received_at,
                            receive_timestamp=received_at,
                            width=session.width,
                            height=session.height,
                            source_fps=session.metrics.source_fps,
                            decoded_fps=session.metrics.decoded_fps,
                            source_type=session.source_kind,
                            health_state=health_state,
                            pixel_format="rgb24",
                            payload=payload,
                            ai_capabilities=session.camera.ai_capabilities,
                            source_pts_seconds=source_pts_seconds,
                        )
                        session.buffer.put(packet)
                        session.metrics.frames_received += 1
                        session.metrics.queue_depth = session.buffer.depth
                        session.metrics.last_frame_at = received_at
                        self._update_decode_fps(session, tick, source_pts_seconds)
                    if frozen:
                        reconnect_error = (
                            "STREAM_FROZEN",
                            "The stream stopped advancing; the decoder is "
                            "reconnecting automatically",
                        )
                        self._set_state(
                            session,
                            ProcessingStreamState.degraded,
                            error=reconnect_error,
                        )
                        raise RuntimeError("decoded stream stopped advancing")
                    if session.state in {
                        ProcessingStreamState.connected,
                        ProcessingStreamState.reconnecting,
                    }:
                        self._set_state(session, ProcessingStreamState.streaming)
                    failure_count = 0
            except Exception as exc:
                if session.stop_event.is_set():
                    continue
                logger.warning(
                    json.dumps(
                        {
                            "event": "stream_decoder_failure",
                            "component": "decoder",
                            "camera_id": session.camera.id,
                            "stream_id": session.id,
                            "error_type": type(exc).__name__,
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                        separators=(",", ":"),
                    )
                )
                with session.lock:
                    session.metrics.decoder_errors += 1
                failure_count += 1
                with session.lock:
                    session.metrics.reconnect_count += 1
                error = reconnect_error or (
                    decoder.safe_error
                    if decoder
                    else (
                        "STREAM_DECODER_START_FAILED",
                        "The stream decoder could not be created",
                    )
                )
                if decoder is not None and decoder.backend == "ffmpeg_nvdec":
                    self._nvdec_fallback_sessions.add(session.id)
                    error = (
                        "NVDEC_STREAM_FALLBACK",
                        "NVDEC could not decode this stream; retrying with CPU FFmpeg",
                    )
                else:
                    failed_over = self._rotate_source(session)
                if failed_over:
                    error = (
                        "STREAM_SOURCE_FAILOVER",
                        "The preferred transport failed; processing is switching to its fallback",
                    )
                self._set_state(session, ProcessingStreamState.reconnecting, error=error)
            finally:
                with session.lock:
                    if session.decoder is decoder:
                        session.decoder = None
                    session.decoder_started_monotonic = None
                if decoder is not None:
                    try:
                        decoder.close()
                    except Exception as exc:
                        logger.error(
                            json.dumps(
                                {
                                    "event": "stream_decoder_cleanup_failed",
                                    "component": "decoder",
                                    "camera_id": session.camera.id,
                                    "stream_id": session.id,
                                    "error_type": type(exc).__name__,
                                    "timestamp": datetime.now(UTC).isoformat(),
                                },
                                separators=(",", ":"),
                            )
                        )
            if session.stop_event.is_set():
                break
            cap = min(self.config.max_backoff_seconds, float(2 ** min(failure_count, 12)))
            delay = 0.25 if failed_over else max(0.25, self.jitter(0.0, cap))
            if session.stop_event.wait(delay):
                break
        self._finalize_session(session)

    def _rotate_source(self, session: ProcessingSession) -> bool:
        with session.lock:
            if not session.fallback_sources or session.credential_lease is not None:
                return False
            candidate = session.fallback_sources.pop(0)
            if candidate.credential_lease is not None:
                session.fallback_sources.append(candidate)
                return False
            previous = ProcessingSourceCandidate(
                profile=session.profile,
                endpoint=session.endpoint,
                source_kind=session.source_kind,
            )
            session.fallback_sources.append(previous)
            session.profile = candidate.profile
            session.endpoint = candidate.endpoint
            session.source_kind = candidate.source_kind
            session.last_source_pts_seconds = None
            session.metrics.latest_source_pts_seconds = None
            session.metrics.pts_timing_active = False
            session.metrics.source_failover_count += 1
            current_profile = session.profile
        logger.warning(
            json.dumps(
                {
                    "event": "stream_source_failover",
                    "component": "stream_session_manager",
                    "camera_id": session.camera.id,
                    "stream_id": session.id,
                    "profile_id": current_profile.id,
                    "adapter_kind": current_profile.adapter_kind,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                separators=(",", ":"),
            )
        )
        return True

    def _observe_freeze(
        self,
        session: ProcessingSession,
        payload: bytes,
        tick: float,
        source_pts_seconds: float | None,
    ) -> bool:
        digest = hashlib.blake2b(payload[::128], digest_size=8).digest()
        source_clock_advanced = source_pts_seconds is not None and (
            session.last_source_pts_seconds is None
            or source_pts_seconds > session.last_source_pts_seconds
        )
        if digest != session.last_frame_digest or source_clock_advanced:
            session.last_frame_digest = digest
            session.identical_since_monotonic = None
            if session.state == ProcessingStreamState.degraded:
                self._set_state(session, ProcessingStreamState.streaming)
            return False
        if session.identical_since_monotonic is None:
            session.identical_since_monotonic = tick
            return False
        return tick - session.identical_since_monotonic >= self.config.freeze_threshold_seconds

    @staticmethod
    def _update_decode_fps(
        session: ProcessingSession,
        tick: float,
        source_pts_seconds: float | None,
    ) -> None:
        if source_pts_seconds is not None:
            previous_pts = session.last_source_pts_seconds
            if previous_pts is not None and source_pts_seconds > previous_pts:
                instantaneous = 1.0 / (source_pts_seconds - previous_pts)
                if 0.1 <= instantaneous <= 240:
                    current = session.metrics.source_fps
                    session.metrics.source_fps = (
                        instantaneous if current is None else current * 0.85 + instantaneous * 0.15
                    )
            session.last_source_pts_seconds = source_pts_seconds
            session.metrics.latest_source_pts_seconds = source_pts_seconds
            session.metrics.pts_timing_active = True
        if session.fps_window_started is None:
            session.fps_window_started = tick
            session.fps_window_frames = 1
            return
        session.fps_window_frames += 1
        elapsed = tick - session.fps_window_started
        if elapsed >= 1.0:
            session.metrics.decoded_fps = session.fps_window_frames / elapsed
            session.fps_window_started = tick
            session.fps_window_frames = 0

    def _monitor(self) -> None:
        while not self._stop.wait(0.5):
            now = self.monotonic()
            for session in self._active_sessions():
                decoder: FrameDecoder | None = None
                with session.lock:
                    last_frame = session.last_frame_monotonic
                    decoder_started = session.decoder_started_monotonic
                    state = session.state
                    startup_timeout = (
                        self.config.http_startup_timeout_seconds
                        if session.source_kind in {"hls", "mjpeg"}
                        else self.config.startup_timeout_seconds
                    )
                    health_timeout = (
                        self.config.http_health_timeout_seconds
                        if session.source_kind in {"hls", "mjpeg"}
                        else self.config.health_timeout_seconds
                    )
                    if state in {
                        ProcessingStreamState.connected,
                        ProcessingStreamState.streaming,
                        ProcessingStreamState.degraded,
                    } and (
                        (last_frame is not None and now - last_frame > health_timeout)
                        or (
                            last_frame is None
                            and decoder_started is not None
                            and now - decoder_started > startup_timeout
                        )
                    ):
                        decoder = session.decoder
                        session.decoder = None
                if decoder is not None:
                    self._set_state(
                        session,
                        ProcessingStreamState.degraded,
                        error=(
                            "STREAM_FRAME_TIMEOUT",
                            "No decoded frame arrived before the health timeout",
                        ),
                    )
                    decoder.close()

    def _finalize_session(self, session: ProcessingSession) -> None:
        self._release_sensitive_source(session)
        with session.lock:
            if session.buffer is not None:
                session.buffer.clear()
                session.metrics.queue_depth = 0
            session.preview_jpeg = None
            session.preview_frame_number = -1
        with self._lock:
            if self._active_by_camera.get(session.camera.id) == session.id:
                del self._active_by_camera[session.camera.id]
        self.scheduler.forget(session.id)
        self._nvdec_fallback_sessions.discard(session.id)
        self._set_state(session, ProcessingStreamState.stopped)

    @staticmethod
    def _release_sensitive_source(session: ProcessingSession) -> None:
        with session.lock:
            lease, session.credential_lease = session.credential_lease, None
            session.endpoint = ""
            fallback_leases = [candidate.credential_lease for candidate in session.fallback_sources]
            for candidate in session.fallback_sources:
                candidate.endpoint = ""
                candidate.credential_lease = None
            session.fallback_sources.clear()
        for item in [lease, *fallback_leases]:
            if item is None:
                continue
            try:
                item.close()
            except Exception:
                pass

    def stop(self, camera_id: str) -> ProcessingSessionSnapshot:
        with self._lock:
            stream_id = self._active_by_camera.get(camera_id)
            session = self._sessions.get(stream_id or "")
        if session is None:
            raise NotFoundError("stream_session", camera_id)
        session.stop_event.set()
        with session.lock:
            decoder = session.decoder
            session.decoder = None
            thread = session.reader_thread
        if decoder is not None:
            decoder.close()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=self.config.stop_timeout_seconds + 1)
        if session.state != ProcessingStreamState.stopped:
            self._finalize_session(session)
        return self.snapshot(session)

    def get(self, camera_id: str) -> ProcessingSessionSnapshot:
        with self._lock:
            stream_id = self._active_by_camera.get(camera_id)
            if stream_id is None:
                candidates = [
                    item for item in self._sessions.values() if item.camera.id == camera_id
                ]
                session = (
                    max(
                        candidates,
                        key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC),
                    )
                    if candidates
                    else None
                )
            else:
                session = self._sessions.get(stream_id)
        if session is None:
            raise NotFoundError("stream_session", camera_id)
        return self.snapshot(session)

    def list(self) -> list[ProcessingSessionSnapshot]:
        with self._lock:
            sessions = list(self._sessions.values())
        return sorted(
            (self.snapshot(item) for item in sessions),
            key=lambda item: item.created_at,
            reverse=True,
        )

    def snapshot(self, session: ProcessingSession) -> ProcessingSessionSnapshot:
        with session.lock:
            assert session.created_at is not None
            assert session.state_changed_at is not None
            metrics = replace(session.metrics)
            if session.metrics.last_frame_at:
                metrics.current_frame_age_ms = max(
                    0.0,
                    (datetime.now(UTC) - session.metrics.last_frame_at).total_seconds() * 1000,
                )
                metrics.latency_estimate_ms = metrics.current_frame_age_ms
            return ProcessingSessionSnapshot(
                id=session.id,
                camera=session.camera,
                profile=session.profile,
                state=session.state,
                decoder_backend=session.decoder_backend,
                transport=session.transport,
                width=session.width,
                height=session.height,
                target_fps=session.target_fps,
                decode_fps=session.decode_fps,
                buffer_capacity=session.buffer_capacity,
                max_frame_age_ms=session.max_frame_age_ms,
                metrics=metrics,
                created_at=session.created_at,
                state_changed_at=session.state_changed_at,
                connected_at=session.connected_at,
                stopped_at=session.stopped_at,
                last_error_code=session.last_error_code,
                last_error_message=session.last_error_message,
                preview_url=(
                    f"/api/v1/streams/{session.camera.id}/preview.jpg"
                    if session.state in ACTIVE_PROCESSING_STATES
                    else None
                ),
            )

    def metrics(self) -> dict[str, object]:
        items = self.list()
        latest_by_camera: dict[str, ProcessingSessionSnapshot] = {}
        for item in items:
            latest_by_camera.setdefault(item.camera.id, item)
        current = list(latest_by_camera.values())
        active = [item for item in current if item.state in ACTIVE_PROCESSING_STATES]
        states = {state.value: 0 for state in ProcessingStreamState}
        for item in current:
            states[item.state.value] += 1

        def average(values: list[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        resources = self._resource_metrics()
        return {
            "active_streams": len(active),
            "offline_streams": sum(states[item] for item in ("failed", "stopped")),
            "degraded_streams": states["degraded"],
            "reconnecting_streams": states["reconnecting"],
            "average_decoded_fps": average([item.metrics.decoded_fps for item in active]),
            "average_processing_fps": average([item.metrics.processing_fps for item in active]),
            "average_latency_ms": average(
                [item.metrics.latency_estimate_ms or 0.0 for item in active]
            ),
            "total_frames_received": sum(item.metrics.frames_received for item in current),
            "total_frames_dropped": sum(item.metrics.frames_dropped for item in current),
            "total_reconnects": sum(item.metrics.reconnect_count for item in current),
            "scheduler_queue_depth": self.scheduler.queue_depth,
            "ai_consumer_attached": self.scheduler.consumer_attached,
            **resources,
            "states": states,
        }

    def _resource_metrics(self) -> dict[str, object]:
        with self._resource_lock:
            try:
                processes = [
                    self._resource_process,
                    *self._resource_process.children(recursive=True),
                ]
                cpu_seconds = 0.0
                memory_bytes = 0
                live_processes = 0
                for process in processes:
                    try:
                        cpu_times = process.cpu_times()
                        cpu_seconds += cpu_times.user + cpu_times.system
                        memory_bytes += process.memory_info().rss
                        live_processes += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                tick = self.monotonic()
                elapsed = max(0.001, tick - self._resource_tick)
                cpu_percent = max(
                    0.0,
                    (cpu_seconds - self._resource_cpu_seconds) / elapsed * 100,
                )
                self._resource_tick = tick
                self._resource_cpu_seconds = cpu_seconds
                return {
                    "worker_cpu_percent": cpu_percent,
                    "worker_memory_mb": memory_bytes / (1024 * 1024),
                    "worker_processes": live_processes,
                    "gpu_decode_utilization_percent": None,
                    "network_receive_mbps": None,
                }
            except (psutil.Error, OSError):
                return {
                    "worker_cpu_percent": 0.0,
                    "worker_memory_mb": 0.0,
                    "worker_processes": 0,
                    "gpu_decode_utilization_percent": None,
                    "network_receive_mbps": None,
                }

    def next_batch(self, timeout: float | None = None) -> FrameBatch | None:
        """P05 consumes this without knowing anything about cameras, RTSP or credentials."""
        return self.scheduler.next_batch(timeout)

    def latest_jpeg(
        self,
        camera_id: str,
        *,
        after_frame: int = -1,
        timeout: float = 5.0,
    ) -> tuple[int, bytes] | None:
        with self._lock:
            stream_id = self._active_by_camera.get(camera_id)
            session = self._sessions.get(stream_id or "")
        if session is None:
            raise NotFoundError("stream_session", camera_id)
        packet = session.buffer.latest_after(after_frame, timeout=timeout)
        if packet is None:
            return None
        with session.lock:
            if session.preview_frame_number == packet.frame_number and session.preview_jpeg:
                return packet.frame_number, session.preview_jpeg
        image = Image.frombytes("RGB", (packet.width, packet.height), packet.payload)
        output = io.BytesIO()
        # Preview delivery favors bounded encode/network cost; analytics retain raw frames.
        image.save(output, format="JPEG", quality=72, optimize=False)
        encoded = output.getvalue()
        with session.lock:
            session.preview_frame_number = packet.frame_number
            session.preview_jpeg = encoded
        return packet.frame_number, encoded
