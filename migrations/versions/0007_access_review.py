"""Add access_review, review_item and approval_request tables.

Revision ID: 0007_access_review
Revises: 0006_multipart_governance
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0007_access_review"
down_revision: str | None = "0006_multipart_governance"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "access_review",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_by_principal_id", sa.Uuid()),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_access_review_tenant_id_id"),
    )
    op.create_index("ix_access_review_tenant_status", "access_review", ["tenant_id", "status"])

    op.create_table(
        "review_item",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False, server_default="unreviewed"),
        sa.Column("reviewer_principal_id", sa.Uuid()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "review_id"],
            ["access_review.tenant_id", "access_review.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewer_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_review_item_review_verdict", "review_item", ["review_id", "verdict"])
    op.create_index(
        "ix_review_item_tenant_resource", "review_item", ["tenant_id", "resource_type", "resource_id"]
    )

    op.create_table(
        "approval_request",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(128), nullable=False),
        sa.Column("resource_id", sa.Uuid()),
        sa.Column("requester_principal_id", sa.Uuid(), nullable=False),
        sa.Column("approver_principal_id", sa.Uuid()),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requester_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="RESTRICT",
            name="fk_approval_request_requester",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approver_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="SET NULL",
            name="fk_approval_request_approver",
        ),
    )
    op.create_index("ix_approval_request_tenant_status", "approval_request", ["tenant_id", "status"])
    op.create_index(
        "ix_approval_request_requester",
        "approval_request",
        ["tenant_id", "requester_principal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_approval_request_requester", table_name="approval_request")
    op.drop_index("ix_approval_request_tenant_status", table_name="approval_request")
    op.drop_table("approval_request")
    op.drop_index("ix_review_item_tenant_resource", table_name="review_item")
    op.drop_index("ix_review_item_review_verdict", table_name="review_item")
    op.drop_table("review_item")
    op.drop_index("ix_access_review_tenant_status", table_name="access_review")
    op.drop_table("access_review")