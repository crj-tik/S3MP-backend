"""Backfill immutable application storage namespaces for existing rows."""

import sqlalchemy as sa
from alembic import op

revision: str = "0025_backfill_app_namespaces"
down_revision: str | None = "0024_app_storage_namespace"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Existing applications map deterministically from tenant slug and the
    # immutable application id. Unbound storage spaces remain for audit flow.
    op.get_bind().execute(
        sa.text(
            """
            UPDATE application AS app
               SET storage_namespace = tenant.slug || '/' || app.id::text
              FROM tenant
             WHERE tenant.id = app.tenant_id
               AND app.storage_namespace IS NULL
            """
        )
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("UPDATE application SET storage_namespace = NULL"))
