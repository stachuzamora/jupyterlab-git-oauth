import io
import json
from unittest.mock import patch

import pytest

from jupyter_server_oauth_providers.credential_helper import (
    _discover_jupyter_token,
    _discover_jupyter_url,
    _read_stdin_credentials,
)


def test_read_stdin_basic():
    data = "protocol=https\nhost=gitlab.example.com\nusername=oauth2\n\n"
    with patch("sys.stdin", io.StringIO(data)):
        result = _read_stdin_credentials()
    assert result == {"protocol": "https", "host": "gitlab.example.com", "username": "oauth2"}


def test_read_stdin_stops_at_blank_line():
    data = "protocol=https\n\nhost=should.not.appear\n"
    with patch("sys.stdin", io.StringIO(data)):
        result = _read_stdin_credentials()
    assert "host" not in result


def test_read_stdin_ignores_lines_without_equals():
    data = "not-a-kv-pair\nprotocol=https\n\n"
    with patch("sys.stdin", io.StringIO(data)):
        result = _read_stdin_credentials()
    assert result == {"protocol": "https"}


def test_discover_url_from_env(monkeypatch):
    monkeypatch.setenv("JUPYTER_SERVER_URL", "http://localhost:9999/")
    assert _discover_jupyter_url() == "http://localhost:9999"


def test_discover_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("JUPYTER_SERVER_URL", "https://jupyter.example.com/")
    assert _discover_jupyter_url() == "https://jupyter.example.com"


def test_discover_url_from_runtime_json(tmp_path, monkeypatch):
    monkeypatch.delenv("JUPYTER_SERVER_URL", raising=False)
    json_file = tmp_path / "nbserver-1234.json"
    json_file.write_text(json.dumps({"url": "http://localhost:7777", "token": "tok"}))
    with patch(
        "jupyter_server_oauth_providers.credential_helper._runtime_json_candidates",
        return_value=[str(json_file)],
    ):
        result = _discover_jupyter_url()
    assert result == "http://localhost:7777"


def test_discover_url_fallback_default_port(monkeypatch):
    monkeypatch.delenv("JUPYTER_SERVER_URL", raising=False)
    with patch(
        "jupyter_server_oauth_providers.credential_helper._runtime_json_candidates",
        return_value=[],
    ):
        result = _discover_jupyter_url()
    assert result == "http://localhost:8888"


def test_discover_token_from_env(monkeypatch):
    monkeypatch.setenv("JUPYTER_TOKEN", "mytoken123")
    assert _discover_jupyter_token() == "mytoken123"


def test_discover_token_from_runtime_json(tmp_path, monkeypatch):
    monkeypatch.delenv("JUPYTER_TOKEN", raising=False)
    json_file = tmp_path / "nbserver.json"
    json_file.write_text(json.dumps({"url": "http://localhost:8888", "token": "abc456"}))
    with patch(
        "jupyter_server_oauth_providers.credential_helper._runtime_json_candidates",
        return_value=[str(json_file)],
    ):
        result = _discover_jupyter_token()
    assert result == "abc456"


def test_discover_token_empty_when_missing(monkeypatch):
    monkeypatch.delenv("JUPYTER_TOKEN", raising=False)
    with patch(
        "jupyter_server_oauth_providers.credential_helper._runtime_json_candidates",
        return_value=[],
    ):
        result = _discover_jupyter_token()
    assert result == ""
