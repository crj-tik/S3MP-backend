"""Add durable RabbitMQ delivery and file-operation occupancy state.

Revision ID: 0054_rabbitmq_file_operations
Revises: 0053_cas_service_ticket_session
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0054_rabbitmq_file_operations"
down_revision: str | None = "0053_cas_service_ticket_session"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("file_object", sa.Column("active_operation_id", sa.Uuid()))
    op.add_column("file_object", sa.Column("operation_phase", sa.String(length=32)))
    op.add_column("file_object", sa.Column("processing_started_at", sa.DateTime(timezone=True)))
    op.add_column(
        "file_operation",
        sa.Column("recovery_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("file_operation", sa.Column("replay_of_event_id", sa.Uuid()))
    op.create_index("ix_file_object_operation_phase", "file_object", ["operation_phase"])
    op.create_table(
        "file_operation_event_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("publish_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("publish_lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("replay_of_event_id", sa.Uuid()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operation_id"], ["file_operation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_file_operation_event_outbox_pending",
        "file_operation_event_outbox",
        ["published_at", "created_at"],
    )
    op.create_table(
        "file_operation_resource_reservation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("storage_space_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operation_id"], ["file_operation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "storage_space_id", "object_key"),
    )


def downgrade() -> None:
    op.drop_table("file_operation_resource_reservation")
    op.drop_index(
        "ix_file_operation_event_outbox_pending", table_name="file_operation_event_outbox"
    )
    op.drop_table("file_operation_event_outbox")
    op.drop_column("file_operation", "replay_of_event_id")
    op.drop_column("file_operation", "recovery_attempt_count")
    op.drop_index("ix_file_object_operation_phase", table_name="file_object")
    op.drop_column("file_object", "processing_started_at")
    op.drop_column("file_object", "operation_phase")
    op.drop_column("file_object", "active_operation_id")
