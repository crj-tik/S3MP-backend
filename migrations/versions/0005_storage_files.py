"""Add storage and file persistence.

Revision ID: 0005_storage_files
Revises: 0004_application_access
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005_storage_files"
down_revision: str | None = "0004_application_access"
branch_labels: str | None = None
depends_on: str | None = None


def _tenant_id() -> sa.Column[object]:
    return sa.Column("tenant_id", sa.Uuid(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "storage_connection",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("endpoint", sa.String(500), nullable=False),
        sa.Column("region", sa.String(100), nullable=False),
        sa.Column("path_style", sa.Boolean(), nullable=False),
        sa.Column("credential_reference", sa.String(500), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_storage_connection"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_storage_connection_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_storage_connection_tenant_id_name"),
    )
    op.create_index(
        "ix_storage_connection_tenant_status", "storage_connection", ["tenant_id", "status"]
    )
    op.create_table(
        "storage_space",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("bucket", sa.String(255), nullable=False),
        sa.Column("root_prefix", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "connection_id"],
            ["storage_connection.tenant_id", "storage_connection.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storage_space"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_storage_space_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_storage_space_tenant_id_name"),
    )
    op.create_index(
        "ix_storage_space_tenant_connection", "storage_space", ["tenant_id", "connection_id"]
    )
    op.create_table(
        "file_object",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("storage_space_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("etag", sa.String(512)),
        sa.Column("checksum", sa.String(512)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "storage_space_id"],
            ["storage_space.tenant_id", "storage_space.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_file_object"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_file_object_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "storage_space_id",
            "object_key",
            name="uq_file_object_tenant_id_storage_space_id_object_key",
        ),
    )
    op.create_index(
        "ix_file_object_tenant_space_key",
        "file_object",
        ["tenant_id", "storage_space_id", "object_key"],
    )
    op.create_table(
        "upload_session",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("storage_space_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("declared_length", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("checksum", sa.String(512)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "storage_space_id"],
            ["storage_space.tenant_id", "storage_space.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_upload_session"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_upload_session_tenant_id_id"),
    )
    op.create_index(
        "ix_upload_session_tenant_status_expires",
        "upload_session",
        ["tenant_id", "status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_upload_session_tenant_status_expires", table_name="upload_session")
    op.drop_table("upload_session")
    op.drop_index("ix_file_object_tenant_space_key", table_name="file_object")
    op.drop_table("file_object")
    op.drop_index("ix_storage_space_tenant_connection", table_name="storage_space")
    op.drop_table("storage_space")
    op.drop_index("ix_storage_connection_tenant_status", table_name="storage_connection")
    op.drop_table("storage_connection")
