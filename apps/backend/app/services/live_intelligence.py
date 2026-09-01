from __future__ import annotations

import hashlib
import json
import logging
import math
import queue
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.advanced import VehicleObservationCreate
from app.schemas.investigation import ANPREventCreate
from app.services.investigation import InvestigationService
from app.services.reid import ReIDService

logger = logging.getLogger("drishti.live_intelligence")
ROUTE_VEHICLE = "vehicle_reid"
ROUTE_VISUAL = "visual_reid"
ROUTE_PLATE = "investigation_anpr"


class LiveIntelligenceRouter:
    """Durable, bounded handoff from crop evidence to operational services."""

    def __init__(
        self,
        evidence_database: str | Path,
        *,
        session_factory: Callable[[], Session],
        app_env: str,
        api_prefix: str,
        max_queue_size: int = 256,
        enabled: bool = True,
    ) -> None:
        self.path = Path(evidence_database).expanduser().resolve()
        self.session_factory = session_factory
        self.app_env = app_env
        self.api_prefix = api_prefix.rstrip("/")
        self.enabled = enabled
        self._jobs: queue.Queue[tuple[str, int]] = queue.Queue(maxsize=max_queue_size)
        self._queued: set[tuple[str, int]] = set()
        self._queue_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if self.enabled:
            self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS live_intelligence_routes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    route_type TEXT NOT NULL,
                    evidence_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(route_type, evidence_id)
                );
                CREATE INDEX IF NOT EXISTS idx_live_routes_status
                    ON live_intelligence_routes(status, updated_at, id);
                UPDATE live_intelligence_routes
                SET status='RETRY_PENDING',
                    last_error='Worker stopped before handoff completed',
                    updated_at=datetime('now')
                WHERE status='PROCESSING';
                """
            )

    def startup(self) -> None:
        if not self.enabled or self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="live-intelligence-router", daemon=True
        )
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None

    def queue_vehicle(self, detection_id: int) -> None:
        self._persist_and_queue(ROUTE_VEHICLE, detection_id)

    def queue_visual_profile(self, detection_id: int) -> None:
        self._persist_and_queue(ROUTE_VISUAL, detection_id)

    def queue_plate(self, plate_id: int) -> None:
        self._persist_and_queue(ROUTE_PLATE, plate_id)

    def _persist_and_queue(self, route_type: str, evidence_id: int) -> None:
        if not self.enabled:
            return
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO live_intelligence_routes (
                    route_type, evidence_id, status, created_at, updated_at
                ) VALUES (?, ?, 'PENDING', ?, ?)
                ON CONFLICT(route_type, evidence_id) DO UPDATE SET
                    status=CASE
                        WHEN live_intelligence_routes.status='COMPLETED' THEN 'COMPLETED'
                        ELSE 'RETRY_PENDING'
                    END,
                    updated_at=excluded.updated_at
                """,
                (route_type, evidence_id, now, now),
            )
            connection.commit()
        self._enqueue(route_type, evidence_id)

    def _enqueue(self, route_type: str, evidence_id: int) -> bool:
        job = (route_type, evidence_id)
        with self._queue_lock:
            if job in self._queued:
                return False
            try:
                self._jobs.put_nowait(job)
            except queue.Full:
                return False
            self._queued.add(job)
        return True

    def _recover(self) -> None:
        available = self._jobs.maxsize - self._jobs.qsize()
        if available <= 0:
            return
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT route_type, evidence_id FROM live_intelligence_routes
                   WHERE status IN ('PENDING', 'RETRY_PENDING') AND attempt_count < 3
                   ORDER BY updated_at, id LIMIT ?""",
                (min(available, 32),),
            ).fetchall()
        for row in rows:
            self._enqueue(str(row["route_type"]), int(row["evidence_id"]))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                route_type, evidence_id = self._jobs.get(timeout=1)
            except queue.Empty:
                self._recover()
                continue
            try:
                if not self._claim(route_type, evidence_id):
                    continue
                if route_type == ROUTE_PLATE:
                    self._route_plate(evidence_id)
                elif route_type == ROUTE_VISUAL:
                    self._route_vehicle(evidence_id, include_visual=True)
                else:
                    self._route_vehicle(evidence_id, include_visual=False)
                self._finish(route_type, evidence_id)
            except Exception as exc:
                self._fail(route_type, evidence_id, exc)
                logger.warning(
                    "Live intelligence handoff failed route=%s evidence=%s error=%s",
                    route_type,
                    evidence_id,
                    type(exc).__name__,
                )
            finally:
                with self._queue_lock:
                    self._queued.discard((route_type, evidence_id))
                self._jobs.task_done()

    def _claim(self, route_type: str, evidence_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE live_intelligence_routes
                   SET status='PROCESSING', attempt_count=attempt_count + 1,
                       last_error=NULL, updated_at=?
                   WHERE route_type=? AND evidence_id=?
                     AND status IN ('PENDING', 'RETRY_PENDING')
                     AND attempt_count < 3""",
                (datetime.now(UTC).isoformat(), route_type, evidence_id),
            )
            connection.commit()
            return cursor.rowcount == 1

    def _finish(self, route_type: str, evidence_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE live_intelligence_routes
                   SET status='COMPLETED', last_error=NULL, updated_at=?
                   WHERE route_type=? AND evidence_id=?""",
                (datetime.now(UTC).isoformat(), route_type, evidence_id),
            )
            connection.commit()

    def _fail(self, route_type: str, evidence_id: int, error: Exception) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT attempt_count FROM live_intelligence_routes
                   WHERE route_type=? AND evidence_id=?""",
                (route_type, evidence_id),
            ).fetchone()
            attempts = int(row[0]) if row else 3
            connection.execute(
                """UPDATE live_intelligence_routes SET status=?, last_error=?, updated_at=?
                   WHERE route_type=? AND evidence_id=?""",
                (
                    "RETRY_PENDING" if attempts < 3 else "FAILED",
                    f"{type(error).__name__}: {str(error)[:400]}",
                    datetime.now(UTC).isoformat(),
                    route_type,
                    evidence_id,
                ),
            )
            connection.commit()

    def _detection(self, detection_id: int) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id, source, frame, time_ms, track_id, class_name, confidence,
                          x1, y1, x2, y2, width, height, created_at
                   FROM detections WHERE id=?""",
                (detection_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Vehicle evidence {detection_id} is unavailable")
        return row

    @staticmethod
    def _camera_id(source: str) -> str:
        camera_id = source.removeprefix("camera:")
        if camera_id == source:
            raise ValueError("Only camera-backed evidence can enter live operational services")
        return camera_id

    @staticmethod
    def _observed_at(row: sqlite3.Row) -> datetime:
        return datetime.fromtimestamp(float(row["time_ms"]) / 1000, tz=UTC)

    def _visual_profile(self, detection_id: int) -> sqlite3.Row | None:
        with self._connect() as connection:
            table = connection.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table' AND name='visual_vehicle_intelligence'"""
            ).fetchone()
            if not table:
                return None
            return connection.execute(
                """SELECT * FROM visual_vehicle_intelligence
                   WHERE detection_id=? AND analysis_status='COMPLETED'
                   ORDER BY analyzed_at DESC, id DESC LIMIT 1""",
                (detection_id,),
            ).fetchone()

    @staticmethod
    def _structured_signature(profile: sqlite3.Row | None) -> list[float] | None:
        if profile is None:
            return None
        tokens = [
            str(profile["vehicle_type"] or "unknown"),
            str(profile["primary_color"] or "unknown"),
            str(profile["damage_status"] or "uncertain"),
            str(profile["vehicle_view"] or "unknown"),
            str(profile["plate_visibility"] or "uncertain"),
        ]
        for field in ("secondary_colors", "distinctive_features", "accessories"):
            try:
                values = json.loads(profile[field] or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                values = []
            tokens.extend(str(value).strip().lower() for value in values if str(value).strip())
        vector = [0.0] * 64
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:2], "big") % len(vector)] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [round(value / magnitude, 6) for value in vector] if magnitude else None

    def _route_vehicle(self, detection_id: int, *, include_visual: bool) -> None:
        row = self._detection(detection_id)
        profile = self._visual_profile(detection_id) if include_visual else None
        embedding = self._structured_signature(profile)
        payload = VehicleObservationCreate(
            source_observation_id=f"live-vehicle-{detection_id}",
            camera_id=self._camera_id(str(row["source"])),
            observed_at=self._observed_at(row),
            track_id=str(row["track_id"]) if row["track_id"] is not None else None,
            vehicle_class=(str(profile["vehicle_type"]) if profile else str(row["class_name"])),
            colour=str(profile["primary_color"]) if profile else None,
            bounding_box=[0.0, 0.0, float(row["width"]), float(row["height"])],
            image_width=max(1, int(row["width"])),
            image_height=max(1, int(row["height"])),
            quality_score=max(0.0, min(1.0, float(row["confidence"]))),
            quality_flags=[] if profile else ["visual_profile_pending"],
            crop_reference=f"{self.api_prefix}/ai/detections/{detection_id}/image",
            embedding=embedding,
            embedding_provider="structured-visual-profile-v1" if embedding else None,
            model_version=(
                f"MDL-VEH-001+{profile['vlm_model']}" if profile else "MDL-VEH-001:yolo26n.pt"
            ),
            source="live_analytics",
        )
        with self.session_factory() as session:
            ReIDService(
                session,
                actor_id="live-analytics",
                request_id=None,
                app_env=self.app_env,
            ).ingest(payload)

    def _route_plate(self, plate_id: int) -> None:
        with self._connect() as connection:
            columns = {
                str(item[1])
                for item in connection.execute("PRAGMA table_info(plate_detections)")
            }
            provider_select = (
                "ocr_selected_provider" if "ocr_selected_provider" in columns else "NULL"
            )
            decision_select = "ocr_decision" if "ocr_decision" in columns else "NULL"
            review_select = (
                "ocr_review_required" if "ocr_review_required" in columns else "0"
            )
            row = connection.execute(
                f"""SELECT id, source_detection_id, source, time_ms, track_id,
                           plate_text, ocr_confidence, detection_confidence,
                           {provider_select} AS ocr_selected_provider,
                           {decision_select} AS ocr_decision,
                           {review_select} AS ocr_review_required
                    FROM plate_detections WHERE id=?""",  # noqa: S608
                (plate_id,),
            ).fetchone()
        if row is None or not row["plate_text"]:
            raise LookupError(f"Readable plate evidence {plate_id} is unavailable")
        if bool(row["ocr_review_required"]) or row["ocr_decision"] == "review_required":
            raise LookupError(f"Unresolved plate evidence {plate_id} cannot be routed")
        payload = ANPREventCreate(
            source_event_id=f"live-anpr-{plate_id}",
            camera_id=self._camera_id(str(row["source"])),
            observed_at=self._observed_at(row),
            plate_text=str(row["plate_text"]),
            plate_confidence=float(row["ocr_confidence"] or 0),
            vehicle_attributes={
                "track_id": row["track_id"],
                "source_detection_id": row["source_detection_id"],
                "detector_confidence": row["detection_confidence"],
                "ocr_selected_provider": row["ocr_selected_provider"] or "legacy",
                "ocr_decision": row["ocr_decision"] or "accepted_legacy",
            },
            evidence_reference=f"{self.api_prefix}/ai/plates/{plate_id}/image",
            model_version="MDL-ANPR-001+SVC-OCR-HYBRID-001",
            source="live_hybrid_anpr",
        )
        with self.session_factory() as session:
            result: dict[str, Any] = InvestigationService(
                session,
                actor_id="live-analytics",
                request_id=None,
                app_env=self.app_env,
            ).ingest_event(payload)
        source_detection_id = row["source_detection_id"]
        if source_detection_id is not None:
            self._route_vehicle_with_plate(int(source_detection_id), result["event"].id, payload)

    def _route_vehicle_with_plate(
        self, detection_id: int, event_id: Any, event: ANPREventCreate
    ) -> None:
        row = self._detection(detection_id)
        profile = self._visual_profile(detection_id)
        embedding = self._structured_signature(profile)
        payload = VehicleObservationCreate(
            source_observation_id=f"live-vehicle-{detection_id}",
            camera_id=event.camera_id,
            anpr_event_id=event_id,
            observed_at=self._observed_at(row),
            track_id=str(row["track_id"]) if row["track_id"] is not None else None,
            plate_text=event.plate_text,
            vehicle_class=(str(profile["vehicle_type"]) if profile else str(row["class_name"])),
            colour=str(profile["primary_color"]) if profile else None,
            bounding_box=[0.0, 0.0, float(row["width"]), float(row["height"])],
            image_width=max(1, int(row["width"])),
            image_height=max(1, int(row["height"])),
            quality_score=max(0.0, min(1.0, float(row["confidence"]))),
            quality_flags=[] if profile else ["visual_profile_pending"],
            crop_reference=f"{self.api_prefix}/ai/detections/{detection_id}/image",
            embedding=embedding,
            embedding_provider="structured-visual-profile-v1" if embedding else None,
            model_version="MDL-VEH-001+MDL-ANPR-001+SVC-OCR-HYBRID-001",
            source="live_analytics",
        )
        with self.session_factory() as session:
            ReIDService(
                session,
                actor_id="live-analytics",
                request_id=None,
                app_env=self.app_env,
            ).ingest(payload)
