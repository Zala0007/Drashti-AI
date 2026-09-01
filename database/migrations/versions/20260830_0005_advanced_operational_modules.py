"""Add Re-ID, case evidence, camera health and coverage intelligence records.

Revision ID: 20260830_0005
Revises: 20260829_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0005"
down_revision: str | None = "20260829_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "vehicle_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_observation_id", sa.String(160), nullable=False),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("anpr_event_id", sa.String(36), sa.ForeignKey("anpr_events.id", ondelete="SET NULL")),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("track_id", sa.String(120)),
        sa.Column("plate_text", sa.String(32)),
        sa.Column("normalized_plate", sa.String(20)),
        sa.Column("vehicle_class", sa.String(60)),
        sa.Column("colour", sa.String(60)),
        sa.Column("direction", sa.String(32)),
        sa.Column("bounding_box", sa.JSON(), nullable=False),
        sa.Column("image_width", sa.Integer()),
        sa.Column("image_height", sa.Integer()),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("quality_flags", sa.JSON(), nullable=False),
        sa.Column("crop_reference", sa.String(500)),
        sa.Column("embedding", sa.JSON()),
        sa.Column("embedding_provider", sa.String(120)),
        sa.Column("model_version", sa.String(180)),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_observation_id", name="uq_vehicle_source_observation"),
    )
    op.create_index("ix_vehicle_observation_camera_time", "vehicle_observations", ["camera_id", "observed_at"])
    op.create_index("ix_vehicle_observation_plate_time", "vehicle_observations", ["normalized_plate", "observed_at"])

    op.create_table(
        "reid_matches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("investigation_id", sa.String(36), sa.ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_observation_id", sa.String(36), sa.ForeignKey("vehicle_observations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("candidate_observation_id", sa.String(36), sa.ForeignKey("vehicle_observations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("visual_similarity", sa.Float()),
        sa.Column("plate_similarity", sa.Float()),
        sa.Column("colour_similarity", sa.Float()),
        sa.Column("class_similarity", sa.Float()),
        sa.Column("temporal_feasibility", sa.Float(), nullable=False),
        sa.Column("route_feasibility", sa.Float(), nullable=False),
        sa.Column("direction_consistency", sa.Float()),
        sa.Column("technical_score", sa.Float(), nullable=False),
        sa.Column("assessment", sa.String(20), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("reviewed_by", sa.String(160)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text()),
        *timestamps(),
        sa.UniqueConstraint("investigation_id", "target_observation_id", "candidate_observation_id", name="uq_reid_investigation_pair"),
    )
    op.create_index("ix_reid_investigation_rank", "reid_matches", ["investigation_id", "technical_score"])

    op.create_table(
        "case_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_number", sa.String(50), nullable=False, unique=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("case_type", sa.String(60), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("assigned_to", sa.String(160)),
        sa.Column("district", sa.String(100)),
        sa.Column("department", sa.String(160)),
        sa.Column("authorization_reference", sa.String(200), nullable=False),
        sa.Column("retention_class", sa.String(60), nullable=False),
        sa.Column("investigation_id", sa.String(36), sa.ForeignKey("investigation_cases.id", ondelete="SET NULL"), unique=True),
        *timestamps(),
    )
    op.create_index("ix_case_file_status_updated", "case_files", ["status", "updated_at"])
    op.create_index("ix_case_file_district_created", "case_files", ["district", "created_at"])

    op.create_table(
        "case_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("case_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(60), nullable=False),
        sa.Column("source_id", sa.String(160), nullable=False),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="SET NULL")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_type", sa.String(60), nullable=False),
        sa.Column("controlled_reference", sa.String(500)),
        sa.Column("sha256", sa.String(64)),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("model_version", sa.String(180)),
        sa.Column("confidence", sa.Float()),
        sa.Column("classification", sa.String(40), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "source_type", "source_id", name="uq_case_evidence_source"),
    )
    op.create_index("ix_case_evidence_case_time", "case_evidence", ["case_id", "occurred_at"])

    op.create_table(
        "case_activity",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("case_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey("case_evidence.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_case_activity_case_time", "case_activity", ["case_id", "created_at"])

    op.create_table(
        "camera_health_aggregates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_seconds", sa.Integer(), nullable=False),
        sa.Column("health_state", sa.String(20), nullable=False),
        sa.Column("availability", sa.Float(), nullable=False),
        sa.Column("decoded_fps", sa.Float()),
        sa.Column("processing_fps", sa.Float()),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("frame_age_ms", sa.Float()),
        sa.Column("reconnect_count", sa.Integer(), nullable=False),
        sa.Column("decoder_errors", sa.Integer(), nullable=False),
        sa.Column("freeze_events", sa.Integer(), nullable=False),
        sa.Column("authentication_failures", sa.Integer(), nullable=False),
        sa.Column("image_quality_state", sa.String(40)),
        sa.Column("edge_node_id", sa.String(120)),
        sa.Column("ai_worker_state", sa.String(30), nullable=False),
        sa.Column("source", sa.String(60), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("camera_id", "bucket_start", "bucket_seconds", name="uq_health_bucket"),
    )
    op.create_index("ix_health_camera_bucket", "camera_health_aggregates", ["camera_id", "bucket_start"])
    op.create_index("ix_health_state_bucket", "camera_health_aggregates", ["health_state", "bucket_start"])

    op.create_table(
        "maintenance_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_key", sa.String(100), nullable=False),
        sa.Column("risk", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("indicators", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("camera_id", "finding_key", name="uq_camera_maintenance_finding"),
    )
    op.create_index("ix_maintenance_risk_updated", "maintenance_findings", ["risk", "updated_at"])

    op.create_table(
        "health_incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("deduplication_key", sa.String(180), nullable=False, unique=True),
        sa.Column("incident_type", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("edge_node_id", sa.String(120)),
        sa.Column("affected_camera_ids", sa.JSON(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_health_incident_status_severity", "health_incidents", ["status", "severity"])

    op.create_table(
        "coverage_analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("district", sa.String(100)),
        sa.Column("analysis_type", sa.String(50), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("camera_count", sa.Integer(), nullable=False),
        sa.Column("operational_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "coverage_gaps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_run_id", sa.String(36), sa.ForeignKey("coverage_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gap_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("radius_m", sa.Float(), nullable=False),
        sa.Column("source_camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="SET NULL")),
        sa.Column("destination_camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="SET NULL")),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("confidence_basis", sa.String(80), nullable=False),
    )
    op.create_index("ix_coverage_gap_run_severity", "coverage_gaps", ["analysis_run_id", "severity"])

    op.create_table(
        "deployment_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_run_id", sa.String(36), sa.ForeignKey("coverage_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("area_label", sa.String(240), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("estimated_radius_m", sa.Float(), nullable=False),
        sa.Column("assumption", sa.String(160), nullable=False),
    )
    op.create_index("ix_deployment_candidate_run_priority", "deployment_candidates", ["analysis_run_id", "priority"])


def downgrade() -> None:
    op.drop_table("deployment_candidates")
    op.drop_table("coverage_gaps")
    op.drop_table("coverage_analysis_runs")
    op.drop_table("health_incidents")
    op.drop_table("maintenance_findings")
    op.drop_table("camera_health_aggregates")
    op.drop_table("case_activity")
    op.drop_table("case_evidence")
    op.drop_table("case_files")
    op.drop_table("reid_matches")
    op.drop_table("vehicle_observations")
