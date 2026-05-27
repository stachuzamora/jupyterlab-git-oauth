from unittest.mock import AsyncMock, patch

import pytest

from jupyterlab_git.git import Git


@pytest.mark.asyncio
async def test_commit_injects_committer_env():
    git = Git()
    mock_execute = AsyncMock(return_value=(0, "", ""))
    with patch.object(git, "_Git__execute", mock_execute):
        result = await git.commit("msg", False, "/repo", author="Jane Doe <jane@example.com>")

    assert result["code"] == 0
    env = mock_execute.call_args.kwargs["env"]
    assert env["GIT_COMMITTER_NAME"] == "Jane Doe"
    assert env["GIT_COMMITTER_EMAIL"] == "jane@example.com"


@pytest.mark.asyncio
async def test_commit_no_author_no_extra_env(monkeypatch):
    monkeypatch.delenv("GIT_COMMITTER_NAME", raising=False)
    monkeypatch.delenv("GIT_COMMITTER_EMAIL", raising=False)
    git = Git()
    mock_execute = AsyncMock(return_value=(0, "", ""))
    with patch.object(git, "_Git__execute", mock_execute):
        await git.commit("msg", False, "/repo")

    env = mock_execute.call_args.kwargs["env"]
    assert "GIT_COMMITTER_NAME" not in env
    assert "GIT_COMMITTER_EMAIL" not in env


@pytest.mark.asyncio
async def test_commit_malformed_author_does_not_crash():
    git = Git()
    with patch.object(git, "_Git__execute", AsyncMock(return_value=(0, "", ""))):
        result = await git.commit("msg", False, "/repo", author="no-angle-brackets")
    assert result["code"] == 0


@pytest.mark.asyncio
async def test_commit_failure_returns_error():
    git = Git()
    with patch.object(git, "_Git__execute", AsyncMock(return_value=(1, "", "nothing to commit"))):
        result = await git.commit("msg", False, "/repo")
    assert result["code"] == 1
    assert "message" in result
