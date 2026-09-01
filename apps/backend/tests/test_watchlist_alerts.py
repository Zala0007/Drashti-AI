from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

OPERATIONS = {"X-Actor-ID": "control-room-1", "X-Actor-Role": "operations"}
ANALYTICS = {"X-Actor-ID": "live-hybrid-ocr", "X-Actor-Role": "analytics"}


def test_live_anpr_event_creates_one_reviewable_watchlist_alert(
    client: TestClient, department: dict[str, object]
) -> None:
    camera_response = client.post(
        "/api/v1/cameras",
        json={
            "camera_code": "WATCH-CAM-001",
            "camera_name": "Evaluation Junction Camera",
            "department_id": str(department["id"]),
            "district": "Ahmedabad",
            "city": "Ahmedabad",
            "latitude": 23.03,
            "longitude": 72.58,
            "camera_type": "anpr",
            "status": "active",
            "health": "online",
            "connectivity_type": "fiber",
            "stream_protocol": "rtsp",
            "stream_reference": "connection-profile:evaluation/watch-cam-001",
            "ai_capabilities": ["anpr", "vehicle_detection"],
        },
        headers={"X-Actor-ID": "registry-admin"},
    )
    assert camera_response.status_code == 201
    camera = camera_response.json()

    entry_response = client.post(
        "/api/v1/watchlist/entries",
        json={
            "plate_text": "GJ 01 AB 1234",
            "subject_label": "Evaluation target vehicle",
            "reason": "Representative technical-evaluation watchlist entry",
            "severity": "critical",
        },
        headers=OPERATIONS,
    )
    assert entry_response.status_code == 201
    entry = entry_response.json()
    assert entry["normalized_plate"] == "GJ01AB1234"

    event_payload = {
        "source_event_id": "hybrid-live-event-001",
        "camera_id": camera["id"],
        "observed_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
        "plate_text": "GJ01AB1234",
        "plate_confidence": 0.93,
        "vehicle_attributes": {"ocr_decision": "providers_agree"},
        "evidence_reference": "/api/v1/ai/plates/9/image",
        "model_version": "MDL-ANPR-001+SVC-OCR-HYBRID-001",
        "source": "live_hybrid_anpr",
    }
    event_response = client.post(
        "/api/v1/investigations/events", json=event_payload, headers=ANALYTICS
    )
    assert event_response.status_code == 202
    assert event_response.json()["alerts_created"] == 1

    replay = client.post(
        "/api/v1/investigations/events", json=event_payload, headers=ANALYTICS
    )
    assert replay.status_code == 202
    assert replay.json()["alerts_created"] == 0

    alerts_response = client.get("/api/v1/watchlist/alerts", headers=OPERATIONS)
    assert alerts_response.status_code == 200
    alerts = alerts_response.json()
    assert alerts["total"] == 1
    assert alerts["unacknowledged"] == 1
    alert = alerts["items"][0]
    assert alert["matched_plate"] == "GJ01AB1234"
    assert alert["camera_code"] == camera["camera_code"]
    assert alert["entry"]["id"] == entry["id"]
    assert alert["evidence_reference"] == "/api/v1/ai/plates/9/image"

    review = client.post(
        f"/api/v1/watchlist/alerts/{alert['id']}/review",
        json={"status": "acknowledged"},
        headers=OPERATIONS,
    )
    assert review.status_code == 200
    assert review.json()["status"] == "acknowledged"
    assert review.json()["acknowledged_by"] == "control-room-1"

    dashboard = client.get("/api/v1/watchlist/dashboard", headers=OPERATIONS).json()
    assert dashboard["active_entries"] == 1
    assert dashboard["new_alerts"] == 0
