"""Retain multipart ingestion provenance when a session is removed.

Revision ID: 0010_ingest_mp_provenance
Revises: 0009_ingestion_integrity
"""

from alembic import op

revision: str = "0010_ingest_mp_provenance"
down_revision: str | None = "0009_ingestion_integrity"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("file_ingestion_record") as batch:
        batch.create_foreign_key(
            "fk_ingestion_multipart_session",
            "multipart_session",
            ["multipart_session_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("file_ingestion_record") as batch:
        batch.drop_constraint("fk_ingestion_multipart_session", type_="foreignkey")
