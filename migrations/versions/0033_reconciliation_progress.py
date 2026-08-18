"""Persist reconciliation progress and failure state."""

import sqlalchemy as sa
from alembic import op

revision: str = "0033_reconciliation_progress"
down_revision: str | None = "0032_quota_reconciliation_ledger"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "quota_reconciliation_run", sa.Column("provider_cursor", sa.String(length=2048))
    )
    op.add_column(
        "quota_reconciliation_run",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("quota_reconciliation_run", sa.Column("error_code", sa.String(length=64)))
    op.add_column(
        "quota_reconciliation_run", sa.Column("error_message", sa.String(length=1024))
    )
    op.add_column(
        "quota_reconciliation_run",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_column("quota_reconciliation_run", "updated_at")
    op.drop_column("quota_reconciliation_run", "error_message")
    op.drop_column("quota_reconciliation_run", "error_code")
    op.drop_column("quota_reconciliation_run", "attempt_count")
    op.drop_column("quota_reconciliation_run", "provider_cursor")
