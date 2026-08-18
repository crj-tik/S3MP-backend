"""Persist Multipart part idempotency identity for safe retries."""

import sqlalchemy as sa
from alembic import op

revision: str = "0030_multipart_part_idempotency"
down_revision: str | None = "0029_backfill_space_bindings"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "multipart_part",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("multipart_part", "idempotency_key")
