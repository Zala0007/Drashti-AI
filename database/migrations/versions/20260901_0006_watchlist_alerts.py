"""Add operational watchlist entries and live ANPR alerts.

Revision ID: 20260901_0006
Revises: 20260830_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0006"
down_revision: str | None = "20260830_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plate_text", sa.String(32), nullable=False),
        sa.Column("normalized_plate", sa.String(20), nullable=False, unique=True),
        sa.Column("subject_label", sa.String(160), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_watchlist_entries_status", "watchlist_entries", ["status"])
    op.create_index(
        "ix_watchlist_status_plate", "watchlist_entries", ["status", "normalized_plate"]
    )
    op.create_table(
        "watchlist_alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "watchlist_entry_id",
            sa.String(36),
            sa.ForeignKey("watchlist_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "anpr_event_id",
            sa.String(36),
            sa.ForeignKey("anpr_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "camera_id",
            sa.String(36),
            sa.ForeignKey("cameras.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("matched_plate", sa.String(20), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_by", sa.String(160)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("watchlist_entry_id", "anpr_event_id", name="uq_watchlist_event"),
    )
    op.create_index(
        "ix_watchlist_alert_status_time", "watchlist_alerts", ["status", "observed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_alert_status_time", table_name="watchlist_alerts")
    op.drop_table("watchlist_alerts")
    op.drop_index("ix_watchlist_status_plate", table_name="watchlist_entries")
    op.drop_index("ix_watchlist_entries_status", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
