"""Read-only federated Skills and MCP catalog source contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import json
import re
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import anyio


FEDERATED_CATALOG_CONTRACT_VERSION = 1
SKILLS_SH_SOURCE_ID = "skills-sh"
SKILLS_SH_ORIGIN = "https://skills.sh"
NEURALDEEP_SOURCE_ID = "neuraldeep"
NEURALDEEP_ORIGIN = "https://neuraldeep.ru"
MAX_FEDERATED_ENTRIES = 10_000
MAX_FEDERATED_PAGE_SIZE = 500
MAX_FEDERATED_PAGES = 100
MAX_FEDERATED_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_FEDERATED_QUERY_LENGTH = 200
MAX_FEDERATED_TEXT_LENGTH = 512
FEDERATED_TIMEOUT_SECONDS = 20.0

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,255}\Z")
_HEX_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_SKILLS_SH_ITEM_FIELDS = {
    "id",
    "slug",
    "name",
    "source",
    "installs",
    "sourceType",
    "installUrl",
    "url",
    "isDuplicate",
    "installsYesterday",
    "change",
}
_NEURALDEEP_ITEM_FIELDS = {
    "id",
    "name",
    "owner",
    "repo",
    "description",
    "installs",
    "trending24h",
    "category",
    "tags",
    "contentPath",
    "authorName",
    "telegramLink",
    "featured",
    "type",
    "status",
    "githubStars",
    "createdAt",
    "updatedAt",
    "authorId",
    "license",
    "url",
    "install",
    "source",
    "score",
    "_count",
}


class FederatedCatalogComponent(str, Enum):
    """Portable component families admitted by federation."""

    SKILL = "skill"
    MCP = "mcp"


class FederatedSourceKind(str, Enum):
    """Provider-neutral discovery source families, not marketplaces."""

    HOSTED_METADATA = "hosted_metadata"
    PUBLIC_GET = "public_get"


@dataclass(frozen=True)
class FederatedSourceDescriptor:
    """Static capabilities and ownership for one source boundary."""

    source_id: str
    kind: FederatedSourceKind
    canonical_origin: str
    components: tuple[FederatedCatalogComponent, ...]
    hosted_auth_required: bool
    immutable_reference_capable: bool
    install_authorized: bool = False

    def __post_init__(self) -> None:
        _validate_id(self.source_id, "federated source id")
        if not isinstance(self.kind, FederatedSourceKind):
            raise ValueError("federated source kind is invalid")
        _canonical_https_origin(self.canonical_origin)
        if not self.components or any(
            not isinstance(item, FederatedCatalogComponent) for item in self.components
        ):
            raise ValueError("federated source components are invalid")
        if not isinstance(self.hosted_auth_required, bool):
            raise ValueError("hosted auth requirement must be boolean")
        if not isinstance(self.immutable_reference_capable, bool):
            raise ValueError("immutable reference capability must be boolean")
        if self.install_authorized is not False:
            raise ValueError("federated sources cannot authorize installation")


@dataclass(frozen=True)
class FederatedProvenance:
    """Content-free upstream identity retained for one candidate."""

    source_id: str
    upstream_id: str
    canonical_origin: str
    observed_at: str
    detail_url: str
    artifact_url: str | None
    artifact_origin: str | None
    relative_path: str | None = None
    file_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_id(self.source_id, "federated source id")
        _validate_id(self.upstream_id, "federated upstream id")
        _canonical_https_origin(self.canonical_origin)
        _parse_timestamp(self.observed_at)
        _validate_https_url(self.detail_url)
        if self.artifact_url is None:
            if self.artifact_origin is not None:
                raise ValueError("artifact origin requires an artifact URL")
        else:
            origin = _origin_for_url(self.artifact_url)
            if self.artifact_origin != origin:
                raise ValueError("artifact origin does not match artifact URL")
        if self.relative_path is not None:
            _validate_relative_path(self.relative_path)
        file_paths = tuple(self.file_paths)
        if len(file_paths) > 512:
            raise ValueError("federated file tree is too large")
        for path in file_paths:
            _validate_relative_path(path)
        if len(set(file_paths)) != len(file_paths):
            raise ValueError("federated file tree contains duplicate paths")
        if self.relative_path is not None and self.relative_path not in file_paths:
            raise ValueError("federated relative path is absent from the file tree")
        object.__setattr__(self, "file_paths", file_paths)


@dataclass(frozen=True)
class FederatedTrustProjection:
    """Bounded upstream claims that never imply installation authority."""

    source_present: bool
    curated: bool
    popularity: int | None
    upstream_audit: str | None
    install_authorized: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.source_present, bool) or not isinstance(
            self.curated, bool
        ):
            raise ValueError("federated trust flags must be boolean")
        if self.popularity is not None and (
            isinstance(self.popularity, bool)
            or not isinstance(self.popularity, int)
            or self.popularity < 0
        ):
            raise ValueError("federated popularity is invalid")
        if self.upstream_audit not in {None, "reported_approved", "reported_reviewed"}:
            raise ValueError("federated audit projection is invalid")
        if self.install_authorized is not False:
            raise ValueError("federated trust cannot authorize installation")


@dataclass(frozen=True)
class FederatedCatalogCandidate:
    """One bounded Skills or MCP discovery candidate."""

    source_id: str
    upstream_id: str
    name: str
    component: FederatedCatalogComponent
    source_present: bool
    immutable_ref: str | None
    provenance: FederatedProvenance
    trust: FederatedTrustProjection

    def __post_init__(self) -> None:
        _validate_id(self.source_id, "federated source id")
        _validate_id(self.upstream_id, "federated upstream id")
        _validate_text(self.name, "federated candidate name")
        if not isinstance(self.component, FederatedCatalogComponent):
            raise ValueError("federated candidate component is invalid")
        if not isinstance(self.source_present, bool):
            raise ValueError("federated source presence must be boolean")
        if self.immutable_ref is not None and not self.immutable_ref.startswith(
            "sha256:"
        ):
            raise ValueError("federated immutable ref is invalid")
        if self.provenance.source_id != self.source_id:
            raise ValueError("federated provenance source does not match")
        if self.provenance.upstream_id != self.upstream_id:
            raise ValueError("federated provenance identity does not match")
        if self.trust.source_present != self.source_present:
            raise ValueError("federated trust presence does not match")
        if self.trust.install_authorized is not False:
            raise ValueError("federated candidate cannot authorize installation")


@dataclass(frozen=True)
class FederatedArtifactResolution:
    """Immutable artifact-reference resolution without downloading content."""

    source_id: str
    upstream_id: str
    available: bool
    immutable_ref: str | None
    artifact_url: str | None
    reason_code: str | None
    relative_path: str | None = None
    install_authorized: bool = False

    def __post_init__(self) -> None:
        _validate_id(self.source_id, "federated source id")
        _validate_id(self.upstream_id, "federated upstream id")
        if not isinstance(self.available, bool):
            raise ValueError("artifact availability must be boolean")
        if self.available:
            if self.immutable_ref is None or self.artifact_url is None:
                raise ValueError(
                    "available artifact resolution requires an immutable ref"
                )
            if self.reason_code is not None:
                raise ValueError(
                    "available artifact resolution cannot include a reason"
                )
            _validate_sha256_ref(self.immutable_ref)
            _validate_https_url(self.artifact_url)
            if self.relative_path is not None:
                _validate_relative_path(self.relative_path)
        elif (
            self.immutable_ref is not None
            or self.artifact_url is not None
            or self.reason_code != "immutable_reference_unavailable"
            or self.relative_path is not None
        ):
            raise ValueError("unavailable artifact resolution is invalid")
        if self.install_authorized is not False:
            raise ValueError("artifact resolution cannot authorize installation")


@dataclass(frozen=True)
class FederatedCatalogSnapshot:
    """Last complete in-process source read."""

    revision: int
    observed_at: str | None
    items: tuple[FederatedCatalogCandidate, ...]


@dataclass(frozen=True)
class FederatedSourceHealth:
    """Bounded content-free source status."""

    source_id: str
    last_attempt_at: str
    last_success_at: str | None
    last_attempt_succeeded: bool
    complete: bool
    cached_count: int
    error_code: str | None = None
    error_type: str | None = None
    install_authorized: bool = False

    def __post_init__(self) -> None:
        _validate_id(self.source_id, "federated source id")
        _parse_timestamp(self.last_attempt_at)
        if self.last_success_at is not None:
            _parse_timestamp(self.last_success_at)
        if not isinstance(self.last_attempt_succeeded, bool) or not isinstance(
            self.complete, bool
        ):
            raise ValueError("federated source health flags must be boolean")
        if (
            isinstance(self.cached_count, bool)
            or not isinstance(self.cached_count, int)
            or self.cached_count < 0
            or self.cached_count > MAX_FEDERATED_ENTRIES
        ):
            raise ValueError("federated cached count is invalid")
        if (self.error_code is None) != (self.error_type is None):
            raise ValueError("federated source error fields must be paired")
        if self.error_code is not None:
            _validate_id(self.error_code, "federated error code")
            _validate_id(self.error_type, "federated error type")
        if self.install_authorized is not False:
            raise ValueError("source health cannot authorize installation")


@dataclass(frozen=True)
class FederatedRefreshResult:
    """Result of an all-pages-before-publish source refresh."""

    success: bool
    snapshot: FederatedCatalogSnapshot
    health: FederatedSourceHealth


@dataclass(frozen=True)
class FederatedRequest:
    """Fixed-origin bounded metadata request passed to an injected fetcher."""

    method: str
    url: str
    headers: Mapping[str, str]
    timeout_seconds: float
    max_response_bytes: int
    allow_loopback_http: bool = False

    def __post_init__(self) -> None:
        if self.method != "GET":
            raise ValueError("federated sources are read-only")
        if self.allow_loopback_http:
            _validate_loopback_http_url(self.url)
        else:
            _validate_https_url(self.url)
        if dict(self.headers) != {"Accept": "application/json"}:
            raise ValueError("federated request headers are invalid")
        if self.timeout_seconds != FEDERATED_TIMEOUT_SECONDS:
            raise ValueError("federated request timeout is invalid")
        if self.max_response_bytes != MAX_FEDERATED_RESPONSE_BYTES:
            raise ValueError("federated response bound is invalid")


@dataclass(frozen=True)
class FederatedHTTPResponse:
    """Transport-neutral JSON response metadata."""

    status_code: int
    final_url: str
    headers: Mapping[str, str]
    body: bytes
    redirected: bool = False


FederatedFetcher = Callable[[FederatedRequest], Awaitable[FederatedHTTPResponse]]


@dataclass(frozen=True)
class FederatedAuditProjection:
    """Bounded content-free security-audit metadata for one candidate."""

    provider: str
    status: str
    audited_at: str
    risk_level: str | None = None

    def __post_init__(self) -> None:
        _validate_text(self.provider, "federated audit provider", maximum=128)
        if self.status not in {"pass", "warn", "fail"}:
            raise ValueError("federated audit status is invalid")
        _parse_timestamp(self.audited_at)
        if self.risk_level not in {
            None,
            "NONE",
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }:
            raise ValueError("federated audit risk level is invalid")


class FederatedCatalogSource(Protocol):
    """Versioned bounded source contract shared by all federation adapters."""

    descriptor: FederatedSourceDescriptor
    last_good: FederatedCatalogSnapshot
    health: FederatedSourceHealth | None

    async def refresh(
        self,
        *,
        components: Sequence[FederatedCatalogComponent] | None = None,
        page_size: int = 100,
    ) -> FederatedRefreshResult: ...

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> tuple[FederatedCatalogCandidate, ...]: ...

    async def detail(self, upstream_id: str) -> FederatedCatalogCandidate: ...

    async def audits(
        self, upstream_id: str
    ) -> tuple[FederatedAuditProjection, ...]: ...

    async def resolve_artifact(
        self, upstream_id: str
    ) -> FederatedArtifactResolution: ...


class _FederatedFailure(RuntimeError):
    def __init__(self, code: str, error_type: str) -> None:
        super().__init__(code)
        self.code = code
        self.error_type = error_type


class _SchemaDrift(_FederatedFailure):
    def __init__(self) -> None:
        super().__init__("source.schema_drift", "SchemaDrift")


class _BaseFederatedSource:
    descriptor: FederatedSourceDescriptor

    def __init__(
        self, *, fetch: FederatedFetcher, now: Callable[[], datetime] | None
    ) -> None:
        self._fetch = fetch
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.last_good = FederatedCatalogSnapshot(
            revision=0, observed_at=None, items=()
        )
        self.health: FederatedSourceHealth | None = None
        self.last_cache_status = "live"
        self.last_cache_age_seconds: int | None = None
        self.last_source_error: str | None = None
        self._ephemeral_candidates: dict[str, FederatedCatalogCandidate] = {}

    async def refresh(
        self,
        *,
        components: Sequence[FederatedCatalogComponent] | None = None,
        page_size: int = 100,
    ) -> FederatedRefreshResult:
        selected = _validate_components(components, self.descriptor.components)
        _validate_limit(page_size, field="federated page_size")
        observed_at = _format_timestamp(self._now())
        try:
            incoming = await self._fetch_inventory(
                components=selected,
                page_size=page_size,
                observed_at=observed_at,
            )
            _reject_duplicate_candidates(incoming)
            if len(incoming) > MAX_FEDERATED_ENTRIES:
                raise _FederatedFailure("source.too_many_entries", "EntryLimit")
        except _FederatedFailure as exc:
            return self._failed_refresh(observed_at, exc)
        except Exception as exc:
            return self._failed_refresh(
                observed_at,
                _FederatedFailure("source.fetch_failed", type(exc).__name__),
            )

        incoming_by_id = {item.upstream_id: item for item in incoming}
        retained: list[FederatedCatalogCandidate] = []
        for item in self.last_good.items:
            if item.component not in selected:
                retained.append(item)
                continue
            if item.upstream_id not in incoming_by_id:
                retained.append(_with_source_presence(item, False))
        retained.extend(
            item
            for item in incoming
            if all(existing.upstream_id != item.upstream_id for existing in retained)
        )
        snapshot = FederatedCatalogSnapshot(
            revision=self.last_good.revision + 1,
            observed_at=observed_at,
            items=tuple(sorted(retained, key=_candidate_sort_key)),
        )
        self.last_good = snapshot
        self.health = FederatedSourceHealth(
            source_id=self.descriptor.source_id,
            last_attempt_at=observed_at,
            last_success_at=observed_at,
            last_attempt_succeeded=True,
            complete=True,
            cached_count=len(snapshot.items),
        )
        return FederatedRefreshResult(
            success=True, snapshot=snapshot, health=self.health
        )

    def _failed_refresh(
        self,
        observed_at: str,
        failure: _FederatedFailure,
    ) -> FederatedRefreshResult:
        self.health = FederatedSourceHealth(
            source_id=self.descriptor.source_id,
            last_attempt_at=observed_at,
            last_success_at=self.last_good.observed_at,
            last_attempt_succeeded=False,
            complete=False,
            cached_count=len(self.last_good.items),
            error_code=failure.code,
            error_type=_safe_error_type(failure.error_type),
        )
        return FederatedRefreshResult(
            success=False,
            snapshot=self.last_good,
            health=self.health,
        )

    async def _request_json(self, url: str, *, allow_not_found: bool = False) -> Any:
        expected_origin = self.descriptor.canonical_origin
        if _origin_for_url(url) != expected_origin:
            raise _FederatedFailure("source.origin_rejected", "OriginRejected")
        request = FederatedRequest(
            method="GET",
            url=url,
            headers={"Accept": "application/json"},
            timeout_seconds=FEDERATED_TIMEOUT_SECONDS,
            max_response_bytes=MAX_FEDERATED_RESPONSE_BYTES,
        )
        try:
            response = await self._fetch(request)
        except _FederatedFailure:
            raise
        except Exception as exc:
            raise _FederatedFailure("source.fetch_failed", type(exc).__name__) from exc
        if response.redirected or response.final_url != url:
            raise _FederatedFailure("source.redirect_rejected", "RedirectRejected")
        if response.status_code in {401, 403}:
            raise _FederatedFailure("source.auth_failed", "AuthenticationFailure")
        if response.status_code == 429:
            raise _FederatedFailure("source.rate_limited", "RateLimitFailure")
        if response.status_code == 404 and allow_not_found:
            return None
        if response.status_code < 200 or response.status_code >= 300:
            raise _FederatedFailure("source.http_failed", "HTTPFailure")
        cache_status = _header(response.headers, "x-giga-cache-status")
        age = _header(response.headers, "age")
        self.last_cache_status = (
            cache_status if cache_status in {"fresh", "stale"} else "live"
        )
        self.last_cache_age_seconds = (
            int(age) if age is not None and age.isdigit() else None
        )
        self.last_source_error = _header(response.headers, "x-giga-source-error")
        if not isinstance(response.body, bytes):
            raise _FederatedFailure("source.invalid_payload", "ResponseBodyType")
        if len(response.body) > MAX_FEDERATED_RESPONSE_BYTES:
            raise _FederatedFailure("source.response_too_large", "ResponseLimit")
        content_type = next(
            (
                value
                for key, value in response.headers.items()
                if key.casefold() == "content-type"
            ),
            "application/json",
        )
        if not content_type.casefold().startswith("application/json"):
            raise _FederatedFailure("source.non_json_response", "ContentType")
        try:
            return json.loads(
                response.body.decode("utf-8"),
                object_pairs_hook=_unique_object,
            )
        except _FederatedFailure:
            raise
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise _FederatedFailure(
                "source.invalid_payload", type(exc).__name__
            ) from exc

    def _cached_detail(self, upstream_id: str) -> FederatedCatalogCandidate:
        _validate_id(upstream_id, "federated upstream id")
        candidate = next(
            (item for item in self.last_good.items if item.upstream_id == upstream_id),
            self._ephemeral_candidates.get(upstream_id),
        )
        if candidate is None or not candidate.source_present:
            raise KeyError(upstream_id)
        return candidate

    def _remember_candidates(
        self, items: Sequence[FederatedCatalogCandidate]
    ) -> tuple[FederatedCatalogCandidate, ...]:
        remembered = tuple(items)
        self._ephemeral_candidates = {
            item.upstream_id: item for item in remembered[:200]
        }
        return remembered

    async def _fetch_inventory(
        self,
        *,
        components: tuple[FederatedCatalogComponent, ...],
        page_size: int,
        observed_at: str,
    ) -> tuple[FederatedCatalogCandidate, ...]:
        raise NotImplementedError


class SkillsShFederatedCatalogSource(_BaseFederatedSource):
    """Metadata-only skills.sh boundary supplied by a Vercel-hosted fetcher."""

    descriptor: FederatedSourceDescriptor

    def __init__(
        self,
        *,
        hosted_fetch: FederatedFetcher | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if hosted_fetch is None:
            raise ValueError("skills.sh requires an explicit hosted metadata fetcher")
        super().__init__(fetch=hosted_fetch, now=now)
        self._curated_ids: frozenset[str] | None = None

    async def _fetch_inventory(
        self,
        *,
        components: tuple[FederatedCatalogComponent, ...],
        page_size: int,
        observed_at: str,
    ) -> tuple[FederatedCatalogCandidate, ...]:
        if components != (FederatedCatalogComponent.SKILL,):
            raise _FederatedFailure(
                "source.unsupported_component", "UnsupportedComponent"
            )
        curated_ids = await self._fetch_curated_ids()
        candidates: list[FederatedCatalogCandidate] = []
        for page in range(MAX_FEDERATED_PAGES):
            url = f"{SKILLS_SH_ORIGIN}/api/v1/skills?page={page}&per_page={page_size}"
            payload = await self._request_json(url)
            items, has_more = _parse_skills_sh_page(
                payload,
                expected_page=page,
                page_size=page_size,
                observed_at=observed_at,
                curated_ids=curated_ids,
            )
            candidates.extend(items)
            if len(candidates) > MAX_FEDERATED_ENTRIES:
                raise _FederatedFailure("source.too_many_entries", "EntryLimit")
            if not has_more:
                return tuple(candidates)
        raise _FederatedFailure("source.pagination_incomplete", "PaginationLimit")

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> tuple[FederatedCatalogCandidate, ...]:
        query = _validate_query(query)
        _validate_limit(limit, field="federated search limit", maximum=200)
        curated_ids = (
            self._curated_ids
            if self._curated_ids is not None
            else await self._fetch_curated_ids()
        )
        url = (
            f"{SKILLS_SH_ORIGIN}/api/v1/skills/search?"
            f"q={urllib_parse.quote(query, safe='')}&limit={limit}"
        )
        payload = await self._request_json(url)
        items = _parse_skills_sh_search(
            payload,
            observed_at=_format_timestamp(self._now()),
            limit=limit,
            curated_ids=curated_ids,
        )
        _reject_duplicate_candidates(items)
        return self._remember_candidates(items)

    async def detail(self, upstream_id: str) -> FederatedCatalogCandidate:
        cached = self._cached_detail(upstream_id)
        url = f"{SKILLS_SH_ORIGIN}/api/v1/skills/{urllib_parse.quote(upstream_id, safe='/')}"
        payload = await self._request_json(url)
        digest, file_paths = _parse_skills_sh_detail(payload, expected_id=upstream_id)
        relative_path = next(
            (
                path
                for path in file_paths
                if path == "SKILL.md" or path.endswith("/SKILL.md")
            ),
            None,
        )
        return replace(
            cached,
            immutable_ref=f"sha256:{digest}",
            provenance=replace(
                cached.provenance,
                relative_path=relative_path,
                file_paths=file_paths,
            ),
        )

    async def audits(self, upstream_id: str) -> tuple[FederatedAuditProjection, ...]:
        self._cached_detail(upstream_id)
        url = (
            f"{SKILLS_SH_ORIGIN}/api/v1/skills/audit/"
            f"{urllib_parse.quote(upstream_id, safe='/')}"
        )
        payload = await self._request_json(url, allow_not_found=True)
        if payload is None:
            return ()
        return _parse_skills_sh_audits(payload, expected_id=upstream_id)

    async def resolve_artifact(self, upstream_id: str) -> FederatedArtifactResolution:
        detailed = await self.detail(upstream_id)
        if detailed.immutable_ref is None or detailed.provenance.artifact_url is None:
            return _unavailable_artifact(self.descriptor.source_id, upstream_id)
        return FederatedArtifactResolution(
            source_id=self.descriptor.source_id,
            upstream_id=upstream_id,
            available=True,
            immutable_ref=detailed.immutable_ref,
            artifact_url=detailed.provenance.artifact_url,
            reason_code=None,
            relative_path=detailed.provenance.relative_path,
        )

    async def _fetch_curated_ids(self) -> frozenset[str]:
        try:
            payload = await self._request_json(
                f"{SKILLS_SH_ORIGIN}/api/v1/skills/curated"
            )
            curated_ids = _parse_skills_sh_curated(payload)
        except _FederatedFailure as exc:
            self.last_source_error = exc.code
            curated_ids = frozenset()
        self._curated_ids = curated_ids
        return curated_ids


class NeuralDeepFederatedCatalogSource(_BaseFederatedSource):
    """Direct fixed-origin public-GET NeuralDeep discovery boundary."""

    descriptor: FederatedSourceDescriptor

    def __init__(
        self,
        *,
        fetch: FederatedFetcher | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(fetch=fetch or fetch_federated_json, now=now)

    async def _fetch_inventory(
        self,
        *,
        components: tuple[FederatedCatalogComponent, ...],
        page_size: int,
        observed_at: str,
    ) -> tuple[FederatedCatalogCandidate, ...]:
        del page_size
        candidates: list[FederatedCatalogCandidate] = []
        for component in components:
            url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type={component.value}"
            payload = await self._request_json(url)
            candidates.extend(
                _parse_neuraldeep_items(
                    payload,
                    expected_component=component,
                    observed_at=observed_at,
                )
            )
        return tuple(candidates)

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> tuple[FederatedCatalogCandidate, ...]:
        query = _validate_query(query)
        _validate_limit(limit, field="federated search limit", maximum=200)
        observed_at = _format_timestamp(self._now())
        candidates: list[FederatedCatalogCandidate] = []
        for component in self.descriptor.components:
            url = (
                f"{NEURALDEEP_ORIGIN}/skapi/skills?"
                f"q={urllib_parse.quote(query, safe='')}&type={component.value}"
            )
            payload = await self._request_json(url)
            candidates.extend(
                _parse_neuraldeep_items(
                    payload,
                    expected_component=component,
                    observed_at=observed_at,
                )
            )
        _reject_duplicate_candidates(candidates)
        return self._remember_candidates(
            tuple(sorted(candidates, key=_candidate_sort_key)[:limit])
        )

    async def detail(self, upstream_id: str) -> FederatedCatalogCandidate:
        return self._cached_detail(upstream_id)

    async def audits(self, upstream_id: str) -> tuple[FederatedAuditProjection, ...]:
        self._cached_detail(upstream_id)
        return ()

    async def resolve_artifact(self, upstream_id: str) -> FederatedArtifactResolution:
        self._cached_detail(upstream_id)
        return _unavailable_artifact(self.descriptor.source_id, upstream_id)


async def fetch_federated_json(request: FederatedRequest) -> FederatedHTTPResponse:
    """Execute one bounded direct GET without following redirects."""
    return await anyio.to_thread.run_sync(lambda: _read_federated_url(request))


def _read_federated_url(request: FederatedRequest) -> FederatedHTTPResponse:
    wire_request = urllib_request.Request(
        request.url,
        headers=dict(request.headers),
        method="GET",
    )
    opener = urllib_request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(wire_request, timeout=request.timeout_seconds) as response:
            body = response.read(request.max_response_bytes + 1)
            return FederatedHTTPResponse(
                status_code=response.status,
                final_url=response.geturl(),
                headers=dict(response.headers.items()),
                body=body,
            )
    except urllib_error.HTTPError as exc:
        body = exc.read(request.max_response_bytes + 1)
        return FederatedHTTPResponse(
            status_code=exc.code,
            final_url=request.url,
            headers=dict(exc.headers.items()) if exc.headers is not None else {},
            body=body,
            redirected=300 <= exc.code < 400,
        )


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _parse_skills_sh_page(
    payload: Any,
    *,
    expected_page: int,
    page_size: int,
    observed_at: str,
    curated_ids: frozenset[str],
) -> tuple[tuple[FederatedCatalogCandidate, ...], bool]:
    mapping = _strict_mapping(payload, {"data", "pagination"})
    pagination = _strict_mapping(
        mapping.get("pagination"),
        {"page", "perPage", "total", "hasMore"},
    )
    page = _integer(pagination.get("page"), "skills.sh page")
    per_page = _integer(pagination.get("perPage"), "skills.sh perPage")
    total = _integer(pagination.get("total"), "skills.sh total")
    has_more = pagination.get("hasMore")
    if page != expected_page or per_page < 1 or per_page > page_size or total < 0:
        raise _FederatedFailure("source.pagination_incomplete", "PaginationState")
    if not isinstance(has_more, bool):
        raise _FederatedFailure("source.invalid_payload", "PaginationState")
    return (
        _parse_skills_sh_items(
            mapping.get("data"),
            observed_at=observed_at,
            curated_ids=curated_ids,
        ),
        has_more,
    )


def _parse_skills_sh_search(
    payload: Any,
    *,
    observed_at: str,
    limit: int,
    curated_ids: frozenset[str],
) -> tuple[FederatedCatalogCandidate, ...]:
    mapping = _strict_mapping(
        payload,
        {"data", "query", "searchType", "count", "durationMs"},
    )
    _validate_text(
        mapping.get("query"), "skills.sh query", maximum=MAX_FEDERATED_QUERY_LENGTH
    )
    _validate_text(mapping.get("searchType"), "skills.sh search type", maximum=32)
    count = _integer(mapping.get("count"), "skills.sh count")
    _integer(mapping.get("durationMs"), "skills.sh duration")
    items = _parse_skills_sh_items(
        mapping.get("data"),
        observed_at=observed_at,
        curated_ids=curated_ids,
    )
    if count != len(items) or len(items) > limit:
        raise _FederatedFailure("source.invalid_payload", "SearchCount")
    return items


def _parse_skills_sh_items(
    payload: Any,
    *,
    observed_at: str,
    curated_ids: frozenset[str],
) -> tuple[FederatedCatalogCandidate, ...]:
    if not isinstance(payload, list):
        raise _FederatedFailure("source.invalid_payload", "ItemList")
    if len(payload) > MAX_FEDERATED_ENTRIES:
        raise _FederatedFailure("source.too_many_entries", "EntryLimit")
    items = tuple(
        _parse_skills_sh_item(
            item,
            observed_at=observed_at,
            curated_ids=curated_ids,
        )
        for item in payload
    )
    _reject_duplicate_candidates(items)
    return items


def _parse_skills_sh_item(
    payload: Any, *, observed_at: str, curated_ids: frozenset[str]
) -> FederatedCatalogCandidate:
    mapping = _strict_mapping(payload, _SKILLS_SH_ITEM_FIELDS)
    upstream_id = _id(mapping.get("id"), "skills.sh id")
    slug = _id(mapping.get("slug"), "skills.sh slug")
    name = _text(mapping.get("name"), "skills.sh name")
    source = _id(mapping.get("source"), "skills.sh source")
    if upstream_id != f"{source}/{slug}":
        raise _FederatedFailure("source.invalid_payload", "IdentityMismatch")
    installs = _integer(mapping.get("installs"), "skills.sh installs")
    if installs < 0:
        raise _FederatedFailure("source.invalid_payload", "Popularity")
    source_type = mapping.get("sourceType")
    if source_type not in {"github", "well-known"}:
        raise _FederatedFailure("source.invalid_payload", "SourceType")
    install_url = mapping.get("installUrl")
    if install_url is not None:
        install_url = _https_url(install_url, "skills.sh install URL")
    detail_url = _https_url(mapping.get("url"), "skills.sh detail URL")
    if _origin_for_url(detail_url) != SKILLS_SH_ORIGIN:
        raise _FederatedFailure("source.origin_rejected", "DetailOrigin")
    duplicate = mapping.get("isDuplicate", False)
    if not isinstance(duplicate, bool):
        raise _FederatedFailure("source.invalid_payload", "DuplicateFlag")
    return _candidate(
        source_id=SKILLS_SH_SOURCE_ID,
        upstream_id=upstream_id,
        name=name,
        component=FederatedCatalogComponent.SKILL,
        source_present=True,
        observed_at=observed_at,
        detail_url=detail_url,
        artifact_url=install_url,
        curated=upstream_id in curated_ids,
        popularity=installs,
        upstream_audit="reported_reviewed" if not duplicate else None,
    )


def _parse_skills_sh_curated(payload: Any) -> frozenset[str]:
    mapping = _strict_mapping(
        payload,
        {"data", "totalOwners", "totalSkills", "generatedAt"},
    )
    owners = mapping.get("data")
    if not isinstance(owners, list) or len(owners) > 1_000:
        raise _FederatedFailure("source.invalid_payload", "CuratedOwners")
    curated_ids: set[str] = set()
    for owner in owners:
        owner_mapping = _strict_mapping(
            owner,
            {
                "owner",
                "totalInstalls",
                "featuredRepo",
                "featuredSkill",
                "skills",
            },
        )
        _text(owner_mapping.get("owner"), "skills.sh curated owner")
        _integer(owner_mapping.get("totalInstalls"), "skills.sh curated installs")
        _text(owner_mapping.get("featuredRepo"), "skills.sh featured repo")
        _text(owner_mapping.get("featuredSkill"), "skills.sh featured skill")
        skills = owner_mapping.get("skills")
        if not isinstance(skills, list):
            raise _FederatedFailure("source.invalid_payload", "CuratedSkills")
        for item in skills:
            item_mapping = _strict_mapping(item, _SKILLS_SH_ITEM_FIELDS)
            curated_ids.add(_id(item_mapping.get("id"), "skills.sh curated id"))
    _integer(mapping.get("totalOwners"), "skills.sh total owners")
    _integer(mapping.get("totalSkills"), "skills.sh total skills")
    _parse_timestamp(mapping.get("generatedAt"))
    return frozenset(curated_ids)


def _parse_skills_sh_detail(
    payload: Any, *, expected_id: str
) -> tuple[str, tuple[str, ...]]:
    mapping = _strict_mapping(
        payload,
        {"id", "source", "slug", "installs", "hash", "files"},
    )
    upstream_id = _id(mapping.get("id"), "skills.sh detail id")
    source = _id(mapping.get("source"), "skills.sh detail source")
    slug = _id(mapping.get("slug"), "skills.sh detail slug")
    _integer(mapping.get("installs"), "skills.sh detail installs")
    digest = mapping.get("hash")
    if upstream_id != expected_id or upstream_id != f"{source}/{slug}":
        raise _FederatedFailure("source.invalid_payload", "IdentityMismatch")
    if not isinstance(digest, str) or _HEX_HASH_RE.fullmatch(digest) is None:
        raise _FederatedFailure("source.invalid_payload", "ImmutableHash")
    raw_files = mapping.get("files")
    if raw_files is None:
        return digest, ()
    if not isinstance(raw_files, list) or len(raw_files) > 512:
        raise _FederatedFailure("source.invalid_payload", "FileTree")
    file_paths = []
    for item in raw_files:
        file_mapping = _strict_mapping(item, {"path"})
        path = file_mapping.get("path")
        try:
            _validate_relative_path(path)
        except ValueError as exc:
            raise _FederatedFailure("source.invalid_payload", "FilePath") from exc
        file_paths.append(path)
    if len(set(file_paths)) != len(file_paths):
        raise _FederatedFailure("source.invalid_payload", "DuplicateFilePath")
    return digest, tuple(file_paths)


def _parse_skills_sh_audits(
    payload: Any, *, expected_id: str
) -> tuple[FederatedAuditProjection, ...]:
    mapping = _strict_mapping(payload, {"id", "source", "slug", "audits"})
    upstream_id = _id(mapping.get("id"), "skills.sh audit id")
    source = _id(mapping.get("source"), "skills.sh audit source")
    slug = _id(mapping.get("slug"), "skills.sh audit slug")
    if upstream_id != expected_id or upstream_id != f"{source}/{slug}":
        raise _FederatedFailure("source.invalid_payload", "IdentityMismatch")
    audits = mapping.get("audits")
    if not isinstance(audits, list) or len(audits) > 32:
        raise _FederatedFailure("source.invalid_payload", "AuditList")
    result = []
    for item in audits:
        audit = _strict_mapping(
            item,
            {"provider", "slug", "status", "auditedAt", "riskLevel"},
        )
        result.append(
            FederatedAuditProjection(
                provider=_text(audit.get("provider"), "skills.sh audit provider"),
                status=_text(audit.get("status"), "skills.sh audit status"),
                audited_at=_text(audit.get("auditedAt"), "skills.sh audit timestamp"),
                risk_level=(
                    _text(audit.get("riskLevel"), "skills.sh audit risk")
                    if audit.get("riskLevel") is not None
                    else None
                ),
            )
        )
    return tuple(result)


def _parse_neuraldeep_items(
    payload: Any,
    *,
    expected_component: FederatedCatalogComponent,
    observed_at: str,
) -> tuple[FederatedCatalogCandidate, ...]:
    if not isinstance(payload, list):
        raise _FederatedFailure("source.invalid_payload", "ItemList")
    if len(payload) > MAX_FEDERATED_ENTRIES:
        raise _FederatedFailure("source.too_many_entries", "EntryLimit")
    items = tuple(
        _parse_neuraldeep_item(
            item,
            expected_component=expected_component,
            observed_at=observed_at,
        )
        for item in payload
    )
    _reject_duplicate_candidates(items)
    return items


def _parse_neuraldeep_item(
    payload: Any,
    *,
    expected_component: FederatedCatalogComponent,
    observed_at: str,
) -> FederatedCatalogCandidate:
    mapping = _strict_mapping(payload, _NEURALDEEP_ITEM_FIELDS)
    upstream_id = _id(mapping.get("id"), "NeuralDeep id")
    name = _text(mapping.get("name"), "NeuralDeep name")
    raw_component = mapping.get("type")
    try:
        component = FederatedCatalogComponent(raw_component)
    except (TypeError, ValueError) as exc:
        raise _FederatedFailure(
            "source.unsupported_component", "UnsupportedComponent"
        ) from exc
    if component is not expected_component:
        raise _FederatedFailure("source.unsupported_component", "ComponentMismatch")
    installs = _integer(mapping.get("installs"), "NeuralDeep installs")
    if installs < 0:
        raise _FederatedFailure("source.invalid_payload", "Popularity")
    status = mapping.get("status")
    if status not in {"approved", "deleted", "deprecated"}:
        raise _FederatedFailure("source.invalid_payload", "Status")
    source_present = status == "approved"
    featured = mapping.get("featured", False)
    if not isinstance(featured, bool):
        raise _FederatedFailure("source.invalid_payload", "FeaturedFlag")
    owner = mapping.get("owner")
    repo = mapping.get("repo")
    artifact_url: str | None = None
    if owner not in {None, ""} and repo not in {None, ""}:
        owner_id = _id(owner, "NeuralDeep owner")
        repo_id = _id(repo, "NeuralDeep repo")
        artifact_url = f"https://github.com/{owner_id}/{repo_id}"
    explicit_url = mapping.get("url")
    if artifact_url is None and explicit_url is not None:
        artifact_url = _https_url(explicit_url, "NeuralDeep artifact URL")
    relative_path = mapping.get("contentPath")
    if relative_path not in {None, ""}:
        try:
            _validate_relative_path(relative_path)
        except ValueError as exc:
            raise _FederatedFailure("source.invalid_payload", "ContentPath") from exc
    else:
        relative_path = None
    return _candidate(
        source_id=NEURALDEEP_SOURCE_ID,
        upstream_id=upstream_id,
        name=name,
        component=component,
        source_present=source_present,
        observed_at=observed_at,
        detail_url=f"{NEURALDEEP_ORIGIN}/{component.value}/{urllib_parse.quote(name, safe='')}",
        artifact_url=artifact_url,
        curated=featured or mapping.get("source") == "curated",
        popularity=installs,
        upstream_audit="reported_approved" if status == "approved" else None,
        relative_path=relative_path,
    )


def _candidate(
    *,
    source_id: str,
    upstream_id: str,
    name: str,
    component: FederatedCatalogComponent,
    source_present: bool,
    observed_at: str,
    detail_url: str,
    artifact_url: str | None,
    curated: bool,
    popularity: int,
    upstream_audit: str | None,
    relative_path: str | None = None,
) -> FederatedCatalogCandidate:
    return FederatedCatalogCandidate(
        source_id=source_id,
        upstream_id=upstream_id,
        name=name,
        component=component,
        source_present=source_present,
        immutable_ref=None,
        provenance=FederatedProvenance(
            source_id=source_id,
            upstream_id=upstream_id,
            canonical_origin=(
                SKILLS_SH_ORIGIN
                if source_id == SKILLS_SH_SOURCE_ID
                else NEURALDEEP_ORIGIN
            ),
            observed_at=observed_at,
            detail_url=detail_url,
            artifact_url=artifact_url,
            artifact_origin=_origin_for_url(artifact_url) if artifact_url else None,
            relative_path=relative_path,
            file_paths=(relative_path,) if relative_path is not None else (),
        ),
        trust=FederatedTrustProjection(
            source_present=source_present,
            curated=curated,
            popularity=popularity,
            upstream_audit=upstream_audit,
        ),
    )


def _with_source_presence(
    candidate: FederatedCatalogCandidate,
    source_present: bool,
) -> FederatedCatalogCandidate:
    return replace(
        candidate,
        source_present=source_present,
        trust=replace(candidate.trust, source_present=source_present),
    )


def _unavailable_artifact(
    source_id: str, upstream_id: str
) -> FederatedArtifactResolution:
    return FederatedArtifactResolution(
        source_id=source_id,
        upstream_id=upstream_id,
        available=False,
        immutable_ref=None,
        artifact_url=None,
        reason_code="immutable_reference_unavailable",
    )


def _strict_mapping(value: Any, allowed: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _FederatedFailure("source.invalid_payload", "ObjectType")
    if set(value) - allowed:
        raise _SchemaDrift()
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _FederatedFailure("source.duplicate_field", "DuplicateField")
        result[key] = value
    return result


def _reject_duplicate_candidates(items: Sequence[FederatedCatalogCandidate]) -> None:
    identities = [item.upstream_id for item in items]
    if len(set(identities)) != len(identities):
        raise _FederatedFailure("source.duplicate_entry", "DuplicateEntry")


def _validate_components(
    requested: Sequence[FederatedCatalogComponent] | None,
    supported: tuple[FederatedCatalogComponent, ...],
) -> tuple[FederatedCatalogComponent, ...]:
    if requested is None:
        return supported
    selected = tuple(requested)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("federated components are invalid")
    if any(not isinstance(item, FederatedCatalogComponent) for item in selected):
        raise _FederatedFailure("source.unsupported_component", "UnsupportedComponent")
    if any(item not in supported for item in selected):
        raise _FederatedFailure("source.unsupported_component", "UnsupportedComponent")
    return tuple(item for item in supported if item in selected)


def _validate_query(value: Any) -> str:
    _validate_text(value, "federated query", maximum=MAX_FEDERATED_QUERY_LENGTH)
    normalized = value.strip()
    if len(normalized) < 2:
        raise ValueError("federated query is too short")
    return normalized


def _validate_limit(
    value: Any, *, field: str, maximum: int = MAX_FEDERATED_PAGE_SIZE
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > maximum
    ):
        raise ValueError(f"{field} is invalid")


def _id(value: Any, field: str) -> str:
    _validate_id(value, field)
    return value


def _validate_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise _FederatedFailure(
            "source.invalid_payload", f"Invalid{_error_label(field)}"
        )


def _text(value: Any, field: str) -> str:
    _validate_text(value, field)
    return value


def _validate_text(
    value: Any, field: str, *, maximum: int = MAX_FEDERATED_TEXT_LENGTH
) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise _FederatedFailure(
            "source.invalid_payload", f"Invalid{_error_label(field)}"
        )


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _FederatedFailure(
            "source.invalid_payload", f"Invalid{_error_label(field)}"
        )
    return value


def _https_url(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise _FederatedFailure(
            "source.invalid_payload", f"Invalid{_error_label(field)}"
        )
    try:
        _validate_https_url(value)
    except ValueError as exc:
        raise _FederatedFailure(
            "source.invalid_payload", f"Invalid{_error_label(field)}"
        ) from exc
    return value


def _validate_https_url(value: str) -> None:
    parsed = urllib_parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.hostname != parsed.hostname.casefold()
        or parsed.port not in {None, 443}
    ):
        raise ValueError("URL must be canonical HTTPS")


def _validate_loopback_http_url(value: str) -> None:
    parsed = urllib_parse.urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("URL must be loopback HTTP")


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


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next(
        (value for key, value in headers.items() if key.casefold() == name.casefold()),
        None,
    )


def _origin_for_url(value: str) -> str:
    _validate_https_url(value)
    parsed = urllib_parse.urlsplit(value)
    return f"https://{parsed.hostname}"


def _canonical_https_origin(value: str) -> str:
    _validate_https_url(value)
    parsed = urllib_parse.urlsplit(value)
    if parsed.path or parsed.query:
        raise ValueError("origin cannot contain a path or query")
    return value


def _validate_sha256_ref(value: str) -> None:
    if not value.startswith("sha256:") or _HEX_HASH_RE.fullmatch(value[7:]) is None:
        raise ValueError("immutable ref must be a sha256 digest")


def _format_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("federated clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("federated timestamp must be text")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("federated timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("federated timestamp must include a timezone")
    return parsed


def _candidate_sort_key(
    candidate: FederatedCatalogCandidate,
) -> tuple[str, str, str]:
    return (candidate.component.value, candidate.name.casefold(), candidate.upstream_id)


def _safe_error_type(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._~-]", "", value)[:64]
    return normalized or "Error"


def _error_label(value: str) -> str:
    return "".join(part.capitalize() for part in re.findall(r"[A-Za-z0-9]+", value))[
        :48
    ]


SkillsShFederatedCatalogSource.descriptor = FederatedSourceDescriptor(
    source_id=SKILLS_SH_SOURCE_ID,
    kind=FederatedSourceKind.HOSTED_METADATA,
    canonical_origin=SKILLS_SH_ORIGIN,
    components=(FederatedCatalogComponent.SKILL,),
    hosted_auth_required=True,
    immutable_reference_capable=True,
)
NeuralDeepFederatedCatalogSource.descriptor = FederatedSourceDescriptor(
    source_id=NEURALDEEP_SOURCE_ID,
    kind=FederatedSourceKind.PUBLIC_GET,
    canonical_origin=NEURALDEEP_ORIGIN,
    components=(FederatedCatalogComponent.SKILL, FederatedCatalogComponent.MCP),
    hosted_auth_required=False,
    immutable_reference_capable=False,
)


__all__ = [
    "FEDERATED_CATALOG_CONTRACT_VERSION",
    "MAX_FEDERATED_ENTRIES",
    "MAX_FEDERATED_PAGES",
    "MAX_FEDERATED_RESPONSE_BYTES",
    "NEURALDEEP_ORIGIN",
    "NEURALDEEP_SOURCE_ID",
    "SKILLS_SH_ORIGIN",
    "SKILLS_SH_SOURCE_ID",
    "FederatedArtifactResolution",
    "FederatedAuditProjection",
    "FederatedCatalogCandidate",
    "FederatedCatalogComponent",
    "FederatedCatalogSnapshot",
    "FederatedCatalogSource",
    "FederatedHTTPResponse",
    "FederatedProvenance",
    "FederatedRefreshResult",
    "FederatedRequest",
    "FederatedSourceDescriptor",
    "FederatedSourceHealth",
    "FederatedSourceKind",
    "FederatedTrustProjection",
    "NeuralDeepFederatedCatalogSource",
    "SkillsShFederatedCatalogSource",
    "fetch_federated_json",
]
