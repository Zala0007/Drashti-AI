from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from app.schemas.visual_intelligence import VehicleVisualProfile, VisualSearchFilters
from app.services.visual_intelligence import (
    VisionIntelligenceProvider,
    VisualIntelligenceEngine,
)


class FakeVisionProvider(VisionIntelligenceProvider):
    name = "test-provider"
    model = "test-vision-v1"

    def analyze_vehicle(self, image: bytes) -> VehicleVisualProfile:
        assert image.startswith(b"vehicle-jpeg")
        return VehicleVisualProfile(
            vehicle_present=True,
            vehicle_type="SUV",
            vehicle_type_confidence="high",
            primary_color="red",
            secondary_colors=["black"],
            visual_condition="possible visible damage around front bumper",
            damage_present="possible",
            damage_regions=[
                {
                    "location": "front bumper",
                    "description": "appears misaligned",
                    "confidence": "medium",
                }
            ],
            distinctive_features=["black roof rails"],
            accessories=["roof rails"],
            vehicle_view="front-left",
            plate_visibility="partial",
            lighting_condition="daylight",
            image_quality="good",
            occlusion="low",
            search_keywords=["red", "SUV", "front bumper damage", "roof rails"],
            short_description="Red SUV with black roof rails and possible front bumper damage.",
            detailed_description=(
                "A red SUV is visible from the front-left with black roof rails and "
                "possible front bumper damage."
            ),
            analysis_confidence="high",
        )

    def health_check(self) -> bool:
        return True


def _evidence_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE detections (
                id INTEGER PRIMARY KEY, source TEXT, frame INTEGER, time_ms REAL,
                track_id INTEGER, class_name TEXT, confidence REAL, width INTEGER,
                height INTEGER, crop BLOB, created_at TEXT
            );
            CREATE TABLE plate_detections (
                id INTEGER PRIMARY KEY, source_detection_id INTEGER, source TEXT,
                frame INTEGER, track_id INTEGER, plate_text TEXT,
                ocr_confidence REAL, detection_confidence REAL, crop BLOB
            );
            """
        )
        connection.execute(
            """INSERT INTO detections VALUES
               (1, 'camera:CAM-021', 42, 1000, 7, 'car', .92, 640, 360, ?,
                '2026-09-01T20:42:18Z')""",
            (b"vehicle-jpeg-2",),
        )
        connection.execute(
            """INSERT INTO plate_detections VALUES
               (3, 1, 'camera:CAM-021', 42, 7, NULL, NULL, .94, ?)""",
            (b"plate-jpeg",),
        )


def test_analyze_once_persist_and_search_with_explanations(tmp_path: Path) -> None:
    database = tmp_path / "crops.db"
    _evidence_database(database)
    engine = VisualIntelligenceEngine(
        database,
        api_prefix="/api/v1",
        provider=FakeVisionProvider(),
        auto_analyze=False,
        retry_attempts=1,
    )
    engine.startup()
    try:
        assert engine.queue_detection(1) is True
        deadline = time.time() + 3
        while engine.status().completed == 0 and time.time() < deadline:
            time.sleep(0.02)
        assert engine.status().completed == 1
        assert engine.queue_detection(1) is False

        # OCR completes asynchronously after the visual profile. Search refreshes the
        # linked plate value without resending the vehicle crop to Groq.
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE plate_detections SET plate_text='GJ01AB1234' WHERE id=3")
            connection.commit()

        response = engine.search(
            query="red damaged SUV with roof rails",
            filters=VisualSearchFilters(),
            page=1,
            page_size=10,
            actor_id="investigator-1",
        )
        assert response.total_results == 1
        result = response.results[0]
        assert result.match_level == "HIGH"
        assert result.anpr_plate == "GJ01AB1234"
        assert result.plate_crop_uri == "/api/v1/ai/plates/3/image"
        assert any("Colour: Red" in reason for reason in result.match_reasons)
        assert any("Vehicle type: SUV" in reason for reason in result.match_reasons)
    finally:
        engine.shutdown()


def test_backfill_advances_past_completed_representatives(tmp_path: Path) -> None:
    database = tmp_path / "crops.db"
    _evidence_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO detections VALUES
               (2, 'camera:CAM-021', 43, 1100, 7, 'car', .90, 620, 340, ?,
                '2026-09-01T20:42:19Z')""",
            (b"vehicle-jpeg",),
        )
        connection.commit()
    engine = VisualIntelligenceEngine(
        database,
        api_prefix="/api/v1",
        provider=FakeVisionProvider(),
        auto_analyze=False,
        retry_attempts=1,
        minimum_request_interval_seconds=0,
    )
    engine.startup()
    try:
        assert engine.backfill(1).queued == 1
        deadline = time.time() + 3
        while engine.status().completed < 1 and time.time() < deadline:
            time.sleep(0.02)
        assert engine.backfill(1).queued == 1
        deadline = time.time() + 3
        while engine.status().completed < 2 and time.time() < deadline:
            time.sleep(0.02)
        assert engine.status().completed == 2
    finally:
        engine.shutdown()


def test_groq_vision_provider_switches_key_on_rate_limit(monkeypatch) -> None:
    from unittest.mock import MagicMock
    from app.services.visual_intelligence import GroqVisionProvider

    call_log = []

    class MockCompletion:
        def __init__(self, key: str):
            self.key = key

        def create(self, **kwargs):
            call_log.append(self.key)
            if self.key == "key-1":
                raise RuntimeError("429 Too Many Requests: Rate limit exceeded")
            msg = MagicMock()
            msg.content = """
            {
                "vehicle_present": true,
                "vehicle_type": "car",
                "vehicle_type_confidence": "high",
                "primary_color": "white",
                "secondary_colors": [],
                "visual_condition": "clean",
                "damage_present": "none_obvious",
                "damage_regions": [],
                "distinctive_features": [],
                "accessories": [],
                "vehicle_view": "front",
                "plate_visibility": "readable",
                "lighting_condition": "daylight",
                "image_quality": "good",
                "occlusion": "none",
                "search_keywords": ["white", "car"],
                "short_description": "White car.",
                "detailed_description": "A white car.",
                "analysis_confidence": "high"
            }
            """
            choice = MagicMock()
            choice.message = msg
            res = MagicMock()
            res.choices = [choice]
            return res

    class MockGroq:
        def __init__(self, api_key: str, **kwargs):
            self.api_key = api_key
            self.chat = MagicMock()
            self.chat.completions = MockCompletion(api_key)

    monkeypatch.setattr("groq.Groq", MockGroq)

    provider = GroqVisionProvider(
        api_keys=("key-1", "key-2"),
        model="qwen/qwen3.6-27b",
        timeout=10.0,
        max_retries=1,
    )

    profile = provider.analyze_vehicle(b"dummy-image")
    assert profile.primary_color == "white"
    assert call_log == ["key-1", "key-2"]

