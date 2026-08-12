"""Add tenant and identity persistence schema.

Revision ID: 0002_identity
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002_identity"
down_revision: str | None = "0001_initial"
branch_labels: str | None = None
depends_on: str | None = None

principal_type = sa.Enum(
    "user", "group", "application", name="principal_type", native_enum=False, create_constraint=True
)
user_status = sa.Enum(
    "active", "disabled", name="user_status", native_enum=False, create_constraint=True
)
membership_status = sa.Enum(
    "invited",
    "active",
    "suspended",
    "removed",
    name="membership_status",
    native_enum=False,
    create_constraint=True,
)
history_from_status = sa.Enum(
    "invited",
    "active",
    "suspended",
    "removed",
    name="membership_history_from_status",
    native_enum=False,
    create_constraint=True,
)
history_to_status = sa.Enum(
    "invited",
    "active",
    "suspended",
    "removed",
    name="membership_history_to_status",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant"),
        sa.UniqueConstraint("slug", name="uq_tenant_slug"),
    )
    op.create_table(
        "user_account",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("status", user_status, nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_account"),
        sa.UniqueConstraint("normalized_email", name="uq_user_account_normalized_email"),
    )
    op.create_table(
        "principal",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type", principal_type, nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_principal_tenant_id_tenant", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_principal"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_principal_tenant_id_id"),
    )
    op.create_index("ix_principal_tenant_type", "principal", ["tenant_id", "type"])
    op.create_table(
        "external_identity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(2048), nullable=False),
        sa.Column("subject", sa.String(1024), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name="fk_external_identity_user_id_user_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_external_identity"),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identity_issuer_subject"),
    )
    op.create_table(
        "membership",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("status", membership_status, nullable=False),
        sa.Column("authorization_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "authorization_version >= 1", name="ck_membership_authorization_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_membership_tenant_id_tenant", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["principal.tenant_id", "principal.id"],
            name="fk_membership_tenant_id_principal_id_principal",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name="fk_membership_user_id_user_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_membership"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_membership_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "principal_id", name="uq_membership_tenant_id_principal_id"
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", "principal_id", name="uq_membership_tenant_id_id_principal_id"
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_id_user_id"),
    )
    op.create_index("ix_membership_tenant_status", "membership", ["tenant_id", "status"])
    op.create_table(
        "membership_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", history_from_status, nullable=True),
        sa.Column("to_status", history_to_status, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by_principal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_membership_status_history_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["membership.tenant_id", "membership.id"],
            name="fk_membership_status_history_tenant_id_membership_id_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "changed_by_principal_id"],
            ["principal.tenant_id", "principal.id"],
            name="fk_membership_history_changed_by_principal",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_membership_status_history"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_membership_status_history_tenant_id_id"),
    )
    op.create_index(
        "ix_membership_history_tenant_membership",
        "membership_status_history",
        ["tenant_id", "membership_id"],
    )
    op.create_table(
        "auth_session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(64), nullable=False),
        sa.Column("csrf_digest", sa.LargeBinary(64), nullable=False),
        sa.Column("authorization_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_auth_session_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id", "principal_id"],
            ["membership.tenant_id", "membership.id", "membership.principal_id"],
            name="fk_auth_session_membership_principal",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_session"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_auth_session_tenant_id_id"),
        sa.UniqueConstraint("token_digest", name="uq_auth_session_token_digest"),
    )
    op.create_index("ix_auth_session_expires_at", "auth_session", ["expires_at"])
    op.create_index(
        "ix_auth_session_tenant_principal", "auth_session", ["tenant_id", "principal_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_auth_session_tenant_principal", table_name="auth_session")
    op.drop_index("ix_auth_session_expires_at", table_name="auth_session")
    op.drop_table("auth_session")
    op.drop_index("ix_membership_history_tenant_membership", table_name="membership_status_history")
    op.drop_table("membership_status_history")
    op.drop_index("ix_membership_tenant_status", table_name="membership")
    op.drop_table("membership")
    op.drop_table("external_identity")
    op.drop_index("ix_principal_tenant_type", table_name="principal")
    op.drop_table("principal")
    op.drop_table("user_account")
    op.drop_table("tenant")
