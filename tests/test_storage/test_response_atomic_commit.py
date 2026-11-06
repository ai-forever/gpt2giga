"""Snapshots and conversation state have one transactional publication point."""

import asyncio
import sqlite3

import pytest

from gpt2giga.storage.resources import (
    ResourceConflictError,
    ResourceNotFoundError,
    ResourceStore,
)


async def test_response_insert_failure_rolls_back_conversation(tmp_path):
    store = await ResourceStore.open(tmp_path)
    initial = {"items": [{"id": "seed"}], "revision": 0, "metadata": {"topic": "test"}}
    await store.put("owner", "conversation", "conv", initial)
    await store.put("owner", "response", "collision", {"original": True})
    with pytest.raises(sqlite3.IntegrityError):
        await store.commit_response(
            "owner",
            "collision",
            {"new": True},
            conversation_id="conv",
            expected_revision=0,
            conversation_items=[{"id": "new"}],
        )
    assert (await store.get("owner", "conversation", "conv")).metadata == initial
    assert (await store.get("owner", "response", "collision")).metadata == {
        "original": True
    }
    await store.aclose()


async def test_response_commit_checks_revision_owner_and_retention(tmp_path):
    now = [0]
    store = await ResourceStore.open(
        tmp_path, clock=lambda: now[0], retention_seconds=10
    )
    await store.put("owner", "conversation", "conv", {"items": [], "revision": 0})
    with pytest.raises(ResourceConflictError):
        await store.commit_response(
            "owner",
            "conflict",
            {},
            conversation_id="conv",
            expected_revision=1,
            conversation_items=[],
        )
    assert await store.get("owner", "response", "conflict") is None
    with pytest.raises(ResourceNotFoundError):
        await store.commit_response(
            "other",
            "foreign",
            {},
            conversation_id="conv",
            expected_revision=0,
            conversation_items=[],
        )
    await store.commit_response(
        "owner",
        "saved",
        {"response": {}},
        conversation_id="conv",
        expected_revision=0,
        conversation_items=[{"id": "first"}],
    )
    assert (await store.get("owner", "conversation", "conv")).metadata == {
        "items": [{"id": "first"}],
        "revision": 1,
    }
    assert await store.is_registered("response", "saved")
    await store.commit_response(
        "owner",
        "ephemeral",
        None,
        conversation_id="conv",
        expected_revision=1,
        conversation_items=[{"id": "second"}],
    )
    assert await store.get("owner", "response", "ephemeral") is None
    now[0] = 11
    with pytest.raises(ResourceNotFoundError):
        await store.commit_response(
            "owner",
            "expired",
            {},
            conversation_id="conv",
            expected_revision=2,
            conversation_items=[],
        )
    assert await store.get("owner", "response", "expired") is None
    await store.aclose()


async def test_repeated_cancellation_drains_and_rolls_back_pending_response(tmp_path):
    store = await ResourceStore.open(tmp_path)
    store._lock.acquire()
    try:
        operation = asyncio.create_task(
            store.commit_response("owner", "cancelled", {"response": {}})
        )
        await asyncio.sleep(0.01)
        operation.cancel()
        await asyncio.sleep(0)
        operation.cancel()
        await asyncio.sleep(0)
        assert not operation.done()
    finally:
        store._lock.release()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert await store.get("owner", "response", "cancelled") is None
    assert not await store.is_registered("response", "cancelled")
    await store.aclose()
