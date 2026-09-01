from __future__ import annotations

import io
import json
import subprocess
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from conftest import make_camera_payload
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.session import get_db
from app.errors import NotFoundError
from app.main import create_app
from app.media.binary import BinaryResolution, resolve_ffmpeg_binary
from app.media.runtime import (
    MediaRuntimeManager,
    RuntimeConfig,
    _default_process_factory,
)
from app.media.types import RuntimeCameraSummary, RuntimeProfileSummary
from app.models import AuditLog


class FakeProcess:
    _next_pid = 40_000

    def __init__(self, *, stdout: str = "", stderr: str = "", exit_code: int | None = None) -> None:
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self.stdin = CapturingInput()
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self._exit_code = exit_code

    def poll(self) -> int | None:
        return self._exit_code

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self._exit_code is None:
            self._exit_code = 0
        return self._exit_code

    def terminate(self) -> None:
        self._exit_code = 0

    def kill(self) -> None:
        self._exit_code = -9

    def send_signal(self, sig: int) -> None:
        del sig
        self._exit_code = 0


class CapturingInput(io.StringIO):
    closed_value = ""

    def close(self) -> None:
        self.closed_value = self.getvalue()
        super().close()


def _safe_terminator(process: FakeProcess, *, timeout_seconds: float) -> None:
    del timeout_seconds
    process.terminate()


class PlaylistProcessFactory:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, arguments: list[str]) -> FakeProcess:
        self.commands.append(list(arguments))
        segment_pattern = Path(arguments[arguments.index("-hls_segment_filename") + 1])
        segment_path = Path(str(segment_pattern).replace("%06d", "000001"))
        playlist_path = Path(arguments[-1])
        segment_path.write_bytes(b"safe-mpeg-ts-payload")
        playlist_path.write_text(
            "#EXTM3U\n"
            "#EXT-X-VERSION:6\n"
            "#EXT-X-TARGETDURATION:2\n"
            "#EXT-X-MEDIA-SEQUENCE:0\n"
            "#EXT-X-INDEPENDENT-SEGMENTS\n"
            "#EXTINF:2.000000,\n"
            f"{segment_path.name}\n",
            encoding="utf-8",
        )
        process = FakeProcess(
            stdout="frame=24\nfps=12.5\nout_time_ms=2000000\nprogress=continue\n",
            stderr="",
        )
        self.processes.append(process)
        return process


def _wait_for_state(
    client: TestClient, session_id: str, expected: set[str], timeout: float = 3.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/federation/runtime/sessions/{session_id}")
        assert response.status_code == 200
        latest = response.json()
        if latest["state"] in expected:
            return latest
        time.sleep(0.05)
    pytest.fail(f"runtime state did not reach {sorted(expected)}; latest={latest}")


@pytest.fixture()
def runtime_client(
    db_session_factory: sessionmaker[Session], tmp_path: Path
) -> Generator[tuple[TestClient, MediaRuntimeManager, PlaylistProcessFactory, Path], None, None]:
    media_root = tmp_path / "media"
    runtime_root = tmp_path / "runtime"
    media_root.mkdir()
    process_factory = PlaylistProcessFactory()
    manager = MediaRuntimeManager(
        RuntimeConfig(
            runtime_root=str(runtime_root),
            configured_binary="fake-ffmpeg",
            segment_duration_seconds=2,
            playlist_window=6,
            watchdog_seconds=2.0,
            max_backoff_seconds=1.0,
            max_restarts=2,
            stop_timeout_seconds=0.2,
            max_active_sessions=4,
        ),
        process_factory=process_factory,
        binary_resolver=lambda configured: BinaryResolution("fake-ffmpeg", "configured"),
        process_terminator=_safe_terminator,
        jitter=lambda lower, upper: lower,
    )
    manager.startup()
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        auto_create_schema=False,
        cors_origins=("http://testserver",),
        federation_encryption_key=Fernet.generate_key().decode("ascii"),
        federation_encryption_key_id="runtime-test-key",
        federation_allowed_cidrs=("127.0.0.0/8", "10.0.0.0/8"),
        federation_media_root=str(media_root),
        federation_runtime_root=str(runtime_root),
    )
    application = create_app(settings=settings, initialize_database=False)
    application.state.media_runtime = manager

    def override_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application, raise_server_exceptions=True) as client:
        yield client, manager, process_factory, media_root
    manager.shutdown()


def _seed_connection(
    client: TestClient,
    media_root: Path,
    *,
    code: str = "runtime-cam-001",
    adapter_kind: str = "recorded_file",
    endpoint: str = "recorded://district/runtime-endpoint-canary.mp4",
    credential_reference: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    department = client.post(
        "/api/v1/departments",
        json={"code": f"dept-{code}", "name": f"Runtime Department {code}"},
    ).json()
    camera = client.post(
        "/api/v1/cameras",
        json=make_camera_payload(
            department["id"],
            camera_code=code,
            camera_name=f"Runtime Camera {code}",
            stream_reference=None,
            credential_reference=None,
        ),
    ).json()
    if adapter_kind == "recorded_file":
        source = media_root / "district" / "runtime-endpoint-canary.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"representative-recorded-media")
    response = client.post(
        "/api/v1/federation/connections",
        json={
            "camera_id": camera["id"],
            "name": f"Runtime source {code}",
            "adapter_kind": adapter_kind,
            "endpoint": endpoint,
            "stream_role": "playback" if adapter_kind == "recorded_file" else "primary",
            "credential_reference": credential_reference,
            "enabled": enabled,
        },
        headers={"X-Actor-ID": "runtime-test-admin"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_runtime_capabilities_are_honest_and_safe(
    runtime_client: tuple[TestClient, MediaRuntimeManager, PlaylistProcessFactory, Path],
) -> None:
    client, _, _, _ = runtime_client
    response = client.get("/api/v1/federation/runtime/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["binary_source"] == "configured"
    assert body["supported_adapter_kinds"] == ["rtsp", "hls", "mjpeg", "onvif", "recorded_file"]
    assert body["unsupported_adapter_kinds"] == ["vms_http"]
    assert body["credential_resolver_mode"] == "fail_closed"
    assert body["network_handoff"]["rtsp"] == "ip_pinned"
    assert body["network_handoff"]["hls_child_uris"] == "not_host_pinned"
    assert body["video_processing_mode"] == "software_h264_transcode"
    assert body["boundary"] == "process_local_poc"
    assert "path" not in body


def test_end_to_end_runtime_start_hls_assets_stop_and_restart(
    runtime_client: tuple[TestClient, MediaRuntimeManager, PlaylistProcessFactory, Path],
    db_session_factory: sessionmaker[Session],
) -> None:
    client, _, factory, media_root = runtime_client
    connection = _seed_connection(client, media_root)
    start = client.post(
        f"/api/v1/federation/connections/{connection['id']}/runtime/start",
        headers={"X-Actor-ID": "operator-7"},
    )
    assert start.status_code == 202
    started = start.json()
    serialized = json.dumps(started)
    assert "recorded://district/runtime-endpoint-canary.mp4" not in serialized
    assert "runtime-endpoint-canary.mp4" not in serialized
    assert "endpoint_ciphertext" not in serialized
    assert started["playlist_url"] is not None
    session_id = started["id"]

    duplicate = client.post(f"/api/v1/federation/connections/{connection['id']}/runtime/start")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "RUNTIME_SESSION_ACTIVE"

    live = _wait_for_state(client, session_id, {"live"})
    assert live["metrics"] == {
        "frame": 24,
        "fps": 12.5,
        "out_time_ms": 2000,
        "progress_at": live["metrics"]["progress_at"],
    }
    assert live["metrics"]["progress_at"] is not None
    sessions = client.get("/api/v1/federation/runtime/sessions").json()
    assert sessions["total"] == 1
    assert sessions["items"][0]["id"] == session_id

    first_command = factory.commands[0]
    assert first_command[0] == "fake-ffmpeg"
    assert first_command[first_command.index("-protocol_whitelist") + 1] == "file,pipe"
    assert "-nostdin" in first_command
    assert (
        "delete_segments+temp_file+independent_segments+program_date_time+omit_endlist"
        in first_command
    )
    assert not any("vault-ref:" in argument for argument in first_command)
    assert not any("runtime-endpoint-canary" in argument for argument in first_command)
    assert "runtime-endpoint-canary.mp4" in factory.processes[0].stdin.closed_value

    playlist = client.get(live["playlist_url"])
    assert playlist.status_code == 200
    assert playlist.headers["cache-control"] == "private, no-store"
    assert playlist.headers["x-content-type-options"] == "nosniff"
    assert "segments/segment_g1_000001.ts" in playlist.text
    assert str(media_root) not in playlist.text
    segment_url = f"/api/v1/federation/runtime/sessions/{session_id}/segments/segment_g1_000001.ts"
    segment = client.get(segment_url)
    assert segment.status_code == 200
    assert segment.content == b"safe-mpeg-ts-payload"
    assert segment.headers["cache-control"] == "private, no-store"

    stopped_response = client.post(
        f"/api/v1/federation/runtime/sessions/{session_id}/stop",
        headers={"X-Actor-ID": "operator-7"},
    )
    assert stopped_response.status_code == 200
    stopped = stopped_response.json()
    assert stopped["state"] == "stopped"
    assert stopped["playlist_url"] is None
    assert client.get(live["playlist_url"]).status_code == 409
    assert client.get(segment_url).status_code == 404

    restarted_response = client.post(f"/api/v1/federation/runtime/sessions/{session_id}/restart")
    assert restarted_response.status_code == 202
    restarted = _wait_for_state(client, session_id, {"live"})
    assert restarted["restart_count"] >= 1
    new_playlist = client.get(restarted["playlist_url"])
    assert "segments/segment_g2_000001.ts" in new_playlist.text
    assert client.get(segment_url).status_code == 404

    with db_session_factory() as session:
        audit = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.resource_type == "connection_profile",
                    AuditLog.resource_id == connection["id"],
                    AuditLog.source == "runtime",
                )
            )
        )
    audit_serialized = json.dumps([item.changes for item in audit])
    assert {item.action for item in audit} >= {
        "runtime.started",
        "runtime.stopped",
        "runtime.restarted",
    }
    assert "runtime-endpoint-canary" not in audit_serialized


def test_unsupported_adapter_and_credential_profiles_fail_closed(
    runtime_client: tuple[TestClient, MediaRuntimeManager, PlaylistProcessFactory, Path],
) -> None:
    client, _, factory, media_root = runtime_client
    unsupported = _seed_connection(
        client,
        media_root,
        code="runtime-onvif",
        adapter_kind="onvif",
        endpoint="http://8.8.8.8/onvif/device_service",
    )
    unsupported_start = client.post(
        f"/api/v1/federation/connections/{unsupported['id']}/runtime/start"
    )
    assert unsupported_start.status_code == 202
    assert unsupported_start.json()["state"] == "unavailable"
    assert unsupported_start.json()["last_error_code"] == "RUNTIME_ONVIF_CREDENTIAL_REQUIRED"
    assert unsupported_start.json()["playlist_url"] is None

    credential_canary = "vault-ref:drishti/runtime/do-not-expose-canary"
    protected = _seed_connection(
        client,
        media_root,
        code="runtime-protected",
        credential_reference=credential_canary,
    )
    protected_start = client.post(f"/api/v1/federation/connections/{protected['id']}/runtime/start")
    assert protected_start.status_code == 202
    protected_body = protected_start.json()
    assert protected_body["state"] == "unavailable"
    assert protected_body["last_error_code"] == "RUNTIME_CREDENTIAL_RESOLVER_UNAVAILABLE"
    assert credential_canary not in protected_start.text
    assert "do-not-expose-canary" not in protected_start.text
    assert factory.commands == []


def test_managed_credential_profile_starts_authenticated_rtsp_without_argv_secret(
    runtime_client: tuple[TestClient, MediaRuntimeManager, PlaylistProcessFactory, Path],
    db_session_factory: sessionmaker[Session],
) -> None:
    client, _, factory, _ = runtime_client
    department = client.post(
        "/api/v1/departments",
        json={"code": "managed-runtime", "name": "Managed Runtime Department"},
    ).json()
    camera = client.post(
        "/api/v1/cameras",
        json=make_camera_payload(
            department["id"],
            camera_code="managed-runtime-camera",
            camera_name="Managed Runtime Camera",
            stream_reference=None,
            credential_reference=None,
        ),
    ).json()
    username = "managed-user-canary"
    password = "managed-password-canary"
    credential = client.post(
        "/api/v1/federation/credentials",
        json={
            "department_id": department["id"],
            "name": "Managed camera identity",
            "username": username,
            "password": password,
        },
    ).json()
    connection = client.post(
        "/api/v1/federation/connections",
        json={
            "camera_id": camera["id"],
            "name": "Authenticated RTSP source",
            "adapter_kind": "rtsp",
            "endpoint": "rtsp://8.8.8.8/live",
            "credential_reference": credential["reference"],
        },
    ).json()
    start = client.post(f"/api/v1/federation/connections/{connection['id']}/runtime/start")
    assert start.status_code == 202
    session = _wait_for_state(client, start.json()["id"], {"live"})
    assert session["state"] == "live"
    command_text = " ".join(factory.commands[-1])
    assert username not in command_text
    assert password not in command_text
    manifest = factory.processes[-1].stdin.closed_value
    assert "pipe:0" in command_text
    assert username in manifest and password in manifest
    assert username not in start.text and password not in start.text
    with db_session_factory() as session_db:
        credential_audit = list(
            session_db.scalars(
                select(AuditLog).where(
                    AuditLog.resource_type == "credential_profile",
                    AuditLog.resource_id == credential["id"],
                )
            )
        )
    assert {entry.action for entry in credential_audit} >= {
        "credential.created",
        "credential.used",
    }
    assert username not in json.dumps([entry.changes for entry in credential_audit])
    assert password not in json.dumps([entry.changes for entry in credential_audit])
    client.post(f"/api/v1/federation/runtime/sessions/{session['id']}/stop")


def test_disabled_missing_capacity_and_binary_unavailable_boundaries(
    runtime_client: tuple[TestClient, MediaRuntimeManager, PlaylistProcessFactory, Path],
    tmp_path: Path,
) -> None:
    client, _, _, media_root = runtime_client
    disabled = _seed_connection(client, media_root, code="runtime-disabled", enabled=False)
    disabled_start = client.post(f"/api/v1/federation/connections/{disabled['id']}/runtime/start")
    assert disabled_start.status_code == 409
    missing = client.post(
        "/api/v1/federation/connections/00000000-0000-0000-0000-000000000001/runtime/start"
    )
    assert missing.status_code == 404

    manager = MediaRuntimeManager(
        RuntimeConfig(runtime_root=str(tmp_path / "unavailable-runtime")),
        binary_resolver=lambda configured: None,
    )
    manager.startup()
    camera, profile = _summaries()
    snapshot = manager.start(
        connection_id=profile.id,
        endpoint=str(tmp_path / "source.mp4"),
        camera=camera,
        profile=profile,
    )
    assert snapshot.state == "unavailable"
    assert snapshot.playlist_url is None
    assert snapshot.last_error_code == "FFMPEG_UNAVAILABLE"
    assert manager.capabilities()["available"] is False


def _summaries() -> tuple[RuntimeCameraSummary, RuntimeProfileSummary]:
    return (
        RuntimeCameraSummary(
            id="00000000-0000-0000-0000-000000000101",
            camera_code="TEST-CAM",
            camera_name="Test camera",
            department_name="Test department",
            district="Ahmedabad",
            city="Ahmedabad",
        ),
        RuntimeProfileSummary(
            id="00000000-0000-0000-0000-000000000201",
            name="Test stream",
            adapter_kind="recorded_file",
            stream_role="playback",
            endpoint_display="recorded://…/….mp4",
        ),
    )


def test_watchdog_bounded_stderr_backoff_and_restart_limit(tmp_path: Path) -> None:
    raw_endpoint = str(tmp_path / "sensitive-runtime-source.mp4")
    processes: list[FakeProcess] = []
    jitter_caps: list[float] = []

    def process_factory(arguments: list[str]) -> FakeProcess:
        process = FakeProcess(stderr=f"opening {raw_endpoint} failed\n" * 120)
        processes.append(process)
        return process

    def jitter(lower: float, upper: float) -> float:
        jitter_caps.append(upper)
        return lower

    manager = MediaRuntimeManager(
        RuntimeConfig(
            runtime_root=str(tmp_path / "watchdog"),
            configured_binary="fake-ffmpeg",
            watchdog_seconds=0.05,
            max_backoff_seconds=4.0,
            max_restarts=1,
            stop_timeout_seconds=0.05,
        ),
        process_factory=process_factory,
        binary_resolver=lambda configured: BinaryResolution("fake-ffmpeg", "configured"),
        process_terminator=_safe_terminator,
        jitter=jitter,
    )
    manager.startup()
    camera, profile = _summaries()
    snapshot = manager.start(
        connection_id=profile.id,
        endpoint=raw_endpoint,
        camera=camera,
        profile=profile,
    )
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        snapshot = manager.get(snapshot.id)
        if snapshot.state == "failed":
            break
        time.sleep(0.05)
    assert snapshot.state == "failed"
    assert snapshot.restart_count == 2
    assert jitter_caps == [1.0]
    internal = manager._sessions[snapshot.id]
    assert len(internal.stderr_tail) <= 80
    assert raw_endpoint not in "\n".join(internal.stderr_tail)
    assert "[REDACTED_ENDPOINT]" in "\n".join(internal.stderr_tail)
    assert raw_endpoint not in json.dumps(snapshot, default=str)


def test_playlist_directive_allowlist_and_asset_validation(
    runtime_client: tuple[TestClient, MediaRuntimeManager, PlaylistProcessFactory, Path],
) -> None:
    client, manager, _, media_root = runtime_client
    connection = _seed_connection(client, media_root, code="runtime-playlist-security")
    started = client.post(f"/api/v1/federation/connections/{connection['id']}/runtime/start").json()
    live = _wait_for_state(client, started["id"], {"live"})
    internal = manager._sessions[started["id"]]
    playlist_path = Path(internal.session_directory) / "playlist.m3u8"
    playlist_path.write_text(
        "#EXTM3U\n"
        '#EXT-X-KEY:METHOD=AES-128,URI="https://metadata.invalid/key"\n'
        "#EXTINF:2,\nsegment_g1_000001.ts\n",
        encoding="utf-8",
    )
    rejected = client.get(live["playlist_url"])
    assert rejected.status_code == 503
    assert "metadata.invalid" not in rejected.text
    with pytest.raises(NotFoundError):
        manager.open_segment(started["id"], "../playlist.m3u8")
    assert (
        client.get(
            f"/api/v1/federation/runtime/sessions/{started['id']}/segments/not-a-segment.ts"
        ).status_code
        == 404
    )


def test_default_process_factory_scrubs_environment_and_never_uses_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_popen(arguments: list[str], **kwargs: Any) -> FakeProcess:
        captured["arguments"] = arguments
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setenv("DATABASE_URL", "postgresql://sensitive-database-canary")
    monkeypatch.setenv("FEDERATION_ENCRYPTION_KEY", "sensitive-key-canary")
    monkeypatch.setenv("THIRD_PARTY_TOKEN", "sensitive-token-canary")
    monkeypatch.setattr("app.media.runtime.subprocess.Popen", fake_popen)
    _default_process_factory(["ffmpeg", "-version"])
    assert captured["shell"] is False
    assert captured["stdin"] is subprocess.PIPE
    environment = captured["env"]
    assert "DATABASE_URL" not in environment
    assert "FEDERATION_ENCRYPTION_KEY" not in environment
    assert "THIRD_PARTY_TOKEN" not in environment
    assert "sensitive" not in json.dumps(environment)


def test_runtime_root_rejects_filesystem_root() -> None:
    filesystem_root = Path.cwd().anchor
    with pytest.raises(ValueError, match="must not be a filesystem root"):
        MediaRuntimeManager(RuntimeConfig(runtime_root=filesystem_root))


def test_actual_generated_media_pipeline_when_ffmpeg_available(tmp_path: Path) -> None:
    resolution = resolve_ffmpeg_binary()
    if resolution is None:
        pytest.skip("FFmpeg binary is not available")
    source = tmp_path / "generated-source.mp4"
    generated = subprocess.run(
        [
            resolution.path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=10",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
        shell=False,
    )
    if generated.returncode != 0:
        pytest.skip("Available FFmpeg build cannot generate the test fixture")
    manager = MediaRuntimeManager(
        RuntimeConfig(
            runtime_root=str(tmp_path / "actual-runtime"),
            configured_binary=resolution.path,
            segment_duration_seconds=1,
            watchdog_seconds=10,
            max_restarts=0,
        )
    )
    manager.startup()
    camera, profile = _summaries()
    snapshot = manager.start(
        connection_id=profile.id,
        endpoint=str(source),
        camera=camera,
        profile=profile,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        snapshot = manager.get(snapshot.id)
        if snapshot.state == "live":
            break
        if snapshot.state in {"failed", "unavailable"}:
            break
        time.sleep(0.2)
    try:
        assert snapshot.state == "live"
        assert "#EXTM3U" in manager.playlist_text(snapshot.id)
    finally:
        manager.shutdown()
