from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes.ai_showcase import get_ai_showcase
from app.services.ai_showcase import AIShowcaseStore

JPEG = b"\xff\xd8\xff\xd9"


def seed_ai_evidence(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE detections (
            id INTEGER PRIMARY KEY, source TEXT NOT NULL, frame INTEGER NOT NULL,
            time_ms REAL NOT NULL, track_id INTEGER, class_id INTEGER NOT NULL,
            class_name TEXT NOT NULL, confidence REAL NOT NULL,
            x1 REAL NOT NULL, y1 REAL NOT NULL, x2 REAL NOT NULL, y2 REAL NOT NULL,
            width INTEGER NOT NULL, height INTEGER NOT NULL, crop BLOB NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE plate_detections (
            id INTEGER PRIMARY KEY, source_detection_id INTEGER, source TEXT NOT NULL,
            frame INTEGER NOT NULL, time_ms REAL NOT NULL, track_id INTEGER,
            plate_text TEXT, ocr_confidence REAL, detection_confidence REAL NOT NULL,
            x1 REAL NOT NULL, y1 REAL NOT NULL, x2 REAL NOT NULL, y2 REAL NOT NULL,
            width INTEGER NOT NULL, height INTEGER NOT NULL, crop BLOB NOT NULL,
            ocr_provider TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE visual_vehicle_intelligence (analysis_status TEXT NOT NULL);
        INSERT INTO visual_vehicle_intelligence VALUES ('COMPLETED');
        INSERT INTO visual_vehicle_intelligence VALUES ('PENDING');
        INSERT INTO visual_vehicle_intelligence VALUES ('FAILED');
        """
    )
    connection.execute(
        """
        INSERT INTO detections VALUES (
            1, 'C:\\sensitive\\traffic.mp4', 42, 1400, 7, 2, 'car', .91,
            1, 2, 101, 52, 100, 50, ?, '2026-08-31 10:00:00'
        )
        """,
        (JPEG,),
    )
    connection.execute(
        """
        INSERT INTO detections VALUES (
            2, 'C:\\sensitive\\latest.mp4', 84, 2800, 8, 2, 'car', .55,
            2, 4, 102, 54, 100, 50, ?, '2026-08-31 10:02:00'
        )
        """,
        (JPEG,),
    )
    connection.execute(
        """
        INSERT INTO plate_detections VALUES (
            1, 1, 'C:\\sensitive\\traffic.mp4', 42, 1400, 7,
            'GJ01AB1234', .94, .88, 10, 20, 80, 40, 70, 20, ?,
            'google-cloud-vision:document-text-detection-v1', '2026-08-31 10:00:01'
        )
        """,
        (JPEG,),
    )
    connection.execute(
        """
        INSERT INTO plate_detections VALUES (
            2, 2, 'C:\\sensitive\\latest.mp4', 84, 2800, 8,
            'GJ02CD5678', .61, .59, 12, 22, 82, 42, 70, 20, ?,
            'google-cloud-vision:document-text-detection-v1', '2026-08-31 10:02:01'
        )
        """,
        (JPEG,),
    )
    connection.commit()
    connection.close()


def test_ai_showcase_exposes_searchable_evidence_without_local_paths(
    client: TestClient, tmp_path: Path
) -> None:
    evidence = tmp_path / "crops.db"
    seed_ai_evidence(evidence)
    client.app.dependency_overrides[get_ai_showcase] = lambda: AIShowcaseStore(evidence, "/api/v1")

    overview = client.get("/api/v1/ai/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["available"] is True
    assert body["vehicle_detections"] == 2
    assert body["plate_detections"] == 2
    assert body["readable_plate_detections"] == 2
    assert body["consensus_plate_detections"] == 0
    assert body["visual_profiles"] == 1
    assert body["visual_pending"] == 1
    assert body["visual_failed"] == 1
    assert body["unique_tracks"] == 2
    assert "accuracy" in body["disclosure"]
    assert {model["model_id"] for model in body["models"]} == {
        "MDL-VEH-001",
        "MDL-ANPR-001",
        "SVC-OCR-HYBRID-001",
        "SVC-VLM-001",
    }

    latest_vehicles = client.get("/api/v1/ai/detections?minimum_confidence=0")
    assert [item["id"] for item in latest_vehicles.json()["items"]] == [2, 1]
    assert latest_vehicles.json()["items"][0]["evidence_id"] == "VEH-00000002"
    assert latest_vehicles.json()["items"][0]["model_id"] == "MDL-VEH-001"

    vehicles = client.get("/api/v1/ai/detections?query=7&class_name=car")
    assert vehicles.status_code == 200
    detection = vehicles.json()["items"][0]
    assert detection["source_label"] == "traffic.mp4"
    assert "sensitive" not in str(detection)

    image = client.get(detection["image_url"])
    assert image.status_code == 200
    assert image.content == JPEG
    assert image.headers["cache-control"].startswith("private, no-store")

    plates = client.get("/api/v1/ai/plates?query=GJ01")
    assert plates.status_code == 200
    plate = plates.json()["items"][0]
    assert plate["plate_text"] == "GJ01AB1234"
    assert plate["ocr_provider"].startswith("google-cloud-vision")
    assert plate["ocr_status"] == "COMPLETED"
    assert plate["ocr_raw_text"] == "GJ01AB1234"
    assert plate["ocr_consensus_count"] == 1
    assert plate["source_vehicle_evidence_id"] == "VEH-00000001"
    assert client.get(plate["image_url"]).content == JPEG

    latest_plates = client.get("/api/v1/ai/plates")
    assert [item["id"] for item in latest_plates.json()["items"]] == [2, 1]
    assert latest_plates.json()["items"][0]["evidence_id"] == "ANPR-00000002"
    assert latest_plates.json()["items"][0]["detector_model_id"] == "MDL-ANPR-001"
    assert latest_plates.json()["items"][0]["ocr_model_id"] == "SVC-OCR-HYBRID-001"


def test_ai_showcase_is_graceful_when_evidence_database_is_absent(
    client: TestClient, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.db"
    client.app.dependency_overrides[get_ai_showcase] = lambda: AIShowcaseStore(missing, "/api/v1")

    assert client.get("/api/v1/ai/overview").json()["available"] is False
    assert client.get("/api/v1/ai/detections").json()["items"] == []
    assert client.get("/api/v1/ai/plates").json()["items"] == []
