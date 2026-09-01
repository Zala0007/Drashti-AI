from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.registry import JSON_VARIANT, Camera, Department, TimestampMixin, uuid_str


class CredentialProfile(TimestampMixin, Base):
    """Department-scoped encrypted username/password material.

    This is the deployable local secret-store boundary used for device qualification.
    Production can replace its resolver with Vault/KMS without changing connection
    profiles. Plaintext fields never participate in ORM serialization or API reads.
    """

    __tablename__ = "credential_profiles"
    __table_args__ = (
        UniqueConstraint("department_id", "name", name="uq_credential_department_name"),
        Index("ix_credential_department_enabled", "department_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    department_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(40), default="username_password", nullable=False)
    username_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_id: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    department: Mapped[Department] = relationship()


class ConnectionProfile(TimestampMixin, Base):
    """Encrypted stream/VMS handoff owned by a registry camera.

    Endpoint material and opaque credential references are deliberately absent
    from every response schema. ``endpoint_display`` is generated before the
    entity is persisted and contains no path, query string or user information.
    """

    __tablename__ = "connection_profiles"
    __table_args__ = (
        UniqueConstraint("camera_id", "name", "stream_role", name="uq_connection_camera_name_role"),
        Index("ix_connection_camera_status", "camera_id", "verification_status"),
        Index("ix_connection_adapter_kind", "adapter_kind"),
        Index("ix_connection_enabled_priority", "enabled", "priority"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    adapter_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    stream_role: Mapped[str] = mapped_column(String(30), nullable=False)

    endpoint_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_display: Mapped[str] = mapped_column(String(300), nullable=False)
    endpoint_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    credential_reference_ciphertext: Mapped[str | None] = mapped_column(Text)
    encryption_key_id: Mapped[str] = mapped_column(String(120), nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(40), default="unverified", nullable=False, index=True
    )
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_probe_latency_ms: Mapped[float | None] = mapped_column(Float)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(500))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    normalized_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, default=dict, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)

    camera: Mapped[Camera] = relationship()
