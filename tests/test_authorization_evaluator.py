from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from s3mp.authorization.domain.evaluator import (
    Binding,
    Decision,
    evaluate,
    validate_canonical_prefix,
)
from s3mp.files.application.authorized_command import AuthorizedFileCommand
from s3mp.identity.domain.context import PrincipalContext


def binding(permission: str, effect: Decision, prefix: str | None = None) -> Binding:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Binding(
        uuid4(),
        permission,
        effect,
        prefix,
        now - timedelta(minutes=1),
        now + timedelta(hours=1),
        "test",
    )


def test_evaluator_inherits_parent_prefix_and_combines_allows() -> None:
    decision = evaluate(
        "files.read",
        [
            binding("files.read", Decision.ALLOW, "team"),
            binding("files.read", Decision.ALLOW, "team/reports"),
        ],
        object_key="team/reports/january.csv",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert decision.decision == Decision.ALLOW
    assert len(decision.sources) == 2


def test_explicit_deny_wins_and_default_is_deny() -> None:
    denied = evaluate(
        "files.read",
        [
            binding("files.read", Decision.ALLOW, "team"),
            binding("files.read", Decision.DENY, "team/private"),
        ],
        object_key="team/private/a.txt",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    default = evaluate("files.read", [], object_key="team/a.txt")

    assert denied.reason_code == "explicit_deny"
    assert default.decision == Decision.DENY
    assert default.reason_code == "default_deny"


def test_storage_space_scoped_binding_does_not_match_another_space() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    allowed_space, other_space = uuid4(), uuid4()
    scoped = Binding(
        uuid4(),
        "files.read",
        Decision.ALLOW,
        "docs",
        now - timedelta(minutes=1),
        now + timedelta(hours=1),
        "test",
        allowed_space,
    )

    assert (
        evaluate(
            "files.read", [scoped], storage_space_id=allowed_space, object_key="docs/a.txt", now=now
        ).decision
        == Decision.ALLOW
    )
    assert (
        evaluate(
            "files.read", [scoped], storage_space_id=other_space, object_key="docs/a.txt", now=now
        ).decision
        == Decision.DENY
    )


def test_expired_binding_and_unlisted_platform_permission_are_denied() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    expired = Binding(
        uuid4(), "files.read", Decision.ALLOW, "team", now - timedelta(hours=2), now, "expired"
    )

    expired_result = evaluate("files.read", [expired], object_key="team/a.txt", now=now)
    platform_result = evaluate("files.read", [], object_key="team/a.txt", now=now)

    assert expired_result.reason_code == "default_deny"
    assert platform_result.reason_code == "default_deny"


@pytest.mark.parametrize(
    "prefix", ["/team", "team//reports", "team/../private", "team\\private", "team%2Fprivate"]
)
def test_canonical_prefix_rejects_ambiguous_paths(prefix: str) -> None:
    with pytest.raises(ValueError):
        validate_canonical_prefix(prefix)


def test_authorized_command_evidence_is_json_serializable() -> None:
    tenant_id, principal_id, space_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    active_binding = Binding(
        uuid4(),
        "files.read",
        Decision.ALLOW,
        "docs",
        now - timedelta(minutes=1),
        now + timedelta(hours=1),
        "test",
    )
    command = AuthorizedFileCommand.create(
        PrincipalContext(tenant_id, principal_id, uuid4(), 1),
        {"id": str(space_id), "bucket": "s3mp-dev", "root_prefix": "tenant"},
        "docs/readme.txt",
        "files.read",
        [active_binding],
    )
    import json

    assert json.loads(json.dumps(command.authorization_evidence))["decision"] == "allow"
