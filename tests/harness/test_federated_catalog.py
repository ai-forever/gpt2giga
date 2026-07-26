from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json

import pytest

from gpt2giga_harness.federated_catalog import (
    MAX_FEDERATED_PAGES,
    MAX_FEDERATED_RESPONSE_BYTES,
    NEURALDEEP_ORIGIN,
    SKILLS_SH_ORIGIN,
    FederatedCatalogComponent,
    FederatedHTTPResponse,
    FederatedSourceKind,
    NeuralDeepFederatedCatalogSource,
    SkillsShFederatedCatalogSource,
)


_NOW = datetime(2026, 7, 20, 9, 30, tzinfo=timezone.utc)
_HASH = "a" * 64


class _FixtureFetcher:
    def __init__(self, responses: Mapping[str, object]) -> None:
        self.responses = dict(responses)
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        response = self.responses[request.url]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, FederatedHTTPResponse):
            return response
        return _response(request.url, response)


async def test_skills_sh_hosted_boundary_refresh_search_detail_and_resolution():
    page_zero = f"{SKILLS_SH_ORIGIN}/api/v1/skills?page=0&per_page=1"
    page_one = f"{SKILLS_SH_ORIGIN}/api/v1/skills?page=1&per_page=1"
    search = f"{SKILLS_SH_ORIGIN}/api/v1/skills/search?q=react&limit=5"
    detail = f"{SKILLS_SH_ORIGIN}/api/v1/skills/acme/skills/react"
    fetcher = _FixtureFetcher(
        {
            page_zero: _skills_page(_skills_item(), page=0, has_more=True),
            page_one: _skills_page(
                _skills_item(
                    upstream_id="example.com/tooling",
                    slug="tooling",
                    source="example.com",
                    install_url="https://example.com",
                ),
                page=1,
                has_more=False,
            ),
            search: {
                "data": [_skills_item()],
                "query": "react",
                "searchType": "fuzzy",
                "count": 1,
                "durationMs": 4,
            },
            detail: {
                "id": "acme/skills/react",
                "source": "acme/skills",
                "slug": "react",
                "installs": 12,
                "hash": _HASH,
            },
        }
    )
    source = SkillsShFederatedCatalogSource(
        hosted_fetch=fetcher,
        now=lambda: _NOW,
    )
    assert source.descriptor.kind is FederatedSourceKind.HOSTED_METADATA
    assert source.descriptor.install_authorized is False

    refresh = await source.refresh(page_size=1)
    found = await source.search("react", limit=5)
    selected = await source.detail("acme/skills/react")
    artifact = await source.resolve_artifact("acme/skills/react")

    assert refresh.success is True
    assert [item.upstream_id for item in refresh.snapshot.items] == [
        "acme/skills/react",
        "example.com/tooling",
    ]
    assert found[0].upstream_id == selected.upstream_id
    assert selected.immutable_ref == f"sha256:{_HASH}"
    assert selected.component is FederatedCatalogComponent.SKILL
    assert selected.provenance.canonical_origin == SKILLS_SH_ORIGIN
    assert selected.trust.popularity == 12
    assert selected.trust.install_authorized is False
    assert selected.source_present is True
    assert artifact.available is True
    assert artifact.immutable_ref == f"sha256:{_HASH}"
    assert artifact.artifact_url == "https://github.com/acme/skills"
    assert artifact.install_authorized is False
    assert all(request.method == "GET" for request in fetcher.requests)
    assert all(
        request.headers == {"Accept": "application/json"}
        for request in fetcher.requests
    )
    assert "files" not in repr(source.last_good)


async def test_skills_sh_curated_detail_paths_and_audits_are_bounded():
    curated_url = f"{SKILLS_SH_ORIGIN}/api/v1/skills/curated"
    page_url = f"{SKILLS_SH_ORIGIN}/api/v1/skills?page=0&per_page=1"
    detail_url = f"{SKILLS_SH_ORIGIN}/api/v1/skills/acme/skills/react"
    audit_url = f"{SKILLS_SH_ORIGIN}/api/v1/skills/audit/acme/skills/react"
    fetcher = _FixtureFetcher(
        {
            curated_url: {
                "data": [
                    {
                        "owner": "acme",
                        "totalInstalls": 12,
                        "featuredRepo": "skills",
                        "featuredSkill": "react",
                        "skills": [_skills_item()],
                    }
                ],
                "totalOwners": 1,
                "totalSkills": 1,
                "generatedAt": "2026-07-24T08:00:00Z",
            },
            page_url: _skills_page(_skills_item(), page=0, has_more=False),
            detail_url: {
                "id": "acme/skills/react",
                "source": "acme/skills",
                "slug": "react",
                "installs": 12,
                "hash": _HASH,
                "files": [
                    {"path": "SKILL.md"},
                    {"path": "references/guide.md"},
                ],
            },
            audit_url: {
                "id": "acme/skills/react",
                "source": "acme/skills",
                "slug": "react",
                "audits": [
                    {
                        "provider": "Socket",
                        "slug": "socket",
                        "status": "pass",
                        "auditedAt": "2026-07-24T08:05:00Z",
                        "riskLevel": "LOW",
                    }
                ],
            },
        }
    )
    source = SkillsShFederatedCatalogSource(
        hosted_fetch=fetcher,
        now=lambda: _NOW,
    )

    refresh = await source.refresh(page_size=1)
    detail = await source.detail("acme/skills/react")
    audits = await source.audits("acme/skills/react")

    assert refresh.success is True
    assert refresh.snapshot.items[0].trust.curated is True
    assert detail.immutable_ref == f"sha256:{_HASH}"
    assert detail.provenance.relative_path == "SKILL.md"
    assert detail.provenance.file_paths == (
        "SKILL.md",
        "references/guide.md",
    )
    assert [(item.provider, item.status, item.risk_level) for item in audits] == [
        ("Socket", "pass", "LOW")
    ]


def test_skills_sh_requires_an_explicit_hosted_metadata_boundary():
    with pytest.raises(ValueError, match="hosted metadata fetcher"):
        SkillsShFederatedCatalogSource()


async def test_neuraldeep_direct_get_keeps_skills_and_mcp_separate():
    skills_url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=skill"
    mcp_url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=mcp"
    search_skill = f"{NEURALDEEP_ORIGIN}/skapi/skills?q=git&type=skill"
    search_mcp = f"{NEURALDEEP_ORIGIN}/skapi/skills?q=git&type=mcp"
    fetcher = _FixtureFetcher(
        {
            skills_url: [_neural_item()],
            mcp_url: [_neural_item(upstream_id="curated:git", kind="mcp")],
            search_skill: [_neural_item()],
            search_mcp: [],
        }
    )
    source = NeuralDeepFederatedCatalogSource(fetch=fetcher, now=lambda: _NOW)
    assert source.descriptor.kind is FederatedSourceKind.PUBLIC_GET
    assert source.descriptor.install_authorized is False

    refresh = await source.refresh()
    found = await source.search("git", limit=10)
    selected = await source.detail("skill-123")
    artifact = await source.resolve_artifact("skill-123")

    assert refresh.success is True
    assert {item.component for item in refresh.snapshot.items} == {
        FederatedCatalogComponent.SKILL,
        FederatedCatalogComponent.MCP,
    }
    assert found == (selected,)
    assert selected.provenance.canonical_origin == NEURALDEEP_ORIGIN
    assert selected.provenance.artifact_origin == "https://github.com"
    assert selected.trust.curated is True
    assert selected.trust.install_authorized is False
    assert artifact.available is False
    assert artifact.reason_code == "immutable_reference_unavailable"
    assert artifact.install_authorized is False
    assert all(
        request.headers == {"Accept": "application/json"}
        for request in fetcher.requests
    )


async def test_neuraldeep_mcp_detail_uses_the_public_slug():
    mcp_url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=mcp"
    source = NeuralDeepFederatedCatalogSource(
        fetch=_FixtureFetcher(
            {
                mcp_url: [
                    _neural_item(
                        upstream_id="curated:gigachat-image",
                        kind="mcp",
                    )
                    | {"name": "GigaChat Image MCP"}
                ]
            }
        ),
        now=lambda: _NOW,
    )

    result = await source.refresh(components=(FederatedCatalogComponent.MCP,))

    assert result.success is True
    assert (
        result.snapshot.items[0].provenance.detail_url
        == "https://neuraldeep.ru/mcp/gigachat-image"
    )


@pytest.mark.parametrize("kind", ["plugin", "extension", "harness_adapter", "cli"])
async def test_federated_sources_fail_closed_for_unsupported_content(kind):
    url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=skill"
    source = NeuralDeepFederatedCatalogSource(
        fetch=_FixtureFetcher({url: [_neural_item(kind=kind)]}),
        now=lambda: _NOW,
    )

    result = await source.refresh(components=(FederatedCatalogComponent.SKILL,))

    assert result.success is False
    assert result.health.error_code == "source.unsupported_component"
    assert result.snapshot.items == ()
    assert result.health.install_authorized is False


async def test_last_good_cache_survives_partial_pagination_and_schema_drift():
    page_zero = f"{SKILLS_SH_ORIGIN}/api/v1/skills?page=0&per_page=1"
    page_one = f"{SKILLS_SH_ORIGIN}/api/v1/skills?page=1&per_page=1"
    fetcher = _FixtureFetcher(
        {
            page_zero: _skills_page(_skills_item(), page=0, has_more=False),
        }
    )
    source = SkillsShFederatedCatalogSource(hosted_fetch=fetcher, now=lambda: _NOW)
    initial = await source.refresh(page_size=1)
    assert initial.success is True

    fetcher.responses[page_zero] = _skills_page(_skills_item(), page=0, has_more=True)
    fetcher.responses[page_one] = RuntimeError("upstream failed")
    partial = await source.refresh(page_size=1)
    assert partial.success is False
    assert partial.health.error_code == "source.fetch_failed"
    assert partial.snapshot == initial.snapshot

    drifted = _skills_page(_skills_item(), page=0, has_more=False)
    drifted["newField"] = True
    fetcher.responses[page_zero] = drifted
    drift = await source.refresh(page_size=1)
    assert drift.success is False
    assert drift.health.error_code == "source.schema_drift"
    assert drift.snapshot == initial.snapshot


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            FederatedHTTPResponse(
                401, SKILLS_SH_ORIGIN + "/api/v1/skills?page=0&per_page=1", {}, b"{}"
            ),
            "source.auth_failed",
        ),
        (
            FederatedHTTPResponse(
                429, SKILLS_SH_ORIGIN + "/api/v1/skills?page=0&per_page=1", {}, b"{}"
            ),
            "source.rate_limited",
        ),
        (
            FederatedHTTPResponse(
                200, "https://evil.example/api/v1/skills", {}, b"{}", redirected=True
            ),
            "source.redirect_rejected",
        ),
        (
            FederatedHTTPResponse(
                200,
                SKILLS_SH_ORIGIN + "/api/v1/skills?page=0&per_page=1",
                {},
                b"x" * (MAX_FEDERATED_RESPONSE_BYTES + 1),
            ),
            "source.response_too_large",
        ),
    ],
)
async def test_transport_failures_are_bounded_content_free(response, code):
    url = f"{SKILLS_SH_ORIGIN}/api/v1/skills?page=0&per_page=1"
    source = SkillsShFederatedCatalogSource(
        hosted_fetch=_FixtureFetcher({url: response}),
        now=lambda: _NOW,
    )

    result = await source.refresh(page_size=1)

    assert result.success is False
    assert result.health.error_code == code
    assert result.health.error_type
    assert result.health.install_authorized is False
    assert "evil.example" not in repr(result.health)


@pytest.mark.parametrize(
    "case",
    ["malformed", "drift", "duplicate"],
)
async def test_skills_sh_rejects_malformed_ids_drift_and_duplicates(case):
    if case == "malformed":
        items = (_skills_item(upstream_id="bad id"),)
    elif case == "drift":
        items = (_skills_item() | {"extra": "drift"},)
    else:
        items = (_skills_item(), _skills_item())
    payload = _skills_page(*items, page=0, has_more=False)
    url = f"{SKILLS_SH_ORIGIN}/api/v1/skills?page=0&per_page=2"
    source = SkillsShFederatedCatalogSource(
        hosted_fetch=_FixtureFetcher({url: payload}),
        now=lambda: _NOW,
    )

    result = await source.refresh(page_size=2)

    assert result.success is False
    assert result.health.error_code in {
        "source.duplicate_entry",
        "source.invalid_payload",
        "source.schema_drift",
    }


async def test_successful_refresh_marks_omitted_entries_not_present():
    skills_url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=skill"
    mcp_url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=mcp"
    fetcher = _FixtureFetcher(
        {
            skills_url: [_neural_item()],
            mcp_url: [_neural_item(upstream_id="mcp-123", kind="mcp")],
        }
    )
    source = NeuralDeepFederatedCatalogSource(fetch=fetcher, now=lambda: _NOW)
    first = await source.refresh()
    assert first.success is True

    fetcher.responses[mcp_url] = []
    second = await source.refresh()

    omitted = next(
        item for item in second.snapshot.items if item.upstream_id == "mcp-123"
    )
    assert omitted.source_present is False
    assert omitted.trust.install_authorized is False
    assert second.health.complete is True


async def test_neuraldeep_deleted_and_malformed_records_fail_closed():
    skills_url = f"{NEURALDEEP_ORIGIN}/skapi/skills?type=skill"
    deleted = _neural_item() | {"status": "deleted"}
    source = NeuralDeepFederatedCatalogSource(
        fetch=_FixtureFetcher({skills_url: [deleted]}),
        now=lambda: _NOW,
    )
    result = await source.refresh(components=(FederatedCatalogComponent.SKILL,))
    assert result.success is True
    assert result.snapshot.items[0].source_present is False

    malformed = _neural_item() | {"id": "bad id"}
    source = NeuralDeepFederatedCatalogSource(
        fetch=_FixtureFetcher({skills_url: [malformed]}),
        now=lambda: _NOW,
    )
    result = await source.refresh(components=(FederatedCatalogComponent.SKILL,))
    assert result.success is False
    assert result.health.error_code == "source.invalid_payload"


async def test_skills_sh_repeated_or_excessive_pagination_fails_closed():
    responses = {}
    for page in range(MAX_FEDERATED_PAGES):
        url = f"{SKILLS_SH_ORIGIN}/api/v1/skills?page={page}&per_page=1"
        responses[url] = _skills_page(
            _skills_item(upstream_id=f"acme/skills/skill-{page}", slug=f"skill-{page}"),
            page=page,
            has_more=True,
        )
    source = SkillsShFederatedCatalogSource(
        hosted_fetch=_FixtureFetcher(responses),
        now=lambda: _NOW,
    )

    result = await source.refresh(page_size=1)

    assert result.success is False
    assert result.health.error_code == "source.pagination_incomplete"


def _response(url: str, payload: object) -> FederatedHTTPResponse:
    return FederatedHTTPResponse(
        status_code=200,
        final_url=url,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def _skills_item(
    *,
    upstream_id: str = "acme/skills/react",
    slug: str = "react",
    source: str = "acme/skills",
    install_url: str = "https://github.com/acme/skills",
) -> dict[str, object]:
    return {
        "id": upstream_id,
        "slug": slug,
        "name": slug,
        "source": source,
        "installs": 12,
        "sourceType": "github"
        if install_url.startswith("https://github.com/")
        else "well-known",
        "installUrl": install_url,
        "url": f"{SKILLS_SH_ORIGIN}/{upstream_id}",
    }


def _skills_page(
    *items: dict[str, object], page: int, has_more: bool
) -> dict[str, object]:
    return {
        "data": list(items),
        "pagination": {
            "page": page,
            "perPage": max(1, len(items)),
            "total": len(items) + (1 if has_more else 0),
            "hasMore": has_more,
        },
    }


def _neural_item(
    *,
    upstream_id: str = "skill-123",
    kind: str = "skill",
) -> dict[str, object]:
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
