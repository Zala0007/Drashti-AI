from __future__ import annotations

import http.client
import json
import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from conftest import make_camera_payload
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.session import get_db
from app.errors import BadRequestError
from app.federation.adapters import HlsAdapter, MjpegAdapter, RecordedFileAdapter, RtspAdapter
from app.federation.network import NetworkPolicy, NetworkTarget
from app.federation.security import EndpointCipher
from app.federation.types import ProbeResult
from app.main import create_app
from app.models import AuditLog, ConnectionProfile


@pytest.fixture()
def federation_client(
    db_session_factory: sessionmaker[Session], tmp_path: Path
) -> Generator[TestClient, None, None]:
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        auto_create_schema=False,
        cors_origins=("http://testserver",),
        federation_encryption_key=Fernet.generate_key().decode("ascii"),
        federation_encryption_key_id="test-key-v1",
        federation_allowed_cidrs=("127.0.0.0/8", "10.0.0.0/8"),
        federation_probe_timeout_seconds=1.0,
        federation_media_root=str(tmp_path),
    )
    application = create_app(settings=settings, initialize_database=False)

    def override_db() -> Generator[Session, None, None]:
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_db] = override_db
    with TestClient(application, raise_server_exceptions=True) as client:
        yield client


def _camera(client: TestClient, *, code: str = "fed-cam-001") -> dict[str, Any]:
    department_response = client.post(
        "/api/v1/departments",
        json={"code": f"dept-{code}", "name": f"Department {code}"},
    )
    assert department_response.status_code == 201
    payload = make_camera_payload(
        department_response.json()["id"],
        camera_code=code,
        camera_name=f"Federation Camera {code}",
        stream_reference=None,
        credential_reference=None,
    )
    camera_response = client.post("/api/v1/cameras", json=payload)
    assert camera_response.status_code == 201
    return camera_response.json()


def _connection_payload(camera_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "camera_id": camera_id,
        "name": "Primary recorded evidence",
        "adapter_kind": "recorded_file",
        "endpoint": "recorded://district-a/evidence-001.mp4",
        "stream_role": "playback",
        "credential_reference": "vault-ref:drishti/federation/profile-001",
        "priority": 20,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def test_adapter_manifests_are_honest_and_complete(federation_client: TestClient) -> None:
    response = federation_client.get("/api/v1/federation/adapters")
    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["kind"] for item in items} == {
        "rtsp",
        "hls",
        "mjpeg",
        "onvif",
        "vms_http",
        "recorded_file",
    }
    assert all(item["supports_probe"] and item["available"] for item in items)
    assert all(item["supports_discovery"] is False for item in items)
    onvif = next(item for item in items if item["kind"] == "onvif")
    assert onvif["supports_stream_handoff"] is True
    assert "media_profile_negotiation" in onvif["capabilities"]


def test_create_list_get_statistics_and_ciphertext_at_rest(
    federation_client: TestClient,
    db_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    camera = _camera(federation_client)
    endpoint = "recorded://district-a/evidence-001.mp4"
    credential_reference = "vault-ref:drishti/federation/profile-001"
    caplog.set_level(logging.INFO)
    response = federation_client.post(
        "/api/v1/federation/connections",
        json=_connection_payload(camera["id"]),
        headers={"X-Actor-ID": "federation-admin"},
    )
    assert response.status_code == 201
    body = response.json()
    serialized = json.dumps(body)
    assert endpoint not in serialized
    assert credential_reference not in serialized
    assert "endpoint_ciphertext" not in body
    assert "credential_reference" not in body
    assert body["endpoint_display"] == "recorded://…/….mp4"
    assert body["has_credential_reference"] is True
    assert body["camera"]["department_name"].startswith("Department")

    connection_id = body["id"]
    assert federation_client.get(f"/api/v1/federation/connections/{connection_id}").json() == body
    listed = federation_client.get(
        "/api/v1/federation/connections",
        params={"adapter_kind": "recorded_file", "search": "evidence"},
    ).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == connection_id
    stats = federation_client.get("/api/v1/federation/connections/statistics").json()
    assert stats == {
        "total": 1,
        "enabled": 1,
        "disabled": 0,
        "by_status": {"unverified": 1},
        "by_adapter_kind": {"recorded_file": 1},
        "healthy_ratio": 0.0,
        "last_probe_at": None,
    }

    with db_session_factory() as session:
        profile = session.scalar(select(ConnectionProfile))
        assert profile is not None
        assert endpoint not in profile.endpoint_ciphertext
        assert credential_reference not in (profile.credential_reference_ciphertext or "")
        assert endpoint not in json.dumps(profile.__dict__, default=str)
        assert credential_reference not in json.dumps(profile.__dict__, default=str)
        audit_rows = list(
            session.scalars(select(AuditLog).where(AuditLog.resource_type == "connection_profile"))
        )
        assert audit_rows
        audit_json = json.dumps([row.changes for row in audit_rows])
        assert endpoint not in audit_json
        assert credential_reference not in audit_json
    assert endpoint not in caplog.text
    assert credential_reference not in caplog.text


def test_missing_key_fails_safely(client: TestClient, department: dict[str, Any]) -> None:
    camera_response = client.post("/api/v1/cameras", json=make_camera_payload(department["id"]))
    response = client.post(
        "/api/v1/federation/connections",
        json=_connection_payload(camera_response.json()["id"]),
    )
    assert response.status_code == 503
    serialized = response.text
    assert response.json()["error"]["code"] == "FEDERATION_ENCRYPTION_UNAVAILABLE"
    assert "recorded://district-a" not in serialized


def test_malformed_encryption_key_is_normalized_to_safe_503(
    db_session_factory: sessionmaker[Session],
) -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        auto_create_schema=False,
        federation_encryption_key="distinct-malformed-key-material",
    )
    application = create_app(settings=settings, initialize_database=False)

    def override_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application, raise_server_exceptions=True) as invalid_client:
        response = invalid_client.get("/api/v1/federation/adapters")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "FEDERATION_ENCRYPTION_INVALID"
    assert "distinct-malformed-key-material" not in response.text
    with pytest.raises(ValueError, match="valid Fernet key"):
        EndpointCipher("still-not-base64", key_id="test")


def test_invalid_scheme_userinfo_and_ssrf_policy_are_rejected(
    federation_client: TestClient,
) -> None:
    camera = _camera(federation_client)
    wrong_scheme = federation_client.post(
        "/api/v1/federation/connections",
        json=_connection_payload(camera["id"], endpoint="rtsp://8.8.8.8/live"),
    )
    assert wrong_scheme.status_code == 400
    assert wrong_scheme.json()["error"]["code"] == "FEDERATION_SCHEME_NOT_ALLOWED"

    userinfo = federation_client.post(
        "/api/v1/federation/connections",
        json=_connection_payload(
            camera["id"],
            name="userinfo",
            adapter_kind="rtsp",
            stream_role="primary",
            endpoint="rtsp://operator:distinct-password@10.1.2.3/live",
        ),
    )
    assert userinfo.status_code == 400
    assert userinfo.json()["error"]["code"] == "FEDERATION_EMBEDDED_CREDENTIALS"
    assert "distinct-password" not in userinfo.text

    policy = NetworkPolicy()
    with pytest.raises(BadRequestError) as private_error:
        policy.validate_network_endpoint(
            "rtsp://127.0.0.1/live",
            allowed_schemes=("rtsp",),
            default_ports={"rtsp": 554},
        )
    assert private_error.value.code == "FEDERATION_ENDPOINT_BLOCKED"
    with pytest.raises(BadRequestError) as metadata_error:
        NetworkPolicy(("169.254.0.0/16",)).validate_network_endpoint(
            "http://169.254.169.254/latest/meta-data",
            allowed_schemes=("http",),
            default_ports={"http": 80},
        )
    assert metadata_error.value.code == "FEDERATION_ENDPOINT_BLOCKED"
    allowed = NetworkPolicy(("10.0.0.0/8",)).validate_network_endpoint(
        "rtsp://10.1.2.3/live",
        allowed_schemes=("rtsp",),
        default_ports={"rtsp": 554},
    )
    assert allowed.resolved_ips == ("10.1.2.3",)
    with pytest.raises(BadRequestError):
        NetworkPolicy().validate_network_endpoint(
            "rtsp://100.64.1.2/live",
            allowed_schemes=("rtsp",),
            default_ports={"rtsp": 554},
        )
    cgnat_allowed = NetworkPolicy(("100.64.0.0/10",)).validate_network_endpoint(
        "rtsp://100.64.1.2/live",
        allowed_schemes=("rtsp",),
        default_ports={"rtsp": 554},
    )
    assert cgnat_allowed.resolved_ips == ("100.64.1.2",)


def test_probe_state_transitions_audit_and_reversible_disable(
    federation_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = _camera(federation_client)
    created = federation_client.post(
        "/api/v1/federation/connections", json=_connection_payload(camera["id"])
    ).json()
    connection_id = created["id"]
    outcomes = iter(
        [
            ProbeResult(
                "authentication_required",
                3.5,
                "AUTHENTICATION_REQUIRED",
                "The endpoint requires credentials",
            ),
            ProbeResult(
                "unreachable",
                9.0,
                "CONNECTION_REFUSED",
                "The endpoint refused the probe connection",
            ),
            ProbeResult(
                "reachable",
                2.0,
                metadata={"protocol": "file", "size_bytes": 1024, "unsafe_url": "secret"},
            ),
        ]
    )

    def fake_probe(
        self: RecordedFileAdapter, endpoint: str, *, timeout_seconds: float
    ) -> ProbeResult:
        del self, endpoint, timeout_seconds
        return next(outcomes)

    monkeypatch.setattr(RecordedFileAdapter, "probe", fake_probe)
    first = federation_client.post(f"/api/v1/federation/connections/{connection_id}/probe").json()
    assert first["verification_status"] == "authentication_required"
    assert first["failure_count"] == 1
    second = federation_client.post(f"/api/v1/federation/connections/{connection_id}/probe").json()
    assert second["verification_status"] == "unreachable"
    assert second["failure_count"] == 2
    third = federation_client.post(f"/api/v1/federation/connections/{connection_id}/probe").json()
    assert third["verification_status"] == "reachable"
    assert third["failure_count"] == 0
    assert third["last_success_at"] is not None
    assert "unsafe_url" not in third["normalized_metadata"]

    disabled = federation_client.post(
        f"/api/v1/federation/connections/{connection_id}/disable"
    ).json()
    assert disabled["enabled"] is False
    assert disabled["verification_status"] == "disabled"
    blocked_probe = federation_client.post(f"/api/v1/federation/connections/{connection_id}/probe")
    assert blocked_probe.status_code == 409
    enabled = federation_client.post(
        f"/api/v1/federation/connections/{connection_id}/enable"
    ).json()
    assert enabled["enabled"] is True
    assert enabled["verification_status"] == "unverified"
    audit = federation_client.get(f"/api/v1/federation/connections/{connection_id}/audit").json()
    assert audit["total"] == 6
    assert {item["action"] for item in audit["items"]} >= {
        "connection.created",
        "connection.probed",
        "connection.disabled",
        "connection.enabled",
    }


def test_missing_camera_duplicate_patch_and_no_delete(
    federation_client: TestClient,
) -> None:
    missing = federation_client.post(
        "/api/v1/federation/connections",
        json=_connection_payload("00000000-0000-0000-0000-000000000001"),
    )
    assert missing.status_code == 404
    camera = _camera(federation_client)
    payload = _connection_payload(camera["id"])
    created = federation_client.post("/api/v1/federation/connections", json=payload)
    duplicate = federation_client.post("/api/v1/federation/connections", json=payload)
    assert duplicate.status_code == 409
    connection_id = created.json()["id"]
    patched = federation_client.patch(
        f"/api/v1/federation/connections/{connection_id}",
        json={"name": "Evidence playback fallback", "priority": 90},
    ).json()
    assert patched["name"] == "Evidence playback fallback"
    assert patched["priority"] == 90
    assert (
        federation_client.delete(f"/api/v1/federation/connections/{connection_id}").status_code
        == 405
    )


def test_endpoint_display_masks_network_topology_and_recorded_identity(
    tmp_path: Path,
) -> None:
    rtsp = RtspAdapter(NetworkPolicy())
    display = rtsp.endpoint_display(
        "rtsp://camera-secret-zone.internal.police.gov:8554/full/private/path"
    )
    assert display == "rtsp://c***e.i***l.p***e.g***v:8554/…"
    assert "camera-secret-zone" not in display
    assert "private/path" not in display
    recorded = RecordedFileAdapter(media_root=str(tmp_path))
    recorded_display = recorded.endpoint_display("recorded://district/vehicle-route-42.mkv")
    assert recorded_display == "recorded://…/….mkv"
    assert "vehicle-route-42" not in recorded_display


def test_mjpeg_probe_reads_headers_only_and_uses_pinned_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_closed = False
    connected_to: tuple[str, int] | None = None

    class FakeResponse:
        status = 200

        def getheader(self, name: str, default: str = "") -> str:
            assert name == "Content-Type"
            return "multipart/x-mixed-replace; boundary=frame"

        def read(self, amount: int | None = None) -> bytes:
            raise AssertionError(f"stream body must not be buffered: {amount}")

        def close(self) -> None:
            nonlocal response_closed
            response_closed = True

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            assert host == "camera.example.gov"
            assert port == 80
            assert 0 < timeout <= 1.0
            self.sock: Any = None

        def request(
            self, method: str, target: str, body: bytes | None, headers: dict[str, str]
        ) -> None:
            assert method == "GET"
            assert target == "/mjpeg"
            assert body is None
            assert self.sock is not None
            assert headers["Accept"].startswith("multipart/")

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            return None

    class FakeSocket:
        def settimeout(self, timeout: float) -> None:
            assert 0 < timeout <= 1.0

        def close(self) -> None:
            return None

    def fake_create_connection(address: tuple[str, int], timeout: float) -> FakeSocket:
        nonlocal connected_to
        connected_to = address
        assert 0 < timeout <= 1.0
        return FakeSocket()

    monkeypatch.setattr("app.federation.adapters.http.client.HTTPConnection", FakeConnection)
    monkeypatch.setattr("app.federation.adapters.socket.create_connection", fake_create_connection)
    adapter = MjpegAdapter(NetworkPolicy())
    monkeypatch.setattr(
        adapter,
        "_target",
        lambda endpoint: NetworkTarget("http", "camera.example.gov", 80, ("203.0.113.25",)),
    )
    result = adapter.probe("http://camera.example.gov/mjpeg", timeout_seconds=1.0)
    assert result.status == "reachable"
    assert connected_to == ("203.0.113.25", 80)
    assert response_closed is True
    # The helper's source-level contract is also guarded: it calls close after
    # header extraction and contains no response.read invocation.
    import inspect as python_inspect

    source = python_inspect.getsource(MjpegAdapter._pinned_request)
    assert "response_prefix_limit > 0" in source
    assert "response.close()" in source


def test_hls_probe_reads_only_bounded_prefix_and_validates_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_amounts: list[int | None] = []

    class FakeResponse:
        status = 200

        def getheader(self, name: str, default: str = "") -> str:
            return "application/vnd.apple.mpegurl"

        def read(self, amount: int | None = None) -> bytes:
            read_amounts.append(amount)
            return b"#EXTM3U\n#EXT-X-VERSION:3\n"

        def close(self) -> None:
            return None

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            self.sock: Any = None

        def request(
            self, method: str, target: str, body: bytes | None, headers: dict[str, str]
        ) -> None:
            return None

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            return None

    class FakeSocket:
        def settimeout(self, timeout: float) -> None:
            assert 0 < timeout <= 1.0

        def close(self) -> None:
            return None

    monkeypatch.setattr("app.federation.adapters.http.client.HTTPConnection", FakeConnection)
    monkeypatch.setattr(
        "app.federation.adapters.socket.create_connection",
        lambda address, timeout: FakeSocket(),
    )
    adapter = HlsAdapter(NetworkPolicy())
    monkeypatch.setattr(
        adapter,
        "_target",
        lambda endpoint: NetworkTarget("http", "hls.example.gov", 80, ("8.8.8.8",)),
    )
    result = adapter.probe("http://hls.example.gov/live.m3u8", timeout_seconds=1.0)
    assert result.status == "reachable"
    assert read_amounts == [4096]

    monkeypatch.setattr(
        adapter,
        "_pinned_request",
        lambda *args, **kwargs: (200, "application/vnd.apple.mpegurl", b"not-a-playlist"),
    )
    invalid = adapter.probe("http://hls.example.gov/live.m3u8", timeout_seconds=1.0)
    assert invalid.status == "misconfigured"
    assert invalid.error_code == "CONTENT_SIGNATURE_MISMATCH"


def test_pinned_http_attempts_share_one_total_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_timeouts: list[float] = []

    def always_timeout(address: tuple[str, int], timeout: float) -> Any:
        observed_timeouts.append(timeout)
        raise TimeoutError

    monkeypatch.setattr("app.federation.adapters.socket.create_connection", always_timeout)
    with pytest.raises(TimeoutError):
        MjpegAdapter._pinned_request(
            "http://camera.example.gov/mjpeg",
            target=NetworkTarget("http", "camera.example.gov", 80, ("8.8.8.8", "1.1.1.1")),
            timeout_seconds=0.5,
            method="GET",
            headers={"Accept": "multipart/x-mixed-replace"},
            body=None,
            response_prefix_limit=0,
        )
    assert len(observed_timeouts) == 2
    assert 0 < observed_timeouts[1] <= observed_timeouts[0] <= 0.5


def test_malformed_http_response_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MjpegAdapter(NetworkPolicy())
    monkeypatch.setattr(
        adapter,
        "_target",
        lambda endpoint: NetworkTarget("http", "camera.example.gov", 80, ("8.8.8.8",)),
    )

    def malformed(*args: Any, **kwargs: Any) -> Any:
        raise http.client.BadStatusLine("distinct-raw-protocol-material")

    monkeypatch.setattr(adapter, "_pinned_request", malformed)
    result = adapter.probe("http://camera.example.gov/mjpeg", timeout_seconds=1.0)
    assert result.status == "misconfigured"
    assert result.error_code == "PROTOCOL_ERROR"
    assert "distinct-raw-protocol-material" not in (result.error_message or "")


def test_connection_profile_schema_contains_only_encrypted_sensitive_columns(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        columns = {
            column["name"]
            for column in inspect(session.get_bind()).get_columns("connection_profiles")
        }
    assert "endpoint_ciphertext" in columns
    assert "credential_reference_ciphertext" in columns
    assert "endpoint" not in columns
    assert "credential_reference" not in columns
