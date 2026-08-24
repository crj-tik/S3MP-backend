"""Allow one active tenant role binding per member or group."""

import sqlalchemy as sa
from alembic import op

revision: str = "0046_unique_active_role_binding_principal"
down_revision: str | None = "0045_api_key_directory_scope"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "uq_role_binding_active_principal",
        "role_binding",
        ["tenant_id", "principal_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_role_binding_active_principal", table_name="role_binding")
