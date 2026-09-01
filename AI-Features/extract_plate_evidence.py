"""Extract number-plate evidence from stored vehicle crops.

The plate-specific .pt model localizes plates. Google Cloud Vision optionally reads
only those small crops. Results are appended to the same evidence database without
changing the original vehicle detections.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from anpr_video_detect import GoogleCloudVisionOCR, PlateCropper, registered_detector

ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = ROOT / "crops.db"
VEHICLE_CLASSES = ("car", "truck", "bus", "motorcycle")

PLATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS plate_detections (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source_detection_id   INTEGER,
    source                TEXT    NOT NULL,
    frame                 INTEGER NOT NULL,
    time_ms               REAL    NOT NULL,
    track_id              INTEGER,
    plate_text             TEXT,
    ocr_confidence         REAL,
    detection_confidence   REAL    NOT NULL,
    x1                     REAL    NOT NULL,
    y1                     REAL    NOT NULL,
    x2                     REAL    NOT NULL,
    y2                     REAL    NOT NULL,
    width                  INTEGER NOT NULL,
    height                 INTEGER NOT NULL,
    crop                   BLOB    NOT NULL,
    ocr_provider           TEXT    NOT NULL,
    created_at             TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_detection_id, x1, y1, x2, y2)
);
CREATE INDEX IF NOT EXISTS idx_plate_text ON plate_detections(plate_text);
CREATE INDEX IF NOT EXISTS idx_plate_track ON plate_detections(source, track_id);
CREATE INDEX IF NOT EXISTS idx_plate_latest
    ON plate_detections(created_at DESC, id DESC);
"""


@dataclass(slots=True)
class PlateCandidate:
    source_detection_id: int
    source: str
    frame: int
    time_ms: float
    track_id: int | None
    box: tuple[int, int, int, int]
    confidence: float
    crop: np.ndarray


def candidate_rows(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    connection.row_factory = sqlite3.Row
    plate_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='plate_detections'"
    ).fetchone()
    exclusion = (
        "AND id NOT IN (SELECT source_detection_id FROM plate_detections "
        "WHERE source_detection_id IS NOT NULL)"
        if plate_table
        else ""
    )
    return list(
        connection.execute(
            f"""
            SELECT id, source, frame, time_ms, track_id, crop
            FROM detections
            WHERE class_name IN (?, ?, ?, ?)
              {exclusion}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,  # noqa: S608
            (*VEHICLE_CLASSES, limit),
        )
    )


def detect_candidates(
    rows: list[sqlite3.Row],
    cropper: PlateCropper,
) -> list[PlateCandidate]:
    candidates: list[PlateCandidate] = []
    for row in rows:
        encoded = np.frombuffer(row["crop"], dtype=np.uint8)
        vehicle = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if vehicle is None:
            continue
        for x1, y1, x2, y2, confidence, _ in cropper.boxes(vehicle):
            plate = vehicle[y1:y2, x1:x2]
            if plate.size == 0:
                continue
            candidates.append(
                PlateCandidate(
                    source_detection_id=row["id"],
                    source=row["source"],
                    frame=row["frame"],
                    time_ms=row["time_ms"],
                    track_id=row["track_id"],
                    box=(x1, y1, x2, y2),
                    confidence=confidence,
                    crop=plate,
                )
            )
    return candidates


def store_candidates(
    connection: sqlite3.Connection,
    candidates: list[PlateCandidate],
    readings: list[tuple[str, float]],
    provider: str,
) -> int:
    stored = 0
    for candidate, (text, ocr_confidence) in zip(candidates, readings):
        encoded, payload = cv2.imencode(
            ".jpg",
            candidate.crop,
            [cv2.IMWRITE_JPEG_QUALITY, 95],
        )
        if not encoded:
            continue
        x1, y1, x2, y2 = candidate.box
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO plate_detections (
                source_detection_id, source, frame, time_ms, track_id,
                plate_text, ocr_confidence, detection_confidence,
                x1, y1, x2, y2, width, height, crop, ocr_provider
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.source_detection_id,
                candidate.source,
                candidate.frame,
                candidate.time_ms,
                candidate.track_id,
                text or None,
                ocr_confidence if text else None,
                candidate.confidence,
                x1,
                y1,
                x2,
                y2,
                candidate.crop.shape[1],
                candidate.crop.shape[0],
                sqlite3.Binary(payload.tobytes()),
                provider,
            ),
        )
        stored += cursor.rowcount
    connection.commit()
    return stored


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--limit", type=int, default=300, help="Maximum unprocessed vehicle crops"
    )
    parser.add_argument("--detector-confidence", type=float, default=0.5)
    parser.add_argument("--google-credentials", type=Path)
    parser.add_argument("--google-timeout", type=float, default=15.0)
    parser.add_argument(
        "--skip-ocr", action="store_true", help="Store crops without remote OCR"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect and report without changing the database",
    )
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    if not 0 <= args.detector_confidence <= 1:
        parser.error("--detector-confidence must be between 0 and 1")
    return args


def main() -> None:
    args = parse_args()
    database = args.db.expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Evidence database not found: {database}")
    connection = sqlite3.connect(database)
    try:
        if not args.dry_run:
            connection.executescript(PLATE_SCHEMA)
        rows = candidate_rows(connection, args.limit)
        cropper = PlateCropper(
            registered_detector(),
            roi=None,
            confidence=args.detector_confidence,
            padding=0.08,
            minimum_size=(12, 5),
        )
        candidates = detect_candidates(rows, cropper)
        print(
            f"Scanned {len(rows)} vehicle crops; detected {len(candidates)} plate candidates"
        )
        if args.dry_run or not candidates:
            return

        if args.skip_ocr:
            readings = [("", 0.0)] * len(candidates)
            provider = "not-requested"
        else:
            credentials = args.google_credentials
            if credentials is None and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                credentials = Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
            ocr = GoogleCloudVisionOCR(
                credentials=credentials, timeout=args.google_timeout
            )
            readings = ocr.recognize_batch([candidate.crop for candidate in candidates])
            provider = "google-cloud-vision:document-text-detection-v1"
        stored = store_candidates(connection, candidates, readings, provider)
        readable = sum(bool(text) for text, _ in readings)
        print(
            f"Stored {stored} plate crops; {readable} produced accepted normalized OCR text"
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
