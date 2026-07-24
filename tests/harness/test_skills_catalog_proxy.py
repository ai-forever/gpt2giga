from __future__ import annotations

import json

from fastapi.testclient import TestClient

from gpt2giga_harness.skills_catalog_proxy import (
    SKILLS_PROXY_UPSTREAM_ORIGIN,
    SkillsCatalogProxySettings,
    SkillsProxyUpstreamResponse,
    create_skills_catalog_proxy_app,
)


class _Upstream:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses[kwargs["url"]]
        if isinstance(response, Exception):
            raise response
        return response


async def _token():
    return "oidc-secret-canary"


def test_proxy_is_fixed_origin_metadata_only_and_cache_bounded():
    list_url = (
        f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills?view=all-time&page=0&per_page=1"
    )
    detail_url = f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills/acme/skills/react"
    upstream = _Upstream(
        {
            list_url: _response(
                list_url,
                {
                    "data": [_skill_item()],
                    "pagination": {
                        "page": 0,
                        "perPage": 1,
                        "total": 1,
                        "hasMore": False,
                    },
                },
            ),
            detail_url: _response(
                detail_url,
                {
                    "id": "acme/skills/react",
                    "source": "acme/skills",
                    "slug": "react",
                    "installs": 12,
                    "hash": "a" * 64,
                    "files": [
                        {"path": "SKILL.md", "contents": "secret-content-canary"}
                    ],
                },
            ),
        }
    )
    client = TestClient(
        create_skills_catalog_proxy_app(token_provider=_token, upstream=upstream)
    )

    listing = client.get("/api/v1/skills", params={"page": 0, "per_page": 1})
    detail = client.get("/api/v1/skills/acme/skills/react")

    assert listing.status_code == 200
    assert detail.status_code == 200
    assert set(detail.json()) == {
        "id",
        "source",
        "slug",
        "installs",
        "hash",
        "files",
    }
    assert detail.json()["files"] == [{"path": "SKILL.md"}]
    assert "secret-content-canary" not in detail.text
    assert listing.headers["etag"].startswith('"')
    assert listing.headers["cache-control"] == "public, max-age=60"
    assert [call["url"] for call in upstream.calls] == [list_url, detail_url]
    assert all(
        call["headers"]["Authorization"].startswith("Bearer ")
        for call in upstream.calls
    )
    assert "oidc-secret-canary" not in listing.text + detail.text


def test_proxy_labels_stale_last_good_after_rate_limit():
    url = (
        f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills?view=all-time&page=0&per_page=1"
    )
    responses = [
        _response(
            url,
            {
                "data": [_skill_item()],
                "pagination": {
                    "page": 0,
                    "perPage": 1,
                    "total": 1,
                    "hasMore": False,
                },
            },
        ),
        SkillsProxyUpstreamResponse(
            status_code=429,
            final_url=url,
            headers={"Retry-After": "12"},
            body=b'{"error":"rate_limited"}',
        ),
    ]

    async def upstream(**_kwargs):
        return responses.pop(0)

    clock = [10.0]
    client = TestClient(
        create_skills_catalog_proxy_app(
            token_provider=_token,
            upstream=upstream,
            monotonic=lambda: clock[0],
        )
    )

    fresh = client.get("/api/v1/skills", params={"page": 0, "per_page": 1})
    clock[0] = 42.0
    stale = client.get("/api/v1/skills", params={"page": 0, "per_page": 1})

    assert fresh.headers["x-giga-cache-status"] == "fresh"
    assert stale.status_code == 200
    assert stale.json() == fresh.json()
    assert stale.headers["x-giga-cache-status"] == "stale"
    assert stale.headers["x-giga-source-error"] == "proxy.upstream_rate_limited"
    assert stale.headers["age"] == "32"
    assert stale.headers["warning"]


def test_proxy_exposes_curated_and_bounded_audit_metadata():
    curated_url = f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills/curated"
    audit_url = f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills/audit/acme/skills/react"
    upstream = _Upstream(
        {
            curated_url: _response(
                curated_url,
                {
                    "data": [
                        {
                            "owner": "acme",
                            "totalInstalls": 12,
                            "featuredRepo": "skills",
                            "featuredSkill": "react",
                            "skills": [_skill_item()],
                        }
                    ],
                    "totalOwners": 1,
                    "totalSkills": 1,
                    "generatedAt": "2026-07-24T08:00:00Z",
                },
            ),
            audit_url: _response(
                audit_url,
                {
                    "id": "acme/skills/react",
                    "source": "acme/skills",
                    "slug": "react",
                    "audits": [
                        {
                            "provider": "Socket",
                            "slug": "socket",
                            "status": "pass",
                            "summary": "secret-summary-canary",
                            "auditedAt": "2026-07-24T08:05:00Z",
                            "riskLevel": "LOW",
                        }
                    ],
                },
            ),
        }
    )
    client = TestClient(
        create_skills_catalog_proxy_app(token_provider=_token, upstream=upstream)
    )

    curated = client.get("/api/v1/skills/curated")
    audit = client.get("/api/v1/skills/audit/acme/skills/react")

    assert curated.status_code == 200
    assert curated.json()["data"][0]["skills"][0]["id"] == "acme/skills/react"
    assert audit.status_code == 200
    assert audit.json()["audits"] == [
        {
            "provider": "Socket",
            "slug": "socket",
            "status": "pass",
            "auditedAt": "2026-07-24T08:05:00Z",
            "riskLevel": "LOW",
        }
    ]
    assert "secret-summary-canary" not in audit.text


def test_proxy_rejects_writes_bad_inputs_and_bounds_rate_without_upstream_calls():
    upstream = _Upstream({})
    client = TestClient(
        create_skills_catalog_proxy_app(
            settings=SkillsCatalogProxySettings(rate_limit_per_minute=2),
            token_provider=_token,
            upstream=upstream,
            monotonic=lambda: 10.0,
        )
    )

    assert client.post("/api/v1/skills").status_code == 405
    assert client.get("/api/v1/skills", params={"per_page": 501}).status_code == 400
    assert client.get("/api/v1/skills/search", params={"q": "x"}).status_code == 429
    assert upstream.calls == []


def test_proxy_maps_upstream_failures_to_content_free_errors(monkeypatch):
    url = (
        f"{SKILLS_PROXY_UPSTREAM_ORIGIN}/api/v1/skills?"
        "view=all-time&page=0&per_page=100"
    )
    upstream = _Upstream(
        {
            url: SkillsProxyUpstreamResponse(
                status_code=401,
                final_url=url,
                headers={},
                body=b'{"message":"oidc-secret-canary"}',
            )
        }
    )
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "configured-secret-canary")
    client = TestClient(
        create_skills_catalog_proxy_app(token_provider=_token, upstream=upstream)
    )

    health = client.get("/healthz")
    failed = client.get("/api/v1/skills")

    assert health.json()["oidc_configured"] is True
    assert failed.status_code == 503
    assert failed.json() == {"error": "proxy.upstream_auth_failed"}
    assert "secret-canary" not in failed.text


def _response(url: str, payload: object) -> SkillsProxyUpstreamResponse:
    return SkillsProxyUpstreamResponse(
        status_code=200,
        final_url=url,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def _skill_item() -> dict[str, object]:
    return {
        "id": "acme/skills/react",
        "slug": "react",
        "name": "react",
        "source": "acme/skills",
        "installs": 12,
        "sourceType": "github",
        "installUrl": "https://github.com/acme/skills",
        "url": "https://skills.sh/acme/skills/react",
    }
