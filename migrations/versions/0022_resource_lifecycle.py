"""Add soft-deletion lifecycle metadata and reusable deleted account identities."""

import sqlalchemy as sa
from alembic import op

revision: str = "0022_resource_lifecycle"
down_revision: str | None = "0021_platform_account_identity"
branch_labels: str | None = None
depends_on: str | None = None


def _assert_no_active_identity_duplicates() -> None:
    connection = op.get_bind()
    queries = {
        "normalized_email": "SELECT normalized_email, COUNT(*) AS duplicate_count "
        "FROM user_account WHERE status <> 'deleted' "
        "GROUP BY normalized_email HAVING COUNT(*) > 1 ORDER BY normalized_email",
        "normalized_employee_number": "SELECT normalized_employee_number, "
        "COUNT(*) AS duplicate_count FROM user_account WHERE status <> 'deleted' "
        "GROUP BY normalized_employee_number HAVING COUNT(*) > 1 "
        "ORDER BY normalized_employee_number",
    }
    for column, query in queries.items():
        rows = connection.execute(
            sa.text(query)
        ).all()
        if rows:
            values = ", ".join(f"{row[0]} ({row[1]})" for row in rows)
            raise RuntimeError(
                f"Cannot create active account identity index for {column}; "
                f"duplicate values require remediation: {values}"
            )


def upgrade() -> None:
    op.add_column(
        "user_account", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("user_account", sa.Column("deleted_by", sa.Uuid(), nullable=True))
    op.add_column(
        "user_account", sa.Column("deletion_reason", sa.String(length=500), nullable=True)
    )
    op.add_column("tenant", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenant", sa.Column("deleted_by", sa.Uuid(), nullable=True))
    op.add_column("tenant", sa.Column("deletion_reason", sa.String(length=500), nullable=True))
    op.add_column(
        "application", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("application", sa.Column("deleted_by", sa.Uuid(), nullable=True))
    op.add_column(
        "application", sa.Column("deletion_reason", sa.String(length=500), nullable=True)
    )

    op.execute("ALTER TABLE user_account DROP CONSTRAINT IF EXISTS user_status")
    op.create_check_constraint(
        "ck_user_account_status_lifecycle",
        "user_account",
        "status IN ('active', 'disabled', 'deleted')",
    )
    op.execute("ALTER TABLE tenant DROP CONSTRAINT IF EXISTS tenant_lifecycle_status")
    op.create_check_constraint(
        "ck_tenant_status_lifecycle",
        "tenant",
        "status IN ('active', 'suspended', 'deleted')",
    )

    _assert_no_active_identity_duplicates()
    op.drop_constraint("uq_user_account_normalized_email", "user_account", type_="unique")
    op.drop_constraint(
        "uq_user_account_normalized_employee_number", "user_account", type_="unique"
    )
    op.create_index(
        "uq_user_active_email",
        "user_account",
        ["normalized_email"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted'"),
    )
    op.create_index(
        "uq_user_active_employee_number",
        "user_account",
        ["normalized_employee_number"],
        unique=True,
        postgresql_where=sa.text(
            "status <> 'deleted' AND normalized_employee_number IS NOT NULL"
        ),
    )
    op.create_index("ix_user_account_lifecycle", "user_account", ["status", "deleted_at"])
    op.create_index("ix_tenant_lifecycle", "tenant", ["status", "deleted_at"])
    op.create_index("ix_application_lifecycle", "application", ["status", "deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_application_lifecycle", table_name="application")
    op.drop_index("ix_tenant_lifecycle", table_name="tenant")
    op.drop_index("ix_user_account_lifecycle", table_name="user_account")
    op.drop_index("uq_user_active_employee_number", table_name="user_account")
    op.drop_index("uq_user_active_email", table_name="user_account")
    op.create_unique_constraint(
        "uq_user_account_normalized_email", "user_account", ["normalized_email"]
    )
    op.create_unique_constraint(
        "uq_user_account_normalized_employee_number",
        "user_account",
        ["normalized_employee_number"],
    )
    op.drop_constraint("ck_tenant_status_lifecycle", "tenant", type_="check")
    op.drop_constraint("ck_user_account_status_lifecycle", "user_account", type_="check")
    op.drop_column("application", "deletion_reason")
    op.drop_column("application", "deleted_by")
    op.drop_column("application", "deleted_at")
    op.drop_column("tenant", "deletion_reason")
    op.drop_column("tenant", "deleted_by")
    op.drop_column("tenant", "deleted_at")
    op.drop_column("user_account", "deletion_reason")
    op.drop_column("user_account", "deleted_by")
    op.drop_column("user_account", "deleted_at")
