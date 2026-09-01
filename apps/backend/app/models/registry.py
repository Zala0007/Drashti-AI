from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Department(TimestampMixin, Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    cameras: Mapped[list[Camera]] = relationship(back_populates="department")


class Camera(TimestampMixin, Base):
    __tablename__ = "cameras"
    __table_args__ = (
        UniqueConstraint("source_system", "external_id", name="uq_camera_source_external"),
        Index("ix_cameras_department_status", "department_id", "status"),
        Index("ix_cameras_district_health", "district", "health"),
        Index("ix_cameras_latitude_longitude", "latitude", "longitude"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    camera_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    camera_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    department_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    district: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    city: Mapped[str | None] = mapped_column(String(100), index=True)
    location_description: Mapped[str | None] = mapped_column(String(500))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    coverage_radius_m: Mapped[float | None] = mapped_column(Float)
    bearing_degrees: Mapped[float | None] = mapped_column(Float)
    field_of_view_degrees: Mapped[float | None] = mapped_column(Float)

    camera_type: Mapped[str] = mapped_column(String(30), default="other", nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(120), index=True)
    model: Mapped[str | None] = mapped_column(String(120))
    vms: Mapped[str | None] = mapped_column(String(160), index=True)
    connectivity_type: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    stream_protocol: Mapped[str] = mapped_column(String(30), default="none", nullable=False)
    stream_reference: Mapped[str | None] = mapped_column(String(500))
    credential_reference: Mapped[str | None] = mapped_column(String(500))
    rtsp_capable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    onvif_capable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[str] = mapped_column(String(30), default="planned", nullable=False, index=True)
    health: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False, index=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    health_details: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, default=dict, nullable=False
    )

    ownership: Mapped[str] = mapped_column(String(30), default="government", nullable=False)
    owner_name: Mapped[str | None] = mapped_column(String(160))
    is_public_facing: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    storage_details: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, default=dict, nullable=False
    )
    ai_capabilities: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list, nullable=False)

    installation_date: Mapped[date | None] = mapped_column(Date)
    installed_by: Mapped[str | None] = mapped_column(String(160))
    installation_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, default=dict, nullable=False
    )
    source_system: Mapped[str | None] = mapped_column(String(100))
    external_id: Mapped[str | None] = mapped_column(String(160))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    department: Mapped[Department] = relationship(back_populates="cameras")


class AuditLog(Base):
    """Append-only record of registry mutations.

    No update/delete methods are exposed. The PostgreSQL migration additionally
    installs a trigger that rejects mutation of existing audit rows.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_resource", "resource_type", "resource_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(80), index=True)
    source: Mapped[str] = mapped_column(String(40), default="api", nullable=False)
    changes: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    response_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
