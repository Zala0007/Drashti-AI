from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import queue
import re
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.errors import NotFoundError, RegistryError
from app.schemas.visual_intelligence import (
    DamageRegion,
    VehicleVisualProfile,
    VisualIntelligenceRead,
    VisualIntelligenceStatus,
    VisualQueueResponse,
    VisualSearchFilters,
    VisualSearchResponse,
    VisualSearchResult,
)

logger = logging.getLogger("drishti.visual_intelligence")

PROMPT_VERSION = "vehicle_visual_profile_v1"
VEHICLE_CLASSES = ("car", "truck", "bus", "motorcycle")
NORMALIZED_TYPES = {
    "car",
    "sedan",
    "hatchback",
    "suv",
    "mpv",
    "van",
    "pickup",
    "truck",
    "bus",
    "motorcycle",
    "scooter",
    "auto-rickshaw",
    "other",
    "unknown",
}
COLORS = {
    "red",
    "orange",
    "yellow",
    "green",
    "blue",
    "purple",
    "black",
    "white",
    "grey",
    "silver",
    "brown",
    "beige",
    "multi-colour",
    "unknown",
}
STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "between",
    "car",
    "detected",
    "for",
    "from",
    "in",
    "is",
    "me",
    "near",
    "of",
    "on",
    "or",
    "seen",
    "show",
    "the",
    "to",
    "vehicle",
    "vehicles",
    "with",
}

VEHICLE_SYSTEM_PROMPT = """
You are a conservative vehicle visual-analysis system for CCTV imagery. Analyze only
what is visibly supported by the supplied vehicle crop. Identify vehicle category,
visible colours, external condition, possible visible damage and location, distinctive
features, accessories, markings, view angle, plate visibility, image quality, occlusion,
and a concise searchable description. Never infer owner, driver, criminal activity,
cause of damage, unseen mechanical condition, or a registration number. Do not claim
an exact make/model unless strongly supported. Use possible, appears, or uncertain when
evidence is ambiguous. Return only one JSON object matching the requested schema.
""".strip()

VEHICLE_USER_PROMPT = """
Return JSON with exactly these keys: vehicle_present, vehicle_type,
vehicle_type_confidence, primary_color, secondary_colors, visual_condition,
damage_present, damage_regions, distinctive_features, accessories, vehicle_view,
plate_visibility, lighting_condition, image_quality, occlusion, search_keywords,
short_description, detailed_description, analysis_confidence.

Allowed confidence values: low, medium, high.
Allowed damage_present: none_obvious, possible, visible, uncertain.
Allowed plate_visibility: readable, partial, unreadable, not_visible, uncertain.
Allowed image_quality: poor, fair, good, unknown.
Allowed occlusion: none, low, medium, high, unknown.
Normalize vehicle_type to: car, sedan, hatchback, SUV, MPV, van, pickup, truck,
bus, motorcycle, scooter, auto-rickshaw, other, unknown.
Normalize primary_color to: red, orange, yellow, green, blue, purple, black,
white, grey, silver, brown, beige, multi-colour, unknown.
Each damage_regions item must contain location, description, confidence.
""".strip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


class VisionIntelligenceProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def analyze_vehicle(self, image: bytes) -> VehicleVisualProfile: ...

    @abstractmethod
    def health_check(self) -> bool: ...


def _is_groq_rate_limit(exc: Exception) -> bool:
    try:
        from groq import RateLimitError
        if isinstance(exc, RateLimitError):
            return True
    except ImportError:
        pass
    if getattr(exc, "status_code", None) == 429:
        return True
    msg = str(exc).lower()
    return (
        "rate limit" in msg
        or "429" in msg
        or "rate_limit_exceeded" in msg
        or "tokens per" in msg
        or "requests per" in msg
        or "quota" in msg
    )


class GroqVisionProvider(VisionIntelligenceProvider):
    name = "groq"

    def __init__(self, *, api_key: str, model: str, timeout: float, max_retries: int) -> None:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_keys: tuple[str, ...] | list[str] | None = None,
        model: str,
        timeout: float,
        max_retries: int,
    ) -> None:
        try:
            from groq import Groq
        except ImportError as exc:
            raise RuntimeError("The groq package is not installed") from exc

        resolved_keys: list[str] = []
        if api_keys:
            resolved_keys.extend([k.strip() for k in api_keys if k and k.strip()])
        elif api_key and api_key.strip():
            resolved_keys.append(api_key.strip())

        if not resolved_keys:
            raise RuntimeError("At least one valid Groq API key is required")

        self.model = model
        self._client = Groq(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self._timeout = timeout
        self._max_retries = max_retries
        self._api_keys = resolved_keys
        self._clients = [
            Groq(api_key=key, timeout=timeout, max_retries=max_retries)
            for key in resolved_keys
        ]
        self._active_index = 0

    def analyze_vehicle(self, image: bytes) -> VehicleVisualProfile:
        encoded = base64.b64encode(image).decode("ascii")
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": VEHICLE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VEHICLE_USER_PROMPT},
        total_keys = len(self._clients)
        last_exc: Exception | None = None

        for attempt in range(total_keys):
            client_idx = (self._active_index + attempt) % total_keys
            client = self._clients[client_idx]
            try:
                completion = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": VEHICLE_SYSTEM_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                            "role": "user",
                            "content": [
                                {"type": "text", "text": VEHICLE_USER_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                                },
                            ],
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
            reasoning_effort="none",
            reasoning_format="hidden",
            temperature=0.2,
            top_p=0.8,
            max_completion_tokens=1400,
            stream=False,
        )
        content = completion.choices[0].message.content or ""
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        return VehicleVisualProfile.model_validate(json.loads(content))
                    response_format={"type": "json_object"},
                    reasoning_effort="none",
                    reasoning_format="hidden",
                    temperature=0.2,
                    top_p=0.8,
                    max_completion_tokens=1400,
                    stream=False,
                )
                if client_idx != self._active_index:
                    logger.info("Groq Vision switched active API key index to %d", client_idx)
                    self._active_index = client_idx
                content = completion.choices[0].message.content or ""
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
                return VehicleVisualProfile.model_validate(json.loads(content))
            except Exception as exc:
                last_exc = exc
                if _is_groq_rate_limit(exc) and attempt < total_keys - 1:
                    next_idx = (self._active_index + attempt + 1) % total_keys
                    logger.warning(
                        "Groq Vision API key at index %d hit rate limit (%s); switching to key index %d",
                        client_idx,
                        type(exc).__name__,
                        next_idx,
                    )
                    continue
                raise
        if last_exc:
            raise last_exc

    def health_check(self) -> bool:
        return bool(self.model)
        return bool(self.model and self._clients)


class VisualIntelligenceEngine:
    def __init__(
        self,
        database_path: str | Path,
        *,
        api_prefix: str,
        provider: VisionIntelligenceProvider | None,
        max_queue_size: int = 64,
        retry_attempts: int = 3,
        auto_analyze: bool = True,
        minimum_request_interval_seconds: float = 2.0,
        on_profile_completed: Callable[[int], None] | None = None,
    ) -> None:
        self.path = Path(database_path).expanduser().resolve()
        self.api_prefix = api_prefix.rstrip("/")
        self.provider = provider
        self.retry_attempts = retry_attempts
        self.auto_analyze = auto_analyze
        self.minimum_request_interval_seconds = max(0.0, minimum_request_interval_seconds)
        self._on_profile_completed = on_profile_completed
        self._jobs: queue.Queue[int] = queue.Queue(maxsize=max_queue_size)
        self._queued: set[int] = set()
        self._queue_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cursor = 0
        self._last_provider_request = 0.0
        self._ensure_schema()
        with self._connect() as connection:
            if self._table_exists(connection, "detections"):
                self._cursor = int(
                    connection.execute("SELECT COALESCE(MAX(id), 0) FROM detections").fetchone()[0]
                )

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=5, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            is not None
        )

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS visual_vehicle_intelligence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    detection_id INTEGER NOT NULL,
                    crop_sha256 TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    track_id INTEGER,
                    timestamp_ms REAL NOT NULL,
                    observed_at TEXT NOT NULL,
                    plate_id INTEGER,
                    anpr_plate TEXT,
                    vehicle_present INTEGER NOT NULL DEFAULT 1,
                    vehicle_type TEXT NOT NULL DEFAULT 'unknown',
                    vehicle_type_confidence TEXT NOT NULL DEFAULT 'low',
                    primary_color TEXT NOT NULL DEFAULT 'unknown',
                    secondary_colors TEXT NOT NULL DEFAULT '[]',
                    damage_status TEXT NOT NULL DEFAULT 'uncertain',
                    damage_regions TEXT NOT NULL DEFAULT '[]',
                    visual_condition TEXT NOT NULL DEFAULT 'uncertain',
                    distinctive_features TEXT NOT NULL DEFAULT '[]',
                    accessories TEXT NOT NULL DEFAULT '[]',
                    vehicle_view TEXT NOT NULL DEFAULT 'unknown',
                    plate_visibility TEXT NOT NULL DEFAULT 'uncertain',
                    lighting_condition TEXT NOT NULL DEFAULT 'unknown',
                    image_quality TEXT NOT NULL DEFAULT 'unknown',
                    occlusion TEXT NOT NULL DEFAULT 'unknown',
                    short_description TEXT NOT NULL DEFAULT '',
                    detailed_description TEXT NOT NULL DEFAULT '',
                    search_keywords TEXT NOT NULL DEFAULT '[]',
                    analysis_confidence TEXT NOT NULL DEFAULT 'low',
                    vlm_provider TEXT NOT NULL,
                    vlm_model TEXT NOT NULL,
                    vlm_prompt_version TEXT NOT NULL,
                    analyzed_at TEXT,
                    processing_ms REAL,
                    analysis_status TEXT NOT NULL,
                    analysis_error TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(detection_id, crop_sha256, vlm_model, vlm_prompt_version)
                );
                CREATE INDEX IF NOT EXISTS idx_visual_status
                    ON visual_vehicle_intelligence(analysis_status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_visual_attributes
                    ON visual_vehicle_intelligence(primary_color, vehicle_type, damage_status);
                CREATE TABLE IF NOT EXISTS visual_search_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    filters_json TEXT NOT NULL,
                    result_count INTEGER NOT NULL,
                    searched_at TEXT NOT NULL
                );
                UPDATE visual_vehicle_intelligence
                SET analysis_status='RETRY_PENDING',
                    analysis_error='Worker stopped before analysis completed',
                    updated_at=datetime('now')
                WHERE analysis_status IN ('PENDING', 'PROCESSING');
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(visual_vehicle_intelligence)")
            }
            migrations = {
                "vehicle_present": "INTEGER NOT NULL DEFAULT 1",
                "vehicle_type_confidence": "TEXT NOT NULL DEFAULT 'low'",
                "lighting_condition": "TEXT NOT NULL DEFAULT 'unknown'",
                "occlusion": "TEXT NOT NULL DEFAULT 'unknown'",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE visual_vehicle_intelligence ADD COLUMN {name} {definition}"
                    )

    def startup(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="visual-intelligence", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                detection_id = self._jobs.get(timeout=2)
            except queue.Empty:
                if self.provider and self.auto_analyze:
                    self._queue_retry_pending()
                    self._queue_new_crops()
                continue
            try:
                self._process(detection_id)
            except Exception:
                logger.exception("visual_analysis_failed detection_id=%s", detection_id)
            finally:
                with self._queue_lock:
                    self._queued.discard(detection_id)
                self._jobs.task_done()

    def _queue_new_crops(self) -> None:
        available = self._jobs.maxsize - self._jobs.qsize()
        if available <= 0:
            return
        with self._connect() as connection:
            if not self._table_exists(connection, "detections"):
                return
            rows = connection.execute(
                """
                SELECT id FROM detections
                WHERE id > ? AND class_name IN (?, ?, ?, ?)
                ORDER BY id ASC LIMIT ?
                """,
                (self._cursor, *VEHICLE_CLASSES, min(20, available)),
            ).fetchall()
        for row in rows:
            self._cursor = max(self._cursor, int(row["id"]))
            self.queue_detection(int(row["id"]), raise_if_unavailable=False)

    def _queue_retry_pending(self) -> None:
        available = self._jobs.maxsize - self._jobs.qsize()
        if available <= 0 or not self.provider:
            return
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT detection_id FROM visual_vehicle_intelligence
                   WHERE analysis_status='RETRY_PENDING' AND vlm_model=?
                         AND vlm_prompt_version=?
                   ORDER BY updated_at ASC LIMIT ?""",
                (self.provider.model, PROMPT_VERSION, min(available, 12)),
            ).fetchall()
        for row in rows:
            self.queue_detection(int(row["detection_id"]), raise_if_unavailable=False)

    def _detection(self, detection_id: int) -> sqlite3.Row:
        with self._connect() as connection:
            if not self._table_exists(connection, "detections"):
                raise NotFoundError("vehicle_detection", str(detection_id))
            row = connection.execute(
                """SELECT id, source, frame, time_ms, track_id, class_name, confidence,
                          width, height, crop, created_at
                   FROM detections WHERE id=? AND class_name IN (?, ?, ?, ?)""",
                (detection_id, *VEHICLE_CLASSES),
            ).fetchone()
        if row is None:
            raise NotFoundError("vehicle_detection", str(detection_id))
        return row

    def _plate(self, detection: sqlite3.Row) -> sqlite3.Row | None:
        with self._connect() as connection:
            if not self._table_exists(connection, "plate_detections"):
                return None
            return connection.execute(
                """
                SELECT id, plate_text, ocr_confidence FROM plate_detections
                WHERE source_detection_id=? OR (
                    source=? AND ABS(frame-?) <= 2 AND
                    (track_id=? OR track_id IS NULL OR ? IS NULL)
                )
                ORDER BY CASE WHEN source_detection_id=? THEN 0 ELSE 1 END,
                         ocr_confidence DESC, detection_confidence DESC LIMIT 1
                """,
                (
                    detection["id"],
                    detection["source"],
                    detection["frame"],
                    detection["track_id"],
                    detection["track_id"],
                    detection["id"],
                ),
            ).fetchone()

    def queue_detection(self, detection_id: int, *, raise_if_unavailable: bool = True) -> bool:
        if not self.provider:
            if raise_if_unavailable:
                raise RegistryError(
                    code="VISUAL_PROVIDER_NOT_CONFIGURED",
                    message="Groq Visual Intelligence is not configured on the backend",
                    status_code=503,
                )
            return False
        detection = self._detection(detection_id)
        crop_hash = hashlib.sha256(bytes(detection["crop"])).hexdigest()
        with self._connect() as connection:
            existing = connection.execute(
                """SELECT analysis_status FROM visual_vehicle_intelligence
                   WHERE detection_id=? AND crop_sha256=? AND vlm_model=?
                         AND vlm_prompt_version=?""",
                (detection_id, crop_hash, self.provider.model, PROMPT_VERSION),
            ).fetchone()
            if existing and existing["analysis_status"] in {"PENDING", "PROCESSING", "COMPLETED"}:
                return False
            cached = connection.execute(
                """SELECT * FROM visual_vehicle_intelligence
                   WHERE crop_sha256=? AND vlm_model=? AND vlm_prompt_version=?
                         AND analysis_status='COMPLETED'
                   ORDER BY analyzed_at DESC LIMIT 1""",
                (crop_hash, self.provider.model, PROMPT_VERSION),
            ).fetchone()
            now = _utc_now()
            plate = self._plate(detection)
            connection.execute(
                """
                INSERT INTO visual_vehicle_intelligence (
                    detection_id, crop_sha256, event_id, source, track_id, timestamp_ms,
                    observed_at, plate_id, anpr_plate, vlm_provider, vlm_model,
                    vlm_prompt_version, analysis_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
                ON CONFLICT(detection_id, crop_sha256, vlm_model, vlm_prompt_version)
                DO UPDATE SET analysis_status='PENDING', analysis_error=NULL,
                              updated_at=excluded.updated_at
                """,
                (
                    detection_id,
                    crop_hash,
                    f"VEH-{detection_id:08d}",
                    detection["source"],
                    detection["track_id"],
                    float(detection["time_ms"]),
                    detection["created_at"],
                    plate["id"] if plate else None,
                    plate["plate_text"] if plate else None,
                    self.provider.name,
                    self.provider.model,
                    PROMPT_VERSION,
                    now,
                    now,
                ),
            )
            if cached:
                connection.execute(
                    """UPDATE visual_vehicle_intelligence
                       SET vehicle_present=?, vehicle_type=?, vehicle_type_confidence=?,
                           primary_color=?, secondary_colors=?, damage_status=?,
                           damage_regions=?, visual_condition=?, distinctive_features=?,
                           accessories=?, vehicle_view=?, plate_visibility=?,
                           lighting_condition=?, image_quality=?, occlusion=?,
                           short_description=?, detailed_description=?, search_keywords=?,
                           analysis_confidence=?,
                           analyzed_at=?, processing_ms=0, analysis_status='COMPLETED',
                           analysis_error=NULL, updated_at=?
                       WHERE detection_id=? AND crop_sha256=? AND vlm_model=?
                             AND vlm_prompt_version=?""",
                    (
                        cached["vehicle_present"],
                        cached["vehicle_type"],
                        cached["vehicle_type_confidence"],
                        cached["primary_color"],
                        cached["secondary_colors"],
                        cached["damage_status"],
                        cached["damage_regions"],
                        cached["visual_condition"],
                        cached["distinctive_features"],
                        cached["accessories"],
                        cached["vehicle_view"],
                        cached["plate_visibility"],
                        cached["lighting_condition"],
                        cached["image_quality"],
                        cached["occlusion"],
                        cached["short_description"],
                        cached["detailed_description"],
                        cached["search_keywords"],
                        cached["analysis_confidence"],
                        now,
                        now,
                        detection_id,
                        crop_hash,
                        self.provider.model,
                        PROMPT_VERSION,
                    ),
                )
            connection.commit()
            if cached:
                self._notify_profile_completed(detection_id)
                return False
        with self._queue_lock:
            if detection_id in self._queued:
                return False
            try:
                self._jobs.put_nowait(detection_id)
            except queue.Full:
                with self._connect() as connection:
                    connection.execute(
                        """UPDATE visual_vehicle_intelligence
                           SET analysis_status='RETRY_PENDING',
                               analysis_error='Bounded analysis queue is full', updated_at=?
                           WHERE detection_id=? AND vlm_model=? AND vlm_prompt_version=?""",
                        (_utc_now(), detection_id, self.provider.model, PROMPT_VERSION),
                    )
                    connection.commit()
                return False
            self._queued.add(detection_id)
        return True

    def _process(self, detection_id: int) -> None:
        if not self.provider:
            return
        detection = self._detection(detection_id)
        started = time.perf_counter()
        error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            with self._connect() as connection:
                connection.execute(
                    """UPDATE visual_vehicle_intelligence SET analysis_status='PROCESSING',
                       attempt_count=?, updated_at=? WHERE detection_id=? AND vlm_model=?
                       AND vlm_prompt_version=?""",
                    (attempt, _utc_now(), detection_id, self.provider.model, PROMPT_VERSION),
                )
                connection.commit()
            try:
                elapsed = time.monotonic() - self._last_provider_request
                remaining = self.minimum_request_interval_seconds - elapsed
                if remaining > 0 and self._stop.wait(remaining):
                    return
                self._last_provider_request = time.monotonic()
                profile = self.provider.analyze_vehicle(bytes(detection["crop"]))
                self._save_profile(detection_id, profile, (time.perf_counter() - started) * 1000)
                return
            except Exception as exc:  # provider, JSON and schema failures are isolated here
                error = exc
                status = "RETRY_PENDING" if attempt < self.retry_attempts else "FAILED"
                with self._connect() as connection:
                    connection.execute(
                        """UPDATE visual_vehicle_intelligence SET analysis_status=?,
                           analysis_error=?, updated_at=? WHERE detection_id=? AND vlm_model=?
                           AND vlm_prompt_version=?""",
                        (
                            status,
                            f"{type(exc).__name__}: {str(exc)[:500]}",
                            _utc_now(),
                            detection_id,
                            self.provider.model,
                            PROMPT_VERSION,
                        ),
                    )
                    connection.commit()
                if attempt < self.retry_attempts:
                    self._stop.wait(min(2**attempt, 8))
        if error:
            logger.warning(
                "Groq enrichment failed for detection %s: %s", detection_id, type(error).__name__
            )

    def _save_profile(
        self, detection_id: int, profile: VehicleVisualProfile, processing_ms: float
    ) -> None:
        vehicle_type = profile.vehicle_type.strip().lower()
        if vehicle_type not in NORMALIZED_TYPES:
            vehicle_type = "other"
        primary_color = profile.primary_color.strip().lower()
        if primary_color not in COLORS:
            primary_color = "unknown"
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE visual_vehicle_intelligence SET vehicle_present=?, vehicle_type=?,
                    vehicle_type_confidence=?, primary_color=?,
                    secondary_colors=?, damage_status=?, damage_regions=?, visual_condition=?,
                    distinctive_features=?, accessories=?, vehicle_view=?, plate_visibility=?,
                    lighting_condition=?, image_quality=?, occlusion=?, short_description=?,
                    detailed_description=?, search_keywords=?,
                    analysis_confidence=?, analyzed_at=?, processing_ms=?,
                    analysis_status='COMPLETED',
                    analysis_error=NULL, updated_at=?
                WHERE detection_id=? AND vlm_model=? AND vlm_prompt_version=?
                """,
                (
                    int(profile.vehicle_present),
                    vehicle_type,
                    profile.vehicle_type_confidence,
                    primary_color,
                    json.dumps(profile.secondary_colors),
                    profile.damage_present,
                    json.dumps([item.model_dump() for item in profile.damage_regions]),
                    profile.visual_condition,
                    json.dumps(profile.distinctive_features),
                    json.dumps(profile.accessories),
                    profile.vehicle_view,
                    profile.plate_visibility,
                    profile.lighting_condition,
                    profile.image_quality,
                    profile.occlusion,
                    profile.short_description,
                    profile.detailed_description,
                    json.dumps(profile.search_keywords),
                    profile.analysis_confidence,
                    _utc_now(),
                    round(processing_ms, 2),
                    _utc_now(),
                    detection_id,
                    self.provider.model,
                    PROMPT_VERSION,
                ),
            )
            connection.commit()
        self._notify_profile_completed(detection_id)

    def _notify_profile_completed(self, detection_id: int) -> None:
        if not self._on_profile_completed:
            return
        try:
            self._on_profile_completed(detection_id)
        except Exception as exc:
            logger.warning(
                "Visual profile handoff failed for detection %s: %s",
                detection_id,
                type(exc).__name__,
            )

    def backfill(self, limit: int, retry_failed: bool = False) -> VisualQueueResponse:
        if not self.provider:
            raise RegistryError(
                code="VISUAL_PROVIDER_NOT_CONFIGURED",
                message="Groq Visual Intelligence is not configured on the backend",
                status_code=503,
            )
        with self._connect() as connection:
            if not self._table_exists(connection, "detections"):
                return VisualQueueResponse(
                    queued=0, skipped=0, queue_depth=0, message="No vehicle crops are available."
                )
            rows = connection.execute(
                """SELECT d.id, d.source, d.track_id, d.time_ms, d.class_name,
                          d.confidence, d.width, d.height
                   FROM detections d
                   WHERE d.class_name IN (?, ?, ?, ?)
                     AND NOT EXISTS (
                         SELECT 1 FROM visual_vehicle_intelligence v
                         WHERE v.detection_id=d.id AND v.vlm_model=?
                           AND v.vlm_prompt_version=?
                           AND v.analysis_status IN ('PENDING', 'PROCESSING', 'COMPLETED')
                     )
                     AND (
                         ?=1 OR NOT EXISTS (
                             SELECT 1 FROM visual_vehicle_intelligence failed
                             WHERE failed.detection_id=d.id AND failed.vlm_model=?
                               AND failed.vlm_prompt_version=?
                               AND failed.analysis_status='FAILED'
                         )
                     )
                   ORDER BY (d.width * d.height * d.confidence) DESC,
                            d.created_at DESC, d.id DESC LIMIT ?""",
                (
                    *VEHICLE_CLASSES,
                    self.provider.model,
                    PROMPT_VERSION,
                    int(retry_failed),
                    self.provider.model,
                    PROMPT_VERSION,
                    max(limit * 20, limit),
                ),
            ).fetchall()
        selected: list[int] = []
        groups: set[tuple[object, ...]] = set()
        for row in rows:
            group = (
                row["source"],
                row["class_name"],
                row["track_id"]
                if row["track_id"] is not None
                else int(float(row["time_ms"]) // 5000),
            )
            if group in groups:
                continue
            groups.add(group)
            selected.append(int(row["id"]))
            if len(selected) >= limit:
                break
        queued = 0
        for detection_id in selected:
            if retry_failed:
                with self._connect() as connection:
                    connection.execute(
                        """UPDATE visual_vehicle_intelligence
                           SET analysis_status='RETRY_PENDING'
                           WHERE detection_id=? AND analysis_status='FAILED'""",
                        (detection_id,),
                    )
                    connection.commit()
            queued += int(self.queue_detection(detection_id))
        return VisualQueueResponse(
            queued=queued,
            skipped=len(selected) - queued,
            queue_depth=self._jobs.qsize(),
            message=(
                f"Queued {queued} representative vehicle "
                f"crop{'s' if queued != 1 else ''} for Groq enrichment."
            ),
        )

    def _row(self, row: sqlite3.Row) -> VisualIntelligenceRead:
        plate_id = row["plate_id"]
        return VisualIntelligenceRead(
            id=int(row["id"]),
            event_id=row["event_id"],
            detection_id=int(row["detection_id"]),
            vehicle_crop_uri=f"{self.api_prefix}/ai/detections/{row['detection_id']}/image",
            plate_crop_uri=f"{self.api_prefix}/ai/plates/{plate_id}/image" if plate_id else None,
            plate_id=plate_id,
            camera_id=row["source"].removeprefix("camera:"),
            track_id=row["track_id"],
            timestamp_ms=float(row["timestamp_ms"]),
            observed_at=row["observed_at"],
            anpr_plate=row["anpr_plate"],
            vehicle_present=bool(row["vehicle_present"]),
            vehicle_type=row["vehicle_type"],
            vehicle_type_confidence=row["vehicle_type_confidence"],
            primary_color=row["primary_color"],
            secondary_colors=[str(item) for item in _json_list(row["secondary_colors"])],
            damage_status=row["damage_status"],
            damage_regions=[
                DamageRegion.model_validate(item) for item in _json_list(row["damage_regions"])
            ],
            visual_condition=row["visual_condition"],
            distinctive_features=[str(item) for item in _json_list(row["distinctive_features"])],
            accessories=[str(item) for item in _json_list(row["accessories"])],
            vehicle_view=row["vehicle_view"],
            plate_visibility=row["plate_visibility"],
            lighting_condition=row["lighting_condition"],
            image_quality=row["image_quality"],
            occlusion=row["occlusion"],
            short_description=row["short_description"],
            detailed_description=row["detailed_description"],
            search_keywords=[str(item) for item in _json_list(row["search_keywords"])],
            analysis_confidence=row["analysis_confidence"],
            vlm_provider=row["vlm_provider"],
            vlm_model=row["vlm_model"],
            vlm_prompt_version=row["vlm_prompt_version"],
            analyzed_at=row["analyzed_at"],
            analysis_status=row["analysis_status"],
            analysis_error=row["analysis_error"],
        )

    def get(self, intelligence_id: int) -> VisualIntelligenceRead:
        self._synchronize_plate_links()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM visual_vehicle_intelligence WHERE id=?", (intelligence_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("visual_intelligence", str(intelligence_id))
        return self._row(row)

    def _synchronize_plate_links(self) -> None:
        with self._connect() as connection:
            if not self._table_exists(connection, "plate_detections"):
                return
            unlinked = connection.execute(
                """SELECT v.id, v.detection_id, v.source, d.frame
                   FROM visual_vehicle_intelligence v
                   JOIN detections d ON d.id=v.detection_id
                   WHERE v.plate_id IS NULL"""
            ).fetchall()
            plate_rows = connection.execute(
                """SELECT id, source_detection_id, source, frame,
                          ocr_confidence, detection_confidence
                   FROM plate_detections"""
            ).fetchall()
            direct: dict[int, list[sqlite3.Row]] = {}
            nearby: dict[tuple[str, int], list[sqlite3.Row]] = {}
            for plate in plate_rows:
                if plate["source_detection_id"] is not None:
                    direct.setdefault(int(plate["source_detection_id"]), []).append(plate)
                nearby.setdefault((str(plate["source"]), int(plate["frame"])), []).append(plate)

            def plate_rank(item: sqlite3.Row) -> tuple[float, float, int]:
                return (
                    float(item["ocr_confidence"] or 0),
                    float(item["detection_confidence"] or 0),
                    int(item["id"]),
                )

            links: list[tuple[int, int]] = []
            for item in unlinked:
                candidates = direct.get(int(item["detection_id"]), [])
                if not candidates:
                    candidates = [
                        plate
                        for frame in range(int(item["frame"]) - 2, int(item["frame"]) + 3)
                        for plate in nearby.get((str(item["source"]), frame), [])
                        if plate["source_detection_id"] is None
                    ]
                if candidates:
                    links.append((int(max(candidates, key=plate_rank)["id"]), int(item["id"])))
            if links:
                connection.executemany(
                    "UPDATE visual_vehicle_intelligence SET plate_id=? WHERE id=?", links
                )
            connection.execute(
                """UPDATE visual_vehicle_intelligence
                   SET anpr_plate=(
                       SELECT p.plate_text FROM plate_detections p
                       WHERE p.id=visual_vehicle_intelligence.plate_id
                   )
                   WHERE plate_id IS NOT NULL"""
            )
            connection.commit()

    @staticmethod
    def _understand_query(query: str) -> dict[str, Any]:
        lowered = query.lower()
        parsed: dict[str, Any] = {}
        for color in COLORS - {"unknown", "multi-colour"}:
            if re.search(rf"\b{re.escape(color)}\b", lowered):
                parsed["primary_color"] = color
                break
        type_aliases = {
            "bike": "motorcycle",
            "motorbike": "motorcycle",
            "auto rickshaw": "auto-rickshaw",
        }
        for alias, normalized in type_aliases.items():
            if alias in lowered:
                parsed["vehicle_type"] = normalized
                break
        if "vehicle_type" not in parsed:
            for vehicle_type in NORMALIZED_TYPES - {"unknown", "other", "car"}:
                if re.search(rf"\b{re.escape(vehicle_type)}s?\b", lowered):
                    parsed["vehicle_type"] = vehicle_type
                    break
        if any(
            term in lowered
            for term in ("damage", "damaged", "dent", "broken", "missing", "deformation")
        ):
            parsed["damage_required"] = True
        if any(term in lowered for term in ("unreadable plate", "poor plate", "plate not visible")):
            parsed["plate_visibility"] = "unreadable"
        camera = re.search(r"\b(?:camera\s*|cam[-_ ]?)([a-z0-9-]+)\b", lowered)
        if camera:
            parsed["camera_term"] = camera.group(1)
        parsed["terms"] = [
            token
            for token in re.findall(r"[a-z0-9-]+", lowered)
            if len(token) > 2 and token not in STOP_WORDS
        ]
        return parsed

    def search(
        self,
        *,
        query: str,
        filters: VisualSearchFilters,
        page: int,
        page_size: int,
        actor_id: str,
    ) -> VisualSearchResponse:
        self._synchronize_plate_links()
        parsed = self._understand_query(query)
        color = (filters.primary_color or parsed.get("primary_color") or "").lower()
        vehicle_type = (filters.vehicle_type or parsed.get("vehicle_type") or "").lower()
        damage_required = bool(parsed.get("damage_required")) or (
            bool(filters.damage_status) and filters.damage_status != "none_obvious"
        )
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM visual_vehicle_intelligence
                   WHERE analysis_status='COMPLETED' ORDER BY analyzed_at DESC"""
            ).fetchall()
        ranked: list[tuple[float, list[str], sqlite3.Row]] = []
        terms = parsed.get("terms", [])
        for row in rows:
            if (
                filters.camera_ids
                and row["source"].removeprefix("camera:") not in filters.camera_ids
            ):
                continue
            observed_date = str(row["observed_at"])[:10]
            if filters.date_from and observed_date < filters.date_from[:10]:
                continue
            if filters.date_to and observed_date > filters.date_to[:10]:
                continue
            if filters.plate_visibility and row["plate_visibility"] != filters.plate_visibility:
                continue
            if filters.image_quality and row["image_quality"] != filters.image_quality:
                continue
            if filters.damage_status and row["damage_status"] != filters.damage_status:
                continue
            observed_time = str(row["observed_at"])[11:19]
            if filters.time_from and observed_time < filters.time_from[:8]:
                continue
            if filters.time_to and observed_time > filters.time_to[:8]:
                continue
            if filters.damage_location:
                damage_text = " ".join(
                    (row["damage_regions"] or "", row["visual_condition"] or "")
                ).lower()
                if filters.damage_location.lower() not in damage_text:
                    continue
            score = 0.0
            reasons: list[str] = []
            if color:
                if row["primary_color"].lower() != color:
                    continue
                score += 3
                reasons.append(f"Colour: {color.title()}")
            if vehicle_type:
                if row["vehicle_type"].lower() != vehicle_type:
                    continue
                score += 3
                type_label = vehicle_type.upper() if vehicle_type == "suv" else vehicle_type.title()
                reasons.append(f"Vehicle type: {type_label}")
            if damage_required:
                if row["damage_status"] not in {"possible", "visible"}:
                    continue
                score += 3
                reasons.append(f"Visual condition: {row['damage_status'].title()} damage")
            if parsed.get("plate_visibility"):
                if row["plate_visibility"] not in {"unreadable", "not_visible", "partial"}:
                    continue
                score += 2
                reasons.append(
                    f"Plate visibility: {row['plate_visibility'].replace('_', ' ').title()}"
                )
            if parsed.get("camera_term") and parsed["camera_term"] not in row["source"].lower():
                continue
            haystack = " ".join(
                str(row[key] or "")
                for key in (
                    "short_description",
                    "detailed_description",
                    "visual_condition",
                    "distinctive_features",
                    "accessories",
                    "search_keywords",
                    "anpr_plate",
                    "source",
                )
            ).lower()
            matched_terms = [term for term in terms if term in haystack]
            score += min(len(matched_terms), 6)
            if matched_terms:
                reasons.append(f"Description contains: {', '.join(matched_terms[:4])}")
            if query.strip() and score <= 0:
                continue
            ranked.append((score, reasons or ["Recent analyzed vehicle observation"], row))
        ranked.sort(key=lambda item: (item[0], item[2]["analyzed_at"] or ""), reverse=True)
        total = len(ranked)
        offset = (page - 1) * page_size
        results: list[VisualSearchResult] = []
        for score, reasons, row in ranked[offset : offset + page_size]:
            level = "HIGH" if score >= 6 else "MEDIUM" if score >= 3 else "LOW"
            results.append(
                VisualSearchResult(
                    **self._row(row).model_dump(), match_level=level, match_reasons=reasons
                )
            )
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO visual_search_audit
                   (actor_id, query, filters_json, result_count, searched_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (actor_id, query, filters.model_dump_json(), total, _utc_now()),
            )
            connection.commit()
        readable = sum(bool(item.anpr_plate) for item in results)
        summary = (
            f"Found {total} vehicle observation{'s' if total != 1 else ''} matching “{query}”. "
            f"{readable} displayed result"
            f"{'s have' if readable != 1 else ' has'} a readable ANPR value."
            if query.strip()
            else (
                f"Showing {total} analyzed vehicle observation"
                f"{'s' if total != 1 else ''}, newest first."
            )
        )
        return VisualSearchResponse(
            query=query,
            total_results=total,
            page=page,
            page_size=page_size,
            pages=max(1, math.ceil(total / page_size)),
            summary=summary,
            parsed_filters={key: value for key, value in parsed.items() if key != "terms"},
            results=results,
        )

    def status(self) -> VisualIntelligenceStatus:
        counts: dict[str, int] = {}
        total_crops = 0
        average: float | None = None
        last_success: str | None = None
        with self._connect() as connection:
            if self._table_exists(connection, "detections"):
                total_crops = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM detections WHERE class_name IN (?, ?, ?, ?)",
                        VEHICLE_CLASSES,
                    ).fetchone()[0]
                )
            for row in connection.execute(
                """SELECT analysis_status, COUNT(*) count
                   FROM visual_vehicle_intelligence GROUP BY analysis_status"""
            ).fetchall():
                counts[row["analysis_status"]] = int(row["count"])
            aggregate = connection.execute(
                """SELECT AVG(processing_ms), MAX(analyzed_at)
                   FROM visual_vehicle_intelligence
                   WHERE analysis_status='COMPLETED'"""
            ).fetchone()
            average = round(float(aggregate[0]), 2) if aggregate[0] is not None else None
            last_success = aggregate[1]
        return VisualIntelligenceStatus(
            provider=self.provider.name if self.provider else "groq",
            model=self.provider.model if self.provider else "not configured",
            prompt_version=PROMPT_VERSION,
            configured=self.provider is not None,
            worker_running=bool(self._thread and self._thread.is_alive()),
            queue_depth=self._jobs.qsize(),
            total_vehicle_crops=total_crops,
            completed=counts.get("COMPLETED", 0),
            pending=counts.get("PENDING", 0) + counts.get("RETRY_PENDING", 0),
            processing=counts.get("PROCESSING", 0),
            failed=counts.get("FAILED", 0),
            skipped=counts.get("SKIPPED", 0),
            average_processing_ms=average,
            last_successful_request=last_success,
        )
