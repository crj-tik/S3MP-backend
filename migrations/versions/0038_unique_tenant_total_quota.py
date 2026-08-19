"""Enforce one active tenant-total quota per tenant."""

from alembic import op

revision: str = "0038_unique_tenant_total"
down_revision: str | None = "0037_legacy_reservation"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "uq_quota_active_tenant_total",
        "quota",
        ["tenant_id"],
        unique=True,
        postgresql_where="application_id IS NULL AND storage_space_id IS NULL AND status = 'active'",
    )


def downgrade() -> None:
    op.drop_index("uq_quota_active_tenant_total", table_name="quota")
