"""Backfill only unambiguous legacy storage-space application bindings.

Legacy spaces that do not have exactly one active application and one unbound
active space in their tenant deliberately remain unbound. Runtime read paths
already quarantine those rows instead of guessing a shared-bucket namespace.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0029_backfill_space_bindings"
down_revision: str | None = "0028_hier_quota_reservations"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            WITH tenant_candidates AS (
                SELECT tenant_id, id AS application_id
                  FROM (
                      SELECT app.tenant_id,
                             app.id,
                             COUNT(*) OVER (PARTITION BY app.tenant_id) AS active_count
                        FROM application AS app
                       WHERE app.status = 'active'
                  ) AS active_applications
                 WHERE active_count = 1
            ), unbound_space_counts AS (
                SELECT tenant_id
                  FROM storage_space
                 WHERE application_id IS NULL
                   AND status = 'active'
                 GROUP BY tenant_id
                HAVING COUNT(*) = 1
            )
            UPDATE storage_space AS space
               SET application_id = candidate.application_id,
                   storage_namespace = app.storage_namespace,
                   profile_version = COALESCE(space.profile_version, 1)
              FROM tenant_candidates AS candidate
              JOIN unbound_space_counts AS unbound
                ON unbound.tenant_id = candidate.tenant_id
              JOIN application AS app
                ON app.tenant_id = candidate.tenant_id
               AND app.id = candidate.application_id
             WHERE space.tenant_id = candidate.tenant_id
               AND space.application_id IS NULL
               AND space.status = 'active'
               AND app.storage_namespace IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    # Binding provenance is intentionally retained: rolling back application
    # code must not discard a verified mapping or reactivate ambiguous rows.
    pass
