"""Legacy migration fixtures and planning safety tests."""

from uuid import uuid4

from s3mp.files.application.provider_migration import classify_legacy_target


def _space(tenant_id, space_id, *, bucket="s3mp-dev", root_prefix="legacy"):
    return {"id": str(space_id), "tenant_id": str(tenant_id), "bucket": bucket, "root_prefix": root_prefix}


def test_legacy_ingestion_with_proven_relative_key_is_ready_for_verified_copy() -> None:
    tenant_id, space_id, record_id = uuid4(), uuid4(), uuid4()
    plan = classify_legacy_target(
        record_type="ingestion", record_id=record_id, tenant_id=tenant_id,
        storage_space=_space(tenant_id, space_id), source_bucket="s3mp-dev",
        source_key="legacy/report.csv", relative_key="report.csv", overlapping_space_ids=set(),
    )
    assert plan.state == "ready_for_verified_copy"
    assert plan.target_fingerprint is not None
    assert "report.csv" not in plan.target_fingerprint


def test_overlapping_legacy_roots_are_quarantined_for_every_fixture_kind() -> None:
    tenant_id, space_id = uuid4(), uuid4()
    for record_type in ("file_object", "upload_session", "multipart_session", "ingestion", "file_operation"):
        plan = classify_legacy_target(
            record_type=record_type, record_id=uuid4(), tenant_id=tenant_id,
            storage_space=_space(tenant_id, space_id), source_bucket="s3mp-dev",
            source_key="legacy/a.txt", relative_key="a.txt", overlapping_space_ids={space_id},
        )
        assert (plan.state, plan.reason) == ("quarantined", "overlapping_legacy_root")


def test_legacy_file_without_proven_relative_key_requires_review() -> None:
    tenant_id, space_id = uuid4(), uuid4()
    plan = classify_legacy_target(
        record_type="file_object", record_id=uuid4(), tenant_id=tenant_id,
        storage_space=_space(tenant_id, space_id), source_bucket=None,
        source_key="legacy/a.txt", relative_key=None, overlapping_space_ids=set(),
    )
    assert (plan.state, plan.reason, plan.target_fingerprint) == (
        "pending_review", "relative_key_not_proven", None
    )


def test_conflicting_tenant_or_bucket_never_receives_a_target() -> None:
    tenant_id, space_id = uuid4(), uuid4()
    plan = classify_legacy_target(
        record_type="ingestion", record_id=uuid4(), tenant_id=tenant_id,
        storage_space=_space(tenant_id, space_id), source_bucket="other-bucket",
        source_key="legacy/a.txt", relative_key="a.txt", overlapping_space_ids=set(),
    )
    assert (plan.state, plan.reason, plan.target_fingerprint) == (
        "quarantined", "source_bucket_mismatch", None
    )
