"""Add file_ingestion_record and file_ingestion_event tables.

Revision ID: 0008_file_ingestion_provenance
Revises: 0007_access_review
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0008_file_ingestion_provenance"
down_revision: str | None = "0007_access_review"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "file_ingestion_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("upload_session_id", sa.Uuid(), nullable=True),
        sa.Column("multipart_session_id", sa.Uuid(), nullable=True),
        sa.Column("file_object_id", sa.Uuid(), nullable=True),
        sa.Column("creator_principal_id", sa.Uuid(), nullable=False),
        sa.Column("acting_principal_id", sa.Uuid(), nullable=False),
        sa.Column("storage_space_id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.String(255), nullable=False),
        sa.Column("relative_key", sa.String(1024), nullable=False),
        sa.Column("physical_key", sa.String(1024), nullable=False),
        sa.Column("provider_etag", sa.String(512), nullable=True),
        sa.Column("provider_version_id", sa.String(512), nullable=True),
        sa.Column("actual_size", sa.Integer(), nullable=True),
        sa.Column("actual_content_type", sa.String(255), nullable=True),
        sa.Column("checksum", sa.String(512), nullable=True),
        sa.Column("authorization_evidence", sa.JSON(), nullable=False),
        sa.Column("authorization_version", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("idempotency_fingerprint", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="initiated"),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "upload_session_id"],
            ["upload_session.tenant_id", "upload_session.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "file_object_id"],
            ["file_object.tenant_id", "file_object.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "idempotency_fingerprint"),
    )
    op.create_index("ix_ingestion_tenant_status", "file_ingestion_record", ["tenant_id", "status"])
    op.create_index(
        "ix_ingestion_tenant_session", "file_ingestion_record", ["tenant_id", "upload_session_id"]
    )

    op.create_table(
        "file_ingestion_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ingestion_record_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ingestion_record_id"],
            ["file_ingestion_record.tenant_id", "file_ingestion_record.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_ingestion_event_record", "file_ingestion_event", ["ingestion_record_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_event_record", table_name="file_ingestion_event")
    op.drop_table("file_ingestion_event")
    op.drop_index("ix_ingestion_tenant_session", table_name="file_ingestion_record")
    op.drop_index("ix_ingestion_tenant_status", table_name="file_ingestion_record")
    op.drop_table("file_ingestion_record")
