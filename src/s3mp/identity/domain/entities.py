"""Persistence-independent identity projections."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Principal:
    id: UUID
    tenant_id: UUID
    type: str
    display_name: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class Membership:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    principal_id: UUID
    status: str
    authorization_version: int
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class Session:
    id: UUID
    tenant_id: UUID
    membership_id: UUID
    principal_id: UUID
    authorization_version: int
    expires_at: datetime
    revoked_at: datetime | None
