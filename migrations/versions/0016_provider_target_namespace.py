"""Add versioned, server-owned storage provider target metadata.

Revision ID: 0016_provider_target_namespace
Revises: 0015_delete_reconcile
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0016_provider_target_namespace"
down_revision: str | None = "0015_delete_reconcile"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "storage_space",
        sa.Column("provider_target_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_storage_space_tenant_target_version",
        "storage_space",
        ["tenant_id", "provider_target_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_storage_space_tenant_target_version", table_name="storage_space")
    op.drop_column("storage_space", "provider_target_version")
