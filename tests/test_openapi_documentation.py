"""Regression checks for runtime OpenAPI Chinese documentation."""

from s3mp.common.openapi_documentation import document_openapi


def test_explicit_field_descriptions_are_not_replaced_by_generic_text() -> None:
    schema = {
        "components": {
            "schemas": {
                "Example": {
                    "type": "object",
                    "properties": {
                        "storage_namespace": {
                            "type": "string",
                            "description": "应用不可变的共享 Bucket 命名空间。",
                        },
                        "profile_version": {"type": "integer"},
                    },
                }
            }
        }
    }

    documented = document_openapi(schema)
    properties = documented["components"]["schemas"]["Example"]["properties"]
    assert properties["storage_namespace"]["description"] == "应用不可变的共享 Bucket 命名空间。"
    assert (
        properties["profile_version"]["description"]
        == "“profile_version”字段；具体取值和约束见当前资源说明。"
    )


def test_shared_storage_contract_components_are_documented_without_secrets() -> None:
    documented = document_openapi({"components": {"schemas": {}}})
    schemas = documented["components"]["schemas"]

    assert schemas["SharedStorageProfile"]["properties"]["path_style"]["type"] == "boolean"
    assert "credential_reference" not in schemas["SharedStorageProfile"]["properties"]
    assert schemas["ApplicationPathGrant"]["properties"]["type"]["enum"] == [
        "storage_space",
        "directory",
    ]
    assert "$ref" in schemas["QuotaReconciliationResult"]["properties"]["items"]["items"]
