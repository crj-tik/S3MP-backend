"""Add application-record concurrency state for file metadata updates.

Revision ID: 0052_file_record_version
Revises: 0051_file_record_metadata
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0052_file_record_version"
down_revision: str | None = "0051_file_record_metadata"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "file_object",
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "file_object", sa.Column("metadata_update_idempotency_key", sa.String(length=128))
    )
    op.add_column("file_object", sa.Column("metadata_update_fingerprint", sa.String(length=64)))


def downgrade() -> None:
    op.drop_column("file_object", "metadata_update_fingerprint")
    op.drop_column("file_object", "metadata_update_idempotency_key")
    op.drop_column("file_object", "record_version")
