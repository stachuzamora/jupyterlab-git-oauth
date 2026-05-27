# Summary

## What this is

Single pip package (`jupyterlab-git-oauth`) that replaces `jupyterlab-git` with OAuth 2.0 Device Authorization Grant for GitLab and GitHub. Designed for Kubeflow Notebooks where users are identified by OIDC headers.

Fork base: `jupyterlab-git` 0.52.0

## Components

| Package | Purpose |
|---------|---------|
| `jupyterlab_git/` | Fork of jupyterlab-git — `handlers.py` injects OAuth token into git ops via `_get_gitlab_auth()`; `git.py` injects OIDC author identity into commits via `GIT_COMMITTER_NAME/EMAIL` env vars |
| `jupyter_server_oauth_providers/` | Jupyter Server extension — device flow broker, token store, REST API (`/api/oauth-providers/*`) |
| `git-credential-jupyterlab-oauth` | Console script (credential helper) — enables `git clone/push/pull` in the terminal using the same OAuth token; auto-configured at Jupyter Server startup |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GITLAB_CLIENT_ID` | — | Activates GitLab provider |
| `GITLAB_URL` | `https://gitlab.com` | GitLab instance URL |
| `GITHUB_CLIENT_ID` | — | Activates GitHub provider |

## Changelog

### [unreleased]

- Added `LICENSE` (BSD-3-Clause), `README.md`, `SUMMARY.md`
- Added GitHub Actions: `ci.yml` (lint + unit tests + build check), `publish.yml` (PyPI via OIDC), `upstream-check.yml` (weekly upstream release alert)
- Added `[project.urls]` and `bugs`/`repository`/`author` to package metadata
- Added `hatch_build.py` — custom build hook that fetches upstream-only Python files (`ssh.py`) from `jupyterlab/jupyterlab-git@v0.52.0` at build time; cleans them up after the wheel is produced; repo stays clean
- Added unit tests (38 total, all green):
  - `test_credential_helper` — URL/token discovery, stdin parsing
  - `test_providers` — provider activation from env vars
  - `test_token_store` — MemoryStore save/load/delete
  - `test_git_author` — commit author injection (our patch to `git.py`)
  - `test_gitlab_auth` — `_get_gitlab_auth()` header priority + fallback (our patch to `handlers.py`), `_token_needs_refresh` static method
- Added Tier 2 integration tests: `test_api` (requires built labextension; excluded from CI unit-test run)
- `tests/conftest.py` stubs `jupyterlab_git.ssh` and `jupyterlab_git._version` (upstream-only files) so our patches can be imported and tested
- Added `[project.optional-dependencies] dev` and `[tool.pytest.ini_options]` to `pyproject.toml`
- CI `test-python` job uses `HATCH_BUILD_HOOKS_ENABLE=false` + `PYTHONPATH=.` to skip JS build

### [0.52.0] — initial

- Consolidated `jupyter-server-oauth-providers` + `jupyterlab-git` fork into single package
- Dropped Gitea; providers: GitLab and GitHub only
- Added `git-credential-jupyterlab-oauth` console script; auto-configured at startup
- Extension auto-enabled via JSON config in `jupyter_server_config.d/`

## TODO

- UI-based config (traitlets + JupyterLab settings schema) — see `TODO.md`
- Python tests for `auth_broker.py`, `identity_sync.py`, `handlers.py` (device flow endpoints)
- Tier 2 integration tests in CI (blocked on building labextension in the test job)
