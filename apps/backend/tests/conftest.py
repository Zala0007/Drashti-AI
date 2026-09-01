from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app


@pytest.fixture()
def db_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def client(db_session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        auto_create_schema=False,
        cors_origins=("http://testserver",),
    )
    application = create_app(settings=settings, initialize_database=False)

    def override_db() -> Generator[Session, None, None]:
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_db] = override_db
    with TestClient(application, raise_server_exceptions=True) as test_client:
        yield test_client


@pytest.fixture()
def department(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/departments",
        json={
            "code": "home",
            "name": "Home Department",
            "description": "Public safety cameras",
        },
        headers={"X-Actor-ID": "test-admin"},
    )
    assert response.status_code == 201
    return response.json()


def make_camera_payload(department_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "camera_code": "ahm-cam-001",
        "camera_name": "Ashram Road Junction",
        "department_id": department_id,
        "district": "Ahmedabad",
        "city": "Ahmedabad",
        "location_description": "Ashram Road near Income Tax Circle",
        "latitude": 23.0385,
        "longitude": 72.5706,
        "camera_type": "anpr",
        "status": "active",
        "health": "unknown",
        "connectivity_type": "fiber",
        "stream_protocol": "rtsp",
        "vendor": "Generic ONVIF",
        "vms": "Department VMS A",
        "stream_reference": "connection-profile:home/ahm-cam-001-main",
        "credential_reference": "vault-ref:cctv/home/ahm-cam-001",
        "ai_capabilities": ["ANPR", "Vehicle_Detection", "anpr"],
        "tags": ["Junction", "Traffic"],
        "storage_details": {"retention_days": 15, "tier": "departmental"},
        "installation_date": "2025-01-15",
    }
    payload.update(overrides)
    return payload
