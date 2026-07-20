from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient

from gpt2giga_harness.federated_catalog import (
    FederatedCatalogComponent,
    FederatedHTTPResponse,
    NEURALDEEP_ORIGIN,
    SKILLS_SH_ORIGIN,
    NeuralDeepFederatedCatalogSource,
    SkillsShFederatedCatalogSource,
)
from gpt2giga_harness.federated_catalog_sync import (
    sync_federated_catalog_source,
    sync_federated_catalog_sources,
)
from gpt2giga_harness.integration_catalog import (
    CatalogSourceType,
    IntegrationCatalogStore,
    sync_official_mcp_registry,
)
from gpt2giga_harness.integration_flows import IntegrationFlowService
from gpt2giga_harness.integration_packages import IntegrationSourceType
from gpt2giga_harness.skills_catalog_proxy import (
    SKILLS_PROXY_UPSTREAM_ORIGIN,
    SkillsProxyUpstreamResponse,
    create_skills_catalog_proxy_app,
)
from gpt2giga_harness.skills_catalog_proxy_client import SkillsCatalogProxyFetcher


_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


class _FederatedFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def __call__(self, request):
        self.calls.append(request.url)
        response = self.responses[request.url]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, FederatedHTTPResponse):
            return response
        return FederatedHTTPResponse(
            status_code=200,
            final_url=request.url,
            headers={"content-type": "application/json"},
            body=json.dumps(response).encode(),
        )


class _ProxyUpstream:
    def __init__(self, responses):
        self.responses = responses

    async def __call__(self, **kwargs):
        payload = self.responses[kwargs["url"]]
        return SkillsProxyUpstreamResponse(
            status_code=200,
            final_url=kwargs["url"],
            headers={"content-type": "application/json"},
            body=json.dumps(payload).encode(),
        )


class _ProxyClientTransport:
    def __init__(self, client):
        self.client = client
        self.calls = []

    async def __call__(self, request):
        self.calls.append(request.url)
        parsed = request.url.removeprefix("https://proxy.test")
        response = self.client.get(parsed)
        return FederatedHTTPResponse(
            status_code=response.status_code,
            final_url=request.url,
            headers=dict(response.headers),
            body=response.content,
        )


async def _token():
    return "fixture-oidc-token"


async def test_proxy_to_source_to_offline_catalog_is_atomic_and_install_closed(
    tmp_path,
):
    upstream_list = (
        f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills?view=all-time&page=0&per_page=2"
    )
    upstream_detail = f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills/acme/skills/react"
    proxy = TestClient(
        create_skills_catalog_proxy_app(
            token_provider=_token,
            upstream=_ProxyUpstream(
                {
                    upstream_list: _skills_page(_skills_item(), per_page=2),
                    upstream_detail: _skills_detail(),
                }
            ),
        )
    )
    proxy_transport = _ProxyClientTransport(proxy)
    hosted_fetch = SkillsCatalogProxyFetcher(
        "https://proxy.test",
        fetch=proxy_transport,
    )
    source = SkillsShFederatedCatalogSource(
        hosted_fetch=hosted_fetch,
        now=lambda: _NOW,
    )
    store = IntegrationCatalogStore(tmp_path, now=lambda: _NOW)

    result = await sync_federated_catalog_source(store, source, page_size=2)

    assert result.success is True
    assert result.resolved_count == 1
    entry = next(item for item in store.list() if item.source_id == "skills-sh")
    assert entry.source_type is CatalogSourceType.FEDERATED_CATALOG
    assert entry.package.source_type is IntegrationSourceType.GIT
    assert entry.package.immutable_ref == "sha256:" + "a" * 64
    assert entry.federated.artifact_resolved is True
    assert entry.install_authorized is False
    assert entry.trust_decision.value == "review_required"
    state = next(
        item for item in store.snapshot().sources if item.source_id == "skills-sh"
    )
    assert state.retry_count == 0
    assert state.cursor is None
    assert state.freshness_expires_at == "2026-07-20T10:00:00Z"
    assert proxy_transport.calls == [
        "https://proxy.test/api/v1/skills?page=0&per_page=2",
        "https://proxy.test/api/v1/skills/acme/skills/react",
    ]

    inventory = IntegrationFlowService(tmp_path).inventory()
    projected = next(
        item for item in inventory["catalog"] if item["catalog_id"] == entry.catalog_id
    )
    assert projected["install_authorized"] is False
    assert projected["component_types"] == ["skill"]
    assert projected["source_present"] is True
    assert projected["discovery"] == {
        "upstream_id": "acme/skills/react",
        "canonical_package_id": None,
        "name": "react",
        "component": "skill",
        "canonical_origin": "https://skills.sh",
        "detail_url": "https://skills.sh/acme/skills/react",
        "artifact_url": "https://github.com/acme/skills",
        "curated": False,
        "popularity": 12,
        "upstream_audit": "reported_reviewed",
        "artifact_resolved": True,
        "source_present": True,
        "install_authorized": False,
    }


async def test_sources_sync_independently_and_unresolved_candidates_stay_visible(
    tmp_path,
):
    skills_url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=skill"
    mcp_url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=mcp"
    neural_fetch = _FederatedFetcher(
        {
            skills_url: [_neural_item()],
            mcp_url: [_neural_item(upstream_id="mcp-1", kind="mcp")],
        }
    )
    neural = NeuralDeepFederatedCatalogSource(
        fetch=neural_fetch,
        now=lambda: _NOW,
    )
    failing = SkillsShFederatedCatalogSource(
        hosted_fetch=_FederatedFetcher(
            {
                f"{SKILLS_SH_ORIGIN}/api/v1/skills?page=0&per_page=100": RuntimeError(
                    "token=secret-canary"
                )
            }
        ),
        now=lambda: _NOW,
    )
    store = IntegrationCatalogStore(tmp_path, now=lambda: _NOW)

    results = await sync_federated_catalog_sources(store, (failing, neural))

    assert [item.success for item in results] == [False, True]
    neural_entries = [item for item in store.list() if item.source_id == "neuraldeep"]
    assert {item.federated.component for item in neural_entries} == {"skill", "mcp"}
    assert all(item.package is None for item in neural_entries)
    assert all(
        item.pinned is False and item.immutable_ref is None for item in neural_entries
    )
    assert "secret-canary" not in store.path.read_text(encoding="utf-8")


async def test_neuraldeep_mcp_metadata_links_exact_official_identity_without_repinning(
    tmp_path,
):
    store = IntegrationCatalogStore(tmp_path, now=lambda: _NOW)

    async def official_page(**_kwargs):
        return {
            "servers": [_official_mcp_response()],
            "metadata": {"count": 1},
        }

    official_sync = await sync_official_mcp_registry(store, fetch_page=official_page)
    assert official_sync.success is True
    official_before = next(
        item for item in store.list() if item.mcp_response is not None
    )
    mcp_url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=mcp"
    neural = NeuralDeepFederatedCatalogSource(
        fetch=_FederatedFetcher(
            {mcp_url: [_neural_item(upstream_id="neural-card-1", kind="mcp")]}
        ),
        now=lambda: _NOW,
    )

    result = await sync_federated_catalog_source(
        store,
        neural,
        components=(FederatedCatalogComponent.MCP,),
    )

    assert result.success is True
    official_after = next(
        item for item in store.list() if item.mcp_response is not None
    )
    localized = next(item for item in store.list() if item.federated is not None)
    assert official_after == official_before
    assert localized.source_id == "neuraldeep"
    assert localized.package_id == "io.example/tools"
    assert localized.federated.canonical_package_id == "io.example/tools"
    assert localized.federated.name == "git-tools"
    assert localized.pinned is False
    assert localized.install_authorized is False


async def test_removal_preserves_pin_and_failure_backoff_preserves_last_good(tmp_path):
    page_url = f"{SKILLS_SH_ORIGIN}/api/v1/skills?page=0&per_page=1"
    detail_url = f"{SKILLS_SH_ORIGIN}/api/v1/skills/acme/skills/react"
    fetcher = _FederatedFetcher(
        {
            page_url: _skills_page(_skills_item(), per_page=1),
            detail_url: _skills_detail(include_files=False),
        }
    )
    clock = [_NOW]
    source = SkillsShFederatedCatalogSource(
        hosted_fetch=fetcher,
        now=lambda: clock[0],
    )
    store = IntegrationCatalogStore(tmp_path, now=lambda: clock[0])
    first = await sync_federated_catalog_source(store, source, page_size=1)
    assert first.success is True
    pinned_id = store.list()[0].catalog_id

    clock[0] += timedelta(minutes=1)
    fetcher.responses[page_url] = _skills_page(per_page=1)
    removed = await sync_federated_catalog_source(store, source, page_size=1)
    assert removed.success is True
    retained = store.get(pinned_id)
    assert retained.pinned is True
    assert retained.source_present is False
    assert retained.federated.source_present is False

    clock[0] += timedelta(minutes=1)
    fetcher.responses[page_url] = RuntimeError("credential=secret-canary")
    failed = await sync_federated_catalog_source(store, source, page_size=1)
    calls_after_failure = len(fetcher.calls)
    skipped = await sync_federated_catalog_source(store, source, page_size=1)

    assert failed.success is False
    assert failed.next_retry_at == "2026-07-20T09:02:30Z"
    assert skipped.attempted is False
    assert len(fetcher.calls) == calls_after_failure
    assert store.get(pinned_id).source_present is False
    assert "secret-canary" not in store.path.read_text(encoding="utf-8")


async def test_same_discovery_version_drift_fails_closed(tmp_path):
    skill_url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=skill"
    fetcher = _FederatedFetcher({skill_url: [_neural_item()]})
    source = NeuralDeepFederatedCatalogSource(fetch=fetcher, now=lambda: _NOW)
    store = IntegrationCatalogStore(tmp_path, now=lambda: _NOW)
    first = await sync_federated_catalog_source(
        store,
        source,
        components=(FederatedCatalogComponent.SKILL,),
    )
    assert first.success is True
    before = store.list()

    changed = _neural_item() | {"owner": "other-owner"}
    fetcher.responses[skill_url] = [changed]
    failed = await sync_federated_catalog_source(
        store,
        source,
        components=(FederatedCatalogComponent.SKILL,),
        force=True,
    )

    assert failed.success is False
    assert store.list() == before


def _skills_item() -> dict[str, object]:
    return {
        "id": "acme/skills/react",
        "slug": "react",
        "name": "react",
        "source": "acme/skills",
        "installs": 12,
        "sourceType": "github",
        "installUrl": "https://github.com/acme/skills",
        "url": f"{SKILLS_SH_ORIGIN}/acme/skills/react",
    }


def _skills_page(*items, per_page: int) -> dict[str, object]:
    return {
        "data": list(items),
        "pagination": {
            "page": 0,
            "perPage": per_page,
            "total": len(items),
            "hasMore": False,
        },
    }


def _skills_detail(*, include_files: bool = True) -> dict[str, object]:
    detail = {
        "id": "acme/skills/react",
        "source": "acme/skills",
        "slug": "react",
        "installs": 12,
        "hash": "a" * 64,
    }
    if include_files:
        detail["files"] = [{"path": "SKILL.md", "contents": "not proxied"}]
    return detail


def _neural_item(*, upstream_id: str = "skill-1", kind: str = "skill"):
    return {
        "id": upstream_id,
        "name": "git-tools",
        "owner": "acme",
        "repo": "tools",
        "description": "not persisted",
        "installs": 7,
        "trending24h": 1,
        "category": "utilities",
        "tags": ["git"],
        "contentPath": None,
        "authorName": "Acme",
        "telegramLink": None,
        "featured": True,
        "type": kind,
        "status": "approved",
        "githubStars": 42,
        "createdAt": "2026-07-01T08:00:00Z",
        "updatedAt": "2026-07-20T08:00:00Z",
        "authorId": None,
    }


def _official_mcp_response() -> dict[str, object]:
    return {
        "server": {
            "$schema": (
                "https://static.modelcontextprotocol.io/schemas/"
                "2025-12-11/server.schema.json"
            ),
            "name": "io.example/tools",
            "title": "Tools",
            "description": "Fixture MCP server.",
            "version": "1.0.0",
            "repository": {
                "url": "https://github.com/acme/tools",
                "source": "github",
            },
        },
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "status": "active",
                "isLatest": True,
                "publishedAt": "2026-07-20T08:00:00Z",
                "updatedAt": "2026-07-20T08:00:00Z",
            }
        },
    }
