[![Publish to PyPI](https://github.com/stachuzamora/jupyterlab-git-oauth/actions/workflows/publish.yml/badge.svg)](https://github.com/stachuzamora/jupyterlab-git-oauth/actions/workflows/publish.yml)
[![Publish to TestPyPI](https://github.com/stachuzamora/jupyterlab-git-oauth/actions/workflows/publish-test.yml/badge.svg)](https://github.com/stachuzamora/jupyterlab-git-oauth/actions/workflows/publish-test.yml)
[![CI](https://github.com/stachuzamora/jupyterlab-git-oauth/actions/workflows/ci.yml/badge.svg)](https://github.com/stachuzamora/jupyterlab-git-oauth/actions/workflows/ci.yml)
# jupyterlab-git-oauth

JupyterLab Git extension with OAuth 2.0 Device Authorization Grant for GitLab and GitHub. Designed for Kubeflow Notebooks and JupyterHub environments where users are identified by OIDC/SSO headers rather than local Unix accounts.

## What it is

A single pip package that replaces [`jupyterlab-git`](https://github.com/jupyterlab/jupyterlab-git) with:

- **OAuth device flow** — authenticate to GitLab and GitHub directly from JupyterLab's status bar; no password or personal access token required
- **OIDC author injection** — automatically sets git `user.name` and `user.email` from the Kubeflow/OIDC user header on every commit
- **Git credential helper** — `git-credential-jupyterlab-oauth` lets terminal git operations reuse the same OAuth token without re-prompting
- **Token refresh** — background broker keeps access tokens fresh across long-running notebook sessions

## Why it exists

In Kubeflow Notebooks, every pod runs as the same `jovyan` user, but the actual person is identified by an OIDC header injected by `oauth2-proxy` (e.g., `kubeflow-userid`). Stock `jupyterlab-git`:

- doesn't know how to read OAuth tokens from a JupyterHub-managed store
- uses the pod's Unix identity for git author, not the OIDC user
- has no device flow UI

This package patches the two files that matter (`jupyterlab_git/handlers.py`, `jupyterlab_git/git.py`) and bundles a Jupyter Server extension providing the OAuth device flow API.

## Fork basis

Forked from [`jupyterlab-git` 0.52.0](https://github.com/jupyterlab/jupyterlab-git).  
The upstream labextension TypeScript and the fork Python patches are combined into a single installable wheel — no separate installs, no version mismatches.

## Features

| Feature | GitLab | GitHub |
|---------|--------|--------|
| Device Authorization Grant (RFC 8628) | ✓ | ✓ |
| Token refresh | ✓ | ✓ |
| OIDC author injection | ✓ | ✓ |
| Status bar widget | ✓ | ✓ |
| Git credential helper | ✓ | ✓ |

## Requirements

**GitLab**

Create an OAuth application (`Admin Area → Applications` or group/user settings) with:
- Grant type: **Device Authorization Code**
- Scopes: `read_user`, `read_repository`, `write_repository`

**GitHub**

Create an OAuth App (`Settings → Developer settings → OAuth Apps`) with device flow enabled (check "Enable Device Flow" in app settings).

## Installation

```bash
pip install jupyterlab-git-oauth
```

This installs the labextension, the Jupyter Server extension, and the `git-credential-jupyterlab-oauth` helper into PATH. The server extension auto-enables itself; no `jupyter server extension enable` step is needed.

## Configuration

Set environment variables before starting Jupyter:

| Variable | Default | Description |
|----------|---------|-------------|
| `GITLAB_CLIENT_ID` | _(none — GitLab disabled)_ | GitLab application client ID |
| `GITLAB_URL` | `https://gitlab.com` | GitLab instance URL (for self-hosted: `https://gitlab.example.com`) |
| `GITHUB_CLIENT_ID` | _(none — GitHub disabled)_ | GitHub OAuth app client ID |

A provider is only activated when its `CLIENT_ID` variable is set.

## Usage

1. Open JupyterLab — the status bar shows **"GitLab: Not connected"**
2. Click the status bar item → a device code is displayed in a dialog
3. Open the authorization URL, enter the code → the dialog confirms success
4. The status bar turns green; git clone / pull / push work from the JupyterLab UI

Terminal git operations also work without re-prompting. The credential helper is auto-configured on Jupyter Server startup (`git config --global credential.helper jupyterlab-oauth`).

To disconnect: click the status bar item again and choose **Disconnect**.

## Docker image

```dockerfile
FROM your-jupyter-base-image
RUN pip install jupyterlab-git-oauth

ENV GITLAB_CLIENT_ID=your-application-client-id
ENV GITLAB_URL=https://gitlab.example.com
# Optional: ENV GITHUB_CLIENT_ID=your-github-app-client-id
```

## Development setup

Requirements: Python 3.9+, Node.js 20+

```bash
git clone https://github.com/stachuzamora/jupyterlab-git-oauth.git
cd jupyterlab-git-oauth

# Install JS dependencies and build the labextension
yarn install
yarn run build:prod

# Install the Python package in editable mode
pip install -e .

# Start Jupyter with provider env vars
GITLAB_CLIENT_ID=abc123 GITLAB_URL=https://gitlab.example.com jupyter lab
```

To watch TypeScript changes during development:

```bash
# Terminal 1
yarn watch

# Terminal 2
jupyter lab
```

## License

BSD-3-Clause — see [LICENSE](LICENSE).  
Upstream [`jupyterlab-git`](https://github.com/jupyterlab/jupyterlab-git) is also BSD-3-Clause.
