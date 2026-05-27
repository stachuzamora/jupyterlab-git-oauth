"""
OAuth Device Authorization Grant broker (RFC 8628).

Provider-agnostic: all methods accept full endpoint URLs so they work with
any provider (GitLab, GitHub, Gitea, etc.).

Public API
----------
    broker = AuthBroker()
    flow   = await broker.start_device_flow(device_auth_endpoint, client_id, scopes)
    result = await broker.poll_device_token(token_endpoint, client_id, device_code)
    tokens = await broker.refresh_access_token(token_endpoint, client_id, refresh_token)
    ok     = await broker.revoke_token(revoke_endpoint, client_id, token)
    user   = await broker.get_user(userinfo_endpoint, access_token, ...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DeviceFlowError(Exception):
    """Base class for device flow errors."""


class DeviceFlowPendingError(DeviceFlowError):
    """User has not yet approved the device (authorization_pending)."""


class DeviceFlowExpiredError(DeviceFlowError):
    """Device code has expired."""


class DeviceFlowSlowDownError(DeviceFlowError):
    """Server requested slower polling."""


class TokenRefreshError(Exception):
    """Refresh token is invalid or expired."""


class ProviderAPIError(Exception):
    """Unexpected error from a provider API."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


# Keep the old name as an alias so any existing imports don't break.
GitLabAPIError = ProviderAPIError


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DeviceFlowResponse:
    """Response from the device authorization endpoint (RFC 8628)."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


@dataclass
class TokenResponse:
    """Successful token grant response."""

    access_token: str
    token_type: str
    refresh_token: str
    expires_in: int
    scope: str
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        import time

        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "refresh_token": self.refresh_token,
            "expires_in": self.expires_in,
            "scope": self.scope,
            "created_at": self.created_at or int(time.time()),
            "expires_at": _iso_expiry(self.expires_in),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenResponse":
        return cls(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            refresh_token=data.get("refresh_token", ""),
            expires_in=data.get("expires_in", 7200),
            scope=data.get("scope", ""),
            created_at=data.get("created_at", 0),
        )


@dataclass
class ProviderUser:
    """Normalised user representation returned by any provider's userinfo endpoint."""

    id: int
    username: str
    email: str
    name: str
    avatar_url: str = ""
    web_url: str = ""
    state: str = "active"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
        *,
        username_field: str = "username",
        email_field: str = "email",
        name_field: str = "name",
        id_field: str = "id",
    ) -> "ProviderUser":
        raw_id = data.get(id_field, 0)
        return cls(
            id=int(raw_id) if raw_id else 0,
            username=data.get(username_field) or "",
            email=data.get(email_field) or "",
            name=data.get(name_field) or data.get(username_field) or "",
            avatar_url=data.get("avatar_url") or "",
            web_url=data.get("web_url") or data.get("html_url") or "",
            state=data.get("state") or "active",
        )


# Keep old name as alias.
GitLabUser = ProviderUser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_expiry(expires_in: int) -> str:
    import time
    from datetime import datetime, timezone

    expiry_ts = time.time() + expires_in
    return datetime.fromtimestamp(expiry_ts, tz=timezone.utc).isoformat()


def _build_client(timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        headers={
            "User-Agent": "jupyter-server-oauth-providers/0.1.0",
            "Accept": "application/json",
        },
        follow_redirects=True,
    )


def _raise_api_error(operation: str, resp: httpx.Response) -> None:
    try:
        body = resp.json()
        detail = body.get("error_description") or body.get("message") or str(body)
    except Exception:
        detail = resp.text[:300]

    raise ProviderAPIError(
        f"{operation}: provider returned HTTP {resp.status_code}: {detail}",
        status_code=resp.status_code,
    )


# ---------------------------------------------------------------------------
# AuthBroker
# ---------------------------------------------------------------------------


class AuthBroker:
    """
    Async broker for OAuth 2.0 Device Authorization Grant (RFC 8628).

    All methods accept full absolute endpoint URLs so they work with any
    provider. Coroutines must be awaited inside a Tornado IOLoop.
    """

    # ------------------------------------------------------------------
    # Device Authorization Grant (RFC 8628)
    # ------------------------------------------------------------------

    async def start_device_flow(
        self,
        device_auth_endpoint: str,
        client_id: str,
        scopes: str,
    ) -> DeviceFlowResponse:
        """POST to the device authorization endpoint."""
        payload = {"client_id": client_id, "scope": scopes}

        async with _build_client() as client:
            resp = await client.post(device_auth_endpoint, data=payload)

        if resp.status_code != 200:
            _raise_api_error("start_device_flow", resp)

        data = resp.json()

        if "error" in data:
            raise DeviceFlowError(
                f"Provider returned error: {data['error']} — {data.get('error_description', '')}"
            )

        return DeviceFlowResponse(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data.get("verification_uri", ""),
            verification_uri_complete=data.get(
                "verification_uri_complete", data.get("verification_uri", "")
            ),
            expires_in=int(data.get("expires_in", 300)),
            interval=int(data.get("interval", 5)),
        )

    async def poll_device_token(
        self,
        token_endpoint: str,
        client_id: str,
        device_code: str,
    ) -> TokenResponse:
        """
        POST to the token endpoint with grant_type=device_code.

        Raises:
            DeviceFlowPendingError  — user hasn't approved yet
            DeviceFlowExpiredError  — code expired
            DeviceFlowSlowDownError — server requested slower polling
        Returns:
            TokenResponse on approval
        """
        payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": device_code,
        }

        async with _build_client() as client:
            resp = await client.post(token_endpoint, data=payload)

        data = resp.json()
        error = data.get("error", "")

        if error == "authorization_pending":
            raise DeviceFlowPendingError("Authorization pending")
        if error == "slow_down":
            raise DeviceFlowSlowDownError("Polling too fast; slow down")
        if error in ("expired_token", "device_code_expired"):
            raise DeviceFlowExpiredError("Device code has expired")
        if error:
            raise DeviceFlowError(
                f"Unexpected error from poll: {error} — {data.get('error_description', '')}"
            )

        if resp.status_code not in (200, 201):
            _raise_api_error("poll_device_token", resp)

        return TokenResponse.from_dict(data)

    # ------------------------------------------------------------------
    # Token lifecycle
    # ------------------------------------------------------------------

    async def refresh_access_token(
        self,
        token_endpoint: str,
        client_id: str,
        refresh_token: str,
    ) -> TokenResponse:
        """POST to the token endpoint with grant_type=refresh_token."""
        payload = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }

        async with _build_client() as client:
            resp = await client.post(token_endpoint, data=payload)

        if resp.status_code in (400, 401):
            data = resp.json()
            raise TokenRefreshError(
                f"Refresh failed: {data.get('error', 'unknown')} — "
                f"{data.get('error_description', '')}"
            )

        if resp.status_code != 200:
            _raise_api_error("refresh_access_token", resp)

        return TokenResponse.from_dict(resp.json())

    async def revoke_token(
        self,
        revoke_endpoint: str,
        client_id: str,
        token: str,
    ) -> bool:
        """
        POST to the revocation endpoint (RFC 7009).

        Returns True if revocation succeeded or the token was already invalid.
        Returns False (without raising) if revoke_endpoint is empty or the
        request fails — revocation is best-effort.
        """
        if not revoke_endpoint:
            return False

        payload = {"client_id": client_id, "token": token}

        try:
            async with _build_client(timeout=10.0) as client:
                resp = await client.post(revoke_endpoint, data=payload)
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("revoke_token: request failed (ignoring): %s", exc)
            return False

    # ------------------------------------------------------------------
    # User info
    # ------------------------------------------------------------------

    async def get_user(
        self,
        userinfo_endpoint: str,
        access_token: str,
        *,
        username_field: str = "username",
        email_field: str = "email",
        name_field: str = "name",
        id_field: str = "id",
    ) -> ProviderUser:
        """GET the userinfo endpoint and return a normalised ProviderUser."""
        async with _build_client() as client:
            resp = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if resp.status_code == 401:
            raise ProviderAPIError("Access token is invalid or expired", status_code=401)
        if resp.status_code != 200:
            _raise_api_error("get_user", resp)

        return ProviderUser.from_api(
            resp.json(),
            username_field=username_field,
            email_field=email_field,
            name_field=name_field,
            id_field=id_field,
        )

    async def get_gitlab_user(
        self,
        gitlab_url: str,
        access_token: str,
    ) -> ProviderUser:
        """Backward-compatible alias: fetches from GitLab's /api/v4/user."""
        return await self.get_user(
            f"{gitlab_url}/api/v4/user",
            access_token,
            username_field="username",
            email_field="email",
            name_field="name",
        )
