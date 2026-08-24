"""Allow multiple roles per principal while preventing duplicate role grants."""

import sqlalchemy as sa
from alembic import op

revision: str = "0047_role_binding_unique_principal_role"
down_revision: str | None = "0046_unique_active_role_binding_principal"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_index("uq_role_binding_active_principal", table_name="role_binding")
    op.create_index(
        "uq_role_binding_active_principal_role",
        "role_binding",
        ["tenant_id", "principal_id", "role_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_role_binding_active_principal_role", table_name="role_binding")
    op.create_index(
        "uq_role_binding_active_principal",
        "role_binding",
        ["tenant_id", "principal_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
