"""Promote tenant-admin to a global platform role and retire legacy bindings."""

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0040_platform_tenant_admin"
down_revision: str | None = "0039_application_membership_binding"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    bind = op.get_bind()
    platform_role = sa.table(
        "platform_role",
        sa.column("id", sa.Uuid),
        sa.column("name", sa.String),
        sa.column("permissions", sa.JSON),
        sa.column("built_in", sa.Boolean),
    )
    role_id = UUID("2db9f2fd-6cc6-5a1e-9f2d-0cb1a2e2e8d0")
    exists = bind.execute(
        sa.select(platform_role.c.id).where(platform_role.c.name == "tenant-admin")
    ).first()
    if exists is None:
        bind.execute(
            sa.insert(platform_role).values(
                id=role_id,
                name="tenant-admin",
                permissions=[],
                built_in=True,
            )
        )

    # Legacy tenant-local bindings must not remain an authorization source.
    # Keep the Role/RoleBinding rows for audit/history, but revoke the binding
    # rather than deleting evidence of the old bootstrap behavior.
    now = datetime.now(timezone.utc)
    bind.execute(
        sa.text(
            """
            UPDATE role_binding
               SET revoked_at = :now
             WHERE revoked_at IS NULL
               AND role_id IN (SELECT id FROM role WHERE name = 'tenant-admin')
            """
        ),
        {"now": now},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM platform_role WHERE name = 'tenant-admin'")
    )
