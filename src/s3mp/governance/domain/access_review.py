"""Access review lifecycle: schedules, items, findings and approval requests."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class ReviewStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReviewItemVerdict(StrEnum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REVOKED = "revoked"
    IGNORED = "ignored"


class ApprovalRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class AccessReview:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    status: ReviewStatus = ReviewStatus.PENDING
    created_by_principal_id: UUID | None = None
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = datetime.now(UTC)

    def start(self) -> "AccessReview":
        if self.status is not ReviewStatus.PENDING:
            raise ValueError("only pending reviews can be started")
        return replace(self, status=ReviewStatus.IN_PROGRESS)

    def complete(self) -> "AccessReview":
        if self.status is not ReviewStatus.IN_PROGRESS:
            raise ValueError("only in-progress reviews can be completed")
        return replace(self, status=ReviewStatus.COMPLETED, completed_at=datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """A single entity under review: a direct binding, group membership, application, or stale grant."""

    id: UUID
    review_id: UUID
    tenant_id: UUID
    resource_type: str  # role_binding, group_membership, application, api_key
    resource_id: UUID
    summary: str
    verdict: ReviewItemVerdict = ReviewItemVerdict.UNREVIEWED
    reviewer_principal_id: UUID | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = datetime.now(UTC)

    def record_verdict(
        self, verdict: ReviewItemVerdict, reviewer_principal_id: UUID
    ) -> "ReviewItem":
        if self.verdict is not ReviewItemVerdict.UNREVIEWED:
            raise ValueError("item already reviewed")
        if verdict is ReviewItemVerdict.UNREVIEWED:
            raise ValueError("must provide a concrete verdict")
        return replace(
            self,
            verdict=verdict,
            reviewer_principal_id=reviewer_principal_id,
            reviewed_at=datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """Approval workflow for sensitive actions like granting high-risk permissions."""

    id: UUID
    tenant_id: UUID
    action: str
    resource_type: str
    resource_id: UUID | None
    requester_principal_id: UUID
    approver_principal_id: UUID | None
    status: ApprovalRequestStatus = ApprovalRequestStatus.PENDING
    reason: str | None = None
    expires_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime = datetime.now(UTC)

    def approve(self, approver_principal_id: UUID) -> "ApprovalRequest":
        if self.status is not ApprovalRequestStatus.PENDING:
            raise ValueError("only pending requests can be approved")
        if self.expires_at is not None and datetime.now(UTC) > self.expires_at:
            raise ValueError("approval request has expired")
        return replace(
            self,
            status=ApprovalRequestStatus.APPROVED,
            approver_principal_id=approver_principal_id,
            resolved_at=datetime.now(UTC),
        )

    def deny(self, approver_principal_id: UUID) -> "ApprovalRequest":
        if self.status is not ApprovalRequestStatus.PENDING:
            raise ValueError("only pending requests can be denied")
        return replace(
            self,
            status=ApprovalRequestStatus.DENIED,
            approver_principal_id=approver_principal_id,
            resolved_at=datetime.now(UTC),
        )