"""Tenant-safe identity repository ports."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from s3mp.identity.domain.context import PrincipalContext
from s3mp.identity.domain.entities import Membership, Principal, Session


class IdentityRepository(Protocol):
    async def get_principal(
        self, context: PrincipalContext, principal_id: UUID
    ) -> Principal | None: ...

    async def get_membership(
        self, context: PrincipalContext, membership_id: UUID
    ) -> Membership | None: ...

    async def list_memberships(self, context: PrincipalContext) -> Sequence[Membership]: ...

    async def get_session(self, context: PrincipalContext, session_id: UUID) -> Session | None: ...
