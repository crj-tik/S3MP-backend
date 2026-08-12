from datetime import UTC, datetime
from uuid import uuid4

from s3mp.authorization.application.explain import explain_permissions, simulate
from s3mp.authorization.domain.evaluator import Binding, Decision


def test_effective_permissions_are_sorted_and_include_stable_sources() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    permissions = explain_permissions(
        uuid4(),
        ["files.write", "files.read", "files.read"],
        [Binding(uuid4(), "files.read", Decision.ALLOW, "team", now, now.replace(year=2027), "r")],
        authorization_version=4,
        object_key="team/a.txt",
        now=now,
    )

    assert [item.permission for item in permissions.permissions] == ["files.read", "files.write"]
    assert permissions.permissions[0].reason_code == "binding_allow"
    assert permissions.permissions[1].reason_code == "default_deny"


def test_simulation_does_not_mutate_bindings() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    bindings = [
        Binding(uuid4(), "files.read", Decision.DENY, None, now, now.replace(year=2027), "r")
    ]
    result = simulate("files.read", bindings, authorization_version=2, now=now)

    assert result["decision"] == Decision.DENY
    assert result["reason_code"] == "explicit_deny"
    assert len(bindings) == 1
