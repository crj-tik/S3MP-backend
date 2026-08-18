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


def test_evaluator_normalizes_naive_persisted_binding_timestamps() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    persisted_binding = Binding(
        uuid4(),
        "files.read",
        Decision.ALLOW,
        "team",
        (now - timedelta(minutes=1)).replace(tzinfo=None),
        (now + timedelta(hours=1)).replace(tzinfo=None),
        "legacy-naive-timestamps",
    )

    assert (
        evaluate("files.read", [persisted_binding], object_key="team/a.txt", now=now).decision
        == Decision.ALLOW
    )


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


def test_group_derived_allow_is_scoped_to_the_bound_application_space() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    application_space, other_application_space = uuid4(), uuid4()
    group_allow = Binding(
        uuid4(),
        "files.read",
        Decision.ALLOW,
        "reports",
        now - timedelta(minutes=1),
        now + timedelta(hours=1),
        "group grant",
        application_space,
    )

    assert evaluate(
        "files.read",
        [group_allow],
        storage_space_id=application_space,
        object_key="reports/a.csv",
        now=now,
    ).decision == Decision.ALLOW
    assert evaluate(
        "files.read",
        [group_allow],
        storage_space_id=other_application_space,
        object_key="reports/a.csv",
        now=now,
    ).decision == Decision.DENY


def test_application_grant_cannot_cross_a_namespace_prefix_boundary() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    app_space = uuid4()
    grant = binding("files.write", Decision.ALLOW, "reports")
    scoped = Binding(
        grant.id,
        grant.permission,
        grant.effect,
        grant.canonical_prefix,
        grant.starts_at,
        grant.expires_at,
        "application grant",
        app_space,
    )

    assert evaluate(
        "files.write", [scoped], storage_space_id=app_space, object_key="reports/a.txt", now=now
    ).decision == Decision.ALLOW
    assert evaluate(
        "files.write",
        [scoped],
        storage_space_id=app_space,
        object_key="reports-private/a.txt",
        now=now,
    ).decision == Decision.DENY


def test_deny_from_application_path_binding_overrides_direct_allow() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    space_id = uuid4()
    allow = Binding(
        uuid4(),
        "files.delete",
        Decision.ALLOW,
        "reports",
        now - timedelta(minutes=1),
        now + timedelta(hours=1),
        "direct user grant",
        space_id,
    )
    deny = Binding(
        uuid4(),
        "files.delete",
        Decision.DENY,
        "reports/locked",
        now - timedelta(minutes=1),
        now + timedelta(hours=1),
        "application deny",
        space_id,
    )

    result = evaluate(
        "files.delete",
        [allow, deny],
        storage_space_id=space_id,
        object_key="reports/locked/a.txt",
        now=now,
    )
    assert result.decision == Decision.DENY
    assert result.reason_code == "explicit_deny"
