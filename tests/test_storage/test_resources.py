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


@pytest.mark.parametrize("budget", ["max_resources", "max_metadata_bytes"])
async def test_put_metadata_admission_precedes_blob_io(tmp_path, monkeypatch, budget):
    from pathlib import Path

    store = await ResourceStore.open(tmp_path, **{budget: 0})
    original_open, original_unlink = Path.open, Path.unlink
    touched = []

    def tracked_open(path, *args, **kwargs):
        if path.parent == tmp_path / "blobs":
            touched.append("open")
        return original_open(path, *args, **kwargs)

    def fail_unlink(path, *args, **kwargs):
        if path.parent == tmp_path / "blobs":
            touched.append("unlink")
            raise PermissionError("injected cleanup failure")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", tracked_open)
        patch.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(ResourceLimitError, match="metadata quota"):
            await store.put("owner", "file", "rejected", {}, blob=b"payload")
    assert touched == []
    assert list((tmp_path / "blobs").iterdir()) == []
    assert not await store.is_registered("file", "rejected")
    await store.aclose()


@pytest.mark.parametrize("failure", ["write", "fsync", "commit"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_failed_put_removes_or_charges_unpublished_blob(
    tmp_path, monkeypatch, failure, cleanup_fails
):
    from pathlib import Path
    from gpt2giga.storage import resources

    store = await ResourceStore.open(tmp_path, max_total_blob_bytes=5)
    connection = store._connection()
    original_open, original_unlink = Path.open, Path.unlink
    failed = False

    class PartialWrite:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, data):
            self.stream.write(data[:3])
            raise OSError("injected write failure")

    def partial_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path.parent == tmp_path / "blobs" and args == ("xb",):
            return PartialWrite(stream)
        return stream

    def fail_fsync(fd):
        raise OSError("injected fsync failure")

    def fail_unlink(path, *args, **kwargs):
        if path.parent == tmp_path / "blobs":
            raise PermissionError("injected cleanup failure")
        return original_unlink(path, *args, **kwargs)

    class FailedCommit:
        def __getattr__(self, name):
            return getattr(connection, name)

        def __enter__(self):
            connection.__enter__()
            return self

        def __exit__(self, exc_type, exc, traceback):
            nonlocal failed
            # The first transaction is the independent foreground purge.
            if (
                not failed
                and exc_type is None
                and connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
            ):
                failed = True
                connection.rollback()
                raise sqlite3.OperationalError("injected commit failure")
            return connection.__exit__(exc_type, exc, traceback)

    with monkeypatch.context() as patch:
        if failure == "write":
            patch.setattr(Path, "open", partial_open)
        elif failure == "fsync":
            patch.setattr(resources.os, "fsync", fail_fsync)
        else:
            patch.setattr(store, "_connection", lambda: FailedCommit())
        if cleanup_fails:
            patch.setattr(Path, "unlink", fail_unlink)
        error = sqlite3.OperationalError if failure == "commit" else OSError
        with pytest.raises(error, match=f"injected {failure} failure"):
            await store.put("owner", "file", "rejected", {}, blob=b"12345")
        assert await store.get("owner", "file", "rejected") is None
        assert not await store.is_registered("file", "rejected")
        expected = (3 if failure == "write" else 5) if cleanup_fails else 0
        assert sum(p.stat().st_size for p in (tmp_path / "blobs").iterdir()) == expected
        assert connection.execute(
            "SELECT resource_count, metadata_bytes, blob_bytes FROM resource_usage"
        ).fetchone() == (0, 0, expected)
        if cleanup_fails:
            with pytest.raises(ResourceLimitError, match="blob quota"):
                await store.put("owner", "file", "another", {}, blob=b"123")
    await store.purge_expired()
    assert list((tmp_path / "blobs").iterdir()) == []
    assert connection.execute("SELECT COUNT(*) FROM blob_cleanup").fetchone()[0] == 0
    assert (
        connection.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0] == 0
    )
    await store.put("owner", "file", "recovered", {}, blob=b"12345")
    await store.aclose()


async def test_put_recovery_preserves_blob_when_commit_succeeded(tmp_path, monkeypatch):
    store = await ResourceStore.open(tmp_path)
    connection = store._connection()
    failed = False

    class ErrorAfterCommit:
        def __getattr__(self, name):
            return getattr(connection, name)

        def __enter__(self):
            connection.__enter__()
            return self

        def __exit__(self, exc_type, exc, traceback):
            nonlocal failed
            result = connection.__exit__(exc_type, exc, traceback)
            if (
                not failed
                and exc_type is None
                and connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
            ):
                failed = True
                raise sqlite3.OperationalError("injected error after commit")
            return result

    with monkeypatch.context() as patch:
        patch.setattr(store, "_connection", lambda: ErrorAfterCommit())
        with pytest.raises(sqlite3.OperationalError, match="after commit"):
            await store.put("owner", "file", "committed", {}, blob=b"retained")
    assert await store.read_blob("owner", "file", "committed") == b"retained"
    assert await store.is_registered("file", "committed")
    assert connection.execute("SELECT COUNT(*) FROM blob_cleanup").fetchone()[0] == 0
    assert (
        connection.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0] == 8
    )
    await store.aclose()


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


async def test_append_keeps_blob_identity_and_never_copies_prefix(
    tmp_path, monkeypatch
):
    from pathlib import Path

    store = await ResourceStore.open(tmp_path)
    await store.put("owner", "upload", "session", {"status": "active"}, blob=b"")
    blob = next((tmp_path / "blobs").iterdir())
    inode = blob.stat().st_ino
    original_open = Path.open
    counts = {"read": 0, "write": 0}

    class CountedFile:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, *args):
            data = self.stream.read(*args)
            counts["read"] += len(data)
            return data

        def write(self, data):
            counts["write"] += len(data)
            return self.stream.write(data)

    def counted_open(path, *args, **kwargs):
        result = original_open(path, *args, **kwargs)
        return CountedFile(result) if path == blob else result

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", counted_open)
        for index in range(64):
            await store.append_blob(
                "owner", "upload", "session", b"x" * 65536, offset=index * 65536
            )
    assert counts == {"read": 0, "write": 64 * 65536}
    assert blob.stat().st_ino == inode
    assert len(await store.read_blob("owner", "upload", "session")) == 64 * 65536
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


async def test_rejected_large_publication_commits_bounded_expiry_cleanup(tmp_path):
    now = [0.0]
    store = await ResourceStore.open(
        tmp_path, clock=lambda: now[0], max_metadata_bytes=40000
    )
    for index in range(400):
        await store.put("owner", "response", str(index), {"x": "x" * 90}, expires_at=1)
    now[0] = 2
    with pytest.raises(ResourceLimitError):
        await store.commit_response("owner", "new", {"x": "x" * 30000})
    with sqlite3.connect(tmp_path / "resources.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 144
    await store.commit_response("owner", "new", {"x": "x" * 30000})
    assert await store.get("owner", "response", "new") is not None
    await store.aclose()


async def test_append_rollback_and_crashed_tail_are_never_read(tmp_path, monkeypatch):
    store = await ResourceStore.open(tmp_path)
    await store.put("owner", "upload", "session", {"status": "active"}, blob=b"ok")
    blob = next((tmp_path / "blobs").iterdir())
    with monkeypatch.context() as patch:

        def reject(db):
            raise ResourceLimitError("simulated metadata rejection")

        patch.setattr(store, "_check_metadata_budget", reject)
        with pytest.raises(ResourceLimitError):
            await store.append_blob("owner", "upload", "session", b"bad", offset=2)
    assert await store.read_blob("owner", "upload", "session") == b"ok"
    with blob.open("ab") as stream:
        stream.write(b"crashed-tail")
    assert await store.read_blob("owner", "upload", "session") == b"ok"
    await store.aclose()
    store = await ResourceStore.open(tmp_path)
    assert blob.read_bytes() == b"ok"
    await store.append_blob("owner", "upload", "session", b"new", offset=2)
    assert await store.read_blob("owner", "upload", "session") == b"oknew"
    await store.aclose()


async def test_queued_storage_uses_no_executor_threads_and_cancels_promptly(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = await ResourceStore.open(tmp_path)
    loop = asyncio.get_running_loop()
    previous = loop._default_executor
    executor = ThreadPoolExecutor(max_workers=2)
    loop.set_default_executor(executor)
    started, release = threading.Event(), threading.Event()
    try:

        def blocked():
            started.set()
            release.wait(timeout=5)

        active = asyncio.create_task(store._run(blocked))
        await asyncio.to_thread(started.wait, 5)
        queued = [asyncio.create_task(store.list("owner", "file")) for _ in range(8)]
        await asyncio.sleep(0)
        assert await asyncio.wait_for(asyncio.to_thread(lambda: "free"), 1) == "free"
        for task in queued:
            task.cancel()
        results = await asyncio.wait_for(
            asyncio.gather(*queued, return_exceptions=True), 1
        )
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
    finally:
        release.set()
        await active
        loop._default_executor = previous
        executor.shutdown()
        await store.aclose()


async def test_usage_accounting_unchanged_update_and_restart(tmp_path):
    store = await ResourceStore.open(tmp_path)
    await store.put("owner", "file", "file_g2g_local", {"text": "é"}, blob=b"abc")
    statements = []
    store._db.set_trace_callback(statements.append)
    await store.update("owner", "file", "file_g2g_local", {"text": "é"})
    assert not any(sql.startswith("UPDATE resources") for sql in statements)
    await store.update("owner", "file", "file_g2g_local", {"text": "new"})
    with sqlite3.connect(tmp_path / "resources.sqlite3") as db:
        assert (
            db.execute(
                "SELECT resource_count, metadata_bytes, blob_bytes FROM resource_usage"
            ).fetchone()
            == db.execute(
                "SELECT COUNT(*), SUM(length(CAST(metadata AS BLOB))), SUM(blob_size) FROM resources"
            ).fetchone()
        )
    await store.aclose()
    store = await ResourceStore.open(tmp_path)
    await store.delete("owner", "file", "file_g2g_local")
    assert store._db.execute(
        "SELECT resource_count, metadata_bytes, blob_bytes FROM resource_usage"
    ).fetchone() == (0, 0, 0)
    await store.aclose()


async def test_failed_append_does_not_truncate_another_workers_committed_bytes(
    tmp_path, monkeypatch
):
    one = await ResourceStore.open(tmp_path)
    two = await ResourceStore.open(tmp_path)
    await one.put("owner", "upload", "session", {"status": "active"}, blob=b"ok")
    loop = asyncio.get_running_loop()
    connection = one._connection()
    interleaved = []

    class RollbackBarrier:
        def __getattr__(self, name):
            return getattr(connection, name)

        def __enter__(self):
            connection.__enter__()
            return self

        def __exit__(self, exc_type, exc, traceback):
            result = connection.__exit__(exc_type, exc, traceback)
            if exc_type is ResourceLimitError:
                # SQLite has released its writer lock. Force another worker to
                # publish before the rejected writer's exception cleanup runs.
                future = asyncio.run_coroutine_threadsafe(
                    two.append_blob(
                        "owner", "upload", "session", b"committed", offset=2
                    ),
                    loop,
                )
                interleaved.append(future.result(timeout=5))
            return result

    def reject(db):
        raise ResourceLimitError("first writer rejected")

    with monkeypatch.context() as patch:
        patch.setattr(one, "_connection", lambda: RollbackBarrier())
        patch.setattr(one, "_check_metadata_budget", reject)
        with pytest.raises(ResourceLimitError):
            await one.append_blob("owner", "upload", "session", b"rejected", offset=2)
    assert len(interleaved) == 1
    assert interleaved[0].blob_size == len(b"okcommitted")
    assert await two.read_blob("owner", "upload", "session") == b"okcommitted"
    assert await one.read_blob("owner", "upload", "session") == b"okcommitted"
    await one.aclose()
    await two.aclose()


async def test_append_metadata_admission_precedes_physical_write(tmp_path, monkeypatch):
    from pathlib import Path

    store = await ResourceStore.open(tmp_path)
    await store.put(
        "owner", "upload", "session", {"status": "active", "upload_offset": 0}, blob=b""
    )
    store.max_metadata_bytes = store._db.execute(
        "SELECT metadata_bytes FROM resource_usage"
    ).fetchone()[0]
    blob = next((tmp_path / "blobs").iterdir())
    original_open = Path.open
    opened = []

    def tracked_open(path, *args, **kwargs):
        if path == blob:
            opened.append(args)
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", tracked_open)
        with pytest.raises(ResourceLimitError):
            await store.append_blob("owner", "upload", "session", b"x" * 10, offset=0)
    assert opened == []
    assert blob.stat().st_size == 0
    assert (await store.get("owner", "upload", "session")).blob_size == 0
    await store.aclose()


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_failed_append_removes_or_charges_uncommitted_bytes(
    tmp_path, monkeypatch, cleanup_fails
):
    from pathlib import Path
    from gpt2giga.storage import resources

    store = await ResourceStore.open(tmp_path, max_total_blob_bytes=5)
    await store.put(
        "owner",
        "upload",
        "session",
        {"status": "active", "upload_offset": 2},
        blob=b"ok",
    )
    blob = next((tmp_path / "blobs").iterdir())
    original_open = Path.open
    fsync_calls = []

    def fail_fsync(fd):
        fsync_calls.append(fd)
        raise OSError("injected fsync failure")

    def fail_cleanup(path, *args, **kwargs):
        if path == blob and fsync_calls and args and args[0] == "r+b":
            raise OSError("injected cleanup failure")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(resources.os, "fsync", fail_fsync)
        if cleanup_fails:
            patch.setattr(Path, "open", fail_cleanup)
        with pytest.raises(OSError, match="fsync"):
            await store.append_blob("owner", "upload", "session", b"bad", offset=2)
        assert await store.read_blob("owner", "upload", "session") == b"ok"
        assert (await store.get("owner", "upload", "session")).blob_size == 2
        physical = sum(p.stat().st_size for p in (tmp_path / "blobs").iterdir())
        charged = store._db.execute("SELECT blob_bytes FROM resource_usage").fetchone()[
            0
        ]
        assert charged == physical == (5 if cleanup_fails else 2)
        if cleanup_fails:
            with pytest.raises(ResourceLimitError):
                await store.put("owner", "file", "other", {}, blob=b"x")
    await store.append_blob("owner", "upload", "session", b"new", offset=2)
    assert blob.read_bytes() == b"oknew"
    assert store._db.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0] == 5
    await store.aclose()


async def test_failed_commit_recovers_against_latest_worker_size(tmp_path, monkeypatch):
    one = await ResourceStore.open(tmp_path)
    two = await ResourceStore.open(tmp_path)
    await one.put("owner", "upload", "session", {"status": "active"}, blob=b"ok")
    loop = asyncio.get_running_loop()
    connection = one._connection()
    rolled_back = False

    class FailedCommit:
        def __getattr__(self, name):
            return getattr(connection, name)

        def __enter__(self):
            connection.__enter__()
            return self

        def __exit__(self, exc_type, exc, traceback):
            nonlocal rolled_back
            if not rolled_back and exc_type is None:
                rolled_back = True
                connection.rollback()
                future = asyncio.run_coroutine_threadsafe(
                    two.append_blob(
                        "owner", "upload", "session", b"committed", offset=2
                    ),
                    loop,
                )
                future.result(timeout=5)
                raise sqlite3.OperationalError("injected commit failure")
            return connection.__exit__(exc_type, exc, traceback)

    with monkeypatch.context() as patch:
        patch.setattr(one, "_connection", lambda: FailedCommit())
        with pytest.raises(sqlite3.OperationalError, match="commit failure"):
            await one.append_blob("owner", "upload", "session", b"rejected", offset=2)
    blob = next((tmp_path / "blobs").iterdir())
    assert blob.read_bytes() == b"okcommitted"
    assert await one.read_blob("owner", "upload", "session") == b"okcommitted"
    assert connection.execute("SELECT blob_bytes FROM resource_usage").fetchone()[
        0
    ] == len(b"okcommitted")
    await one.aclose()
    await two.aclose()


async def test_failed_append_cleanup_is_recovered_on_restart(tmp_path, monkeypatch):
    from pathlib import Path
    from gpt2giga.storage import resources

    store = await ResourceStore.open(tmp_path, max_total_blob_bytes=5)
    await store.put(
        "owner",
        "upload",
        "session",
        {"status": "active", "upload_offset": 2},
        blob=b"ok",
    )
    original_open = Path.open
    failed = False

    def fail_fsync(fd):
        nonlocal failed
        failed = True
        raise OSError("injected fsync failure")

    def fail_cleanup(path, *args, **kwargs):
        if failed and args and args[0] == "r+b":
            raise OSError("injected cleanup failure")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(resources.os, "fsync", fail_fsync)
        patch.setattr(Path, "open", fail_cleanup)
        with pytest.raises(OSError, match="fsync"):
            await store.append_blob("owner", "upload", "session", b"bad", offset=2)
    assert store._db.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0] == 5
    await store.aclose()
    store = await ResourceStore.open(tmp_path, max_total_blob_bytes=5)
    assert store._db.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0] == 2
    assert store._db.execute("SELECT COUNT(*) FROM blob_cleanup").fetchone()[0] == 0
    assert sum(p.stat().st_size for p in (tmp_path / "blobs").iterdir()) == 2
    await store.append_blob("owner", "upload", "session", b"new", offset=2)
    await store.aclose()


async def test_partial_append_write_failure_restores_physical_committed_prefix(
    tmp_path, monkeypatch
):
    from pathlib import Path

    store = await ResourceStore.open(tmp_path)
    await store.put(
        "owner",
        "upload",
        "session",
        {"status": "active", "upload_offset": 2},
        blob=b"ok",
    )
    original_open = Path.open
    blob = next((tmp_path / "blobs").iterdir())

    class PartialWrite:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def write(self, data):
            self.stream.write(data[:2])
            self.stream.flush()
            raise OSError("injected partial write")

    def partial_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return PartialWrite(stream) if path == blob else stream

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", partial_open)
        with pytest.raises(OSError, match="partial write"):
            await store.append_blob("owner", "upload", "session", b"bad", offset=2)
    assert blob.read_bytes() == b"ok"
    assert store._db.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0] == 2
    assert (await store.get("owner", "upload", "session")).metadata[
        "upload_offset"
    ] == 2
    await store.aclose()


async def test_append_failure_with_inaccessible_blob_preserves_admitted_charge(
    tmp_path, monkeypatch
):
    from pathlib import Path
    from gpt2giga.storage import resources

    store = await ResourceStore.open(tmp_path, max_total_blob_bytes=5)
    await store.put(
        "owner",
        "upload",
        "session",
        {"status": "active", "upload_offset": 2},
        blob=b"ok",
    )
    blob = next((tmp_path / "blobs").iterdir())
    original_open, original_stat = Path.open, Path.stat
    failed = False

    def fail_fsync(fd):
        nonlocal failed
        failed = True
        raise OSError("injected fsync failure")

    def inaccessible_open(path, *args, **kwargs):
        if failed and path == blob and args and args[0] == "r+b":
            raise PermissionError("injected inaccessible blob")
        return original_open(path, *args, **kwargs)

    def inaccessible_stat(path, *args, **kwargs):
        if failed and path == blob:
            raise PermissionError("injected inaccessible stat")
        return original_stat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(resources.os, "fsync", fail_fsync)
        patch.setattr(Path, "open", inaccessible_open)
        patch.setattr(Path, "stat", inaccessible_stat)
        with pytest.raises(OSError, match="fsync failure"):
            await store.append_blob("owner", "upload", "session", b"bad", offset=2)
        assert (
            store._db.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0]
            == 5
        )
        assert (await store.get("owner", "upload", "session")).blob_size == 2
        with pytest.raises(ResourceLimitError):
            await store.put("owner", "file", "other", {}, blob=b"x")
    await store.purge_expired()
    assert blob.read_bytes() == b"ok"
    assert store._db.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0] == 2
    await store.aclose()


async def test_delete_transfers_blob_charge_before_unlocking_metadata(
    tmp_path, monkeypatch
):
    store = await ResourceStore.open(tmp_path, max_total_blob_bytes=5)
    await store.put("owner", "upload", "session", {"status": "active"}, blob=b"ok")
    blob = next((tmp_path / "blobs").iterdir())
    with blob.open("ab") as stream:
        stream.write(b"bad")
    with store._db:
        store._db.execute("INSERT INTO blob_cleanup VALUES (?, ?)", (blob.name, 3))
    connection = store._connection()
    removal_committed = []

    class CrashBeforeCleanup:
        def __getattr__(self, name):
            return getattr(connection, name)

        def __enter__(self):
            connection.__enter__()
            return self

        def __exit__(self, exc_type, exc, traceback):
            result = connection.__exit__(exc_type, exc, traceback)
            if not removal_committed and exc_type is None:
                with sqlite3.connect(tmp_path / "resources.sqlite3") as observer:
                    removal_committed.append(
                        observer.execute(
                            "SELECT blob_bytes FROM resource_usage"
                        ).fetchone()[0]
                    )
                    assert (
                        observer.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
                        == 0
                    )
                raise OSError("injected crash after metadata commit")
            return result

    with monkeypatch.context() as patch:
        patch.setattr(store, "_connection", lambda: CrashBeforeCleanup())
        with pytest.raises(OSError, match="crash"):
            await store.delete("owner", "upload", "session", expected_status="active")
    assert removal_committed == [5]
    assert blob.stat().st_size == 5
    assert (
        connection.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0] == 5
    )
    await store.purge_expired()
    assert not blob.exists()
    assert (
        connection.execute("SELECT blob_bytes FROM resource_usage").fetchone()[0] == 0
    )
    await store.aclose()
