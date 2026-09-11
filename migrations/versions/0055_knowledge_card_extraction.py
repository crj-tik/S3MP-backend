"""Add durable knowledge extraction tasks, exclusions, batches and outbox.

Revision ID: 0055_knowledge_card_extraction
Revises: 0054_rabbitmq_file_operations
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0055_knowledge_card_extraction"
down_revision: str | None = "0054_rabbitmq_file_operations"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_analysis_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_file_id", sa.Uuid()),
        sa.Column("source_application_id", sa.Uuid()),
        sa.Column("source_storage_space_id", sa.Uuid()),
        sa.Column("source_storage_namespace", sa.String(length=1024)),
        sa.Column("source_object_key", sa.String(length=1024), nullable=False),
        sa.Column("source_content_type", sa.String(length=255), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64)),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("contract_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("phase", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("batch_id", sa.String(length=64)),
        sa.Column("batch_prefix", sa.String(length=2048)),
        sa.Column("failure_reason", sa.String(length=256)),
        sa.Column("diagnostics", sa.JSON()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["file_object.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_file_id", "contract_manifest_hash"),
    )
    op.create_index(
        "ix_knowledge_analysis_task_pending", "knowledge_analysis_task", ["state", "created_at"]
    )
    op.create_index(
        "ix_knowledge_analysis_task_source_hash",
        "knowledge_analysis_task",
        ["tenant_id", "source_content_hash"],
    )
    op.create_table(
        "knowledge_extraction_exclusion_rule",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("directory_path", sa.String(length=1024), nullable=False),
        sa.Column("rule_source", sa.String(length=32), nullable=False),
        sa.Column("created_by_principal_id", sa.Uuid()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "application_id", "directory_path", "rule_source"),
    )
    op.create_index(
        "ix_knowledge_exclusion_rule_match",
        "knowledge_extraction_exclusion_rule",
        ["tenant_id", "application_id", "enabled"],
    )
    op.create_table(
        "knowledge_batch",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("s3_prefix", sa.String(length=2048), nullable=False),
        sa.Column("completion_manifest_key", sa.String(length=2048), nullable=False),
        sa.Column("completion_manifest_checksum", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["knowledge_analysis_task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "batch_id"),
    )
    op.create_index("ix_knowledge_batch_task", "knowledge_batch", ["task_id"])
    op.create_table(
        "knowledge_card",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.String(length=256), nullable=False),
        sa.Column("card_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("s3_key", sa.String(length=2048), nullable=False),
        sa.Column("checksum", sa.String(length=64)),
        sa.Column("source_locations", sa.JSON(), nullable=False),
        sa.Column("index_state", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["knowledge_batch.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "batch_id", "card_id"),
    )
    op.create_index("ix_knowledge_card_tenant_card", "knowledge_card", ["tenant_id", "card_id"])
    op.create_table(
        "knowledge_event_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid()),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("publish_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("publish_lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["knowledge_analysis_task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_event_outbox_pending",
        "knowledge_event_outbox",
        ["published_at", "created_at"],
    )
    op.create_table(
        "knowledge_dead_letter_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["knowledge_analysis_task.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_dead_letter_task", "knowledge_dead_letter_event", ["task_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_dead_letter_task", table_name="knowledge_dead_letter_event")
    op.drop_table("knowledge_dead_letter_event")
    op.drop_index("ix_knowledge_event_outbox_pending", table_name="knowledge_event_outbox")
    op.drop_table("knowledge_event_outbox")
    op.drop_index("ix_knowledge_card_tenant_card", table_name="knowledge_card")
    op.drop_table("knowledge_card")
    op.drop_index("ix_knowledge_batch_task", table_name="knowledge_batch")
    op.drop_table("knowledge_batch")
    op.drop_index(
        "ix_knowledge_exclusion_rule_match", table_name="knowledge_extraction_exclusion_rule"
    )
    op.drop_table("knowledge_extraction_exclusion_rule")
    op.drop_index("ix_knowledge_analysis_task_source_hash", table_name="knowledge_analysis_task")
    op.drop_index("ix_knowledge_analysis_task_pending", table_name="knowledge_analysis_task")
    op.drop_table("knowledge_analysis_task")
