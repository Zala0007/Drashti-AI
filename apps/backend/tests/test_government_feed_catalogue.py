from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.session import get_db
from app.federation.network import NetworkTarget
from app.federation.security import EndpointCipher
from app.main import create_app
from app.models import Camera, ConnectionProfile
from app.services.government_feeds import (
    GovernmentFeedCatalogueClient,
    _CatalogueCamera,
)
from app.services.streams import StreamProcessingService


@pytest.fixture()
def government_client(
    db_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, str], None, None]:
    encryption_key = Fernet.generate_key().decode("ascii")
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        auto_create_schema=False,
        federation_encryption_key=encryption_key,
        federation_encryption_key_id="government-feed-test-v1",
        government_feed_catalogue_url="https://catalogue.example.gov/api/ingest",
    )
    application = create_app(settings=settings, initialize_database=False)

    def override_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db

    entries = [
        _CatalogueCamera.model_validate(
            {
                "id": "1",
                "number": 1,
                "name": "Camera 1",
                "location": "01 Paldi Circle",
                "codec": "h264",
                "live": True,
                "width": 1920,
                "height": 1080,
                "fps": 12.5,
                "bitrate_kbps": 900,
                "rtsp_url": "rtsp://catalogue.example.gov:8554/stream/1",
                "hls_live_url": "/live/stream/1/index.m3u8",
            }
        ),
        _CatalogueCamera.model_validate(
            {
                "id": "2",
                "number": 2,
                "name": "Camera 2",
                "location": "02 bilimora",
                "codec": "hevc",
                "live": False,
                "width": 1280,
                "height": 960,
                "fps": 25,
                "bitrate_kbps": 1100,
                "rtsp_url": "rtsp://catalogue.example.gov:8554/stream/2",
                "hls_live_url": "/live/stream/2/index.m3u8",
            }
        ),
    ]
    monkeypatch.setattr(
        GovernmentFeedCatalogueClient,
        "fetch",
        lambda self: (datetime(2026, 8, 27, 10, 0, tzinfo=UTC), entries),
    )

    def allow_public_target(self: Any, endpoint: str, **kwargs: Any) -> NetworkTarget:
        parsed = urlsplit(endpoint)
        return NetworkTarget(
            parsed.scheme,
            parsed.hostname or "catalogue.example.gov",
            parsed.port or (443 if parsed.scheme == "https" else 554),
            ("8.8.8.8",),
        )

    monkeypatch.setattr(
        "app.federation.network.NetworkPolicy.validate_network_endpoint",
        allow_public_target,
    )
    with TestClient(application, raise_server_exceptions=True) as client:
        yield client, encryption_key


def test_catalogue_sync_is_dynamic_encrypted_and_idempotent(
    government_client: tuple[TestClient, str],
    db_session_factory: sessionmaker[Session],
) -> None:
    client, encryption_key = government_client
    discovered = client.get("/api/v1/federation/catalogues/government-feeds")
    assert discovered.status_code == 200
    assert discovered.json()["total"] == 2
    assert discovered.json()["live"] == 1
    assert {item["sync_state"] for item in discovered.json()["items"]} == {"new"}
    assert "rtsp://" not in discovered.text
    assert "m3u8" not in discovered.text

    response = client.post(
        "/api/v1/federation/catalogues/government-feeds/sync",
        json={"include_offline": True, "create_hls_fallback": True},
        headers={"X-Actor-ID": "evaluation-admin"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cameras_created"] == 2
    assert body["connections_created"] == 4
    assert body["provisional_geospatial_records"] == 2
    assert {item["sync_state"] for item in body["items"]} == {"onboarded"}
    assert "rtsp://" not in response.text
    assert "m3u8" not in response.text

    replay = client.post(
        "/api/v1/federation/catalogues/government-feeds/sync",
        json={"include_offline": True, "create_hls_fallback": True},
    )
    assert replay.status_code == 200
    assert replay.json()["cameras_unchanged"] == 2
    assert replay.json()["connections_unchanged"] == 4

    with db_session_factory() as session:
        cameras = list(session.scalars(select(Camera).order_by(Camera.external_id)))
        profiles = list(session.scalars(select(ConnectionProfile).order_by(ConnectionProfile.id)))
        assert len(cameras) == 2
        assert len(profiles) == 4
        assert cameras[0].district == "Ahmedabad"
        assert cameras[1].city == "Bilimora"
        assert all(camera.installation_metadata["coordinates_provisional"] for camera in cameras)
        cipher = EndpointCipher(encryption_key, key_id="government-feed-test-v1")
        endpoints = {cipher.decrypt(profile.endpoint_ciphertext) for profile in profiles}
        assert "rtsp://catalogue.example.gov:8554/stream/1" in endpoints
        assert "https://catalogue.example.gov/live/stream/2/index.m3u8" in endpoints
        assert all("catalogue.example.gov" not in profile.endpoint_display for profile in profiles)


def test_catalogue_sync_rejects_cross_provider_stream_targets(
    government_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = government_client
    poisoned = _CatalogueCamera.model_validate(
        {
            "id": "9",
            "number": 9,
            "name": "Camera 9",
            "location": "Untrusted redirect",
            "live": True,
            "rtsp_url": "rtsp://different.example.net:8554/stream/9",
            "hls_live_url": "/live/stream/9/index.m3u8",
        }
    )
    monkeypatch.setattr(
        GovernmentFeedCatalogueClient,
        "fetch",
        lambda self: (datetime.now(UTC), [poisoned]),
    )
    response = client.post(
        "/api/v1/federation/catalogues/government-feeds/sync",
        json={},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "GOVERNMENT_FEED_CATALOGUE_INVALID"
    assert "different.example.net" not in response.text


def test_explicit_transport_preference_does_not_rotate_to_another_protocol(
    government_client: tuple[TestClient, str],
    db_session_factory: sessionmaker[Session],
) -> None:
    client, _ = government_client
    response = client.post(
        "/api/v1/federation/catalogues/government-feeds/sync",
        json={"include_offline": True, "create_hls_fallback": True},
    )
    assert response.status_code == 200

    with db_session_factory() as session:
        camera = session.scalar(select(Camera).where(Camera.external_id == "1"))
        assert camera is not None
        service = StreamProcessingService(
            session,
            engine=None,  # type: ignore[arg-type]
            source_resolver=None,  # type: ignore[arg-type]
            actor_id="test-operator",
            request_id=None,
        )

        adaptive = service._profiles(camera.id, None)
        hls_only = service._profiles(camera.id, None, "hls")
        rtsp_only = service._profiles(camera.id, None, "rtsp")

        assert [profile.adapter_kind for profile in adaptive] == ["rtsp", "hls"]
        assert [profile.adapter_kind for profile in hls_only] == ["hls"]
        assert [profile.adapter_kind for profile in rtsp_only] == ["rtsp"]
