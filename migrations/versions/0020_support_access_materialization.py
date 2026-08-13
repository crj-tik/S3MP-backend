"""Link support-access approval to its temporary tenant authority.

Revision ID: 0020_support_access
Revises: 0019_platform_control_plane
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0020_support_access"
down_revision: str | None = "0019_platform_control_plane"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "support_access_request",
        sa.Column(
            "approved_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "support_access_request",
        sa.Column(
            "membership_id",
            sa.Uuid(),
            sa.ForeignKey("membership.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "support_access_request",
        sa.Column(
            "role_binding_id",
            sa.Uuid(),
            sa.ForeignKey("role_binding.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("support_access_request", "role_binding_id")
    op.drop_column("support_access_request", "membership_id")
    op.drop_column("support_access_request", "approved_by_user_id")
