"""Platform-only authorization evaluation."""

from dataclasses import dataclass

from s3mp.common.errors import ApiError
from s3mp.platform.domain.context import PlatformContext


@dataclass(frozen=True, slots=True)
class PlatformAuthorizer:
    """Evaluate authority without consulting tenant memberships or bindings."""

    def require(self, context: PlatformContext, permission: str) -> None:
        if permission not in context.permissions:
            raise ApiError("permission_denied", "Platform permission denied", status_code=403)
