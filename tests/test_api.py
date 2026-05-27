"""
Tier 2 integration tests — require a running Jupyter Server with the extension loaded.

Setup:
    pip install -e ".[dev]"   (after building the labextension)
    pytest tests/test_api.py

These are excluded from the standard CI run (no labextension build there).
"""

import json

import pytest

pytest_plugins = ("pytest_jupyter.jupyter_server",)


@pytest.fixture
def jp_server_config():
    return {
        "ServerApp": {
            "jpserver_extensions": {"jupyter_server_oauth_providers": True}
        }
    }


@pytest.mark.anyio
async def test_providers_list_empty(jp_fetch, monkeypatch):
    monkeypatch.delenv("GITLAB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    resp = await jp_fetch("api/oauth-providers/providers")
    data = json.loads(resp.body)
    assert "providers" in data
    assert data["providers"] == []


@pytest.mark.anyio
async def test_providers_list_with_gitlab(jp_fetch, monkeypatch):
    monkeypatch.setenv("GITLAB_CLIENT_ID", "test-client-id")
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    resp = await jp_fetch("api/oauth-providers/providers")
    data = json.loads(resp.body)
    names = [p["name"] for p in data["providers"]]
    assert "gitlab" in names


@pytest.mark.anyio
async def test_providers_list_response_shape(jp_fetch, monkeypatch):
    monkeypatch.delenv("GITLAB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    resp = await jp_fetch("api/oauth-providers/providers")
    data = json.loads(resp.body)
    assert "topbar_enabled" in data


@pytest.mark.anyio
async def test_credential_endpoint_no_user_returns_401(jp_fetch):
    resp = await jp_fetch(
        "api/oauth-providers/credential",
        raise_error=False,
    )
    assert resp.code in (401, 403)
