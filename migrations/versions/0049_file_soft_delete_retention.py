"""Add recoverable file deletion retention state and Redis schedule outbox.

Revision ID: 0049_file_soft_delete_retention
Revises: 0048_third_party_file_rename
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0049_file_soft_delete_retention"
down_revision: str | None = "0048_third_party_file_rename"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "file_object",
        sa.Column("soft_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "file_object", sa.Column("deletion_idempotency_key", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "file_object", sa.Column("purge_due_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("file_object", sa.Column("purge_state", sa.String(length=32), nullable=True))
    op.add_column(
        "file_object",
        sa.Column("purge_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "file_object", sa.Column("purge_next_retry_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "file_object", sa.Column("purge_failure_reason", sa.String(length=128), nullable=True)
    )
    op.add_column("file_object", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "file_object", sa.Column("restore_idempotency_key", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "file_object", sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_file_object_retention_due",
        "file_object",
        ["purge_due_at"],
        postgresql_where=sa.text("soft_deleted AND purge_due_at IS NOT NULL"),
    )
    op.drop_index("uq_file_object_active_key", table_name="file_object")
    op.create_index(
        "uq_file_object_active_key",
        "file_object",
        ["tenant_id", "storage_space_id", "object_key"],
        unique=True,
        postgresql_where=sa.text(
            "soft_deleted OR status IN "
            "('available', 'renaming', 'rename_failed', 'deleting', 'delete_failed')"
        ),
    )
    op.create_table(
        "file_retention_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["file_object.tenant_id", "file_object.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "file_id"),
    )
    op.create_index(
        "ix_file_retention_outbox_pending",
        "file_retention_outbox",
        ["processed_at", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_file_retention_outbox_pending", table_name="file_retention_outbox")
    op.drop_table("file_retention_outbox")
    op.drop_index("uq_file_object_active_key", table_name="file_object")
    op.create_index(
        "uq_file_object_active_key",
        "file_object",
        ["tenant_id", "storage_space_id", "object_key"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('available', 'renaming', 'rename_failed', 'deleting', 'delete_failed')"
        ),
    )
    op.drop_index("ix_file_object_retention_due", table_name="file_object")
    for column in (
        "purged_at",
        "restored_at",
        "restore_idempotency_key",
        "purge_failure_reason",
        "purge_next_retry_at",
        "purge_attempt_count",
        "purge_state",
        "purge_due_at",
        "soft_deleted",
        "deletion_idempotency_key",
    ):
        op.drop_column("file_object", column)
