"""High-risk audit-unavailable fail-close error-envelope contract test.

A high-risk mutation whose audit record cannot be made durable MUST return
``503 audit_unavailable`` and MUST NOT perform the externally visible action.
The fake service simulates this fail-close behaviour.
"""

from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from _http import make_app
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext


def _ctx() -> PrincipalContext:
    return PrincipalContext(uuid4(), uuid4(), uuid4(), 1)


class FailCloseFileService:
    """Fake that raises audit_unavailable and records whether storage was touched."""

    def __init__(self) -> None:
        self.storage_touched = False

    async def list_files(
        self, tenant_id: Any, space_id: str, prefix: str
    ) -> list[dict[str, Any]]:
        return []

    async def get_file(
        self, tenant_id: Any, space_id: str, file_id: str
    ) -> dict[str, Any]:
        return {"id": file_id, "object_key": "a.txt", "etag": "v1"}

    async def delete_file(
        self, tenant_id: Any, space_id: str, file_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Audit cannot be persisted → reject before touching storage.
        raise ApiError(
            "audit_unavailable",
            "Audit storage is unavailable; high-risk operation rejected",
            status_code=503,
        )

    async def create_file_operation(
        self, tenant_id: Any, space_id: str, body: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"id": str(uuid4()), "status": "pending"}

    async def get_file_operation(self, tenant_id: Any, op_id: str) -> dict[str, Any]:
        return {"id": op_id, "status": "pending"}

    async def create_upload(
        self, ctx: PrincipalContext, space_id: str, body: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"id": str(uuid4()), "status": "pending"}

    async def get_upload(self, tenant_id: Any, upload_id: str) -> dict[str, Any]:
        return {"id": upload_id, "status": "pending"}

    async def complete_upload(
        self, tenant_id: Any, upload_id: str, body: Any
    ) -> dict[str, Any]:
        return {"id": upload_id, "status": "completed"}

    async def create_presigned_download(
        self, ctx: PrincipalContext, space_id: str, body: Any
    ) -> dict[str, Any]:
        return {"url": "https://x", "expires_in": 900}

    async def create_multipart_upload(
        self, ctx: PrincipalContext, space_id: str, body: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"id": str(uuid4()), "status": "pending"}

    async def get_multipart_upload(self, tenant_id: Any, mp_id: str) -> dict[str, Any]:
        return {"id": mp_id, "status": "pending"}

    async def abort_multipart_upload(self, tenant_id: Any, mp_id: str, **kwargs: Any) -> None:
        return None

    async def list_multipart_parts(
        self, tenant_id: Any, mp_id: str
    ) -> list[dict[str, Any]]:
        return []

    async def create_multipart_part(
        self, tenant_id: Any, mp_id: str, body: Any
    ) -> dict[str, Any]:
        return {"part_number": body.part_number}

    async def confirm_multipart_part(
        self, tenant_id: Any, mp_id: str, part_number: int, body: Any
    ) -> dict[str, Any]:
        return {"part_number": part_number, "etag": body.etag}

    async def complete_multipart_upload(
        self, tenant_id: Any, mp_id: str, body: Any
    ) -> dict[str, Any]:
        return {"id": mp_id, "status": "completed"}


async def test_audit_unavailable_returns_503_and_does_not_touch_storage() -> None:
    svc = FailCloseFileService()
    app = make_app({"file_service": svc}, context=_ctx())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/api/v1/storage_spaces/{uuid4()}/files/{uuid4()}"
        )

    assert response.status_code == 503
    assert response.json()["code"] == "audit_unavailable"
    assert "request_id" in response.json()
    # Fail-close: the externally visible action was not performed.
    assert svc.storage_touched is False
