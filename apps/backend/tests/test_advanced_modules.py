from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from conftest import make_camera_payload
from fastapi.testclient import TestClient

INVESTIGATOR = {"X-Actor-ID": "investigator-42", "X-Actor-Role": "investigator"}
OTHER_INVESTIGATOR = {"X-Actor-ID": "investigator-99", "X-Actor-Role": "investigator"}
ANALYTICS = {"X-Actor-ID": "edge-analytics-1", "X-Actor-Role": "analytics"}
OPERATIONS = {"X-Actor-ID": "operations-7", "X-Actor-Role": "operations"}
PLANNER = {"X-Actor-ID": "planner-3", "X-Actor-Role": "planner"}


def _camera(
    client: TestClient,
    department_id: str,
    index: int,
    latitude: float,
    longitude: float,
    *,
    health: str = "online",
    edge_node_id: str | None = None,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/cameras",
        json=make_camera_payload(
            department_id,
            camera_code=f"ADV-CAM-{index:03d}",
            camera_name=f"Advanced Intelligence Camera {index}",
            latitude=latitude,
            longitude=longitude,
            health=health,
            bearing_degrees=45,
            coverage_radius_m=1500,
            installation_metadata={"edge_node_id": edge_node_id} if edge_node_id else {},
            ai_capabilities=["anpr", "vehicle_tracking"],
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_reid_review_updates_pursuit_and_case_evidence_is_audited(
    client: TestClient,
    department: dict[str, Any],
) -> None:
    for index, offset in enumerate((0.0, 0.006, 0.012, 0.018), start=1):
        _camera(client, department["id"], index, 23.03 + offset, 72.57 + offset)

    seeded = client.post(
        "/api/v1/investigations/demo-scenario",
        json={"target_plate": "GJ01AB1234"},
        headers=INVESTIGATOR,
    )
    assert seeded.status_code == 200, seeded.text
    created = client.post(
        "/api/v1/investigations",
        json={
            "target_plate": "GJ01AB1234",
            "priority": "critical",
            "reason": "Authorized advanced module integration validation",
        },
        headers=INVESTIGATOR,
    )
    assert created.status_code == 201, created.text
    investigation = created.json()
    investigation_id = investigation["case"]["id"]
    original_observation_count = len(investigation["observations"])

    demo = client.post(
        f"/api/v1/reid/investigations/{investigation_id}/demo",
        headers=INVESTIGATOR,
    )
    assert demo.status_code == 200, demo.text
    assert "Synthetic" in demo.json()["disclosure"]

    ranked = client.post(
        f"/api/v1/reid/investigations/{investigation_id}/rank",
        json={"max_candidates": 10},
        headers=INVESTIGATOR,
    )
    assert ranked.status_code == 200, ranked.text
    result = ranked.json()
    assert len(result["items"]) == 2
    assert "uncalibrated" in result["disclosure"]
    best = result["items"][0]
    assert best["candidate"]["quality_flags"] == ["plate_unreadable"]
    assert best["visual_similarity"] is not None
    assert best["technical_score"] > result["items"][1]["technical_score"]

    reviewed = client.post(
        f"/api/v1/reid/matches/{best['id']}/review",
        json={
            "status": "confirmed",
            "note": "Vehicle body, colour, time and route were manually reviewed.",
        },
        headers=INVESTIGATOR,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["reviewed_by"] == "investigator-42"
    pursuit = client.get(f"/api/v1/investigations/{investigation_id}", headers=INVESTIGATOR).json()
    assert pursuit["case"]["status"] == "reacquired"
    assert len(pursuit["observations"]) == original_observation_count + 1

    case_response = client.post(
        "/api/v1/cases",
        json={
            "title": "Ahmedabad corridor vehicle pursuit",
            "description": "Controlled case workspace for reviewed vehicle intelligence.",
            "priority": "critical",
            "authorization_reference": "AUTH-COURT-2026-0081",
            "investigation_id": investigation_id,
        },
        headers=INVESTIGATOR,
    )
    assert case_response.status_code == 201, case_response.text
    workspace = case_response.json()
    case_id = workspace["case"]["id"]
    assert workspace["case"]["status"] == "active"
    assert len(workspace["evidence"]) == original_observation_count + 1
    assert workspace["integrity_verified"] == len(workspace["evidence"])
    assert all(len(item["sha256"]) == 64 for item in workspace["evidence"])
    assert "controlled_reference" not in workspace["evidence"][0]

    denied = client.get(f"/api/v1/cases/{case_id}", headers=OTHER_INVESTIGATOR)
    assert denied.status_code == 403

    evidence = workspace["evidence"][0]
    viewed = client.get(f"/api/v1/cases/{case_id}/evidence/{evidence['id']}", headers=INVESTIGATOR)
    assert viewed.status_code == 200
    exported = client.post(f"/api/v1/cases/{case_id}/export", headers=INVESTIGATOR)
    assert exported.status_code == 200, exported.text
    export_body = exported.json()
    assert "not a complete legal chain of custody" in export_body["integrity_disclosure"]
    actions = {item["action"] for item in export_body["workspace"]["activity"]}
    assert {"case.created", "evidence.viewed", "case.exported"}.issubset(actions)


def test_health_debounce_grouping_history_and_recovery(
    client: TestClient,
    department: dict[str, Any],
) -> None:
    cameras = [
        _camera(
            client,
            department["id"],
            20 + index,
            23.10 + index * 0.002,
            72.60 + index * 0.002,
            edge_node_id="edge-west-1",
        )
        for index in range(3)
    ]
    base = datetime.now(UTC) - timedelta(minutes=15)
    for interval in (0, 5):
        for camera in cameras:
            response = client.post(
                "/api/v1/camera-health/aggregates",
                json={
                    "camera_id": camera["id"],
                    "bucket_start": (base + timedelta(minutes=interval)).isoformat(),
                    "availability": 0,
                    "decoded_fps": 0,
                    "reconnect_count": 8,
                    "decoder_errors": 10,
                    "edge_node_id": "edge-west-1",
                    "ai_worker_state": "offline",
                    "source": "edge_aggregate_test",
                },
                headers=ANALYTICS,
            )
            assert response.status_code == 202, response.text
            assert response.json()["health_state"] == "offline"

    dashboard = client.get("/api/v1/camera-health/dashboard", headers=OPERATIONS)
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert body["states"]["offline"] == 3
    assert len(body["incidents"]) == 1
    assert body["incidents"][0]["incident_type"] == "edge_node_outage"
    assert len(body["incidents"][0]["affected_camera_ids"]) == 3
    assert "No random" in body["telemetry_basis"]

    history = client.get(
        f"/api/v1/camera-health/cameras/{cameras[0]['id']}/history",
        headers=OPERATIONS,
    )
    assert history.status_code == 200
    assert len(history.json()["items"]) == 2

    for camera in cameras:
        recovered = client.post(
            "/api/v1/camera-health/aggregates",
            json={
                "camera_id": camera["id"],
                "bucket_start": datetime.now(UTC).isoformat(),
                "availability": 1,
                "decoded_fps": 25,
                "processing_fps": 12,
                "latency_ms": 80,
                "edge_node_id": "edge-west-1",
                "ai_worker_state": "healthy",
                "source": "edge_aggregate_test",
            },
            headers=ANALYTICS,
        )
        assert recovered.status_code == 202
        assert recovered.json()["health_state"] == "healthy"
    recovered_dashboard = client.get("/api/v1/camera-health/dashboard", headers=OPERATIONS).json()
    assert recovered_dashboard["states"]["healthy"] == 3
    assert recovered_dashboard["incidents"] == []


def test_coverage_uses_registry_health_and_what_if_does_not_mutate_camera(
    client: TestClient,
    department: dict[str, Any],
) -> None:
    first = _camera(client, department["id"], 30, 23.02, 72.50)
    _camera(client, department["id"], 31, 23.03, 72.51)
    offline = _camera(
        client,
        department["id"],
        32,
        23.55,
        73.10,
        health="offline",
    )
    analysis = client.post(
        "/api/v1/coverage/analyses",
        json={"gap_threshold_m": 5000, "redundancy_radius_m": 3000},
        headers=PLANNER,
    )
    assert analysis.status_code == 200, analysis.text
    body = analysis.json()
    assert body["camera_count"] == 3
    assert body["operational_count"] == 2
    assert body["metrics"]["operational_nodes"] == 2
    assert body["metrics"]["temporary_gaps"] == 1
    assert any(item["source_camera_id"] == offline["id"] for item in body["gaps"])
    assert body["deployment_candidates"]
    assert "candidate area only" in body["deployment_candidates"][0]["assumption"]

    simulation = client.post(
        "/api/v1/coverage/what-if",
        json={"camera_id": first["id"]},
        headers=PLANNER,
    )
    assert simulation.status_code == 200, simulation.text
    what_if = simulation.json()
    assert what_if["simulation"] is True
    assert "no camera or stream state was changed" in what_if["assumptions"][0]
    camera_after = client.get(f"/api/v1/cameras/{first['id']}").json()
    assert camera_after["status"] == "active"
    assert camera_after["health"] == "online"
