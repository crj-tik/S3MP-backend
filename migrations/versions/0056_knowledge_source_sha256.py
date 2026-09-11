"""Separate declared checksums from canonical knowledge-source SHA-256.

Revision ID: 0056_knowledge_source_sha256
Revises: 0055_knowledge_card_extraction
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0056_knowledge_source_sha256"
down_revision: str | None = "0055_knowledge_card_extraction"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "knowledge_analysis_task",
        "source_content_hash",
        existing_type=sa.String(length=64),
        type_=sa.String(length=512),
    )
    op.add_column("knowledge_analysis_task", sa.Column("source_sha256", sa.String(length=64)))
    op.drop_index("ix_knowledge_analysis_task_source_hash", table_name="knowledge_analysis_task")
    op.create_index(
        "ix_knowledge_analysis_task_source_hash",
        "knowledge_analysis_task",
        ["tenant_id", "source_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_analysis_task_source_hash", table_name="knowledge_analysis_task")
    op.drop_column("knowledge_analysis_task", "source_sha256")
    op.alter_column(
        "knowledge_analysis_task",
        "source_content_hash",
        existing_type=sa.String(length=512),
        type_=sa.String(length=64),
    )
