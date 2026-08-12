"""Add recoverable file-deletion state.

Revision ID: 0012_file_delete_outbox
Revises: 0011_ingest_quota_link
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0012_file_delete_outbox"
down_revision: str | None = "0011_ingest_quota_link"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "file_object",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="available"),
    )
    op.create_index("ix_file_object_tenant_status", "file_object", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_file_object_tenant_status", table_name="file_object")
    op.drop_column("file_object", "status")
