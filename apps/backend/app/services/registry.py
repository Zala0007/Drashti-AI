from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import BadRequestError, ConflictError, NotFoundError
from app.models import AuditLog, Camera, Department, ImportJob
from app.repositories import CameraFilters, RegistryRepository
from app.schemas.registry import (
    AuditList,
    CameraCreate,
    CameraFilterOptions,
    CameraList,
    CameraRead,
    CameraStatistics,
    CameraUpdate,
    DepartmentCreate,
    DepartmentList,
    DepartmentRead,
    DepartmentUpdate,
    DuplicateMode,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
    HeartbeatRequest,
    ImportResponse,
    ImportRowResult,
    page_count,
)

REDACTED_FIELDS = {"stream_reference", "credential_reference"}
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 10_000
MAX_FIELD_CHARS = 64 * 1024
MAX_RESULT_ROWS = 10_000

# Python's CSV parser otherwise accepts process-dependent field sizes. This
# backend owns CSV parsing in its process, so a fixed global parser ceiling is
# preferable to temporarily changing the process-global value per request.
csv.field_size_limit(MAX_FIELD_CHARS)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        else:
            value = value.astimezone(UTC)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(nested) for nested in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _redact_changes(changes: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in changes.items():
        if key in REDACTED_FIELDS:
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = _redact_changes(value)
        else:
            redacted[key] = _json_safe(value)
    return redacted


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _camera_orm_data(
    payload: CameraCreate | CameraUpdate, *, exclude_unset: bool = False
) -> dict[str, Any]:
    """Keep Python date/datetime values while converting the string UUID FK."""
    data = payload.model_dump(mode="python", exclude_unset=exclude_unset)
    if "department_id" in data and data["department_id"] is not None:
        data["department_id"] = str(data["department_id"])
    return data


class RegistryService:
    def __init__(
        self,
        session: Session,
        *,
        actor_id: str = "system",
        request_id: str | None = None,
    ) -> None:
        self.session = session
        self.repository = RegistryRepository(session)
        self.actor_id = actor_id
        self.request_id = request_id

    def _audit(
        self,
        *,
        resource_type: str,
        resource_id: str,
        action: str,
        changes: dict[str, Any],
        source: str = "api",
    ) -> None:
        self.repository.add(
            AuditLog(
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                actor_id=self.actor_id,
                request_id=self.request_id,
                source=source,
                changes=_redact_changes(changes),
            )
        )

    def _commit(self, *, conflict_code: str, conflict_message: str) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(conflict_code, conflict_message) from exc

    def create_department(self, payload: DepartmentCreate) -> DepartmentRead:
        if self.repository.get_department_by_code(payload.code):
            raise ConflictError(
                "DEPARTMENT_CODE_EXISTS",
                "A department with this code already exists",
                {"code": payload.code},
            )
        department = Department(**payload.model_dump(mode="json"))
        self.repository.add(department)
        self.session.flush()
        self._audit(
            resource_type="department",
            resource_id=department.id,
            action="department.created",
            changes={"after": payload.model_dump(mode="json")},
        )
        self._commit(
            conflict_code="DEPARTMENT_EXISTS",
            conflict_message="A department with the same code or name already exists",
        )
        self.session.refresh(department)
        return DepartmentRead.model_validate(department)

    def get_department(self, department_id: str) -> DepartmentRead:
        department = self.repository.get_department(department_id)
        if not department:
            raise NotFoundError("department", department_id)
        return DepartmentRead.model_validate(department)

    def list_departments(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        include_inactive: bool,
    ) -> DepartmentList:
        items, total = self.repository.list_departments(
            page=page,
            page_size=page_size,
            search=search,
            include_inactive=include_inactive,
        )
        return DepartmentList(
            items=[DepartmentRead.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=page_count(total, page_size),
        )

    def update_department(self, department_id: str, payload: DepartmentUpdate) -> DepartmentRead:
        department = self.repository.get_department(department_id)
        if not department:
            raise NotFoundError("department", department_id)
        updates = payload.model_dump(exclude_unset=True, mode="json")
        changes = {
            field: {"old": getattr(department, field), "new": value}
            for field, value in updates.items()
            if getattr(department, field) != value
        }
        for field, value in updates.items():
            setattr(department, field, value)
        if changes:
            self._audit(
                resource_type="department",
                resource_id=department.id,
                action="department.updated",
                changes=changes,
            )
        self._commit(
            conflict_code="DEPARTMENT_EXISTS",
            conflict_message="A department with this name already exists",
        )
        self.session.refresh(department)
        return DepartmentRead.model_validate(department)

    def create_camera(self, payload: CameraCreate) -> CameraRead:
        if self.repository.get_camera_by_code(payload.camera_code):
            raise ConflictError(
                "CAMERA_CODE_EXISTS",
                "A camera with this code already exists",
                {"camera_code": payload.camera_code},
            )
        department = self.repository.get_department(str(payload.department_id))
        if not department:
            raise NotFoundError("department", str(payload.department_id))
        if not department.is_active:
            raise ConflictError(
                "DEPARTMENT_INACTIVE",
                "Cameras cannot be assigned to an inactive department",
                {"department_id": str(payload.department_id)},
            )
        data = _camera_orm_data(payload)
        data["ai_enabled"] = bool(data["ai_capabilities"])
        camera = Camera(**data)
        self.repository.add(camera)
        self.session.flush()
        self._audit(
            resource_type="camera",
            resource_id=camera.id,
            action="camera.created",
            changes={"after": data},
        )
        self._commit(
            conflict_code="CAMERA_EXISTS",
            conflict_message="A camera with the same code or external identity already exists",
        )
        camera = self.repository.get_camera(camera.id)
        assert camera is not None
        return CameraRead.model_validate(camera)

    def get_camera(self, camera_id: str) -> CameraRead:
        camera = self.repository.get_camera(camera_id)
        if not camera:
            raise NotFoundError("camera", camera_id)
        return CameraRead.model_validate(camera)

    def list_cameras(self, *, filters: CameraFilters, page: int, page_size: int) -> CameraList:
        items, total = self.repository.list_cameras(filters=filters, page=page, page_size=page_size)
        return CameraList(
            items=[CameraRead.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=page_count(total, page_size),
        )

    def update_camera(self, camera_id: str, payload: CameraUpdate) -> CameraRead:
        camera = self.repository.get_camera(camera_id)
        if not camera:
            raise NotFoundError("camera", camera_id)
        if camera.status == "retired":
            raise ConflictError("CAMERA_RETIRED", "A retired camera cannot be modified")

        updates = _camera_orm_data(payload, exclude_unset=True)
        if "department_id" in updates:
            department = self.repository.get_department(str(updates["department_id"]))
            if not department:
                raise NotFoundError("department", str(updates["department_id"]))
            if not department.is_active:
                raise ConflictError(
                    "DEPARTMENT_INACTIVE",
                    "Cameras cannot be assigned to an inactive department",
                )
        if "ai_capabilities" in updates:
            updates["ai_enabled"] = bool(updates["ai_capabilities"])
        if updates.get("stream_protocol") == "rtsp":
            updates.setdefault("rtsp_capable", True)
        if updates.get("stream_protocol") == "onvif":
            updates.setdefault("onvif_capable", True)

        changes: dict[str, Any] = {}
        for field, value in updates.items():
            old_value = getattr(camera, field)
            if old_value != value:
                changes[field] = {"old": old_value, "new": value}
                setattr(camera, field, value)
        if changes:
            self._audit(
                resource_type="camera",
                resource_id=camera.id,
                action="camera.updated",
                changes=changes,
            )
        self._commit(
            conflict_code="CAMERA_UPDATE_CONFLICT",
            conflict_message="The camera update conflicts with an existing record",
        )
        camera = self.repository.get_camera(camera.id)
        assert camera is not None
        return CameraRead.model_validate(camera)

    def retire_camera(self, camera_id: str, *, reason: str) -> CameraRead:
        camera = self.repository.get_camera(camera_id)
        if not camera:
            raise NotFoundError("camera", camera_id)
        if camera.status == "retired":
            return CameraRead.model_validate(camera)
        retired_at = datetime.now(UTC)
        old_status = camera.status
        old_health = camera.health
        camera.status = "retired"
        camera.health = "offline"
        camera.retired_at = retired_at
        self._audit(
            resource_type="camera",
            resource_id=camera.id,
            action="camera.retired",
            changes={
                "status": {"old": old_status, "new": "retired"},
                "health": {"old": old_health, "new": "offline"},
                "retired_at": {"old": None, "new": retired_at},
                "reason": reason,
            },
        )
        self._commit(
            conflict_code="CAMERA_RETIRE_CONFLICT",
            conflict_message="The camera could not be retired",
        )
        camera = self.repository.get_camera(camera.id)
        assert camera is not None
        return CameraRead.model_validate(camera)

    def record_heartbeat(self, camera_id: str, payload: HeartbeatRequest) -> CameraRead:
        camera = self.repository.get_camera(camera_id)
        if not camera:
            raise NotFoundError("camera", camera_id)
        if camera.status == "retired":
            raise ConflictError("CAMERA_RETIRED", "Heartbeat is not accepted for a retired camera")
        observed_at = _aware_utc(payload.observed_at)
        now = datetime.now(UTC)
        if (observed_at - now).total_seconds() > 300:
            raise BadRequestError(
                "HEARTBEAT_IN_FUTURE",
                "Heartbeat timestamp cannot be more than five minutes in the future",
            )
        if camera.last_heartbeat and observed_at < _aware_utc(camera.last_heartbeat):
            raise ConflictError(
                "STALE_HEARTBEAT",
                "Heartbeat is older than the latest recorded heartbeat",
                {"last_heartbeat": _aware_utc(camera.last_heartbeat).isoformat()},
            )
        old_health = camera.health
        camera.health = payload.health.value if isinstance(payload.health, Enum) else payload.health
        camera.last_heartbeat = observed_at
        camera.health_details = payload.details
        self._audit(
            resource_type="camera",
            resource_id=camera.id,
            action="camera.heartbeat",
            changes={
                "health": {"old": old_health, "new": camera.health},
                "last_heartbeat": observed_at,
                "details": payload.details,
            },
            source="heartbeat",
        )
        self._commit(
            conflict_code="HEARTBEAT_CONFLICT",
            conflict_message="Heartbeat could not be recorded",
        )
        camera = self.repository.get_camera(camera.id)
        assert camera is not None
        return CameraRead.model_validate(camera)

    def statistics(self, *, filters: CameraFilters) -> CameraStatistics:
        values = self.repository.camera_statistics(filters=filters)
        health = values["by_health"]
        return CameraStatistics(
            total=values["total"],
            online=health.get("online", 0),
            offline=health.get("offline", 0),
            degraded=health.get("degraded", 0),
            unknown=health.get("unknown", 0),
            ai_enabled=values["ai_enabled"],
            by_department=values["by_department"],
            by_status=values["by_status"],
            by_health=health,
        )

    def filter_options(self, *, include_retired: bool = False) -> CameraFilterOptions:
        return CameraFilterOptions.model_validate(
            self.repository.camera_filter_options(include_retired=include_retired)
        )

    def geojson(self, *, filters: CameraFilters, limit: int) -> GeoJSONFeatureCollection:
        items, total = self.repository.list_cameras(filters=filters, page=1, page_size=limit)
        features = []
        for camera in items:
            properties = {
                "camera_code": camera.camera_code,
                "camera_name": camera.camera_name,
                "department_id": camera.department_id,
                "department_code": camera.department.code,
                "department_name": camera.department.name,
                "district": camera.district,
                "city": camera.city,
                "location_description": camera.location_description,
                "camera_type": camera.camera_type,
                "vendor": camera.vendor,
                "model": camera.model,
                "vms": camera.vms,
                "connectivity_type": camera.connectivity_type,
                "stream_protocol": camera.stream_protocol,
                "rtsp_capable": camera.rtsp_capable,
                "onvif_capable": camera.onvif_capable,
                "status": camera.status,
                "health": camera.health,
                "last_heartbeat": _json_safe(camera.last_heartbeat),
                "ownership": camera.ownership,
                "owner_name": camera.owner_name,
                "is_public_facing": camera.is_public_facing,
                "ai_capabilities": camera.ai_capabilities,
                "ai_enabled": camera.ai_enabled,
                "tags": camera.tags,
                "coverage_radius_m": camera.coverage_radius_m,
                "bearing_degrees": camera.bearing_degrees,
                "field_of_view_degrees": camera.field_of_view_degrees,
                "installation_date": _json_safe(camera.installation_date),
                "installed_by": camera.installed_by,
                "created_at": _json_safe(camera.created_at),
                "updated_at": _json_safe(camera.updated_at),
            }
            features.append(
                GeoJSONFeature(
                    id=UUID(camera.id),
                    geometry=GeoJSONGeometry(coordinates=(camera.longitude, camera.latitude)),
                    properties=properties,
                )
            )
        return GeoJSONFeatureCollection(
            features=features,
            number_matched=total,
            number_returned=len(features),
        )

    def camera_audit(self, camera_id: str, *, page: int, page_size: int) -> AuditList:
        if not self.repository.get_camera(camera_id):
            raise NotFoundError("camera", camera_id)
        items, total = self.repository.list_audit_logs(
            resource_type="camera",
            resource_id=camera_id,
            page=page,
            page_size=page_size,
        )
        return AuditList(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=page_count(total, page_size),
        )

    def import_csv(
        self,
        *,
        content: bytes,
        supplied_idempotency_key: str | None,
        on_duplicate: DuplicateMode,
    ) -> ImportResponse:
        if not content:
            raise BadRequestError("EMPTY_IMPORT", "The uploaded CSV file is empty")
        if len(content) > MAX_IMPORT_BYTES:
            raise BadRequestError(
                "IMPORT_TOO_LARGE", "CSV imports are limited to 10 MiB per request"
            )
        digest = hashlib.sha256(content).hexdigest()
        idempotency_key = (supplied_idempotency_key or f"sha256:{digest}").strip()
        if not idempotency_key or len(idempotency_key) > 200:
            raise BadRequestError(
                "INVALID_IDEMPOTENCY_KEY",
                "Idempotency-Key must contain 1-200 characters",
            )
        existing_job = self.repository.get_import_job(idempotency_key)
        if existing_job:
            if existing_job.content_sha256 != digest:
                raise ConflictError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "The Idempotency-Key was already used with different content",
                )
            replay = dict(existing_job.response_payload)
            replay["replayed"] = True
            return ImportResponse.model_validate(replay)

        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BadRequestError("INVALID_CSV_ENCODING", "CSV must be UTF-8 encoded") from exc

        reader = csv.DictReader(io.StringIO(decoded), strict=True)
        try:
            fieldnames = reader.fieldnames
        except csv.Error as exc:
            self._raise_csv_parser_error(exc, line_number=reader.line_num or None)
        if not fieldnames:
            raise BadRequestError("INVALID_CSV", "CSV header row is missing")
        headers = {header.strip() for header in fieldnames if header}
        required = {"camera_code", "camera_name", "district", "latitude", "longitude"}
        missing = sorted(required - headers)
        if missing or not ({"department_id", "department_code"} & headers):
            if not ({"department_id", "department_code"} & headers):
                missing.append("department_id or department_code")
            raise BadRequestError(
                "MISSING_CSV_COLUMNS",
                "CSV is missing required columns",
                {"missing": missing},
            )

        job = ImportJob(
            idempotency_key=idempotency_key,
            content_sha256=digest,
            status="processing",
            response_payload={},
        )
        self.repository.add(job)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(
                "IMPORT_IN_PROGRESS",
                "An import with this Idempotency-Key is already in progress",
            ) from exc

        results: list[ImportRowResult] = []
        counts = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
        allowed_fields = set(CameraCreate.model_fields)
        row_count = 0
        while True:
            try:
                raw_row = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:
                self._raise_csv_parser_error(exc, line_number=reader.line_num or None)
            row_count += 1
            if row_count > MAX_IMPORT_ROWS:
                self.session.rollback()
                raise BadRequestError(
                    "IMPORT_ROW_LIMIT_EXCEEDED",
                    f"CSV imports are limited to {MAX_IMPORT_ROWS} data rows",
                    {"max_rows": MAX_IMPORT_ROWS},
                )
            if len(results) >= MAX_RESULT_ROWS:
                self.session.rollback()
                raise BadRequestError(
                    "IMPORT_RESULT_LIMIT_EXCEEDED",
                    "CSV import result limit was exceeded",
                    {"max_result_rows": MAX_RESULT_ROWS},
                )
            row_number = row_count + 1
            camera_code = (raw_row.get("camera_code") or "").strip().upper() or None
            try:
                row = self._prepare_csv_row(raw_row, allowed_fields=allowed_fields)
                payload = CameraCreate.model_validate(row)
                department = self.repository.get_department(str(payload.department_id))
                if not department:
                    raise NotFoundError("department", str(payload.department_id))
                if not department.is_active:
                    raise ConflictError(
                        "DEPARTMENT_INACTIVE", "The selected department is inactive"
                    )
                existing = self.repository.get_camera_by_code(payload.camera_code)
                if existing and on_duplicate == DuplicateMode.skip:
                    counts["skipped"] += 1
                    results.append(
                        ImportRowResult(
                            row_number=row_number,
                            camera_code=payload.camera_code,
                            camera_id=UUID(existing.id),
                            status="skipped",
                            error={"code": "DUPLICATE_CAMERA", "message": "Camera already exists"},
                        )
                    )
                    continue
                if existing and on_duplicate == DuplicateMode.error:
                    raise ConflictError("DUPLICATE_CAMERA", "Camera code already exists")

                with self.session.begin_nested():
                    if existing:
                        self._update_from_import(existing, payload)
                        camera = existing
                        action = "camera.imported_update"
                        status = "updated"
                    else:
                        data = _camera_orm_data(payload)
                        data["ai_enabled"] = bool(data["ai_capabilities"])
                        camera = Camera(**data)
                        self.repository.add(camera)
                        action = "camera.imported_create"
                        status = "created"
                    self.session.flush()
                    self._audit(
                        resource_type="camera",
                        resource_id=camera.id,
                        action=action,
                        changes={"import_id": job.id, "camera_code": camera.camera_code},
                        source="csv_import",
                    )
                    self.session.flush()
                counts[status] += 1
                results.append(
                    ImportRowResult(
                        row_number=row_number,
                        camera_code=payload.camera_code,
                        camera_id=UUID(camera.id),
                        status=status,
                    )
                )
            except (
                ValidationError,
                NotFoundError,
                ConflictError,
                ValueError,
                IntegrityError,
            ) as exc:
                counts["failed"] += 1
                results.append(
                    ImportRowResult(
                        row_number=row_number,
                        camera_code=camera_code,
                        status="failed",
                        error=self._row_error(exc),
                    )
                )

        response = ImportResponse(
            import_id=UUID(job.id),
            idempotency_key=idempotency_key,
            total_rows=len(results),
            created=counts["created"],
            updated=counts["updated"],
            skipped=counts["skipped"],
            failed=counts["failed"],
            results=results,
        )
        job.status = "completed_with_errors" if counts["failed"] else "completed"
        job.completed_at = datetime.now(UTC)
        job.response_payload = response.model_dump(mode="json")
        self._commit(
            conflict_code="IMPORT_COMMIT_CONFLICT",
            conflict_message="The camera import could not be committed",
        )
        return response

    def _raise_csv_parser_error(self, exc: csv.Error, *, line_number: int | None) -> None:
        self.session.rollback()
        field_too_large = "field larger than field limit" in str(exc).lower()
        raise BadRequestError(
            "CSV_FIELD_TOO_LARGE" if field_too_large else "INVALID_CSV_SYNTAX",
            (
                f"A CSV field exceeds the {MAX_FIELD_CHARS}-character limit"
                if field_too_large
                else "CSV syntax could not be parsed"
            ),
            {
                "line_number": line_number,
                "max_field_chars": MAX_FIELD_CHARS,
            },
        ) from exc

    def _prepare_csv_row(
        self, raw_row: dict[str | None, str | None], *, allowed_fields: set[str]
    ) -> dict[str, Any]:
        row: dict[str, Any] = {}
        for raw_key, raw_value in raw_row.items():
            if raw_key is None:
                continue
            key = raw_key.strip()
            if key not in allowed_fields or raw_value is None:
                continue
            value = raw_value.strip()
            if not value:
                if key in {"camera_code", "camera_name", "district", "latitude", "longitude"}:
                    row[key] = value
                continue
            if key in {"rtsp_capable", "onvif_capable", "is_public_facing"}:
                lowered = value.lower()
                if lowered not in {"true", "false", "1", "0", "yes", "no"}:
                    raise ValueError(f"{key} must be true or false")
                row[key] = lowered in {"true", "1", "yes"}
            elif key in {"ai_capabilities", "tags"}:
                if value.startswith("["):
                    parsed = json.loads(value)
                    if not isinstance(parsed, list):
                        raise ValueError(f"{key} must be a JSON array or pipe-separated list")
                    row[key] = parsed
                else:
                    row[key] = [item.strip() for item in value.split("|") if item.strip()]
            elif key in {"storage_details", "installation_metadata"}:
                parsed = json.loads(value)
                if not isinstance(parsed, dict):
                    raise ValueError(f"{key} must be a JSON object")
                row[key] = parsed
            else:
                row[key] = value

        if not row.get("department_id"):
            department_code = (raw_row.get("department_code") or "").strip().upper()
            if not department_code:
                raise ValueError("department_id or department_code is required")
            department = self.repository.get_department_by_code(department_code)
            if not department:
                raise ValueError(f"unknown department_code '{department_code}'")
            row["department_id"] = department.id
        return row

    def _update_from_import(self, camera: Camera, payload: CameraCreate) -> None:
        data = _camera_orm_data(payload)
        explicitly_supplied = set(payload.model_fields_set) - {"camera_code"}
        data = {field: value for field, value in data.items() if field in explicitly_supplied}
        if "ai_capabilities" in explicitly_supplied:
            data["ai_enabled"] = bool(data["ai_capabilities"])
        if "stream_protocol" in explicitly_supplied:
            if payload.stream_protocol == "rtsp":
                data["rtsp_capable"] = True
            elif payload.stream_protocol == "onvif":
                data["onvif_capable"] = True
        changes: dict[str, Any] = {}
        for field, value in data.items():
            old_value = getattr(camera, field)
            if old_value != value:
                changes[field] = {"old": old_value, "new": value}
                setattr(camera, field, value)
        if changes:
            self._audit(
                resource_type="camera",
                resource_id=camera.id,
                action="camera.updated",
                changes=changes,
                source="csv_import",
            )

    @staticmethod
    def _row_error(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, ValidationError):
            return {
                "code": "ROW_VALIDATION_ERROR",
                "message": "CSV row validation failed",
                "details": [
                    {
                        "field": ".".join(str(part) for part in error["loc"]),
                        "message": error["msg"],
                        "type": error["type"],
                    }
                    for error in exc.errors(include_url=False, include_context=False)
                ],
            }
        if isinstance(exc, (NotFoundError, ConflictError)):
            return {"code": exc.code, "message": exc.message, "details": exc.details}
        if isinstance(exc, IntegrityError):
            return {
                "code": "ROW_CONFLICT",
                "message": "CSV row conflicts with an existing camera identity",
            }
        return {"code": "INVALID_ROW", "message": str(exc)}
