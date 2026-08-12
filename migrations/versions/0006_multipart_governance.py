"""Add multipart, object-operation, quota and audit tables.

Revision ID: 0006_multipart_governance
Revises: 0005_storage_files
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0006_multipart_governance"
down_revision: str | None = "0005_storage_files"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "quota",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("storage_space_id", sa.Uuid()),
        sa.Column("limit_bytes", sa.Integer(), nullable=False),
        sa.Column("used_bytes", sa.Integer(), nullable=False),
        sa.Column("reserved_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "storage_space_id"],
            ["storage_space.tenant_id", "storage_space.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "storage_space_id", name="uq_quota_tenant_id_storage_space_id"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_quota_tenant_id_id"),
    )
    op.create_table(
        "quota_reservation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("quota_id", sa.Uuid(), nullable=False),
        sa.Column("requested_bytes", sa.Integer(), nullable=False),
        sa.Column("actual_bytes", sa.Integer()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "quota_id"], ["quota.tenant_id", "quota.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_quota_reservation_tenant_status", "quota_reservation", ["tenant_id", "status"]
    )
    op.create_table(
        "multipart_session",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("storage_space_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("provider_upload_id", sa.String(512)),
        sa.Column("declared_length", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("quota_reservation_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principal.tenant_id", "principal.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "storage_space_id"], ["storage_space.tenant_id", "storage_space.id"]
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_multipart_session_tenant_id_id"),
    )
    op.create_index(
        "ix_multipart_session_tenant_status_expires",
        "multipart_session",
        ["tenant_id", "status", "expires_at"],
    )
    op.create_table(
        "multipart_part",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("multipart_session_id", sa.Uuid(), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(512), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "multipart_session_id"],
            ["multipart_session.tenant_id", "multipart_session.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "multipart_session_id",
            "part_number",
            name="uq_multipart_part_tenant_session_number",
        ),
    )
    op.create_table(
        "file_operation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(32), nullable=False),
        sa.Column("source_key", sa.String(1024)),
        sa.Column("destination_key", sa.String(1024)),
        sa.Column("keys", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("failure_reason", sa.String(500)),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principal.tenant_id", "principal.id"]
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_file_operation_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_file_operation_tenant_idempotency_key"
        ),
    )
    op.create_index("ix_file_operation_tenant_status", "file_operation", ["tenant_id", "status"])
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_principal_id", sa.Uuid()),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(128), nullable=False),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_audit_event_tenant_occurred", "audit_event", ["tenant_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_event_tenant_occurred", table_name="audit_event")
    op.drop_table("audit_event")
    op.drop_index("ix_file_operation_tenant_status", table_name="file_operation")
    op.drop_table("file_operation")
    op.drop_table("multipart_part")
    op.drop_index("ix_multipart_session_tenant_status_expires", table_name="multipart_session")
    op.drop_table("multipart_session")
    op.drop_index("ix_quota_reservation_tenant_status", table_name="quota_reservation")
    op.drop_table("quota_reservation")
    op.drop_table("quota")
