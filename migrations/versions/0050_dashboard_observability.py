"""Add delayed storage and API usage observability projections.

Revision ID: 0050_dashboard_observability
Revises: 0049_file_soft_delete_retention
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0050_dashboard_observability"
down_revision: str | None = "0049_file_soft_delete_retention"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_storage_summary",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("active_file_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("occupied_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("pending_cleanup_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "application_api_metric",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=256), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("client_error_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("server_error_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "application_id"],
            ["application.tenant_id", "application.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "application_id", "operation", "window_start"),
    )
    op.create_index(
        "ix_application_api_metric_tenant_window",
        "application_api_metric",
        ["tenant_id", "window_start"],
    )
    op.create_table(
        "application_api_error",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=256), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "application_id"],
            ["application.tenant_id", "application.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_api_error_tenant_occurred",
        "application_api_error",
        ["tenant_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_application_api_error_tenant_occurred", table_name="application_api_error")
    op.drop_table("application_api_error")
    op.drop_index("ix_application_api_metric_tenant_window", table_name="application_api_metric")
    op.drop_table("application_api_metric")
    op.drop_table("tenant_storage_summary")
