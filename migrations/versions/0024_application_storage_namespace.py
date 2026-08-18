"""Add immutable application storage namespace metadata."""

import sqlalchemy as sa
from alembic import op

revision: str = "0024_app_storage_namespace"
down_revision: str | None = "0023_shared_s3_namespace"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "application", sa.Column("storage_namespace", sa.String(length=512), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("application", "storage_namespace")
