from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from conftest import make_camera_payload
from fastapi.testclient import TestClient


def create_camera(client: TestClient, department_id: str, **overrides: object) -> dict:
    response = client.post(
        "/api/v1/cameras",
        json=make_camera_payload(department_id, **overrides),
        headers={"X-Actor-ID": "registry-test"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_and_readiness(client: TestClient) -> None:
    live = client.get("/health")
    ready = client.get("/health/ready")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["checks"] == {"database": "ok"}
    assert "X-Request-ID" in ready.headers


def test_request_log_is_structured_and_excludes_query_and_headers(
    client: TestClient, caplog
) -> None:
    caplog.set_level(logging.INFO, logger="drishti.registry")
    response = client.get(
        "/health?access_token=DO-NOT-LOG",
        headers={"Authorization": "Bearer DO-NOT-LOG", "X-Request-ID": "qa-request-1"},
    )
    assert response.status_code == 200
    record = next(
        record
        for record in reversed(caplog.records)
        if record.name == "drishti.registry" and '"event":"http_request"' in record.message
    )
    event = json.loads(record.message)
    assert event["request_id"] == "qa-request-1"
    assert event["method"] == "GET"
    assert event["path"] == "/health"
    assert event["status"] == 200
    assert event["duration_ms"] >= 0
    assert "DO-NOT-LOG" not in record.message


def test_department_create_list_update_and_duplicate(client: TestClient, department: dict) -> None:
    assert department["code"] == "HOME"
    assert department["created_at"].endswith(("Z", "+00:00"))
    listing = client.get("/api/v1/departments?search=home").json()
    assert listing["total"] == 1
    assert listing["pages"] == 1

    updated = client.patch(
        f"/api/v1/departments/{department['id']}",
        json={"description": "Updated description"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Updated description"

    duplicate = client.post("/api/v1/departments", json={"code": "HOME", "name": "Another Home"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DEPARTMENT_CODE_EXISTS"


def test_camera_create_normalizes_and_hides_internal_references(
    client: TestClient, department: dict
) -> None:
    camera = create_camera(client, department["id"])
    assert camera["camera_code"] == "AHM-CAM-001"
    assert camera["ai_capabilities"] == ["anpr", "vehicle_detection"]
    assert camera["tags"] == ["junction", "traffic"]
    assert camera["ai_enabled"] is True
    assert camera["rtsp_capable"] is True
    assert camera["installation_date"] == "2025-01-15"
    assert camera["created_at"].endswith(("Z", "+00:00"))
    assert camera["updated_at"].endswith(("Z", "+00:00"))
    assert "stream_reference" not in camera
    assert "credential_reference" not in camera

    duplicate = client.post("/api/v1/cameras", json=make_camera_payload(department["id"]))
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CAMERA_CODE_EXISTS"


def test_secret_bearing_streams_and_metadata_are_rejected(
    client: TestClient, department: dict
) -> None:
    payload = make_camera_payload(
        department["id"],
        stream_reference="rtsp://admin:password@10.0.0.1/live",
    )
    response = client.post("/api/v1/cameras", json=payload)
    assert response.status_code == 422

    payload = make_camera_payload(
        department["id"],
        camera_code="AHM-CAM-004",
        storage_details={
            "connection": {
                "credentials": "admin:pw",
                "endpoint": "rtsp://admin:pw@camera.internal/live",
            }
        },
    )
    response = client.post("/api/v1/cameras", json=payload)
    assert response.status_code == 422

    payload = make_camera_payload(
        department["id"],
        camera_code="AHM-CAM-005",
        installation_metadata={"endpoint": "https://camera.internal/config?access_token=TOPSECRET"},
    )
    response = client.post("/api/v1/cameras", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    payload = make_camera_payload(
        department["id"],
        camera_code="AHM-CAM-003",
        stream_reference="https://streams.internal.example/camera/3",
        credential_reference="not-an-opaque-vault-reference",
    )
    response = client.post("/api/v1/cameras", json=payload)
    assert response.status_code == 422

    payload = make_camera_payload(
        department["id"],
        camera_code="AHM-CAM-002",
        storage_details={"password": "not-allowed"},
    )
    response = client.post("/api/v1/cameras", json=payload)
    assert response.status_code == 422


def test_camera_cannot_be_created_or_patched_as_retired(
    client: TestClient, department: dict
) -> None:
    create_response = client.post(
        "/api/v1/cameras",
        json=make_camera_payload(department["id"], status="retired"),
    )
    assert create_response.status_code == 422
    assert create_response.json()["error"]["code"] == "VALIDATION_ERROR"

    camera = create_camera(client, department["id"], camera_code="AHM-CAM-RETIRE")
    patch_response = client.patch(f"/api/v1/cameras/{camera['id']}", json={"status": "retired"})
    assert patch_response.status_code == 422
    assert patch_response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_search_filters_pagination_and_filtered_statistics(
    client: TestClient, department: dict
) -> None:
    create_camera(client, department["id"])
    create_camera(
        client,
        department["id"],
        camera_code="SRT-CAM-001",
        camera_name="Surat Gate",
        district="Surat",
        city="Surat",
        latitude=21.1702,
        longitude=72.8311,
        health="online",
        ai_capabilities=[],
        tags=["gate"],
    )
    listing = client.get("/api/v1/cameras?page=1&page_size=1")
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert listing.json()["pages"] == 2
    assert len(listing.json()["items"]) == 1

    surat = client.get("/api/v1/cameras?search=surat&district=Surat").json()
    assert surat["total"] == 1
    assert surat["items"][0]["camera_code"] == "SRT-CAM-001"

    stats = client.get("/api/v1/cameras/statistics?district=Surat")
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["total"] == 1
    assert body["online"] == 1
    assert body["ai_enabled"] == 0
    assert body["by_department"][0]["count"] == 1


def test_city_vendor_and_vms_filters_are_combined_across_registry_views(
    client: TestClient, department: dict
) -> None:
    create_camera(client, department["id"])
    create_camera(
        client,
        department["id"],
        camera_code="AHM-CAM-002",
        camera_name="Ahmedabad Axis Camera",
        vendor="Axis Communications",
        health="online",
    )
    create_camera(
        client,
        department["id"],
        camera_code="SRT-CAM-001",
        camera_name="Surat Generic Camera",
        district="Surat",
        city="Surat",
        latitude=21.1702,
        longitude=72.8311,
        vms="Milestone XProtect",
        health="online",
    )

    params = {
        "city": "AHMEDABAD",
        "vendor": "generic onvif",
        "vms": "department vms a",
    }
    listing = client.get("/api/v1/cameras", params=params)
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["camera_code"] == "AHM-CAM-001"

    statistics = client.get("/api/v1/cameras/statistics", params=params)
    assert statistics.status_code == 200, statistics.text
    assert statistics.json()["total"] == 1
    assert statistics.json()["unknown"] == 1
    assert statistics.json()["ai_enabled"] == 1

    geojson = client.get("/api/v1/cameras/geojson", params=params)
    assert geojson.status_code == 200, geojson.text
    assert geojson.json()["number_matched"] == 1
    assert geojson.json()["features"][0]["properties"]["camera_code"] == "AHM-CAM-001"

    assert client.get("/api/v1/cameras", params={"vendor": "generic"}).json()["total"] == 0
    assert client.get("/api/v1/cameras", params={"vms": "department"}).json()["total"] == 0


def test_camera_search_includes_department_code_and_name_across_registry_views(
    client: TestClient, department: dict
) -> None:
    create_camera(client, department["id"])

    for search in (department["code"].lower(), department["name"].lower()):
        listing = client.get("/api/v1/cameras", params={"search": search})
        assert listing.status_code == 200, listing.text
        assert listing.json()["total"] == 1
        assert listing.json()["items"][0]["camera_code"] == "AHM-CAM-001"

        statistics = client.get("/api/v1/cameras/statistics", params={"search": search})
        assert statistics.status_code == 200, statistics.text
        assert statistics.json()["total"] == 1

        geojson = client.get("/api/v1/cameras/geojson", params={"search": search})
        assert geojson.status_code == 200, geojson.text
        assert geojson.json()["number_matched"] == 1
        assert geojson.json()["features"][0]["properties"]["camera_code"] == "AHM-CAM-001"


def test_filter_options_are_sorted_safe_and_exclude_retired_by_default(
    client: TestClient, department: dict
) -> None:
    create_camera(client, department["id"])
    retired_candidate = create_camera(
        client,
        department["id"],
        camera_code="SRT-CAM-001",
        camera_name="Surat Perimeter",
        district="Surat",
        city="Surat",
        latitude=21.1702,
        longitude=72.8311,
        camera_type="fixed",
        vendor="Axis Communications",
        vms="Milestone XProtect",
        connectivity_type="cellular_4g",
        stream_protocol="onvif",
        ai_capabilities=["Crowd_Counting"],
    )

    options_response = client.get("/api/v1/cameras/filter-options")
    assert options_response.status_code == 200, options_response.text
    options = options_response.json()
    assert options == {
        "districts": ["Ahmedabad", "Surat"],
        "cities": ["Ahmedabad", "Surat"],
        "vendors": ["Axis Communications", "Generic ONVIF"],
        "vms": ["Department VMS A", "Milestone XProtect"],
        "ai_capabilities": ["anpr", "crowd_counting", "vehicle_detection"],
        "camera_types": ["anpr", "fixed"],
        "connectivity_types": ["cellular_4g", "fiber"],
        "stream_protocols": ["onvif", "rtsp"],
    }
    serialized = json.dumps(options)
    assert "stream_reference" not in serialized
    assert "credential_reference" not in serialized
    assert "connection-profile:" not in serialized
    assert "vault-ref:" not in serialized

    retirement = client.post(
        f"/api/v1/cameras/{retired_candidate['id']}/retire",
        json={"reason": "Removed from active inventory after replacement"},
    )
    assert retirement.status_code == 200, retirement.text

    active_options = client.get("/api/v1/cameras/filter-options").json()
    assert active_options == {
        "districts": ["Ahmedabad"],
        "cities": ["Ahmedabad"],
        "vendors": ["Generic ONVIF"],
        "vms": ["Department VMS A"],
        "ai_capabilities": ["anpr", "vehicle_detection"],
        "camera_types": ["anpr"],
        "connectivity_types": ["fiber"],
        "stream_protocols": ["rtsp"],
    }
    all_options = client.get(
        "/api/v1/cameras/filter-options", params={"include_retired": True}
    ).json()
    assert all_options == options


def test_geojson_bbox_nearby_and_safe_properties(client: TestClient, department: dict) -> None:
    create_camera(client, department["id"])
    create_camera(
        client,
        department["id"],
        camera_code="SRT-CAM-001",
        camera_name="Surat Gate",
        district="Surat",
        latitude=21.1702,
        longitude=72.8311,
    )

    bbox = client.get("/api/v1/cameras/geojson?bbox=72.4,22.9,72.7,23.2")
    assert bbox.status_code == 200, bbox.text
    feature_collection = bbox.json()
    assert feature_collection["type"] == "FeatureCollection"
    assert feature_collection["number_matched"] == 1
    feature = feature_collection["features"][0]
    assert feature["geometry"]["coordinates"] == [72.5706, 23.0385]
    assert "stream_reference" not in feature["properties"]
    assert "credential_reference" not in feature["properties"]
    assert feature["properties"]["created_at"].endswith(("Z", "+00:00"))

    nearby = client.get("/api/v1/cameras?near_lat=23.0385&near_lon=72.5706&radius_m=3000")
    assert nearby.status_code == 200, nearby.text
    assert nearby.json()["total"] == 1
    assert nearby.json()["items"][0]["camera_code"] == "AHM-CAM-001"

    incomplete = client.get("/api/v1/cameras?near_lat=23.0")
    assert incomplete.status_code == 400
    assert incomplete.json()["error"]["code"] == "INCOMPLETE_NEARBY_FILTER"


def test_patch_heartbeat_retirement_and_append_audit(client: TestClient, department: dict) -> None:
    camera = create_camera(client, department["id"])
    camera_id = camera["id"]

    patched = client.patch(
        f"/api/v1/cameras/{camera_id}",
        json={
            "camera_name": "Ashram Road ANPR",
            "stream_reference": "stream-profile:home/rotated-reference",
        },
        headers={"X-Actor-ID": "operator-7"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["camera_name"] == "Ashram Road ANPR"

    observed = datetime.now(UTC).replace(microsecond=0)
    heartbeat = client.post(
        f"/api/v1/cameras/{camera_id}/heartbeat",
        json={
            "health": "online",
            "observed_at": observed.isoformat(),
            "details": {"fps": 24.8, "latency_ms": 86},
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["health"] == "online"

    stale = client.post(
        f"/api/v1/cameras/{camera_id}/heartbeat",
        json={
            "health": "offline",
            "observed_at": (observed - timedelta(minutes=5)).isoformat(),
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_HEARTBEAT"

    audit = client.get(f"/api/v1/cameras/{camera_id}/audit").json()
    assert audit["total"] == 3
    assert {entry["action"] for entry in audit["items"]} == {
        "camera.created",
        "camera.updated",
        "camera.heartbeat",
    }
    serialized = str(audit["items"])
    assert all(item["created_at"].endswith(("Z", "+00:00")) for item in audit["items"])
    assert "rotated-reference" not in serialized
    assert "vault-ref:" not in serialized
    assert "[REDACTED]" in serialized

    retired = client.post(
        f"/api/v1/cameras/{camera_id}/retire",
        json={"reason": "Camera replaced after end of service life"},
    )
    assert retired.status_code == 200
    assert retired.json()["status"] == "retired"
    assert retired.json()["health"] == "offline"
    assert client.get("/api/v1/cameras").json()["total"] == 0
    assert client.get("/api/v1/cameras?include_retired=true").json()["total"] == 1

    rejected_patch = client.patch(
        f"/api/v1/cameras/{camera_id}", json={"camera_name": "Cannot change"}
    )
    assert rejected_patch.status_code == 409


def test_heartbeat_rejects_secret_bearing_details(client: TestClient, department: dict) -> None:
    camera = create_camera(client, department["id"])
    response = client.post(
        f"/api/v1/cameras/{camera['id']}/heartbeat",
        json={
            "health": "online",
            "details": {"nested": {"authorization": "Bearer TOPSECRET"}},
        },
    )
    assert response.status_code == 422
    audit = client.get(f"/api/v1/cameras/{camera['id']}/audit").json()
    assert audit["total"] == 1
    assert "TOPSECRET" not in str(audit)


def test_update_only_changes_explicit_fields(client: TestClient, department: dict) -> None:
    camera = create_camera(client, department["id"])
    response = client.patch(f"/api/v1/cameras/{camera['id']}", json={"city": None})
    assert response.status_code == 200, response.text
    assert response.json()["city"] is None
    assert response.json()["district"] == "Ahmedabad"

    invalid = client.patch(f"/api/v1/cameras/{camera['id']}", json={"district": None})
    assert invalid.status_code == 422


def test_structured_not_found_and_validation_errors(client: TestClient) -> None:
    missing = client.get("/api/v1/cameras/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CAMERA_NOT_FOUND"
    assert missing.json()["error"]["request_id"]

    invalid = client.post("/api/v1/departments", json={"code": "!", "name": "x"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(invalid.json()["error"]["details"], list)
