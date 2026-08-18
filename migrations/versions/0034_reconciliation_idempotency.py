"""Add scoped reconciliation idempotency keys."""

import sqlalchemy as sa
from alembic import op

revision: str = "0034_reconciliation_idempotency"
down_revision: str | None = "0033_reconciliation_progress"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "quota_reconciliation_run", sa.Column("idempotency_key", sa.String(length=128))
    )
    op.create_unique_constraint(
        "uq_quota_reconciliation_run_tenant_idempotency",
        "quota_reconciliation_run",
        ["tenant_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_quota_reconciliation_run_tenant_idempotency",
        "quota_reconciliation_run",
        type_="unique",
    )
    op.drop_column("quota_reconciliation_run", "idempotency_key")
