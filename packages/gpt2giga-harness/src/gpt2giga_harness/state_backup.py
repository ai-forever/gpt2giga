"""Deterministic offline backups for Harness-owned user state."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
from tempfile import TemporaryDirectory, mkdtemp
from typing import BinaryIO, Iterator
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from gpt2giga_harness.runtime.store import RUNTIME_SCHEMA_VERSION


BACKUP_KIND = "gpt2giga_harness_state_backup"
BACKUP_MANIFEST = "manifest.json"
BACKUP_SCHEMA_VERSION = 1
_CHUNK_SIZE = 1024 * 1024
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_SQLITE_SUFFIX = ".sqlite3"
_TRANSIENT_SUFFIXES = ("-shm", "-wal")


@dataclass(frozen=True)
class StateBackupResult:
    """Content-free result of creating or verifying one state archive."""

    schema_version: int
    harness_version: str
    file_count: int
    total_bytes: int
    sha256: str
    runtime_schema_version: int | None
    max_supported_runtime_schema_version: int
    restore_compatible: bool

    def to_dict(self) -> dict[str, bool | int | str | None]:
        """Serialize the stable result without exposing a local path."""
        return {
            "schema_version": self.schema_version,
            "harness_version": self.harness_version,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "sha256": self.sha256,
            "runtime_schema_version": self.runtime_schema_version,
            "max_supported_runtime_schema_version": (
                self.max_supported_runtime_schema_version
            ),
            "restore_compatible": self.restore_compatible,
        }


@dataclass(frozen=True)
class StateRestoreResult:
    """Content-free result of atomically restoring one state archive."""

    backup: StateBackupResult
    replaced_existing: bool

    def to_dict(self) -> dict[str, bool | int | str | None]:
        """Serialize restore evidence without exposing local paths."""
        return {
            **self.backup.to_dict(),
            "restored": True,
            "replaced_existing": self.replaced_existing,
        }


def create_state_backup(data_dir: str | Path, output: str | Path) -> StateBackupResult:
    """Create an atomic deterministic archive of a quiescent Harness data dir."""
    source = Path(data_dir).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"Harness state directory does not exist: {source}")
    if destination == source or destination.is_relative_to(source):
        raise ValueError(
            "State backup output must be outside the Harness data directory."
        )
    if destination.exists():
        raise ValueError(f"State backup output already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    before = _fingerprint_tree(source)
    temp = destination.with_name(f".{destination.name}.tmp")
    try:
        temp.unlink(missing_ok=True)
        temp.touch(mode=0o600, exist_ok=False)
        with TemporaryDirectory(prefix="gpt2giga-harness-backup-") as temp_dir:
            _write_archive(source, temp, Path(temp_dir))
        after = _fingerprint_tree(source)
        if before != after:
            raise ValueError(
                "Harness state changed while the backup was being created; "
                "stop the UI, workers, and active runs, then retry."
            )
        result = verify_state_backup(temp)
        os.chmod(temp, 0o600)
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        if destination.exists():
            raise ValueError(f"State backup output already exists: {destination}")
        temp.replace(destination)
        return result
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def verify_state_backup(archive: str | Path) -> StateBackupResult:
    """Verify manifest hashes, safe paths, and SQLite integrity in an archive."""
    path = Path(archive).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"State backup does not exist: {path}")
    try:
        with ZipFile(path, "r") as bundle:
            infos = bundle.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ValueError("State backup contains duplicate archive paths.")
            for info in infos:
                _validate_archive_path(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError("State backup must not contain symbolic links.")
            if bundle.testzip() is not None:
                raise ValueError("State backup failed its ZIP integrity check.")
            try:
                manifest = json.loads(bundle.read(BACKUP_MANIFEST))
            except (KeyError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "State backup manifest is missing or invalid."
                ) from exc
            entries = _validate_manifest(manifest)
            info_by_name = {info.filename: info for info in infos}
            expected_names = {BACKUP_MANIFEST, *(entry["path"] for entry in entries)}
            if set(names) != expected_names:
                raise ValueError("State backup contents do not match its manifest.")
            runtime_schema_version: int | None = None
            with TemporaryDirectory(prefix="gpt2giga-harness-verify-") as temp_dir:
                for index, entry in enumerate(entries):
                    archived_mode = info_by_name[entry["path"]].external_attr >> 16
                    if not stat.S_ISREG(archived_mode) or stat.S_IMODE(
                        archived_mode
                    ) != int(entry["mode"]):
                        raise ValueError(
                            f"State backup entry mode is invalid: {entry['path']}"
                        )
                    digest, size = _hash_zip_entry(bundle, entry["path"])
                    if digest != entry["sha256"] or size != entry["size"]:
                        raise ValueError(
                            f"State backup entry failed verification: {entry['path']}"
                        )
                    if entry["kind"] == "sqlite":
                        sqlite_path = Path(temp_dir) / f"sqlite-{index}.sqlite3"
                        sqlite_path.write_bytes(bundle.read(entry["path"]))
                        user_version = _verify_sqlite(sqlite_path, entry["path"])
                        declared_version = entry.get("sqlite_user_version")
                        if (
                            declared_version is not None
                            and declared_version != user_version
                        ):
                            raise ValueError(
                                "State backup SQLite schema metadata does not "
                                f"match its contents: {entry['path']}"
                            )
                        if entry["path"] == "runtime.sqlite3":
                            runtime_schema_version = user_version
    except BadZipFile as exc:
        raise ValueError("State backup is not a valid ZIP archive.") from exc
    return _result_for_archive(path, manifest, runtime_schema_version)


def restore_state_backup(
    archive: str | Path,
    destination: str | Path,
    *,
    replace: bool = False,
) -> StateRestoreResult:
    """Restore a verified archive through an offline atomic directory swap."""
    source = Path(archive).expanduser().resolve()
    raw_destination = Path(destination).expanduser()
    if raw_destination.is_symlink():
        raise ValueError("State restore destination must not be a symbolic link.")
    target = raw_destination.resolve()
    if target.parent == target:
        raise ValueError("State restore destination must not be a filesystem root.")
    if source == target or source.is_relative_to(target):
        raise ValueError(
            "State restore archive must be outside the destination directory."
        )

    verified = verify_state_backup(source)
    if not verified.restore_compatible:
        raise ValueError(
            "State backup runtime schema is newer than this Harness supports: "
            f"archive={verified.runtime_schema_version}, "
            f"supported={verified.max_supported_runtime_schema_version}."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    before: dict[str, tuple[int, str]] | None = None
    if existed:
        if not target.is_dir():
            raise ValueError("State restore destination is not a directory.")
        if not replace:
            raise ValueError(
                "State restore destination already exists; stop Harness and pass "
                "--replace to confirm offline replacement."
            )
        _assert_restore_destination_quiescent(target)
        before = _fingerprint_tree(target)

    with TemporaryDirectory(
        prefix=f".{target.name}.restore-", dir=target.parent
    ) as temp_dir:
        stage = Path(temp_dir) / "state"
        stage.mkdir(mode=0o700)
        _extract_archive(source, stage)
        if _hash_file(source)[0] != verified.sha256:
            raise ValueError("State backup changed while it was being restored.")
        if existed:
            _assert_restore_destination_quiescent(target)
            if before != _fingerprint_tree(target):
                raise ValueError(
                    "Harness state changed while restore was staged; stop the UI, "
                    "workers, and active runs, then retry."
                )
        _publish_restored_state(stage, target, replace=existed)
    return StateRestoreResult(backup=verified, replaced_existing=existed)


def _write_archive(source: Path, output: Path, temp_dir: Path) -> dict[str, object]:
    entries: list[dict[str, int | str]] = []
    with ZipFile(output, "w", compression=ZIP_STORED, allowZip64=True) as bundle:
        for path in _iter_state_files(source):
            relative = path.relative_to(source).as_posix()
            mode = stat.S_IMODE(path.stat().st_mode)
            if path.name.endswith(_SQLITE_SUFFIX):
                snapshot = temp_dir / f"sqlite-{len(entries)}.sqlite3"
                sqlite_user_version = _snapshot_sqlite(path, snapshot)
                digest, size = _write_file(bundle, relative, snapshot, mode)
                kind = "sqlite"
            else:
                digest, size = _write_file(bundle, relative, path, mode)
                kind = "file"
            entry: dict[str, int | str] = {
                "kind": kind,
                "mode": mode,
                "path": relative,
                "sha256": digest,
                "size": size,
            }
            if kind == "sqlite":
                entry["sqlite_user_version"] = sqlite_user_version
            entries.append(entry)
        manifest: dict[str, object] = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "kind": BACKUP_KIND,
            "harness_version": _harness_version(),
            "source_layout": "harness_user_data_dir",
            "restore_policy": "offline_replace_only",
            "entries": entries,
        }
        payload = _canonical_json(manifest)
        _write_bytes(bundle, BACKUP_MANIFEST, payload, 0o600)
    return manifest


def _iter_state_files(source: Path) -> Iterator[Path]:
    for root, directories, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        for name in sorted((*directories, *files)):
            candidate = root_path / name
            if candidate.is_symlink():
                raise ValueError(
                    f"Harness state contains an unsupported symbolic link: "
                    f"{candidate.relative_to(source)}"
                )
        directories.sort()
        for name in sorted(files):
            path = root_path / name
            if _is_transient(path):
                continue
            if not path.is_file():
                raise ValueError(
                    f"Harness state contains an unsupported file type: "
                    f"{path.relative_to(source)}"
                )
            yield path


def _fingerprint_tree(source: Path) -> dict[str, tuple[int, str]]:
    fingerprints: dict[str, tuple[int, str]] = {}
    for root, directories, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        directories.sort()
        for name in sorted(files):
            path = root_path / name
            if path.is_symlink() or not path.is_file():
                continue
            if name.endswith("-shm") or (
                name.endswith("-wal") and path.stat().st_size == 0
            ):
                continue
            relative = path.relative_to(source).as_posix()
            fingerprints[relative] = (path.stat().st_size, _hash_file(path)[0])
    return fingerprints


def _is_transient(path: Path) -> bool:
    name = path.name
    return (
        name.endswith(_TRANSIENT_SUFFIXES)
        or name.endswith(".lock")
        or (name.startswith(".") and name.endswith(".tmp"))
    )


def _snapshot_sqlite(source: Path, destination: Path) -> int:
    try:
        source_uri = f"{source.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(source_uri, uri=True) as source_db:
            with sqlite3.connect(destination) as destination_db:
                source_db.backup(destination_db)
                result = destination_db.execute("PRAGMA quick_check").fetchone()
                user_version_row = destination_db.execute(
                    "PRAGMA user_version"
                ).fetchone()
    except sqlite3.Error as exc:
        raise ValueError(f"Unable to snapshot SQLite state: {source.name}") from exc
    if result is None or result[0] != "ok":
        raise ValueError(f"SQLite state failed integrity check: {source.name}")
    return int(user_version_row[0]) if user_version_row is not None else 0


def _verify_sqlite(path: Path, archive_name: str) -> int:
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
            user_version_row = connection.execute("PRAGMA user_version").fetchone()
    except sqlite3.Error as exc:
        raise ValueError(
            f"State backup SQLite entry is invalid: {archive_name}"
        ) from exc
    if result is None or result[0] != "ok":
        raise ValueError(f"State backup SQLite entry is corrupt: {archive_name}")
    return int(user_version_row[0]) if user_version_row is not None else 0


def _assert_restore_destination_quiescent(destination: Path) -> None:
    for root, directories, files in os.walk(destination, followlinks=False):
        root_path = Path(root)
        for name in (*directories, *files):
            path = root_path / name
            if path.is_symlink():
                raise ValueError(
                    "Harness state contains a symbolic link and cannot be replaced "
                    "safely."
                )
        for name in files:
            if name.endswith((*_TRANSIENT_SUFFIXES, ".lock")):
                raise ValueError(
                    "Harness state has active lock/WAL/SHM markers; stop the UI, "
                    "workers, and active runs before restore."
                )


def _extract_archive(archive: Path, destination: Path) -> None:
    try:
        with ZipFile(archive, "r") as bundle:
            manifest = json.loads(bundle.read(BACKUP_MANIFEST))
            entries = _validate_manifest(manifest)
            for entry in entries:
                relative = PurePosixPath(str(entry["path"]))
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                digest = sha256()
                size = 0
                with bundle.open(str(entry["path"]), "r") as source:
                    with target.open("xb") as output:
                        while chunk := source.read(_CHUNK_SIZE):
                            output.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                os.chmod(target, int(entry["mode"]))
                if digest.hexdigest() != entry["sha256"] or size != entry["size"]:
                    raise ValueError(
                        f"Restored state entry failed verification: {entry['path']}"
                    )
                if entry["kind"] == "sqlite":
                    _verify_sqlite(target, str(entry["path"]))
    except (BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("State backup changed while it was being restored.") from exc
    for directory in sorted(
        (path for path in destination.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        os.chmod(directory, 0o700)
        _fsync_directory(directory)
    os.chmod(destination, 0o700)
    _fsync_directory(destination)


def _publish_restored_state(
    stage: Path,
    destination: Path,
    *,
    replace: bool,
) -> None:
    if not replace:
        stage.replace(destination)
        _fsync_directory(destination.parent)
        return

    previous = Path(
        mkdtemp(prefix=f".{destination.name}.pre-restore-", dir=destination.parent)
    )
    previous.rmdir()
    destination.replace(previous)
    _fsync_directory(destination.parent)
    try:
        stage.replace(destination)
        _fsync_directory(destination.parent)
    except BaseException:
        if not destination.exists() and previous.exists():
            previous.replace(destination)
            _fsync_directory(destination.parent)
        raise
    shutil.rmtree(previous)
    _fsync_directory(destination.parent)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_file(
    bundle: ZipFile,
    archive_name: str,
    source: Path,
    mode: int,
) -> tuple[str, int]:
    with source.open("rb") as stream:
        return _write_stream(bundle, archive_name, stream, mode)


def _write_bytes(
    bundle: ZipFile,
    archive_name: str,
    payload: bytes,
    mode: int,
) -> tuple[str, int]:
    from io import BytesIO

    return _write_stream(bundle, archive_name, BytesIO(payload), mode)


def _write_stream(
    bundle: ZipFile,
    archive_name: str,
    stream: BinaryIO,
    mode: int,
) -> tuple[str, int]:
    info = ZipInfo(archive_name, date_time=_FIXED_ZIP_TIMESTAMP)
    info.compress_type = ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    digest = sha256()
    size = 0
    with bundle.open(info, "w", force_zip64=True) as target:
        while chunk := stream.read(_CHUNK_SIZE):
            target.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _hash_file(path: Path) -> tuple[str, int]:
    digest = sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _hash_zip_entry(bundle: ZipFile, name: str) -> tuple[str, int]:
    digest = sha256()
    size = 0
    with bundle.open(name, "r") as stream:
        while chunk := stream.read(_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _validate_manifest(manifest: object) -> list[dict[str, object]]:
    if not isinstance(manifest, dict):
        raise ValueError("State backup manifest must be an object.")
    if manifest.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise ValueError("State backup schema version is unsupported.")
    if manifest.get("kind") != BACKUP_KIND:
        raise ValueError("State backup kind is unsupported.")
    if manifest.get("source_layout") != "harness_user_data_dir":
        raise ValueError("State backup source layout is unsupported.")
    if manifest.get("restore_policy") != "offline_replace_only":
        raise ValueError("State backup restore policy is unsupported.")
    harness_version = manifest.get("harness_version")
    if not isinstance(harness_version, str) or not harness_version:
        raise ValueError("State backup Harness version is invalid.")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("State backup manifest entries are invalid.")
    validated: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("State backup manifest entry is invalid.")
        path = entry.get("path")
        digest = entry.get("sha256")
        size = entry.get("size")
        kind = entry.get("kind")
        mode = entry.get("mode")
        sqlite_user_version = entry.get("sqlite_user_version")
        if not isinstance(path, str):
            raise ValueError("State backup manifest path is invalid.")
        _validate_archive_path(path)
        if path == BACKUP_MANIFEST or path in seen:
            raise ValueError("State backup manifest paths must be unique.")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("State backup manifest digest is invalid.")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("State backup manifest size is invalid.")
        if kind not in {"file", "sqlite"}:
            raise ValueError("State backup manifest entry kind is invalid.")
        if sqlite_user_version is not None and (
            kind != "sqlite"
            or not isinstance(sqlite_user_version, int)
            or isinstance(sqlite_user_version, bool)
            or sqlite_user_version < 0
        ):
            raise ValueError("State backup SQLite schema metadata is invalid.")
        if (
            not isinstance(mode, int)
            or isinstance(mode, bool)
            or not 0 <= mode <= 0o777
        ):
            raise ValueError("State backup manifest mode is invalid.")
        seen.add(path)
        validated.append(entry)
    return validated


def _validate_archive_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("State backup contains an unsafe archive path.")


def _result_for_archive(
    path: Path,
    manifest: dict[str, object],
    runtime_schema_version: int | None,
) -> StateBackupResult:
    entries = _validate_manifest(manifest)
    return StateBackupResult(
        schema_version=BACKUP_SCHEMA_VERSION,
        harness_version=str(manifest.get("harness_version") or "unknown"),
        file_count=len(entries),
        total_bytes=sum(int(entry["size"]) for entry in entries),
        sha256=_hash_file(path)[0],
        runtime_schema_version=runtime_schema_version,
        max_supported_runtime_schema_version=RUNTIME_SCHEMA_VERSION,
        restore_compatible=(
            runtime_schema_version is None
            or runtime_schema_version <= RUNTIME_SCHEMA_VERSION
        ),
    )


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def _harness_version() -> str:
    try:
        return version("gpt2giga-harness")
    except PackageNotFoundError:
        return "unknown"
