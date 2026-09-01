"""Create encrypted department-scoped device credential profiles.

Revision ID: 20260827_0003
Revises: 20260824_0002
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0003"
down_revision: str | None = "20260824_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credential_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "auth_type",
            sa.String(length=40),
            nullable=False,
            server_default="username_password",
        ),
        sa.Column("username_ciphertext", sa.Text(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("encryption_key_id", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("department_id", "name", name="uq_credential_department_name"),
    )
    op.create_index(
        "ix_credential_profiles_department_id",
        "credential_profiles",
        ["department_id"],
    )
    op.create_index(
        "ix_credential_profiles_last_used_at",
        "credential_profiles",
        ["last_used_at"],
    )
    op.create_index(
        "ix_credential_department_enabled",
        "credential_profiles",
        ["department_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_table("credential_profiles")
