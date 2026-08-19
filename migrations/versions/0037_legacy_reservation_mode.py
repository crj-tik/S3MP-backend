"""Allow transitional reservations for legacy storage-space quotas."""

import sqlalchemy as sa
from alembic import op

revision: str = "0037_legacy_reservation"
down_revision: str | None = "0036_reservation_allocation_mode"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_quota_reservation_allocation_mode", "quota_reservation", type_="check"
    )
    op.create_check_constraint(
        "ck_quota_reservation_allocation_mode",
        "quota_reservation",
        "allocation_mode IN ('shared_pool', 'application_reserved', 'storage_space_legacy')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_quota_reservation_allocation_mode", "quota_reservation", type_="check"
    )
    op.create_check_constraint(
        "ck_quota_reservation_allocation_mode",
        "quota_reservation",
        "allocation_mode IN ('shared_pool', 'application_reserved')",
    )
