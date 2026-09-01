from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ANPREvent, Camera, Department, VehicleObservation
from app.services.live_intelligence import LiveIntelligenceRouter


def _evidence_database(path: Path, camera_id: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE detections (
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, frame INTEGER NOT NULL,
                time_ms REAL NOT NULL, track_id INTEGER, class_name TEXT NOT NULL,
                confidence REAL NOT NULL, x1 REAL NOT NULL, y1 REAL NOT NULL,
                x2 REAL NOT NULL, y2 REAL NOT NULL, width INTEGER NOT NULL,
                height INTEGER NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE plate_detections (
                id INTEGER PRIMARY KEY, source_detection_id INTEGER, source TEXT NOT NULL,
                time_ms REAL NOT NULL, track_id INTEGER, plate_text TEXT,
                ocr_confidence REAL, detection_confidence REAL NOT NULL
            );
            """
        )
        connection.execute(
            """INSERT INTO detections VALUES
               (1, ?, 17, 1788210000000, 4, 'car', 0.91,
                20, 30, 180, 110, 160, 80, '2026-09-01T12:00:00+00:00')""",
            (f"camera:{camera_id}",),
        )
        connection.execute(
            """INSERT INTO plate_detections VALUES
               (9, 1, ?, 1788210000000, 8, 'GJ01AB1234', 0.94, 0.88)""",
            (f"camera:{camera_id}",),
        )


def test_routes_vehicle_and_plate_evidence_into_operational_stores(
    tmp_path: Path, db_session_factory: sessionmaker[Session]
) -> None:
    department = Department(code="traffic", name="Traffic Police")
    camera = Camera(
        camera_code="CAM-LIVE-001",
        camera_name="Live Junction Camera",
        department=department,
        district="Ahmedabad",
        latitude=23.03,
        longitude=72.58,
        status="active",
    )
    with db_session_factory() as session:
        session.add(camera)
        session.commit()
        camera_id = camera.id

    evidence_path = tmp_path / "live-evidence.db"
    _evidence_database(evidence_path, camera_id)
    router = LiveIntelligenceRouter(
        evidence_path,
        session_factory=db_session_factory,
        app_env="test",
        api_prefix="/api/v1",
    )

    router._route_vehicle(1, include_visual=False)
    router._route_plate(9)

    with db_session_factory() as session:
        observation = session.scalar(
            select(VehicleObservation).where(
                VehicleObservation.source_observation_id == "live-vehicle-1"
            )
        )
        event = session.scalar(
            select(ANPREvent).where(ANPREvent.source_event_id == "live-anpr-9")
        )
        assert observation is not None
        assert event is not None
        assert observation.track_id == "4"
        assert observation.plate_text == "GJ01AB1234"
        assert observation.anpr_event_id == event.id
        assert observation.crop_reference == "/api/v1/ai/detections/1/image"
        assert observation.bounding_box == [0.0, 0.0, 160.0, 80.0]
        assert event.evidence_reference == "/api/v1/ai/plates/9/image"
        assert event.source == "live_hybrid_anpr"
        assert event.model_version == "MDL-ANPR-001+SVC-OCR-HYBRID-001"


def test_review_required_hybrid_plate_is_not_routed(
    tmp_path: Path, db_session_factory: sessionmaker[Session]
) -> None:
    department = Department(code="traffic-review", name="Traffic Review")
    camera = Camera(
        camera_code="CAM-REVIEW-001",
        camera_name="Review Junction Camera",
        department=department,
        district="Ahmedabad",
        latitude=23.03,
        longitude=72.58,
        status="active",
    )
    with db_session_factory() as session:
        session.add(camera)
        session.commit()
        camera_id = camera.id

    evidence_path = tmp_path / "review-evidence.db"
    _evidence_database(evidence_path, camera_id)
    with sqlite3.connect(evidence_path) as connection:
        connection.execute("ALTER TABLE plate_detections ADD ocr_selected_provider TEXT")
        connection.execute("ALTER TABLE plate_detections ADD ocr_decision TEXT")
        connection.execute(
            "ALTER TABLE plate_detections ADD ocr_review_required INTEGER DEFAULT 0"
        )
        connection.execute(
            """UPDATE plate_detections
               SET ocr_decision='review_required', ocr_review_required=1 WHERE id=9"""
        )

    router = LiveIntelligenceRouter(
        evidence_path,
        session_factory=db_session_factory,
        app_env="test",
        api_prefix="/api/v1",
    )
    with pytest.raises(LookupError, match="cannot be routed"):
        router._route_plate(9)

    with db_session_factory() as session:
        assert session.scalar(select(ANPREvent)) is None
