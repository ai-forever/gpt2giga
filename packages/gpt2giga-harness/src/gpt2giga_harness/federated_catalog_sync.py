"""Offline-first synchronization for provider-neutral federated catalogs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from urllib.parse import urlsplit

from gpt2giga_harness.federated_catalog import (
    FederatedArtifactResolution,
    FederatedCatalogCandidate,
    FederatedCatalogComponent,
    FederatedCatalogSource,
)
from gpt2giga_harness.integration_catalog import (
    CatalogEntry,
    CatalogEntryStatus,
    CatalogSourceError,
    CatalogSourceType,
    FederatedCatalogMetadata,
    IntegrationCatalogStore,
)
from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationSourceType,
    IntegrationUpdatePolicy,
    integration_package_semantic_hash,
)


FEDERATED_FRESHNESS_SECONDS = 3_600
FEDERATED_INITIAL_RETRY_SECONDS = 30
FEDERATED_MAX_RETRY_SECONDS = 3_600


@dataclass(frozen=True)
class FederatedCatalogSyncResult:
    """One source synchronization outcome with bounded retry evidence."""

    source_id: str
    attempted: bool
    success: bool
    fetched_count: int
    stored_count: int
    resolved_count: int
    discovery_only_count: int
    next_retry_at: str | None
    errors: tuple[CatalogSourceError, ...]


async def sync_federated_catalog_source(
    store: IntegrationCatalogStore,
    source: FederatedCatalogSource,
    *,
    components: Sequence[FederatedCatalogComponent] | None = None,
    page_size: int = 100,
    force: bool = False,
) -> FederatedCatalogSyncResult:
    """Validate a complete source read before one atomic offline merge."""
    source_id = source.descriptor.source_id
    now = store._now().astimezone(timezone.utc)
    previous = next(
        (item for item in store.snapshot().sources if item.source_id == source_id),
        None,
    )
    if (
        not force
        and previous is not None
        and previous.next_retry_at is not None
        and _parse_timestamp(previous.next_retry_at) > now
    ):
        return FederatedCatalogSyncResult(
            source_id=source_id,
            attempted=False,
            success=False,
            fetched_count=0,
            stored_count=previous.entry_count,
            resolved_count=0,
            discovery_only_count=0,
            next_retry_at=previous.next_retry_at,
            errors=(),
        )

    refresh = await source.refresh(components=components, page_size=page_size)
    if not refresh.success:
        return _record_failure(
            store,
            source_id=source_id,
            observed_at=refresh.health.last_attempt_at,
            code=refresh.health.error_code or "source.fetch_failed",
            error_type=refresh.health.error_type or "FederatedSourceFailure",
            previous_retry_count=previous.retry_count if previous is not None else 0,
        )

    try:
        entries = []
        resolved_count = 0
        official_mcp_identities = _official_mcp_identity_index(store)
        for candidate in refresh.snapshot.items:
            if not candidate.source_present:
                continue
            resolution = await _resolve_candidate(source, candidate)
            entry = _catalog_entry(
                candidate,
                resolution,
                _canonical_mcp_package_id(candidate, official_mcp_identities),
            )
            entries.append(entry)
            resolved_count += entry.package is not None
        _reject_stale_conflicts(store, source_id, entries)
    except Exception as exc:
        return _record_failure(
            store,
            source_id=source_id,
            observed_at=refresh.health.last_attempt_at,
            code="source.normalization_failed",
            error_type=type(exc).__name__,
            previous_retry_count=previous.retry_count if previous is not None else 0,
        )

    freshness_expires_at = _format_timestamp(
        _parse_timestamp(refresh.health.last_attempt_at)
        + timedelta(seconds=FEDERATED_FRESHNESS_SECONDS)
    )
    merged = store.merge_federated_source(
        source_id=source_id,
        incoming=tuple(entries),
        observed_at=refresh.health.last_attempt_at,
        freshness_expires_at=freshness_expires_at,
    )
    if not merged.success:
        return _record_failure(
            store,
            source_id=source_id,
            observed_at=refresh.health.last_attempt_at,
            code="source.immutable_conflict",
            error_type="CatalogConflictError",
            previous_retry_count=previous.retry_count if previous is not None else 0,
        )
    return FederatedCatalogSyncResult(
        source_id=source_id,
        attempted=True,
        success=True,
        fetched_count=len(refresh.snapshot.items),
        stored_count=merged.stored_count,
        resolved_count=resolved_count,
        discovery_only_count=len(entries) - resolved_count,
        next_retry_at=None,
        errors=(),
    )


async def sync_federated_catalog_sources(
    store: IntegrationCatalogStore,
    sources: Sequence[FederatedCatalogSource],
    *,
    page_size: int = 100,
) -> tuple[FederatedCatalogSyncResult, ...]:
    """Synchronize independent sources without sharing failure state."""
    results = []
    for source in sources:
        results.append(
            await sync_federated_catalog_source(
                store,
                source,
                page_size=page_size,
            )
        )
    return tuple(results)


async def _resolve_candidate(
    source: FederatedCatalogSource,
    candidate: FederatedCatalogCandidate,
) -> FederatedArtifactResolution | None:
    if (
        candidate.source_present
        and candidate.component is FederatedCatalogComponent.SKILL
        and candidate.provenance.artifact_url is not None
        and _is_github_repository(candidate.provenance.artifact_url)
    ):
        resolution = await source.resolve_artifact(candidate.upstream_id)
        if resolution.available:
            return resolution
    return None


def _catalog_entry(
    candidate: FederatedCatalogCandidate,
    resolution: FederatedArtifactResolution | None,
    canonical_package_id: str | None,
) -> CatalogEntry:
    metadata = FederatedCatalogMetadata(
        upstream_id=candidate.upstream_id,
        canonical_package_id=canonical_package_id,
        name=candidate.name,
        component=candidate.component.value,
        canonical_origin=candidate.provenance.canonical_origin,
        detail_url=candidate.provenance.detail_url,
        artifact_url=candidate.provenance.artifact_url,
        curated=candidate.trust.curated,
        popularity=candidate.trust.popularity,
        upstream_audit=candidate.trust.upstream_audit,
        artifact_resolved=resolution is not None,
        source_present=candidate.source_present,
    )
    package_id = canonical_package_id or (
        f"federated:{candidate.source_id}:{candidate.upstream_id}"
    )
    package = (
        _git_skill_package(candidate, resolution, package_id)
        if resolution is not None
        else None
    )
    version = package.version if package is not None else "discovery"
    immutable_ref = package.immutable_ref if package is not None else None
    content_hash = (
        integration_package_semantic_hash(package)
        if package is not None
        else _discovery_identity_hash(candidate)
    )
    return CatalogEntry(
        catalog_id=_catalog_id(candidate.source_id, package_id, version),
        source_id=candidate.source_id,
        source_type=CatalogSourceType.FEDERATED_CATALOG,
        package_id=package_id,
        version=version,
        immutable_ref=immutable_ref,
        content_hash=content_hash,
        status=CatalogEntryStatus.ACTIVE,
        pinned=package is not None,
        source_present=candidate.source_present,
        install_authorized=False,
        first_seen_at=candidate.provenance.observed_at,
        last_seen_at=candidate.provenance.observed_at,
        package=package,
        federated=metadata,
    )


def _git_skill_package(
    candidate: FederatedCatalogCandidate,
    resolution: FederatedArtifactResolution,
    package_id: str,
) -> IntegrationPackage:
    if resolution.immutable_ref is None or resolution.artifact_url is None:
        raise ValueError("resolved federated artifact is incomplete")
    digest = resolution.immutable_ref.removeprefix("sha256:")
    owner = urlsplit(resolution.artifact_url).path.strip("/").split("/", 1)[0]
    return IntegrationPackage(
        id=package_id,
        version=f"sha256-{digest[:16]}",
        publisher=owner,
        license="unknown",
        source_type=IntegrationSourceType.GIT,
        source=resolution.artifact_url,
        immutable_ref=resolution.immutable_ref,
        checksum=resolution.immutable_ref,
        components=(
            IntegrationComponent(
                id=f"skill:{candidate.upstream_id}",
                type=IntegrationComponentType.SKILL,
                portable=True,
            ),
        ),
        requirements=(),
        overlays=(),
        compatibility=(),
        scopes=(InstallationScope.MANAGED_HOME, InstallationScope.PROJECT),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("external-skill-review",),
        rollback_steps=("transactional-owner-restore",),
    )


def _reject_stale_conflicts(
    store: IntegrationCatalogStore,
    source_id: str,
    incoming: Sequence[CatalogEntry],
) -> None:
    current = {
        item.catalog_id: item
        for item in store.snapshot().entries
        if item.source_id == source_id
    }
    for candidate in incoming:
        existing = current.get(candidate.catalog_id)
        if existing is not None and (
            existing.content_hash != candidate.content_hash
            or existing.immutable_ref != candidate.immutable_ref
        ):
            raise ValueError("federated source attempted same-version drift")


def _record_failure(
    store: IntegrationCatalogStore,
    *,
    source_id: str,
    observed_at: str,
    code: str,
    error_type: str,
    previous_retry_count: int,
) -> FederatedCatalogSyncResult:
    retry_count = min(previous_retry_count + 1, 100)
    delay = min(
        FEDERATED_INITIAL_RETRY_SECONDS * (2 ** min(retry_count - 1, 16)),
        FEDERATED_MAX_RETRY_SECONDS,
    )
    next_retry_at = _format_timestamp(
        _parse_timestamp(observed_at) + timedelta(seconds=delay)
    )
    recorded = store.record_federated_failure(
        source_id=source_id,
        code=code,
        error_type=error_type,
        observed_at=observed_at,
        retry_count=retry_count,
        next_retry_at=next_retry_at,
    )
    return FederatedCatalogSyncResult(
        source_id=source_id,
        attempted=True,
        success=False,
        fetched_count=0,
        stored_count=recorded.stored_count,
        resolved_count=0,
        discovery_only_count=0,
        next_retry_at=next_retry_at,
        errors=recorded.errors,
    )


def _is_github_repository(url: str) -> bool:
    return _canonical_github_repository(url) is not None


def _canonical_github_repository(url: str) -> str | None:
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    if not (
        parsed.scheme == "https"
        and parsed.netloc == "github.com"
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and len(parts) == 2
        and all(parts)
    ):
        return None
    return f"https://github.com/{parts[0]}/{parts[1]}"


def _official_mcp_identity_index(
    store: IntegrationCatalogStore,
) -> dict[str, str]:
    identities: dict[str, str] = {}
    for entry in store.snapshot().entries:
        if entry.mcp_response is None:
            continue
        _add_identity(identities, f"name:{entry.package_id}", entry.package_id)
        repository = entry.mcp_response["server"].get("repository")
        if not isinstance(repository, dict):
            continue
        url = repository.get("url")
        canonical_url = (
            _canonical_github_repository(url) if isinstance(url, str) else None
        )
        if canonical_url is not None:
            _add_identity(
                identities,
                f"repository:{canonical_url}",
                entry.package_id,
            )
    return identities


def _add_identity(
    identities: dict[str, str],
    key: str,
    package_id: str,
) -> None:
    current = identities.get(key)
    if current is not None and current != package_id:
        raise ValueError("official MCP identity is ambiguous")
    identities[key] = package_id


def _canonical_mcp_package_id(
    candidate: FederatedCatalogCandidate,
    identities: dict[str, str],
) -> str | None:
    if candidate.component is not FederatedCatalogComponent.MCP:
        return None
    direct = identities.get(f"name:{candidate.upstream_id}")
    if direct is not None:
        return direct
    artifact_url = candidate.provenance.artifact_url
    canonical_url = (
        _canonical_github_repository(artifact_url) if artifact_url is not None else None
    )
    if canonical_url is None:
        return None
    return identities.get(f"repository:{canonical_url}")


def _discovery_identity_hash(candidate: FederatedCatalogCandidate) -> str:
    payload = {
        "source_id": candidate.source_id,
        "upstream_id": candidate.upstream_id,
        "component": candidate.component.value,
        "canonical_origin": candidate.provenance.canonical_origin,
        "detail_url": candidate.provenance.detail_url,
        "artifact_url": candidate.provenance.artifact_url,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _catalog_id(source_id: str, package_id: str, version: str) -> str:
    digest = hashlib.sha256(
        json.dumps(
            [source_id, package_id, version],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"catalog_{digest[:32]}"


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("federated timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


__all__ = [
    "FEDERATED_FRESHNESS_SECONDS",
    "FEDERATED_INITIAL_RETRY_SECONDS",
    "FEDERATED_MAX_RETRY_SECONDS",
    "FederatedCatalogSyncResult",
    "sync_federated_catalog_source",
    "sync_federated_catalog_sources",
]
