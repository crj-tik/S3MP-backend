"""Persist application namespace evidence on file workflow records."""

import sqlalchemy as sa
from alembic import op

revision: str = "0027_file_storage_provenance"
down_revision: str | None = "0026_application_quota_scope"
branch_labels: str | None = None
depends_on: str | None = None

_TABLES = (
    "file_object",
    "upload_session",
    "multipart_session",
    "file_operation",
    "file_ingestion_record",
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("application_id", sa.Uuid(), nullable=True))
        op.add_column(table, sa.Column("storage_namespace", sa.String(length=512), nullable=True))
        op.add_column(
            table,
            sa.Column("profile_version", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_column(table, "profile_version")
        op.drop_column(table, "storage_namespace")
        op.drop_column(table, "application_id")
