#!/usr/bin/env python3
"""
git-credential-gitlab — Git credential helper for Jupyter/GitLab auth.

Implements the Git credential helper protocol (gitcredentials(7)).
Reads one action from argv[1]: get | store | erase.

For 'get':
  1. Discovers the Jupyter Server URL.
  2. Discovers the Jupyter auth token.
  3. Calls GET /api/gitlab-auth/status.
  4. If connected, writes:
       username=oauth2
       password=<access_token>
  5. If not connected, exits 1 with a user-visible error message.

For 'store': no-op (the backend manages token storage).
For 'erase': calls POST /api/gitlab-auth/disconnect.

The helper respects the following environment variables:
  JUPYTER_SERVER_URL   — override the Jupyter Server URL (no trailing slash)
  JUPYTER_TOKEN        — Jupyter auth token (overrides runtime JSON discovery)
  GIT_CREDENTIAL_GITLAB_DEBUG  — set to "1" for verbose debug output

Exit codes:
  0 — success (for 'get': credentials written to stdout)
  1 — could not provide credentials (git will prompt the user)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEBUG = os.environ.get("GIT_CREDENTIAL_GITLAB_DEBUG", "0") == "1"
DEFAULT_JUPYTER_PORT = 8888
MAX_RETRIES = 2
RETRY_BACKOFF_S = 1.0
REQUEST_TIMEOUT_S = 8.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _debug(msg: str) -> None:
    if DEBUG:
        print(f"[git-credential-gitlab] DEBUG: {msg}", file=sys.stderr)


def _error(msg: str) -> None:
    print(f"git-credential-gitlab: {msg}", file=sys.stderr)


def _fatal(msg: str) -> None:
    _error(msg)
    sys.exit(1)


def _discover_jupyter_url() -> str:
    """Return the Jupyter Server base URL (no trailing slash)."""
    # 1. Explicit env var
    url = os.environ.get("JUPYTER_SERVER_URL", "")
    if url:
        return url.rstrip("/")

    # 2. Try to read from runtime JSON (most accurate)
    for candidate in _runtime_json_candidates():
        try:
            with open(candidate) as f:
                data = json.load(f)
            url = data.get("url", "")
            if url:
                _debug(f"Found URL in runtime JSON {candidate}: {url}")
                return url.rstrip("/")
        except (OSError, json.JSONDecodeError):
            continue

    # 3. Fall back to localhost with default port
    port = _detect_jupyter_port()
    return f"http://localhost:{port}"


def _detect_jupyter_port() -> int:
    """Try to guess the port from runtime JSON or fall back to 8888."""
    for candidate in _runtime_json_candidates():
        try:
            with open(candidate) as f:
                data = json.load(f)
            port = data.get("port", 0)
            if port:
                return int(port)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return DEFAULT_JUPYTER_PORT


def _runtime_json_candidates() -> list[str]:
    """Return paths to likely Jupyter runtime JSON files."""
    candidates: list[str] = []
    home = Path.home()

    dirs = [
        home / ".local" / "share" / "jupyter" / "runtime",
        Path("/tmp/jupyter_runtime"),
        Path(f"/run/user/{os.getuid()}/jupyter")
        if hasattr(os, "getuid")
        else Path("/tmp"),
    ]

    for d in dirs:
        if d.is_dir():
            # Sort by mtime descending (most recent first)
            json_files = sorted(
                d.glob("*.json"),
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )
            candidates.extend(str(p) for p in json_files)

    return candidates


def _discover_jupyter_token() -> str:
    """Return the Jupyter auth token, or '' if not required."""
    # 1. Explicit env var
    token = os.environ.get("JUPYTER_TOKEN", "")
    if token:
        _debug(f"Using JUPYTER_TOKEN env var: {token[:8]}...")
        return token

    # 2. Runtime JSON
    for candidate in _runtime_json_candidates():
        try:
            with open(candidate) as f:
                data = json.load(f)
            tok = data.get("token", "")
            if tok:
                _debug(f"Found token in {candidate}: {tok[:8]}...")
                return tok
        except (OSError, json.JSONDecodeError):
            continue

    _debug("No Jupyter token found — assuming no-auth or cookie auth.")
    return ""


def _jupyter_get(url: str, token: str) -> dict:
    """
    HTTP GET the given URL with optional token auth.
    Returns parsed JSON dict.
    Raises urllib.error.URLError on network errors,
    raises RuntimeError on non-200 status.
    """
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"token {token}"

    req = urllib.request.Request(url, headers=headers, method="GET")

    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                body = resp.read()
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and not token:
                # Server requires auth but no token — surface a clear message
                raise RuntimeError(
                    "Jupyter Server requires authentication (HTTP 403). "
                    "Set JUPYTER_TOKEN or JUPYTER_SERVER_URL environment variable."
                ) from exc
            raise
        except (urllib.error.URLError, OSError) as exc:
            if attempt < MAX_RETRIES:
                _debug(f"Request failed (attempt {attempt + 1}), retrying: {exc}")
                time.sleep(RETRY_BACKOFF_S * (attempt + 1))
                continue
            raise

    # Unreachable but satisfies type checker
    raise RuntimeError("Exhausted retries")


def _jupyter_post(url: str, token: str, body: dict) -> dict:
    """HTTP POST JSON body to a Jupyter Server URL."""
    import urllib.request

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    # Attempt to read XSRF cookie from the runtime JSON
    xsrf = _read_xsrf_token()
    if xsrf:
        headers["X-XSRFToken"] = xsrf

    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        _debug(f"POST {url} failed HTTP {exc.code}: {body_bytes[:200]}")
        raise


def _read_xsrf_token() -> str:
    """
    Try to read the _xsrf token from Jupyter's cookie jar.
    This is a best-effort attempt; returns '' if not found.
    """
    # The credential helper runs outside the browser, so there's no cookie jar.
    # However, if the server is configured with token auth, the XSRF check
    # can be bypassed via the Authorization header.  Return empty string.
    return ""


def _read_stdin_credentials() -> dict[str, str]:
    """
    Parse git credential helper input from stdin.
    Format: key=value lines terminated by blank line.
    """
    creds: dict[str, str] = {}
    for line in sys.stdin:
        line = line.rstrip("\n\r")
        if not line:
            break
        if "=" in line:
            key, _, value = line.partition("=")
            creds[key.strip()] = value.strip()
    return creds


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def action_get() -> None:
    """
    Provide credentials for git.
    Called when git needs a username/password for an HTTPS operation.
    """
    creds = _read_stdin_credentials()
    _debug(f"Git requesting credentials for: {creds}")

    # Only handle GitLab URLs
    protocol = creds.get("protocol", "")

    if protocol and protocol not in ("http", "https"):
        _debug(f"Unsupported protocol '{protocol}' — not handling.")
        sys.exit(1)

    jupyter_url = _discover_jupyter_url()
    token = _discover_jupyter_token()

    _debug(f"Jupyter URL: {jupyter_url}")
    _debug(f"Token: {'<set>' if token else '<not set>'}")

    # /api/oauth-providers/credential handles token retrieval and refresh in one call.
    # It trusts localhost callers (this helper runs in the same pod as Jupyter Server).
    credential_url = f"{jupyter_url}/api/oauth-providers/credential?provider=gitlab"

    try:
        cred = _jupyter_get(credential_url, token)
    except urllib.error.URLError as exc:
        _error(
            f"Cannot reach Jupyter Server at {jupyter_url}: {exc}\n"
            f"  Hint: Is Jupyter running? Set JUPYTER_SERVER_URL if on a non-standard port."
        )
        sys.exit(1)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            try:
                body = json.loads(exc.read())
            except Exception:
                body = {}
            if body.get("reconnect_required"):
                _error(
                    "GitLab token has expired. Reconnect in JupyterLab:\n"
                    "  → Status bar → 'GitLab: Reconnect required' → click to reconnect"
                )
            elif body.get("error") == "unauthenticated":
                _error(
                    "Pod user identity not yet cached.\n"
                    "  Open JupyterLab in the browser first, then retry the git operation."
                )
            else:
                _error(
                    "GitLab not connected: open JupyterLab and click 'GitLab: Not connected'\n"
                    "  in the status bar to authorize this notebook."
                )
        elif exc.code == 403:
            _error("Credential endpoint rejected this request (not from localhost).")
        else:
            _error(f"Credential endpoint returned HTTP {exc.code}.")
        sys.exit(1)
    except RuntimeError as exc:
        _error(str(exc))
        sys.exit(1)

    _debug(f"Credential response keys: {list(cred.keys())}")

    access_token = cred.get("password", "")
    if not access_token:
        _error(
            "GitLab is connected but the access token could not be retrieved.\n"
            "Try disconnecting and reconnecting in JupyterLab."
        )
        sys.exit(1)

    # Write credentials to stdout in git credential helper format
    print("username=oauth2")
    print(f"password={access_token}")
    print("")  # blank line terminates the response
    _debug("Credentials provided to git.")


def action_store() -> None:
    """
    Called when git has successfully used a credential.
    We manage token storage in the backend — no-op here.
    """
    # Consume stdin to avoid broken pipe
    try:
        for _ in sys.stdin:
            pass
    except Exception:
        pass
    _debug("store action: no-op (backend manages storage).")


def action_erase() -> None:
    """
    Called when git determines a credential is bad (e.g., 401 response).
    We call the disconnect endpoint to clear stored tokens.
    """
    creds = _read_stdin_credentials()
    _debug(f"Erase called for: {creds}")

    jupyter_url = _discover_jupyter_url()
    token = _discover_jupyter_token()
    disconnect_url = f"{jupyter_url}/api/oauth-providers/gitlab/disconnect"

    try:
        result = _jupyter_post(disconnect_url, token, {})
        _debug(f"Disconnect result: {result}")
    except Exception as exc:
        _debug(f"Disconnect request failed (non-fatal): {exc}")

    _error(
        "GitLab credentials were rejected by the server.\n"
        "Your GitLab session has been cleared. Reconnect in JupyterLab."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2:
        _fatal(
            "Usage: git-credential-gitlab <get|store|erase>\n"
            "This is a git credential helper — do not invoke it directly.\n"
            "Configure it with: git config --global credential.helper 'gitlab'"
        )

    action = sys.argv[1].lower().strip()
    _debug(f"Action: {action}")

    if action == "get":
        action_get()
    elif action == "store":
        action_store()
    elif action == "erase":
        action_erase()
    else:
        _fatal(f"Unknown action: {action!r}")


if __name__ == "__main__":
    main()
