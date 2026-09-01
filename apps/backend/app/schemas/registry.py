from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class CameraStatus(StrEnum):
    planned = "planned"
    active = "active"
    maintenance = "maintenance"
    inactive = "inactive"
    retired = "retired"


class HealthStatus(StrEnum):
    unknown = "unknown"
    online = "online"
    offline = "offline"
    degraded = "degraded"


class CameraType(StrEnum):
    fixed = "fixed"
    ptz = "ptz"
    dome = "dome"
    bullet = "bullet"
    anpr = "anpr"
    thermal = "thermal"
    panoramic = "panoramic"
    analog = "analog"
    other = "other"


class ConnectivityType(StrEnum):
    fiber = "fiber"
    mpls = "mpls"
    broadband = "broadband"
    cellular_4g = "cellular_4g"
    cellular_5g = "cellular_5g"
    lan = "lan"
    wireless = "wireless"
    satellite = "satellite"
    unknown = "unknown"


class StreamProtocol(StrEnum):
    rtsp = "rtsp"
    onvif = "onvif"
    hls = "hls"
    http = "http"
    vendor_sdk = "vendor_sdk"
    none = "none"


class OwnershipType(StrEnum):
    government = "government"
    private = "private"
    public_private = "public_private"
    unknown = "unknown"


class DuplicateMode(StrEnum):
    skip = "skip"
    update = "update"
    error = "error"


class RegistrySchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    @model_validator(mode="after")
    def normalize_response_datetimes(self) -> RegistrySchema:
        # SQLite does not preserve timezone metadata even for timezone=True
        # columns. Normalize every schema datetime so local demo and Postgres
        # responses have the same unambiguous UTC semantics.
        for field_name in type(self).model_fields:
            value = getattr(self, field_name, None)
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                else:
                    value = value.astimezone(UTC)
                object.__setattr__(self, field_name, value)
        return self


def _normalized_code(value: str) -> str:
    normalized = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_.:/-]{1,63}", normalized):
        raise ValueError(
            "must be 2-64 characters using letters, numbers, '.', '_', ':', '/' or '-'"
        )
    return normalized


def _normalized_list(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip().lower()
        if not value or value in seen:
            continue
        if len(value) > 80:
            raise ValueError("list entries must not exceed 80 characters")
        result.append(value)
        seen.add(value)
    return result


def _reject_secrets(value: Any, path: str = "value") -> Any:
    prohibited_fragments = (
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "credential",
        "authorization",
        "auth",
        "bearer",
        "private",
        "access",
        "signature",
    )
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in prohibited_fragments):
                raise ValueError(f"{path} must not contain secret-bearing key '{key}'")
            _reject_secrets(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secrets(nested, f"{path}[{index}]")
    elif isinstance(value, str):
        parsed = urlsplit(value.strip())
        if parsed.username or parsed.password:
            raise ValueError(f"{path} must not contain URL-embedded credentials")
        query_keys = {key.lower() for key in parse_qs(parsed.query)}
        if any(any(fragment in key for fragment in prohibited_fragments) for key in query_keys):
            raise ValueError(f"{path} must not contain secret-bearing query parameters")
        if re.fullmatch(r"(?i)\s*(?:bearer|basic)\s+[A-Za-z0-9+/=_:.-]{8,}\s*", value):
            raise ValueError(f"{path} must not contain an authorization value")
    return value


def _validate_opaque_reference(
    value: str | None, *, allowed_prefixes: tuple[str, ...], field_name: str
) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    prefixes = "|".join(re.escape(prefix) for prefix in allowed_prefixes)
    if not re.fullmatch(rf"(?:{prefixes}):[A-Za-z0-9][A-Za-z0-9._/-]{{0,399}}", value):
        allowed = ", ".join(f"{prefix}:<safe-id>" for prefix in allowed_prefixes)
        raise ValueError(
            f"{field_name} must be an opaque profile identifier ({allowed}); URLs are prohibited"
        )
    return value


class DepartmentCreate(RegistrySchema):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return _normalized_code(value)


class DepartmentUpdate(RegistrySchema):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def ensure_change(self) -> DepartmentUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        for field in {"name", "is_active"}:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class DepartmentRead(RegistrySchema):
    id: UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DepartmentSummary(RegistrySchema):
    id: UUID
    code: str
    name: str


class DepartmentList(RegistrySchema):
    items: list[DepartmentRead]
    total: int
    page: int
    page_size: int
    pages: int


class CameraCreate(RegistrySchema):
    camera_code: str = Field(min_length=2, max_length=64)
    camera_name: str = Field(min_length=2, max_length=200)
    department_id: UUID
    district: str = Field(min_length=2, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    city: str | None = Field(default=None, max_length=100)
    location_description: str | None = Field(default=None, max_length=500)
    coverage_radius_m: float | None = Field(default=None, gt=0, le=100_000)
    bearing_degrees: float | None = Field(default=None, ge=0, lt=360)
    field_of_view_degrees: float | None = Field(default=None, gt=0, le=360)

    camera_type: CameraType = CameraType.other
    status: CameraStatus = CameraStatus.planned
    health: HealthStatus = HealthStatus.unknown
    connectivity_type: ConnectivityType = ConnectivityType.unknown
    stream_protocol: StreamProtocol = StreamProtocol.none
    vendor: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    vms: str | None = Field(default=None, max_length=160)
    stream_reference: str | None = Field(default=None, max_length=500)
    credential_reference: str | None = Field(default=None, max_length=500)
    rtsp_capable: bool = False
    onvif_capable: bool = False

    ownership: OwnershipType = OwnershipType.government
    owner_name: str | None = Field(default=None, max_length=160)
    is_public_facing: bool = True
    storage_details: dict[str, Any] = Field(default_factory=dict)
    ai_capabilities: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=50)
    installation_date: date | None = None
    installed_by: str | None = Field(default=None, max_length=160)
    installation_metadata: dict[str, Any] = Field(default_factory=dict)
    source_system: str | None = Field(default=None, max_length=100)
    external_id: str | None = Field(default=None, max_length=160)

    @field_validator("camera_code")
    @classmethod
    def normalize_camera_code(cls, value: str) -> str:
        return _normalized_code(value)

    @field_validator("ai_capabilities", "tags")
    @classmethod
    def normalize_lists(cls, value: list[str]) -> list[str]:
        return _normalized_list(value)

    @field_validator("stream_reference")
    @classmethod
    def validate_stream_reference(cls, value: str | None) -> str | None:
        return _validate_opaque_reference(
            value,
            allowed_prefixes=("connection-profile", "stream-profile"),
            field_name="stream_reference",
        )

    @field_validator("credential_reference")
    @classmethod
    def validate_credential_reference(cls, value: str | None) -> str | None:
        return _validate_opaque_reference(
            value,
            allowed_prefixes=("credential-profile", "vault-ref"),
            field_name="credential_reference",
        )

    @field_validator("storage_details", "installation_metadata")
    @classmethod
    def reject_embedded_secrets(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _reject_secrets(value)

    @model_validator(mode="after")
    def validate_capability_protocol(self) -> CameraCreate:
        if self.status == CameraStatus.retired:
            raise ValueError("new cameras cannot be retired; use the retirement endpoint")
        if self.stream_protocol == StreamProtocol.rtsp:
            self.rtsp_capable = True
        if self.stream_protocol == StreamProtocol.onvif:
            self.onvif_capable = True
        if bool(self.source_system) != bool(self.external_id):
            raise ValueError("source_system and external_id must be supplied together")
        return self


class CameraUpdate(RegistrySchema):
    camera_name: str | None = Field(default=None, min_length=2, max_length=200)
    department_id: UUID | None = None
    district: str | None = Field(default=None, min_length=2, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    city: str | None = Field(default=None, max_length=100)
    location_description: str | None = Field(default=None, max_length=500)
    coverage_radius_m: float | None = Field(default=None, gt=0, le=100_000)
    bearing_degrees: float | None = Field(default=None, ge=0, lt=360)
    field_of_view_degrees: float | None = Field(default=None, gt=0, le=360)
    camera_type: CameraType | None = None
    status: CameraStatus | None = None
    health: HealthStatus | None = None
    connectivity_type: ConnectivityType | None = None
    stream_protocol: StreamProtocol | None = None
    vendor: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    vms: str | None = Field(default=None, max_length=160)
    stream_reference: str | None = Field(default=None, max_length=500)
    credential_reference: str | None = Field(default=None, max_length=500)
    rtsp_capable: bool | None = None
    onvif_capable: bool | None = None
    ownership: OwnershipType | None = None
    owner_name: str | None = Field(default=None, max_length=160)
    is_public_facing: bool | None = None
    storage_details: dict[str, Any] | None = None
    ai_capabilities: list[str] | None = Field(default=None, max_length=50)
    tags: list[str] | None = Field(default=None, max_length=50)
    installation_date: date | None = None
    installed_by: str | None = Field(default=None, max_length=160)
    installation_metadata: dict[str, Any] | None = None

    @field_validator("ai_capabilities", "tags")
    @classmethod
    def normalize_lists(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _normalized_list(value)

    @field_validator("stream_reference")
    @classmethod
    def validate_stream_reference(cls, value: str | None) -> str | None:
        return _validate_opaque_reference(
            value,
            allowed_prefixes=("connection-profile", "stream-profile"),
            field_name="stream_reference",
        )

    @field_validator("credential_reference")
    @classmethod
    def validate_credential_reference(cls, value: str | None) -> str | None:
        return _validate_opaque_reference(
            value,
            allowed_prefixes=("credential-profile", "vault-ref"),
            field_name="credential_reference",
        )

    @field_validator("storage_details", "installation_metadata")
    @classmethod
    def reject_embedded_secrets(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if value is None else _reject_secrets(value)

    @model_validator(mode="after")
    def validate_update(self) -> CameraUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        non_nullable = {
            "camera_name",
            "department_id",
            "district",
            "latitude",
            "longitude",
            "camera_type",
            "status",
            "health",
            "connectivity_type",
            "stream_protocol",
            "rtsp_capable",
            "onvif_capable",
            "ownership",
            "is_public_facing",
            "storage_details",
            "ai_capabilities",
            "tags",
            "installation_metadata",
        }
        for field in non_nullable & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if self.status == CameraStatus.retired:
            raise ValueError("use the dedicated retirement endpoint")
        return self


class CameraRead(RegistrySchema):
    id: UUID
    camera_code: str
    camera_name: str
    department_id: UUID
    department: DepartmentSummary
    district: str
    city: str | None
    location_description: str | None
    latitude: float
    longitude: float
    coverage_radius_m: float | None
    bearing_degrees: float | None
    field_of_view_degrees: float | None
    camera_type: CameraType
    vendor: str | None
    model: str | None
    vms: str | None
    connectivity_type: ConnectivityType
    stream_protocol: StreamProtocol
    rtsp_capable: bool
    onvif_capable: bool
    status: CameraStatus
    health: HealthStatus
    last_heartbeat: datetime | None
    health_details: dict[str, Any]
    ownership: OwnershipType
    owner_name: str | None
    is_public_facing: bool
    storage_details: dict[str, Any]
    ai_capabilities: list[str]
    ai_enabled: bool
    tags: list[str]
    installation_date: date | None
    installed_by: str | None
    installation_metadata: dict[str, Any]
    source_system: str | None
    external_id: str | None
    retired_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CameraList(RegistrySchema):
    items: list[CameraRead]
    total: int
    page: int
    page_size: int
    pages: int


class HeartbeatRequest(RegistrySchema):
    health: HealthStatus
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("details")
    @classmethod
    def reject_embedded_secrets(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _reject_secrets(value)

    @field_validator("observed_at")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class RetirementRequest(RegistrySchema):
    reason: str = Field(min_length=3, max_length=500)


class AuditRead(RegistrySchema):
    id: UUID
    resource_type: str
    resource_id: UUID
    action: str
    actor_id: str
    request_id: str | None
    source: str
    changes: dict[str, Any]
    created_at: datetime


class AuditList(RegistrySchema):
    items: list[AuditRead]
    total: int
    page: int
    page_size: int
    pages: int


class CountGroup(RegistrySchema):
    key: str
    count: int


class DepartmentCount(RegistrySchema):
    department_id: UUID
    department_code: str
    department_name: str
    count: int


class CameraStatistics(RegistrySchema):
    total: int
    online: int
    offline: int
    degraded: int
    unknown: int
    ai_enabled: int
    by_department: list[DepartmentCount]
    by_status: dict[str, int]
    by_health: dict[str, int]


class CameraFilterOptions(RegistrySchema):
    districts: list[str]
    cities: list[str]
    vendors: list[str]
    vms: list[str]
    ai_capabilities: list[str]
    camera_types: list[str]
    connectivity_types: list[str]
    stream_protocols: list[str]


class GeoJSONGeometry(RegistrySchema):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]


class GeoJSONFeature(RegistrySchema):
    type: Literal["Feature"] = "Feature"
    id: UUID
    geometry: GeoJSONGeometry
    properties: dict[str, Any]


class GeoJSONFeatureCollection(RegistrySchema):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]
    number_matched: int
    number_returned: int


class ImportRowResult(RegistrySchema):
    row_number: int
    camera_code: str | None = None
    status: Literal["created", "updated", "skipped", "failed"]
    camera_id: UUID | None = None
    error: dict[str, Any] | None = None


class ImportResponse(RegistrySchema):
    import_id: UUID
    idempotency_key: str
    replayed: bool = False
    total_rows: int
    created: int
    updated: int
    skipped: int
    failed: int
    results: list[ImportRowResult]


class HealthResponse(RegistrySchema):
    status: Literal["ok", "ready", "not_ready"]
    service: str
    version: str
    checks: dict[str, str] = Field(default_factory=dict)


class ErrorDetail(RegistrySchema):
    code: str
    message: str
    details: Any = None
    request_id: str | None = None


class ErrorResponse(RegistrySchema):
    error: ErrorDetail


def page_count(total: int, page_size: int) -> int:
    return math.ceil(total / page_size) if total else 0
