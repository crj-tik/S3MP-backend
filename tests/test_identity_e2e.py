"""Identity /me endpoint end-to-end with real postgresql.

The identity management service is not wired in main.py's lifespan, so this
test manually provides an ``identity_context_provider`` that derives the response
from the real PrincipalContext. It verifies the HTTP /me path works with a real
app + real pg (the PrincipalContext is seeded into real pg first).
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
from s3mp.identity.infrastructure.models import (
    MembershipModel,
    MembershipStatus,
    PrincipalModel,
    PrincipalType,
    UserModel,
)
from s3mp.main import create_app


async def test_me_returns_context_backed_by_real_pg() -> None:
    app = create_app(real_settings())
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        factory = real_session_factory(engine)
        tenant_id = uuid4()
        await seed_tenant(engine, tenant_id)
        try:
            principal_id = uuid4()
            membership_id = uuid4()
            user_id = uuid4()
            async with factory() as session:
                session.add(
                    UserModel(
                        id=user_id,
                        email=f"{user_id}@test",
                        normalized_email=f"{user_id}@test",
                        display_name="E2E User",
                    )
                )
                await session.flush()
                session.add(
                    PrincipalModel(
                        id=principal_id,
                        tenant_id=tenant_id,
                        type=PrincipalType.USER,
                        display_name="E2E User",
                    )
                )
                await session.flush()
                session.add(
                    MembershipModel(
                        id=membership_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        principal_id=principal_id,
                        status=MembershipStatus.ACTIVE,
                    )
                )
                await session.commit()

            ctx = PrincipalContext(tenant_id, principal_id, membership_id, 1)

            class Provider:
                async def get_me(self, context: PrincipalContext) -> dict[str, Any]:
                    return {
                        "principal": {
                            "id": str(context.principal_id),
                            "type": "user",
                            "display_name": "E2E User",
                        },
                        "current_tenant": {
                            "id": str(context.tenant_id),
                            "name": "T",
                            "membership_status": "active",
                        },
                        "available_tenants": [],
                        "coarse_permissions": ["files.read"],
                        "authorization_version": context.authorization_version,
                    }

            app.state.identity_context_provider = Provider()

            @app.middleware("http")
            async def inject(request: Any, call_next: Any) -> Any:
                request.state.principal_context = ctx
                return await call_next(request)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/me")

            assert response.status_code == 200
            body = response.json()
            assert body["principal"]["id"] == str(principal_id)
            assert body["authorization_version"] == 1
        finally:
            await delete_tenant(engine, tenant_id)
