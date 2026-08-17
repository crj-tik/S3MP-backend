"""Platform authority is global and cannot be converted into tenant authority."""

from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from s3mp.common.errors import ApiError
from s3mp.platform.application.authorization import PlatformAuthorizer
from s3mp.platform.application.baseline import reconcile_platform_roles
from s3mp.platform.domain.context import PlatformContext
from s3mp.platform.infrastructure.models import PlatformRoleModel


class _ScalarRows:
    def __init__(self, rows: list[PlatformRoleModel]) -> None:
        self._rows = rows

    def all(self) -> list[PlatformRoleModel]:
        return self._rows


class _BaselineSession:
    def __init__(self, roles: list[PlatformRoleModel]) -> None:
        self.roles = roles
        self.added: list[object] = []

    async def scalars(self, _statement: object) -> _ScalarRows:
        return _ScalarRows(self.roles)

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, PlatformRoleModel):
            self.roles.append(value)


def test_platform_authorizer_does_not_treat_tenant_permissions_as_platform_permissions() -> None:
    context = PlatformContext(uuid4(), uuid4(), frozenset({"platform.tenants.manage"}))
    with pytest.raises(ApiError, match="Platform permission denied"):
        PlatformAuthorizer().require(context, "files.read")


def test_platform_authorizer_requires_explicit_platform_permission() -> None:
    context = PlatformContext(uuid4(), uuid4(), frozenset({"platform.tenants.read"}))
    PlatformAuthorizer().require(context, "platform.tenants.read")


async def test_platform_baseline_reconciles_initialized_admin_and_preserves_custom_role() -> None:
    new_database_session = _BaselineSession([])
    await reconcile_platform_roles(cast(AsyncSession, new_database_session))
    seeded_admin = next(
        role for role in new_database_session.roles if role.name == "platform_admin"
    )
    assert "platform.tenants.read" in seeded_admin.permissions

    admin = PlatformRoleModel(
        name="platform_admin", permissions=["platform.tenants.manage"], built_in=True
    )
    custom = PlatformRoleModel(
        name="custom-role", permissions=["platform.custom.only"], built_in=False
    )
    session = _BaselineSession([admin, custom])

    changed = await reconcile_platform_roles(cast(AsyncSession, session))

    assert "platform_admin" in changed
    assert "platform.tenants.read" in admin.permissions
    assert custom.permissions == ["platform.custom.only"]
    PlatformAuthorizer().require(
        PlatformContext(uuid4(), uuid4(), frozenset(admin.permissions)),
        "platform.tenants.read",
    )
    assert any(
        getattr(event, "action", None) == "platform.role_baseline_reconciled"
        for event in session.added
    )

    session.added.clear()
    assert await reconcile_platform_roles(cast(AsyncSession, session)) == set()
    assert session.added == []
