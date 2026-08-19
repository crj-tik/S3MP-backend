"""Bind an application to one tenant-local membership representative."""

import sqlalchemy as sa
from alembic import op

revision: str = "0039_application_membership_binding"
down_revision: str | None = "0038_unique_tenant_total"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "application_membership_binding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_principal_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "application_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "application_id"],
            ["application.tenant_id", "application.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["membership.tenant_id", "membership.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_application_membership_binding_tenant_status",
        "application_membership_binding",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_membership_binding_tenant_status",
        table_name="application_membership_binding",
    )
    op.drop_table("application_membership_binding")
