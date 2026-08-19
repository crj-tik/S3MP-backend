"""Backfill distinct application principals and authority versions.

Revision ID: 0013_application_principals
Revises: 0012_file_delete_outbox
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op

revision: str = "0013_application_principals"
down_revision: str | None = "0012_file_delete_outbox"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "application",
        sa.Column("authorization_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "ck_application_authorization_version_positive",
        "application",
        "authorization_version >= 1",
    )

    # The backfill below needs result rows and therefore cannot be rendered
    # by Alembic's offline SQL generator.  Keep schema DDL available for
    # review; the data backfill still runs normally in online migrations.
    if context.is_offline_mode():
        return

    connection = op.get_bind()
    applications = connection.execute(
        sa.text(
            "SELECT a.id, a.tenant_id, a.name, "
            "EXISTS (SELECT 1 FROM application_owner ao "
            "JOIN principal p ON p.tenant_id = ao.tenant_id "
            "AND p.id = ao.owner_principal_id "
            "WHERE ao.tenant_id = a.tenant_id AND ao.application_id = a.id "
            "AND p.enabled = true AND p.type IN ('user', 'group')) AS has_valid_owner "
            "FROM application a"
        )
    ).mappings()
    for application in applications:
        principal_id = uuid4()
        connection.execute(
            sa.text(
                "INSERT INTO principal (id, tenant_id, type, display_name, enabled) "
                "VALUES (:id, :tenant_id, 'application', :display_name, true)"
            ),
            {
                "id": principal_id,
                "tenant_id": application["tenant_id"],
                "display_name": application["name"],
            },
        )
        connection.execute(
            sa.text(
                "UPDATE application SET principal_id = :principal_id, "
                "status = CASE WHEN :has_valid_owner THEN status ELSE 'pending_takeover' END "
                "WHERE tenant_id = :tenant_id AND id = :id"
            ),
            {
                "principal_id": principal_id,
                "tenant_id": application["tenant_id"],
                "id": application["id"],
                "has_valid_owner": application["has_valid_owner"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO audit_event "
                "(id, tenant_id, actor_principal_id, action, resource_type, resource_id, details) "
                "VALUES (:event_id, :tenant_id, NULL, :action, 'application', :resource_id, "
                "CAST(:details AS json))"
            ),
            {
                "event_id": uuid4(),
                "tenant_id": application["tenant_id"],
                "action": (
                    "migration.application_principal_backfilled"
                    if application["has_valid_owner"]
                    else "migration.application_quarantined"
                ),
                "resource_id": str(application["id"]),
                "details": (
                    '{"result":"backfilled","principal_type":"application"}'
                    if application["has_valid_owner"]
                    else '{"result":"pending_takeover","reason":"no_valid_owner"}'
                ),
            },
        )


def downgrade() -> None:
    # Backfilled principals may already be referenced by RoleBindings. Preserve
    # them as historical identities; only remove the additive authority column.
    op.execute(
        "ALTER TABLE application "
        "DROP CONSTRAINT IF EXISTS ck_application_authorization_version_positive"
    )
    op.drop_column("application", "authorization_version")
