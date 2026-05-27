"""
OAuth Providers Extension Application
======================================

Registers all URL handlers. Providers are activated by the presence of
their env vars at startup, or by UI-supplied overrides stored via the
/api/oauth-providers/<provider>/config endpoint.
"""

from __future__ import annotations

import shutil
import subprocess

from jupyter_server.extension.application import ExtensionApp
from jupyter_server.utils import url_path_join

from .handlers import (
    CredentialHandler,
    DevicePollHandler,
    DeviceStartHandler,
    DisconnectHandler,
    IdentitySyncHandler,
    IdentityValidateHandler,
    ProviderConfigHandler,
    ProvidersListHandler,
    StatusHandler,
)
from .providers import get_active_providers
from .token_store import create_token_store


class OAuthProvidersExtensionApp(ExtensionApp):
    """Jupyter Server extension providing multi-provider OAuth device flow."""

    name = "jupyter_server_oauth_providers"
    extension_url = "/api/oauth-providers"
    load_other_extensions = True

    def initialize_settings(self) -> None:
        self.settings["oauth_token_store"] = create_token_store()
        if "oauth_provider_overrides" not in self.settings:
            self.settings["oauth_provider_overrides"] = {}

        active = get_active_providers(self.settings["oauth_provider_overrides"])
        self.log.info(
            "[oauth-providers] Active providers: %s",
            list(active.keys()) or "(none — set provider env vars)",
        )

        self._configure_git_credential_helper()

    def _configure_git_credential_helper(self) -> None:
        helper = "jupyterlab-oauth"
        binary = shutil.which("git-credential-jupyterlab-oauth")
        if binary is None:
            self.log.debug("[oauth-providers] git-credential-jupyterlab-oauth not in PATH, skipping git config")
            return
        try:
            result = subprocess.run(
                ["git", "config", "--global", "credential.helper", helper],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                self.log.info("[oauth-providers] git credential.helper set to %r", helper)
            else:
                self.log.warning("[oauth-providers] git config failed: %s", result.stderr.decode())
        except Exception as exc:
            self.log.warning("[oauth-providers] could not configure git credential helper: %s", exc)

    def initialize_handlers(self) -> None:
        base = self.extension_url
        url = lambda s: url_path_join(base, s)  # noqa: E731

        self.handlers = [
            (url(r"/providers"),                                    ProvidersListHandler),
            (url(r"/(?P<provider>[^/]+)/config"),                   ProviderConfigHandler),
            (url(r"/(?P<provider>[^/]+)/status"),                   StatusHandler),
            (url(r"/(?P<provider>[^/]+)/device/start"),             DeviceStartHandler),
            (url(r"/(?P<provider>[^/]+)/device/poll"),              DevicePollHandler),
            (url(r"/(?P<provider>[^/]+)/disconnect"),               DisconnectHandler),
            (url(r"/(?P<provider>[^/]+)/identity/sync"),            IdentitySyncHandler),
            (url(r"/(?P<provider>[^/]+)/identity/validate"),        IdentityValidateHandler),
            (url(r"/credential"),                                   CredentialHandler),
        ]

        self.log.info(
            "[oauth-providers] Registered %d endpoints under %s",
            len(self.handlers), base,
        )
