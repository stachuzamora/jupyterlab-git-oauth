"""
jupyter_server_oauth_providers
==============================

Jupyter Server extension providing a multi-provider OAuth 2.0 Device
Authorization Grant broker (GitLab, GitHub, Gitea).

Extension entry point
---------------------
Jupyter Server 2.x discovers extensions via the
`jupyter_server.extension.entry_points` group in pyproject.toml which
points here.  The `_load_jupyter_server_extension` function (alias:
`load_jupyter_server_extension`) is the legacy hook still used by some
tooling; both are exported.
"""

from __future__ import annotations

from .app import OAuthProvidersExtensionApp


def _jupyter_server_extension_points():
    """Jupyter Server 2.x discovery hook."""
    return [{"module": "jupyter_server_oauth_providers", "app": OAuthProvidersExtensionApp}]


def _load_jupyter_server_extension(server_app) -> None:  # noqa: ANN001
    """Legacy hook — no-op; Jupyter Server 2.x uses _jupyter_server_extension_points."""
    pass


load_jupyter_server_extension = _load_jupyter_server_extension

__all__ = [
    "OAuthProvidersExtensionApp",
    "_jupyter_server_extension_points",
    "load_jupyter_server_extension",
    "_load_jupyter_server_extension",
]

__version__ = "0.1.0"
