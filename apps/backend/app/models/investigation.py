from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.registry import JSON_VARIANT, Camera, TimestampMixin, utcnow, uuid_str


class ANPREvent(Base):
    """One immutable plate observation produced by the shared analytics pipeline."""

    __tablename__ = "anpr_events"
    __table_args__ = (
        Index("ix_anpr_normalized_observed", "normalized_plate", "observed_at"),
        Index("ix_anpr_camera_observed", "camera_id", "observed_at"),
        UniqueConstraint("source_event_id", name="uq_anpr_source_event"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    plate_text: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_plate: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    plate_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str | None] = mapped_column(String(32))
    vehicle_attributes: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, default=dict, nullable=False
    )
    evidence_reference: Mapped[str | None] = mapped_column(String(500))
    model_version: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(60), default="anpr_pipeline", nullable=False)

    camera: Mapped[Camera] = relationship()


class CameraGraphEdge(TimestampMixin, Base):
    __tablename__ = "camera_graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_camera_id", "destination_camera_id", name="uq_camera_graph_direction"
        ),
        Index("ix_camera_graph_source_enabled", "source_camera_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False
    )
    destination_camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False
    )
    road_distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_travel_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    topology_source: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)


class InvestigationCase(TimestampMixin, Base):
    __tablename__ = "investigation_cases"
    __table_args__ = (
        Index("ix_investigation_status_updated", "status", "updated_at"),
        Index("ix_investigation_target_created", "target_plate", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    target_plate: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    target_plate_original: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="high", nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(40), default="created", nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_camera_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="SET NULL")
    )
    graph_method: Mapped[str] = mapped_column(String(80), default="awaiting_anchor", nullable=False)
    route_confidence: Mapped[str] = mapped_column(String(20), default="unavailable", nullable=False)
    last_recalculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    observations: Mapped[list[InvestigationObservation]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan"
    )
    candidates: Mapped[list[InvestigationCandidate]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan"
    )


class InvestigationObservation(Base):
    __tablename__ = "investigation_observations"
    __table_args__ = (
        UniqueConstraint("investigation_id", "event_id", name="uq_investigation_event"),
        Index("ix_investigation_observation_time", "investigation_id", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("anpr_events.id", ondelete="RESTRICT"), nullable=False
    )
    camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    plate_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    temporal_feasibility: Mapped[float] = mapped_column(Float, nullable=False)
    route_feasibility: Mapped[float] = mapped_column(Float, nullable=False)
    correlation_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reasoning: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list, nullable=False)

    investigation: Mapped[InvestigationCase] = relationship(back_populates="observations")
    event: Mapped[ANPREvent] = relationship()
    camera: Mapped[Camera] = relationship()


class InvestigationCandidate(Base):
    __tablename__ = "investigation_candidates"
    __table_args__ = (
        UniqueConstraint("investigation_id", "camera_id", name="uq_investigation_candidate"),
        Index("ix_investigation_candidate_rank", "investigation_id", "rank"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False
    )
    anchor_camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False
    )
    camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    eta_min_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    eta_max_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    graph_method: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    investigation: Mapped[InvestigationCase] = relationship(back_populates="candidates")
    camera: Mapped[Camera] = relationship(foreign_keys=[camera_id])


class InvestigationActivity(Base):
    __tablename__ = "investigation_activity"
    __table_args__ = (Index("ix_investigation_activity_time", "investigation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False
    )
    activity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
