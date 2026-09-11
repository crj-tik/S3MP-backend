"""Add nullable public deterministic file references.

Revision ID: 0059_deterministic_file_references
Revises: 0058_file_deletion_records
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0059_deterministic_file_references"
down_revision: str | None = "0058_file_deletion_records"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("file_object", sa.Column("public_file_ref", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_file_object_public_file_ref", "file_object", ["public_file_ref"], unique=True
    )
    op.add_column("multipart_session", sa.Column("checksum", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("multipart_session", "checksum")
    op.drop_index("uq_file_object_public_file_ref", table_name="file_object")
    op.drop_column("file_object", "public_file_ref")
