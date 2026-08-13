"""Provider targets are deterministic and isolated from user-controlled keys."""

from uuid import uuid4

import pytest

from s3mp.storage.domain.policy import StoragePolicyError, derive_provider_target


def test_same_relative_key_in_different_tenants_has_distinct_provider_key() -> None:
    space = uuid4()
    first = derive_provider_target(
        tenant_id=uuid4(), storage_space_id=space, bucket="s3mp-dev", relative_key="team/report.csv"
    )
    second = derive_provider_target(
        tenant_id=uuid4(), storage_space_id=space, bucket="s3mp-dev", relative_key="team/report.csv"
    )

    assert first.bucket == second.bucket == "s3mp-dev"
    assert first.key != second.key
    assert first.key.endswith("/team/report.csv")


@pytest.mark.parametrize(
    "prefix", ["../escape", "team//reports", "team/../private", "team\\private"]
)
def test_operator_prefix_cannot_escape_server_owned_namespace(prefix: str) -> None:
    with pytest.raises(StoragePolicyError):
        derive_provider_target(
            tenant_id=uuid4(),
            storage_space_id=uuid4(),
            bucket="s3mp-dev",
            relative_key="report.csv",
            operator_prefix=prefix,
        )
