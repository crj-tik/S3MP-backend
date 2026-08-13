"""Add isolated platform-control-plane authority and account session storage.

Revision ID: 0019_platform_control_plane
Revises: 0018_provider_manifest_locations
"""

from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0019_platform_control_plane"
down_revision: str | None = "0018_provider_manifest_locations"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )
    op.create_table(
        "platform_role",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("built_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    platform_role = sa.table(
        "platform_role",
        sa.column("id", sa.Uuid),
        sa.column("name", sa.String),
        sa.column("permissions", sa.JSON),
        sa.column("built_in", sa.Boolean),
    )
    op.bulk_insert(
        platform_role,
        [
            {
                "id": UUID("94084979-5f08-5e50-b1d9-8d97486b9575"),
                "name": "platform_admin",
                "permissions": [
                    "platform.tenants.manage",
                    "platform.roles.manage",
                    "platform.support.manage",
                    "platform.audit.read",
                ],
                "built_in": True,
            },
            {
                "id": UUID("c6bc0a1d-c25a-5388-9af3-3a35e8f6645f"),
                "name": "platform_operator",
                "permissions": ["platform.tenants.read", "platform.support.manage"],
                "built_in": True,
            },
            {
                "id": UUID("5fcf88e5-bc04-55a3-a5d3-6cae4a3d8e10"),
                "name": "platform_auditor",
                "permissions": ["platform.audit.read", "platform.tenants.read"],
                "built_in": True,
            },
        ],
    )
    op.create_table(
        "platform_role_binding",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            sa.Uuid(),
            sa.ForeignKey("platform_role.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_platform_role_binding_user_expiry", "platform_role_binding", ["user_id", "expires_at"]
    )
    op.create_table(
        "platform_bootstrap_state",
        sa.Column("singleton", sa.Boolean(), primary_key=True, nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("singleton", name="platform_bootstrap_singleton"),
    )
    op.create_table(
        "platform_audit_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "actor_user_id", sa.Uuid(), sa.ForeignKey("user_account.id", ondelete="SET NULL")
        ),
        sa.Column("action", sa.String(160), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(120)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_platform_audit_event_actor_created",
        "platform_audit_event",
        ["actor_user_id", "created_at"],
    )
    op.create_table(
        "account_session",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_digest", sa.LargeBinary(64), nullable=False, unique=True),
        sa.Column("csrf_digest", sa.LargeBinary(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_account_session_user_expires", "account_session", ["user_id", "expires_at"])
    op.create_index("ix_account_session_expires", "account_session", ["expires_at"])
    op.create_table(
        "support_access_request",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "requester_user_id",
            sa.Uuid(),
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_support_access_request_tenant_expiry",
        "support_access_request",
        ["tenant_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("support_access_request")
    op.drop_table("account_session")
    op.drop_table("platform_audit_event")
    op.drop_table("platform_bootstrap_state")
    op.drop_table("platform_role_binding")
    op.drop_table("platform_role")
    op.drop_column("tenant", "status")
