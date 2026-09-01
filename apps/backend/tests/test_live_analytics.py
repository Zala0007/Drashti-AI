from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.analytics.ocr import HybridOCRReconciler, OCRReading
from app.analytics.worker import (
    AnalyticsConfig,
    AnalyticsDetection,
    LiveAnalyticsWorker,
    _EvidenceWriter,
    _PlateConsensus,
)
from app.stream_engine.types import FramePacket, ProcessingStreamState


class FakeDetector:
    device = "cuda:0"
    model_name = "test-models"


def test_camera_result_routes_vehicle_and_plate_evidence(tmp_path: Path) -> None:
    database = tmp_path / "evidence.db"
    config = AnalyticsConfig(
        evidence_database=str(database),
        evidence_interval_seconds=1,
        ocr_enabled=False,
    )
    visual_queue: list[int] = []
    worker = LiveAnalyticsWorker(  # type: ignore[arg-type]
        SimpleNamespace(scheduler=SimpleNamespace(consumer_attached=True)),
        config,
        detector=FakeDetector(),
        on_vehicle_evidence=visual_queue.append,
    )
    worker._writer = _EvidenceWriter(str(database))
    packet = FramePacket(
        camera_id="00000000-0000-0000-0000-000000000001",
        stream_id="00000000-0000-0000-0000-000000000002",
        connection_id="00000000-0000-0000-0000-000000000003",
        frame_number=7,
        source_timestamp=None,
        capture_timestamp=datetime.now(UTC),
        receive_timestamp=datetime.now(UTC),
        width=160,
        height=90,
        source_fps=10,
        decoded_fps=10,
        source_type="rtsp",
        health_state=ProcessingStreamState.streaming,
        pixel_format="rgb24",
        payload=b"",
    )
    detections = [
        AnalyticsDetection("object", 2, "car", 0.91, 5, 5, 80, 70),
        AnalyticsDetection("object", 2, "car", 0.89, 85, 5, 150, 70),
        AnalyticsDetection("plate", 0, "license_plate", 0.88, 30, 45, 70, 60),
    ]

    worker._publish(packet, Image.new("RGB", (160, 90), "white"), detections, 12.5)

    result = worker.get(packet.camera_id)
    assert result is not None
    assert result.device == "cuda:0"
    assert [item.track_id for item in result.detections] == [1, 2, 1]
    assert set(result.routed_modules) == {
        "live_overlay",
        "plate_detection",
        "vehicle_database",
        "vehicle_detection",
        "visual_intelligence",
        "vehicle_reid",
    }
    assert worker.capabilities()["consumer_attached"] is True
    assert "visual_intelligence" in worker.capabilities()["routes"]
    assert "investigation" in worker.capabilities()["routes"]
    worker._writer.close()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM detections").fetchone()[0] == 2
        assert [row[0] for row in connection.execute("SELECT track_id FROM detections")] == [1, 2]
        assert connection.execute("SELECT COUNT(*) FROM plate_detections").fetchone()[0] == 1
        assert (
            connection.execute("SELECT source_detection_id FROM plate_detections").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT ocr_status FROM plate_detections").fetchone()[0] == "SKIPPED"
        )
    assert visual_queue == [1, 2]


def test_temporal_plate_consensus_uses_camera_scoped_tracks() -> None:
    consensus = _PlateConsensus(history_size=4)
    assert consensus.update("camera-1", 7, "GJ01AB1234", 0.72) == (
        "GJ01AB1234",
        0.72,
        1,
    )
    text, confidence, count = consensus.update("camera-1", 7, "GJ01AB1234", 0.88)
    assert text == "GJ01AB1234"
    assert confidence == 0.8
    assert count == 2
    assert consensus.update("camera-2", 7, "GJ02CD5678", 0.91) == (
        "GJ02CD5678",
        0.91,
        1,
    )


def test_evidence_writer_retains_both_ocr_candidates_and_final_decision(
    tmp_path: Path,
) -> None:
    database = tmp_path / "hybrid-evidence.db"
    writer = _EvidenceWriter(str(database))
    packet = FramePacket(
        camera_id="00000000-0000-0000-0000-000000000001",
        stream_id="00000000-0000-0000-0000-000000000002",
        connection_id="00000000-0000-0000-0000-000000000003",
        frame_number=8,
        source_timestamp=None,
        capture_timestamp=datetime.now(UTC),
        receive_timestamp=datetime.now(UTC),
        width=160,
        height=90,
        source_fps=10,
        decoded_fps=10,
        source_type="rtsp",
        health_state=ProcessingStreamState.streaming,
        pixel_format="rgb24",
        payload=b"",
    )
    row_id, _ = writer.plate(
        packet,
        Image.new("RGB", (160, 90), "white"),
        AnalyticsDetection("plate", 0, "license_plate", 0.9, 20, 30, 130, 65, track_id=4),
        source_detection_id=None,
        ocr_requested=True,
    )
    google = OCRReading(
        provider="google",
        text="GJ O1 AB 1234",
        raw_text="GJ O1 AB 1234",
        confidence=0.78,
        processing_ms=180,
    )
    groq = OCRReading(
        provider="groq",
        text="GJ01AB1234",
        raw_text="GJ01AB1234",
        confidence=0.94,
        processing_ms=520,
    )
    decision = HybridOCRReconciler().reconcile(google, groq)
    writer.complete_hybrid_ocr(
        row_id,
        google=google,
        groq=groq,
        decision=decision,
        consensus_text=decision.accepted_text,
        consensus_confidence=decision.confidence,
        consensus_count=1,
    )
    writer.close()

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM plate_detections WHERE id=?", (row_id,)
        ).fetchone()
    assert row is not None
    assert row["plate_text"] == "GJ01AB1234"
    assert row["google_ocr_text"] == "GJ01AB1234"
    assert row["groq_ocr_text"] == "GJ01AB1234"
    assert row["ocr_selected_provider"] == "hybrid"
    assert row["ocr_decision"] == "providers_agree"
    assert row["ocr_review_required"] == 0
    assert row["ocr_status"] == "COMPLETED"
