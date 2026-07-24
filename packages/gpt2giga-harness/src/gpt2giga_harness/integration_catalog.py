"""Durable integration catalog and offline MCP subregistry contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import anyio

from gpt2giga_harness.integration_packages import (
    IntegrationPackage,
    IntegrationSourceType,
    IntegrationTrustDecision,
    assess_integration_package,
    integration_package_from_dict,
    integration_package_semantic_hash,
    integration_package_to_dict,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.types import REDACTED, redact_secrets


CATALOG_SCHEMA_VERSION = 1
OFFICIAL_MCP_REGISTRY_SOURCE_ID = "official-mcp-registry"
OFFICIAL_MCP_REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io"
OFFICIAL_MCP_REGISTRY_API_VERSION = "v0.1"
MAX_CATALOG_ENTRIES = 50_000
MAX_CATALOG_SOURCE_ENTRIES = 10_000
MAX_CATALOG_SOURCES = 100
MAX_CATALOG_PAGE_SIZE = 1_000
MAX_CATALOG_SOURCE_ERRORS = 20
MAX_CATALOG_JSON_BYTES = 256 * 1024
MAX_CATALOG_JSON_DEPTH = 20
MAX_REGISTRY_PAGES = 1_000
MAX_REGISTRY_RESPONSE_BYTES = 2 * 1024 * 1024
_MCP_OFFICIAL_META_KEY = "io.modelcontextprotocol.registry/official"
_LOCAL_SUBREGISTRY_META_KEY = "agent_workbench.catalog/v1"
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,255}\Z")
_MCP_NAME_RE = re.compile(r"[A-Za-z0-9.-]+/[A-Za-z0-9._-]+\Z")
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_IMMUTABLE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,511}\Z")


class CatalogSourceType(str, Enum):
    """Reviewed source families admitted to the N4 catalog."""

    LOCAL_PRIVATE = "local_private"
    OFFICIAL_MCP_REGISTRY = "official_mcp_registry"
    PROVIDER_MARKETPLACE = "provider_marketplace"
    GIT = "git"
    LOCAL = "local"
    FEDERATED_CATALOG = "federated_catalog"


class CatalogEntryStatus(str, Enum):
    """Lifecycle status retained independently from immutable content."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DELETED = "deleted"


class CatalogConflictError(RuntimeError):
    """Raised when a source attempts to replace an immutable catalog pin."""


class CatalogStateError(RuntimeError):
    """Raised when durable catalog state is corrupt or from a future schema."""


@dataclass(frozen=True, order=True)
class CatalogSourceError:
    """Bounded content-free source failure retained for diagnostics."""

    code: str
    source_id: str
    error_type: str
    occurred_at: str

    def __post_init__(self) -> None:
        _validate_identity(self.code, field_name="catalog source error code")
        _validate_identity(self.source_id, field_name="catalog source id")
        _validate_identity(self.error_type, field_name="catalog source error type")
        _parse_timestamp(self.occurred_at)


@dataclass(frozen=True)
class CatalogSourceState:
    """Last synchronization state for one independent catalog source."""

    source_id: str
    source_type: CatalogSourceType
    last_attempt_at: str
    last_success_at: str | None
    last_attempt_succeeded: bool
    complete: bool
    entry_count: int
    cursor: str | None = None
    retry_count: int = 0
    next_retry_at: str | None = None
    etag: str | None = None
    freshness_expires_at: str | None = None
    errors: tuple[CatalogSourceError, ...] = ()

    def __post_init__(self) -> None:
        _validate_identity(self.source_id, field_name="catalog source id")
        if not isinstance(self.source_type, CatalogSourceType):
            raise ValueError("catalog source type is invalid")
        _parse_timestamp(self.last_attempt_at)
        if self.last_success_at is not None:
            _parse_timestamp(self.last_success_at)
        if not isinstance(self.last_attempt_succeeded, bool):
            raise ValueError("catalog source success flag must be a boolean")
        if not isinstance(self.complete, bool):
            raise ValueError("catalog source completeness must be a boolean")
        if (
            isinstance(self.entry_count, bool)
            or not isinstance(self.entry_count, int)
            or self.entry_count < 0
            or self.entry_count > MAX_CATALOG_ENTRIES
        ):
            raise ValueError("catalog source entry_count is invalid")
        if self.cursor is not None:
            _validate_bounded_metadata(self.cursor, "catalog source cursor", 2_048)
        if (
            isinstance(self.retry_count, bool)
            or not isinstance(self.retry_count, int)
            or self.retry_count < 0
            or self.retry_count > 100
        ):
            raise ValueError("catalog source retry_count is invalid")
        if self.next_retry_at is not None:
            _parse_timestamp(self.next_retry_at)
        if self.etag is not None:
            _validate_bounded_metadata(self.etag, "catalog source etag", 512)
        if self.freshness_expires_at is not None:
            _parse_timestamp(self.freshness_expires_at)
        errors = tuple(self.errors)
        if len(errors) > MAX_CATALOG_SOURCE_ERRORS or any(
            not isinstance(item, CatalogSourceError) for item in errors
        ):
            raise ValueError("catalog source errors are invalid")
        object.__setattr__(self, "errors", errors)


@dataclass(frozen=True)
class FederatedCatalogMetadata:
    """Bounded discovery metadata retained without artifact authority."""

    upstream_id: str
    canonical_package_id: str | None
    name: str
    component: str
    canonical_origin: str
    detail_url: str
    artifact_url: str | None
    curated: bool
    popularity: int | None
    upstream_audit: str | None
    artifact_resolved: bool
    source_present: bool
    install_authorized: bool = False
    observed_at: str | None = None
    discovery_location: str | None = None
    immutable_ref: str | None = None
    content_hash: str | None = None
    relative_path: str | None = None

    def __post_init__(self) -> None:
        _validate_identity(self.upstream_id, field_name="federated upstream id")
        if self.canonical_package_id is not None:
            _validate_mcp_name(self.canonical_package_id)
        _validate_bounded_metadata(self.name, "federated display name", 512)
        if self.component not in {"skill", "mcp"}:
            raise ValueError("federated component is invalid")
        _validate_https_origin(self.canonical_origin)
        _validate_https_url(self.detail_url)
        if self.artifact_url is not None:
            _validate_https_url(self.artifact_url)
        if not isinstance(self.curated, bool):
            raise ValueError("federated curated flag must be a boolean")
        if self.popularity is not None and (
            isinstance(self.popularity, bool)
            or not isinstance(self.popularity, int)
            or self.popularity < 0
        ):
            raise ValueError("federated popularity is invalid")
        if self.upstream_audit not in {
            None,
            "reported_approved",
            "reported_reviewed",
        }:
            raise ValueError("federated upstream audit is invalid")
        if not isinstance(self.artifact_resolved, bool) or not isinstance(
            self.source_present, bool
        ):
            raise ValueError("federated state flags must be booleans")
        if self.install_authorized is not False:
            raise ValueError("federated metadata cannot authorize installation")
        if self.observed_at is not None:
            _parse_timestamp(self.observed_at)
        if self.discovery_location is not None:
            _validate_bounded_metadata(
                self.discovery_location, "federated discovery location", 512
            )
        if self.immutable_ref is not None:
            _validate_immutable_ref(self.immutable_ref)
        if self.content_hash is not None:
            _validate_hash(self.content_hash, field_name="federated content hash")
        if self.relative_path is not None:
            _validate_relative_path(self.relative_path)


@dataclass(frozen=True)
class CatalogEntry:
    """One immutable package/server version plus mutable source visibility."""

    catalog_id: str
    source_id: str
    source_type: CatalogSourceType
    package_id: str
    version: str
    immutable_ref: str | None
    content_hash: str
    status: CatalogEntryStatus
    pinned: bool
    source_present: bool
    install_authorized: bool
    first_seen_at: str
    last_seen_at: str
    package: IntegrationPackage | None = None
    mcp_response: Mapping[str, Any] | None = None
    federated: FederatedCatalogMetadata | None = None

    def __post_init__(self) -> None:
        _validate_identity(self.catalog_id, field_name="catalog id")
        _validate_identity(self.source_id, field_name="catalog source id")
        if not isinstance(self.source_type, CatalogSourceType):
            raise ValueError("catalog source type is invalid")
        _validate_identity(self.package_id, field_name="catalog package id")
        _validate_identity(self.version, field_name="catalog version")
        if self.immutable_ref is not None:
            _validate_immutable_ref(self.immutable_ref)
        _validate_hash(self.content_hash, field_name="catalog content hash")
        if not isinstance(self.status, CatalogEntryStatus):
            raise ValueError("catalog entry status is invalid")
        if not isinstance(self.pinned, bool):
            raise ValueError("catalog pinned flag must be a boolean")
        if not isinstance(self.source_present, bool):
            raise ValueError("catalog source presence must be a boolean")
        if self.install_authorized is not False:
            raise ValueError("catalog entries cannot authorize installation")
        _parse_timestamp(self.first_seen_at)
        _parse_timestamp(self.last_seen_at)
        if _parse_timestamp(self.first_seen_at) > _parse_timestamp(self.last_seen_at):
            raise ValueError("catalog first_seen_at cannot follow last_seen_at")
        if self.catalog_id != _catalog_id(
            self.source_id,
            self.package_id,
            self.version,
        ):
            raise ValueError("catalog id does not match source identity")
        if (
            self.package is None
            and self.mcp_response is None
            and self.federated is None
        ):
            raise ValueError("catalog entry must contain a payload")
        if self.package is not None and self.mcp_response is not None:
            raise ValueError("catalog entry cannot contain package and MCP payloads")
        if self.federated is not None:
            if self.source_type not in {
                CatalogSourceType.FEDERATED_CATALOG,
                CatalogSourceType.GIT,
            }:
                raise ValueError(
                    "federated metadata requires a federated or reviewed Git source"
                )
            if self.federated.source_present != self.source_present:
                raise ValueError("federated source presence does not match entry")
            if self.federated.artifact_resolved != (self.package is not None):
                raise ValueError("federated artifact resolution does not match payload")
        if self.package is not None:
            if (
                self.package.id != self.package_id
                or self.package.version != self.version
            ):
                raise ValueError("catalog package identity does not match manifest")
            if self.package.immutable_ref != self.immutable_ref:
                raise ValueError("catalog immutable ref does not match manifest")
            if integration_package_semantic_hash(self.package) != self.content_hash:
                raise ValueError("catalog package content hash does not match")
            if self.status is not CatalogEntryStatus.ACTIVE:
                raise ValueError("manifest catalog entries must be active")
            if self.immutable_ref is None or self.pinned is not True:
                raise ValueError("manifest catalog entries require immutable pins")
            if self.source_type is CatalogSourceType.FEDERATED_CATALOG:
                if self.package.source_type is not IntegrationSourceType.GIT:
                    raise ValueError("federated packages must retain Git provenance")
            else:
                _validate_import_source(self.package.source_type, self.source_type)
        elif self.mcp_response is not None:
            if self.immutable_ref is None or self.pinned is not True:
                raise ValueError("MCP response entries require immutable pins")
            if (
                self.source_type is not CatalogSourceType.OFFICIAL_MCP_REGISTRY
                or self.source_id != OFFICIAL_MCP_REGISTRY_SOURCE_ID
            ):
                raise ValueError("MCP response entries require the official source")
            response = _normalize_mcp_response(self.mcp_response)
            server = response["server"]
            if server["name"] != self.package_id or server["version"] != self.version:
                raise ValueError("catalog MCP identity does not match response")
            if self.immutable_ref != f"{self.package_id}@{self.version}":
                raise ValueError("catalog MCP immutable ref does not match response")
            if _json_hash(server) != self.content_hash:
                raise ValueError("catalog MCP content hash does not match")
            if self.status is not _mcp_status(response):
                raise ValueError("catalog MCP status does not match response")
            object.__setattr__(self, "mcp_response", response)
        elif self.immutable_ref is not None or self.pinned:
            raise ValueError("discovery-only entries cannot claim immutable pins")

    @property
    def trust_decision(self) -> IntegrationTrustDecision:
        """Return package trust or the fail-closed raw-registry default."""
        if self.package is None:
            return IntegrationTrustDecision.REVIEW_REQUIRED
        return assess_integration_package(self.package).decision


@dataclass(frozen=True)
class CatalogSnapshot:
    """Complete local catalog snapshot loaded without upstream access."""

    revision: int
    updated_at: str | None
    entries: tuple[CatalogEntry, ...]
    sources: tuple[CatalogSourceState, ...]


@dataclass(frozen=True)
class CatalogSyncResult:
    """Result of one all-or-nothing source synchronization attempt."""

    success: bool
    fetched_count: int
    stored_count: int
    errors: tuple[CatalogSourceError, ...]


RegistryPageFetcher = Callable[..., Awaitable[Mapping[str, Any]]]


class IntegrationCatalogStore:
    """Atomically persist immutable catalog pins and source health."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(data_dir).expanduser().resolve() / "integrations"
        self.path = self.root / "catalog.json"
        self.lock_path = self.root / ".catalog.json.lock"
        self._now = now or (lambda: datetime.now(timezone.utc))

    def snapshot(self) -> CatalogSnapshot:
        """Load the last complete local snapshot without network access."""
        self._ensure_root()
        with exclusive_file_lock(self.path):
            return self._read_unlocked()

    def list(self) -> tuple[CatalogEntry, ...]:
        """Return all cached catalog entries in deterministic order."""
        return self.snapshot().entries

    def get(self, catalog_id: str) -> CatalogEntry | None:
        """Return one catalog entry by stable local id."""
        _validate_identity(catalog_id, field_name="catalog id")
        return next(
            (item for item in self.snapshot().entries if item.catalog_id == catalog_id),
            None,
        )

    def delete_definition(
        self,
        catalog_id: str,
        *,
        expected_revision: int,
    ) -> CatalogEntry:
        """Delete one exact user-owned catalog definition after dependency checks."""
        _validate_identity(catalog_id, field_name="catalog id")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("catalog expected revision is invalid")
        self._ensure_root()
        with exclusive_file_lock(self.path):
            snapshot = self._read_unlocked()
            if snapshot.revision != expected_revision:
                raise CatalogConflictError(
                    "catalog changed after definition deletion preview"
                )
            entry = next(
                (item for item in snapshot.entries if item.catalog_id == catalog_id),
                None,
            )
            if entry is None:
                raise CatalogConflictError("catalog definition was not found")
            if entry.source_type not in {
                CatalogSourceType.GIT,
                CatalogSourceType.LOCAL,
            }:
                raise CatalogConflictError(
                    "only user-owned Git or local definitions can be deleted"
                )
            remaining = tuple(
                item for item in snapshot.entries if item.catalog_id != catalog_id
            )
            sources = tuple(
                replace(
                    source,
                    entry_count=sum(
                        item.source_id == source.source_id for item in remaining
                    ),
                )
                if source.source_id == entry.source_id
                else source
                for source in snapshot.sources
            )
            self._write_unlocked(
                CatalogSnapshot(
                    revision=snapshot.revision + 1,
                    updated_at=_format_timestamp(self._now()),
                    entries=remaining,
                    sources=sources,
                )
            )
            return entry

    def import_package(
        self,
        package: IntegrationPackage,
        *,
        source_id: str,
        source_type: CatalogSourceType,
        federated: FederatedCatalogMetadata | None = None,
    ) -> CatalogEntry:
        """Import one reviewed immutable manifest without reading its source."""
        if not isinstance(package, IntegrationPackage):
            raise TypeError("catalog import requires an IntegrationPackage")
        _validate_import_source(package.source_type, source_type)
        timestamp = _format_timestamp(self._now())
        entry = CatalogEntry(
            catalog_id=_catalog_id(source_id, package.id, package.version),
            source_id=source_id,
            source_type=source_type,
            package_id=package.id,
            version=package.version,
            immutable_ref=package.immutable_ref,
            content_hash=integration_package_semantic_hash(package),
            status=CatalogEntryStatus.ACTIVE,
            pinned=True,
            source_present=True,
            install_authorized=False,
            first_seen_at=timestamp,
            last_seen_at=timestamp,
            package=package,
            federated=federated,
        )
        result = self._merge_source(
            source_id=source_id,
            source_type=source_type,
            incoming=(entry,),
            observed_at=timestamp,
            complete=False,
            raise_on_conflict=True,
        )
        stored = self.get(entry.catalog_id)
        if stored is None:  # pragma: no cover - guarded by the merge contract
            raise CatalogStateError("catalog import was not persisted")
        if not result.success:  # pragma: no cover - conflicts raise above
            raise CatalogConflictError("catalog import conflicted")
        return stored

    def import_manifest(
        self,
        payload: Mapping[str, Any],
        *,
        source_id: str,
        source_type: CatalogSourceType,
    ) -> CatalogEntry:
        """Parse and import one strict N4 IntegrationPackage manifest."""
        return self.import_package(
            integration_package_from_dict(payload),
            source_id=source_id,
            source_type=source_type,
        )

    def _merge_source(
        self,
        *,
        source_id: str,
        source_type: CatalogSourceType,
        incoming: Sequence[CatalogEntry],
        observed_at: str,
        complete: bool,
        raise_on_conflict: bool = False,
        fail_entire_source_on_conflict: bool = False,
        cursor: str | None = None,
        retry_count: int = 0,
        next_retry_at: str | None = None,
        etag: str | None = None,
        freshness_expires_at: str | None = None,
    ) -> CatalogSyncResult:
        _validate_identity(source_id, field_name="catalog source id")
        if not isinstance(source_type, CatalogSourceType):
            raise ValueError("catalog source type is invalid")
        incoming_by_id = {item.catalog_id: item for item in incoming}
        if len(incoming_by_id) != len(incoming):
            raise ValueError("catalog source returned duplicate entries")
        if len(incoming_by_id) > MAX_CATALOG_SOURCE_ENTRIES:
            raise ValueError("catalog source returned too many entries")
        self._ensure_root()
        with exclusive_file_lock(self.path):
            snapshot = self._read_unlocked()
            entries = {item.catalog_id: item for item in snapshot.entries}
            original_entries = dict(entries)
            errors: list[CatalogSourceError] = []
            for catalog_id, candidate in incoming_by_id.items():
                if (
                    candidate.source_id != source_id
                    or candidate.source_type is not source_type
                ):
                    raise ValueError("catalog entry source does not match merge source")
                current = entries.get(catalog_id)
                if current is not None and (
                    current.content_hash != candidate.content_hash
                    or current.immutable_ref != candidate.immutable_ref
                ):
                    error = _source_error(
                        code="source.immutable_conflict",
                        source_id=source_id,
                        error_type="CatalogConflictError",
                        occurred_at=observed_at,
                    )
                    errors.append(error)
                    if raise_on_conflict:
                        raise CatalogConflictError(
                            "catalog source attempted to replace an immutable pin"
                        )
                    continue
                if current is not None:
                    candidate = replace(
                        candidate,
                        first_seen_at=current.first_seen_at,
                        last_seen_at=observed_at,
                        source_present=True,
                        federated=(
                            replace(candidate.federated, source_present=True)
                            if candidate.federated is not None
                            else None
                        ),
                    )
                entries[catalog_id] = candidate
            if errors and fail_entire_source_on_conflict:
                entries = original_entries
            elif complete:
                for catalog_id, current in tuple(entries.items()):
                    if (
                        current.source_id == source_id
                        and catalog_id not in incoming_by_id
                    ):
                        entries[catalog_id] = replace(
                            current,
                            source_present=False,
                            federated=(
                                replace(current.federated, source_present=False)
                                if current.federated is not None
                                else None
                            ),
                        )
            if len(entries) > MAX_CATALOG_ENTRIES:
                raise CatalogStateError("catalog contains too many entries")
            source_states = {item.source_id: item for item in snapshot.sources}
            previous = source_states.get(source_id)
            if previous is not None and previous.source_type is not source_type:
                raise CatalogConflictError("catalog source id is owned by another type")
            combined_errors = _bounded_errors(
                *(previous.errors if previous is not None else ()), *errors
            )
            attempt_succeeded = not errors
            source_states[source_id] = CatalogSourceState(
                source_id=source_id,
                source_type=source_type,
                last_attempt_at=observed_at,
                last_success_at=(
                    observed_at
                    if attempt_succeeded
                    else (previous.last_success_at if previous is not None else None)
                ),
                last_attempt_succeeded=attempt_succeeded,
                complete=complete and attempt_succeeded,
                entry_count=sum(
                    item.source_id == source_id for item in entries.values()
                ),
                cursor=cursor if attempt_succeeded else None,
                retry_count=retry_count,
                next_retry_at=next_retry_at,
                etag=etag,
                freshness_expires_at=freshness_expires_at,
                errors=combined_errors,
            )
            updated = CatalogSnapshot(
                revision=snapshot.revision + 1,
                updated_at=observed_at,
                entries=tuple(sorted(entries.values(), key=_entry_sort_key)),
                sources=tuple(
                    sorted(source_states.values(), key=lambda item: item.source_id)
                ),
            )
            self._write_unlocked(updated)
        return CatalogSyncResult(
            success=not errors,
            fetched_count=len(incoming),
            stored_count=sum(item.source_id == source_id for item in updated.entries),
            errors=tuple(errors),
        )

    def _record_source_failure(
        self,
        *,
        source_id: str,
        source_type: CatalogSourceType,
        error: CatalogSourceError,
        observed_at: str,
        retry_count: int | None = None,
        next_retry_at: str | None = None,
    ) -> CatalogSyncResult:
        self._ensure_root()
        with exclusive_file_lock(self.path):
            snapshot = self._read_unlocked()
            source_states = {item.source_id: item for item in snapshot.sources}
            previous = source_states.get(source_id)
            if previous is not None and previous.source_type is not source_type:
                raise CatalogConflictError("catalog source id is owned by another type")
            source_states[source_id] = CatalogSourceState(
                source_id=source_id,
                source_type=source_type,
                last_attempt_at=observed_at,
                last_success_at=(
                    previous.last_success_at if previous is not None else None
                ),
                last_attempt_succeeded=False,
                complete=False,
                entry_count=sum(
                    item.source_id == source_id for item in snapshot.entries
                ),
                cursor=previous.cursor if previous is not None else None,
                retry_count=(
                    retry_count
                    if retry_count is not None
                    else min(
                        previous.retry_count + 1 if previous is not None else 1,
                        100,
                    )
                ),
                next_retry_at=next_retry_at,
                etag=previous.etag if previous is not None else None,
                freshness_expires_at=(
                    previous.freshness_expires_at if previous is not None else None
                ),
                errors=_bounded_errors(
                    *(previous.errors if previous is not None else ()), error
                ),
            )
            updated = CatalogSnapshot(
                revision=snapshot.revision + 1,
                updated_at=observed_at,
                entries=snapshot.entries,
                sources=tuple(
                    sorted(source_states.values(), key=lambda item: item.source_id)
                ),
            )
            self._write_unlocked(updated)
        return CatalogSyncResult(
            success=False,
            fetched_count=0,
            stored_count=sum(item.source_id == source_id for item in updated.entries),
            errors=(error,),
        )

    def merge_federated_source(
        self,
        *,
        source_id: str,
        incoming: Sequence[CatalogEntry],
        observed_at: str,
        freshness_expires_at: str,
        etag: str | None = None,
    ) -> CatalogSyncResult:
        """Atomically publish one complete federated source snapshot."""
        return self._merge_source(
            source_id=source_id,
            source_type=CatalogSourceType.FEDERATED_CATALOG,
            incoming=incoming,
            observed_at=observed_at,
            complete=True,
            fail_entire_source_on_conflict=True,
            cursor=None,
            retry_count=0,
            next_retry_at=None,
            etag=etag,
            freshness_expires_at=freshness_expires_at,
        )

    def record_federated_failure(
        self,
        *,
        source_id: str,
        code: str,
        error_type: str,
        observed_at: str,
        retry_count: int,
        next_retry_at: str,
    ) -> CatalogSyncResult:
        """Retain last-good federated entries and bounded retry state."""
        return self._record_source_failure(
            source_id=source_id,
            source_type=CatalogSourceType.FEDERATED_CATALOG,
            error=_source_error(
                code=code,
                source_id=source_id,
                error_type=error_type,
                occurred_at=observed_at,
            ),
            observed_at=observed_at,
            retry_count=retry_count,
            next_retry_at=next_retry_at,
        )

    def _ensure_root(self) -> None:
        if self.root.is_symlink():
            raise CatalogStateError("integration catalog root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink() or self.lock_path.is_symlink():
            raise CatalogStateError("integration catalog state cannot be a symlink")
        try:
            os.chmod(self.root, 0o700)
        except OSError:  # pragma: no cover - permission hardening is best effort
            pass

    def _read_unlocked(self) -> CatalogSnapshot:
        if not self.path.exists():
            return CatalogSnapshot(revision=0, updated_at=None, entries=(), sources=())
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return _snapshot_from_dict(payload)
        except CatalogStateError:
            raise
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise CatalogStateError("integration catalog state is unreadable") from exc

    def _write_unlocked(self, snapshot: CatalogSnapshot) -> None:
        payload = _snapshot_to_dict(snapshot)
        content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
        _atomic_write_private(self.path, content)


async def sync_official_mcp_registry(
    store: IntegrationCatalogStore,
    *,
    fetch_page: RegistryPageFetcher | None = None,
    page_size: int = 100,
) -> CatalogSyncResult:
    """Fetch every official Registry page before atomically merging the cache."""
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or page_size < 1
        or page_size > MAX_CATALOG_PAGE_SIZE
    ):
        raise ValueError("registry page_size is invalid")
    fetcher = fetch_page or fetch_official_mcp_registry_page
    observed_at = _format_timestamp(store._now())
    cursor: str | None = None
    seen_cursors: set[str] = set()
    entries: dict[str, CatalogEntry] = {}
    try:
        for _page_number in range(MAX_REGISTRY_PAGES):
            payload = await fetcher(
                cursor=cursor,
                limit=page_size,
                include_deleted=True,
            )
            responses, next_cursor = _parse_registry_page(payload)
            for response in responses:
                entry = _official_registry_entry(response, observed_at=observed_at)
                existing = entries.get(entry.catalog_id)
                if existing is not None and existing.content_hash != entry.content_hash:
                    raise CatalogConflictError(
                        "official registry page contains conflicting immutable entries"
                    )
                entries[entry.catalog_id] = entry
            if len(entries) > MAX_CATALOG_SOURCE_ENTRIES:
                raise ValueError("official registry returned too many entries")
            if next_cursor is None:
                break
            if next_cursor in seen_cursors:
                raise ValueError("official registry repeated a pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise ValueError("official registry exceeded the page bound")
    except Exception as exc:
        error = _source_error(
            code="source.fetch_failed",
            source_id=OFFICIAL_MCP_REGISTRY_SOURCE_ID,
            error_type=type(exc).__name__,
            occurred_at=observed_at,
        )
        return store._record_source_failure(
            source_id=OFFICIAL_MCP_REGISTRY_SOURCE_ID,
            source_type=CatalogSourceType.OFFICIAL_MCP_REGISTRY,
            error=error,
            observed_at=observed_at,
        )
    return store._merge_source(
        source_id=OFFICIAL_MCP_REGISTRY_SOURCE_ID,
        source_type=CatalogSourceType.OFFICIAL_MCP_REGISTRY,
        incoming=tuple(entries.values()),
        observed_at=observed_at,
        complete=True,
    )


async def fetch_official_mcp_registry_page(
    *,
    cursor: str | None,
    limit: int,
    include_deleted: bool,
) -> Mapping[str, Any]:
    """Read one bounded page from the fixed official Registry endpoint."""
    parameters: dict[str, str] = {
        "limit": str(limit),
        "include_deleted": "true" if include_deleted else "false",
    }
    if cursor is not None:
        parameters["cursor"] = cursor
    url = (
        f"{OFFICIAL_MCP_REGISTRY_BASE_URL}/{OFFICIAL_MCP_REGISTRY_API_VERSION}/"
        f"servers?{urllib_parse.urlencode(parameters)}"
    )
    return await anyio.to_thread.run_sync(lambda: _read_registry_url(url))


class MCPSubregistry:
    """Serve MCP Registry-compatible reads exclusively from the local cache."""

    def __init__(self, store: IntegrationCatalogStore) -> None:
        self.store = store

    def list_servers(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        search: str | None = None,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Return a deterministic local Registry page without upstream access."""
        _validate_page_limit(limit)
        _validate_include_deleted(include_deleted)
        entries = self._mcp_entries(include_deleted=include_deleted)
        if search is not None:
            if not isinstance(search, str):
                raise ValueError("subregistry search must be text")
            query = search.strip().casefold()
            if len(query) > 200:
                raise ValueError("subregistry search is too long")
            if query:
                entries = tuple(item for item in entries if _entry_matches(item, query))
        start = _cursor_start(entries, cursor)
        selected = entries[start : start + limit]
        next_cursor = None
        if start + len(selected) < len(entries) and selected:
            next_cursor = _encode_cursor(selected[-1].catalog_id)
        metadata: dict[str, Any] = {"count": len(selected)}
        if next_cursor is not None:
            metadata["nextCursor"] = next_cursor
        return {
            "servers": [_subregistry_response(item) for item in selected],
            "metadata": metadata,
        }

    def list_versions(
        self,
        server_name: str,
        *,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Return all locally cached versions for one MCP server."""
        _validate_mcp_name(server_name)
        _validate_include_deleted(include_deleted)
        entries = tuple(
            item
            for item in self._mcp_entries(include_deleted=include_deleted)
            if item.package_id == server_name
        )
        if not entries:
            raise KeyError(server_name)
        entries = tuple(sorted(entries, key=_published_at, reverse=True))
        return {
            "servers": [_subregistry_response(item) for item in entries],
            "metadata": {"count": len(entries)},
        }

    def get_version(
        self,
        server_name: str,
        version: str,
        *,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Return one exact or locally declared latest MCP version."""
        _validate_mcp_name(server_name)
        _validate_identity(version, field_name="MCP version")
        _validate_include_deleted(include_deleted)
        entries = tuple(
            item
            for item in self._mcp_entries(include_deleted=include_deleted)
            if item.package_id == server_name
        )
        if version == "latest":
            latest = next((item for item in entries if _is_latest(item)), None)
            if latest is None:
                raise KeyError((server_name, version))
            return _subregistry_response(latest)
        match = next((item for item in entries if item.version == version), None)
        if match is None:
            raise KeyError((server_name, version))
        return _subregistry_response(match)

    def _mcp_entries(self, *, include_deleted: bool) -> tuple[CatalogEntry, ...]:
        return tuple(
            item
            for item in self.store.list()
            if item.mcp_response is not None
            and (include_deleted or item.status is not CatalogEntryStatus.DELETED)
        )


def catalog_entry_to_dict(entry: CatalogEntry) -> dict[str, Any]:
    """Serialize one local catalog entry without implying install authority."""
    return {
        "catalog_id": entry.catalog_id,
        "source_id": entry.source_id,
        "source_type": entry.source_type.value,
        "package_id": entry.package_id,
        "version": entry.version,
        "immutable_ref": entry.immutable_ref,
        "content_hash": entry.content_hash,
        "status": entry.status.value,
        "pinned": entry.pinned,
        "source_present": entry.source_present,
        "install_authorized": entry.install_authorized,
        "trust_decision": entry.trust_decision.value,
        "first_seen_at": entry.first_seen_at,
        "last_seen_at": entry.last_seen_at,
        "federated": (
            _federated_metadata_to_dict(entry.federated)
            if entry.federated is not None
            else None
        ),
    }


def _official_registry_entry(
    response: Mapping[str, Any],
    *,
    observed_at: str,
) -> CatalogEntry:
    normalized = _normalize_mcp_response(response)
    server = normalized["server"]
    package_id = server["name"]
    version = server["version"]
    return CatalogEntry(
        catalog_id=_catalog_id(OFFICIAL_MCP_REGISTRY_SOURCE_ID, package_id, version),
        source_id=OFFICIAL_MCP_REGISTRY_SOURCE_ID,
        source_type=CatalogSourceType.OFFICIAL_MCP_REGISTRY,
        package_id=package_id,
        version=version,
        immutable_ref=f"{package_id}@{version}",
        content_hash=_json_hash(server),
        status=_mcp_status(normalized),
        pinned=True,
        source_present=True,
        install_authorized=False,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
        mcp_response=normalized,
    )


def _parse_registry_page(
    payload: Mapping[str, Any],
) -> tuple[tuple[Mapping[str, Any], ...], str | None]:
    if not isinstance(payload, Mapping):
        raise ValueError("official registry page must be an object")
    if set(payload) - {"servers", "metadata"}:
        raise ValueError("official registry page contains unknown fields")
    servers = payload.get("servers")
    if not isinstance(servers, list) or len(servers) > MAX_CATALOG_PAGE_SIZE:
        raise ValueError("official registry servers are invalid")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ValueError("official registry metadata must be an object")
    count = metadata.get("count")
    if count is not None and (
        isinstance(count, bool) or not isinstance(count, int) or count != len(servers)
    ):
        raise ValueError("official registry page count does not match")
    cursor = metadata.get("nextCursor")
    if cursor is not None:
        if not isinstance(cursor, str) or len(cursor) > 2_048:
            raise ValueError("official registry nextCursor is invalid")
        cursor = cursor or None
    return tuple(_normalize_mcp_response(item) for item in servers), cursor


def _normalize_mcp_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("MCP registry response must be an object")
    if set(value) - {"server", "_meta"}:
        raise ValueError("MCP registry response contains unknown fields")
    safe = _sanitize_json(value)
    server = safe.get("server")
    if not isinstance(server, Mapping):
        raise ValueError("MCP registry response requires server metadata")
    name = server.get("name")
    version = server.get("version")
    description = server.get("description")
    _validate_mcp_name(name)
    _validate_identity(version, field_name="MCP version")
    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description) > 100
    ):
        raise ValueError("MCP description is invalid")
    metadata = safe.get("_meta", {})
    if not isinstance(metadata, Mapping):
        raise ValueError("MCP registry metadata must be an object")
    official = metadata.get(_MCP_OFFICIAL_META_KEY, {})
    if not isinstance(official, Mapping):
        raise ValueError("official MCP registry metadata must be an object")
    if set(official) - {
        "status",
        "statusMessage",
        "statusChangedAt",
        "publishedAt",
        "updatedAt",
        "isLatest",
    }:
        raise ValueError("official MCP registry metadata contains unknown fields")
    status = official.get("status", CatalogEntryStatus.ACTIVE.value)
    try:
        CatalogEntryStatus(status)
    except (TypeError, ValueError) as exc:
        raise ValueError("official MCP registry status is invalid") from exc
    status_message = official.get("statusMessage")
    if status_message is not None and (
        not isinstance(status_message, str) or len(status_message) > 500
    ):
        raise ValueError("official MCP registry statusMessage is invalid")
    for field_name in ("statusChangedAt", "publishedAt", "updatedAt"):
        timestamp = official.get(field_name)
        if timestamp is not None:
            _parse_timestamp(timestamp)
    is_latest = official.get("isLatest")
    if is_latest is not None and not isinstance(is_latest, bool):
        raise ValueError("official MCP registry isLatest is invalid")
    return safe


def _sanitize_json(value: Any) -> Any:
    sanitized = _sanitize_json_value(value, depth=0, secret_input=False)
    sanitized = redact_secrets(sanitized)
    try:
        encoded = json.dumps(
            sanitized,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("catalog source metadata must be JSON-compatible") from exc
    if len(encoded) > MAX_CATALOG_JSON_BYTES:
        raise ValueError("catalog source metadata is too large")
    return json.loads(encoded.decode("utf-8"))


def _sanitize_json_value(value: Any, *, depth: int, secret_input: bool) -> Any:
    if depth > MAX_CATALOG_JSON_DEPTH:
        raise ValueError("catalog source metadata is too deeply nested")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("catalog source metadata keys must be text")
        marks_secret = value.get("isSecret") is True
        return {
            key: (
                REDACTED
                if (secret_input or marks_secret) and key in {"value", "default"}
                else _sanitize_json_value(
                    item,
                    depth=depth + 1,
                    secret_input=(secret_input or marks_secret),
                )
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_json_value(item, depth=depth + 1, secret_input=secret_input)
            for item in value
        ]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("catalog source metadata must be JSON-compatible")


def _subregistry_response(entry: CatalogEntry) -> dict[str, Any]:
    response = _sanitize_json(entry.mcp_response)
    metadata = dict(response.get("_meta", {}))
    metadata[_LOCAL_SUBREGISTRY_META_KEY] = {
        "catalogId": entry.catalog_id,
        "sourceId": entry.source_id,
        "sourceType": entry.source_type.value,
        "immutableRef": entry.immutable_ref,
        "contentHash": entry.content_hash,
        "pinned": True,
        "sourcePresent": entry.source_present,
        "installAuthorized": False,
        "trustDecision": entry.trust_decision.value,
    }
    response["_meta"] = metadata
    return response


def _mcp_status(response: Mapping[str, Any]) -> CatalogEntryStatus:
    metadata = response.get("_meta", {})
    official = metadata.get(_MCP_OFFICIAL_META_KEY, {})
    return CatalogEntryStatus(official.get("status", CatalogEntryStatus.ACTIVE.value))


def _is_latest(entry: CatalogEntry) -> bool:
    if entry.mcp_response is None:
        return False
    metadata = entry.mcp_response.get("_meta", {})
    official = metadata.get(_MCP_OFFICIAL_META_KEY, {})
    return official.get("isLatest") is True


def _published_at(entry: CatalogEntry) -> datetime:
    if entry.mcp_response is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    metadata = entry.mcp_response.get("_meta", {})
    official = metadata.get(_MCP_OFFICIAL_META_KEY, {})
    value = official.get("publishedAt")
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return _parse_timestamp(value).astimezone(timezone.utc)


def _entry_matches(entry: CatalogEntry, query: str) -> bool:
    if entry.mcp_response is None:
        return False
    server = entry.mcp_response["server"]
    values = (server.get("name"), server.get("title"), server.get("description"))
    return any(query in str(value).casefold() for value in values if value is not None)


def _cursor_start(entries: Sequence[CatalogEntry], cursor: str | None) -> int:
    if cursor is None:
        return 0
    catalog_id = _decode_cursor(cursor)
    for index, entry in enumerate(entries):
        if entry.catalog_id == catalog_id:
            return index + 1
    raise ValueError("subregistry cursor does not match the current query")


def _encode_cursor(catalog_id: str) -> str:
    return (
        base64.urlsafe_b64encode(catalog_id.encode("utf-8")).decode("ascii").rstrip("=")
    )


def _decode_cursor(cursor: str) -> str:
    if not isinstance(cursor, str) or not cursor or len(cursor) > 512:
        raise ValueError("subregistry cursor is invalid")
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("subregistry cursor is invalid") from exc
    _validate_identity(decoded, field_name="catalog id")
    return decoded


def _validate_page_limit(limit: int) -> None:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 1
        or limit > MAX_CATALOG_PAGE_SIZE
    ):
        raise ValueError("subregistry limit is invalid")


def _validate_include_deleted(value: Any) -> None:
    if not isinstance(value, bool):
        raise ValueError("subregistry include_deleted must be a boolean")


def _validate_import_source(
    package_source: IntegrationSourceType,
    catalog_source: CatalogSourceType,
) -> None:
    expected = {
        CatalogSourceType.LOCAL_PRIVATE: IntegrationSourceType.CURATED_CATALOG,
        CatalogSourceType.PROVIDER_MARKETPLACE: IntegrationSourceType.PROVIDER_MARKETPLACE,
        CatalogSourceType.GIT: IntegrationSourceType.GIT,
        CatalogSourceType.LOCAL: IntegrationSourceType.LOCAL,
    }.get(catalog_source)
    if expected is None or package_source is not expected:
        raise ValueError("catalog import source does not match manifest source_type")


def _snapshot_to_dict(snapshot: CatalogSnapshot) -> dict[str, Any]:
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "revision": snapshot.revision,
        "updated_at": snapshot.updated_at,
        "entries": [_entry_to_state(item) for item in snapshot.entries],
        "sources": [_source_state_to_dict(item) for item in snapshot.sources],
    }


def _snapshot_from_dict(value: Any) -> CatalogSnapshot:
    mapping = _strict_mapping(
        value,
        allowed={"schema_version", "revision", "updated_at", "entries", "sources"},
        field_name="integration catalog",
    )
    if mapping.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise CatalogStateError("unsupported integration catalog schema_version")
    revision = mapping.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise CatalogStateError("integration catalog revision is invalid")
    updated_at = mapping.get("updated_at")
    if updated_at is not None:
        _parse_timestamp(updated_at)
    raw_entries = mapping.get("entries")
    raw_sources = mapping.get("sources")
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_CATALOG_ENTRIES:
        raise CatalogStateError("integration catalog entries are invalid")
    if not isinstance(raw_sources, list) or len(raw_sources) > MAX_CATALOG_SOURCES:
        raise CatalogStateError("integration catalog sources are invalid")
    entries = tuple(_entry_from_state(item) for item in raw_entries)
    sources = tuple(_source_state_from_dict(item) for item in raw_sources)
    if len({item.catalog_id for item in entries}) != len(entries):
        raise CatalogStateError("integration catalog contains duplicate ids")
    if len({item.source_id for item in sources}) != len(sources):
        raise CatalogStateError("integration catalog contains duplicate sources")
    if entries != tuple(sorted(entries, key=_entry_sort_key)):
        raise CatalogStateError("integration catalog entries are not normalized")
    if sources != tuple(sorted(sources, key=lambda item: item.source_id)):
        raise CatalogStateError("integration catalog sources are not normalized")
    source_states = {item.source_id: item for item in sources}
    for entry in entries:
        state = source_states.get(entry.source_id)
        if state is None or state.source_type is not entry.source_type:
            raise CatalogStateError("catalog entry source state does not match")
    for state in sources:
        if state.entry_count != sum(
            item.source_id == state.source_id for item in entries
        ):
            raise CatalogStateError("catalog source entry_count does not match")
    if revision == 0 and (updated_at is not None or entries or sources):
        raise CatalogStateError("empty catalog revision contains state")
    if revision > 0 and updated_at is None:
        raise CatalogStateError("catalog updated_at is required")
    return CatalogSnapshot(
        revision=revision,
        updated_at=updated_at,
        entries=entries,
        sources=sources,
    )


def _entry_to_state(entry: CatalogEntry) -> dict[str, Any]:
    return {
        "catalog_id": entry.catalog_id,
        "source_id": entry.source_id,
        "source_type": entry.source_type.value,
        "package_id": entry.package_id,
        "version": entry.version,
        "immutable_ref": entry.immutable_ref,
        "content_hash": entry.content_hash,
        "status": entry.status.value,
        "pinned": entry.pinned,
        "source_present": entry.source_present,
        "install_authorized": entry.install_authorized,
        "first_seen_at": entry.first_seen_at,
        "last_seen_at": entry.last_seen_at,
        "package": (
            integration_package_to_dict(entry.package)
            if entry.package is not None
            else None
        ),
        "mcp_response": entry.mcp_response,
        "federated": (
            _federated_metadata_to_dict(entry.federated)
            if entry.federated is not None
            else None
        ),
    }


def _entry_from_state(value: Any) -> CatalogEntry:
    mapping = _strict_mapping(
        value,
        allowed={
            "catalog_id",
            "source_id",
            "source_type",
            "package_id",
            "version",
            "immutable_ref",
            "content_hash",
            "status",
            "pinned",
            "source_present",
            "install_authorized",
            "first_seen_at",
            "last_seen_at",
            "package",
            "mcp_response",
            "federated",
        },
        field_name="catalog entry",
    )
    package_payload = mapping.get("package")
    package = (
        integration_package_from_dict(package_payload)
        if package_payload is not None
        else None
    )
    return CatalogEntry(
        catalog_id=_required_text(mapping.get("catalog_id"), "catalog id"),
        source_id=_required_text(mapping.get("source_id"), "catalog source id"),
        source_type=_enum_value(
            CatalogSourceType, mapping.get("source_type"), "catalog source type"
        ),
        package_id=_required_text(mapping.get("package_id"), "catalog package id"),
        version=_required_text(mapping.get("version"), "catalog version"),
        immutable_ref=_optional_text(
            mapping.get("immutable_ref"), "catalog immutable ref"
        ),
        content_hash=_required_text(
            mapping.get("content_hash"), "catalog content hash"
        ),
        status=_enum_value(CatalogEntryStatus, mapping.get("status"), "catalog status"),
        pinned=_required_bool(mapping.get("pinned"), "catalog pinned"),
        source_present=_required_bool(
            mapping.get("source_present"), "catalog source_present"
        ),
        install_authorized=_required_bool(
            mapping.get("install_authorized"), "catalog install_authorized"
        ),
        first_seen_at=_required_text(
            mapping.get("first_seen_at"), "catalog first_seen_at"
        ),
        last_seen_at=_required_text(
            mapping.get("last_seen_at"), "catalog last_seen_at"
        ),
        package=package,
        mcp_response=mapping.get("mcp_response"),
        federated=(
            _federated_metadata_from_dict(mapping.get("federated"))
            if mapping.get("federated") is not None
            else None
        ),
    )


def _source_state_to_dict(state: CatalogSourceState) -> dict[str, Any]:
    return {
        "source_id": state.source_id,
        "source_type": state.source_type.value,
        "last_attempt_at": state.last_attempt_at,
        "last_success_at": state.last_success_at,
        "last_attempt_succeeded": state.last_attempt_succeeded,
        "complete": state.complete,
        "entry_count": state.entry_count,
        "cursor": state.cursor,
        "retry_count": state.retry_count,
        "next_retry_at": state.next_retry_at,
        "etag": state.etag,
        "freshness_expires_at": state.freshness_expires_at,
        "errors": [
            {
                "code": item.code,
                "source_id": item.source_id,
                "error_type": item.error_type,
                "occurred_at": item.occurred_at,
            }
            for item in state.errors
        ],
    }


def _source_state_from_dict(value: Any) -> CatalogSourceState:
    mapping = _strict_mapping(
        value,
        allowed={
            "source_id",
            "source_type",
            "last_attempt_at",
            "last_success_at",
            "last_attempt_succeeded",
            "complete",
            "entry_count",
            "cursor",
            "retry_count",
            "next_retry_at",
            "etag",
            "freshness_expires_at",
            "errors",
        },
        field_name="catalog source state",
    )
    errors = mapping.get("errors")
    if not isinstance(errors, list):
        raise ValueError("catalog source errors must be a list")
    return CatalogSourceState(
        source_id=_required_text(mapping.get("source_id"), "catalog source id"),
        source_type=_enum_value(
            CatalogSourceType, mapping.get("source_type"), "catalog source type"
        ),
        last_attempt_at=_required_text(
            mapping.get("last_attempt_at"), "catalog last_attempt_at"
        ),
        last_success_at=_optional_text(
            mapping.get("last_success_at"), "catalog last_success_at"
        ),
        last_attempt_succeeded=_required_bool(
            mapping.get("last_attempt_succeeded"), "catalog last_attempt_succeeded"
        ),
        complete=_required_bool(mapping.get("complete"), "catalog complete"),
        entry_count=_required_int(mapping.get("entry_count"), "catalog entry_count"),
        cursor=_optional_text(mapping.get("cursor"), "catalog source cursor"),
        retry_count=(
            _required_int(mapping.get("retry_count"), "catalog retry_count")
            if "retry_count" in mapping
            else 0
        ),
        next_retry_at=_optional_text(
            mapping.get("next_retry_at"), "catalog next_retry_at"
        ),
        etag=_optional_text(mapping.get("etag"), "catalog etag"),
        freshness_expires_at=_optional_text(
            mapping.get("freshness_expires_at"), "catalog freshness_expires_at"
        ),
        errors=tuple(_source_error_from_dict(item) for item in errors),
    )


def _federated_metadata_to_dict(
    metadata: FederatedCatalogMetadata,
) -> dict[str, Any]:
    return {
        "upstream_id": metadata.upstream_id,
        "canonical_package_id": metadata.canonical_package_id,
        "name": metadata.name,
        "component": metadata.component,
        "canonical_origin": metadata.canonical_origin,
        "detail_url": metadata.detail_url,
        "artifact_url": metadata.artifact_url,
        "curated": metadata.curated,
        "popularity": metadata.popularity,
        "upstream_audit": metadata.upstream_audit,
        "artifact_resolved": metadata.artifact_resolved,
        "source_present": metadata.source_present,
        "install_authorized": metadata.install_authorized,
        "observed_at": metadata.observed_at,
        "discovery_location": metadata.discovery_location,
        "immutable_ref": metadata.immutable_ref,
        "content_hash": metadata.content_hash,
        "relative_path": metadata.relative_path,
    }


def _federated_metadata_from_dict(value: Any) -> FederatedCatalogMetadata:
    mapping = _strict_mapping(
        value,
        allowed={
            "upstream_id",
            "canonical_package_id",
            "name",
            "component",
            "canonical_origin",
            "detail_url",
            "artifact_url",
            "curated",
            "popularity",
            "upstream_audit",
            "artifact_resolved",
            "source_present",
            "install_authorized",
            "observed_at",
            "discovery_location",
            "immutable_ref",
            "content_hash",
            "relative_path",
        },
        field_name="federated catalog metadata",
    )
    popularity = mapping.get("popularity")
    if popularity is not None:
        popularity = _required_int(popularity, "federated popularity")
    return FederatedCatalogMetadata(
        upstream_id=_required_text(mapping.get("upstream_id"), "federated upstream id"),
        canonical_package_id=_optional_text(
            mapping.get("canonical_package_id"), "federated canonical package id"
        ),
        name=_required_text(mapping.get("name"), "federated name"),
        component=_required_text(mapping.get("component"), "federated component"),
        canonical_origin=_required_text(
            mapping.get("canonical_origin"), "federated canonical origin"
        ),
        detail_url=_required_text(mapping.get("detail_url"), "federated detail URL"),
        artifact_url=_optional_text(
            mapping.get("artifact_url"), "federated artifact URL"
        ),
        curated=_required_bool(mapping.get("curated"), "federated curated"),
        popularity=popularity,
        upstream_audit=_optional_text(
            mapping.get("upstream_audit"), "federated upstream audit"
        ),
        artifact_resolved=_required_bool(
            mapping.get("artifact_resolved"), "federated artifact_resolved"
        ),
        source_present=_required_bool(
            mapping.get("source_present"), "federated source_present"
        ),
        install_authorized=_required_bool(
            mapping.get("install_authorized"), "federated install_authorized"
        ),
        observed_at=_optional_text(mapping.get("observed_at"), "federated observed_at"),
        discovery_location=_optional_text(
            mapping.get("discovery_location"), "federated discovery location"
        ),
        immutable_ref=_optional_text(
            mapping.get("immutable_ref"), "federated immutable ref"
        ),
        content_hash=_optional_text(
            mapping.get("content_hash"), "federated content hash"
        ),
        relative_path=_optional_text(
            mapping.get("relative_path"), "federated relative path"
        ),
    )


def _source_error_from_dict(value: Any) -> CatalogSourceError:
    mapping = _strict_mapping(
        value,
        allowed={"code", "source_id", "error_type", "occurred_at"},
        field_name="catalog source error",
    )
    return CatalogSourceError(
        code=_required_text(mapping.get("code"), "catalog source error code"),
        source_id=_required_text(mapping.get("source_id"), "catalog source id"),
        error_type=_required_text(mapping.get("error_type"), "catalog error type"),
        occurred_at=_required_text(
            mapping.get("occurred_at"), "catalog error timestamp"
        ),
    )


def _source_error(
    *,
    code: str,
    source_id: str,
    error_type: str,
    occurred_at: str,
) -> CatalogSourceError:
    safe_type = (
        re.sub(r"[^A-Za-z0-9._:+~-]", "_", error_type).lstrip("_")[:128] or "Error"
    )
    return CatalogSourceError(
        code=code,
        source_id=source_id,
        error_type=safe_type,
        occurred_at=occurred_at,
    )


def _bounded_errors(*errors: CatalogSourceError) -> tuple[CatalogSourceError, ...]:
    return tuple(errors[-MAX_CATALOG_SOURCE_ERRORS:])


def _catalog_id(source_id: str, package_id: str, version: str) -> str:
    _validate_identity(source_id, field_name="catalog source id")
    digest = hashlib.sha256(
        json.dumps(
            [source_id, package_id, version],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"catalog_{digest[:32]}"


def _entry_sort_key(entry: CatalogEntry) -> tuple[str, str, str, str]:
    return (entry.package_id, entry.version, entry.source_id, entry.catalog_id)


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _read_registry_url(url: str) -> Mapping[str, Any]:
    request = urllib_request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "gpt2giga-harness-integration-catalog/1",
        },
        method="GET",
    )
    opener = urllib_request.build_opener(_NoRedirectHandler())
    with opener.open(request, timeout=20.0) as response:
        content_type = response.headers.get_content_type()
        if content_type != "application/json":
            raise ValueError("official registry returned a non-JSON response")
        body = response.read(MAX_REGISTRY_RESPONSE_BYTES + 1)
    if len(body) > MAX_REGISTRY_RESPONSE_BYTES:
        raise ValueError("official registry response is too large")
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("official registry response must be an object")
    return payload


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("official registry redirects are not accepted")


def _atomic_write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _strict_mapping(
    value: Any,
    *,
    allowed: set[str],
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{field_name} contains unknown fields")
    return value


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be text")
    return value


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _required_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _required_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _enum_value(enum_type: type[Enum], value: Any, field_name: str):
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} is invalid") from exc


def _validate_identity(value: Any, *, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or _IDENTITY_RE.fullmatch(value) is None
        or redact_secrets(value) != value
    ):
        raise ValueError(f"{field_name} is invalid")


def _validate_mcp_name(value: Any) -> None:
    if (
        not isinstance(value, str)
        or len(value) < 3
        or len(value) > 200
        or _MCP_NAME_RE.fullmatch(value) is None
    ):
        raise ValueError("MCP server name is invalid")


def _validate_immutable_ref(value: Any) -> None:
    if not isinstance(value, str) or _IMMUTABLE_REF_RE.fullmatch(value) is None:
        raise ValueError("catalog immutable ref is invalid")


def _validate_bounded_metadata(value: Any, field_name: str, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError(f"{field_name} is invalid")


def _validate_https_url(value: Any) -> None:
    _validate_bounded_metadata(value, "federated HTTPS URL", 2_048)
    parsed = urllib_parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or parsed.fragment
    ):
        raise ValueError("federated HTTPS URL is invalid")


def _validate_https_origin(value: Any) -> None:
    _validate_https_url(value)
    parsed = urllib_parse.urlsplit(value)
    if parsed.path or parsed.query:
        raise ValueError("federated HTTPS origin is invalid")


def _validate_relative_path(value: Any) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 512
        or value.startswith(("/", "\\"))
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("federated relative path is invalid")


def _validate_hash(value: Any, *, field_name: str) -> None:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")


def _format_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("catalog clock must return datetime")
    if value.tzinfo is None:
        raise ValueError("catalog clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("catalog timestamp must be text")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("catalog timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("catalog timestamp must include a timezone")
    return parsed


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "CatalogConflictError",
    "CatalogEntry",
    "CatalogEntryStatus",
    "FederatedCatalogMetadata",
    "CatalogSnapshot",
    "CatalogSourceError",
    "CatalogSourceState",
    "CatalogSourceType",
    "CatalogStateError",
    "CatalogSyncResult",
    "IntegrationCatalogStore",
    "MCPSubregistry",
    "OFFICIAL_MCP_REGISTRY_API_VERSION",
    "OFFICIAL_MCP_REGISTRY_BASE_URL",
    "OFFICIAL_MCP_REGISTRY_SOURCE_ID",
    "catalog_entry_to_dict",
    "fetch_official_mcp_registry_page",
    "sync_official_mcp_registry",
]
