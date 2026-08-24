"""Persist application audit actors separately from target application storage."""

import sqlalchemy as sa
from alembic import op

revision: str = "0044_file_actor_application_attribution"
down_revision: str | None = "0043_application_code"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("file_object", sa.Column("deletion_actor_application_id", sa.Uuid(), nullable=True))
    for table in ("upload_session", "multipart_session", "file_operation", "file_ingestion_record"):
        op.add_column(table, sa.Column("actor_application_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    for table in ("file_ingestion_record", "file_operation", "multipart_session", "upload_session"):
        op.drop_column(table, "actor_application_id")
    op.drop_column("file_object", "deletion_actor_application_id")
