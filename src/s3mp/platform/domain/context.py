"""Global account context, deliberately distinct from a tenant PrincipalContext."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PlatformContext:
    user_id: UUID
    session_id: UUID
    permissions: frozenset[str]
