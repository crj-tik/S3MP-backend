"""Authentication provider ports and external subject mapping values."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthenticationRequest:
    """Opaque provider-specific authentication input."""

    credential: str
    redirect_uri: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalSubject:
    """Case-sensitive OIDC issuer + subject mapping key."""

    issuer: str
    subject: str

    def __post_init__(self) -> None:
        if not self.issuer or not self.issuer.strip():
            raise ValueError("issuer must not be empty")
        if not self.subject:
            raise ValueError("subject must not be empty")


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """Normalized successful provider result."""

    issuer: str
    subject: str
    email: str | None = None
    display_name: str | None = None

    @property
    def external_subject(self) -> ExternalSubject:
        return ExternalSubject(self.issuer, self.subject)


class AuthProvider(Protocol):
    async def authenticate(self, request: AuthenticationRequest) -> AuthenticatedIdentity: ...


class OIDCProvider(AuthProvider, Protocol):
    @property
    def issuer(self) -> str: ...

    async def authorization_url(self, state: str, redirect_uri: str) -> str: ...


class ExternalIdentityMapper(Protocol):
    async def find_user_id(self, external_subject: ExternalSubject) -> UUID | None: ...
