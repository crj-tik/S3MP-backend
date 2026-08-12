"""Add tenant-scoped groups, roles, permissions and role bindings.

Revision ID: 0003_authorization
Revises: 0002_identity
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003_authorization"
down_revision: str | None = "0002_identity"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "user_group",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principal.tenant_id", "principal.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_group"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_user_group_tenant_id_id"),
    )
    op.create_index("ix_user_group_tenant_name", "user_group", ["tenant_id", "name"])
    op.create_table(
        "group_member",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "group_id"], ["user_group.tenant_id", "user_group.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principal.tenant_id", "principal.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_group_member"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_group_member_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "group_id", "principal_id", name="uq_group_member_membership"),
    )
    op.create_index("ix_group_member_tenant_group", "group_member", ["tenant_id", "group_id"])
    op.create_table(
        "permission",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("delegable", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_permission"),
        sa.UniqueConstraint("name", name="uq_permission_name"),
    )
    op.create_table(
        "role",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("built_in", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_role"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_role_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_role_tenant_name"),
    )
    op.create_index("ix_role_tenant_name", "role", ["tenant_id", "name"])
    op.create_table(
        "role_permission",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permission.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permission"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission_role_id"),
    )
    op.create_table(
        "role_binding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("effect", sa.String(10), nullable=False),
        sa.Column("storage_space_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_prefix", sa.String(2048), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_principal_id", sa.Uuid(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("effect IN ('allow', 'deny')", name="ck_role_binding_effect"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principal.tenant_id", "principal.id"], ondelete="CASCADE",
            name="fk_role_binding_principal",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["role.tenant_id", "role.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_principal_id"],
            ["principal.tenant_id", "principal.id"], ondelete="RESTRICT",
            name="fk_role_binding_created_by_principal",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_role_binding"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_role_binding_tenant_id_id"),
    )
    op.create_index("ix_role_binding_tenant_principal", "role_binding", ["tenant_id", "principal_id"])
    op.create_index(
        "ix_role_binding_tenant_scope", "role_binding", ["tenant_id", "storage_space_id", "canonical_prefix"]
    )


def downgrade() -> None:
    op.drop_index("ix_role_binding_tenant_scope", table_name="role_binding")
    op.drop_index("ix_role_binding_tenant_principal", table_name="role_binding")
    op.drop_table("role_binding")
    op.drop_table("role_permission")
    op.drop_index("ix_role_tenant_name", table_name="role")
    op.drop_table("role")
    op.drop_table("permission")
    op.drop_index("ix_group_member_tenant_group", table_name="group_member")
    op.drop_table("group_member")
    op.drop_index("ix_user_group_tenant_name", table_name="user_group")
    op.drop_table("user_group")
