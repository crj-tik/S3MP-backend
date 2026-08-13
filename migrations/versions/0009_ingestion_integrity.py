"""Repair ingestion retention foreign keys and add reconciliation indexes.

Revision ID: 0009_ingestion_integrity
Revises: 0008_file_ingestion_provenance
"""

from alembic import op

revision: str = "0009_ingestion_integrity"
down_revision: str | None = "0008_file_ingestion_provenance"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("file_ingestion_record") as batch:
        batch.drop_constraint(
            "fk_file_ingestion_record_tenant_id_upload_session", type_="foreignkey"
        )
        batch.drop_constraint("fk_file_ingestion_record_tenant_id_file_object", type_="foreignkey")
        batch.create_foreign_key(
            "fk_ingestion_upload_session",
            "upload_session",
            ["upload_session_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_ingestion_file_object",
            "file_object",
            ["file_object_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_ingestion_tenant_multipart_session",
        "file_ingestion_record",
        ["tenant_id", "multipart_session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_tenant_multipart_session", table_name="file_ingestion_record")
    with op.batch_alter_table("file_ingestion_record") as batch:
        batch.drop_constraint("fk_ingestion_file_object", type_="foreignkey")
        batch.drop_constraint("fk_ingestion_upload_session", type_="foreignkey")
        batch.create_foreign_key(
            "fk_file_ingestion_record_tenant_id_file_object",
            "file_object",
            ["tenant_id", "file_object_id"],
            ["tenant_id", "id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_file_ingestion_record_tenant_id_upload_session",
            "upload_session",
            ["tenant_id", "upload_session_id"],
            ["tenant_id", "id"],
            ondelete="SET NULL",
        )
