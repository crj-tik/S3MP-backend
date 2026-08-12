from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from s3mp.authorization.domain.delegation import (
    DelegationScope,
    validate_delegated_scope,
    validate_direct_grant,
)


def test_direct_grant_requires_reason_expiry_and_separation() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    validate_direct_grant(
        actor_principal_id=uuid4(),
        target_principal_id=uuid4(),
        permission="files.read",
        reason="temporary project access",
        expires_at=now + timedelta(hours=1),
        now=now,
    )
    with pytest.raises(ValueError):
        validate_direct_grant(
            actor_principal_id=uuid4(),
            target_principal_id=uuid4(),
            permission="files.read",
            reason=" ",
            expires_at=now + timedelta(hours=1),
            now=now,
        )


def test_delegation_must_be_a_permission_and_scope_subset() -> None:
    delegator = DelegationScope(frozenset({"files.read", "files.list"}), "team")
    validate_delegated_scope(DelegationScope(frozenset({"files.read"}), "team/reports"), delegator)

    with pytest.raises(ValueError):
        validate_delegated_scope(DelegationScope(frozenset({"files.write"}), "team"), delegator)
    with pytest.raises(ValueError):
        validate_delegated_scope(DelegationScope(frozenset({"files.read"}), "other"), delegator)


def test_self_grant_is_rejected_for_separation_of_duties() -> None:
    principal_id = uuid4()
    with pytest.raises(ValueError):
        validate_direct_grant(
            actor_principal_id=principal_id,
            target_principal_id=principal_id,
            permission="files.read",
            reason="self grant",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
