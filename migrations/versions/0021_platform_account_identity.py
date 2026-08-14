"""Add company employee number to global accounts."""

import sqlalchemy as sa
from alembic import op

revision: str = "0021_platform_account_identity"
down_revision: str | None = "0020_support_access"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("user_account", sa.Column("employee_number", sa.String(length=64), nullable=True))
    op.add_column(
        "user_account",
        sa.Column("normalized_employee_number", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_user_account_normalized_employee_number",
        "user_account",
        ["normalized_employee_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_user_account_normalized_employee_number", "user_account", type_="unique"
    )
    op.drop_column("user_account", "normalized_employee_number")
    op.drop_column("user_account", "employee_number")
