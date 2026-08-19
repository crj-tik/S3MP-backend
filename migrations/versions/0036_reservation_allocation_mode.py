"""Record whether an upload reservation uses an application allocation or pool."""

import sqlalchemy as sa
from alembic import op

revision: str = "0036_reservation_allocation_mode"
down_revision: str | None = "0035_quota_allocation"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "quota_reservation",
        sa.Column("allocation_mode", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE quota_reservation
            SET allocation_mode = CASE
                WHEN application_quota_id IS NOT NULL THEN 'application_reserved'
                ELSE 'shared_pool'
            END
            """
        )
    )
    op.alter_column("quota_reservation", "allocation_mode", nullable=False, server_default="shared_pool")
    op.create_check_constraint(
        "ck_quota_reservation_allocation_mode",
        "quota_reservation",
        "allocation_mode IN ('shared_pool', 'application_reserved')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_quota_reservation_allocation_mode", "quota_reservation", type_="check")
    op.drop_column("quota_reservation", "allocation_mode")
