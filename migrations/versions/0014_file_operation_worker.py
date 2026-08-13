"""Add durable worker state to file operations.

Revision ID: 0014_file_operation_worker
Revises: 0013_application_principals
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0014_file_operation_worker"
down_revision: str | None = "0013_application_principals"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("file_operation", sa.Column("storage_space_id", sa.Uuid(), nullable=True))
    op.add_column(
        "file_operation",
        sa.Column("authorization_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "file_operation",
        sa.Column(
            "authorization_evidence",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "file_operation",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("file_operation", sa.Column("lease_owner", sa.String(128), nullable=True))
    op.add_column(
        "file_operation", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "file_operation", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "file_operation", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_file_operation_ready", "file_operation", ["status", "next_retry_at"])


def downgrade() -> None:
    op.drop_index("ix_file_operation_ready", table_name="file_operation")
    for name in (
        "completed_at",
        "next_retry_at",
        "lease_expires_at",
        "lease_owner",
        "attempt_count",
        "authorization_evidence",
        "authorization_version",
        "storage_space_id",
    ):
        op.drop_column("file_operation", name)
