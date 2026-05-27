"""
Provider base — shared dataclass and interface for all OAuth providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderConfig:
    """
    All configuration required to run the device flow for one provider.

    Required env vars per provider:
      GitLab:  GITLAB_CLIENT_ID  (+ optionally GITLAB_URL, defaults to gitlab.com)
      GitHub:  GITHUB_CLIENT_ID
      Gitea:   GITEA_URL + GITEA_CLIENT_ID

    Any provider whose required vars are absent is simply not activated.
    """

    # Unique machine name — used in API routes and token store keys.
    name: str

    # Human-readable label shown in the UI.
    display_name: str

    # OAuth application client ID.
    client_id: str

    # Space-separated scopes to request.
    scopes: str

    # Base URL of the provider (e.g. "https://gitlab.com").
    # Used for server-side API calls and as the device flow base.
    base_url: str

    # URL shown to users in prompts (may differ from base_url when the
    # internal URL uses a cluster-internal hostname).
    external_url: str = ""

    # RFC 8628 device authorization endpoint (absolute URL).
    device_auth_endpoint: str = ""

    # Token endpoint (absolute URL).
    token_endpoint: str = ""

    # User info endpoint (absolute URL, returns JSON with user profile).
    userinfo_endpoint: str = ""

    # JSON key in the userinfo response that holds the login/username.
    username_field: str = "username"

    # JSON key in the userinfo response that holds the email address.
    email_field: str = "email"

    # JSON key for the display name. Empty string means fall back to username.
    name_field: str = "name"

    # Token revocation endpoint (absolute URL). Empty means revocation is skipped.
    revoke_endpoint: str = ""

    # Whether this provider supports RFC 8628 device authorization grant.
    # False means the UI should offer a PAT (personal access token) input instead.
    supports_device_flow: bool = True

    # Extra per-provider metadata (logo colour, icon name, etc.)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.external_url:
            self.external_url = self.base_url
