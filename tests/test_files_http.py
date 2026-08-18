"""HTTP contract tests for the files router (fake-service injection)."""

from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from _http import make_app
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext


def _ctx() -> PrincipalContext:
    return PrincipalContext(uuid4(), uuid4(), uuid4(), 1)


class FakeFileService:
    def __init__(self, *, cross_tenant_file: bool = False) -> None:
        self.cross_tenant_file = cross_tenant_file

    async def list_files(
        self, tenant_id: Any, space_id: str, prefix: str, status: Any = None
    ) -> list[dict[str, Any]]:
        return [{"id": str(uuid4()), "object_key": "docs/readme.txt", "etag": "abc"}]

    async def get_file(self, tenant_id: Any, space_id: str, file_id: str) -> dict[str, Any]:
        if self.cross_tenant_file:
            raise ApiError("resource_not_found", "File not found", status_code=404)
        return {"id": file_id, "object_key": "docs/readme.txt", "etag": "abc"}

    async def delete_file(
        self,
        tenant_id: Any,
        space_id: str,
        file_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"id": file_id, "status": "deleted"}

    async def create_file_operation(
        self,
        tenant_id: Any,
        space_id: str,
        body: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"id": str(uuid4()), "operation_type": body.operation_type, "status": "pending"}

    async def get_file_operation(self, tenant_id: Any, operation_id: str) -> dict[str, Any]:
        return {"id": operation_id, "status": "pending"}

    async def create_direct_upload(
        self,
        ctx: PrincipalContext,
        space_id: str,
        body: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "id": str(uuid4()),
            "object_key": body.object_key,
            "status": "pending",
            "content_length": body.content_length,
            "content_type": body.content_type,
            "mode": "direct",
            "method": "PUT",
            "url": "https://s3.example.com/upload",
            "headers": {"Content-Type": body.content_type},
        }

    async def get_direct_upload(self, ctx: PrincipalContext, upload_id: str) -> dict[str, Any]:
        return {
            "id": upload_id,
            "status": "pending",
            "mode": "direct",
            "method": "PUT",
            "url": "https://s3.example.com/upload",
            "headers": {"Content-Type": "text/plain"},
        }

    async def complete_direct_upload(
        self, ctx: PrincipalContext, upload_id: str, body: Any, **kwargs: Any
    ) -> dict[str, Any]:
        return {"id": upload_id, "status": "completed", "etag": "abc"}

    async def create_presigned_download(
        self, ctx: PrincipalContext, space_id: str, body: Any
    ) -> dict[str, Any]:
        return {"url": "https://s3.example.com/presigned", "expires_in": body.ttl_seconds}

    async def create_multipart_upload(
        self,
        ctx: PrincipalContext,
        space_id: str,
        body: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"id": str(uuid4()), "object_key": body.object_key, "status": "pending"}

    async def get_multipart_upload(self, tenant_id: Any, multipart_id: str) -> dict[str, Any]:
        return {"id": multipart_id, "status": "pending"}

    async def abort_multipart_upload(
        self, tenant_id: Any, multipart_id: str, **kwargs: Any
    ) -> None:
        return None

    async def list_multipart_parts(self, tenant_id: Any, multipart_id: str) -> list[dict[str, Any]]:
        return [{"part_number": 1, "etag": "p1", "content_length": 100}]

    async def upload_multipart_part(
        self,
        ctx: PrincipalContext,
        multipart_id: str,
        part_number: int,
        body: bytes,
        content_length: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "id": str(uuid4()),
            "part_number": part_number,
            "etag": "part-1",
            "content_length": content_length,
        }

    async def complete_multipart_upload(
        self, tenant_id: Any, multipart_id: str, body: Any, **kwargs: Any
    ) -> dict[str, Any]:
        return {"id": multipart_id, "status": "completed"}


def _app(cross_tenant: bool = False) -> Any:
    return make_app(
        {"file_service": FakeFileService(cross_tenant_file=cross_tenant)}, context=_ctx()
    )


async def test_list_files_returns_200() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/storage_spaces/{uuid4()}/files")

    assert response.status_code == 200
    assert response.json()[0]["etag"] == "abc"


async def test_create_direct_upload_returns_201() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/storage_spaces/{uuid4()}/direct_uploads",
            json={
                "object_key": "docs/readme.txt",
                "content_length": 100,
                "content_type": "text/plain",
            },
            headers={"Idempotency-Key": "upload-create-1"},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["mode"] == "direct"
    assert response.json()["url"].startswith("https://")


async def test_create_file_operation_returns_202() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/storage_spaces/{uuid4()}/file_operations",
            json={"operation_type": "copy", "source_key": "a.txt", "destination_key": "b.txt"},
            headers={"Idempotency-Key": "operation-create-1"},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "pending"


async def test_other_tenant_member_cannot_read_operation_metadata() -> None:
    class DenyingOperationService(FakeFileService):
        async def get_file_operation(
            self, ctx: PrincipalContext, operation_id: str
        ) -> dict[str, Any]:
            raise ApiError("permission_denied", "Delegated access is required", status_code=403)

    app = make_app({"file_service": DenyingOperationService()}, context=_ctx())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/file_operations/{uuid4()}")

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert "id" not in response.json()


async def test_operation_http_response_has_no_internal_fields() -> None:
    class RedactedOperationService(FakeFileService):
        async def get_file_operation(
            self, ctx: PrincipalContext, operation_id: str
        ) -> dict[str, Any]:
            # This mirrors the application-service public projection boundary.
            return {"id": operation_id, "operation_type": "copy", "status": "pending"}

    app = make_app({"file_service": RedactedOperationService()}, context=_ctx())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/file_operations/{uuid4()}")

    assert response.status_code == 200
    assert not {
        "tenant_id",
        "principal_id",
        "membership_id",
        "storage_space_id",
        "provider_target_version",
        "authorization_version",
        "authorization_evidence",
        "lease_owner",
        "lease_expires_at",
    }.intersection(response.json())


async def test_complete_direct_upload_returns_etag() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/direct_uploads/{uuid4()}/completion",
            json={"checksum": "sha256:abc"},
            headers={"Idempotency-Key": "upload-complete-1"},
        )

    assert response.status_code == 200
    assert response.json()["etag"] == "abc"


async def test_unauthenticated_request_returns_401() -> None:
    app = make_app({"file_service": FakeFileService()})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/storage_spaces/{uuid4()}/files")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


async def test_cross_tenant_file_returns_404_without_leaking() -> None:
    app = _app(cross_tenant=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/storage_spaces/{uuid4()}/files/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"
    assert "id" not in response.json()


async def test_etag_mismatch_returns_412() -> None:
    # The fake simulates a stale If-Match conflict to verify the error envelope.
    # NOTE: the files router receives If-Match but does not forward it to the
    # service, so ETag enforcement is not wired at the router layer today.
    from s3mp.common.errors import ApiError

    class EtagConflictFileService(FakeFileService):
        async def delete_file(
            self,
            tenant_id: Any,
            space_id: str,
            file_id: str,
            **kwargs: Any,
        ) -> dict[str, Any]:
            raise ApiError(
                "etag_mismatch",
                "If-Match does not identify the current resource version",
                status_code=412,
            )

    app = make_app({"file_service": EtagConflictFileService()}, context=_ctx())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/api/v1/storage_spaces/{uuid4()}/files/{uuid4()}",
            headers={"If-Match": '"stale-etag"', "Idempotency-Key": "file-delete-1"},
        )

    assert response.status_code == 412
    assert response.json()["code"] == "etag_mismatch"


async def test_multipart_part_upload_forwards_idempotency_key() -> None:
    class CapturingService(FakeFileService):
        key: str | None = None

        async def upload_multipart_part(
            self,
            ctx: PrincipalContext,
            multipart_id: str,
            part_number: int,
            body: bytes,
            content_length: int,
            **kwargs: Any,
        ) -> dict[str, Any]:
            self.key = kwargs.get("idempotency_key")
            return {
                "id": str(uuid4()),
                "part_number": part_number,
                "etag": "part-1",
                "content_length": content_length,
            }

    service = CapturingService()
    app = make_app({"file_service": service}, context=_ctx())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/multipart_uploads/{uuid4()}/parts/1",
            content=b"x",
            headers={"Idempotency-Key": "part-confirm-1"},
        )

    assert response.status_code == 200
    assert service.key == "part-confirm-1"


async def test_file_mutation_rejects_missing_idempotency_key_before_service() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/storage_spaces/{uuid4()}/direct_uploads",
            json={
                "object_key": "docs/readme.txt",
                "content_length": 100,
                "content_type": "text/plain",
            },
        )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_idempotency_key"
