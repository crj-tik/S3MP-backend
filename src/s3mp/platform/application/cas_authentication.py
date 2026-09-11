"""CAS redirect, ticket validation, and Session-service identity verification."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit

import httpx
from defusedxml import ElementTree as ET  # type: ignore[import-untyped]
from redis.asyncio import Redis

from s3mp.common.config import Settings
from s3mp.common.logging import REDACTED, log_event

logger = logging.getLogger(__name__)
_BUSINESS_TOKEN_ELEMENT = re.compile(
    r"(<(?:[A-Za-z0-9_-]+:)?businessToken(?:\s[^>]*)?>).*?(</(?:[A-Za-z0-9_-]+:)?businessToken>)",
    flags=re.IGNORECASE | re.DOTALL,
)


class CasAuthenticationError(Exception):
    """Safe authentication failure with non-sensitive diagnostic classification."""

    def __init__(
        self,
        stage: str = "unknown",
        error_code: str = "authentication_failed",
        *,
        error_type: str | None = None,
        error_detail: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(error_code)
        self.stage = stage
        self.error_code = error_code
        self.error_type = error_type
        self.error_detail = error_detail
        self.status_code = status_code


def _safe_http_error(stage: str, error_code: str, exc: httpx.HTTPError) -> CasAuthenticationError:
    """Record upstream diagnostics without retaining secret-bearing query strings."""
    request = getattr(exc, "request", None)
    url = getattr(request, "url", None)
    endpoint = "unknown"
    if url is not None:
        endpoint = f"{url.scheme}://{url.host}{url.path}"
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    detail = (
        f"upstream HTTP {status_code} from {endpoint}"
        if status_code is not None
        else f"{type(exc).__name__} contacting {endpoint}"
    )
    return CasAuthenticationError(
        stage,
        error_code,
        error_type=type(exc).__name__,
        error_detail=detail,
        status_code=status_code if isinstance(status_code, int) else None,
    )


def _session_response_diagnostics(payload: object) -> object:
    """Keep identity attributes visible while masking only credential values."""
    sensitive = ("token", "secret", "signature", "password", "credential")
    structural = {"tokeninfo", "token_info"}

    def scrub(value: object, key: str | None = None) -> object:
        normalized = key.lower() if key is not None else ""
        if (
            normalized
            and normalized not in structural
            and any(marker in normalized for marker in sensitive)
        ):
            return REDACTED
        if isinstance(value, dict):
            return {str(item_key): scrub(item, str(item_key)) for item_key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(payload)


@dataclass(frozen=True, slots=True)
class CasIdentity:
    subject: str
    employee_number: str | None
    email: str | None
    display_name: str | None
    debug_fields: dict[str, object]


class CasAuthentication:
    def __init__(self, settings: Settings, redis: Redis) -> None:
        self._settings = settings
        self._redis = redis

    @staticmethod
    def _state_key(state: str) -> str:
        return "s3mp:cas:state:" + hashlib.sha256(state.encode()).hexdigest()

    def _valid_return_path(self, value: str | None) -> str:
        if not value:
            return "/s3mp/"
        parsed = urlparse(value)
        if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
            raise CasAuthenticationError
        return value

    async def begin(self, return_to: str | None) -> tuple[str, str]:
        target = self._valid_return_path(return_to)
        state = secrets.token_urlsafe(32)
        stored = await self._redis.set(
            self._state_key(state), target, ex=self._settings.cas_state_ttl_seconds, nx=True
        )
        if not stored:
            raise CasAuthenticationError
        login_url = self._settings.cas_login_url or ""
        return login_url + "?" + urlencode({"service": self._settings.cas_service_url}), state

    def global_logout_url(self) -> str | None:
        """Build the configured CAS logout redirect without trusting browser input."""
        logout_url = self._settings.cas_logout_url
        return_url = self._settings.cas_logout_return_url
        if not logout_url or not return_url:
            return None
        parsed = urlsplit(logout_url)
        separator = "&" if parsed.query else ""
        query = (
            parsed.query
            + separator
            + urlencode({self._settings.cas_logout_return_parameter: return_url})
        )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))

    @staticmethod
    def logout_request_ticket(logout_request: str) -> str:
        """Extract CAS SLO SessionIndex (the original ST) from a hardened XML payload."""
        try:
            root = ET.fromstring(logout_request)
        except ET.ParseError as exc:
            raise CasAuthenticationError("single_logout", "invalid_logout_request") from exc
        if root.tag.rsplit("}", 1)[-1] != "LogoutRequest":
            raise CasAuthenticationError("single_logout", "invalid_logout_request")
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == "SessionIndex" and element.text:
                return str(element.text).strip()
        raise CasAuthenticationError("single_logout", "missing_session_index")

    async def consume(self, state: str) -> str:
        key = self._state_key(state)
        value = await self._redis.getdel(key)
        if not value:
            raise CasAuthenticationError("state", "missing_expired_or_replayed_state")
        return str(value)

    async def verify(self, ticket: str) -> CasIdentity:
        timeout = httpx.Timeout(self._settings.cas_http_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            try:
                response = await client.get(
                    self._settings.cas_validate_url or "",
                    params={"ticket": ticket, "service": self._settings.cas_service_url},
                )
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise _safe_http_error("cas_ticket_validation", "timeout", exc) from exc
            except httpx.HTTPStatusError as exc:
                raise _safe_http_error("cas_ticket_validation", "http_error", exc) from exc
            except httpx.RequestError as exc:
                raise _safe_http_error("cas_ticket_validation", "transport_error", exc) from exc
            if self._settings.cas_log_response_bodies:
                log_event(
                    logger,
                    logging.INFO,
                    "cas_service_validate_response",
                    layer="authentication",
                    dependency="cas",
                    dependency_operation="service_validate",
                    outcome="succeeded",
                    diagnostic_response=_BUSINESS_TOKEN_ELEMENT.sub(
                        r"\1[REDACTED]\2", response.text
                    ),
                )
            try:
                token = self._business_token(response.text)
            except (ET.ParseError, ValueError, TypeError) as exc:
                raise CasAuthenticationError(
                    "cas_ticket_validation",
                    "invalid_response",
                    error_type=type(exc).__name__,
                    error_detail=str(exc),
                ) from exc
            try:
                session = await client.post(
                    (self._settings.cas_session_host or "").rstrip("/") + "/token/verify",
                    data={
                        "token": token,
                        "source": self._settings.cas_session_source or "",
                        "signature": self._settings.secret_value("cas_session_signature") or "",
                    },
                )
                session.raise_for_status()
            except httpx.TimeoutException as exc:
                raise _safe_http_error("session_identity_verification", "timeout", exc) from exc
            except httpx.HTTPStatusError as exc:
                raise _safe_http_error("session_identity_verification", "http_error", exc) from exc
            except httpx.RequestError as exc:
                raise _safe_http_error(
                    "session_identity_verification", "transport_error", exc
                ) from exc
            try:
                payload = session.json()
            except ValueError as exc:
                raise CasAuthenticationError(
                    "session_identity_verification",
                    "invalid_response",
                    error_type=type(exc).__name__,
                    error_detail=str(exc),
                ) from exc
            if self._settings.cas_log_response_bodies:
                log_event(
                    logger,
                    logging.INFO,
                    "session_token_verify_response",
                    layer="authentication",
                    dependency="session_service",
                    dependency_operation="token_verify",
                    outcome="succeeded",
                    diagnostic_response=_session_response_diagnostics(payload),
                )
        return self._session_identity(payload)

    @staticmethod
    def _business_token(xml: str) -> str:
        root = ET.fromstring(xml)
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == "businessToken" and element.text:
                return str(element.text).strip()
        raise ValueError("missing CAS business token")

    @staticmethod
    def _session_identity(payload: object) -> CasIdentity:
        result_code = (
            payload.get("errorCode", payload.get("error_code"))
            if isinstance(payload, dict)
            else None
        )
        if not isinstance(payload, dict) or result_code != 0:
            if isinstance(payload, dict):
                safe_codes = {
                    name: payload.get(name)
                    for name in ("errorCode", "error_code", "code", "status")
                    if isinstance(payload.get(name), int | str | bool | type(None))
                }
                detail = (
                    "Session response rejected: "
                    f"top_level_keys={sorted(str(key) for key in payload)}; "
                    f"safe_status_fields={safe_codes}"
                )
            else:
                detail = f"Session response rejected: top_level_type={type(payload).__name__}"
            raise CasAuthenticationError(
                "session_identity_verification",
                "rejected_response",
                error_detail=detail,
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise CasAuthenticationError("session_identity_verification", "invalid_response")
        info = data.get("tokenInfo") or data.get("token_info")
        user = data.get("userInfo") or data.get("user_info")
        if not isinstance(info, dict) or not isinstance(user, dict):
            raise CasAuthenticationError("session_identity_verification", "invalid_response")
        subject = str(info.get("ucid") or "").strip()
        if not subject:
            raise CasAuthenticationError("session_identity_verification", "missing_subject")
        employee = (
            user.get("employeeNumber")
            or user.get("employee_number")
            or user.get("userCode")
            or user.get("usercode")
        )
        email = (
            user.get("email")
            or user.get("mail")
            or user.get("userFullEmail")
            or user.get("user_full_email")
        )
        display_name = user.get("displayName") or user.get("display_name") or user.get("name")

        def debug_values(values: dict[object, object]) -> dict[str, object]:
            sensitive = ("token", "secret", "signature", "password", "credential")
            return {
                str(key): value
                for key, value in values.items()
                if not any(marker in str(key).lower() for marker in sensitive)
            }

        return CasIdentity(
            subject,
            str(employee).strip() if employee else None,
            str(email).strip() if email else None,
            str(display_name).strip() if display_name else None,
            {
                "data_keys": sorted(str(key) for key in data),
                "subject_fields": debug_values(info),
                "user_fields": debug_values(user),
            },
        )
