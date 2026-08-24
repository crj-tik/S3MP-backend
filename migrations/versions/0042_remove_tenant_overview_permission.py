"""Remove the obsolete tenant.read overview permission."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0042_remove_tenant_read"
down_revision: str | None = "0041_implicit_app_storage"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permission WHERE name = 'tenant.read'")
    ).scalar_one_or_none()
    if permission_id is None:
        return
    bind.execute(
        sa.text("DELETE FROM role_permission WHERE permission_id = :permission_id"),
        {"permission_id": permission_id},
    )
    bind.execute(
        sa.text("DELETE FROM permission WHERE id = :permission_id"),
        {"permission_id": permission_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM permission WHERE name = 'tenant.read'")
    ).scalar_one_or_none()
    if exists is None:
        bind.execute(
            sa.text(
                """
                INSERT INTO permission (id, name, resource_type, delegable, description)
                VALUES (:id, 'tenant.read', 'tenant', true, 'View tenant metadata.')
                """
            ),
            {"id": uuid4()},
        )
