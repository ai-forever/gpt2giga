import asyncio
import sqlite3
import threading

import pytest
from fastapi import FastAPI, Request

from gpt2giga.app_state import get_resource_owner, get_resource_store
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.storage.resources import (
    ResourceLimitError,
    ResourceConflictError,
    ResourceStore,
    ResourceStoreError,
)


async def test_restart_workers_ownership_and_metadata(tmp_path):
    first = await ResourceStore.open(tmp_path)
    second = await ResourceStore.open(tmp_path)
    owner = first.owner_namespace("secret-credential", profile="one")
    assert second.owner_namespace("secret-credential", profile="one") == owner
    other = second.owner_namespace("secret-credential", profile="two")
    metadata = {
        "purpose": "assistants",
        "mime_type": "application/pdf",
        "upstream_id": "upstream",
        "deadline": 10,
    }
    await first.put(owner, "file", "file-one", metadata, blob=b"\x00\xffraw")
    assert (await second.get(owner, "file", "file-one")).metadata == metadata
    assert await second.get(other, "file", "file-one") is None
    assert await second.read_blob(other, "file", "file-one") is None
    assert await second.list(other, "file") == []
    assert await second.is_registered("file", "file-one")
    assert not await second.delete(other, "file", "file-one")
    await first.aclose()
    await second.aclose()
    restarted = await ResourceStore.open(tmp_path)
    assert restarted.owner_namespace("secret-credential", profile="one") == owner
    assert await restarted.read_blob(owner, "file", "file-one") == b"\x00\xffraw"
    await restarted.aclose()
    assert b"secret-credential" not in (tmp_path / "resources.sqlite3").read_bytes()


async def test_retention_is_separate_from_batch_deadline_and_cleans_blobs(tmp_path):
    now = [100.0]
    store = await ResourceStore.open(
        tmp_path, retention_seconds=100, clock=lambda: now[0]
    )
    await store.put(
        "one",
        "batch",
        "batch-one",
        {"deadline": 101, "status": "completed"},
        blob=b"result",
    )
    now[0] = 150
    assert (await store.get("one", "batch", "batch-one")).metadata[
        "status"
    ] == "completed"
    assert await store.purge_expired() == 0
    now[0] = 201
    assert await store.get("one", "batch", "batch-one") is None
    assert await store.read_blob("one", "batch", "batch-one") is None
    assert await store.purge_expired() == 1
    assert not await store.is_registered("batch", "batch-one")
    assert list((tmp_path / "blobs").iterdir()) == []
    await store.aclose()


async def test_quotas_rollback_and_owned_delete(tmp_path):
    store = await ResourceStore.open(tmp_path, max_blob_bytes=4, max_total_blob_bytes=6)
    with pytest.raises(ResourceLimitError):
        await store.put("owner", "file", "too-big", {}, blob=b"12345")
    await store.put("owner", "file", "first", {}, blob=b"1234")
    with pytest.raises(ResourceLimitError):
        await store.put("owner", "file", "second", {}, blob=b"123")
    with pytest.raises(sqlite3.IntegrityError):
        await store.put("owner", "file", "first", {}, blob=b"1")
    assert len(list((tmp_path / "blobs").iterdir())) == 1
    assert await store.get("owner", "file", "second") is None
    assert await store.delete("owner", "file", "first")
    assert not await store.delete("owner", "file", "first")
    assert await store.is_registered("file", "first")
    assert list((tmp_path / "blobs").iterdir()) == []
    await store.aclose()
    with pytest.raises(ResourceStoreError):
        await store.list("owner", "file")


async def test_atomic_updates_across_workers_and_stable_order(tmp_path):
    one = await ResourceStore.open(tmp_path, clock=lambda: 1)
    two = await ResourceStore.open(tmp_path, clock=lambda: 1)
    await one.put("owner", "batch", "z", {"count": 0})
    await one.put("owner", "batch", "a", {})
    await asyncio.gather(
        *(
            store.update("owner", "batch", "z", lambda m: {"count": m["count"] + 1})
            for store in [one, two] * 10
        )
    )
    assert (await one.get("owner", "batch", "z")).metadata["count"] == 20
    assert [r.public_id for r in await two.list("owner", "batch")] == ["a", "z"]
    await two.update("owner", "batch", "a", {"status": "done"})
    assert (await one.get("owner", "batch", "a")).metadata == {"status": "done"}
    assert await one.update("other", "batch", "a", {}) is None
    await one.aclose()
    await two.aclose()


async def test_unavailable_path_does_not_fall_back(tmp_path):
    path = tmp_path / "file"
    path.write_text("not a directory")
    with pytest.raises(FileExistsError):
        await ResourceStore.open(path)


async def test_cancelled_operation_drains_worker(tmp_path):
    store = await ResourceStore.open(tmp_path)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def operation():
        started.set()
        release.wait(timeout=5)
        finished.set()

    task = asyncio.create_task(store._run(operation))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    await store.aclose()


async def test_request_namespace_ignores_untrusted_identity_headers(tmp_path):
    app = FastAPI()
    app.state.resource_store = await ResourceStore.open(tmp_path)
    app.state.config = ProxyConfig(
        proxy=ProxySettings(pass_token=False), _env_file=None
    )

    def request(headers):
        return Request(
            {
                "type": "http",
                "app": app,
                "headers": headers,
                "path": "/files",
                "query_string": b"",
            }
        )

    one = get_resource_owner(
        request([(b"x-api-key", b"arbitrary"), (b"x-user-id", b"alice")])
    )
    two = get_resource_owner(
        request([(b"x-api-key", b"other"), (b"x-user-id", b"bob")])
    )
    assert one == two
    app.state.config.proxy_settings.pass_token = True
    one = get_resource_owner(request([(b"authorization", b"Bearer giga-auth-one")]))
    two = get_resource_owner(request([(b"authorization", b"Bearer giga-auth-two")]))
    assert one != two
    assert (
        get_resource_owner(request([(b"authorization", b"Bearer giga-auth-one")]))
        == one
    )
    assert (
        get_resource_owner(
            request([(b"authorization", b"Bearer giga-auth-one")]), profile="other"
        )
        != one
    )
    assert get_resource_store(request([])) is app.state.resource_store
    await app.state.resource_store.aclose()
    del app.state.resource_store
    with pytest.raises(ResourceStoreError):
        get_resource_store(request([]))


def test_resource_settings_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("GPT2GIGA_RESOURCE_STORE_PATH", str(tmp_path))
    monkeypatch.setenv("GPT2GIGA_RESOURCE_RETENTION_SECONDS", "100")
    monkeypatch.setenv("GPT2GIGA_RESOURCE_MAX_BLOB_BYTES", "200")
    monkeypatch.setenv("GPT2GIGA_RESOURCE_MAX_TOTAL_BLOB_BYTES", "500")
    monkeypatch.setenv("GPT2GIGA_RESOURCE_MAX_METADATA_BYTES", "800")
    monkeypatch.setenv("GPT2GIGA_RESOURCE_MAX_RESOURCES", "10")
    monkeypatch.setenv("GPT2GIGA_RESOURCE_TRUSTED_IDENTITY", "service-account")
    config = ProxySettings(_env_file=None)
    assert config.resource_store_path == str(tmp_path)
    assert config.resource_retention_seconds == 100
    assert config.resource_max_blob_bytes == 200
    assert config.resource_max_total_blob_bytes == 500
    assert config.resource_max_metadata_bytes == 800
    assert config.resource_max_resources == 10
    assert config.resource_trusted_identity == "service-account"


async def test_resumable_offset_finalize_and_quota(tmp_path):
    store = await ResourceStore.open(tmp_path, max_blob_bytes=4)
    await store.put("owner", "upload", "session", {"status": "active"}, blob=b"")
    await store.append_blob("owner", "upload", "session", b"ab", offset=0)
    with pytest.raises(ResourceConflictError, match="offset"):
        await store.append_blob("owner", "upload", "session", b"cd", offset=0)
    with pytest.raises(ResourceLimitError):
        await store.append_blob("owner", "upload", "session", b"cde", offset=2)
    assert await store.read_blob("owner", "upload", "session") == b"ab"
    await store.append_blob("owner", "upload", "session", b"cd", offset=2)
    await store.update("owner", "upload", "session", {"status": "finalizing"})
    with pytest.raises(ResourceConflictError, match="no longer"):
        await store.append_blob("owner", "upload", "session", b"", offset=4)
    assert await store.read_blob("owner", "upload", "session") == b"abcd"
    assert await store.append_blob("other", "upload", "session", b"", offset=0) is None
    await store.aclose()


async def test_concurrent_worker_initialization_uses_one_namespace_secret(tmp_path):
    stores = await asyncio.gather(*(ResourceStore.open(tmp_path) for _ in range(4)))
    assert len({store.owner_namespace("identity") for store in stores}) == 1
    await asyncio.gather(*(store.aclose() for store in stores))


async def test_startup_removes_crashed_unpublished_blob_only(tmp_path):
    store = await ResourceStore.open(tmp_path)
    await store.put("owner", "file", "existing", {}, blob=b"keep")
    await store.aclose()
    orphan = tmp_path / "blobs" / ("a" * 32)
    orphan.write_bytes(b"unpublished")
    store = await ResourceStore.open(tmp_path)
    assert not orphan.exists()
    assert await store.read_blob("owner", "file", "existing") == b"keep"
    await store.aclose()


async def test_failed_old_blob_cleanup_preserves_committed_append(
    tmp_path, monkeypatch
):
    store = await ResourceStore.open(tmp_path)
    await store.put("owner", "upload", "session", {"status": "active"}, blob=b"a")
    old_blob = next((tmp_path / "blobs").iterdir())
    unlink = type(old_blob).unlink

    def fail_old(path, *args, **kwargs):
        if path == old_blob:
            raise PermissionError("simulated cleanup failure")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(type(old_blob), "unlink", fail_old)
        with pytest.raises(PermissionError):
            await store.append_blob("owner", "upload", "session", b"b", offset=1)
    assert await store.read_blob("owner", "upload", "session") == b"ab"
    await store.aclose()
    store = await ResourceStore.open(tmp_path)
    assert not old_blob.exists()
    assert await store.read_blob("owner", "upload", "session") == b"ab"
    await store.aclose()


async def test_response_only_writes_bound_metadata_without_tombstone_growth(tmp_path):
    now = [100.0]
    store = await ResourceStore.open(
        tmp_path, retention_seconds=1, clock=lambda: now[0]
    )
    for index in range(20):
        await store.commit_response("owner", f"resp_g2g_{index}", {"text": "x" * 8192})
        now[0] += 2
    with sqlite3.connect(tmp_path / "resources.sqlite3") as db:
        assert db.execute("SELECT public_id FROM resources").fetchall() == [
            ("resp_g2g_19",)
        ]
        assert (
            db.execute("SELECT COUNT(*) FROM registered_resources").fetchone()[0] == 0
        )
    await store.aclose()


async def test_metadata_and_resource_limits_are_independent_of_blobs(tmp_path):
    store = await ResourceStore.open(tmp_path, max_metadata_bytes=100, max_resources=2)
    await store.commit_response("owner-a", "first", {"text": "x" * 40})
    with pytest.raises(ResourceLimitError):
        await store.commit_response("owner-b", "too-large", {"text": "x" * 60})
    await store.put("owner-b", "file", "second", {})
    with pytest.raises(ResourceLimitError):
        await store.put("owner-a", "file", "third", {})
    with pytest.raises(ResourceLimitError):
        await store.update("owner-b", "file", "second", {"text": "x" * 60})
    assert await store.get("owner-b", "response", "first") is None
    assert (await store.get("owner-b", "file", "second")).metadata == {}
    await store.aclose()


async def test_same_offset_race_has_typed_conflict(tmp_path):
    from gpt2giga.storage.resources import ResourceConflictError

    one = await ResourceStore.open(tmp_path)
    two = await ResourceStore.open(tmp_path)
    await one.put("owner", "upload", "session", {"status": "active"}, blob=b"")
    results = await asyncio.gather(
        one.append_blob("owner", "upload", "session", b"ab", offset=0),
        two.append_blob("owner", "upload", "session", b"ab", offset=0),
        return_exceptions=True,
    )
    assert sum(isinstance(result, ResourceConflictError) for result in results) == 1
    assert await one.read_blob("owner", "upload", "session") == b"ab"
    await one.aclose()
    await two.aclose()


async def test_promote_blob_uses_one_quota_and_retains_owner(tmp_path):
    store = await ResourceStore.open(tmp_path, max_total_blob_bytes=6)
    await store.put(
        "owner", "upload", "session", {"status": "finalizing"}, blob=b"abcd"
    )
    result = await store.promote_blob(
        "owner", "upload", "session", "file", "final", {"local": True}
    )
    assert result.blob_size == 4
    assert await store.get("owner", "upload", "session") is None
    assert await store.read_blob("owner", "file", "final") == b"abcd"
    assert await store.read_blob("other", "file", "final") is None
    assert len(list((tmp_path / "blobs").iterdir())) == 1
    await store.aclose()


async def test_startup_discards_redundant_tombstones_but_keeps_native_file_gate(
    tmp_path,
):
    store = await ResourceStore.open(tmp_path)
    await store.put("owner", "file", "native-file", {})
    await store.delete("owner", "file", "native-file")
    await store.aclose()
    with sqlite3.connect(tmp_path / "resources.sqlite3") as db:
        db.executemany(
            "INSERT INTO registered_resources VALUES (?, ?)",
            [
                ("response", "resp_g2g_old"),
                ("batch", "batch_g2g_old"),
                ("upload", "old-session"),
                ("conversation", "conv_old"),
                ("file", "file_g2g_old"),
            ],
        )
    store = await ResourceStore.open(tmp_path)
    assert await store.is_registered("file", "native-file")
    with sqlite3.connect(tmp_path / "resources.sqlite3") as db:
        assert db.execute(
            "SELECT kind, public_id FROM registered_resources"
        ).fetchall() == [("file", "native-file")]
    await store.aclose()
