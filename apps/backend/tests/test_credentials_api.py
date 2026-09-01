from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest
from conftest import make_camera_payload
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.session import get_db
from app.main import create_app
from app.models import AuditLog, CredentialProfile


@pytest.fixture()
def credential_client(
    db_session_factory: sessionmaker[Session], tmp_path: Path
) -> Generator[TestClient, None, None]:
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        auto_create_schema=False,
        cors_origins=("http://testserver",),
        federation_encryption_key=Fernet.generate_key().decode("ascii"),
        federation_encryption_key_id="credential-test-v1",
        federation_media_root=str(tmp_path / "media"),
        federation_runtime_root=str(tmp_path / "runtime"),
    )
    application = create_app(settings=settings, initialize_database=False)

    def override_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application, raise_server_exceptions=True) as client:
        yield client


def _department(client: TestClient, *, code: str = "credential-home") -> dict[str, str]:
    response = client.post(
        "/api/v1/departments",
        json={"code": code, "name": f"Department {code}"},
    )
    assert response.status_code == 201
    return response.json()


def test_credentials_are_write_only_encrypted_scoped_and_audited(
    credential_client: TestClient,
    db_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    department = _department(credential_client)
    username = "operator-canary"
    password = "high-entropy-password-canary"
    caplog.clear()
    created = credential_client.post(
        "/api/v1/federation/credentials",
        json={
            "department_id": department["id"],
            "name": "District camera service account",
            "username": username,
            "password": password,
            "enabled": True,
        },
        headers={"X-Actor-ID": "credential-admin"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    serialized = created.text
    assert body["reference"] == f"credential-profile:{body['id']}"
    assert body["department"]["id"] == department["id"]
    assert body["has_username"] is True
    assert body["has_secret"] is True
    for protected in (username, password, "username_ciphertext", "secret_ciphertext"):
        assert protected not in serialized
        assert protected not in caplog.text

    listed = credential_client.get(
        f"/api/v1/federation/credentials?department_id={department['id']}"
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert username not in listed.text and password not in listed.text

    with db_session_factory() as session:
        profile = session.get(CredentialProfile, body["id"])
        assert profile is not None
        assert profile.username_ciphertext != username
        assert profile.secret_ciphertext != password
        audit = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.resource_type == "credential_profile",
                    AuditLog.resource_id == body["id"],
                )
            )
        )
    audit_json = json.dumps([entry.changes for entry in audit])
    assert {entry.action for entry in audit} == {"credential.created"}
    assert username not in audit_json and password not in audit_json

    rotated_password = "rotated-secret-canary"
    updated = credential_client.patch(
        f"/api/v1/federation/credentials/{body['id']}",
        json={"password": rotated_password},
    )
    assert updated.status_code == 200
    assert rotated_password not in updated.text
    audit_response = credential_client.get(f"/api/v1/federation/credentials/{body['id']}/audit")
    assert audit_response.status_code == 200
    assert audit_response.json()["total"] == 2
    assert rotated_password not in audit_response.text


def test_credential_duplicate_validation_and_missing_encryption_fail_closed(
    credential_client: TestClient,
    client: TestClient,
) -> None:
    department = _department(credential_client, code="credential-transport")
    payload = {
        "department_id": department["id"],
        "name": "Camera account",
        "username": "operator",
        "password": "secret",
    }
    first = credential_client.post("/api/v1/federation/credentials", json=payload)
    assert first.status_code == 201
    duplicate = credential_client.post("/api/v1/federation/credentials", json=payload)
    assert duplicate.status_code == 409
    invalid = credential_client.patch(
        f"/api/v1/federation/credentials/{first.json()['id']}",
        json={"password": "line\nbreak"},
    )
    assert invalid.status_code == 400

    no_key_department = client.post(
        "/api/v1/departments", json={"code": "no-key", "name": "No Key Department"}
    ).json()
    no_key = client.post(
        "/api/v1/federation/credentials",
        json={**payload, "department_id": no_key_department["id"]},
    )
    assert no_key.status_code == 503
    assert "secret" not in no_key.text


def test_credential_schema_contains_only_ciphertext_columns(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        columns = {
            column["name"]
            for column in inspect(session.get_bind()).get_columns("credential_profiles")
        }
    assert {"username_ciphertext", "secret_ciphertext", "encryption_key_id"} <= columns
    assert "username" not in columns
    assert "password" not in columns
    assert "secret" not in columns


def test_connection_rejects_cross_department_credential_reference(
    credential_client: TestClient,
) -> None:
    owner = _department(credential_client, code="credential-owner")
    other = _department(credential_client, code="credential-other")
    credential = credential_client.post(
        "/api/v1/federation/credentials",
        json={
            "department_id": owner["id"],
            "name": "Owner camera account",
            "username": "owner-user",
            "password": "owner-secret",
        },
    ).json()
    camera = credential_client.post(
        "/api/v1/cameras",
        json=make_camera_payload(
            other["id"],
            camera_code="cross-dept-camera",
            camera_name="Cross department camera",
            stream_reference=None,
            credential_reference=None,
        ),
    ).json()
    response = credential_client.post(
        "/api/v1/federation/connections",
        json={
            "camera_id": camera["id"],
            "name": "Cross department source",
            "adapter_kind": "rtsp",
            "endpoint": "rtsp://8.8.8.8/live",
            "credential_reference": credential["reference"],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CREDENTIAL_PROFILE_SCOPE_MISMATCH"
    assert "owner-user" not in response.text and "owner-secret" not in response.text


def test_openapi_separates_write_only_secret_input_from_safe_read_model(
    credential_client: TestClient,
) -> None:
    schemas = credential_client.get("/openapi.json").json()["components"]["schemas"]
    read_fields = schemas["CredentialProfileRead"]["properties"]
    assert "username" not in read_fields
    assert "password" not in read_fields
    assert "username_ciphertext" not in read_fields
    assert "secret_ciphertext" not in read_fields
    create_fields = schemas["CredentialProfileCreate"]["properties"]
    assert create_fields["username"].get("writeOnly") is True
    assert create_fields["password"].get("writeOnly") is True
