from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import stat

import pytest

from gpt2giga_harness.integration_catalog import (
    MAX_CATALOG_SOURCE_ERRORS,
    OFFICIAL_MCP_REGISTRY_SOURCE_ID,
    CatalogConflictError,
    CatalogEntryStatus,
    CatalogSourceType,
    CatalogStateError,
    IntegrationCatalogStore,
    MCPSubregistry,
    catalog_entry_to_dict,
    sync_official_mcp_registry,
)
from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationSourceType,
    IntegrationUpdatePolicy,
    integration_package_to_dict,
)


_DIGEST = "sha256:" + "a" * 64
_SECOND_DIGEST = "sha256:" + "b" * 64
_NOW = datetime(2026, 7, 19, 8, 30, tzinfo=timezone.utc)


async def test_official_registry_sync_is_paginated_cached_and_offline(tmp_path):
    pages = {
        None: {
            "servers": [_mcp_response("io.example/alpha", "1.0.0", latest=True)],
            "metadata": {"count": 1, "nextCursor": "next-page"},
        },
        "next-page": {
            "servers": [_mcp_response("io.example/beta", "2.0.0", latest=True)],
            "metadata": {"count": 1, "nextCursor": ""},
        },
    }
    calls = []

    async def fetch_page(**kwargs):
        calls.append(kwargs)
        return pages[kwargs["cursor"]]

    store = _store(tmp_path)
    result = await sync_official_mcp_registry(
        store,
        fetch_page=fetch_page,
        page_size=1,
    )

    assert result.success is True
    assert result.fetched_count == 2
    assert [item["cursor"] for item in calls] == [None, "next-page"]
    assert all(item["include_deleted"] is True for item in calls)
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600

    subregistry = MCPSubregistry(IntegrationCatalogStore(tmp_path))
    first = subregistry.list_servers(limit=1)
    second = subregistry.list_servers(
        limit=1,
        cursor=first["metadata"]["nextCursor"],
    )

    assert [item["server"]["name"] for item in first["servers"]] == ["io.example/alpha"]
    assert [item["server"]["name"] for item in second["servers"]] == ["io.example/beta"]
    local_meta = first["servers"][0]["_meta"]["agent_workbench.catalog/v1"]
    assert local_meta["sourceId"] == OFFICIAL_MCP_REGISTRY_SOURCE_ID
    assert local_meta["pinned"] is True
    assert local_meta["sourcePresent"] is True
    assert local_meta["installAuthorized"] is False
    assert local_meta["trustDecision"] == "review_required"
    assert len(calls) == 2


async def test_status_changes_and_upstream_omission_do_not_replace_pins(tmp_path):
    store = _store(tmp_path)
    alpha = _mcp_response("io.example/alpha", "1.0.0", latest=True)
    beta = _mcp_response("io.example/beta", "1.0.0", latest=True)

    await sync_official_mcp_registry(
        store,
        fetch_page=_one_page_fetcher(alpha, beta),
    )
    deprecated = _mcp_response(
        "io.example/alpha",
        "1.0.0",
        latest=True,
        status="deprecated",
    )
    await sync_official_mcp_registry(
        store,
        fetch_page=_one_page_fetcher(deprecated),
    )

    by_name = {item.package_id: item for item in store.list()}
    assert by_name["io.example/alpha"].status is CatalogEntryStatus.DEPRECATED
    assert by_name["io.example/alpha"].source_present is True
    assert by_name["io.example/beta"].pinned is True
    assert by_name["io.example/beta"].source_present is False

    conflicting = _mcp_response(
        "io.example/alpha",
        "1.0.0",
        latest=True,
        description="Changed content for the same immutable version.",
    )
    result = await sync_official_mcp_registry(
        store,
        fetch_page=_one_page_fetcher(conflicting),
    )

    assert result.success is False
    assert [item.code for item in result.errors] == ["source.immutable_conflict"]
    retained = {item.package_id: item for item in store.list()}["io.example/alpha"]
    assert retained.mcp_response["server"]["description"] == "Fixture MCP server."
    assert retained.status is CatalogEntryStatus.DEPRECATED
    assert retained.install_authorized is False
    source = next(
        item
        for item in store.snapshot().sources
        if item.source_id == OFFICIAL_MCP_REGISTRY_SOURCE_ID
    )
    assert source.last_attempt_succeeded is False
    assert source.complete is False


async def test_failed_sync_preserves_cache_and_bounds_secret_free_errors(tmp_path):
    store = _store(tmp_path)
    await sync_official_mcp_registry(
        store,
        fetch_page=_one_page_fetcher(
            _mcp_response("io.example/alpha", "1.0.0", latest=True)
        ),
    )
    catalog_ids = [item.catalog_id for item in store.list()]

    async def fail(**_kwargs):
        raise ValueError("api_key=secret-value-canary")

    for _ in range(MAX_CATALOG_SOURCE_ERRORS + 5):
        result = await sync_official_mcp_registry(store, fetch_page=fail)
        assert result.success is False

    snapshot = store.snapshot()
    source = next(
        item
        for item in snapshot.sources
        if item.source_id == OFFICIAL_MCP_REGISTRY_SOURCE_ID
    )
    assert [item.catalog_id for item in snapshot.entries] == catalog_ids
    assert source.last_attempt_succeeded is False
    assert source.last_success_at == "2026-07-19T08:30:00Z"
    assert len(source.errors) == MAX_CATALOG_SOURCE_ERRORS
    assert {item.error_type for item in source.errors} == {"ValueError"}
    assert "secret-value-canary" not in store.path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("catalog_source", "package_source"),
    [
        (CatalogSourceType.LOCAL_PRIVATE, IntegrationSourceType.CURATED_CATALOG),
        (
            CatalogSourceType.PROVIDER_MARKETPLACE,
            IntegrationSourceType.PROVIDER_MARKETPLACE,
        ),
        (CatalogSourceType.GIT, IntegrationSourceType.GIT),
        (CatalogSourceType.LOCAL, IntegrationSourceType.LOCAL),
    ],
)
def test_reviewed_manifest_imports_retain_provenance_without_trust(
    tmp_path,
    catalog_source,
    package_source,
):
    store = _store(tmp_path)
    package = _package(package_source)

    entry = store.import_manifest(
        integration_package_to_dict(package),
        source_id=f"source-{catalog_source.value}",
        source_type=catalog_source,
    )
    payload = catalog_entry_to_dict(entry)

    assert entry.package == package
    assert payload["source_type"] == catalog_source.value
    assert payload["immutable_ref"] == package.immutable_ref
    assert payload["pinned"] is True
    assert payload["install_authorized"] is False
    assert payload["trust_decision"] == "review_required"


def test_manifest_import_rejects_source_mismatch_and_immutable_conflict(tmp_path):
    store = _store(tmp_path)
    package = _package(IntegrationSourceType.GIT)

    with pytest.raises(ValueError, match="source does not match"):
        store.import_package(
            package,
            source_id="git-example",
            source_type=CatalogSourceType.LOCAL,
        )

    original = store.import_package(
        package,
        source_id="git-example",
        source_type=CatalogSourceType.GIT,
    )
    changed = replace(
        package,
        immutable_ref="commit-cafebabe",
        checksum=_SECOND_DIGEST,
    )
    with pytest.raises(CatalogConflictError, match="immutable pin"):
        store.import_package(
            changed,
            source_id="git-example",
            source_type=CatalogSourceType.GIT,
        )

    assert store.get(original.catalog_id).package == package

    with pytest.raises(CatalogConflictError, match="owned by another type"):
        store.import_package(
            _package(IntegrationSourceType.LOCAL),
            source_id="git-example",
            source_type=CatalogSourceType.LOCAL,
        )


async def test_secret_inputs_are_redacted_before_cache_and_subregistry(tmp_path):
    response = _mcp_response("io.example/secret", "1.0.0", latest=True)
    response["server"]["packages"] = [
        {
            "registryType": "npm",
            "identifier": "example-mcp",
            "version": "1.0.0",
            "transport": {"type": "stdio"},
            "environmentVariables": [
                {
                    "name": "SERVICE_CREDENTIAL",
                    "isSecret": True,
                    "value": "secret-value-canary",
                }
            ],
        }
    ]
    store = _store(tmp_path)

    await sync_official_mcp_registry(
        store,
        fetch_page=_one_page_fetcher(response),
    )

    cached = store.path.read_text(encoding="utf-8")
    projected = MCPSubregistry(store).get_version("io.example/secret", "latest")
    variable = projected["server"]["packages"][0]["environmentVariables"][0]
    assert "secret-value-canary" not in cached
    assert variable["name"] == "SERVICE_CREDENTIAL"
    assert variable["value"] == "<redacted>"


async def test_subregistry_filters_deleted_and_validates_cursor_and_versions(tmp_path):
    store = _store(tmp_path)
    active = _mcp_response("io.example/server", "1.0.0", latest=False)
    latest = _mcp_response("io.example/server", "2.0.0", latest=True)
    active["_meta"]["io.modelcontextprotocol.registry/official"]["publishedAt"] = (
        "2026-07-18T08:00:00Z"
    )
    deleted = _mcp_response(
        "io.example/deleted",
        "1.0.0",
        latest=True,
        status="deleted",
    )
    await sync_official_mcp_registry(
        store,
        fetch_page=_one_page_fetcher(active, latest, deleted),
    )
    subregistry = MCPSubregistry(store)

    assert subregistry.list_servers()["metadata"]["count"] == 2
    assert subregistry.list_servers(include_deleted=True)["metadata"]["count"] == 3
    versions = subregistry.list_versions("io.example/server")
    assert versions["metadata"]["count"] == 2
    assert [item["server"]["version"] for item in versions["servers"]] == [
        "2.0.0",
        "1.0.0",
    ]
    assert (
        subregistry.get_version("io.example/server", "latest")["server"]["version"]
        == "2.0.0"
    )
    assert (
        subregistry.get_version("io.example/server", "1.0.0")["server"]["version"]
        == "1.0.0"
    )
    with pytest.raises(ValueError, match="cursor"):
        subregistry.list_servers(cursor="not-a-current-cursor")
    with pytest.raises(ValueError, match="limit"):
        subregistry.list_servers(limit=0)
    with pytest.raises(ValueError, match="include_deleted"):
        subregistry.list_servers(include_deleted="false")
    with pytest.raises(ValueError, match="search"):
        subregistry.list_servers(search=123)
    with pytest.raises(KeyError):
        subregistry.get_version("io.example/deleted", "latest")


def test_future_and_corrupt_catalog_state_fail_closed(tmp_path):
    store = _store(tmp_path)
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "revision": 1,
                "updated_at": "2026-07-19T08:30:00Z",
                "entries": [],
                "sources": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CatalogStateError, match="schema_version"):
        store.snapshot()

    store.path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(CatalogStateError, match="unreadable"):
        store.snapshot()


async def test_cached_status_and_source_counts_are_integrity_checked(tmp_path):
    store = _store(tmp_path)
    response = _mcp_response(
        "io.example/deprecated",
        "1.0.0",
        latest=True,
        status="deprecated",
    )
    await sync_official_mcp_registry(
        store,
        fetch_page=_one_page_fetcher(response),
    )
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["entries"][0]["status"] = "active"
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CatalogStateError, match="unreadable"):
        store.snapshot()

    payload["entries"][0]["status"] = "deprecated"
    payload["sources"][0]["entry_count"] = 0
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CatalogStateError, match="entry_count"):
        store.snapshot()


async def test_official_pin_supports_full_bounded_name_and_version_ref(tmp_path):
    namespace = "n" * 180
    version = "v" * 100
    store = _store(tmp_path)

    result = await sync_official_mcp_registry(
        store,
        fetch_page=_one_page_fetcher(
            _mcp_response(f"{namespace}/server", version, latest=True)
        ),
    )

    assert result.success is True
    assert len(store.list()[0].immutable_ref) > 256


async def test_partial_paginated_failure_does_not_publish_a_partial_snapshot(tmp_path):
    store = _store(tmp_path)
    calls = 0

    async def fetch_page(**kwargs):
        nonlocal calls
        calls += 1
        if kwargs["cursor"] is None:
            return {
                "servers": [_mcp_response("io.example/partial", "1.0.0", latest=True)],
                "metadata": {"count": 1, "nextCursor": "second"},
            }
        raise RuntimeError("second page failed with token=secret-value-canary")

    result = await sync_official_mcp_registry(store, fetch_page=fetch_page)

    assert calls == 2
    assert result.success is False
    assert store.list() == ()
    assert "secret-value-canary" not in store.path.read_text(encoding="utf-8")


def test_catalog_rejects_symlink_backed_state(tmp_path):
    store = _store(tmp_path)
    store.root.mkdir(parents=True)
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    store.path.symlink_to(target)

    with pytest.raises(CatalogStateError, match="symlink"):
        store.snapshot()


def _store(tmp_path) -> IntegrationCatalogStore:
    return IntegrationCatalogStore(tmp_path, now=lambda: _NOW)


def _one_page_fetcher(*responses):
    async def fetch_page(**kwargs):
        assert kwargs["cursor"] is None
        assert kwargs["include_deleted"] is True
        return {
            "servers": list(responses),
            "metadata": {"count": len(responses)},
        }

    return fetch_page


def _mcp_response(
    name: str,
    version: str,
    *,
    latest: bool,
    status: str = "active",
    description: str = "Fixture MCP server.",
):
    return {
        "server": {
            "$schema": (
                "https://static.modelcontextprotocol.io/schemas/"
                "2025-12-11/server.schema.json"
            ),
            "name": name,
            "title": name.rsplit("/", 1)[-1].title(),
            "description": description,
            "version": version,
        },
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "status": status,
                "isLatest": latest,
                "publishedAt": "2026-07-19T08:00:00Z",
                "updatedAt": "2026-07-19T08:00:00Z",
            }
        },
    }


def _package(source_type: IntegrationSourceType) -> IntegrationPackage:
    return IntegrationPackage(
        id=f"example.{source_type.value}",
        version="1.0.0",
        publisher="example-publisher",
        license="Apache-2.0",
        source_type=source_type,
        source=f"source:{source_type.value}",
        immutable_ref="commit-deadbeef",
        checksum=_DIGEST,
        components=(
            IntegrationComponent(
                id="portable-mcp",
                type=IntegrationComponentType.MCP,
                portable=True,
            ),
        ),
        requirements=(),
        overlays=(),
        compatibility=(),
        scopes=(InstallationScope.MANAGED_HOME,),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("manifest-check",),
        rollback_steps=("remove-catalog-entry",),
    )
