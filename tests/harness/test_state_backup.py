import json
import os
from pathlib import Path
import sqlite3
import stat
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pytest

from gpt2giga_harness import cli
from gpt2giga_harness.runtime.store import (
    RUNTIME_SCHEMA_VERSION,
    RuntimeCoordinationStore,
    _MIGRATIONS,
)
from gpt2giga_harness.state_backup import (
    BACKUP_KIND,
    BACKUP_MANIFEST,
    BACKUP_SCHEMA_VERSION,
    create_state_backup,
    restore_state_backup,
    verify_state_backup,
)


def _seed_state(data_dir: Path) -> None:
    sessions = data_dir / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "session.json").write_text('{"id":"session_1"}\n', encoding="utf-8")
    os.chmod(sessions / "session.json", 0o600)
    with sqlite3.connect(data_dir / "runtime.sqlite3") as connection:
        connection.execute("CREATE TABLE records (id TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO records VALUES ('record_1', 'retained')")
    (data_dir / "orphan-wal").write_bytes(b"transient")
    (data_dir / "sessions.lock").write_text("transient", encoding="utf-8")
    (data_dir / ".write.tmp").write_text("transient", encoding="utf-8")


def test_state_backup_is_deterministic_versioned_and_sqlite_safe(tmp_path):
    data_dir = tmp_path / "state"
    _seed_state(data_dir)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_result = create_state_backup(data_dir, first)
    second_result = create_state_backup(data_dir, second)
    verified = verify_state_backup(first)

    assert first.read_bytes() == second.read_bytes()
    assert first_result == second_result == verified
    assert first_result.file_count == 2
    assert first_result.runtime_schema_version == 0
    assert first_result.max_supported_runtime_schema_version == RUNTIME_SCHEMA_VERSION
    assert first_result.restore_compatible is True
    assert first.stat().st_mode & 0o777 == 0o600
    with ZipFile(first) as bundle:
        manifest = json.loads(bundle.read(BACKUP_MANIFEST))
        assert manifest["schema_version"] == BACKUP_SCHEMA_VERSION
        assert manifest["kind"] == BACKUP_KIND
        assert manifest["restore_policy"] == "offline_replace_only"
        assert manifest["entries"][0]["sqlite_user_version"] == 0
        assert [entry["path"] for entry in manifest["entries"]] == [
            "runtime.sqlite3",
            "sessions/session.json",
        ]
        assert "orphan-wal" not in bundle.namelist()
        sqlite_copy = tmp_path / "runtime-copy.sqlite3"
        sqlite_copy.write_bytes(bundle.read("runtime.sqlite3"))
    with sqlite3.connect(sqlite_copy) as connection:
        assert connection.execute("SELECT * FROM records").fetchone() == (
            "record_1",
            "retained",
        )


def test_state_backup_rejects_unsafe_or_changed_inputs(tmp_path, monkeypatch):
    data_dir = tmp_path / "state"
    data_dir.mkdir()
    (data_dir / "state.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the Harness data directory"):
        create_state_backup(data_dir, data_dir / "backup.zip")

    symlink = data_dir / "external"
    symlink.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symbolic link"):
        create_state_backup(data_dir, tmp_path / "symlink.zip")
    symlink.unlink()

    from gpt2giga_harness import state_backup

    real_fingerprint = state_backup._fingerprint_tree
    calls = 0

    def changing_fingerprint(source):
        nonlocal calls
        calls += 1
        result = real_fingerprint(source)
        if calls == 2:
            result["changed-during-backup"] = (1, "0" * 64)
        return result

    monkeypatch.setattr(state_backup, "_fingerprint_tree", changing_fingerprint)
    output = tmp_path / "changed.zip"
    with pytest.raises(ValueError, match="changed while the backup"):
        create_state_backup(data_dir, output)
    assert not output.exists()


def test_state_backup_verification_rejects_manifest_mismatch(tmp_path):
    archive = tmp_path / "invalid.zip"
    manifest = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "kind": BACKUP_KIND,
        "harness_version": "0.0.1a4",
        "source_layout": "harness_user_data_dir",
        "restore_policy": "offline_replace_only",
        "entries": [
            {
                "kind": "file",
                "mode": 0o600,
                "path": "state.json",
                "sha256": "0" * 64,
                "size": 2,
            }
        ],
    }
    with ZipFile(archive, "w", compression=ZIP_STORED) as bundle:
        bundle.writestr(BACKUP_MANIFEST, json.dumps(manifest))
        info = ZipInfo("state.json")
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o600) << 16
        bundle.writestr(info, "{}")

    with pytest.raises(ValueError, match="entry failed verification"):
        verify_state_backup(archive)


def test_state_backup_cli_creates_and_verifies_json(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "state"
    data_dir.mkdir()
    (data_dir / "state.json").write_text("{}\n", encoding="utf-8")
    archive = tmp_path / "state.zip"
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(data_dir))

    assert cli.main(["state", "backup", "--output", str(archive), "--json"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["schema_version"] == BACKUP_SCHEMA_VERSION
    assert created["file_count"] == 1
    assert "output" not in created

    assert cli.main(["state", "verify", str(archive), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == created

    restored = tmp_path / "restored"
    assert (
        cli.main(
            [
                "state",
                "restore",
                str(archive),
                "--destination",
                str(restored),
                "--json",
            ]
        )
        == 0
    )
    restore_result = json.loads(capsys.readouterr().out)
    assert restore_result["restored"] is True
    assert restore_result["replaced_existing"] is False
    assert restore_result["restore_compatible"] is True
    assert (restored / "state.json").read_text(encoding="utf-8") == "{}\n"


def test_state_restore_requires_explicit_offline_replace(tmp_path):
    original = tmp_path / "original"
    _seed_state(original)
    archive = tmp_path / "state.zip"
    create_state_backup(original, archive)
    destination = tmp_path / "destination"
    _seed_state(destination)
    (destination / "orphan-wal").unlink()
    (destination / "sessions.lock").unlink()
    (destination / ".write.tmp").unlink()
    (destination / "sessions/session.json").write_text(
        '{"id":"newer"}\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="pass --replace"):
        restore_state_backup(archive, destination)
    assert "newer" in (destination / "sessions/session.json").read_text()

    result = restore_state_backup(archive, destination, replace=True)

    assert result.replaced_existing is True
    assert result.backup.restore_compatible is True
    assert (destination / "sessions/session.json").read_text() == (
        '{"id":"session_1"}\n'
    )
    assert (destination / "sessions/session.json").stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(destination / "runtime.sqlite3") as connection:
        assert connection.execute("SELECT * FROM records").fetchone() == (
            "record_1",
            "retained",
        )
    assert not list(tmp_path.glob(".destination.restore-*"))
    assert not list(tmp_path.glob(".destination.pre-restore-*"))


def test_state_restore_accepts_older_schema_then_migrates_on_open(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    path = legacy / "runtime.sqlite3"
    version, name, statements = _MIGRATIONS[0]
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        for statement in statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations VALUES (?, ?, ?)",
            (version, name, "2026-07-10T00:00:00+00:00"),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    archive = tmp_path / "legacy.zip"
    created = create_state_backup(legacy, archive)
    restored = tmp_path / "restored"

    assert created.runtime_schema_version == 1
    assert created.restore_compatible is True
    restore_state_backup(archive, restored)
    store = RuntimeCoordinationStore(restored)

    assert store.schema_version == RUNTIME_SCHEMA_VERSION
    assert verify_state_backup(archive).runtime_schema_version == 1


def test_state_restore_rejects_future_schema_without_mutating_destination(tmp_path):
    future = tmp_path / "future"
    future.mkdir()
    with sqlite3.connect(future / "runtime.sqlite3") as connection:
        connection.execute(f"PRAGMA user_version = {RUNTIME_SCHEMA_VERSION + 1}")
    archive = tmp_path / "future.zip"
    created = create_state_backup(future, archive)
    destination = tmp_path / "destination"
    destination.mkdir()
    marker = destination / "marker.json"
    marker.write_text('{"preserved":true}\n', encoding="utf-8")

    assert created.runtime_schema_version == RUNTIME_SCHEMA_VERSION + 1
    assert created.restore_compatible is False
    with pytest.raises(ValueError, match="newer than this Harness supports"):
        restore_state_backup(archive, destination, replace=True)

    assert marker.read_text(encoding="utf-8") == '{"preserved":true}\n'


def test_state_restore_rejects_active_or_changing_destination(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "state.json").write_text("{}\n", encoding="utf-8")
    archive = tmp_path / "state.zip"
    create_state_backup(source, archive)
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "state.json").write_text("{}\n", encoding="utf-8")
    active = destination / "runtime.sqlite3-wal"
    active.write_bytes(b"active")

    with pytest.raises(ValueError, match="active lock/WAL/SHM"):
        restore_state_backup(archive, destination, replace=True)
    active.unlink()

    from gpt2giga_harness import state_backup

    real_fingerprint = state_backup._fingerprint_tree
    calls = 0

    def changing_fingerprint(path):
        nonlocal calls
        result = real_fingerprint(path)
        calls += 1
        if calls == 2:
            result["changed-during-restore"] = (1, "0" * 64)
        return result

    monkeypatch.setattr(state_backup, "_fingerprint_tree", changing_fingerprint)
    with pytest.raises(ValueError, match="changed while restore was staged"):
        restore_state_backup(archive, destination, replace=True)
    assert (destination / "state.json").read_text(encoding="utf-8") == "{}\n"


def test_state_restore_rolls_back_destination_when_publish_fails(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "state.json").write_text('{"state":"backup"}\n', encoding="utf-8")
    archive = tmp_path / "state.zip"
    create_state_backup(source, archive)
    destination = tmp_path / "destination"
    destination.mkdir()
    marker = destination / "state.json"
    marker.write_text('{"state":"current"}\n', encoding="utf-8")
    real_replace = Path.replace

    def failing_publish(path, target):
        if path.name == "state" and Path(target) == destination:
            raise OSError("injected publish failure")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", failing_publish)
    with pytest.raises(OSError, match="injected publish failure"):
        restore_state_backup(archive, destination, replace=True)

    assert marker.read_text(encoding="utf-8") == '{"state":"current"}\n'
    assert not list(tmp_path.glob(".destination.pre-restore-*"))
