"""Platform authority is global and cannot be converted into tenant authority."""

from uuid import uuid4

import pytest

from s3mp.common.errors import ApiError
from s3mp.platform.application.authorization import PlatformAuthorizer
from s3mp.platform.domain.context import PlatformContext


def test_platform_authorizer_does_not_treat_tenant_permissions_as_platform_permissions() -> None:
    context = PlatformContext(uuid4(), uuid4(), frozenset({"platform.tenants.manage"}))
    with pytest.raises(ApiError, match="Platform permission denied"):
        PlatformAuthorizer().require(context, "files.read")


def test_platform_authorizer_requires_explicit_platform_permission() -> None:
    context = PlatformContext(uuid4(), uuid4(), frozenset({"platform.tenants.read"}))
    PlatformAuthorizer().require(context, "platform.tenants.read")
