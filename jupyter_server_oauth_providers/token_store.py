"""
Token storage — in-memory only.

Tokens live for the lifetime of the Jupyter Server process (i.e. the pod).
When the pod restarts, users re-authorize via the device flow.
This avoids storing credentials at rest and removes the need for K8s RBAC
or encryption key management.
"""

from __future__ import annotations

from typing import Any


class MemoryStore:
    """Per-process in-memory token store. Not shared across restarts."""

    def __init__(self) -> None:
        self._tokens: dict[str, dict[str, Any]] = {}

    async def save_token(self, user_id: str, data: dict[str, Any]) -> None:
        self._tokens[user_id] = data

    async def load_token(self, user_id: str) -> dict[str, Any] | None:
        return self._tokens.get(user_id)

    async def delete_token(self, user_id: str) -> None:
        self._tokens.pop(user_id, None)


def create_token_store() -> MemoryStore:
    return MemoryStore()
