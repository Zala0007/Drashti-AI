from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator

from app.schemas.registry import AuditRead, RegistrySchema


class AdapterKind(StrEnum):
    rtsp = "rtsp"
    hls = "hls"
    mjpeg = "mjpeg"
    onvif = "onvif"
    vms_http = "vms_http"
    recorded_file = "recorded_file"


class StreamRole(StrEnum):
    primary = "primary"
    substream = "substream"
    playback = "playback"
    metadata = "metadata"


class VerificationStatus(StrEnum):
    unverified = "unverified"
    reachable = "reachable"
    unreachable = "unreachable"
    authentication_required = "authentication_required"
    blocked = "blocked"
    misconfigured = "misconfigured"
    adapter_unavailable = "adapter_unavailable"
    disabled = "disabled"


class AdapterManifestRead(RegistrySchema):
    kind: AdapterKind
    label: str
    description: str
    version: str
    schemes: list[str] | tuple[str, ...]
    capabilities: list[str] | tuple[str, ...]
    supports_discovery: bool
    supports_probe: bool
    supports_stream_handoff: bool
    available: bool
    unavailable_reason: str | None


class AdapterList(RegistrySchema):
    items: list[AdapterManifestRead]


class ConnectionCreate(RegistrySchema):
    camera_id: UUID
    name: str = Field(min_length=2, max_length=160)
    adapter_kind: AdapterKind
    endpoint: SecretStr = Field(min_length=4, max_length=4096)
    stream_role: StreamRole = StreamRole.primary
    credential_reference: str | None = Field(default=None, max_length=500)
    priority: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True

    @field_validator("credential_reference")
    @classmethod
    def reject_obvious_secret_values(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if "://" in value or "@" in value or "=" in value:
            raise ValueError("must be an opaque credential reference, never a secret or URL")
        return value


class ConnectionUpdate(RegistrySchema):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    adapter_kind: AdapterKind | None = None
    endpoint: SecretStr | None = Field(default=None, min_length=4, max_length=4096)
    stream_role: StreamRole | None = None
    credential_reference: str | None = Field(default=None, max_length=500)
    priority: int | None = Field(default=None, ge=0, le=1000)
    enabled: bool | None = None

    @field_validator("credential_reference")
    @classmethod
    def reject_obvious_secret_values(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if "://" in value or "@" in value or "=" in value:
            raise ValueError("must be an opaque credential reference, never a secret or URL")
        return value

    @model_validator(mode="after")
    def ensure_change(self) -> ConnectionUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        non_nullable = {
            "name",
            "adapter_kind",
            "endpoint",
            "stream_role",
            "priority",
            "enabled",
        }
        for field_name in non_nullable & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ConnectionCameraRead(RegistrySchema):
    id: UUID
    camera_code: str
    camera_name: str
    department_id: UUID
    department_code: str
    department_name: str
    district: str
    city: str | None
    latitude: float
    longitude: float


class ConnectionRead(RegistrySchema):
    id: UUID
    name: str
    adapter_kind: AdapterKind
    stream_role: StreamRole
    endpoint_display: str
    endpoint_fingerprint: str
    enabled: bool
    priority: int
    verification_status: VerificationStatus
    last_probe_at: datetime | None
    last_probe_latency_ms: float | None
    last_error_code: str | None
    last_error_message: str | None
    last_success_at: datetime | None
    failure_count: int
    normalized_metadata: dict[str, Any]
    encryption_key_id: str
    has_credential_reference: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    camera: ConnectionCameraRead


class ConnectionList(RegistrySchema):
    items: list[ConnectionRead]
    total: int
    page: int
    page_size: int
    pages: int


class ConnectionStatistics(RegistrySchema):
    total: int
    enabled: int
    disabled: int
    by_status: dict[str, int]
    by_adapter_kind: dict[str, int]
    healthy_ratio: float
    last_probe_at: datetime | None


class ConnectionAuditList(RegistrySchema):
    items: list[AuditRead]
    total: int
    page: int
    page_size: int
    pages: int
