"""Add an optional application-relative directory scope to API keys."""

import sqlalchemy as sa
from alembic import op

revision: str = "0045_api_key_directory_scope"
down_revision: str | None = "0044_file_actor_application_attribution"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("api_key", sa.Column("directory_prefix", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("api_key", "directory_prefix")
