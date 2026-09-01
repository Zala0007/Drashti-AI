from __future__ import annotations

from fastapi.testclient import TestClient

import app.services.registry as registry_service

HEADER = (
    "camera_code,camera_name,department_code,district,city,latitude,longitude,"
    "camera_type,status,health,stream_protocol,ai_capabilities,tags,installation_date\n"
)


def test_csv_import_row_errors_duplicates_and_idempotent_replay(
    client: TestClient, department: dict
) -> None:
    content = HEADER + (
        "CAM-CSV-001,Riverfront ANPR,HOME,Ahmedabad,Ahmedabad,23.0300,72.5800,"
        "anpr,active,online,rtsp,anpr|vehicle_detection,riverfront|traffic,2025-01-15\n"
        "CAM-BAD-001,Bad Coordinates,HOME,Ahmedabad,Ahmedabad,999,72.58,"
        "fixed,active,unknown,rtsp,anpr,bad,2025-01-15\n"
        "CAM-CSV-001,Duplicate Camera,HOME,Ahmedabad,Ahmedabad,23.031,72.581,"
        "anpr,active,online,rtsp,anpr,duplicate,2025-01-15\n"
    )
    response = client.post(
        "/api/v1/cameras/import?on_duplicate=skip",
        files={"file": ("cameras.csv", content.encode(), "text/csv")},
        headers={"Idempotency-Key": "registry-import-001", "X-Actor-ID": "bulk-admin"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_rows"] == 3
    assert body["created"] == 1
    assert body["skipped"] == 1
    assert body["failed"] == 1
    assert body["results"][1]["error"]["code"] == "ROW_VALIDATION_ERROR"

    replay = client.post(
        "/api/v1/cameras/import?on_duplicate=skip",
        files={"file": ("cameras.csv", content.encode(), "text/csv")},
        headers={"Idempotency-Key": "registry-import-001"},
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["import_id"] == body["import_id"]
    assert client.get("/api/v1/cameras").json()["total"] == 1

    different = HEADER + (
        "CAM-CSV-999,Different,HOME,Ahmedabad,Ahmedabad,23.0,72.5,"
        "fixed,active,online,rtsp,anpr,test,2025-01-15\n"
    )
    conflict = client.post(
        "/api/v1/cameras/import",
        files={"file": ("cameras.csv", different.encode(), "text/csv")},
        headers={"Idempotency-Key": "registry-import-001"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_csv_update_mode_and_derived_content_idempotency(
    client: TestClient, department: dict
) -> None:
    content = HEADER + (
        "CAM-CSV-002,Original Name,HOME,Ahmedabad,Ahmedabad,23.0,72.5,"
        "fixed,active,unknown,rtsp,anpr,original,2025-01-15\n"
    )
    created = client.post(
        "/api/v1/cameras/import",
        files={"file": ("cameras.csv", content.encode(), "text/csv")},
    )
    assert created.status_code == 200, created.text
    assert created.json()["created"] == 1

    replay = client.post(
        "/api/v1/cameras/import",
        files={"file": ("cameras.csv", content.encode(), "text/csv")},
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True

    updated_content = HEADER + (
        "CAM-CSV-002,Updated Name,HOME,Ahmedabad,Ahmedabad,23.01,72.51,"
        "anpr,active,online,rtsp,anpr|vehicle_detection,updated,2025-02-01\n"
    )
    updated = client.post(
        "/api/v1/cameras/import?on_duplicate=update",
        files={"file": ("cameras.csv", updated_content.encode(), "text/csv")},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["updated"] == 1
    cameras = client.get("/api/v1/cameras?search=CAM-CSV-002").json()
    assert cameras["total"] == 1
    assert cameras["items"][0]["camera_name"] == "Updated Name"
    assert cameras["items"][0]["health"] == "online"
    assert cameras["items"][0]["installation_date"] == "2025-02-01"


def test_csv_requires_columns_and_utf8(client: TestClient, department: dict) -> None:
    invalid = client.post(
        "/api/v1/cameras/import",
        files={"file": ("bad.csv", b"camera_code,name\nCAM-1,Nope\n", "text/csv")},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "MISSING_CSV_COLUMNS"

    encoding = client.post(
        "/api/v1/cameras/import",
        files={"file": ("bad.csv", b"\xff\xfe\x00", "text/csv")},
    )
    assert encoding.status_code == 400
    assert encoding.json()["error"]["code"] == "INVALID_CSV_ENCODING"


def test_csv_update_does_not_apply_defaults_for_omitted_optional_fields(
    client: TestClient, department: dict
) -> None:
    create = client.post(
        "/api/v1/cameras",
        json={
            "camera_code": "CAM-SPARSE-001",
            "camera_name": "Before Sparse Update",
            "department_id": department["id"],
            "district": "Ahmedabad",
            "latitude": 23.03,
            "longitude": 72.58,
            "camera_type": "anpr",
            "status": "active",
            "health": "online",
            "connectivity_type": "fiber",
            "stream_protocol": "rtsp",
            "vendor": "Keep This Vendor",
            "ai_capabilities": ["anpr", "vehicle_detection"],
            "tags": ["keep-this-tag"],
        },
    )
    assert create.status_code == 201, create.text

    sparse = (
        "camera_code,camera_name,department_code,district,latitude,longitude\n"
        "CAM-SPARSE-001,After Sparse Update,HOME,Ahmedabad,23.04,72.59\n"
    )
    update = client.post(
        "/api/v1/cameras/import?on_duplicate=update",
        files={"file": ("sparse.csv", sparse.encode(), "text/csv")},
    )
    assert update.status_code == 200, update.text
    assert update.json()["updated"] == 1

    camera = client.get("/api/v1/cameras?search=CAM-SPARSE-001").json()["items"][0]
    assert camera["camera_name"] == "After Sparse Update"
    assert camera["camera_type"] == "anpr"
    assert camera["status"] == "active"
    assert camera["health"] == "online"
    assert camera["connectivity_type"] == "fiber"
    assert camera["stream_protocol"] == "rtsp"
    assert camera["vendor"] == "Keep This Vendor"
    assert camera["ai_capabilities"] == ["anpr", "vehicle_detection"]
    assert camera["ai_enabled"] is True
    assert camera["tags"] == ["keep-this-tag"]


def test_csv_update_derives_capability_when_protocol_is_explicit(
    client: TestClient, department: dict
) -> None:
    create = client.post(
        "/api/v1/cameras",
        json={
            "camera_code": "CAM-PROTOCOL-001",
            "camera_name": "Protocol Camera",
            "department_id": department["id"],
            "district": "Ahmedabad",
            "latitude": 23.03,
            "longitude": 72.58,
        },
    )
    assert create.status_code == 201
    assert create.json()["rtsp_capable"] is False

    csv_content = (
        "camera_code,camera_name,department_code,district,latitude,longitude,"
        "stream_protocol\n"
        "CAM-PROTOCOL-001,Protocol Camera Updated,HOME,Ahmedabad,23.03,72.58,rtsp\n"
    )
    update = client.post(
        "/api/v1/cameras/import?on_duplicate=update",
        files={"file": ("protocol.csv", csv_content.encode(), "text/csv")},
    )
    assert update.status_code == 200, update.text
    assert update.json()["updated"] == 1
    camera = client.get("/api/v1/cameras?search=CAM-PROTOCOL-001").json()["items"][0]
    assert camera["stream_protocol"] == "rtsp"
    assert camera["rtsp_capable"] is True


def test_oversized_csv_field_returns_structured_400_without_partial_import(
    client: TestClient, department: dict
) -> None:
    oversized_name = "X" * max(registry_service.MAX_FIELD_CHARS + 1, 131_073)
    content = (
        "camera_code,camera_name,department_code,district,latitude,longitude\n"
        f"CAM-FIELD-001,{oversized_name},HOME,Ahmedabad,23.03,72.58\n"
    )
    assert len(content.encode()) < registry_service.MAX_IMPORT_BYTES
    response = client.post(
        "/api/v1/cameras/import",
        files={"file": ("oversized-field.csv", content.encode(), "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CSV_FIELD_TOO_LARGE"
    assert client.get("/api/v1/cameras").json()["total"] == 0


def test_csv_row_and_result_limits_are_atomic(
    client: TestClient, department: dict, monkeypatch
) -> None:
    header = "camera_code,camera_name,department_code,district,latitude,longitude\n"
    rows = "".join(
        f"CAM-LIMIT-{number:03d},Camera {number},HOME,Ahmedabad,23.03,72.58\n"
        for number in range(3)
    )

    monkeypatch.setattr(registry_service, "MAX_IMPORT_ROWS", 2)
    row_limit = client.post(
        "/api/v1/cameras/import",
        files={"file": ("row-limit.csv", (header + rows).encode(), "text/csv")},
    )
    assert row_limit.status_code == 400
    assert row_limit.json()["error"]["code"] == "IMPORT_ROW_LIMIT_EXCEEDED"
    assert client.get("/api/v1/cameras").json()["total"] == 0

    monkeypatch.setattr(registry_service, "MAX_IMPORT_ROWS", 10)
    monkeypatch.setattr(registry_service, "MAX_RESULT_ROWS", 2)
    result_limit = client.post(
        "/api/v1/cameras/import",
        files={"file": ("result-limit.csv", (header + rows).encode(), "text/csv")},
    )
    assert result_limit.status_code == 400
    assert result_limit.json()["error"]["code"] == "IMPORT_RESULT_LIMIT_EXCEEDED"
    assert client.get("/api/v1/cameras").json()["total"] == 0


def test_malformed_csv_returns_structured_400(client: TestClient, department: dict) -> None:
    malformed = (
        "camera_code,camera_name,department_code,district,latitude,longitude\n"
        'CAM-BROKEN-001,"unterminated,HOME,Ahmedabad,23.03,72.58\n'
    )
    response = client.post(
        "/api/v1/cameras/import",
        files={"file": ("malformed.csv", malformed.encode(), "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CSV_SYNTAX"
