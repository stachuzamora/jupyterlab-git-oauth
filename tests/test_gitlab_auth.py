from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jupyter_server_oauth_providers.handlers import CredentialHandler
from jupyterlab_git.handlers import GitHandler


async def _call(settings, headers):
    handler = SimpleNamespace(
        settings=settings,
        request=SimpleNamespace(headers=headers),
    )
    return await GitHandler._get_gitlab_auth(handler)


@pytest.mark.asyncio
async def test_returns_none_when_no_store():
    assert await _call({}, {}) is None


@pytest.mark.asyncio
async def test_returns_none_when_no_user_header():
    store = AsyncMock()
    assert await _call({"oauth_token_store": store}, {}) is None
    store.load_token.assert_not_called()


@pytest.mark.asyncio
async def test_returns_credentials_for_connected_gitlab_user():
    store = AsyncMock()
    store.load_token = AsyncMock(
        return_value={"access_token": "glpat-abc", "provider_username": "jdoe"}
    )
    result = await _call(
        {"oauth_token_store": store},
        {"kubeflow-userid": "jdoe@example.com"},
    )
    assert result == {"username": "jdoe", "password": "glpat-abc"}


@pytest.mark.asyncio
async def test_falls_back_to_github_if_gitlab_not_connected():
    async def load_token(key):
        if key.startswith("gitlab:"):
            return None
        return {"access_token": "ghu_token", "provider_username": "jdoe"}

    store = AsyncMock()
    store.load_token = load_token
    result = await _call(
        {"oauth_token_store": store},
        {"X-Auth-Request-User": "jdoe"},
    )
    assert result == {"username": "jdoe", "password": "ghu_token"}


@pytest.mark.asyncio
async def test_returns_none_when_not_connected():
    store = AsyncMock()
    store.load_token = AsyncMock(return_value=None)
    assert await _call({"oauth_token_store": store}, {"X-Forwarded-User": "u@x.com"}) is None


@pytest.mark.asyncio
async def test_header_priority_kubeflow_over_x_auth():
    store = AsyncMock()
    store.load_token = AsyncMock(return_value={"access_token": "tok", "provider_username": "u"})
    await _call(
        {"oauth_token_store": store},
        {"kubeflow-userid": "primary@x.com", "X-Auth-Request-User": "secondary@x.com"},
    )
    first_key = store.load_token.call_args_list[0].args[0]
    assert "primary@x.com" in first_key


# --- CredentialHandler._token_needs_refresh (pure static, no server) ---

@pytest.mark.parametrize("value,expected", [
    ("", False),
    ("2099-01-01T00:00:00+00:00", False),
    ("2020-01-01T00:00:00+00:00", True),
    ("not-a-date", False),
    ("2020-06-01T00:00:00Z", True),
])
def test_token_needs_refresh(value, expected):
    assert CredentialHandler._token_needs_refresh(value) == expected
