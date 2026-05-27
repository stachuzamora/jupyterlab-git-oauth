import pytest

from jupyter_server_oauth_providers.token_store import MemoryStore, create_token_store


@pytest.mark.asyncio
async def test_save_and_load():
    store = MemoryStore()
    await store.save_token("user1", {"access_token": "tok123"})
    result = await store.load_token("user1")
    assert result == {"access_token": "tok123"}


@pytest.mark.asyncio
async def test_load_missing_returns_none():
    store = MemoryStore()
    result = await store.load_token("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_delete_token():
    store = MemoryStore()
    await store.save_token("user1", {"access_token": "tok"})
    await store.delete_token("user1")
    result = await store.load_token("user1")
    assert result is None


@pytest.mark.asyncio
async def test_delete_missing_is_noop():
    store = MemoryStore()
    await store.delete_token("nonexistent")


def test_create_token_store_returns_memory_store():
    store = create_token_store()
    assert isinstance(store, MemoryStore)
