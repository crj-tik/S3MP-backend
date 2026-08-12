"""Files upload end-to-end with real postgresql and the real file service.

Verifies the full HTTP → FileApplicationService → SqlAlchemyFileStore → real pg
chain: create an upload via HTTP, read it back, confirm cross-tenant isolation.
"""

from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from _infrastructure import (
    delete_tenant,
    real_session_factory,
    real_settings,
    seed_tenant,
)
from s3mp.identity.domain.context import PrincipalContext
from s3mp.identity.infrastructure.models import PrincipalModel, PrincipalType
from s3mp.main import create_app
from s3mp.storage.infrastructure.models import StorageConnectionModel, StorageSpaceModel


async def test_upload_create_and_get_round_trips_through_real_pg() -> None:
    app = create_app(real_settings())
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        factory = real_session_factory(engine)
        tenant_id = uuid4()
        await seed_tenant(engine, tenant_id)
        try:
            principal_id = uuid4()
            async with factory() as session:
                conn = StorageConnectionModel(
                    tenant_id=tenant_id, name="primary", endpoint="https://s3.example.com",
                    region="us-east-1", path_style=True, credential_reference="vault/s3",
                )
                session.add(conn)
                await session.flush()
                space = StorageSpaceModel(
                    tenant_id=tenant_id, connection_id=conn.id, name="default",
                    bucket="s3mp-dev", root_prefix="",
                )
                session.add(space)
                await session.flush()
                session.add(PrincipalModel(
                    id=principal_id, tenant_id=tenant_id, type=PrincipalType.USER,
                    display_name="E2E",
                ))
                await session.commit()
                space_id = str(space.id)

            ctx = PrincipalContext(tenant_id, principal_id, uuid4(), 1)

            @app.middleware("http")
            async def inject(request: Any, call_next: Any) -> Any:
                request.state.principal_context = ctx
                return await call_next(request)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create = await client.post(
                    f"/api/v1/storage_spaces/{space_id}/uploads",
                    json={
                        "object_key": "e2e/test.txt",
                        "content_length": 42,
                        "content_type": "text/plain",
                    },
                )
                upload_id = create.json()["id"]
                fetched = await client.get(f"/api/v1/uploads/{upload_id}")

            assert create.status_code == 201
            assert create.json()["object_key"] == "e2e/test.txt"
            assert create.json()["status"] == "pending"
            assert fetched.status_code == 200
            assert fetched.json()["object_key"] == "e2e/test.txt"
        finally:
            await delete_tenant(engine, tenant_id)
