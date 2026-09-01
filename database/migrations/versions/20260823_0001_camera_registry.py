"""Create the P0.1 camera registry, audit log and PostGIS index.

Revision ID: 20260823_0001
Revises:
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type() -> sa.types.TypeEngine[object]:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"
    if is_postgresql:
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "departments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_departments_name"),
    )
    op.create_index("ix_departments_code", "departments", ["code"], unique=True)
    op.create_index("ix_departments_is_active", "departments", ["is_active"])

    op.create_table(
        "cameras",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("camera_code", sa.String(length=64), nullable=False),
        sa.Column("camera_name", sa.String(length=200), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=False),
        sa.Column("district", sa.String(length=100), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("location_description", sa.String(length=500), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("coverage_radius_m", sa.Float(), nullable=True),
        sa.Column("bearing_degrees", sa.Float(), nullable=True),
        sa.Column("field_of_view_degrees", sa.Float(), nullable=True),
        sa.Column(
            "camera_type", sa.String(length=30), nullable=False, server_default="other"
        ),
        sa.Column("vendor", sa.String(length=120), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("vms", sa.String(length=160), nullable=True),
        sa.Column(
            "connectivity_type",
            sa.String(length=30),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "stream_protocol",
            sa.String(length=30),
            nullable=False,
            server_default="none",
        ),
        sa.Column("stream_reference", sa.String(length=500), nullable=True),
        sa.Column("credential_reference", sa.String(length=500), nullable=True),
        sa.Column(
            "rtsp_capable", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "onvif_capable", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="planned"
        ),
        sa.Column(
            "health", sa.String(length=30), nullable=False, server_default="unknown"
        ),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_details", _json_type(), nullable=False, server_default="{}"),
        sa.Column(
            "ownership",
            sa.String(length=30),
            nullable=False,
            server_default="government",
        ),
        sa.Column("owner_name", sa.String(length=160), nullable=True),
        sa.Column(
            "is_public_facing", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("storage_details", _json_type(), nullable=False, server_default="{}"),
        sa.Column("ai_capabilities", _json_type(), nullable=False, server_default="[]"),
        sa.Column(
            "ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("tags", _json_type(), nullable=False, server_default="[]"),
        sa.Column("installation_date", sa.Date(), nullable=True),
        sa.Column("installed_by", sa.String(length=160), nullable=True),
        sa.Column(
            "installation_metadata", _json_type(), nullable=False, server_default="{}"
        ),
        sa.Column("source_system", sa.String(length=100), nullable=True),
        sa.Column("external_id", sa.String(length=160), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_system", "external_id", name="uq_camera_source_external"
        ),
    )
    op.create_index("ix_cameras_camera_code", "cameras", ["camera_code"], unique=True)
    op.create_index("ix_cameras_camera_name", "cameras", ["camera_name"])
    op.create_index("ix_cameras_department_id", "cameras", ["department_id"])
    op.create_index("ix_cameras_district", "cameras", ["district"])
    op.create_index("ix_cameras_city", "cameras", ["city"])
    op.create_index("ix_cameras_vendor", "cameras", ["vendor"])
    op.create_index("ix_cameras_vms", "cameras", ["vms"])
    op.create_index("ix_cameras_status", "cameras", ["status"])
    op.create_index("ix_cameras_health", "cameras", ["health"])
    op.create_index("ix_cameras_ai_enabled", "cameras", ["ai_enabled"])
    op.create_index("ix_cameras_last_heartbeat", "cameras", ["last_heartbeat"])
    op.create_index("ix_cameras_retired_at", "cameras", ["retired_at"])
    op.create_index(
        "ix_cameras_department_status", "cameras", ["department_id", "status"]
    )
    op.create_index("ix_cameras_district_health", "cameras", ["district", "health"])
    op.create_index(
        "ix_cameras_latitude_longitude", "cameras", ["latitude", "longitude"]
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("actor_id", sa.String(length=160), nullable=False),
        sa.Column("request_id", sa.String(length=80), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="api"),
        sa.Column("changes", _json_type(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index(
        "ix_audit_resource",
        "audit_logs",
        ["resource_type", "resource_id", "created_at"],
    )

    op.create_table(
        "import_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "response_payload", _json_type(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_jobs_idempotency_key",
        "import_jobs",
        ["idempotency_key"],
        unique=True,
    )

    if is_postgresql:
        op.execute(
            "ALTER TABLE cameras ADD COLUMN location_geog geography(Point,4326) "
            "GENERATED ALWAYS AS "
            "(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED"
        )
        op.execute(
            "CREATE INDEX ix_cameras_location_geog ON cameras USING GIST (location_geog)"
        )
        op.execute(
            "CREATE FUNCTION reject_audit_log_mutation() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'audit_logs are append-only'; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER trg_audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs "
            "FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation()"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS reject_audit_log_mutation()")
    op.drop_table("import_jobs")
    op.drop_table("audit_logs")
    op.drop_table("cameras")
    op.drop_table("departments")
