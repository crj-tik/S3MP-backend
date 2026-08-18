"""Add platform shared S3 profile and application storage namespace metadata."""

import sqlalchemy as sa
from alembic import op

revision: str = "0023_shared_s3_namespace"
down_revision: str | None = "0022_resource_lifecycle"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "platform_storage_profile",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("endpoint", sa.String(length=500), nullable=False),
        sa.Column("region", sa.String(length=100), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("path_style", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("signature_version", sa.String(length=32), nullable=False, server_default="s3v4"),
        sa.Column("credential_reference", sa.String(length=500), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_storage_profile_status",
        "platform_storage_profile",
        ["status"],
    )
    op.add_column("storage_space", sa.Column("application_id", sa.Uuid(), nullable=True))
    op.add_column(
        "storage_space", sa.Column("storage_namespace", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "storage_space",
        sa.Column("profile_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_storage_space_tenant_application",
        "storage_space",
        ["tenant_id", "application_id"],
    )
    op.create_foreign_key(
        "fk_storage_space_application",
        "storage_space",
        "application",
        ["tenant_id", "application_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_storage_space_tenant_application",
        "storage_space",
        ["tenant_id", "application_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_storage_space_tenant_application", "storage_space", type_="unique")
    op.drop_constraint("fk_storage_space_application", "storage_space", type_="foreignkey")
    op.drop_index("ix_storage_space_tenant_application", table_name="storage_space")
    op.drop_column("storage_space", "profile_version")
    op.drop_column("storage_space", "storage_namespace")
    op.drop_column("storage_space", "application_id")
    op.drop_index("ix_platform_storage_profile_status", table_name="platform_storage_profile")
    op.drop_table("platform_storage_profile")
