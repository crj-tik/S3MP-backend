"""Add tenant-unique third-party application codes."""

import sqlalchemy as sa
from alembic import op

revision: str = "0043_application_code"
down_revision: str | None = "0042_remove_tenant_read"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("application", sa.Column("code", sa.String(length=64), nullable=True))
    op.execute("UPDATE application SET code = replace(CAST(id AS text), '-', '') WHERE code IS NULL")
    op.alter_column("application", "code", nullable=False)
    op.create_unique_constraint("uq_application_tenant_code", "application", ["tenant_id", "code"])


def downgrade() -> None:
    op.drop_constraint("uq_application_tenant_code", "application", type_="unique")
    op.drop_column("application", "code")
