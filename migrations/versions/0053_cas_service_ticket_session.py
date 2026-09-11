"""Persist CAS service-ticket to local account-session mappings for SLO.

Revision ID: 0053_cas_service_ticket_session
Revises: 0052_file_record_version
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0053_cas_service_ticket_session"
down_revision: str | None = "0052_file_record_version"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "cas_service_ticket_session",
        sa.Column("ticket_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("account_session_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["account_session_id"], ["account_session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("ticket_digest"),
    )
    op.create_index(
        "ix_cas_service_ticket_session_account",
        "cas_service_ticket_session",
        ["account_session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cas_service_ticket_session_account", table_name="cas_service_ticket_session")
    op.drop_table("cas_service_ticket_session")
