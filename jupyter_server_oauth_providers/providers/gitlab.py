"""
GitLab provider — supports both gitlab.com and self-managed instances.

Env vars:
  GITLAB_CLIENT_ID   required
  GITLAB_URL         optional, defaults to https://gitlab.com
  GITLAB_EXTERNAL_URL optional, shown to users when internal URL differs
  GITLAB_SCOPES      optional, defaults to DEFAULT_SCOPES
"""

from __future__ import annotations

import os

from .base import ProviderConfig

DEFAULT_SCOPES = "read_repository write_repository read_user"
DEFAULT_URL = "https://gitlab.com"


def build(overrides: dict | None = None) -> ProviderConfig | None:
    """
    Return a GitLab ProviderConfig if GITLAB_CLIENT_ID is set, else None.

    `overrides` may supply any ProviderConfig field — UI-configured values
    take effect here so long as env vars don't override them.
    """
    overrides = overrides or {}

    client_id = os.environ.get("GITLAB_CLIENT_ID") or overrides.get("client_id", "")
    if not client_id:
        return None

    base_url = (
        os.environ.get("GITLAB_URL")
        or overrides.get("base_url", "")
        or DEFAULT_URL
    ).rstrip("/")

    external_url = (
        os.environ.get("GITLAB_EXTERNAL_URL")
        or overrides.get("external_url", "")
        or base_url
    )

    scopes = (
        os.environ.get("GITLAB_SCOPES")
        or overrides.get("scopes", "")
        or DEFAULT_SCOPES
    )

    return ProviderConfig(
        name="gitlab",
        display_name="GitLab",
        client_id=client_id,
        scopes=scopes,
        base_url=base_url,
        external_url=external_url,
        device_auth_endpoint=f"{base_url}/oauth/authorize_device",
        token_endpoint=f"{base_url}/oauth/token",
        revoke_endpoint=f"{base_url}/oauth/revoke",
        userinfo_endpoint=f"{base_url}/api/v4/user",
        username_field="username",
        email_field="email",
        name_field="name",
        meta={"color": "#FC6D26", "icon": "gitlab"},
    )
