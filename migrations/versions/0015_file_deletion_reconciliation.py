"""Persist bounded and re-authorized file deletion reconciliation.

Revision ID: 0015_delete_reconcile
Revises: 0014_file_operation_worker
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0015_delete_reconcile"
down_revision: str | None = "0014_file_operation_worker"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("file_object", sa.Column("deletion_attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("file_object", sa.Column("deletion_next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("file_object", sa.Column("deletion_failure_reason", sa.String(128), nullable=True))
    op.add_column("file_object", sa.Column("deletion_principal_id", sa.Uuid(), nullable=True))
    op.add_column("file_object", sa.Column("deletion_authorization_version", sa.Integer(), nullable=True))
    op.add_column("file_object", sa.Column("deletion_authorization_evidence", sa.JSON(), nullable=True))
    # Existing delete intents cannot be safely attributed; fail closed and
    # preserve them for operator review rather than touching object storage.
    op.execute(
        "UPDATE file_object SET status = 'delete_failed', "
        "deletion_failure_reason = 'legacy_authorization_evidence_missing' "
        "WHERE status = 'deleting'"
    )


def downgrade() -> None:
    for name in (
        "deletion_authorization_evidence", "deletion_authorization_version",
        "deletion_principal_id", "deletion_failure_reason",
        "deletion_next_retry_at", "deletion_attempt_count",
    ):
        op.drop_column("file_object", name)
