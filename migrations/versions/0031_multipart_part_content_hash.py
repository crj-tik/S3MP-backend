"""Persist Multipart part content identity for strict idempotent retries."""

import sqlalchemy as sa
from alembic import op

revision: str = "0031_multipart_part_content_hash"
down_revision: str | None = "0030_multipart_part_idempotency"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "multipart_part",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("multipart_part", "content_sha256")
