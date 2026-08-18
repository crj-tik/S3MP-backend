"""Add application-scoped quota allocation metadata."""

import sqlalchemy as sa
from alembic import op

revision: str = "0026_application_quota_scope"
down_revision: str | None = "0025_backfill_app_namespaces"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("quota", sa.Column("application_id", sa.Uuid(), nullable=True))
    op.create_index("ix_quota_tenant_application", "quota", ["tenant_id", "application_id"])
    op.create_foreign_key(
        "fk_quota_application",
        "quota",
        "application",
        ["tenant_id", "application_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_quota_tenant_application", "quota", ["tenant_id", "application_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_quota_tenant_application", "quota", type_="unique")
    op.drop_constraint("fk_quota_application", "quota", type_="foreignkey")
    op.drop_index("ix_quota_tenant_application", table_name="quota")
    op.drop_column("quota", "application_id")
