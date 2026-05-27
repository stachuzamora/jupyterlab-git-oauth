"""
Provider registry — discovers and returns active providers.

A provider is active if its required env vars are set OR if UI-supplied
overrides contain enough information to build a valid config.

UI overrides are stored in Tornado settings under 'oauth_provider_overrides'
as a dict keyed by provider name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import ProviderConfig
from . import gitlab, github

if TYPE_CHECKING:
    pass

_BUILDERS = [gitlab.build, github.build]


def get_active_providers(
    overrides: dict[str, dict] | None = None,
) -> dict[str, ProviderConfig]:
    """
    Return a dict of {provider_name: ProviderConfig} for all active providers.

    Providers are tried in order: GitLab, GitHub.
    A provider is active if its builder returns a non-None config.
    """
    result: dict[str, ProviderConfig] = {}
    overrides = overrides or {}

    for build in _BUILDERS:
        # Pass any UI-stored overrides for this provider
        # (builder name → provider name derived from the module)
        module_name = build.__module__.rsplit(".", 1)[-1]
        provider_overrides = overrides.get(module_name, {})
        config = build(provider_overrides)
        if config is not None:
            result[config.name] = config

    return result


def get_provider(
    name: str,
    overrides: dict[str, dict] | None = None,
) -> ProviderConfig | None:
    """Return a single provider by name, or None if not active."""
    return get_active_providers(overrides).get(name)
