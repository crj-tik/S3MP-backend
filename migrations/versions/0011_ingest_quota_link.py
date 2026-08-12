"""Link ingestion records to durable quota reservations.

Revision ID: 0011_ingest_quota_link
Revises: 0010_ingest_mp_provenance
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0011_ingest_quota_link"
down_revision: str | None = "0010_ingest_mp_provenance"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("file_ingestion_record") as batch:
        batch.add_column(sa.Column("quota_reservation_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_ingestion_quota_reservation",
            "quota_reservation",
            ["quota_reservation_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_ingestion_tenant_quota_reservation",
        "file_ingestion_record",
        ["tenant_id", "quota_reservation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_tenant_quota_reservation", table_name="file_ingestion_record")
    with op.batch_alter_table("file_ingestion_record") as batch:
        batch.drop_constraint("fk_ingestion_quota_reservation", type_="foreignkey")
        batch.drop_column("quota_reservation_id")
