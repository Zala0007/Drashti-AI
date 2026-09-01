from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from conftest import make_camera_payload
from fastapi.testclient import TestClient

from app.services.investigation_engine import plate_similarity

AUTH = {"X-Actor-ID": "investigator-42", "X-Actor-Role": "investigator"}


def _camera(
    client: TestClient,
    department_id: str,
    index: int,
    latitude: float,
    longitude: float,
    *,
    health: str = "online",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/cameras",
        json=make_camera_payload(
            department_id,
            camera_code=f"SIE-AHD-{index:03d}",
            camera_name=f"Investigation Corridor {index}",
            latitude=latitude,
            longitude=longitude,
            status="active",
            health=health,
            bearing_degrees=45,
            ai_capabilities=["anpr", "vehicle_tracking"],
        ),
    )
    assert response.status_code == 201
    return response.json()


def test_plate_similarity_handles_common_ocr_confusion_without_equating_weak_text() -> None:
    assert plate_similarity("GJ01AB1234", "GJ01AB1234") == 1
    assert plate_similarity("GJ01AB1234", "GJ01A81234") > 0.95
    assert plate_similarity("GJ01AB1234", "MH12ZZ9999") < 0.4


def test_authorized_investigation_builds_observed_route_and_bounded_predictions(
    client: TestClient,
    department: dict[str, Any],
) -> None:
    cameras = [
        _camera(client, department["id"], 1, 23.0300, 72.5700),
        _camera(client, department["id"], 2, 23.0350, 72.5750),
        _camera(client, department["id"], 3, 23.0400, 72.5800),
        _camera(client, department["id"], 4, 23.0460, 72.5860),
        _camera(client, department["id"], 5, 23.0520, 72.5920),
    ]
    unauthorized = client.get("/api/v1/investigations")
    assert unauthorized.status_code == 422

    seeded = client.post(
        "/api/v1/investigations/demo-scenario",
        json={"target_plate": "GJ01AB1234"},
        headers=AUTH,
    )
    assert seeded.status_code == 200
    assert seeded.json()["events_created"] == 3
    assert "Synthetic demonstration" in seeded.json()["disclosure"]

    created = client.post(
        "/api/v1/investigations",
        json={
            "target_plate": "GJ 01 AB 1234",
            "priority": "critical",
            "reason": "Authorized pursuit exercise for case validation",
        },
        headers=AUTH,
    )
    assert created.status_code == 201, created.text
    workspace = created.json()
    assert workspace["case"]["target_plate"] == "GJ01AB1234"
    assert workspace["case"]["status"] == "active_tracking"
    assert len(workspace["observations"]) == 3
    assert {item["evidence_class"] for item in workspace["observations"]} == {"observed"}
    assert any(item["event"]["plate_text"] == "GJ01A81234" for item in workspace["observations"])
    assert workspace["route_segments"]
    assert {item["segment_class"] for item in workspace["route_segments"]} == {"inferred"}
    assert workspace["candidates"]
    assert len(workspace["candidates"]) <= 12
    assert {item["evidence_class"] for item in workspace["candidates"]} == {"predicted"}
    assert workspace["prediction_basis"].startswith("Bounded geospatial")
    candidate_ids = {item["camera"]["id"] for item in workspace["candidates"]}
    assert cameras[3]["id"] in candidate_ids or cameras[4]["id"] in candidate_ids

    backtest = client.get(
        f"/api/v1/investigations/{workspace['case']['id']}/prediction-backtest",
        headers=AUTH,
    )
    assert backtest.status_code == 200, backtest.text
    evaluation = backtest.json()
    assert evaluation["eligible_transitions"] == 2
    assert evaluation["evaluated_transitions"] == 2
    assert evaluation["coverage"] == 1
    assert evaluation["top_5_accuracy"] is not None
    assert "not a probability" in evaluation["evaluation_basis"]


def test_impossible_travel_is_rejected_and_one_event_updates_multiple_cases(
    client: TestClient,
    department: dict[str, Any],
) -> None:
    first = _camera(client, department["id"], 10, 23.0300, 72.5700)
    distant = _camera(client, department["id"], 11, 21.1702, 72.8311)
    now = datetime.now(UTC)
    first_event = {
        "source_event_id": "live-event-001",
        "camera_id": first["id"],
        "observed_at": (now - timedelta(minutes=2)).isoformat(),
        "plate_text": "GJ01AB1234",
        "plate_confidence": 0.98,
        "source": "test_anpr",
    }
    first_response = client.post("/api/v1/investigations/events", json=first_event, headers=AUTH)
    assert first_response.status_code == 202
    case_ids = []
    for suffix in ("A", "B"):
        response = client.post(
            "/api/v1/investigations",
            json={
                "target_plate": "GJ01AB1234",
                "priority": "high",
                "reason": f"Authorized simultaneous investigation {suffix}",
            },
            headers=AUTH,
        )
        assert response.status_code == 201
        case_ids.append(response.json()["case"]["id"])

    impossible = client.post(
        "/api/v1/investigations/events",
        json={
            "source_event_id": "live-event-002",
            "camera_id": distant["id"],
            "observed_at": now.isoformat(),
            "plate_text": "GJ01AB1234",
            "plate_confidence": 0.99,
            "source": "test_anpr",
        },
        headers=AUTH,
    )
    assert impossible.status_code == 202
    assert impossible.json()["cases_updated"] == 2
    for case_id in case_ids:
        workspace = client.get(f"/api/v1/investigations/{case_id}", headers=AUTH).json()
        rejected = [item for item in workspace["observations"] if item["status"] == "rejected"]
        assert len(rejected) == 1
        assert rejected[0]["temporal_feasibility"] == 0
        assert "physically implausible" in " ".join(rejected[0]["reasoning"])
