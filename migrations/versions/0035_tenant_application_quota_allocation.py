"""Add explicit quota allocation modes and lifecycle states."""

import sqlalchemy as sa
from alembic import op

revision: str = "0035_quota_allocation"
down_revision: str | None = "0034_reconciliation_idempotency"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("quota", sa.Column("allocation_mode", sa.String(length=32), nullable=True))
    op.add_column("quota", sa.Column("status", sa.String(length=16), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE quota
            SET allocation_mode = CASE
                WHEN application_id IS NOT NULL THEN 'application_reserved'
                WHEN storage_space_id IS NOT NULL THEN 'storage_space_legacy'
                ELSE 'tenant_total'
            END,
            status = CASE
                WHEN storage_space_id IS NOT NULL THEN 'legacy'
                ELSE 'active'
            END
            """
        )
    )
    op.alter_column("quota", "allocation_mode", nullable=False, server_default="tenant_total")
    op.alter_column("quota", "status", nullable=False, server_default="active")
    op.create_check_constraint(
        "ck_quota_allocation_mode",
        "quota",
        "allocation_mode IN ('tenant_total', 'application_reserved', 'storage_space_legacy')",
    )
    op.create_check_constraint(
        "ck_quota_status",
        "quota",
        "status IN ('active', 'suspended', 'revoked', 'legacy')",
    )
    op.create_index(
        "ix_quota_tenant_status_mode", "quota", ["tenant_id", "status", "allocation_mode"]
    )
    op.create_index("ix_quota_application_status", "quota", ["application_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_quota_application_status", table_name="quota")
    op.drop_index("ix_quota_tenant_status_mode", table_name="quota")
    op.drop_constraint("ck_quota_status", "quota", type_="check")
    op.drop_constraint("ck_quota_allocation_mode", "quota", type_="check")
    op.drop_column("quota", "status")
    op.drop_column("quota", "allocation_mode")
