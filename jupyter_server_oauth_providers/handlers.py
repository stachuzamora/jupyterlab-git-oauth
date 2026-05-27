"""
Tornado handlers for the OAuth providers extension.

Endpoints (all under /api/oauth-providers):
  GET  /providers                             — list active providers
  GET  /<provider>/config                     — get provider config / overrides
  POST /<provider>/config                     — save UI-supplied overrides
  GET  /<provider>/status                     — connection status for current user
  POST /<provider>/device/start               — begin device flow
  POST /<provider>/device/poll                — poll for approval
  POST /<provider>/disconnect                 — revoke & clear token
  POST /<provider>/identity/sync              — write git commit identity
  GET  /<provider>/identity/validate          — validate git commit identity
  GET  /credential?provider=<name>            — serve token to git credential helper

Identity resolution order (for 'current user'):
  1. kubeflow-userid          (Kubeflow AuthService / Envoy injection)
  2. X-Auth-Request-User      (oauth2-proxy)
  3. X-Forwarded-User         (various reverse proxies)

All handlers return 401 if no user identity can be resolved.

XSRF:
  JupyterLab sends the _xsrf cookie value in X-XSRFToken on every fetch(),
  so standard XSRF protection works here.
  For testing with curl: --cookie "_xsrf=test" -H "X-XSRFToken: test"
"""

from __future__ import annotations

import json
import traceback
import uuid
from typing import Any
from urllib.parse import urlparse

import tornado.web
from jupyter_server.base.handlers import JupyterHandler

from .audit import AuditLogger
from .auth_broker import (
    AuthBroker,
    DeviceFlowExpiredError,
    DeviceFlowPendingError,
    DeviceFlowSlowDownError,
    DeviceFlowResponse,
    TokenResponse,
)
from .providers import ProviderConfig, get_active_providers, get_provider
from .token_store import create_token_store


# ---------------------------------------------------------------------------
# Base handler
# ---------------------------------------------------------------------------


class _BaseOAuthHandler(JupyterHandler):
    """Shared helpers for all OAuth provider handlers."""

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return self.path_kwargs.get("provider", "")

    @property
    def provider(self) -> ProviderConfig | None:
        overrides = self.settings.get("oauth_provider_overrides", {})
        return get_provider(self.provider_name, overrides)

    def require_provider(self) -> ProviderConfig:
        """Return the active ProviderConfig or abort with 404."""
        cfg = self.provider
        if cfg is None:
            self.write_json(
                {
                    "error": "unknown_provider",
                    "detail": (
                        f"Provider '{self.provider_name}' is not active. "
                        "Set the required env vars or POST to /config with overrides."
                    ),
                },
                status=404,
            )
            raise tornado.web.Finish()
        return cfg

    # ------------------------------------------------------------------
    # URL rewriting (internal → external)
    # ------------------------------------------------------------------

    @staticmethod
    def _rewrite_uri(uri: str, provider: ProviderConfig) -> str:
        """Replace the provider's internal base_url with external_url in uri."""
        if not uri or not provider.external_url:
            return uri
        internal = provider.base_url.rstrip("/")
        external = provider.external_url.rstrip("/")
        if internal == external:
            return uri

        parsed_internal = urlparse(internal)
        parsed_uri = urlparse(uri)

        def _netloc_key(p) -> str:
            host = p.hostname or ""
            port = p.port
            return host if port in (80, 443, None) else f"{host}:{port}"

        if _netloc_key(parsed_uri) == _netloc_key(parsed_internal):
            suffix = parsed_uri.path
            if parsed_uri.query:
                suffix += "?" + parsed_uri.query
            return external + suffix

        return uri

    # ------------------------------------------------------------------
    # Shared services (lazy-init from settings)
    # ------------------------------------------------------------------

    @property
    def broker(self) -> AuthBroker:
        if "oauth_broker" not in self.settings:
            self.settings["oauth_broker"] = AuthBroker()
        return self.settings["oauth_broker"]

    @property
    def token_store(self):  # noqa: ANN201
        store = self.settings.get("oauth_token_store")
        if store is None:
            store = create_token_store()
            self.settings["oauth_token_store"] = store
        return store

    @property
    def audit(self) -> AuditLogger:
        if "oauth_audit" not in self.settings:
            self.settings["oauth_audit"] = AuditLogger()
        return self.settings["oauth_audit"]

    # ------------------------------------------------------------------
    # Token store keys
    # ------------------------------------------------------------------

    @staticmethod
    def _token_key(provider_name: str, user_id: str) -> str:
        """Namespaced token key so each (provider, user) pair is isolated."""
        return f"{provider_name}:{user_id}"

    @staticmethod
    def _pending_key(provider_name: str, user_id: str) -> str:
        return f"oauth_pending_{provider_name}_{user_id}"

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def resolve_current_user(self) -> str | None:
        """Resolve authenticated user from proxy-injected request headers."""
        for header in ("kubeflow-userid", "X-Auth-Request-User", "X-Forwarded-User"):
            value = self.request.headers.get(header)
            if value:
                return value.strip()
        return None

    def require_user(self) -> str:
        """Return the current user or abort with 401."""
        user = self.resolve_current_user()
        if not user:
            self.set_status(401)
            self.finish(
                json.dumps(
                    {
                        "error": "unauthenticated",
                        "detail": (
                            "Cannot resolve user identity. Expected one of: "
                            "kubeflow-userid, X-Auth-Request-User, X-Forwarded-User"
                        ),
                    }
                )
            )
            raise tornado.web.Finish()
        # Cache pod-level identity for localhost credential-helper callers.
        # Safe because Kubeflow Notebook pods are single-user per pod.
        if "oauth_pod_user" not in self.settings:
            self.settings["oauth_pod_user"] = user
        return user

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def write_json(self, data: Any, status: int = 200) -> None:
        self.set_status(status)
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(data))

    def json_body(self) -> dict:
        try:
            body = self.request.body
            if body:
                return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            pass
        return {}

    def correlation_id(self) -> str:
        body = self.json_body()
        return (
            body.get("correlation_id")
            or self.request.headers.get("X-Correlation-ID")
            or uuid.uuid4().hex
        )


# ---------------------------------------------------------------------------
# GET /api/oauth-providers/providers
# ---------------------------------------------------------------------------


class ProvidersListHandler(_BaseOAuthHandler):
    """
    Returns the list of active (configured) providers.

    Response 200:
      [
        {
          "name": "gitlab",
          "display_name": "GitLab",
          "external_url": "https://gitlab.example.com",
          "meta": {"color": "#FC6D26", "icon": "gitlab"}
        },
        ...
      ]
    """

    async def get(self) -> None:
        import os

        overrides = self.settings.get("oauth_provider_overrides", {})
        providers = get_active_providers(overrides)
        topbar_enabled = os.environ.get("OAUTH_TOPBAR", "").lower() in ("1", "true", "yes")
        self.write_json(
            {
                "providers": [
                    {
                        "name": cfg.name,
                        "display_name": cfg.display_name,
                        "external_url": cfg.external_url or cfg.base_url,
                        "meta": cfg.meta,
                    }
                    for cfg in providers.values()
                ],
                "topbar_enabled": topbar_enabled,
            }
        )


# ---------------------------------------------------------------------------
# GET /POST /api/oauth-providers/<provider>/config
# ---------------------------------------------------------------------------


class ProviderConfigHandler(_BaseOAuthHandler):
    """
    GET  — return the resolved config (and stored overrides) for a provider.
    POST — save UI-supplied field overrides and return the updated config.

    POST body (JSON, any subset):
      { "client_id": "...", "base_url": "...", "external_url": "...", "scopes": "..." }
    """

    _ALLOWED_OVERRIDE_KEYS = frozenset({"client_id", "base_url", "external_url", "scopes"})

    async def get(self, **kwargs) -> None:
        overrides = self.settings.get("oauth_provider_overrides", {})
        stored_overrides = overrides.get(self.provider_name, {})
        cfg = self.provider

        if cfg:
            self.write_json(
                {
                    "name": cfg.name,
                    "display_name": cfg.display_name,
                    "base_url": cfg.base_url,
                    "external_url": cfg.external_url,
                    "client_id": cfg.client_id,
                    "scopes": cfg.scopes,
                    "active": True,
                    "overrides": stored_overrides,
                }
            )
        else:
            self.write_json(
                {
                    "name": self.provider_name,
                    "active": False,
                    "overrides": stored_overrides,
                }
            )

    async def post(self, **kwargs) -> None:
        self.require_user()
        body = self.json_body()

        unknown = set(body.keys()) - self._ALLOWED_OVERRIDE_KEYS
        if unknown:
            self.write_json(
                {"error": "invalid_fields", "detail": f"Unknown fields: {sorted(unknown)}"},
                status=400,
            )
            return

        overrides = self.settings.setdefault("oauth_provider_overrides", {})
        existing = overrides.get(self.provider_name, {})
        existing.update({k: v for k, v in body.items() if v})
        overrides[self.provider_name] = existing

        cfg = get_provider(self.provider_name, overrides)
        if cfg:
            self.write_json(
                {
                    "name": cfg.name,
                    "display_name": cfg.display_name,
                    "base_url": cfg.base_url,
                    "external_url": cfg.external_url,
                    "client_id": cfg.client_id,
                    "scopes": cfg.scopes,
                    "active": True,
                }
            )
        else:
            self.write_json(
                {
                    "name": self.provider_name,
                    "active": False,
                    "detail": "Provider not yet active — set all required fields.",
                }
            )


# ---------------------------------------------------------------------------
# GET /api/oauth-providers/<provider>/status
# ---------------------------------------------------------------------------


class StatusHandler(_BaseOAuthHandler):
    """
    Returns the current connection status for the authenticated user.

    Response 200 (connected):
      {
        "connected": true,
        "provider": "gitlab",
        "provider_url": "https://gitlab.example.com",
        "user_id": 42,
        "username": "alice",
        "email": "alice@example.com",
        "display_name": "Alice",
        "token_expires_at": "2024-12-01T12:00:00Z"
      }

    Response 200 (not connected):
      { "connected": false, "provider": "gitlab", "provider_url": "..." }
    """

    async def get(self, **kwargs) -> None:
        user_id = self.require_user()
        provider = self.require_provider()
        token_key = self._token_key(provider.name, user_id)

        try:
            stored = await self.token_store.load_token(token_key)
        except Exception as exc:
            self.log.warning("[oauth] token store read error for %s/%s: %s", provider.name, user_id, exc)
            stored = None

        provider_url = provider.external_url or provider.base_url

        if not stored or not stored.get("access_token"):
            self.write_json({"connected": False, "provider": provider.name, "provider_url": provider_url})
            return

        try:
            prov_user = await self.broker.get_user(
                provider.userinfo_endpoint,
                stored["access_token"],
                username_field=provider.username_field,
                email_field=provider.email_field,
                name_field=provider.name_field,
            )
            self.write_json(
                {
                    "connected": True,
                    "provider": provider.name,
                    "provider_url": provider_url,
                    "user_id": prov_user.id,
                    "username": prov_user.username,
                    "email": prov_user.email,
                    "display_name": prov_user.name,
                    "token_expires_at": stored.get("expires_at"),
                }
            )
        except Exception:
            # Token likely expired — try refresh
            refresh_token = stored.get("refresh_token")
            if refresh_token:
                try:
                    new_tokens = await self.broker.refresh_access_token(
                        provider.token_endpoint, provider.client_id, refresh_token
                    )
                    await self.token_store.save_token(token_key, new_tokens.to_dict())
                    prov_user = await self.broker.get_user(
                        provider.userinfo_endpoint,
                        new_tokens.access_token,
                        username_field=provider.username_field,
                        email_field=provider.email_field,
                        name_field=provider.name_field,
                    )
                    self.audit.emit(
                        "token_refreshed",
                        jupyter_user_id=user_id,
                        provider=provider.name,
                        provider_user_id=str(prov_user.id),
                        result="success",
                    )
                    self.write_json(
                        {
                            "connected": True,
                            "provider": provider.name,
                            "provider_url": provider_url,
                            "user_id": prov_user.id,
                            "username": prov_user.username,
                            "email": prov_user.email,
                            "display_name": prov_user.name,
                        }
                    )
                    return
                except Exception as refresh_exc:
                    self.audit.emit(
                        "token_refresh_failed",
                        jupyter_user_id=user_id,
                        provider=provider.name,
                        result="failed",
                        error=str(refresh_exc),
                    )

            self.write_json(
                {
                    "connected": False,
                    "reconnect_required": True,
                    "provider": provider.name,
                    "provider_url": provider_url,
                }
            )


# ---------------------------------------------------------------------------
# POST /api/oauth-providers/<provider>/device/start
# ---------------------------------------------------------------------------


class DeviceStartHandler(_BaseOAuthHandler):
    """
    Initiates the Device Authorization Grant flow.

    Request body (optional JSON):
      {
        "repo_path": "/home/jovyan/work/myrepo",
        "remote_url": "https://gitlab.example.com/group/project.git",
        "correlation_id": "optional-uuid"
      }

    Response 200:
      {
        "device_code": "...",
        "user_code": "ABCD-1234",
        "verification_uri": "https://gitlab.example.com/oauth/device",
        "verification_uri_complete": "https://...?user_code=ABCD-1234",
        "expires_in": 300,
        "interval": 5,
        "correlation_id": "..."
      }
    """

    async def post(self, **kwargs) -> None:
        user_id = self.require_user()
        provider = self.require_provider()
        body = self.json_body()
        corr_id = self.correlation_id()

        repo_path = body.get("repo_path", "")

        if not provider.device_auth_endpoint:
            self.write_json(
                {
                    "error": "configuration_error",
                    "detail": f"No device_auth_endpoint configured for provider '{provider.name}'",
                },
                status=503,
            )
            return

        try:
            flow: DeviceFlowResponse = await self.broker.start_device_flow(
                device_auth_endpoint=provider.device_auth_endpoint,
                client_id=provider.client_id,
                scopes=provider.scopes,
            )
        except Exception as exc:
            self.log.error(
                "[oauth] device/start failed for %s: %s\n%s",
                provider.name, exc, traceback.format_exc(),
            )
            self.write_json({"error": "upstream_error", "detail": str(exc)}, status=502)
            return

        pending_key = self._pending_key(provider.name, user_id)
        self.settings[pending_key] = {
            "device_code": flow.device_code,
            "interval": flow.interval,
            "correlation_id": corr_id,
        }

        self.audit.emit(
            "device_flow_started",
            jupyter_user_id=user_id,
            provider=provider.name,
            repo_path=repo_path,
            result="initiated",
            correlation_id=corr_id,
        )

        self.write_json(
            {
                "device_code": flow.device_code,
                "user_code": flow.user_code,
                "verification_uri": self._rewrite_uri(flow.verification_uri, provider),
                "verification_uri_complete": self._rewrite_uri(
                    flow.verification_uri_complete, provider
                ),
                "expires_in": flow.expires_in,
                "interval": flow.interval,
                "correlation_id": corr_id,
            }
        )


# ---------------------------------------------------------------------------
# POST /api/oauth-providers/<provider>/device/poll
# ---------------------------------------------------------------------------


class DevicePollHandler(_BaseOAuthHandler):
    """
    Polls to check whether the user has approved the device flow.

    Request body:
      {
        "device_code": "...",       // required if not using correlation_id
        "correlation_id": "..."     // optional
      }

    Response 200 (approved):
      { "status": "approved", "username": "alice", "email": "alice@example.com" }

    Response 200 (pending):
      { "status": "pending" }

    Response 200 (expired):
      { "status": "expired" }
    """

    async def post(self, **kwargs) -> None:
        user_id = self.require_user()
        provider = self.require_provider()
        body = self.json_body()
        corr_id = body.get("correlation_id", "")

        device_code = body.get("device_code", "")
        if not device_code and corr_id:
            pending_key = self._pending_key(provider.name, user_id)
            pending = self.settings.get(pending_key, {})
            if pending.get("correlation_id") == corr_id:
                device_code = pending.get("device_code", "")

        if not device_code:
            self.write_json(
                {"error": "missing_device_code", "detail": "Provide device_code or correlation_id"},
                status=400,
            )
            return

        try:
            result = await self.broker.poll_device_token(
                token_endpoint=provider.token_endpoint,
                client_id=provider.client_id,
                device_code=device_code,
            )
        except DeviceFlowPendingError:
            self.write_json({"status": "pending"})
            return
        except DeviceFlowExpiredError:
            self.write_json({"status": "expired"})
            return
        except DeviceFlowSlowDownError:
            self.write_json({"status": "pending", "slow_down": True})
            return
        except Exception as exc:
            self.log.error("[oauth] device/poll failed for %s: %s", provider.name, exc)
            self.write_json({"error": "upstream_error", "detail": str(exc)}, status=502)
            return

        if not isinstance(result, TokenResponse):
            self.write_json({"status": "pending"})
            return

        # Approved — fetch user info and persist token
        try:
            prov_user = await self.broker.get_user(
                provider.userinfo_endpoint,
                result.access_token,
                username_field=provider.username_field,
                email_field=provider.email_field,
                name_field=provider.name_field,
            )
        except Exception as exc:
            self.log.error("[oauth] get_user after poll failed for %s: %s", provider.name, exc)
            self.write_json({"error": "user_fetch_error", "detail": str(exc)}, status=502)
            return

        token_data = result.to_dict()
        token_data["provider_user_id"] = prov_user.id
        token_data["provider_username"] = prov_user.username
        token_data["provider_email"] = prov_user.email
        token_data["provider_display_name"] = prov_user.name

        token_key = self._token_key(provider.name, user_id)
        await self.token_store.save_token(token_key, token_data)

        self.settings.pop(self._pending_key(provider.name, user_id), None)

        self.audit.emit(
            "device_flow_approved",
            jupyter_user_id=user_id,
            provider=provider.name,
            provider_user_id=str(prov_user.id),
            result="approved",
            correlation_id=corr_id,
        )

        self.write_json(
            {
                "status": "approved",
                "provider": provider.name,
                "user_id": prov_user.id,
                "username": prov_user.username,
                "email": prov_user.email,
                "display_name": prov_user.name,
            }
        )


# ---------------------------------------------------------------------------
# POST /api/oauth-providers/<provider>/disconnect
# ---------------------------------------------------------------------------


class DisconnectHandler(_BaseOAuthHandler):
    """
    Revokes the provider token and clears local storage.

    Response 200:
      { "disconnected": true }
    """

    async def post(self, **kwargs) -> None:
        user_id = self.require_user()
        provider = self.require_provider()
        token_key = self._token_key(provider.name, user_id)

        try:
            stored = await self.token_store.load_token(token_key)
        except Exception:
            stored = None

        if stored:
            access_token = stored.get("access_token", "")
            if access_token and provider.revoke_endpoint:
                try:
                    await self.broker.revoke_token(
                        provider.revoke_endpoint, provider.client_id, access_token
                    )
                except Exception as exc:
                    self.log.warning(
                        "[oauth] token revocation failed for %s (ignoring): %s",
                        provider.name, exc,
                    )

            try:
                await self.token_store.delete_token(token_key)
            except Exception as exc:
                self.log.error("[oauth] token store delete failed: %s", exc)
                self.write_json({"error": "store_error", "detail": str(exc)}, status=500)
                return

        self.audit.emit(
            "disconnect",
            jupyter_user_id=user_id,
            provider=provider.name,
            result="disconnected",
        )

        self.write_json({"disconnected": True})


# ---------------------------------------------------------------------------
# POST /api/oauth-providers/<provider>/identity/sync
# ---------------------------------------------------------------------------


class IdentitySyncHandler(_BaseOAuthHandler):
    """
    Syncs git commit identity (user.name, user.email) for a repository.

    Request body:
      { "repo_path": "/home/jovyan/work/myrepo" }

    Response 200:
      { "synced": true, "name": "Alice", "email": "alice@example.com", "was_placeholder": true }
    """

    async def post(self, **kwargs) -> None:
        user_id = self.require_user()
        provider = self.require_provider()
        body = self.json_body()
        repo_path = body.get("repo_path", "")

        if not repo_path:
            self.write_json(
                {"error": "missing_repo_path", "detail": "repo_path is required"},
                status=400,
            )
            return

        token_key = self._token_key(provider.name, user_id)
        try:
            stored = await self.token_store.load_token(token_key)
        except Exception as exc:
            self.write_json({"error": "store_error", "detail": str(exc)}, status=500)
            return

        if not stored or not stored.get("access_token"):
            self.write_json(
                {"error": "not_connected", "detail": f"Connect to {provider.display_name} first"},
                status=401,
            )
            return

        try:
            prov_user = await self.broker.get_user(
                provider.userinfo_endpoint,
                stored["access_token"],
                username_field=provider.username_field,
                email_field=provider.email_field,
                name_field=provider.name_field,
            )
        except Exception as exc:
            self.write_json({"error": "provider_error", "detail": str(exc)}, status=502)
            return

        from .identity_sync import CommitIdentity, IdentitySync

        identity_sync = IdentitySync()
        identity = identity_sync.resolve_commit_identity(user_id, prov_user)
        was_placeholder = await self._check_placeholder(identity_sync, repo_path)

        try:
            identity_sync.write_git_identity(repo_path, identity)
        except Exception as exc:
            self.log.error("[oauth] write_git_identity failed: %s", exc)
            self.write_json({"error": "git_config_error", "detail": str(exc)}, status=500)
            return

        self.audit.emit(
            "identity_sync",
            jupyter_user_id=user_id,
            provider=provider.name,
            provider_user_id=str(prov_user.id),
            repo_path=repo_path,
            result="synced",
        )

        self.write_json(
            {
                "synced": True,
                "name": identity.name,
                "email": identity.email,
                "was_placeholder": was_placeholder,
            }
        )

    async def _check_placeholder(self, identity_sync, repo_path: str) -> bool:
        try:
            import subprocess

            name = subprocess.check_output(
                ["git", "-C", repo_path, "config", "user.name"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
            email = subprocess.check_output(
                ["git", "-C", repo_path, "config", "user.email"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
            return identity_sync.is_placeholder_identity(name, email)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# GET /api/oauth-providers/<provider>/identity/validate
# ---------------------------------------------------------------------------


class IdentityValidateHandler(_BaseOAuthHandler):
    """
    Validates git commit identity for a repository against the provider user.

    Query params:
      repo_path=/home/jovyan/work/myrepo

    Response 200:
      {
        "valid": true,
        "current_name": "Alice",
        "current_email": "alice@example.com",
        "provider_name": "Alice",
        "provider_email": "alice@example.com",
        "is_placeholder": false
      }
    """

    async def get(self, **kwargs) -> None:
        user_id = self.require_user()
        provider = self.require_provider()
        repo_path = self.get_argument("repo_path", "")

        if not repo_path:
            self.write_json(
                {"error": "missing_repo_path", "detail": "repo_path query param required"},
                status=400,
            )
            return

        token_key = self._token_key(provider.name, user_id)
        try:
            stored = await self.token_store.load_token(token_key)
        except Exception as exc:
            self.write_json({"error": "store_error", "detail": str(exc)}, status=500)
            return

        if not stored or not stored.get("access_token"):
            self.write_json(
                {"error": "not_connected", "detail": f"Connect to {provider.display_name} first"},
                status=401,
            )
            return

        try:
            prov_user = await self.broker.get_user(
                provider.userinfo_endpoint,
                stored["access_token"],
                username_field=provider.username_field,
                email_field=provider.email_field,
                name_field=provider.name_field,
            )
        except Exception as exc:
            self.write_json({"error": "provider_error", "detail": str(exc)}, status=502)
            return

        from .identity_sync import IdentitySync

        identity_sync = IdentitySync()
        validation = identity_sync.validate_git_identity(repo_path, prov_user)

        self.write_json(
            {
                "valid": validation.valid,
                "current_name": validation.current_name,
                "current_email": validation.current_email,
                "provider_name": prov_user.name,
                "provider_email": prov_user.email,
                "is_placeholder": validation.is_placeholder,
            }
        )


# ---------------------------------------------------------------------------
# GET /api/oauth-providers/credential
# ---------------------------------------------------------------------------


class CredentialHandler(_BaseOAuthHandler):
    """
    Returns the OAuth access token for the git-credential helper.

    Called by the credential helper subprocess running in the same pod.
    The helper calls localhost:8888 directly, bypassing the Kubeflow auth
    proxy, so identity headers are not present on these requests.

    Trust model:
      - Kubeflow Notebook pods are single-user. The pod-level user identity
        is cached in settings after the first proxied JupyterLab request.
      - Localhost callers are trusted to be that pod user.
      - Non-localhost callers must provide a valid identity header.

    Query params:
      provider=<name>   — required if more than one provider is active

    Response 200:
      { "username": "oauth2", "password": "<access_token>" }

    Response 401: not connected or token refresh failed
    Response 403: not localhost and no valid user header
    """

    _LOCALHOST_IPS = frozenset(("127.0.0.1", "::1", "::ffff:127.0.0.1"))

    def _resolve_user_for_credential(self) -> str | None:
        user = self.resolve_current_user()
        if user:
            return user
        if self.request.remote_ip in self._LOCALHOST_IPS:
            return self.settings.get("oauth_pod_user")
        return None

    def _resolve_provider_for_credential(self) -> ProviderConfig | None:
        overrides = self.settings.get("oauth_provider_overrides", {})
        name = self.get_argument("provider", "")
        if name:
            return get_provider(name, overrides)
        # Default to the only active provider when exactly one is configured.
        active = get_active_providers(overrides)
        if len(active) == 1:
            return next(iter(active.values()))
        return None

    @staticmethod
    def _token_needs_refresh(expires_at: str) -> bool:
        if not expires_at:
            return False
        try:
            from datetime import datetime, timezone

            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
            return remaining < 120
        except Exception:
            return False

    async def get(self) -> None:
        user_id = self._resolve_user_for_credential()

        if not user_id:
            is_local = self.request.remote_ip in self._LOCALHOST_IPS
            if not is_local:
                self.write_json(
                    {
                        "error": "forbidden",
                        "detail": (
                            "Credential endpoint is only accessible from localhost "
                            "or with a valid user identity header."
                        ),
                    },
                    status=403,
                )
            else:
                self.write_json(
                    {
                        "error": "unauthenticated",
                        "detail": (
                            "Pod user identity not yet cached. "
                            "Open JupyterLab in the browser first."
                        ),
                    },
                    status=401,
                )
            return

        provider = self._resolve_provider_for_credential()
        if provider is None:
            self.write_json(
                {
                    "error": "provider_required",
                    "detail": (
                        "Multiple providers are active. "
                        "Pass ?provider=<name> to select one."
                    ),
                },
                status=400,
            )
            return

        token_key = self._token_key(provider.name, user_id)
        try:
            stored = await self.token_store.load_token(token_key)
        except Exception as exc:
            self.write_json({"error": "store_error", "detail": str(exc)}, status=500)
            return

        if not stored or not stored.get("access_token"):
            self.write_json(
                {
                    "error": "not_connected",
                    "detail": (
                        f"{provider.display_name} not connected. "
                        "Open JupyterLab and authenticate via the sidebar."
                    ),
                },
                status=401,
            )
            return

        access_token = stored["access_token"]

        if self._token_needs_refresh(stored.get("expires_at", "")):
            refresh_token = stored.get("refresh_token", "")
            if refresh_token and provider.token_endpoint:
                try:
                    new_tokens = await self.broker.refresh_access_token(
                        provider.token_endpoint, provider.client_id, refresh_token
                    )
                    updated = {**stored, **new_tokens.to_dict()}
                    await self.token_store.save_token(token_key, updated)
                    access_token = new_tokens.access_token
                    self.audit.emit(
                        "token_refreshed",
                        jupyter_user_id=user_id,
                        provider=provider.name,
                        result="success",
                        action="credential_helper_refresh",
                    )
                except Exception as exc:
                    self.audit.emit(
                        "token_refresh_failed",
                        jupyter_user_id=user_id,
                        provider=provider.name,
                        result="failed",
                        error=str(exc),
                    )
                    self.write_json(
                        {
                            "error": "token_expired",
                            "reconnect_required": True,
                            "detail": (
                                f"{provider.display_name} token expired and refresh failed. "
                                "Reconnect in JupyterLab."
                            ),
                        },
                        status=401,
                    )
                    return

        self.audit.emit(
            "git_action_preflight",
            jupyter_user_id=user_id,
            provider=provider.name,
            provider_user_id=str(stored.get("provider_user_id", "")),
            action="credential_helper_get",
            result="provided",
        )

        self.write_json({"username": "oauth2", "password": access_token})
