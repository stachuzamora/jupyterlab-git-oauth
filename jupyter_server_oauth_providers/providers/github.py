"""
GitHub provider — always github.com, no URL config needed.

Env vars:
  GITHUB_CLIENT_ID   required
  GITHUB_SCOPES      optional, defaults to DEFAULT_SCOPES

Note: GitHub device flow uses a slightly different response shape than
RFC 8628 (interval is in the top-level response, not as a JSON key).
The auth_broker handles this transparently.
"""

from __future__ import annotations

import os

from .base import ProviderConfig

DEFAULT_SCOPES = "repo read:user"
BASE_URL = "https://github.com"


def build(overrides: dict | None = None) -> ProviderConfig | None:
    overrides = overrides or {}

    client_id = os.environ.get("GITHUB_CLIENT_ID") or overrides.get("client_id", "")
    if not client_id:
        return None

    scopes = (
        os.environ.get("GITHUB_SCOPES")
        or overrides.get("scopes", "")
        or DEFAULT_SCOPES
    )

    return ProviderConfig(
        name="github",
        display_name="GitHub",
        client_id=client_id,
        scopes=scopes,
        base_url=BASE_URL,
        external_url=BASE_URL,
        device_auth_endpoint="https://github.com/login/device/code",
        token_endpoint="https://github.com/login/oauth/access_token",
        userinfo_endpoint="https://api.github.com/user",
        username_field="login",
        email_field="email",
        name_field="name",
        meta={"color": "#24292e", "icon": "github"},
    )
