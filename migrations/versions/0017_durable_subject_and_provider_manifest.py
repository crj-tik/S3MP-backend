"""Add durable subject evidence and provider migration manifests.

Revision ID: 0017_durable_subject_provider
Revises: 0016_provider_target_namespace
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0017_durable_subject_provider"
down_revision: str | None = "0016_provider_target_namespace"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    for table in ("upload_session", "multipart_session", "file_operation"):
        op.add_column(table, sa.Column("membership_id", sa.Uuid(), nullable=True))
        # Do not certify historical provider keys as namespaced.  New code
        # writes version 1 explicitly; pre-existing rows remain version 0.
        op.add_column(
            table,
            sa.Column("provider_target_version", sa.Integer(), nullable=False, server_default="0"),
        )
    op.add_column(
        "file_object",
        sa.Column("provider_target_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("file_ingestion_record", sa.Column("membership_id", sa.Uuid(), nullable=True))
    op.add_column(
        "file_ingestion_record",
        sa.Column("provider_target_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_file_operation_tenant_membership", "file_operation", ["tenant_id", "membership_id"]
    )
    op.create_index(
        "ix_ingestion_tenant_membership", "file_ingestion_record", ["tenant_id", "membership_id"]
    )
    op.create_table(
        "provider_migration_manifest",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("storage_space_id", sa.Uuid(), nullable=True),
        sa.Column("record_type", sa.String(64), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="pending_review"),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("target_fingerprint", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "record_type", "record_id"),
    )
    op.create_index(
        "ix_provider_migration_manifest_state",
        "provider_migration_manifest",
        ["state", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_provider_migration_manifest_state", table_name="provider_migration_manifest")
    op.drop_table("provider_migration_manifest")
    op.drop_index("ix_ingestion_tenant_membership", table_name="file_ingestion_record")
    op.drop_index("ix_file_operation_tenant_membership", table_name="file_operation")
    op.drop_column("file_ingestion_record", "provider_target_version")
    op.drop_column("file_ingestion_record", "membership_id")
    op.drop_column("file_object", "provider_target_version")
    for table in ("file_operation", "multipart_session", "upload_session"):
        op.drop_column(table, "provider_target_version")
        op.drop_column(table, "membership_id")
