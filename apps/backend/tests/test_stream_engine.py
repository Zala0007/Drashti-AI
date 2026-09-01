from __future__ import annotations

import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from app.media.binary import BinaryResolution, resolve_ffmpeg_binary
from app.media.credentials import CredentialLease
from app.media.runtime import MediaRuntimeManager
from app.stream_engine import DecodedFrame, DecoderConfig, FFmpegRawDecoder, LatestFrameBuffer
from app.stream_engine.decoder import DecoderError
from app.stream_engine.engine import StreamEngine, StreamEngineConfig
from app.stream_engine.types import (
    FramePacket,
    ProcessingCameraSummary,
    ProcessingProfileSummary,
    ProcessingSourceCandidate,
    ProcessingStreamState,
)


def _camera(identifier: str = "camera-1") -> ProcessingCameraSummary:
    return ProcessingCameraSummary(
        id=identifier,
        camera_code=identifier.upper(),
        camera_name=f"Test {identifier}",
        department_id="department-1",
        department_name="Home Department",
        district="Ahmedabad",
        city="Ahmedabad",
        latitude=23.02,
        longitude=72.57,
        vendor="Test Vendor",
        model="T-1",
        camera_type="anpr",
    )


def _profile(identifier: str = "profile-1") -> ProcessingProfileSummary:
    return ProcessingProfileSummary(
        id=identifier,
        name="Main stream",
        adapter_kind="rtsp",
        stream_role="main",
        endpoint_display="rtsp://t***t/…",
    )


def _packet(frame_number: int) -> FramePacket:
    now = datetime.now(UTC)
    return FramePacket(
        camera_id="camera-1",
        stream_id="stream-1",
        connection_id="profile-1",
        frame_number=frame_number,
        source_timestamp=None,
        capture_timestamp=now,
        receive_timestamp=now,
        width=2,
        height=2,
        source_fps=25,
        decoded_fps=10,
        source_type="rtsp",
        health_state=ProcessingStreamState.streaming,
        pixel_format="rgb24",
        payload=bytes([frame_number % 255]) * 12,
    )


def _wait_until(predicate: object, timeout: float = 2.0) -> None:
    callback = predicate
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callback():  # type: ignore[operator]
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


class StableDecoder:
    backend = "fake"

    def __init__(self, width: int, height: int) -> None:
        self.payload_size = width * height * 3
        self.frame = 0
        self.closed = threading.Event()

    def open(self, endpoint: str) -> None:
        assert endpoint == "rtsp://source"

    def read_frame(self) -> bytes:
        if self.closed.wait(0.01):
            raise DecoderError("closed")
        self.frame += 1
        return bytes([self.frame % 255]) * self.payload_size

    def close(self) -> None:
        self.closed.set()

    @property
    def safe_error(self) -> tuple[str, str]:
        return "TEST_DECODER_STOPPED", "The test decoder stopped"


class FailingDecoder(StableDecoder):
    def open(self, endpoint: str) -> None:
        del endpoint
        raise DecoderError("camera unavailable")


class FrozenDecoder(StableDecoder):
    def read_frame(self) -> bytes:
        if self.closed.wait(0.01):
            raise DecoderError("closed")
        return b"\x2a" * self.payload_size


class StationaryTimedDecoder(StableDecoder):
    def read_frame(self) -> DecodedFrame:
        if self.closed.wait(0.01):
            raise DecoderError("closed")
        self.frame += 1
        return DecodedFrame(
            payload=b"\x2a" * self.payload_size,
            source_pts_seconds=self.frame / 25,
        )


def _engine(*, failing_camera: str | None = None) -> StreamEngine:
    def factory(session: object, config: DecoderConfig, binary: BinaryResolution) -> StableDecoder:
        del binary
        camera_id = session.camera.id  # type: ignore[attr-defined]
        if camera_id == failing_camera:
            return FailingDecoder(config.width, config.height)
        return StableDecoder(config.width, config.height)

    return StreamEngine(
        StreamEngineConfig(
            width=16,
            height=8,
            decode_fps=20,
            target_fps=10,
            batch_size=2,
            batch_timeout_ms=10,
            buffer_size=2,
            health_timeout_seconds=1,
            freeze_threshold_seconds=1,
            max_backoff_seconds=1,
            stop_timeout_seconds=1,
        ),
        decoder_factory=factory,
        binary_resolver=lambda _: BinaryResolution("fake-ffmpeg", "configured"),
        jitter=lambda _start, _end: 0,
    )


def test_latest_frame_buffer_drops_oldest_and_retains_newest() -> None:
    buffer = LatestFrameBuffer(capacity=2)
    buffer.put(_packet(1))
    buffer.put(_packet(2))
    buffer.put(_packet(3))

    assert buffer.depth == 2
    assert buffer.frames_replaced == 1
    assert buffer.latest() is not None
    assert buffer.latest().frame_number == 3  # type: ignore[union-attr]
    assert buffer.latest_after(2, timeout=0.01).frame_number == 3  # type: ignore[union-attr]


def test_stream_lifecycle_emits_ai_ready_batches_and_preview() -> None:
    engine = _engine()
    engine.startup()
    try:
        started = engine.start(
            camera=_camera(),
            profile=_profile(),
            endpoint="rtsp://source",
            source_kind="rtsp",
        )
        assert started.state in {
            ProcessingStreamState.connecting,
            ProcessingStreamState.connected,
            ProcessingStreamState.streaming,
        }
        _wait_until(lambda: engine.get("camera-1").state == ProcessingStreamState.streaming)
        batch = engine.next_batch(timeout=1)
        assert batch is not None
        assert batch.packets[0].camera_id == "camera-1"
        assert batch.packets[0].pixel_format == "rgb24"
        preview = engine.latest_jpeg("camera-1", timeout=1)
        assert preview is not None
        assert preview[1].startswith(b"\xff\xd8")

        stopped = engine.stop("camera-1")
        assert stopped.state == ProcessingStreamState.stopped
        assert stopped.metrics.queue_depth == 0
        assert engine.next_batch(timeout=0.05) is None
    finally:
        engine.shutdown()


def test_one_camera_failure_does_not_interrupt_other_streams() -> None:
    engine = _engine(failing_camera="camera-bad")
    engine.startup()
    try:
        engine.start(
            camera=_camera("camera-bad"),
            profile=_profile("profile-bad"),
            endpoint="rtsp://source",
            source_kind="rtsp",
        )
        engine.start(
            camera=_camera("camera-good"),
            profile=_profile("profile-good"),
            endpoint="rtsp://source",
            source_kind="rtsp",
        )
        _wait_until(lambda: engine.get("camera-good").state == ProcessingStreamState.streaming)
        _wait_until(lambda: engine.get("camera-bad").metrics.reconnect_count >= 1)

        good = engine.get("camera-good")
        bad = engine.get("camera-bad")
        assert good.metrics.frames_received > 0
        assert bad.state == ProcessingStreamState.reconnecting
        assert bad.metrics.decoder_errors >= 1
    finally:
        engine.shutdown()


def test_frozen_stream_reconnects_without_manual_intervention() -> None:
    decoder_instances: list[FrozenDecoder] = []

    def factory(
        _session: object,
        config: DecoderConfig,
        _binary: BinaryResolution,
    ) -> FrozenDecoder:
        decoder = FrozenDecoder(config.width, config.height)
        decoder_instances.append(decoder)
        return decoder

    engine = StreamEngine(
        StreamEngineConfig(
            width=16,
            height=8,
            freeze_threshold_seconds=0.04,
            health_timeout_seconds=1,
            max_backoff_seconds=0.1,
            stop_timeout_seconds=1,
        ),
        decoder_factory=factory,
        binary_resolver=lambda _: BinaryResolution("fake-ffmpeg", "configured"),
        jitter=lambda _start, _end: 0,
    )
    engine.startup()
    try:
        engine.start(
            camera=_camera(),
            profile=_profile(),
            endpoint="rtsp://source",
            source_kind="rtsp",
        )
        _wait_until(lambda: len(decoder_instances) >= 2)
        assert engine.get("camera-1").metrics.reconnect_count >= 1
    finally:
        engine.shutdown()


def test_stationary_scene_with_advancing_source_clock_is_not_frozen() -> None:
    def factory(
        _session: object,
        config: DecoderConfig,
        _binary: BinaryResolution,
    ) -> StationaryTimedDecoder:
        return StationaryTimedDecoder(config.width, config.height)

    engine = StreamEngine(
        StreamEngineConfig(
            width=16,
            height=8,
            freeze_threshold_seconds=0.04,
            health_timeout_seconds=1,
            max_backoff_seconds=0.1,
            stop_timeout_seconds=1,
        ),
        decoder_factory=factory,
        binary_resolver=lambda _: BinaryResolution("fake-ffmpeg", "configured"),
        jitter=lambda _start, _end: 0,
    )
    engine.startup()
    try:
        engine.start(
            camera=_camera(),
            profile=_profile(),
            endpoint="rtsp://source",
            source_kind="rtsp",
        )
        _wait_until(lambda: engine.get("camera-1").metrics.frames_received >= 12)
        snapshot = engine.get("camera-1")
        assert snapshot.state == ProcessingStreamState.streaming
        assert snapshot.metrics.reconnect_count == 0
    finally:
        engine.shutdown()


def test_failed_primary_transport_rotates_to_hls_fallback() -> None:
    class HlsStableDecoder(StableDecoder):
        def open(self, endpoint: str) -> None:
            assert endpoint == "https://fallback/live.m3u8"

    def factory(session: object, config: DecoderConfig, binary: BinaryResolution) -> StableDecoder:
        del binary
        if session.source_kind == "rtsp":  # type: ignore[attr-defined]
            return FailingDecoder(config.width, config.height)
        return HlsStableDecoder(config.width, config.height)

    engine = StreamEngine(
        StreamEngineConfig(
            width=16,
            height=8,
            health_timeout_seconds=1,
            max_backoff_seconds=1,
            stop_timeout_seconds=1,
        ),
        decoder_factory=factory,
        binary_resolver=lambda _: BinaryResolution("fake-ffmpeg", "configured"),
        jitter=lambda _start, _end: 0,
    )
    engine.startup()
    try:
        engine.start(
            camera=_camera(),
            profile=_profile("rtsp-primary"),
            endpoint="rtsp://source",
            source_kind="rtsp",
            fallback_sources=[
                ProcessingSourceCandidate(
                    profile=ProcessingProfileSummary(
                        id="hls-fallback",
                        name="HTTPS HLS fallback",
                        adapter_kind="hls",
                        stream_role="playback",
                        endpoint_display="https://f***k/â€¦",
                    ),
                    endpoint="https://fallback/live.m3u8",
                    source_kind="hls",
                )
            ],
        )
        _wait_until(lambda: engine.get("camera-1").state == ProcessingStreamState.streaming)
        snapshot = engine.get("camera-1")
        assert snapshot.profile.id == "hls-fallback"
        assert snapshot.metrics.source_failover_count == 1
        assert snapshot.metrics.frames_received > 0
    finally:
        engine.shutdown()


def test_transport_specific_read_timeouts_do_not_make_rtsp_wait_for_hls() -> None:
    observed: list[tuple[str, float]] = []

    class HlsStableDecoder(StableDecoder):
        def open(self, endpoint: str) -> None:
            assert endpoint == "https://fallback/live.m3u8"

    def factory(session: object, config: DecoderConfig, binary: BinaryResolution) -> StableDecoder:
        del binary
        source_kind = session.source_kind  # type: ignore[attr-defined]
        observed.append((source_kind, config.read_timeout_seconds))
        if source_kind == "rtsp":
            return FailingDecoder(config.width, config.height)
        return HlsStableDecoder(config.width, config.height)

    engine = StreamEngine(
        StreamEngineConfig(
            width=16,
            height=8,
            startup_timeout_seconds=2,
            health_timeout_seconds=3,
            http_startup_timeout_seconds=7,
            http_health_timeout_seconds=11,
            max_backoff_seconds=1,
            stop_timeout_seconds=1,
        ),
        decoder_factory=factory,
        binary_resolver=lambda _: BinaryResolution("fake-ffmpeg", "configured"),
        jitter=lambda _start, _end: 0,
    )
    engine.startup()
    try:
        engine.start(
            camera=_camera(),
            profile=_profile("rtsp-primary"),
            endpoint="rtsp://source",
            source_kind="rtsp",
            fallback_sources=[
                ProcessingSourceCandidate(
                    profile=ProcessingProfileSummary(
                        id="hls-fallback",
                        name="HTTPS HLS fallback",
                        adapter_kind="hls",
                        stream_role="playback",
                        endpoint_display="https://f***k/…",
                    ),
                    endpoint="https://fallback/live.m3u8",
                    source_kind="hls",
                )
            ],
        )
        _wait_until(lambda: engine.get("camera-1").state == ProcessingStreamState.streaming)
        assert observed[:2] == [("rtsp", 3), ("hls", 11)]
    finally:
        engine.shutdown()


def test_live_ffmpeg_command_uses_bounded_fast_probe() -> None:
    decoder = FFmpegRawDecoder(
        binary=BinaryResolution("ffmpeg", "configured"),
        config=DecoderConfig(width=160, height=90, decode_fps=5),
        source_kind="rtsp",
    )

    command = decoder._command()

    assert command[command.index("-analyzeduration") + 1] == "500000"
    assert command[command.index("-probesize") + 1] == "32768"
    assert command[command.index("-fpsprobesize") + 1] == "0"
    assert "-rtsp_transport" not in command
    manifest = MediaRuntimeManager._source_manifest(
        "rtsp://camera/live",
        input_options={"rtsp_transport": "tcp", "timeout": "10000000"},
    )
    assert "option rtsp_transport tcp" in manifest
    assert "option timeout 10000000" in manifest


def test_slow_downstream_drops_batches_without_unbounded_growth() -> None:
    engine = _engine()
    engine.startup()
    try:
        engine.start(
            camera=_camera(),
            profile=_profile(),
            endpoint="rtsp://source",
            source_kind="rtsp",
        )
        _wait_until(lambda: engine.get("camera-1").metrics.frames_received >= 20)
        assert engine.next_batch(timeout=1) is not None
        _wait_until(
            lambda: engine.get("camera-1").metrics.dropped_due_to_backpressure > 0,
        )
        snapshot = engine.get("camera-1")
        assert engine.scheduler.queue_depth <= 2
        assert snapshot.metrics.queue_depth <= snapshot.buffer_capacity
        assert snapshot.metrics.dropped_due_to_backpressure > 0
    finally:
        engine.shutdown()


def test_ffmpeg_decoder_reads_a_real_recorded_source(tmp_path: Path) -> None:
    binary = resolve_ffmpeg_binary()
    assert binary is not None
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            binary.path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=5",
            "-t",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source),
        ],
        check=True,
        timeout=20,
    )
    decoder = FFmpegRawDecoder(
        binary=binary,
        config=DecoderConfig(width=160, height=90, decode_fps=5),
        source_kind="recorded_file",
    )
    try:
        decoder.open(str(source.resolve()))
        frame = decoder.read_frame()
        assert len(frame) == 160 * 90 * 3
        assert frame.source_pts_seconds is not None
    finally:
        decoder.close()


def test_unavailable_decoder_releases_credentials_and_source_immediately() -> None:
    engine = StreamEngine(
        StreamEngineConfig(width=16, height=8),
        binary_resolver=lambda _: None,
    )
    lease = CredentialLease(
        username="device-operator",
        password="must-be-cleared",
        source="test",
    )
    engine.startup()
    try:
        snapshot = engine.start(
            camera=_camera(),
            profile=_profile(),
            endpoint="rtsp://device-operator:must-be-cleared@10.0.0.2/live",
            source_kind="rtsp",
            credential_lease=lease,
        )
        assert snapshot.state == ProcessingStreamState.failed
        assert lease.username == ""
        assert lease.password == ""
        internal = next(iter(engine._sessions.values()))
        assert internal.endpoint == ""
        assert "must-be-cleared" not in repr(internal)
    finally:
        engine.shutdown()
