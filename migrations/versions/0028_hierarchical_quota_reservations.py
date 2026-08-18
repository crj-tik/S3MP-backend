"""Track both application and tenant quota ledgers in one reservation."""

import sqlalchemy as sa
from alembic import op

revision: str = "0028_hier_quota_reservations"
down_revision: str | None = "0027_file_storage_provenance"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("quota_reservation", sa.Column("application_quota_id", sa.Uuid(), nullable=True))
    op.add_column("quota_reservation", sa.Column("tenant_quota_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("quota_reservation", "tenant_quota_id")
    op.drop_column("quota_reservation", "application_quota_id")
