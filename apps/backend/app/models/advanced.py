from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.registry import JSON_VARIANT, TimestampMixin, utcnow, uuid_str


class VehicleObservation(Base):
    __tablename__ = "vehicle_observations"
    __table_args__ = (
        UniqueConstraint("source_observation_id", name="uq_vehicle_source_observation"),
        Index("ix_vehicle_observation_camera_time", "camera_id", "observed_at"),
        Index("ix_vehicle_observation_plate_time", "normalized_plate", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_observation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    anpr_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("anpr_events.id", ondelete="SET NULL"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    track_id: Mapped[str | None] = mapped_column(String(120))
    plate_text: Mapped[str | None] = mapped_column(String(32))
    normalized_plate: Mapped[str | None] = mapped_column(String(20), index=True)
    vehicle_class: Mapped[str | None] = mapped_column(String(60), index=True)
    colour: Mapped[str | None] = mapped_column(String(60), index=True)
    direction: Mapped[str | None] = mapped_column(String(32))
    bounding_box: Mapped[list[float]] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    image_width: Mapped[int | None] = mapped_column(Integer)
    image_height: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    crop_reference: Mapped[str | None] = mapped_column(String(500))
    embedding: Mapped[list[float] | None] = mapped_column(JSON_VARIANT)
    embedding_provider: Mapped[str | None] = mapped_column(String(120))
    model_version: Mapped[str | None] = mapped_column(String(180))
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ReIDMatch(TimestampMixin, Base):
    __tablename__ = "reid_matches"
    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "target_observation_id",
            "candidate_observation_id",
            name="uq_reid_investigation_pair",
        ),
        Index("ix_reid_investigation_rank", "investigation_id", "technical_score"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False
    )
    target_observation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("vehicle_observations.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_observation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("vehicle_observations.id", ondelete="RESTRICT"), nullable=False
    )
    visual_similarity: Mapped[float | None] = mapped_column(Float)
    plate_similarity: Mapped[float | None] = mapped_column(Float)
    colour_similarity: Mapped[float | None] = mapped_column(Float)
    class_similarity: Mapped[float | None] = mapped_column(Float)
    temporal_feasibility: Mapped[float] = mapped_column(Float, nullable=False)
    route_feasibility: Mapped[float] = mapped_column(Float, nullable=False)
    direction_consistency: Mapped[float | None] = mapped_column(Float)
    technical_score: Mapped[float] = mapped_column(Float, nullable=False)
    assessment: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(160))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)


class CaseFile(TimestampMixin, Base):
    __tablename__ = "case_files"
    __table_args__ = (
        Index("ix_case_file_status_updated", "status", "updated_at"),
        Index("ix_case_file_district_created", "district", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    case_type: Mapped[str] = mapped_column(String(60), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(160), index=True)
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    department: Mapped[str | None] = mapped_column(String(160))
    authorization_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(60), nullable=False)
    investigation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("investigation_cases.id", ondelete="SET NULL"), unique=True
    )


class CaseEvidence(Base):
    __tablename__ = "case_evidence"
    __table_args__ = (
        Index("ix_case_evidence_case_time", "case_id", "occurred_at"),
        UniqueConstraint("case_id", "source_type", "source_id", name="uq_case_evidence_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("case_files.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    camera_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="SET NULL"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(60), nullable=False)
    controlled_reference: Mapped[str | None] = mapped_column(String(500))
    sha256: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(180))
    confidence: Mapped[float | None] = mapped_column(Float)
    classification: Mapped[str] = mapped_column(String(40), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CaseActivity(Base):
    __tablename__ = "case_activity"
    __table_args__ = (Index("ix_case_activity_case_time", "case_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("case_files.id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("case_evidence.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CameraHealthAggregate(Base):
    __tablename__ = "camera_health_aggregates"
    __table_args__ = (
        UniqueConstraint("camera_id", "bucket_start", "bucket_seconds", name="uq_health_bucket"),
        Index("ix_health_camera_bucket", "camera_id", "bucket_start"),
        Index("ix_health_state_bucket", "health_state", "bucket_start"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False
    )
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    health_state: Mapped[str] = mapped_column(String(20), nullable=False)
    availability: Mapped[float] = mapped_column(Float, nullable=False)
    decoded_fps: Mapped[float | None] = mapped_column(Float)
    processing_fps: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    frame_age_ms: Mapped[float | None] = mapped_column(Float)
    reconnect_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    decoder_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    freeze_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    authentication_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    image_quality_state: Mapped[str] = mapped_column(String(40), default="not_measured")
    edge_node_id: Mapped[str | None] = mapped_column(String(120), index=True)
    ai_worker_state: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class MaintenanceFinding(TimestampMixin, Base):
    __tablename__ = "maintenance_findings"
    __table_args__ = (
        Index("ix_maintenance_risk_updated", "risk", "updated_at"),
        UniqueConstraint("camera_id", "finding_key", name="uq_camera_maintenance_finding"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    camera_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False
    )
    finding_key: Mapped[str] = mapped_column(String(100), nullable=False)
    risk: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    indicators: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HealthIncident(TimestampMixin, Base):
    __tablename__ = "health_incidents"
    __table_args__ = (
        UniqueConstraint("deduplication_key", name="uq_health_incident_deduplication"),
        Index("ix_health_incident_status_severity", "status", "severity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    deduplication_key: Mapped[str] = mapped_column(String(180), nullable=False)
    incident_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    edge_node_id: Mapped[str | None] = mapped_column(String(120), index=True)
    affected_camera_ids: Mapped[list[str]] = mapped_column(
        JSON_VARIANT, default=list, nullable=False
    )
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoverageAnalysisRun(Base):
    __tablename__ = "coverage_analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    camera_count: Mapped[int] = mapped_column(Integer, nullable=False)
    operational_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CoverageGap(Base):
    __tablename__ = "coverage_gaps"
    __table_args__ = (Index("ix_coverage_gap_run_severity", "analysis_run_id", "severity"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    analysis_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("coverage_analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    gap_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_m: Mapped[float] = mapped_column(Float, nullable=False)
    source_camera_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="SET NULL")
    )
    destination_camera_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cameras.id", ondelete="SET NULL")
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_basis: Mapped[str] = mapped_column(String(80), nullable=False)


class DeploymentCandidate(Base):
    __tablename__ = "deployment_candidates"
    __table_args__ = (Index("ix_deployment_candidate_run_priority", "analysis_run_id", "priority"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    analysis_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("coverage_analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    area_label: Mapped[str] = mapped_column(String(240), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    estimated_radius_m: Mapped[float] = mapped_column(Float, nullable=False)
    assumption: Mapped[str] = mapped_column(String(160), nullable=False)
