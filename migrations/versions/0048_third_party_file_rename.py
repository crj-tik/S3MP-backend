"""Add durable third-party file rename support.

Revision ID: 0048_third_party_file_rename
Revises: 0047_role_binding_unique_principal_role
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0048_third_party_file_rename"
down_revision: str | None = "0047_role_binding_unique_principal_role"
branch_labels: str | None = None
depends_on: str | None = None

def upgrade() -> None:
    # A historical tombstone must not indefinitely reserve a logical path. Fail
    # migration rather than silently picking one of any live collisions.
    duplicate = op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM file_object "
            "WHERE status IN ('available', 'renaming', 'rename_failed', 'deleting', "
            "'delete_failed') GROUP BY tenant_id, storage_space_id, object_key "
            "HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError("live file-object key collision; resolve before rename migration")

    op.drop_constraint(
        "uq_file_object_tenant_id_storage_space_id_object_key", "file_object", type_="unique"
    )
    op.create_index(
        "uq_file_object_active_key",
        "file_object",
        ["tenant_id", "storage_space_id", "object_key"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('available', 'renaming', 'rename_failed', 'deleting', 'delete_failed')"
        ),
    )
    op.add_column("file_operation", sa.Column("source_file_id", sa.Uuid(), nullable=True))
    op.add_column("file_operation", sa.Column("result_file_id", sa.Uuid(), nullable=True))
    op.add_column("file_operation", sa.Column("request_fingerprint", sa.String(64), nullable=True))
    op.create_index(
        "uq_file_operation_rename_source_active",
        "file_operation",
        ["tenant_id", "source_file_id"],
        unique=True,
        postgresql_where=sa.text(
            "operation_type = 'rename' AND "
            "status IN ('pending', 'running', 'retry_wait', 'partial_failure')"
        ),
    )
    op.create_index(
        "uq_file_operation_rename_idempotency",
        "file_operation",
        ["tenant_id", "application_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("operation_type = 'rename'"),
    )


def downgrade() -> None:
    op.drop_index("uq_file_operation_rename_idempotency", table_name="file_operation")
    op.drop_index("uq_file_operation_rename_source_active", table_name="file_operation")
    op.drop_column("file_operation", "request_fingerprint")
    op.drop_column("file_operation", "result_file_id")
    op.drop_column("file_operation", "source_file_id")
    op.drop_index("uq_file_object_active_key", table_name="file_object")
    op.create_unique_constraint(
        "uq_file_object_tenant_id_storage_space_id_object_key",
        "file_object",
        ["tenant_id", "storage_space_id", "object_key"],
    )
