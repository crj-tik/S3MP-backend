"""Add quota reconciliation metadata and idempotent deletion ledger support."""

import sqlalchemy as sa
from alembic import op

revision: str = "0032_quota_reconciliation_ledger"
down_revision: str | None = "0031_multipart_part_content_hash"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("file_object", sa.Column("deleted_at", sa.DateTime(timezone=True)))

    for table, columns in {
        "file_object": ("content_length",),
        "upload_session": ("declared_length",),
        "multipart_session": ("declared_length",),
        "multipart_part": ("content_length",),
        "file_ingestion_record": ("actual_size",),
        "quota": ("limit_bytes", "used_bytes", "reserved_bytes"),
        "quota_reservation": ("requested_bytes", "actual_bytes"),
    }.items():
        for column in columns:
            op.alter_column(table, column, type_=sa.BigInteger())

    op.add_column(
        "quota",
        sa.Column(
            "consistency_status",
            sa.String(length=32),
            nullable=False,
            server_default="realtime",
        ),
    )
    op.add_column("quota", sa.Column("measured_at", sa.DateTime(timezone=True)))
    op.add_column("quota", sa.Column("last_reconciliation_run_id", sa.Uuid()))
    op.add_column(
        "quota",
        sa.Column("drift_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    op.create_table(
        "quota_reconciliation_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("storage_space_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="audit"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Index("ix_quota_reconciliation_run_tenant_created", "tenant_id", "created_at"),
    )
    op.create_table(
        "quota_reconciliation_difference",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("storage_space_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("physical_key_fingerprint", sa.String(length=64)),
        sa.Column("recorded_bytes", sa.BigInteger()),
        sa.Column("observed_bytes", sa.BigInteger()),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Index("ix_quota_reconciliation_difference_run_kind", "run_id", "kind"),
    )
    op.create_table(
        "quota_adjustment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("quota_id", sa.Uuid(), nullable=False),
        sa.Column("file_object_id", sa.Uuid(), nullable=True),
        sa.Column("reconciliation_run_id", sa.Uuid(), nullable=True),
        sa.Column("delta_bytes", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Index("ix_quota_adjustment_tenant_created", "tenant_id", "created_at"),
        sa.Index("ix_quota_adjustment_idempotency", "idempotency_key", unique=True),
    )


def downgrade() -> None:
    op.drop_table("quota_adjustment")
    op.drop_table("quota_reconciliation_difference")
    op.drop_table("quota_reconciliation_run")
    op.drop_column("quota", "drift_summary")
    op.drop_column("quota", "last_reconciliation_run_id")
    op.drop_column("quota", "measured_at")
    op.drop_column("quota", "consistency_status")
    for table, columns in {
        "quota_reservation": ("actual_bytes", "requested_bytes"),
        "quota": ("reserved_bytes", "used_bytes", "limit_bytes"),
        "file_ingestion_record": ("actual_size",),
        "multipart_part": ("content_length",),
        "multipart_session": ("declared_length",),
        "upload_session": ("declared_length",),
        "file_object": ("content_length",),
    }.items():
        for column in columns:
            op.alter_column(table, column, type_=sa.Integer())
    op.drop_column("file_object", "deleted_at")
