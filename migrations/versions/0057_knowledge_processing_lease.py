"""Add durable ownership leases for knowledge analysis workers.

Revision ID: 0057_knowledge_processing_lease
Revises: 0056_knowledge_source_sha256
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0057_knowledge_processing_lease"
down_revision: str | None = "0056_knowledge_source_sha256"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("knowledge_analysis_task", sa.Column("processing_lease_token", sa.Uuid()))
    op.add_column(
        "knowledge_analysis_task",
        sa.Column("processing_lease_expires_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_knowledge_analysis_task_processing_lease",
        "knowledge_analysis_task",
        ["state", "processing_lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_analysis_task_processing_lease", table_name="knowledge_analysis_task"
    )
    op.drop_column("knowledge_analysis_task", "processing_lease_expires_at")
    op.drop_column("knowledge_analysis_task", "processing_lease_token")
