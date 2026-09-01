from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from app.errors import NotFoundError
from app.schemas.ai_showcase import (
    AIClassCount,
    AIDetectionPage,
    AIDetectionRead,
    AIFeatureStatus,
    AIModelStatus,
    AIPlatePage,
    AIPlateRead,
    AIShowcaseOverview,
    OCRCandidateRead,
)

VEHICLE_CLASSES = ("car", "truck", "bus", "motorcycle")
VEHICLE_MODEL_ID = "MDL-VEH-001"
PLATE_MODEL_ID = "MDL-ANPR-001"
OCR_MODEL_ID = "SVC-OCR-HYBRID-001"
VISUAL_MODEL_ID = "SVC-VLM-001"


def _source_label(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1] or "unknown source"


class AIShowcaseStore:
    """Read-only projection over locally generated AI crop evidence."""

    def __init__(self, database_path: str | Path, api_prefix: str = "/api/v1") -> None:
        self.path = Path(database_path).expanduser().resolve()
        self.api_prefix = api_prefix.rstrip("/")

    def _connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        connection = sqlite3.connect(
            f"file:{self.path.as_posix()}?mode=ro",
            uri=True,
            timeout=2,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
            is not None
        )

    def _model_statuses(
        self,
        *,
        vehicle_outputs: int = 0,
        plate_outputs: int = 0,
        ocr_outputs: int = 0,
        visual_outputs: int = 0,
    ) -> list[AIModelStatus]:
        registry_path = self.path.parent / "models" / "model_registry.json"
        if not registry_path.is_file():
            deployed_registry = Path("./AI-Features/models/model_registry.json").resolve()
            if deployed_registry.is_file():
                registry_path = deployed_registry
        if not registry_path.is_file():
            repository_registry = (
                Path(__file__).resolve().parents[4]
                / "AI-Features"
                / "models"
                / "model_registry.json"
            )
            if repository_registry.is_file():
                registry_path = repository_registry
        if not registry_path.is_file():
            return [
                AIModelStatus(
                    model_id="REGISTRY-001",
                    key="registry",
                    name="Model registry",
                    purpose="Model provenance",
                    status="unavailable",
                    detail="No model registry is available beside the evidence database.",
                )
            ]
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return [
                AIModelStatus(
                    model_id="REGISTRY-001",
                    key="registry",
                    name="Model registry",
                    purpose="Model provenance",
                    status="invalid",
                    detail="The model registry could not be validated.",
                )
            ]
        detector = registry.get("active_detector", {})
        general = registry.get("general_detector", {})
        ocr = registry.get("ocr_provider", {})
        visual = registry.get("visual_intelligence_provider", {})
        return [
            AIModelStatus(
                model_id=VEHICLE_MODEL_ID,
                key="vehicle_detector",
                name="YOLO26 vehicle detector",
                purpose="Vehicle and road-object localization",
                status=str(general.get("validation_status", "registered")),
                detail=(
                    f"Checksum-attributed checkpoint · {general.get('file', 'model unavailable')}"
                ),
                output_count=vehicle_outputs,
            ),
            AIModelStatus(
                model_id=PLATE_MODEL_ID,
                key="plate_detector",
                name="License-plate detector",
                purpose="Plate localization and crop extraction",
                status=str(detector.get("validation_status", "registered")),
                detail=(
                    f"Checksum-attributed checkpoint · {detector.get('file', 'model unavailable')}"
                ),
                output_count=plate_outputs,
            ),
            AIModelStatus(
                model_id=OCR_MODEL_ID,
                key="plate_ocr",
                name="Hybrid plate OCR",
                purpose="Google-primary OCR with selective Groq verification",
                status="configured" if ocr.get("name") else "unavailable",
                detail="Remote document-text detection · application-default credentials",
                output_count=ocr_outputs,
            ),
            AIModelStatus(
                model_id=VISUAL_MODEL_ID,
                key="visual_intelligence",
                name="Groq Visual Intelligence",
                purpose="Searchable vehicle appearance and condition profiles",
                status="observed" if visual_outputs else "configured",
                detail=(
                    f"{visual.get('name', 'groq')} · "
                    f"{visual.get('model', 'backend-configured vision model')} · "
                    f"{visual.get('prompt_version', 'vehicle_visual_profile_v1')}"
                ),
                output_count=visual_outputs,
            ),
        ]

    def overview(self) -> AIShowcaseOverview:
        models = self._model_statuses()
        if not self.path.is_file():
            return AIShowcaseOverview(
                available=False,
                models=models,
                features=self._features(False, 0, 0, 0, 0, 0, 0, 0, 0),
                disclosure=(
                    "The AI evidence database is not mounted. Model cards describe configured "
                    "capabilities, not observed detections."
                ),
            )
        with self._connect() as connection:
            if not self._table_exists(connection, "detections"):
                return AIShowcaseOverview(
                    available=False,
                    models=models,
                    features=self._features(False, 0, 0, 0, 0, 0, 0, 0, 0),
                    disclosure="The configured database does not contain the detection schema.",
                )
            summary = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT source) AS source_count,
                       COUNT(DISTINCT frame) AS frame_count,
                       COUNT(DISTINCT CASE WHEN track_id IS NOT NULL
                              THEN source || ':' || track_id END)
                           AS unique_tracks,
                       AVG(confidence) AS average_confidence,
                       MIN(created_at) AS first_observed_at,
                       MAX(created_at) AS last_observed_at
                FROM detections
                """
            ).fetchone()
            class_rows = connection.execute(
                """
                SELECT class_name, COUNT(*) AS count, AVG(confidence) AS average_confidence
                FROM detections GROUP BY class_name ORDER BY count DESC, class_name
                """
            ).fetchall()
            vehicle_total = connection.execute(
                "SELECT COUNT(*) FROM detections WHERE class_name IN (?, ?, ?, ?)",
                VEHICLE_CLASSES,
            ).fetchone()[0]
            plate_total = (
                connection.execute("SELECT COUNT(*) FROM plate_detections").fetchone()[0]
                if self._table_exists(connection, "plate_detections")
                else 0
            )
            readable_plate_total, average_ocr_confidence = (
                connection.execute(
                    """
                    SELECT COUNT(*), AVG(ocr_confidence) FROM plate_detections
                    WHERE plate_text IS NOT NULL AND plate_text != ''
                    """
                ).fetchone()
                if self._table_exists(connection, "plate_detections")
                else (0, 0.0)
            )
            consensus_plate_total = 0
            if self._table_exists(connection, "plate_detections"):
                plate_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(plate_detections)")
                }
                if "ocr_consensus_count" in plate_columns:
                    consensus_plate_total = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM plate_detections "
                            "WHERE ocr_consensus_count >= 2"
                        ).fetchone()[0]
                    )
            visual_completed = 0
            visual_pending = 0
            visual_failed = 0
            if self._table_exists(connection, "visual_vehicle_intelligence"):
                visual_rows = connection.execute(
                    """SELECT analysis_status, COUNT(*)
                       FROM visual_vehicle_intelligence GROUP BY analysis_status"""
                ).fetchall()
                visual_counts = {str(row[0]): int(row[1]) for row in visual_rows}
                visual_completed = visual_counts.get("COMPLETED", 0)
                visual_pending = (
                    visual_counts.get("PENDING", 0)
                    + visual_counts.get("PROCESSING", 0)
                    + visual_counts.get("RETRY_PENDING", 0)
                )
                visual_failed = visual_counts.get("FAILED", 0)
            reid_routed = 0
            investigation_routed = 0
            if self._table_exists(connection, "live_intelligence_routes"):
                route_rows = connection.execute(
                    """SELECT route_type, COUNT(*) FROM live_intelligence_routes
                       WHERE status='COMPLETED' GROUP BY route_type"""
                ).fetchall()
                route_counts = {str(row[0]): int(row[1]) for row in route_rows}
                reid_routed = route_counts.get("vehicle_reid", 0) + route_counts.get(
                    "visual_reid", 0
                )
                investigation_routed = route_counts.get("investigation_anpr", 0)
        total = int(summary["total"] or 0)
        tracks = int(summary["unique_tracks"] or 0)
        return AIShowcaseOverview(
            available=True,
            total_detections=total,
            vehicle_detections=int(vehicle_total),
            plate_detections=int(plate_total),
            readable_plate_detections=int(readable_plate_total),
            consensus_plate_detections=consensus_plate_total,
            visual_profiles=visual_completed,
            visual_pending=visual_pending,
            visual_failed=visual_failed,
            unique_tracks=tracks,
            source_count=int(summary["source_count"] or 0),
            frame_count=int(summary["frame_count"] or 0),
            average_confidence=round(float(summary["average_confidence"] or 0.0), 4),
            average_ocr_confidence=round(float(average_ocr_confidence or 0.0), 4),
            first_observed_at=summary["first_observed_at"],
            last_observed_at=summary["last_observed_at"],
            class_counts=[
                AIClassCount(
                    class_name=row["class_name"],
                    count=int(row["count"]),
                    average_confidence=round(float(row["average_confidence"] or 0.0), 4),
                )
                for row in class_rows
            ],
            models=self._model_statuses(
                vehicle_outputs=int(vehicle_total),
                plate_outputs=int(plate_total),
                ocr_outputs=int(readable_plate_total),
                visual_outputs=visual_completed,
            ),
            features=self._features(
                True,
                total,
                tracks,
                int(plate_total),
                int(readable_plate_total),
                visual_completed,
                consensus_plate_total,
                reid_routed,
                investigation_routed,
            ),
            disclosure=(
                "Counts and confidence values are observed outputs from stored inference evidence. "
                "They are not labelled-set accuracy, legal identity, or autonomous "
                "enforcement decisions."
            ),
        )

    @staticmethod
    def _features(
        available: bool,
        detection_count: int,
        track_count: int,
        plate_count: int,
        readable_plate_count: int,
        visual_profile_count: int,
        consensus_plate_count: int,
        reid_routed_count: int,
        investigation_routed_count: int,
    ) -> list[AIFeatureStatus]:
        observed = "observed" if available and detection_count else "ready"
        return [
            AIFeatureStatus(
                key="vehicle_detection",
                name="Vehicle detection",
                status=observed,
                description=(
                    "Localizes cars, buses, trucks, motorcycles, and other configured classes."
                ),
                evidence=f"{detection_count:,} stored object crops"
                if detection_count
                else "Awaiting evidence",
            ),
            AIFeatureStatus(
                key="vehicle_tracking",
                name="Vehicle tracking",
                status="observed" if track_count else "ready",
                description=(
                    "Assigns lightweight per-camera IoU track identities without "
                    "another model pass."
                ),
                evidence=f"{track_count:,} distinct source-track identities"
                if track_count
                else "Live per-camera tracker active",
            ),
            AIFeatureStatus(
                key="vehicle_database",
                name="Vehicle crop archive",
                status=observed,
                description=(
                    "Searchable image evidence with class, confidence, frame, and track provenance."
                ),
                evidence="SQLite-backed image records" if available else "Database unavailable",
            ),
            AIFeatureStatus(
                key="plate_detection",
                name="Number-plate localization",
                status="observed" if plate_count else "ready",
                description=(
                    "Uses the plate-specific .pt detector to create tightly bounded OCR crops."
                ),
                evidence=f"{plate_count:,} stored plate crops"
                if plate_count
                else "Detector configured",
            ),
            AIFeatureStatus(
                key="cloud_ocr",
                name="Hybrid plate OCR",
                status="observed" if readable_plate_count else "configured",
                description=(
                    "Uses Google as the fast primary reader, invokes Groq only for uncertain "
                    "crops, and quarantines unresolved provider conflicts."
                ),
                evidence=(
                    f"{readable_plate_count:,} normalized OCR readings"
                    if readable_plate_count
                    else "Provider-attributed confidence and raw crop retained"
                ),
            ),
            AIFeatureStatus(
                key="visual_intelligence",
                name="Visual Intelligence",
                status="observed" if visual_profile_count else "ready",
                description=(
                    "Converts retained vehicle crops into conservative, searchable "
                    "appearance and visible-condition profiles."
                ),
                evidence=(
                    f"{visual_profile_count:,} Groq-enriched vehicle profiles"
                    if visual_profile_count
                    else "Awaiting retained vehicle crops"
                ),
            ),
            AIFeatureStatus(
                key="temporal_consensus",
                name="Temporal OCR consensus",
                status="observed" if consensus_plate_count else "ready",
                description=(
                    "Stabilizes accepted hybrid OCR readings with confidence-weighted "
                    "voting inside each camera track."
                ),
                evidence=(
                    f"{consensus_plate_count:,} multi-reading consensus results"
                    if consensus_plate_count
                    else "Live track-aware consensus active"
                ),
            ),
            AIFeatureStatus(
                key="investigation_handoff",
                name="Investigation handoff",
                status="observed" if investigation_routed_count else "ready",
                description=(
                    "Automatically publishes readable plate evidence into the controlled "
                    "investigation event ledger."
                ),
                evidence=(
                    f"{investigation_routed_count:,} durable ANPR handoffs completed"
                    if investigation_routed_count
                    else "Durable automatic handoff active"
                ),
            ),
            AIFeatureStatus(
                key="vehicle_reid",
                name="Vehicle Re-Identification",
                status="observed" if reid_routed_count else "ready",
                description=(
                    "Automatically indexes retained vehicle crops and structured visual "
                    "profiles for investigator-reviewed matching."
                ),
                evidence=(
                    f"{reid_routed_count:,} durable Re-ID handoffs completed"
                    if reid_routed_count
                    else "Automatic indexing active; human confirmation required"
                ),
            ),
        ]

    def detections(
        self,
        *,
        query: str | None,
        class_name: str | None,
        minimum_confidence: float,
        page: int,
        page_size: int,
    ) -> AIDetectionPage:
        if not self.path.is_file():
            return AIDetectionPage(items=[], total=0, page=page, page_size=page_size, pages=1)
        clauses = ["class_name IN (?, ?, ?, ?)", "confidence >= ?"]
        parameters: list[Any] = [*VEHICLE_CLASSES, minimum_confidence]
        if class_name:
            clauses.append("class_name = ?")
            parameters.append(class_name)
        if query:
            token = f"%{query.strip()}%"
            clauses.append(
                "(class_name LIKE ? OR source LIKE ? OR CAST(track_id AS TEXT) LIKE ? "
                "OR CAST(frame AS TEXT) LIKE ?)"
            )
            parameters.extend([token, token, token, token])
        where = " AND ".join(clauses)
        offset = (page - 1) * page_size
        with self._connect() as connection:
            if not self._table_exists(connection, "detections"):
                return AIDetectionPage(items=[], total=0, page=page, page_size=page_size, pages=1)
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM detections WHERE {where}",  # noqa: S608
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT id, source, frame, time_ms, track_id, class_id, class_name,
                       confidence, x1, y1, x2, y2, width, height, created_at
                FROM detections WHERE {where}
                ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
                """,  # noqa: S608
                [*parameters, page_size, offset],
            ).fetchall()
        return AIDetectionPage(
            items=[self._detection(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
            pages=max(1, math.ceil(total / page_size)),
        )

    def _detection(self, row: sqlite3.Row) -> AIDetectionRead:
        return AIDetectionRead(
            id=row["id"],
            evidence_id=f"VEH-{int(row['id']):08d}",
            model_id=VEHICLE_MODEL_ID,
            model_name="yolo26n.pt",
            source_label=_source_label(row["source"]),
            frame=row["frame"],
            time_ms=round(float(row["time_ms"]), 2),
            track_id=row["track_id"],
            class_id=row["class_id"],
            class_name=row["class_name"],
            confidence=round(float(row["confidence"]), 4),
            box=[round(float(row[key]), 2) for key in ("x1", "y1", "x2", "y2")],
            width=row["width"],
            height=row["height"],
            created_at=row["created_at"],
            image_url=f"{self.api_prefix}/ai/detections/{row['id']}/image",
        )

    def detection_image(self, detection_id: int) -> bytes:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT crop FROM detections WHERE id=?", (detection_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("ai_detection", str(detection_id))
        return bytes(row["crop"])

    def plates(self, *, query: str | None, page: int, page_size: int) -> AIPlatePage:
        if not self.path.is_file():
            return AIPlatePage(items=[], total=0, page=page, page_size=page_size, pages=1)
        with self._connect() as connection:
            if not self._table_exists(connection, "plate_detections"):
                return AIPlatePage(items=[], total=0, page=page, page_size=page_size, pages=1)
            plate_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(plate_detections)")
            }
            ocr_status_select = (
                "ocr_status"
                if "ocr_status" in plate_columns
                else "CASE WHEN plate_text IS NOT NULL AND plate_text != '' "
                "THEN 'COMPLETED' ELSE 'PENDING' END AS ocr_status"
            )
            raw_text_select = (
                "ocr_raw_text"
                if "ocr_raw_text" in plate_columns
                else "plate_text AS ocr_raw_text"
            )
            raw_confidence_select = (
                "ocr_raw_confidence"
                if "ocr_raw_confidence" in plate_columns
                else "ocr_confidence AS ocr_raw_confidence"
            )
            consensus_count_select = (
                "ocr_consensus_count"
                if "ocr_consensus_count" in plate_columns
                else "CASE WHEN plate_text IS NOT NULL AND plate_text != '' "
                "THEN 1 ELSE 0 END AS ocr_consensus_count"
            )
            hybrid_selects = [
                (
                    name
                    if name in plate_columns
                    else f"{fallback} AS {name}"
                )
                for name, fallback in (
                    ("google_ocr_raw_text", "NULL"),
                    ("google_ocr_text", "NULL"),
                    ("google_ocr_confidence", "NULL"),
                    ("google_ocr_processing_ms", "NULL"),
                    ("google_ocr_error", "NULL"),
                    ("groq_ocr_raw_text", "NULL"),
                    ("groq_ocr_text", "NULL"),
                    ("groq_ocr_confidence", "NULL"),
                    ("groq_ocr_processing_ms", "NULL"),
                    ("groq_ocr_error", "NULL"),
                    ("ocr_selected_provider", "NULL"),
                    ("ocr_decision", "NULL"),
                    ("ocr_decision_reason", "NULL"),
                    ("ocr_review_required", "0"),
                )
            ]
            clauses: list[str] = []
            parameters: list[Any] = []
            if query:
                token = f"%{query.strip()}%"
                clauses.append(
                    "(plate_text LIKE ? OR source LIKE ? OR CAST(track_id AS TEXT) LIKE ?)"
                )
                parameters.extend([token, token, token])
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM plate_detections {where}",  # noqa: S608
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT id, source_detection_id, source, frame, time_ms, track_id,
                       plate_text, ocr_confidence, detection_confidence,
                       x1, y1, x2, y2, width, height, ocr_provider,
                       {ocr_status_select}, {raw_text_select},
                       {raw_confidence_select}, {consensus_count_select},
                       {', '.join(hybrid_selects)}, created_at
                FROM plate_detections {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,  # noqa: S608
                [*parameters, page_size, (page - 1) * page_size],
            ).fetchall()
        return AIPlatePage(
            items=[self._plate(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
            pages=max(1, math.ceil(total / page_size)),
        )

    def _plate(self, row: sqlite3.Row) -> AIPlateRead:
        columns = set(row.keys())
        source_detection_id = row["source_detection_id"]
        candidates = [
            OCRCandidateRead(
                provider=provider,
                status=(
                    "failed"
                    if row[f"{prefix}_ocr_error"]
                    else "completed"
                    if row[f"{prefix}_ocr_raw_text"] or row[f"{prefix}_ocr_text"]
                    else "not_invoked"
                ),
                raw_text=row[f"{prefix}_ocr_raw_text"] or None,
                normalized_text=row[f"{prefix}_ocr_text"] or None,
                confidence=(
                    round(float(row[f"{prefix}_ocr_confidence"]), 4)
                    if row[f"{prefix}_ocr_confidence"] is not None
                    else None
                ),
                processing_ms=(
                    round(float(row[f"{prefix}_ocr_processing_ms"]), 2)
                    if row[f"{prefix}_ocr_processing_ms"] is not None
                    else None
                ),
                error=row[f"{prefix}_ocr_error"] or None,
            )
            for provider, prefix in (("Google Cloud Vision", "google"), ("Groq", "groq"))
        ]
        return AIPlateRead(
            id=row["id"],
            evidence_id=f"ANPR-{int(row['id']):08d}",
            detector_model_id=PLATE_MODEL_ID,
            detector_model_name="license_plate_detector.pt",
            ocr_model_id=OCR_MODEL_ID,
            source_detection_id=source_detection_id,
            source_label=_source_label(row["source"]),
            frame=row["frame"],
            time_ms=round(float(row["time_ms"]), 2),
            track_id=row["track_id"],
            plate_text=row["plate_text"] or None,
            ocr_confidence=(
                round(float(row["ocr_confidence"]), 4)
                if row["ocr_confidence"] is not None
                else None
            ),
            ocr_raw_text=row["ocr_raw_text"] or None,
            ocr_raw_confidence=(
                round(float(row["ocr_raw_confidence"]), 4)
                if row["ocr_raw_confidence"] is not None
                else None
            ),
            ocr_consensus_count=int(row["ocr_consensus_count"] or 0),
            ocr_candidates=candidates,
            ocr_selected_provider=row["ocr_selected_provider"] or None,
            ocr_decision=row["ocr_decision"] or None,
            ocr_decision_reason=row["ocr_decision_reason"] or None,
            ocr_review_required=bool(row["ocr_review_required"]),
            detection_confidence=round(float(row["detection_confidence"]), 4),
            box=[round(float(row[key]), 2) for key in ("x1", "y1", "x2", "y2")],
            width=row["width"],
            height=row["height"],
            ocr_provider=row["ocr_provider"],
            ocr_status=(
                row["ocr_status"]
                if "ocr_status" in columns
                else "COMPLETED"
                if row["plate_text"]
                else "PENDING"
            ),
            source_vehicle_evidence_id=(
                f"VEH-{int(source_detection_id):08d}" if source_detection_id else None
            ),
            source_vehicle_image_url=(
                f"{self.api_prefix}/ai/detections/{source_detection_id}/image"
                if source_detection_id
                else None
            ),
            created_at=row["created_at"],
            image_url=f"{self.api_prefix}/ai/plates/{row['id']}/image",
        )

    def plate_image(self, plate_id: int) -> bytes:
        with self._connect() as connection:
            if not self._table_exists(connection, "plate_detections"):
                raise NotFoundError("plate_detection", str(plate_id))
            row = connection.execute(
                "SELECT crop FROM plate_detections WHERE id=?", (plate_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("plate_detection", str(plate_id))
        return bytes(row["crop"])
