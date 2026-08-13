"""Persist internal locations for resumable provider migration manifests.

Revision ID: 0018_provider_manifest_locations
Revises: 0017_durable_subject_provider
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0018_provider_manifest_locations"
down_revision: str | None = "0017_durable_subject_provider"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("provider_migration_manifest", sa.Column("source_bucket", sa.String(255)))
    op.add_column("provider_migration_manifest", sa.Column("source_key", sa.String(1024)))
    op.add_column("provider_migration_manifest", sa.Column("target_bucket", sa.String(255)))
    op.add_column("provider_migration_manifest", sa.Column("target_key", sa.String(1024)))


def downgrade() -> None:
    op.drop_column("provider_migration_manifest", "target_key")
    op.drop_column("provider_migration_manifest", "target_bucket")
    op.drop_column("provider_migration_manifest", "source_key")
    op.drop_column("provider_migration_manifest", "source_bucket")
