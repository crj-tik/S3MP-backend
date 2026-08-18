from s3mp.governance.application.quota_reconciliation import (
    ReconciliationDifference,
    ReconciliationFile,
    ReconciliationObject,
    compare_inventory,
)


def test_compare_inventory_classifies_provider_and_size_drift() -> None:
    results = compare_inventory(
        [
            ReconciliationFile("tenant/app/a.txt", "tenant", "app", "space", 4),
            ReconciliationFile("tenant/app/absent.txt", "tenant", "app", "space", 8),
        ],
        [
            ReconciliationObject("tenant/app/a.txt", 5),
            ReconciliationObject("tenant/app/missing.txt", 3),
            ReconciliationObject("unknown/orphan.txt", 2),
        ],
        known_namespace_prefixes=("tenant/app/",),
    )
    assert [(item.kind, item.physical_key) for item in results] == [
        (ReconciliationDifference.SIZE_MISMATCH, "tenant/app/a.txt"),
        (ReconciliationDifference.PROVIDER_MISSING, "tenant/app/absent.txt"),
        (ReconciliationDifference.DB_MISSING, "tenant/app/missing.txt"),
        (ReconciliationDifference.ORPHAN_OBJECT, "unknown/orphan.txt"),
    ]


def test_compare_inventory_marks_duplicate_database_mapping() -> None:
    results = compare_inventory(
        [
            ReconciliationFile("same/key", "tenant-a", "app-a", "space-a", 1),
            ReconciliationFile("same/key", "tenant-b", "app-b", "space-b", 1),
        ],
        [ReconciliationObject("same/key", 1)],
    )
    assert results[0].kind is ReconciliationDifference.DUPLICATE_MAPPING


def test_compare_inventory_keeps_namespaces_isolated_and_redacts_keys_in_reports() -> None:
    results = compare_inventory(
        [ReconciliationFile("tenant-a/app/a.txt", "tenant-a", "app-a", "space-a", 4)],
        [
            ReconciliationObject("tenant-a/app/a.txt", 4),
            ReconciliationObject("tenant-b/app/a.txt", 4),
        ],
        known_namespace_prefixes=("tenant-a/app/",),
    )
    assert [item.kind for item in results] == [
        ReconciliationDifference.MATCHED,
        ReconciliationDifference.ORPHAN_OBJECT,
    ]
    assert all("access_key" not in item.physical_key for item in results)
