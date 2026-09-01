"""Add the Special Investigation Engine event, case, graph and correlation records.

Revision ID: 20260829_0004
Revises: 20260827_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0004"
down_revision: str | None = "20260827_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "anpr_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_event_id", sa.String(160), nullable=False, unique=True),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plate_text", sa.String(32), nullable=False),
        sa.Column("normalized_plate", sa.String(20), nullable=False),
        sa.Column("plate_confidence", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(32)),
        sa.Column("vehicle_attributes", sa.JSON(), nullable=False),
        sa.Column("evidence_reference", sa.String(500)),
        sa.Column("model_version", sa.String(120)),
        sa.Column("source", sa.String(60), nullable=False),
    )
    op.create_index("ix_anpr_normalized_observed", "anpr_events", ["normalized_plate", "observed_at"])
    op.create_index("ix_anpr_camera_observed", "anpr_events", ["camera_id", "observed_at"])

    op.create_table(
        "camera_graph_edges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("destination_camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("road_distance_m", sa.Float(), nullable=False),
        sa.Column("estimated_travel_seconds", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(32)),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("topology_source", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_camera_id", "destination_camera_id", name="uq_camera_graph_direction"),
    )
    op.create_index("ix_camera_graph_source_enabled", "camera_graph_edges", ["source_camera_id", "enabled"])

    op.create_table(
        "investigation_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_number", sa.String(40), nullable=False, unique=True),
        sa.Column("target_plate", sa.String(20), nullable=False),
        sa.Column("target_plate_original", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("district", sa.String(100)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("latest_camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="SET NULL")),
        sa.Column("graph_method", sa.String(80), nullable=False),
        sa.Column("route_confidence", sa.String(20), nullable=False),
        sa.Column("last_recalculated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_investigation_status_updated", "investigation_cases", ["status", "updated_at"])
    op.create_index("ix_investigation_target_created", "investigation_cases", ["target_plate", "created_at"])

    op.create_table(
        "investigation_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("investigation_id", sa.String(36), sa.ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("anpr_events.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plate_similarity", sa.Float(), nullable=False),
        sa.Column("temporal_feasibility", sa.Float(), nullable=False),
        sa.Column("route_feasibility", sa.Float(), nullable=False),
        sa.Column("correlation_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reasoning", sa.JSON(), nullable=False),
        sa.UniqueConstraint("investigation_id", "event_id", name="uq_investigation_event"),
    )
    op.create_index("ix_investigation_observation_time", "investigation_observations", ["investigation_id", "observed_at"])

    op.create_table(
        "investigation_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("investigation_id", sa.String(36), sa.ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("anchor_camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.String(20), nullable=False),
        sa.Column("eta_min_seconds", sa.Integer(), nullable=False),
        sa.Column("eta_max_seconds", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("graph_method", sa.String(80), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("investigation_id", "camera_id", name="uq_investigation_candidate"),
    )
    op.create_index("ix_investigation_candidate_rank", "investigation_candidates", ["investigation_id", "rank"])

    op.create_table(
        "investigation_activity",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("investigation_id", sa.String(36), sa.ForeignKey("investigation_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_type", sa.String(60), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_investigation_activity_time", "investigation_activity", ["investigation_id", "created_at"])


def downgrade() -> None:
    op.drop_table("investigation_activity")
    op.drop_table("investigation_candidates")
    op.drop_table("investigation_observations")
    op.drop_table("investigation_cases")
    op.drop_table("camera_graph_edges")
    op.drop_table("anpr_events")
