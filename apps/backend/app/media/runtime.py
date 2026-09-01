from __future__ import annotations

import os
import random
import re
import signal
import stat
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TextIO

from app.errors import ConflictError, NotFoundError, RegistryError
from app.media.binary import BinaryResolution, resolve_ffmpeg_binary
from app.media.credentials import CredentialLease, CredentialResolver, FailClosedCredentialResolver
from app.media.hardware import HardwareDecodeCapability, detect_nvdec
from app.media.types import (
    ACTIVE_STATES,
    MediaSessionState,
    RuntimeCameraSummary,
    RuntimeMetrics,
    RuntimeProfileSummary,
    RuntimeSession,
    RuntimeSessionSnapshot,
)

SUPPORTED_RUNTIME_ADAPTERS = ("rtsp", "hls", "mjpeg", "onvif", "recorded_file")
UNSUPPORTED_RUNTIME_ADAPTERS = ("vms_http",)
SEGMENT_NAME_PATTERN = re.compile(r"segment_g[0-9]{1,6}_[0-9]{6,12}\.ts\Z")
MAX_PLAYLIST_BYTES = 1024 * 1024
MAX_STDERR_LINES = 80
MAX_STDERR_LINE_CHARS = 600
_URL_PATTERN = re.compile(r"(?i)\b(?:rtsp|https?|file|recorded)://[^\s]+")
_SAFE_PLAYLIST_TAGS = (
    "#EXTM3U",
    "#EXT-X-VERSION:",
    "#EXT-X-TARGETDURATION:",
    "#EXT-X-MEDIA-SEQUENCE:",
    "#EXT-X-DISCONTINUITY-SEQUENCE:",
    "#EXT-X-INDEPENDENT-SEGMENTS",
    "#EXT-X-PROGRAM-DATE-TIME:",
    "#EXT-X-ALLOW-CACHE:",
    "#EXTINF:",
    "#EXT-X-DISCONTINUITY",
    "#EXT-X-ENDLIST",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProcessLike(Protocol):
    pid: int
    stdin: TextIO | None
    stdout: TextIO | None
    stderr: TextIO | None

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def send_signal(self, sig: int) -> None: ...


ProcessFactory = Callable[[list[str]], ProcessLike]
BinaryResolver = Callable[[str | None], BinaryResolution | None]
HardwareDetector = Callable[[BinaryResolution | None], HardwareDecodeCapability]


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    runtime_root: str
    configured_binary: str | None = None
    decoder_backend: str = "auto"
    segment_duration_seconds: int = 2
    playlist_window: int = 6
    watchdog_seconds: float = 12.0
    max_backoff_seconds: float = 30.0
    max_restarts: int = 8
    stop_timeout_seconds: float = 5.0
    max_active_sessions: int = 8
    credential_resolver_mode: str = "fail_closed"

    def __post_init__(self) -> None:
        if self.decoder_backend not in {"auto", "nvdec", "ffmpeg"}:
            raise ValueError("decoder_backend must be auto, nvdec, or ffmpeg")


def _validate_runtime_root(raw_root: str) -> Path:
    root = Path(raw_root).expanduser().resolve(strict=False)
    anchor = Path(root.anchor).resolve(strict=False) if root.anchor else None
    if not root.name or (anchor is not None and root == anchor):
        raise ValueError("FEDERATION_RUNTIME_ROOT must not be a filesystem root")
    return root


def _default_process_factory(arguments: list[str]) -> ProcessLike:
    inherited_environment_keys = {
        "DYLD_LIBRARY_PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LD_LIBRARY_PATH",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    }
    runtime_environment = {
        key: value for key, value in os.environ.items() if key.upper() in inherited_environment_keys
    }
    kwargs: dict[str, Any] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
        "shell": False,
        "env": runtime_environment,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(arguments, **kwargs)  # type: ignore[return-value]


def _terminate_process_tree(process: ProcessLike, *, timeout_seconds: float) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except (AttributeError, OSError, ValueError):
                process.terminate()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=timeout_seconds)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.wait(timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass


class MediaRuntimeManager:
    """Process-local FFmpeg supervisor with a replaceable scheduling boundary.

    Session state and ownership locks are intentionally in memory for P0.3R.
    State is lost on process restart and this class must not be presented as a
    statewide scheduler. Its API permits a future durable regional controller.
    """

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        process_factory: ProcessFactory | None = None,
        binary_resolver: BinaryResolver = resolve_ffmpeg_binary,
        hardware_detector: HardwareDetector = detect_nvdec,
        credential_resolver: CredentialResolver | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = _utcnow,
        jitter: Callable[[float, float], float] = random.uniform,
        process_terminator: Callable[..., None] = _terminate_process_tree,
    ) -> None:
        self.config = config
        self.root = _validate_runtime_root(config.runtime_root)
        self.process_factory = process_factory or _default_process_factory
        self.binary_resolver = binary_resolver
        self.hardware_detector = hardware_detector
        self.credential_resolver = credential_resolver or FailClosedCredentialResolver()
        self.monotonic = monotonic
        self.wall_clock = wall_clock
        self.jitter = jitter
        self.process_terminator = process_terminator
        self._sessions: dict[str, RuntimeSession] = {}
        self._active_by_connection: dict[str, str] = {}
        self._lock = threading.RLock()
        self._shutdown = False
        self._binary: BinaryResolution | None = None
        self._hardware_decode = HardwareDecodeCapability(False, "ffmpeg", "not_probed")
        self._nvdec_fallback_sessions: set[str] = set()

    def startup(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._binary = self.binary_resolver(self.config.configured_binary)
        if self.config.decoder_backend == "ffmpeg":
            self._hardware_decode = HardwareDecodeCapability(
                False, "ffmpeg", "disabled_by_configuration"
            )
        else:
            self._hardware_decode = self.hardware_detector(self._binary)

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown = True
            session_ids = list(self._sessions)
        for session_id in session_ids:
            try:
                self.stop(session_id)
            except NotFoundError:
                continue

    def capabilities(self) -> dict[str, Any]:
        if self._binary is None:
            self._binary = self.binary_resolver(self.config.configured_binary)
        if self._hardware_decode.reason == "not_probed":
            if self.config.decoder_backend == "ffmpeg":
                self._hardware_decode = HardwareDecodeCapability(
                    False, "ffmpeg", "disabled_by_configuration"
                )
            else:
                self._hardware_decode = self.hardware_detector(self._binary)
        with self._lock:
            active_sessions = len(self._active_by_connection)
        return {
            "available": self._binary is not None,
            "binary_source": self._binary.source if self._binary else "unavailable",
            "supported_adapter_kinds": list(SUPPORTED_RUNTIME_ADAPTERS),
            "unsupported_adapter_kinds": list(UNSUPPORTED_RUNTIME_ADAPTERS),
            "output_protocol": "hls",
            "segment_duration_seconds": self.config.segment_duration_seconds,
            "playlist_window": self.config.playlist_window,
            "decoder_backend": self._hardware_decode.backend,
            "hardware_decode_active": self._hardware_decode.available,
            "hardware_decode_reason": self._hardware_decode.reason,
            "video_processing_mode": (
                "nvdec_decode_software_h264_transcode"
                if self._hardware_decode.available
                else "software_h264_transcode"
            ),
            "max_active_sessions": self.config.max_active_sessions,
            "credential_resolver_mode": self.config.credential_resolver_mode,
            "network_handoff": {
                "rtsp": "ip_pinned",
                "mjpeg": "protocol_limited_start_validation",
                "hls": "protocol_limited_start_validation",
                "hls_child_uris": "not_host_pinned",
            },
            "active_sessions": active_sessions,
            "supervision": {
                "watchdog_seconds": self.config.watchdog_seconds,
                "max_backoff_seconds": self.config.max_backoff_seconds,
                "max_restarts": self.config.max_restarts,
            },
            "boundary": "process_local_poc",
        }

    def _session_directory(self, session_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f-]{36}", session_id):
            raise NotFoundError("runtime_session", session_id)
        candidate = (self.root / session_id).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise NotFoundError("runtime_session", session_id) from exc
        return candidate

    def _new_session(
        self,
        *,
        connection_id: str,
        endpoint: str,
        camera: RuntimeCameraSummary,
        profile: RuntimeProfileSummary,
    ) -> RuntimeSession:
        session_id = str(uuid.uuid4())
        now = self.wall_clock()
        directory = self._session_directory(session_id)
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        return RuntimeSession(
            id=session_id,
            connection_id=connection_id,
            camera=camera,
            profile=profile,
            endpoint=endpoint,
            session_directory=str(directory),
            state=MediaSessionState.starting,
            started_at=now,
            state_changed_at=now,
        )

    def _set_state(
        self,
        session: RuntimeSession,
        state: MediaSessionState,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with session.lock:
            session.state = state
            session.state_changed_at = self.wall_clock()
            session.last_error_code = error_code
            session.last_error_message = error_message
            if state == MediaSessionState.stopped:
                session.stopped_at = session.state_changed_at
        if state not in ACTIVE_STATES:
            with self._lock:
                if self._active_by_connection.get(session.connection_id) == session.id:
                    self._active_by_connection.pop(session.connection_id, None)

    def create_unavailable(
        self,
        *,
        connection_id: str,
        camera: RuntimeCameraSummary,
        profile: RuntimeProfileSummary,
        error_code: str,
        error_message: str,
    ) -> RuntimeSessionSnapshot:
        with self._lock:
            active_id = self._active_by_connection.get(connection_id)
            if active_id:
                raise ConflictError(
                    "RUNTIME_SESSION_ACTIVE",
                    "This connection already has an active runtime session",
                    {"session_id": active_id},
                )
            session = self._new_session(
                connection_id=connection_id,
                endpoint="",
                camera=camera,
                profile=profile,
            )
            self._sessions[session.id] = session
        self._set_state(
            session,
            MediaSessionState.unavailable,
            error_code=error_code,
            error_message=error_message,
        )
        return self.snapshot(session)

    def start(
        self,
        *,
        connection_id: str,
        endpoint: str,
        camera: RuntimeCameraSummary,
        profile: RuntimeProfileSummary,
        credential_lease: CredentialLease | None = None,
    ) -> RuntimeSessionSnapshot:
        with self._lock:
            if self._shutdown:
                raise RegistryError(
                    code="RUNTIME_SHUTTING_DOWN",
                    message="The media runtime is shutting down",
                    status_code=503,
                )
            active_id = self._active_by_connection.get(connection_id)
            if active_id:
                raise ConflictError(
                    "RUNTIME_SESSION_ACTIVE",
                    "This connection already has an active runtime session",
                    {"session_id": active_id},
                )
            if len(self._active_by_connection) >= self.config.max_active_sessions:
                raise RegistryError(
                    code="RUNTIME_CAPACITY_EXCEEDED",
                    message="This runtime node has reached its configured session capacity",
                    status_code=429,
                )
            session = self._new_session(
                connection_id=connection_id,
                endpoint=endpoint,
                camera=camera,
                profile=profile,
            )
            session.credential_lease = credential_lease
            self._sessions[session.id] = session
            self._active_by_connection[connection_id] = session.id

        if self._binary is None:
            self._binary = self.binary_resolver(self.config.configured_binary)
        if self._binary is None:
            self._set_state(
                session,
                MediaSessionState.unavailable,
                error_code="FFMPEG_UNAVAILABLE",
                error_message="FFmpeg is not available on this runtime node",
            )
            self._close_lease(session)
            return self.snapshot(session)

        thread = threading.Thread(
            target=self._supervise,
            args=(session,),
            name=f"drishti-media-{session.id[:8]}",
            daemon=True,
        )
        session.supervisor_thread = thread
        thread.start()
        return self.snapshot(session)

    def _build_command(self, session: RuntimeSession) -> list[str]:
        if self._binary is None:
            raise RuntimeError("FFmpeg binary resolution was lost")
        directory = Path(session.session_directory)
        playlist_path = directory / "playlist.m3u8"
        segment_pattern = directory / f"segment_g{session.generation}_%06d.ts"
        arguments = [
            self._binary.path,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "info",
            "-nostats",
            "-fflags",
            "+genpts+discardcorrupt",
        ]
        use_nvdec = (
            self._hardware_decode.available and session.id not in self._nvdec_fallback_sessions
        )
        with session.lock:
            session.decoder_backend = "ffmpeg_nvdec" if use_nvdec else "ffmpeg"
        if session.profile.adapter_kind in {"rtsp", "onvif"}:
            # ``rtp`` is required by FFmpeg even when RTP is interleaved over
            # the RTSP TCP connection; UDP transport is not enabled here.
            protocol_whitelist = "file,pipe,rtsp,rtp,tcp"
        elif session.profile.adapter_kind in {"hls", "mjpeg"}:
            protocol_whitelist = (
                "file,pipe,http,https,tcp,tls,crypto"
                if session.profile.adapter_kind == "hls"
                else "file,pipe,http,https,tcp,tls"
            )
        elif session.profile.adapter_kind == "recorded_file":
            protocol_whitelist = "file,pipe"
            arguments.extend(["-re", "-stream_loop", "-1"])
        else:
            raise RuntimeError("Unsupported media adapter reached the command builder")
        if use_nvdec:
            arguments.extend(["-hwaccel", "cuda"])
        arguments.extend(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-protocol_whitelist",
                protocol_whitelist,
                "-i",
                "pipe:0",
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
                "-g",
                "50",
                "-keyint_min",
                "50",
                "-sc_threshold",
                "0",
                "-f",
                "hls",
                "-hls_time",
                str(self.config.segment_duration_seconds),
                "-hls_list_size",
                str(self.config.playlist_window),
                "-hls_flags",
                "delete_segments+temp_file+independent_segments+program_date_time+omit_endlist",
                "-hls_segment_filename",
                str(segment_pattern),
                "-progress",
                "pipe:1",
                str(playlist_path),
            ]
        )
        return arguments

    @staticmethod
    def _manifest_endpoint(endpoint: str) -> str:
        if "\\" in endpoint:
            local_path = Path(endpoint).expanduser()
            if not local_path.is_absolute():
                raise RuntimeError("The media endpoint cannot be represented safely")
            endpoint = local_path.resolve(strict=False).as_posix()
        if not endpoint or any(
            character in endpoint for character in ("'", "\r", "\n", "\\", "\0")
        ):
            raise RuntimeError("The media endpoint cannot be represented safely")
        return endpoint

    @classmethod
    def _source_manifest(cls, endpoint: str, *, input_options: dict[str, str] | None = None) -> str:
        endpoint = cls._manifest_endpoint(endpoint)
        lines = ["ffconcat version 1.0", f"file '{endpoint}'"]
        for name, value in (input_options or {}).items():
            if not re.fullmatch(r"[a-z_]+", name) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                raise RuntimeError("The media input option cannot be represented safely")
            lines.append(f"option {name} {value}")
        return "\n".join(lines) + "\n"

    def _write_source_manifest(
        self,
        process: ProcessLike,
        endpoint: str,
        *,
        input_options: dict[str, str] | None = None,
    ) -> None:
        if process.stdin is None:
            raise RuntimeError("The media process has no protected input channel")
        manifest = self._source_manifest(endpoint, input_options=input_options)
        try:
            process.stdin.write(manifest)
            process.stdin.flush()
        finally:
            process.stdin.close()

    def _safe_stderr_line(self, line: str, endpoint: str) -> str:
        value = line
        redaction_candidates = {endpoint} if endpoint else set()
        try:
            redaction_candidates.add(self._manifest_endpoint(endpoint))
        except RuntimeError:
            pass
        for candidate in sorted(redaction_candidates, key=len, reverse=True):
            value = value.replace(candidate, "[REDACTED_ENDPOINT]")
        return _URL_PATTERN.sub("[REDACTED_ENDPOINT]", value)[:MAX_STDERR_LINE_CHARS]

    def _stderr_reader(self, session: RuntimeSession, process: ProcessLike) -> None:
        if process.stderr is None:
            return
        for line in iter(process.stderr.readline, ""):
            if not line:
                break
            safe_line = self._safe_stderr_line(line.strip(), session.endpoint)
            with session.lock:
                session.stderr_tail.append(safe_line)
                if len(session.stderr_tail) > MAX_STDERR_LINES:
                    del session.stderr_tail[: len(session.stderr_tail) - MAX_STDERR_LINES]
            if session.stop_event.is_set():
                break

    def _progress_reader(self, session: RuntimeSession, process: ProcessLike) -> None:
        if process.stdout is None:
            return
        for line in iter(process.stdout.readline, ""):
            if session.stop_event.is_set():
                break
            key, separator, raw_value = line.strip().partition("=")
            if not separator:
                continue
            value = raw_value.strip()
            now = self.wall_clock()
            with session.lock:
                try:
                    if key == "frame":
                        session.metrics.frame = max(0, int(value))
                    elif key == "fps":
                        session.metrics.fps = max(0.0, float(value))
                    elif key == "out_time_ms":
                        session.metrics.out_time_ms = max(0, int(value) // 1000)
                except ValueError:
                    continue
                if key == "progress":
                    session.metrics.progress_at = now
                    session.last_progress_at = now
                    session.last_progress_monotonic = self.monotonic()

    def _observe_playlist(self, session: RuntimeSession) -> bool:
        playlist = Path(session.session_directory) / "playlist.m3u8"
        try:
            stat = playlist.stat()
        except OSError:
            return False
        if stat.st_size <= 0 or stat.st_size > MAX_PLAYLIST_BYTES:
            return False
        try:
            raw = playlist.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        media_sequence = ""
        last_segment = ""
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                media_sequence = stripped
            elif stripped and not stripped.startswith("#"):
                last_segment = Path(stripped).name
        if not SEGMENT_NAME_PATTERN.fullmatch(last_segment):
            return False
        signature = f"{media_sequence}|{last_segment}"
        observed = self.monotonic()
        with session.lock:
            if signature != session.playlist_signature:
                session.playlist_signature = signature
                modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
                session.last_playlist_at = modified_at
                session.last_playlist_monotonic = observed
        return True

    def _failure_from_stderr(
        self, session: RuntimeSession, exit_code: int | None
    ) -> tuple[str, str]:
        with session.lock:
            tail = "\n".join(session.stderr_tail).casefold()
        if "unauthorized" in tail or "401" in tail or "403" in tail:
            return "RUNTIME_AUTHENTICATION_REQUIRED", "The media source requires credentials"
        if "connection refused" in tail:
            return "RUNTIME_CONNECTION_REFUSED", "The media source refused the connection"
        if "no such file" in tail or "not found" in tail:
            return "RUNTIME_SOURCE_NOT_FOUND", "The media source could not be found"
        if exit_code is None:
            return "RUNTIME_WATCHDOG_STALLED", "The media pipeline stopped producing output"
        return "FFMPEG_EXITED", "The media pipeline exited unexpectedly"

    def _prepare_retry(self, session: RuntimeSession, *, error: tuple[str, str]) -> bool:
        with session.lock:
            session.restart_count += 1
            count = session.restart_count
        if count > self.config.max_restarts:
            self._set_state(
                session,
                MediaSessionState.failed,
                error_code="RUNTIME_RESTART_LIMIT",
                error_message="The media pipeline exceeded its supervised restart limit",
            )
            self._close_lease(session)
            return False
        self._set_state(
            session,
            MediaSessionState.backoff,
            error_code=error[0],
            error_message=error[1],
        )
        cap = min(self.config.max_backoff_seconds, float(2 ** max(0, count - 1)))
        delay = max(0.25, self.jitter(0.0, cap))
        return not session.stop_event.wait(delay)

    def _prepare_nvdec_fallback(self, session: RuntimeSession, *, message: str) -> bool:
        self._nvdec_fallback_sessions.add(session.id)
        self._set_state(
            session,
            MediaSessionState.backoff,
            error_code="NVDEC_STREAM_FALLBACK",
            error_message=message,
        )
        # A hardware compatibility miss is not a stream restart failure and
        # must still get one CPU attempt when max_restarts is configured as 0.
        return not session.stop_event.wait(0.25)

    def _supervise(self, session: RuntimeSession) -> None:
        while not session.stop_event.is_set():
            self._remove_generated_assets(session)
            self._set_state(session, MediaSessionState.starting)
            with session.lock:
                session.generation += 1
                session.stderr_tail.clear()
                session.last_progress_monotonic = None
                session.last_playlist_at = None
                session.last_playlist_monotonic = None
                session.playlist_signature = None
            launched_at = self.monotonic()
            try:
                process = self.process_factory(self._build_command(session))
                input_options = {"timeout": "10000000"}
                if session.profile.adapter_kind in {"rtsp", "onvif"}:
                    input_options["rtsp_transport"] = "tcp"
                self._write_source_manifest(
                    process,
                    session.endpoint,
                    input_options=input_options,
                )
            except (OSError, RuntimeError):
                if session.decoder_backend == "ffmpeg_nvdec":
                    if not self._prepare_nvdec_fallback(
                        session,
                        message="NVDEC could not start this stream; retrying with CPU FFmpeg",
                    ):
                        return
                    continue
                else:
                    start_error = (
                        "FFMPEG_START_FAILED",
                        "The media pipeline could not be started",
                    )
                if not self._prepare_retry(
                    session,
                    error=start_error,
                ):
                    return
                continue
            with session.lock:
                session.process = process
            stderr_thread = threading.Thread(
                target=self._stderr_reader, args=(session, process), daemon=True
            )
            progress_thread = threading.Thread(
                target=self._progress_reader, args=(session, process), daemon=True
            )
            stderr_thread.start()
            progress_thread.start()

            failure: tuple[str, str] | None = None
            while not session.stop_event.wait(0.2):
                exit_code = process.poll()
                if exit_code is not None:
                    failure = self._failure_from_stderr(session, exit_code)
                    break
                playlist_ready = self._observe_playlist(session)
                now_monotonic = self.monotonic()
                if playlist_ready:
                    with session.lock:
                        heartbeat = max(
                            session.last_playlist_monotonic or launched_at,
                            session.last_progress_monotonic or launched_at,
                        )
                    if now_monotonic - heartbeat <= self.config.watchdog_seconds:
                        if session.state != MediaSessionState.live:
                            self._set_state(session, MediaSessionState.live)
                        continue
                if now_monotonic - launched_at > self.config.watchdog_seconds:
                    self._set_state(
                        session,
                        MediaSessionState.degraded,
                        error_code="RUNTIME_WATCHDOG_STALLED",
                        error_message="The media pipeline stopped producing output",
                    )
                    failure = self._failure_from_stderr(session, None)
                    break

            self.process_terminator(process, timeout_seconds=self.config.stop_timeout_seconds)
            with session.lock:
                session.process = None
            if session.stop_event.is_set():
                break
            if failure is None:
                failure = self._failure_from_stderr(session, process.poll())
            if session.decoder_backend == "ffmpeg_nvdec":
                if not self._prepare_nvdec_fallback(
                    session,
                    message="NVDEC could not decode this stream; retrying with CPU FFmpeg",
                ):
                    return
                continue
            if not self._prepare_retry(session, error=failure):
                return

        self._set_state(session, MediaSessionState.stopped)
        self._close_lease(session)

    def snapshot(self, session: RuntimeSession) -> RuntimeSessionSnapshot:
        with session.lock:
            assert session.started_at is not None
            assert session.state_changed_at is not None
            return RuntimeSessionSnapshot(
                id=session.id,
                connection_id=session.connection_id,
                state=session.state,
                camera=session.camera,
                profile=session.profile,
                decoder_backend=session.decoder_backend,
                playlist_url=(
                    f"/api/v1/federation/runtime/sessions/{session.id}/playlist.m3u8"
                    if session.state in ACTIVE_STATES
                    else None
                ),
                metrics=RuntimeMetrics(
                    frame=session.metrics.frame,
                    fps=session.metrics.fps,
                    out_time_ms=session.metrics.out_time_ms,
                    progress_at=session.metrics.progress_at,
                ),
                restart_count=session.restart_count,
                started_at=session.started_at,
                state_changed_at=session.state_changed_at,
                last_progress_at=session.last_progress_at,
                last_playlist_at=session.last_playlist_at,
                stopped_at=session.stopped_at,
                last_error_code=session.last_error_code,
                last_error_message=session.last_error_message,
            )

    def get(self, session_id: str) -> RuntimeSessionSnapshot:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise NotFoundError("runtime_session", session_id)
        return self.snapshot(session)

    def list(self) -> list[RuntimeSessionSnapshot]:
        with self._lock:
            sessions = list(self._sessions.values())
        snapshots = [self.snapshot(session) for session in sessions]
        return sorted(snapshots, key=lambda item: item.started_at, reverse=True)

    def stop(self, session_id: str) -> RuntimeSessionSnapshot:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise NotFoundError("runtime_session", session_id)
        session.stop_event.set()
        with session.lock:
            process = session.process
            thread = session.supervisor_thread
        if process is not None:
            self.process_terminator(process, timeout_seconds=self.config.stop_timeout_seconds)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=self.config.stop_timeout_seconds + 1.0)
        if session.state != MediaSessionState.stopped:
            self._set_state(session, MediaSessionState.stopped)
            self._close_lease(session)
        self._remove_generated_assets(session)
        self._nvdec_fallback_sessions.discard(session.id)
        return self.snapshot(session)

    def _remove_generated_assets(self, session: RuntimeSession) -> None:
        directory = Path(session.session_directory)
        for candidate in directory.iterdir():
            if candidate.name == "playlist.m3u8" or SEGMENT_NAME_PATTERN.fullmatch(candidate.name):
                try:
                    candidate.unlink()
                except OSError:
                    continue

    def restart(self, session_id: str) -> RuntimeSessionSnapshot:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise NotFoundError("runtime_session", session_id)
        self.stop(session_id)
        self._remove_generated_assets(session)
        self._nvdec_fallback_sessions.discard(session.id)
        with session.lock:
            session.stop_event = threading.Event()
            session.stopped_at = None
            session.last_error_code = None
            session.last_error_message = None
            session.metrics = RuntimeMetrics()
            session.last_progress_at = None
            session.last_playlist_at = None
            session.last_progress_monotonic = None
            session.last_playlist_monotonic = None
            session.playlist_signature = None
            session.restart_count += 1
        if not session.endpoint:
            self._set_state(
                session,
                MediaSessionState.unavailable,
                error_code="RUNTIME_SOURCE_UNAVAILABLE",
                error_message="This runtime session has no resolvable media source",
            )
            return self.snapshot(session)
        if self._binary is None:
            self._binary = self.binary_resolver(self.config.configured_binary)
        if self._binary is None:
            self._set_state(
                session,
                MediaSessionState.unavailable,
                error_code="FFMPEG_UNAVAILABLE",
                error_message="FFmpeg is not available on this runtime node",
            )
            return self.snapshot(session)
        with self._lock:
            active_id = self._active_by_connection.get(session.connection_id)
            if active_id and active_id != session.id:
                raise ConflictError(
                    "RUNTIME_SESSION_ACTIVE",
                    "This connection already has an active runtime session",
                    {"session_id": active_id},
                )
            if (
                session.connection_id not in self._active_by_connection
                and len(self._active_by_connection) >= self.config.max_active_sessions
            ):
                raise RegistryError(
                    code="RUNTIME_CAPACITY_EXCEEDED",
                    message="This runtime node has reached its configured session capacity",
                    status_code=429,
                )
            self._active_by_connection[session.connection_id] = session.id
        self._set_state(session, MediaSessionState.starting)
        thread = threading.Thread(
            target=self._supervise,
            args=(session,),
            name=f"drishti-media-{session.id[:8]}",
            daemon=True,
        )
        session.supervisor_thread = thread
        thread.start()
        return self.snapshot(session)

    def _close_lease(self, session: RuntimeSession) -> None:
        with session.lock:
            lease = session.credential_lease
            session.credential_lease = None
        if lease is not None:
            try:
                lease.close()
            except Exception:
                pass

    def playlist_text(self, session_id: str) -> str:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise NotFoundError("runtime_session", session_id)
        if session.state not in ACTIVE_STATES:
            raise RegistryError(
                code="RUNTIME_SESSION_NOT_ACTIVE",
                message="The runtime session is not active",
                status_code=409,
            )
        path = Path(session.session_directory) / "playlist.m3u8"
        try:
            size = path.stat().st_size
            if size <= 0 or size > MAX_PLAYLIST_BYTES:
                raise OSError
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RegistryError(
                code="RUNTIME_PLAYLIST_NOT_READY",
                message="The runtime playlist is not ready",
                status_code=409,
            ) from exc
        safe_lines: list[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                if stripped.startswith("#") and not stripped.startswith(_SAFE_PLAYLIST_TAGS):
                    raise RegistryError(
                        code="RUNTIME_PLAYLIST_INVALID",
                        message="The runtime playlist contains an unsupported directive",
                        status_code=503,
                    )
                safe_lines.append(line)
                continue
            asset_name = Path(stripped).name
            if not SEGMENT_NAME_PATTERN.fullmatch(asset_name):
                raise RegistryError(
                    code="RUNTIME_PLAYLIST_INVALID",
                    message="The runtime playlist contains an invalid media asset",
                    status_code=503,
                )
            safe_lines.append(f"segments/{asset_name}")
        return "\n".join(safe_lines) + "\n"

    def open_segment(self, session_id: str, asset_name: str) -> tuple[Any, int]:
        if not SEGMENT_NAME_PATTERN.fullmatch(asset_name):
            raise NotFoundError("runtime_asset", asset_name)
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise NotFoundError("runtime_session", session_id)
        if session.state not in ACTIVE_STATES:
            raise NotFoundError("runtime_asset", asset_name)
        directory = Path(session.session_directory).resolve(strict=False)
        candidate = (directory / asset_name).resolve(strict=False)
        try:
            candidate.relative_to(directory)
        except ValueError as exc:
            raise NotFoundError("runtime_asset", asset_name) from exc
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, flags)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                os.close(descriptor)
                raise OSError
        except OSError as exc:
            raise NotFoundError("runtime_asset", asset_name) from exc
        if candidate.is_symlink():
            os.close(descriptor)
            raise NotFoundError("runtime_asset", asset_name)
        return os.fdopen(descriptor, "rb"), metadata.st_size
