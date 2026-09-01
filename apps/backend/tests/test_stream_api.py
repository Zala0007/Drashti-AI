from __future__ import annotations

import inspect
import json
import subprocess
import time
from collections.abc import Generator
from pathlib import Path
from uuid import UUID

import pytest
from conftest import make_camera_payload
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.streams import stream_preview
from app.config import Settings
from app.db.session import get_db
from app.main import create_app
from app.media.binary import resolve_ffmpeg_binary


def test_stream_capabilities_and_empty_health_metrics(client: TestClient) -> None:
    capabilities = client.get("/api/v1/streams/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["latest_frame_semantics"] is True
    assert capabilities.json()["batch_dispatch"] is True
    assert "hardware_decode_reason" in capabilities.json()

    analytics_capabilities = client.get("/api/v1/streams/analytics/capabilities")
    assert analytics_capabilities.status_code == 200
    assert analytics_capabilities.json()["status"] == "disabled"
    assert analytics_capabilities.json()["consumer_attached"] is False

    analytics = client.get("/api/v1/streams/analytics")
    assert analytics.status_code == 200
    assert analytics.json() == {"items": [], "total": 0}

    streams = client.get("/api/v1/streams")
    assert streams.status_code == 200
    assert streams.json() == {"items": [], "total": 0}

    metrics = client.get("/api/v1/streams/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["active_streams"] == 0
    assert metrics.json()["scheduler_queue_depth"] == 0
    assert metrics.json()["ai_consumer_attached"] is False


def test_stream_read_paths_do_not_acquire_database_sessions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_db() -> Generator[Session, None, None]:
        raise AssertionError("read-only stream delivery must not acquire a DB session")
        yield

    application = client.app
    application.dependency_overrides[get_db] = forbidden_db
    snapshot_timeouts: list[float] = []

    def latest_jpeg(*_args: object, **kwargs: float) -> tuple[int, bytes]:
        snapshot_timeouts.append(kwargs["timeout"])
        return 42, b"\xff\xd8preview\xff\xd9"

    monkeypatch.setattr(application.state.stream_engine, "latest_jpeg", latest_jpeg)
    try:
        assert client.get("/api/v1/streams/capabilities").status_code == 200
        assert client.get("/api/v1/streams").status_code == 200
        assert client.get("/api/v1/streams/metrics").status_code == 200
        snapshot = client.get(
            "/api/v1/streams/00000000-0000-0000-0000-000000000042/preview.jpg"
        )
        assert snapshot.status_code == 200
        assert snapshot.headers["x-frame-number"] == "42"
        assert snapshot_timeouts == [0.0]
        preview = stream_preview(
            camera_id=UUID("00000000-0000-0000-0000-000000000042"),
            engine=application.state.stream_engine,
        )
        assert inspect.isasyncgen(preview.body_iterator)
    finally:
        application.dependency_overrides.pop(get_db, None)


def test_p03_recorded_profile_to_p04_decoder_lifecycle(
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    binary = resolve_ffmpeg_binary()
    assert binary is not None
    media_root = tmp_path / "media"
    source = media_root / "district" / "qualification.mp4"
    source.parent.mkdir(parents=True)
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
            "3",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source),
        ],
        check=True,
        timeout=20,
    )
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        auto_create_schema=False,
        cors_origins=("http://testserver",),
        federation_encryption_key=Fernet.generate_key().decode("ascii"),
        federation_media_root=str(media_root),
        stream_engine_output_width=160,
        stream_engine_output_height=90,
        stream_engine_decode_fps=5,
        stream_engine_target_fps=4,
        stream_engine_stop_timeout_seconds=1,
        stream_engine_max_active_sessions=2,
    )
    application = create_app(settings=settings, initialize_database=False)

    def override_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application, raise_server_exceptions=True) as client:
        department = client.post(
            "/api/v1/departments",
            json={"code": "stream-test", "name": "Stream Test Department"},
        ).json()
        camera = client.post(
            "/api/v1/cameras",
            json=make_camera_payload(
                department["id"],
                camera_code="p04-real-001",
                camera_name="P04 Real Decoder Test",
                stream_reference=None,
                credential_reference=None,
            ),
        ).json()
        connection = client.post(
            "/api/v1/federation/connections",
            json={
                "camera_id": camera["id"],
                "name": "Qualified playback profile",
                "adapter_kind": "recorded_file",
                "endpoint": "recorded://district/qualification.mp4",
                "stream_role": "playback",
                "enabled": True,
            },
        )
        assert connection.status_code == 201

        start = client.post(f"/api/v1/streams/{camera['id']}/start")
        assert start.status_code == 202, start.text
        assert "qualification.mp4" not in json.dumps(start.json())
        deadline = time.monotonic() + 5
        health = start.json()
        while time.monotonic() < deadline and health["state"] != "streaming":
            time.sleep(0.05)
            health = client.get(f"/api/v1/streams/{camera['id']}/health").json()
        assert health["state"] == "streaming"
        assert health["metrics"]["frames_received"] > 0

        jpeg = application.state.stream_engine.latest_jpeg(camera["id"], timeout=1)
        assert jpeg is not None
        assert jpeg[1].startswith(b"\xff\xd8")
        snapshot = client.get(f"/api/v1/streams/{camera['id']}/preview.jpg")
        assert snapshot.status_code == 200
        assert snapshot.headers["content-type"] == "image/jpeg"
        assert snapshot.headers["cache-control"] == "private, no-store, no-cache, must-revalidate"
        assert snapshot.headers["x-frame-number"].isdigit()
        assert snapshot.content.startswith(b"\xff\xd8")
        stop = client.post(f"/api/v1/streams/{camera['id']}/stop")
        assert stop.status_code == 200
        assert stop.json()["state"] == "stopped"
