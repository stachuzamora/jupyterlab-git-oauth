# TODO

## Python version compatibility

Currently `requires-python = ">=3.9"` but CI only tests 3.11. Either:
- Tighten to `>=3.11` (matches actual target: Kubeflow/JupyterHub)
- Or add a matrix to CI: `python-version: ["3.11", "3.12"]`

## UI-based provider configuration

Currently the only way to configure providers is via environment variables
(`GITLAB_CLIENT_ID`, `GITLAB_URL`, `GITHUB_CLIENT_ID`). This is fine for
Docker/Kubernetes but breaks the Extension Manager install story — a user who
installs from the JupyterLab UI has no way to supply those vars.

### What's needed

**Server side — traitlets on `OAuthProvidersExtensionApp`:**

```python
class OAuthProvidersExtensionApp(ExtensionApp):
    gitlab_client_id = Unicode("", config=True)
    gitlab_url       = Unicode("https://gitlab.com", config=True)
    github_client_id = Unicode("", config=True)
```

Traitlets are read from `~/.jupyter/jupyter_server_config.py`:

```python
c.OAuthProvidersExtensionApp.gitlab_client_id = "abc123"
c.OAuthProvidersExtensionApp.gitlab_url = "https://gitlab.example.com"
```

Priority order should be: traitlets → env vars → defaults.

**Frontend side — JupyterLab settings schema:**

Add a `schema/oauth-providers.json` settings schema so users can configure
client IDs from *Settings → Settings Editor* in the JupyterLab UI. The
frontend posts these to `/api/oauth-providers/<provider>/config` on save,
which stores them in `oauth_provider_overrides` in Tornado settings.
The `/api/oauth-providers/providers` endpoint already reads from overrides —
this path is mostly wired, just needs the settings schema and a save handler
in the frontend.
