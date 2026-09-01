from __future__ import annotations

import io
import logging
import queue
import sqlite3
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from app.analytics.ocr import (
    GooglePlateOCR,
    GroqPlateOCR,
    HybridOCRReconciler,
    OCRDecision,
    OCRReading,
)
from app.stream_engine import StreamEngine
from app.stream_engine.types import FramePacket

logger = logging.getLogger("drishti.analytics")
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle"}


@dataclass(frozen=True, slots=True)
class AnalyticsConfig:
    enabled: bool = True
    general_model_path: str = "./AI-Features/models/yolo26n.pt"
    plate_model_path: str = "./AI-Features/models/license_plate_detector.pt"
    evidence_database: str = "./AI-Features/crops.db"
    confidence: float = 0.4
    plate_confidence: float = 0.35
    evidence_interval_seconds: float = 2.0
    ocr_enabled: bool = True
    ocr_timeout_seconds: float = 8.0
    ocr_cooldown_seconds: float = 4.0
    ocr_batch_size: int = 8
    google_accept_confidence: float = 0.86
    groq_ocr_enabled: bool = True
    groq_api_key: str | None = None
    groq_model: str = "qwen/qwen3.6-27b"
    groq_timeout_seconds: float = 45.0
    groq_max_retries: int = 2
    groq_accept_confidence: float = 0.82
    groq_minimum_interval_seconds: float = 0.5


@dataclass(frozen=True, slots=True)
class AnalyticsDetection:
    kind: str
    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    plate_text: str | None = None
    ocr_confidence: float | None = None
    track_id: int | None = None


@dataclass(frozen=True, slots=True)
class _TrackState:
    box: tuple[float, float, float, float]
    class_name: str
    last_seen: int


class _IoUTracker:
    """Small per-camera tracker; adds no model pass and never blocks inference."""

    def __init__(self, *, minimum_iou: float, maximum_misses: int) -> None:
        self.minimum_iou = minimum_iou
        self.maximum_misses = maximum_misses
        self._tick = 0
        self._next_id = 1
        self._tracks: dict[int, _TrackState] = {}

    @staticmethod
    def _iou(
        first: tuple[float, float, float, float],
        second: tuple[float, float, float, float],
    ) -> float:
        x1, y1 = max(first[0], second[0]), max(first[1], second[1])
        x2, y2 = min(first[2], second[2]), min(first[3], second[3])
        intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
        second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union else 0.0

    def update(self, detections: list[AnalyticsDetection]) -> list[int]:
        self._tick += 1
        active = {
            track_id: state
            for track_id, state in self._tracks.items()
            if self._tick - state.last_seen <= self.maximum_misses
        }
        assigned: list[int] = []
        used: set[int] = set()
        for detection in detections:
            box = (detection.x1, detection.y1, detection.x2, detection.y2)
            candidates = [
                (self._iou(box, state.box), track_id)
                for track_id, state in active.items()
                if track_id not in used and state.class_name == detection.class_name
            ]
            best_iou, track_id = max(candidates, default=(0.0, -1))
            if best_iou < self.minimum_iou:
                track_id = self._next_id
                self._next_id += 1
            self._tracks[track_id] = _TrackState(box, detection.class_name, self._tick)
            used.add(track_id)
            assigned.append(track_id)
        self._tracks = {
            track_id: state
            for track_id, state in self._tracks.items()
            if self._tick - state.last_seen <= self.maximum_misses
        }
        return assigned


class _PlateConsensus:
    """Confidence-weighted OCR voting scoped to one camera and plate track."""

    def __init__(self, history_size: int = 8) -> None:
        self.history_size = history_size
        self._histories: defaultdict[tuple[str, int], deque[tuple[str, float]]] = defaultdict(
            lambda: deque(maxlen=self.history_size)
        )
        self._last_seen: dict[tuple[str, int], float] = {}

    def update(
        self, camera_id: str, track_id: int | None, text: str, confidence: float
    ) -> tuple[str, float, int]:
        if track_id is None:
            return text, confidence, int(bool(text))
        key = (camera_id, track_id)
        now = time.monotonic()
        if text:
            self._histories[key].append((text, confidence))
        self._last_seen[key] = now
        expired = [item for item, seen in self._last_seen.items() if now - seen > 600]
        for item in expired:
            self._last_seen.pop(item, None)
            self._histories.pop(item, None)
        history = self._histories[key]
        if not history:
            return "", 0.0, 0
        weighted: defaultdict[str, float] = defaultdict(float)
        confidences: defaultdict[str, list[float]] = defaultdict(list)
        for candidate, candidate_confidence in history:
            weighted[candidate] += max(candidate_confidence, 0.01)
            confidences[candidate].append(candidate_confidence)
        winner = max(weighted, key=weighted.get)
        winner_confidences = confidences[winner]
        return (
            winner,
            sum(winner_confidences) / len(winner_confidences),
            len(history),
        )


@dataclass(frozen=True, slots=True)
class CameraAnalytics:
    camera_id: str
    stream_id: str
    frame_number: int
    observed_at: datetime
    status: str
    model: str
    device: str
    inference_ms: float
    detections: tuple[AnalyticsDetection, ...] = ()
    routed_modules: tuple[str, ...] = ()
    error_message: str | None = None


class Detector(Protocol):
    device: str
    model_name: str

    def predict(
        self, packets: tuple[FramePacket, ...]
    ) -> list[tuple[Image.Image, list[AnalyticsDetection]]]: ...


class _UltralyticsDetector:
    def __init__(self, config: AnalyticsConfig) -> None:
        try:
            import torch
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Ultralytics analytics dependencies are not installed") from exc
        general_path = Path(config.general_model_path).expanduser().resolve()
        plate_path = Path(config.plate_model_path).expanduser().resolve()
        if not general_path.is_file() or not plate_path.is_file():
            raise RuntimeError("Configured analytics model files are unavailable")
        self._general = YOLO(str(general_path))
        self._plate = YOLO(str(plate_path))
        self._confidence = config.confidence
        self._plate_confidence = config.plate_confidence
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self._device_argument: int | str = 0 if self.device.startswith("cuda") else "cpu"
        self.model_name = f"{general_path.name} + {plate_path.name}"

    @staticmethod
    def _detections(result: Any, *, kind: str) -> list[AnalyticsDetection]:
        boxes = result.boxes
        if boxes is None or not len(boxes):
            return []
        coordinates = boxes.xyxy.cpu().tolist()
        scores = boxes.conf.cpu().tolist()
        classes = boxes.cls.int().cpu().tolist()
        names = result.names
        detections: list[AnalyticsDetection] = []
        for box, score, class_id in zip(coordinates, scores, classes, strict=True):
            name = "license_plate" if kind == "plate" else str(names[class_id])
            detections.append(
                AnalyticsDetection(
                    kind=kind,
                    class_id=int(class_id),
                    class_name=name,
                    confidence=round(float(score), 4),
                    x1=float(box[0]),
                    y1=float(box[1]),
                    x2=float(box[2]),
                    y2=float(box[3]),
                )
            )
        return detections

    def predict(
        self, packets: tuple[FramePacket, ...]
    ) -> list[tuple[Image.Image, list[AnalyticsDetection]]]:
        images = [
            Image.frombytes("RGB", (packet.width, packet.height), packet.payload)
            for packet in packets
        ]
        general = self._general.predict(
            source=images,
            conf=self._confidence,
            device=self._device_argument,
            verbose=False,
        )
        plates = self._plate.predict(
            source=images,
            conf=self._plate_confidence,
            device=self._device_argument,
            verbose=False,
        )
        return [
            (
                image,
                [
                    *self._detections(general_result, kind="object"),
                    *self._detections(plate_result, kind="plate"),
                ],
            )
            for image, general_result, plate_result in zip(images, general, plates, strict=True)
        ]


class _EvidenceWriter:
    def __init__(self, path: str) -> None:
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(resolved), check_same_thread=False, timeout=5)
        self._lock = threading.Lock()
        with self._connection:
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                    frame INTEGER NOT NULL, time_ms REAL NOT NULL, track_id INTEGER,
                    class_id INTEGER NOT NULL, class_name TEXT NOT NULL,
                    confidence REAL NOT NULL, x1 REAL NOT NULL, y1 REAL NOT NULL,
                    x2 REAL NOT NULL, y2 REAL NOT NULL, width INTEGER NOT NULL,
                    height INTEGER NOT NULL, crop BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_class ON detections(class_name);
                CREATE INDEX IF NOT EXISTS idx_frame ON detections(source, frame);
                CREATE INDEX IF NOT EXISTS idx_track ON detections(source, track_id);
                CREATE INDEX IF NOT EXISTS idx_detection_latest
                    ON detections(created_at DESC, id DESC);
                CREATE TABLE IF NOT EXISTS plate_detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_detection_id INTEGER, source TEXT NOT NULL,
                    frame INTEGER NOT NULL, time_ms REAL NOT NULL, track_id INTEGER,
                    plate_text TEXT, ocr_confidence REAL,
                    detection_confidence REAL NOT NULL, x1 REAL NOT NULL,
                    y1 REAL NOT NULL, x2 REAL NOT NULL, y2 REAL NOT NULL,
                    width INTEGER NOT NULL, height INTEGER NOT NULL,
                    crop BLOB NOT NULL, ocr_provider TEXT NOT NULL,
                    ocr_status TEXT NOT NULL DEFAULT 'PENDING',
                    ocr_error TEXT,
                    ocr_attempt_count INTEGER NOT NULL DEFAULT 0,
                    ocr_raw_text TEXT,
                    ocr_raw_confidence REAL,
                    ocr_consensus_count INTEGER NOT NULL DEFAULT 0,
                    google_ocr_raw_text TEXT,
                    google_ocr_text TEXT,
                    google_ocr_confidence REAL,
                    google_ocr_processing_ms REAL,
                    google_ocr_error TEXT,
                    groq_ocr_raw_text TEXT,
                    groq_ocr_text TEXT,
                    groq_ocr_confidence REAL,
                    groq_ocr_processing_ms REAL,
                    groq_ocr_error TEXT,
                    groq_ocr_attempt_count INTEGER NOT NULL DEFAULT 0,
                    ocr_selected_provider TEXT,
                    ocr_decision TEXT,
                    ocr_decision_reason TEXT,
                    ocr_review_required INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_plate_text ON plate_detections(plate_text);
                CREATE INDEX IF NOT EXISTS idx_plate_source_frame
                    ON plate_detections(source, frame);
                CREATE INDEX IF NOT EXISTS idx_plate_latest
                    ON plate_detections(created_at DESC, id DESC);
                """
            )
            columns = {
                str(row[1])
                for row in self._connection.execute("PRAGMA table_info(plate_detections)")
            }
            if "ocr_status" not in columns:
                self._connection.execute(
                    "ALTER TABLE plate_detections ADD COLUMN ocr_status "
                    "TEXT NOT NULL DEFAULT 'PENDING'"
                )
            if "ocr_error" not in columns:
                self._connection.execute("ALTER TABLE plate_detections ADD COLUMN ocr_error TEXT")
            if "ocr_attempt_count" not in columns:
                self._connection.execute(
                    "ALTER TABLE plate_detections ADD COLUMN ocr_attempt_count "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "ocr_raw_text" not in columns:
                self._connection.execute(
                    "ALTER TABLE plate_detections ADD COLUMN ocr_raw_text TEXT"
                )
            if "ocr_raw_confidence" not in columns:
                self._connection.execute(
                    "ALTER TABLE plate_detections ADD COLUMN ocr_raw_confidence REAL"
                )
            if "ocr_consensus_count" not in columns:
                self._connection.execute(
                    "ALTER TABLE plate_detections ADD COLUMN ocr_consensus_count "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            hybrid_columns = {
                "google_ocr_raw_text": "TEXT",
                "google_ocr_text": "TEXT",
                "google_ocr_confidence": "REAL",
                "google_ocr_processing_ms": "REAL",
                "google_ocr_error": "TEXT",
                "groq_ocr_raw_text": "TEXT",
                "groq_ocr_text": "TEXT",
                "groq_ocr_confidence": "REAL",
                "groq_ocr_processing_ms": "REAL",
                "groq_ocr_error": "TEXT",
                "groq_ocr_attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "ocr_selected_provider": "TEXT",
                "ocr_decision": "TEXT",
                "ocr_decision_reason": "TEXT",
                "ocr_review_required": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, column_type in hybrid_columns.items():
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE plate_detections ADD COLUMN {name} {column_type}"
                    )
            self._connection.execute(
                """UPDATE plate_detections
                   SET ocr_status=CASE
                       WHEN plate_text IS NOT NULL AND plate_text != '' THEN 'COMPLETED'
                       WHEN ocr_status='PROCESSING' THEN 'RETRY_PENDING'
                       WHEN ocr_status='GROQ_PROCESSING' THEN 'GROQ_RETRY_PENDING'
                       ELSE ocr_status
                   END"""
            )

    @staticmethod
    def _crop(
        image: Image.Image,
        detection: AnalyticsDetection,
        *,
        horizontal_padding: float = 0.0,
        vertical_padding: float = 0.0,
    ) -> tuple[bytes, int, int]:
        width = max(1.0, detection.x2 - detection.x1)
        height = max(1.0, detection.y2 - detection.y1)
        left = max(0, int(detection.x1 - width * horizontal_padding))
        top = max(0, int(detection.y1 - height * vertical_padding))
        right = min(image.width, int(detection.x2 + width * horizontal_padding))
        bottom = min(image.height, int(detection.y2 + height * vertical_padding))
        crop = image.crop((left, top, right, bottom))
        output = io.BytesIO()
        crop.save(output, format="JPEG", quality=90)
        return output.getvalue(), crop.width, crop.height

    def vehicle(
        self, packet: FramePacket, image: Image.Image, detection: AnalyticsDetection
    ) -> int:
        crop, width, height = self._crop(image, detection)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO detections (
                    source, frame, time_ms, track_id, class_id, class_name,
                    confidence, x1, y1, x2, y2, width, height, crop
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"camera:{packet.camera_id}",
                    packet.frame_number,
                    packet.capture_timestamp.timestamp() * 1000,
                    detection.track_id,
                    detection.class_id,
                    detection.class_name,
                    detection.confidence,
                    detection.x1,
                    detection.y1,
                    detection.x2,
                    detection.y2,
                    width,
                    height,
                    crop,
                ),
            )
            return int(cursor.lastrowid)

    def plate(
        self,
        packet: FramePacket,
        image: Image.Image,
        detection: AnalyticsDetection,
        *,
        source_detection_id: int | None,
        ocr_requested: bool,
    ) -> tuple[int, bytes]:
        crop, width, height = self._crop(
            image,
            detection,
            horizontal_padding=0.08,
            vertical_padding=0.15,
        )
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO plate_detections (
                    source_detection_id, source, frame, time_ms, track_id,
                    plate_text, ocr_confidence, detection_confidence,
                    x1, y1, x2, y2, width, height, crop, ocr_provider, ocr_status
                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_detection_id,
                    f"camera:{packet.camera_id}",
                    packet.frame_number,
                    packet.capture_timestamp.timestamp() * 1000,
                    detection.track_id,
                    detection.confidence,
                    detection.x1,
                    detection.y1,
                    detection.x2,
                    detection.y2,
                    width,
                    height,
                    crop,
                    "google-cloud-vision:document-text-detection-v1",
                    "PENDING" if ocr_requested else "SKIPPED",
                ),
            )
            return int(cursor.lastrowid), crop

    def update_ocr(
        self,
        row_id: int,
        *,
        raw_text: str,
        raw_confidence: float,
        consensus_text: str,
        consensus_confidence: float,
        consensus_count: int,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """UPDATE plate_detections
                   SET plate_text=?, ocr_confidence=?, ocr_raw_text=?,
                       ocr_raw_confidence=?, ocr_consensus_count=?,
                       ocr_status='COMPLETED', ocr_error=NULL
                   WHERE id=?""",
                (
                    consensus_text or None,
                    consensus_confidence,
                    raw_text or None,
                    raw_confidence,
                    consensus_count,
                    row_id,
                ),
            )

    def request_groq_fallback(
        self, row_id: int, google: OCRReading | None, reason: str
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """UPDATE plate_detections
                   SET google_ocr_raw_text=?, google_ocr_text=?,
                       google_ocr_confidence=?, google_ocr_processing_ms=?,
                       google_ocr_error=?, ocr_status='GROQ_PENDING',
                       ocr_decision='FALLBACK_REQUIRED', ocr_decision_reason=?,
                       ocr_review_required=0, ocr_error=NULL
                   WHERE id=?""",
                (
                    google.raw_text if google else None,
                    google.normalized_text if google else None,
                    google.confidence if google else None,
                    google.processing_ms if google else None,
                    google.error if google else None,
                    reason,
                    row_id,
                ),
            )

    def complete_hybrid_ocr(
        self,
        row_id: int,
        *,
        google: OCRReading | None,
        groq: OCRReading | None,
        decision: OCRDecision,
        consensus_text: str,
        consensus_confidence: float,
        consensus_count: int,
    ) -> None:
        selected = google if decision.provider == "google" else groq
        if decision.provider == "hybrid":
            selected = groq or google
        final_text = consensus_text if decision.status == "ACCEPTED" else ""
        final_confidence = consensus_confidence if final_text else 0.0
        with self._lock, self._connection:
            self._connection.execute(
                """UPDATE plate_detections
                   SET plate_text=?, ocr_confidence=?, ocr_raw_text=?,
                       ocr_raw_confidence=?, ocr_consensus_count=?,
                       google_ocr_raw_text=?, google_ocr_text=?,
                       google_ocr_confidence=?, google_ocr_processing_ms=?,
                       google_ocr_error=?, groq_ocr_raw_text=?, groq_ocr_text=?,
                       groq_ocr_confidence=?, groq_ocr_processing_ms=?, groq_ocr_error=?,
                       ocr_selected_provider=?, ocr_provider=?, ocr_decision=?,
                       ocr_decision_reason=?, ocr_review_required=?, ocr_status=?,
                       ocr_error=NULL
                   WHERE id=?""",
                (
                    final_text or None,
                    final_confidence,
                    selected.raw_text if selected else None,
                    selected.confidence if selected else None,
                    consensus_count,
                    google.raw_text if google else None,
                    google.normalized_text if google else None,
                    google.confidence if google else None,
                    google.processing_ms if google else None,
                    google.error if google else None,
                    groq.raw_text if groq else None,
                    groq.normalized_text if groq else None,
                    groq.confidence if groq else None,
                    groq.processing_ms if groq else None,
                    groq.error if groq else None,
                    decision.provider,
                    f"hybrid-ocr:{decision.provider or 'unresolved'}",
                    (
                        "providers_agree"
                        if decision.provider == "hybrid"
                        else "google_primary"
                        if decision.provider == "google"
                        else "groq_fallback"
                        if decision.provider == "groq"
                        else "review_required"
                    ),
                    decision.reason,
                    int(decision.review_required),
                    "COMPLETED" if final_text else "REVIEW_REQUIRED",
                    row_id,
                ),
            )

    def begin_ocr(self, row_id: int) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """UPDATE plate_detections
                   SET ocr_status='PROCESSING', ocr_attempt_count=ocr_attempt_count + 1,
                       ocr_error=NULL
                   WHERE id=? AND ocr_status IN ('PENDING', 'RETRY_PENDING')""",
                (row_id,),
            )
            return cursor.rowcount == 1

    def fail_ocr(self, row_id: int, error: Exception, *, max_attempts: int = 3) -> int:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT ocr_attempt_count FROM plate_detections WHERE id=?", (row_id,)
            ).fetchone()
            attempts = int(row[0]) if row else max_attempts
            status = "RETRY_PENDING" if attempts < max_attempts else "FAILED"
            self._connection.execute(
                """UPDATE plate_detections SET ocr_status=?, ocr_error=? WHERE id=?""",
                (status, f"{type(error).__name__}: {str(error)[:300]}", row_id),
            )
            return attempts

    def fail_google(
        self,
        row_id: int,
        error: Exception,
        *,
        fallback_available: bool,
        max_attempts: int = 3,
    ) -> int:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT ocr_attempt_count FROM plate_detections WHERE id=?", (row_id,)
            ).fetchone()
            attempts = int(row[0]) if row else max_attempts
            if attempts < max_attempts:
                status = "RETRY_PENDING"
            elif fallback_available:
                status = "GROQ_PENDING"
            else:
                status = "FAILED"
            self._connection.execute(
                """UPDATE plate_detections
                   SET ocr_status=?, google_ocr_error=?, ocr_error=? WHERE id=?""",
                (
                    status,
                    f"{type(error).__name__}: {str(error)[:300]}",
                    f"{type(error).__name__}: {str(error)[:300]}",
                    row_id,
                ),
            )
            return attempts

    def begin_groq(self, row_id: int) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """UPDATE plate_detections
                   SET ocr_status='GROQ_PROCESSING',
                       groq_ocr_attempt_count=groq_ocr_attempt_count + 1,
                       groq_ocr_error=NULL
                   WHERE id=? AND ocr_status IN ('GROQ_PENDING', 'GROQ_RETRY_PENDING')""",
                (row_id,),
            )
            return cursor.rowcount == 1

    def fail_groq(self, row_id: int, error: Exception, *, max_attempts: int = 3) -> int:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT groq_ocr_attempt_count FROM plate_detections WHERE id=?", (row_id,)
            ).fetchone()
            attempts = int(row[0]) if row else max_attempts
            status = "GROQ_RETRY_PENDING" if attempts < max_attempts else "REVIEW_REQUIRED"
            self._connection.execute(
                """UPDATE plate_detections
                   SET ocr_status=?, groq_ocr_error=?, ocr_error=?,
                       ocr_decision='provider_failure',
                       ocr_decision_reason='Groq fallback failed; officer review is required',
                       ocr_review_required=1
                   WHERE id=?""",
                (
                    status,
                    f"{type(error).__name__}: {str(error)[:300]}",
                    f"{type(error).__name__}: {str(error)[:300]}",
                    row_id,
                ),
            )
            return attempts

    def pending_ocr(self) -> _OCRJob | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT id, source, frame, track_id, crop, x1, y1, x2, y2
                   FROM plate_detections
                   WHERE ocr_status IN ('PENDING', 'RETRY_PENDING')
                         AND ocr_attempt_count < 3
                   ORDER BY created_at ASC, id ASC LIMIT 1"""
            ).fetchone()
        if row is None:
            return None
        return _OCRJob(
            row_id=int(row[0]),
            camera_id=str(row[1]).removeprefix("camera:"),
            stream_id="persisted-evidence",
            frame_number=int(row[2]),
            track_id=int(row[3]) if row[3] is not None else None,
            crop=bytes(row[4]),
            x1=float(row[5]),
            y1=float(row[6]),
            x2=float(row[7]),
            y2=float(row[8]),
        )

    def pending_groq(self) -> _GroqOCRJob | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT id, source, frame, track_id, crop, x1, y1, x2, y2,
                          google_ocr_raw_text, google_ocr_text,
                          google_ocr_confidence, google_ocr_processing_ms,
                          google_ocr_error
                   FROM plate_detections
                   WHERE ocr_status IN ('GROQ_PENDING', 'GROQ_RETRY_PENDING')
                         AND groq_ocr_attempt_count < 3
                   ORDER BY created_at ASC, id ASC LIMIT 1"""
            ).fetchone()
        if row is None:
            return None
        job = _OCRJob(
            row_id=int(row[0]),
            camera_id=str(row[1]).removeprefix("camera:"),
            stream_id="persisted-evidence",
            frame_number=int(row[2]),
            track_id=int(row[3]) if row[3] is not None else None,
            crop=bytes(row[4]),
            x1=float(row[5]),
            y1=float(row[6]),
            x2=float(row[7]),
            y2=float(row[8]),
        )
        google = OCRReading(
            provider="google",
            text=str(row[10] or row[9] or ""),
            raw_text=str(row[9] or ""),
            confidence=float(row[11] or 0),
            processing_ms=float(row[12]) if row[12] is not None else None,
            error=str(row[13]) if row[13] else None,
        )
        return _GroqOCRJob(job=job, google=google)

    def close(self) -> None:
        with self._lock:
            self._connection.close()


@dataclass(frozen=True, slots=True)
class _OCRJob:
    row_id: int
    camera_id: str
    stream_id: str
    frame_number: int
    track_id: int | None
    crop: bytes
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True, slots=True)
class _GroqOCRJob:
    job: _OCRJob
    google: OCRReading | None


class LiveAnalyticsWorker:
    """Bounded, latest-frame AI consumer shared by all active cameras."""

    def __init__(
        self,
        engine: StreamEngine,
        config: AnalyticsConfig,
        *,
        detector: Detector | None = None,
        on_vehicle_evidence: Callable[[int], None] | None = None,
        on_plate_evidence: Callable[[int], None] | None = None,
    ) -> None:
        self.engine = engine
        self.config = config
        self._detector = detector
        self._writer: _EvidenceWriter | None = None
        self._ocr: GooglePlateOCR | None = None
        self._groq_ocr: GroqPlateOCR | None = None
        self._ocr_reconciler = HybridOCRReconciler(
            google_accept_confidence=config.google_accept_confidence,
            groq_accept_confidence=config.groq_accept_confidence,
        )
        self._results: dict[str, CameraAnalytics] = {}
        self._last_evidence: dict[str, float] = {}
        self._last_ocr: dict[str, float] = {}
        self._vehicle_trackers: dict[str, _IoUTracker] = {}
        self._plate_trackers: dict[str, _IoUTracker] = {}
        self._plate_consensus = _PlateConsensus()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ocr_thread: threading.Thread | None = None
        self._groq_ocr_thread: threading.Thread | None = None
        self._ocr_queue: queue.Queue[_OCRJob] = queue.Queue(maxsize=256)
        self._groq_ocr_queue: queue.Queue[_GroqOCRJob] = queue.Queue(maxsize=128)
        self._last_groq_ocr_request = 0.0
        self._status = "disabled" if not config.enabled else "initializing"
        self._reason: str | None = None
        self._on_vehicle_evidence = on_vehicle_evidence
        self._on_plate_evidence = on_plate_evidence

    def set_vehicle_evidence_callback(self, callback: Callable[[int], None] | None) -> None:
        self._on_vehicle_evidence = callback

    def set_plate_evidence_callback(self, callback: Callable[[int], None] | None) -> None:
        self._on_plate_evidence = callback

    def startup(self) -> None:
        if not self.config.enabled or self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="drishti-live-ai", daemon=True)
        self._thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in (self._thread, self._ocr_thread, self._groq_ocr_thread):
            if thread and thread is not threading.current_thread():
                thread.join(timeout=timeout)
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def _run(self) -> None:
        try:
            detector = self._detector or _UltralyticsDetector(self.config)
            self._detector = detector
            self._writer = _EvidenceWriter(self.config.evidence_database)
        except Exception as exc:
            self._status = "unavailable"
            self._reason = str(exc)
            logger.warning("Live analytics unavailable: %s", type(exc).__name__)
            return
        self._status = "active"
        if self.config.ocr_enabled:
            self._ocr_thread = threading.Thread(
                target=self._run_ocr, name="drishti-google-plate-ocr", daemon=True
            )
            self._ocr_thread.start()
            if self._groq_fallback_available:
                self._groq_ocr_thread = threading.Thread(
                    target=self._run_groq_ocr,
                    name="drishti-groq-plate-ocr",
                    daemon=True,
                )
                self._groq_ocr_thread.start()
        while not self._stop.is_set():
            batch = self.engine.next_batch(timeout=0.5)
            if batch is None:
                continue
            started = time.perf_counter()
            try:
                inferred = detector.predict(batch.packets)
                elapsed = (time.perf_counter() - started) * 1000
                for packet, (image, detections) in zip(batch.packets, inferred, strict=True):
                    self._publish(packet, image, detections, elapsed / len(batch.packets))
            except Exception as exc:
                self._reason = "An inference batch failed; the worker is continuing"
                logger.warning("Live inference batch failed: %s", type(exc).__name__)

    def _publish(
        self,
        packet: FramePacket,
        image: Image.Image,
        detections: list[AnalyticsDetection],
        inference_ms: float,
    ) -> None:
        detections = self._assign_tracks(packet.camera_id, detections)
        modules = {"live_overlay"}
        now = time.monotonic()
        vehicles = [item for item in detections if item.class_name in VEHICLE_CLASSES]
        plates = [item for item in detections if item.kind == "plate"]
        if vehicles:
            modules.update(("vehicle_detection", "vehicle_database", "visual_intelligence"))
        if plates:
            modules.add("plate_detection")

        vehicle_due = (
            bool(vehicles)
            and now - self._last_evidence.get(packet.camera_id, 0)
            >= self.config.evidence_interval_seconds
        )
        plate_due = (
            bool(plates)
            and now - self._last_ocr.get(packet.camera_id, 0) >= self.config.ocr_cooldown_seconds
        )
        # Retain every vehicle in the selected evidence frame. A plate evidence frame
        # also retains its containing vehicle so the two crops can be verified together.
        retain_vehicles = vehicle_due or plate_due
        retained: list[tuple[AnalyticsDetection, int]] = []
        if retain_vehicles:
            assert self._writer is not None
            for detection in vehicles:
                retained.append((detection, self._writer.vehicle(packet, image, detection)))
            if vehicles:
                self._last_evidence[packet.camera_id] = now

        ocr_allowed = self.config.ocr_enabled and "anpr" in packet.ai_capabilities
        if ocr_allowed and plates:
            modules.update(("cloud_ocr", "hybrid_ocr"))
        if plate_due:
            assert self._writer is not None
            for detection in plates:
                parent_id = self._parent_vehicle(detection, retained)
                row_id, crop = self._writer.plate(
                    packet,
                    image,
                    detection,
                    source_detection_id=parent_id,
                    ocr_requested=ocr_allowed,
                )
                if ocr_allowed:
                    try:
                        self._ocr_queue.put_nowait(
                            _OCRJob(
                                row_id,
                                packet.camera_id,
                                packet.stream_id,
                                packet.frame_number,
                                detection.track_id,
                                crop,
                                detection.x1,
                                detection.y1,
                                detection.x2,
                                detection.y2,
                            )
                        )
                    except queue.Full:
                        # The durable PENDING row is recovered by the OCR worker.
                        self._reason = "Cloud OCR queue saturated; persisted crops will retry"
            self._last_ocr[packet.camera_id] = now

        if self._on_vehicle_evidence:
            modules.add("vehicle_reid")
            for _, detection_id in retained:
                try:
                    self._on_vehicle_evidence(detection_id)
                except Exception as exc:
                    logger.warning(
                        "Visual Intelligence enqueue failed for detection %s: %s",
                        detection_id,
                        type(exc).__name__,
                    )
        result = CameraAnalytics(
            camera_id=packet.camera_id,
            stream_id=packet.stream_id,
            frame_number=packet.frame_number,
            observed_at=datetime.now(UTC),
            status="active",
            model=self._detector.model_name if self._detector else "unavailable",
            device=self._detector.device if self._detector else "unavailable",
            inference_ms=round(inference_ms, 2),
            detections=tuple(detections),
            routed_modules=tuple(sorted(modules)),
        )
        with self._lock:
            self._results[packet.camera_id] = result

    def _assign_tracks(
        self, camera_id: str, detections: list[AnalyticsDetection]
    ) -> list[AnalyticsDetection]:
        vehicles = [item for item in detections if item.class_name in VEHICLE_CLASSES]
        plates = [item for item in detections if item.kind == "plate"]
        vehicle_tracker = self._vehicle_trackers.setdefault(
            camera_id, _IoUTracker(minimum_iou=0.18, maximum_misses=15)
        )
        plate_tracker = self._plate_trackers.setdefault(
            camera_id, _IoUTracker(minimum_iou=0.1, maximum_misses=60)
        )
        vehicle_ids = iter(vehicle_tracker.update(vehicles))
        plate_ids = iter(plate_tracker.update(plates))
        tracked: list[AnalyticsDetection] = []
        for detection in detections:
            if detection.class_name in VEHICLE_CLASSES:
                tracked.append(replace(detection, track_id=next(vehicle_ids)))
            elif detection.kind == "plate":
                tracked.append(replace(detection, track_id=next(plate_ids)))
            else:
                tracked.append(detection)
        return tracked

    @staticmethod
    def _parent_vehicle(
        plate: AnalyticsDetection,
        retained: list[tuple[AnalyticsDetection, int]],
    ) -> int | None:
        center_x = (plate.x1 + plate.x2) / 2
        center_y = (plate.y1 + plate.y2) / 2
        containing = [
            item
            for item in retained
            if item[0].x1 <= center_x <= item[0].x2 and item[0].y1 <= center_y <= item[0].y2
        ]
        if not containing:
            return None
        _, detection_id = min(
            containing,
            key=lambda item: (item[0].x2 - item[0].x1) * (item[0].y2 - item[0].y1),
        )
        return detection_id

    @property
    def _groq_fallback_available(self) -> bool:
        return bool(
            self.config.groq_ocr_enabled
            and self.config.groq_api_key
            and self.config.groq_model
        )

    def _run_ocr(self) -> None:
        try:
            self._ocr = GooglePlateOCR(self.config.ocr_timeout_seconds)
        except Exception as exc:
            self._reason = f"Google OCR unavailable; Groq fallback remains eligible: {exc}"
            self._ocr = None
        while not self._stop.is_set():
            jobs = self._google_batch()
            if not jobs:
                continue
            assert self._writer is not None
            claimed = [job for job in jobs if self._writer.begin_ocr(job.row_id)]
            if not claimed:
                continue
            if self._ocr is None:
                error = RuntimeError("Google Cloud Vision provider is unavailable")
                for job in claimed:
                    self._handle_google_failure(job, error, immediate_fallback=True)
                continue
            try:
                readings = self._ocr.recognize_batch([job.crop for job in claimed])
                if len(readings) != len(claimed):
                    raise RuntimeError("Google OCR returned an incomplete response batch")
                for job, reading in zip(claimed, readings, strict=True):
                    if reading.error:
                        self._handle_google_failure(job, RuntimeError(reading.error))
                    else:
                        self._handle_google_reading(job, reading)
            except Exception as exc:
                self._reason = f"Google OCR request failed: {type(exc).__name__}"
                for job in claimed:
                    self._handle_google_failure(job, exc)

    def _google_batch(self) -> list[_OCRJob]:
        assert self._writer is not None
        try:
            first = self._ocr_queue.get(timeout=0.35)
        except queue.Empty:
            recovered = self._writer.pending_ocr()
            return [recovered] if recovered else []
        jobs = [first]
        deadline = time.monotonic() + 0.025
        while len(jobs) < self.config.ocr_batch_size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                jobs.append(self._ocr_queue.get(timeout=remaining))
            except queue.Empty:
                break
        return jobs

    def _handle_google_failure(
        self, job: _OCRJob, error: Exception, *, immediate_fallback: bool = False
    ) -> None:
        assert self._writer is not None
        if immediate_fallback and self._groq_fallback_available:
            google = OCRReading(
                provider="google", text="", confidence=0.0, error=str(error)
            )
            self._writer.request_groq_fallback(job.row_id, google, str(error))
            self._enqueue_groq(_GroqOCRJob(job=job, google=google))
            return
        attempts = self._writer.fail_google(
            job.row_id,
            error,
            fallback_available=self._groq_fallback_available,
        )
        if attempts >= 3 and self._groq_fallback_available:
            google = OCRReading(
                provider="google", text="", confidence=0.0, error=str(error)
            )
            self._enqueue_groq(_GroqOCRJob(job=job, google=google))
        else:
            self._stop.wait(min(2**attempts, 8))

    def _handle_google_reading(self, job: _OCRJob, google: OCRReading) -> None:
        assert self._writer is not None
        decision = self._ocr_reconciler.google_decision(google)
        if decision.needs_fallback and self._groq_fallback_available:
            self._writer.request_groq_fallback(job.row_id, google, decision.reason)
            self._enqueue_groq(_GroqOCRJob(job=job, google=google))
            return
        if decision.needs_fallback:
            decision = self._ocr_reconciler.reconcile(google, None)
        self._complete_ocr_job(job, google=google, groq=None, decision=decision)

    def _enqueue_groq(self, job: _GroqOCRJob) -> None:
        try:
            self._groq_ocr_queue.put_nowait(job)
        except queue.Full:
            self._reason = "Groq OCR queue saturated; persisted fallbacks will retry"

    def _run_groq_ocr(self) -> None:
        assert self.config.groq_api_key
        try:
            self._groq_ocr = GroqPlateOCR(
                api_key=self.config.groq_api_key,
                model=self.config.groq_model,
                timeout=self.config.groq_timeout_seconds,
                max_retries=self.config.groq_max_retries,
            )
        except Exception as exc:
            self._reason = f"Groq OCR fallback unavailable: {exc}"
            return
        while not self._stop.is_set():
            try:
                queued = self._groq_ocr_queue.get(timeout=0.5)
            except queue.Empty:
                assert self._writer is not None
                queued = self._writer.pending_groq()
                if queued is None:
                    continue
            assert self._writer is not None
            if not self._writer.begin_groq(queued.job.row_id):
                continue
            try:
                elapsed = time.monotonic() - self._last_groq_ocr_request
                wait_for = self.config.groq_minimum_interval_seconds - elapsed
                if wait_for > 0 and self._stop.wait(wait_for):
                    return
                self._last_groq_ocr_request = time.monotonic()
                assert self._groq_ocr is not None
                groq = self._groq_ocr.recognize(queued.job.crop)
                decision = self._ocr_reconciler.reconcile(queued.google, groq)
                self._complete_ocr_job(
                    queued.job,
                    google=queued.google,
                    groq=groq,
                    decision=decision,
                )
            except Exception as exc:
                self._reason = f"Groq OCR fallback failed: {type(exc).__name__}"
                attempts = self._writer.fail_groq(queued.job.row_id, exc)
                self._stop.wait(min(2**attempts, 8))

    def _complete_ocr_job(
        self,
        job: _OCRJob,
        *,
        google: OCRReading | None,
        groq: OCRReading | None,
        decision: OCRDecision,
    ) -> None:
        text, confidence, consensus_count = self._plate_consensus.update(
            job.camera_id,
            job.track_id,
            decision.accepted_text,
            decision.confidence,
        )
        assert self._writer is not None
        self._writer.complete_hybrid_ocr(
            job.row_id,
            google=google,
            groq=groq,
            decision=decision,
            consensus_text=text,
            consensus_confidence=confidence,
            consensus_count=consensus_count,
        )
        routed_to_investigation = False
        if text and not decision.review_required and self._on_plate_evidence:
            try:
                self._on_plate_evidence(job.row_id)
                routed_to_investigation = True
            except Exception as exc:
                logger.warning(
                    "Investigation handoff enqueue failed for plate %s: %s",
                    job.row_id,
                    type(exc).__name__,
                )
        with self._lock:
            result = self._results.get(job.camera_id)
            if not (
                result
                and result.stream_id == job.stream_id
                and result.frame_number == job.frame_number
            ):
                return
            changed = False
            revised: list[AnalyticsDetection] = []
            for detection in result.detections:
                matches_job = (
                    detection.kind == "plate"
                    and abs(detection.x1 - job.x1) < 0.5
                    and abs(detection.y1 - job.y1) < 0.5
                    and abs(detection.x2 - job.x2) < 0.5
                    and abs(detection.y2 - job.y2) < 0.5
                )
                if not changed and matches_job:
                    revised.append(
                        replace(
                            detection,
                            plate_text=text or None,
                            ocr_confidence=round(confidence, 4),
                        )
                    )
                    changed = True
                else:
                    revised.append(detection)
            routed_modules = set(result.routed_modules)
            routed_modules.update(("hybrid_ocr", "temporal_consensus"))
            if routed_to_investigation:
                routed_modules.add("investigation")
            self._results[job.camera_id] = replace(
                result,
                detections=tuple(revised),
                routed_modules=tuple(sorted(routed_modules)),
            )

    def capabilities(self) -> dict[str, Any]:
        detector = self._detector
        return {
            "enabled": self.config.enabled,
            "status": self._status,
            "consumer_attached": self.engine.scheduler.consumer_attached,
            "model": detector.model_name if detector else None,
            "device": detector.device if detector else None,
            "reason": self._reason,
            "routes": [
                "live_overlay",
                "vehicle_detection",
                "vehicle_database",
                "plate_detection",
                "cloud_ocr",
                "hybrid_ocr",
                "visual_intelligence",
                "temporal_consensus",
                "vehicle_reid",
                "investigation",
            ],
        }

    def get(self, camera_id: str) -> CameraAnalytics | None:
        with self._lock:
            return self._results.get(camera_id)

    def list(self) -> list[CameraAnalytics]:
        with self._lock:
            return sorted(self._results.values(), key=lambda item: item.observed_at, reverse=True)
