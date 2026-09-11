"""Add per-delete records for isolated trash retention.

Revision ID: 0058_file_deletion_records
Revises: 0057_knowledge_processing_lease
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0058_file_deletion_records"
down_revision: str | None = "0057_knowledge_processing_lease"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "file_deletion_record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("storage_space_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("original_relative_key", sa.String(length=1024), nullable=False),
        sa.Column("original_physical_key", sa.String(length=1024), nullable=False),
        sa.Column("trash_physical_key", sa.String(length=1024), nullable=False),
        sa.Column("content_length", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("etag", sa.String(length=512), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("purge_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="requested", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
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
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key"),
    )
    op.create_index(
        "ix_file_deletion_record_due", "file_deletion_record", ["purge_due_at", "status"]
    )
    op.create_index(
        "ix_file_deletion_record_original_key",
        "file_deletion_record",
        ["tenant_id", "storage_space_id", "original_relative_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_file_deletion_record_original_key", table_name="file_deletion_record")
    op.drop_index("ix_file_deletion_record_due", table_name="file_deletion_record")
    op.drop_table("file_deletion_record")
