"""Store application-provided JSON metadata on uploaded file records.

Revision ID: 0051_file_record_metadata
Revises: 0050_dashboard_observability
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051_file_record_metadata"
down_revision: str | None = "0050_dashboard_observability"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    for table in ("file_object", "upload_session", "multipart_session", "file_ingestion_record"):
        op.add_column(
            table, sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )


def downgrade() -> None:
    for table in ("file_ingestion_record", "multipart_session", "upload_session", "file_object"):
        op.drop_column(table, "metadata")
