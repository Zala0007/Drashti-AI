"""Create encrypted P0.3 federation connection profiles.

Revision ID: 20260824_0002
Revises: 20260823_0001
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0002"
down_revision: str | None = "20260823_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type() -> sa.types.TypeEngine[object]:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "connection_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("adapter_kind", sa.String(length=40), nullable=False),
        sa.Column("stream_role", sa.String(length=30), nullable=False),
        sa.Column("endpoint_ciphertext", sa.Text(), nullable=False),
        sa.Column("endpoint_display", sa.String(length=300), nullable=False),
        sa.Column("endpoint_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("credential_reference_ciphertext", sa.Text(), nullable=True),
        sa.Column("encryption_key_id", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column(
            "verification_status",
            sa.String(length=40),
            nullable=False,
            server_default="unverified",
        ),
        sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_probe_latency_ms", sa.Float(), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "normalized_metadata", _json_type(), nullable=False, server_default="{}"
        ),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "camera_id", "name", "stream_role", name="uq_connection_camera_name_role"
        ),
    )
    op.create_index(
        "ix_connection_profiles_camera_id", "connection_profiles", ["camera_id"]
    )
    op.create_index(
        "ix_connection_profiles_endpoint_fingerprint",
        "connection_profiles",
        ["endpoint_fingerprint"],
    )
    op.create_index(
        "ix_connection_profiles_verification_status",
        "connection_profiles",
        ["verification_status"],
    )
    op.create_index(
        "ix_connection_profiles_last_probe_at", "connection_profiles", ["last_probe_at"]
    )
    op.create_index(
        "ix_connection_profiles_last_success_at",
        "connection_profiles",
        ["last_success_at"],
    )
    op.create_index(
        "ix_connection_camera_status",
        "connection_profiles",
        ["camera_id", "verification_status"],
    )
    op.create_index(
        "ix_connection_adapter_kind", "connection_profiles", ["adapter_kind"]
    )
    op.create_index(
        "ix_connection_enabled_priority", "connection_profiles", ["enabled", "priority"]
    )


def downgrade() -> None:
    op.drop_table("connection_profiles")
