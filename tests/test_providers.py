import pytest

from jupyter_server_oauth_providers.providers.github import build as github_build
from jupyter_server_oauth_providers.providers.gitlab import build as gitlab_build
from jupyter_server_oauth_providers.providers.registry import get_active_providers


def test_gitlab_build_returns_none_without_env(monkeypatch):
    monkeypatch.delenv("GITLAB_CLIENT_ID", raising=False)
    assert gitlab_build() is None


def test_gitlab_build_returns_config_with_client_id(monkeypatch):
    monkeypatch.setenv("GITLAB_CLIENT_ID", "test-id")
    cfg = gitlab_build()
    assert cfg is not None
    assert cfg.client_id == "test-id"
    assert cfg.base_url == "https://gitlab.com"


def test_gitlab_build_respects_custom_url(monkeypatch):
    monkeypatch.setenv("GITLAB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    cfg = gitlab_build()
    assert cfg.base_url == "https://gitlab.example.com"
    assert "gitlab.example.com" in cfg.device_auth_endpoint


def test_github_build_returns_none_without_env(monkeypatch):
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    assert github_build() is None


def test_github_build_returns_config_with_client_id(monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "gh-client-id")
    cfg = github_build()
    assert cfg is not None
    assert cfg.client_id == "gh-client-id"


def test_get_active_providers_empty_when_no_env(monkeypatch):
    monkeypatch.delenv("GITLAB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    assert get_active_providers() == {}


def test_get_active_providers_gitlab_only(monkeypatch):
    monkeypatch.setenv("GITLAB_CLIENT_ID", "glab-id")
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    result = get_active_providers()
    assert "gitlab" in result
    assert "github" not in result


def test_get_active_providers_both(monkeypatch):
    monkeypatch.setenv("GITLAB_CLIENT_ID", "glab-id")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "gh-id")
    result = get_active_providers()
    assert "gitlab" in result
    assert "github" in result
