"""Backfill and constrain implicit one-to-one application storage."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0041_implicit_app_storage"
down_revision: str | None = "0040_platform_tenant_admin"
branch_labels: str | None = None
depends_on: str | None = None


def _scalar(bind: sa.Connection, query: str) -> int:
    return int(bind.execute(sa.text(query)).scalar_one())


def upgrade() -> None:
    bind = op.get_bind()
    conflicts = {
        "duplicate_application_spaces": _scalar(
            bind,
            """
            SELECT COUNT(*) FROM (
                SELECT tenant_id, application_id
                  FROM storage_space
                 WHERE application_id IS NOT NULL
                 GROUP BY tenant_id, application_id HAVING COUNT(*) > 1
            ) AS conflicts
            """,
        ),
        "duplicate_namespaces": _scalar(
            bind,
            """
            SELECT COUNT(*) FROM (
                SELECT storage_namespace
                  FROM storage_space
                 WHERE storage_namespace IS NOT NULL
                 GROUP BY storage_namespace HAVING COUNT(*) > 1
            ) AS conflicts
            """,
        ),
        "cross_tenant_or_namespace_mismatch": _scalar(
            bind,
            """
            SELECT COUNT(*)
              FROM application AS a
              JOIN storage_space AS s ON s.application_id = a.id
             WHERE s.tenant_id <> a.tenant_id
                OR (a.storage_namespace IS NOT NULL
                    AND s.storage_namespace IS DISTINCT FROM a.storage_namespace)
            """,
        ),
    }
    if any(conflicts.values()):
        raise RuntimeError(f"implicit application storage preflight failed: {conflicts}")

    profile = bind.execute(
        sa.text(
            """
            SELECT endpoint, region, bucket, path_style, credential_reference, profile_version
              FROM platform_storage_profile
             WHERE status = 'active'
             ORDER BY profile_version DESC
             LIMIT 1
            """
        )
    ).mappings().first()
    applications = bind.execute(
        sa.text(
            """
            SELECT a.id, a.tenant_id, t.slug, a.storage_namespace
              FROM application AS a
              JOIN tenant AS t ON t.id = a.tenant_id
             WHERE a.status <> 'deleted'
             ORDER BY a.tenant_id, a.id
            """
        )
    ).mappings().all()
    if applications and profile is None:
        raise RuntimeError("implicit application storage requires an active platform profile")
    if profile is None:
        return

    connection_name = f"__s3mp_managed_shared_profile_v{profile['profile_version']}__"
    connection_ids: dict[object, object] = {}
    for app in applications:
        tenant_id = app["tenant_id"]
        if tenant_id not in connection_ids:
            connection_id = bind.execute(
                sa.text(
                    """
                    SELECT id FROM storage_connection
                     WHERE tenant_id = :tenant_id AND name = :name
                    """
                ),
                {"tenant_id": tenant_id, "name": connection_name},
            ).scalar_one_or_none()
            if connection_id is None:
                connection_id = uuid4()
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO storage_connection
                            (id, tenant_id, name, endpoint, region, path_style,
                             credential_reference, capabilities, status)
                        VALUES
                            (:id, :tenant_id, :name, :endpoint, :region, :path_style,
                             :credential_reference, CAST(:capabilities AS json), 'active')
                        """
                    ),
                    {
                        "id": connection_id,
                        "tenant_id": tenant_id,
                        "name": connection_name,
                        "endpoint": profile["endpoint"],
                        "region": profile["region"],
                        "path_style": profile["path_style"],
                        "credential_reference": profile["credential_reference"],
                        "capabilities": '{"list_objects":true,"head_object":true,'
                        '"presigned_get":true,"presigned_put":true,"multipart":true,'
                        '"copy_object":true,"delete_object":true}',
                    },
                )
            connection_ids[tenant_id] = connection_id

        namespace = app["storage_namespace"] or f"{app['slug']}/{app['id']}"
        if app["storage_namespace"] is None:
            bind.execute(
                sa.text("UPDATE application SET storage_namespace = :namespace WHERE id = :id"),
                {"namespace": namespace, "id": app["id"]},
            )
        existing = bind.execute(
            sa.text(
                "SELECT id FROM storage_space WHERE tenant_id = :tenant_id "
                "AND application_id = :application_id"
            ),
            {"tenant_id": tenant_id, "application_id": app["id"]},
        ).scalar_one_or_none()
        if existing is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO storage_space
                        (id, tenant_id, connection_id, application_id, name, bucket,
                         root_prefix, storage_namespace, profile_version,
                         provider_target_version, status)
                    VALUES
                        (:id, :tenant_id, :connection_id, :application_id, :name, :bucket,
                         '', :namespace, :profile_version, 1, 'active')
                    """
                ),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "connection_id": connection_ids[tenant_id],
                    "application_id": app["id"],
                    "name": f"__application_storage__{app['id']}",
                    "bucket": profile["bucket"],
                    "namespace": namespace,
                    "profile_version": profile["profile_version"],
                },
            )

    op.create_index(
        "uq_application_storage_namespace",
        "application",
        ["storage_namespace"],
        unique=True,
        postgresql_where=sa.text("storage_namespace IS NOT NULL"),
    )
    op.create_index(
        "uq_storage_space_namespace",
        "storage_space",
        ["storage_namespace"],
        unique=True,
        postgresql_where=sa.text("storage_namespace IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_storage_space_namespace", table_name="storage_space")
    op.drop_index("uq_application_storage_namespace", table_name="application")

