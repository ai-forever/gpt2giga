from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

import pytest

from gpt2giga_harness.claude_mcp_target import CLAUDE_MCP_TARGET_ID
from gpt2giga_harness.codex_mcp_target import CODEX_MCP_TARGET_ID
from gpt2giga_harness.external_mcp import (
    HARNESS_MANAGED_MCP_TARGET_ID,
    ExternalMCPArtifactResolution,
    ExternalMCPSelection,
    ExternalMCPSelectionKind,
    ExternalMCPToolPolicy,
    external_mcp_descriptor_to_dict,
    normalize_external_mcp_candidate,
    project_external_mcp_target,
)
from gpt2giga_harness.gemini_mcp_target import GEMINI_MCP_TARGET_ID
from gpt2giga_harness.integration_catalog import (
    CatalogEntry,
    CatalogEntryStatus,
    CatalogSourceType,
    FederatedCatalogMetadata,
    IntegrationCatalogStore,
    sync_official_mcp_registry,
)
from gpt2giga_harness.integration_packages import (
    IntegrationRequirementType,
    assess_integration_package,
)
from gpt2giga_harness.managed_mcp import HeadlessManagedMCPSnapshotStore
from gpt2giga_harness.mcp import MCPTransport
from gpt2giga_harness.secrets import SecretReference, SecretReferenceKind
from gpt2giga_harness.tools import PolicyDecision


_NOW = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
_DIGEST = "sha256:" + "a" * 64
_SECOND_DIGEST = "sha256:" + "b" * 64


async def test_package_pin_projects_deterministically_to_all_targets_and_snapshot(
    tmp_path,
):
    official = await _official_entry(tmp_path, _package_server())
    discovery = _discovery_entry(official.package_id)
    secret = SecretReference(
        kind=SecretReferenceKind.ENVIRONMENT,
        name="SERVICE_TOKEN",
    )
    selection = ExternalMCPSelection(
        kind=ExternalMCPSelectionKind.PACKAGE,
        artifact=ExternalMCPArtifactResolution(
            registry_type="npm",
            identifier="@acme/tools-mcp",
            version="1.2.3",
            immutable_ref="npm:@acme/tools-mcp@1.2.3",
            integrity=_DIGEST,
            download_origin="https://registry.npmjs.org",
        ),
        launch_argv=(
            "/managed/artifacts/npm/acme-tools-mcp/1.2.3/bin/tools-mcp",
            "--stdio",
        ),
        environment={"SERVICE_TOKEN": secret},
        timeout_seconds=30,
    )

    descriptor = normalize_external_mcp_candidate(
        official,
        selection,
        discovery_entry=discovery,
    )
    serialized = external_mcp_descriptor_to_dict(descriptor)

    assert descriptor.official_name == "io.example/tools"
    assert descriptor.discovery_source_id == "neuraldeep"
    assert descriptor.transport is MCPTransport.STDIO
    assert descriptor.command == (
        "/managed/artifacts/npm/acme-tools-mcp/1.2.3/bin/tools-mcp"
    )
    assert serialized["environment"]["SERVICE_TOKEN"]["name"] == "SERVICE_TOKEN"
    assert "secret-value-canary" not in json.dumps(serialized)
    package = descriptor.to_integration_package()
    assert package.immutable_ref == "npm:@acme/tools-mcp@1.2.3"
    assert {item.type for item in package.requirements} == {
        IntegrationRequirementType.COMMAND,
        IntegrationRequirementType.NETWORK,
        IntegrationRequirementType.PACKAGE,
        IntegrationRequirementType.PERMISSION,
        IntegrationRequirementType.SECRET,
    }
    assert assess_integration_package(package).install_authorized is False

    for target_id in (
        CODEX_MCP_TARGET_ID,
        CLAUDE_MCP_TARGET_ID,
        GEMINI_MCP_TARGET_ID,
        HARNESS_MANAGED_MCP_TARGET_ID,
    ):
        first = project_external_mcp_target(descriptor, target_id)
        second = project_external_mcp_target(descriptor, target_id)
        assert first == second
        assert first.supported is True
        assert first.install_authorized is False
        assert first.commands == (
            (
                "/managed/artifacts/npm/acme-tools-mcp/1.2.3/bin/tools-mcp",
                "--stdio",
            ),
        )
        assert first.packages[0]["integrity"] == _DIGEST
        assert first.network_origins == ("https://registry.npmjs.org",)
        assert "managed-configuration" in first.filesystem_permissions[-1]
        assert first.secret_references[0]["reference"]["name"] == "SERVICE_TOKEN"

    harness_descriptor = descriptor.to_harness_descriptor(trusted=True, enabled=True)
    snapshot = HeadlessManagedMCPSnapshotStore(tmp_path / "snapshots").create(
        project_id="proj_one",
        harness_id="codex-cli",
        descriptors=(harness_descriptor,),
        server_ids=(descriptor.id,),
    )
    assert snapshot.server_ids == (descriptor.id,)
    assert (
        snapshot.descriptors[0]["environment"]["SERVICE_TOKEN"]["secret_ref"]["name"]
        == "SERVICE_TOKEN"
    )


async def test_streamable_http_keeps_exact_origin_and_fails_tool_policy_per_target(
    tmp_path,
):
    official = await _official_entry(tmp_path, _remote_server())
    selection = ExternalMCPSelection(
        kind=ExternalMCPSelectionKind.REMOTE,
        headers={
            "Authorization": SecretReference(
                kind=SecretReferenceKind.ENVIRONMENT,
                name="REMOTE_MCP_TOKEN",
            )
        },
        tool_policy=ExternalMCPToolPolicy(
            include_tools=("read_records",),
            default=PolicyDecision.ALLOW,
        ),
    )

    descriptor = normalize_external_mcp_candidate(official, selection)

    assert descriptor.transport is MCPTransport.STREAMABLE_HTTP
    assert descriptor.url == "https://mcp.example.com/v1"
    assert descriptor.network_origins == ("https://mcp.example.com",)
    codex = project_external_mcp_target(descriptor, CODEX_MCP_TARGET_ID)
    claude = project_external_mcp_target(descriptor, CLAUDE_MCP_TARGET_ID)
    gemini = project_external_mcp_target(descriptor, GEMINI_MCP_TARGET_ID)
    harness = project_external_mcp_target(descriptor, HARNESS_MANAGED_MCP_TARGET_ID)

    assert codex.supported is True
    assert codex.configuration["transport"] == "streamable_http"
    assert gemini.supported is False
    assert gemini.error_code == "target.default_policy_unsupported"
    assert harness.supported is True
    assert harness.configuration["transport"] == "streamable_http"
    assert claude.supported is False
    assert claude.error_code == "target.tool_policy_unsupported"
    assert claude.configuration == {}
    assert all(item.commands == () for item in (codex, claude, gemini, harness))


async def test_native_targets_reject_secret_alias_without_blocking_harness(tmp_path):
    official = await _official_entry(tmp_path, _package_server())
    descriptor = normalize_external_mcp_candidate(
        official,
        ExternalMCPSelection(
            kind=ExternalMCPSelectionKind.PACKAGE,
            artifact=ExternalMCPArtifactResolution(
                registry_type="npm",
                identifier="@acme/tools-mcp",
                version="1.2.3",
                immutable_ref="npm:@acme/tools-mcp@1.2.3",
                integrity=_DIGEST,
                download_origin="https://registry.npmjs.org",
            ),
            launch_argv=("/managed/artifacts/npm/acme-tools-mcp/1.2.3/bin/tools-mcp",),
            environment={
                "SERVICE_TOKEN": SecretReference(
                    kind=SecretReferenceKind.ENVIRONMENT,
                    name="DIFFERENT_TOKEN",
                )
            },
        ),
    )

    assert (
        project_external_mcp_target(descriptor, CODEX_MCP_TARGET_ID).error_code
        == "target.environment_alias_unsupported"
    )
    assert (
        project_external_mcp_target(descriptor, HARNESS_MANAGED_MCP_TARGET_ID).supported
        is True
    )


async def test_reviewed_git_resolution_uses_official_repository_identity(tmp_path):
    official = await _official_entry(tmp_path, _git_server())
    selection = ExternalMCPSelection(
        kind=ExternalMCPSelectionKind.GIT,
        artifact=ExternalMCPArtifactResolution(
            registry_type="git",
            identifier="https://github.com/acme/tools.git",
            version="1.2.3",
            immutable_ref="commit-" + "d" * 40,
            integrity=_SECOND_DIGEST,
            download_origin="https://github.com",
        ),
        launch_argv=("/managed/artifacts/git/acme-tools/1.2.3/bin/tools-mcp",),
    )

    descriptor = normalize_external_mcp_candidate(official, selection)

    assert descriptor.artifact.registry_type == "git"
    assert descriptor.to_integration_package().source_type.value == "git"
    assert (
        project_external_mcp_target(descriptor, CODEX_MCP_TARGET_ID).supported is True
    )


@pytest.mark.parametrize(
    ("artifact", "message"),
    [
        (
            {
                "registry_type": "npm",
                "identifier": "@acme/tools-mcp",
                "version": "latest",
                "immutable_ref": "latest",
                "integrity": _DIGEST,
                "download_origin": "https://registry.npmjs.org",
            },
            "version must be exact",
        ),
        (
            {
                "registry_type": "npm",
                "identifier": "@acme/tools-mcp",
                "version": "1.2.3",
                "immutable_ref": "npm:@acme/tools-mcp@1.2.3",
                "integrity": "sha512:not-admitted",
                "download_origin": "https://registry.npmjs.org",
            },
            "requires SHA-256 integrity",
        ),
    ],
)
def test_artifact_resolution_rejects_mutable_or_unverified_inputs(artifact, message):
    with pytest.raises(ValueError, match=message):
        ExternalMCPArtifactResolution(**artifact)


def test_selection_rejects_shell_command_strings():
    artifact = ExternalMCPArtifactResolution(
        registry_type="npm",
        identifier="@acme/tools-mcp",
        version="1.2.3",
        immutable_ref="npm:@acme/tools-mcp@1.2.3",
        integrity=_DIGEST,
        download_origin="https://registry.npmjs.org",
    )

    with pytest.raises(ValueError, match="shell command strings are forbidden"):
        ExternalMCPSelection(
            kind=ExternalMCPSelectionKind.PACKAGE,
            artifact=artifact,
            launch_argv=("sh", "-c", "npx @acme/tools-mcp@1.2.3"),
        )

    with pytest.raises(ValueError, match="implicit installer commands are forbidden"):
        ExternalMCPSelection(
            kind=ExternalMCPSelectionKind.PACKAGE,
            artifact=artifact,
            launch_argv=("npx", "--yes", "@acme/tools-mcp@1.2.3"),
        )


async def test_normalization_rejects_integrity_drift_and_non_https_remote(tmp_path):
    official = await _official_entry(
        tmp_path / "package",
        _package_server(file_sha256="b" * 64),
    )
    selection = ExternalMCPSelection(
        kind=ExternalMCPSelectionKind.PACKAGE,
        artifact=ExternalMCPArtifactResolution(
            registry_type="npm",
            identifier="@acme/tools-mcp",
            version="1.2.3",
            immutable_ref="npm:@acme/tools-mcp@1.2.3",
            integrity=_DIGEST,
            download_origin="https://registry.npmjs.org",
        ),
        launch_argv=("/managed/artifacts/npm/acme-tools-mcp/1.2.3/bin/tools-mcp",),
        environment={
            "SERVICE_TOKEN": SecretReference(
                kind=SecretReferenceKind.ENVIRONMENT,
                name="SERVICE_TOKEN",
            )
        },
    )
    with pytest.raises(ValueError, match="integrity conflicts"):
        normalize_external_mcp_candidate(official, selection)

    remote = await _official_entry(tmp_path / "remote", _remote_server(http=True))
    with pytest.raises(ValueError, match="canonical HTTPS"):
        normalize_external_mcp_candidate(
            remote,
            ExternalMCPSelection(
                kind=ExternalMCPSelectionKind.REMOTE,
                headers={
                    "Authorization": SecretReference(
                        kind=SecretReferenceKind.ENVIRONMENT,
                        name="REMOTE_MCP_TOKEN",
                    )
                },
            ),
        )


async def test_discovery_card_cannot_replace_official_identity(tmp_path):
    official = await _official_entry(tmp_path, _remote_server())
    selection = ExternalMCPSelection(
        kind=ExternalMCPSelectionKind.REMOTE,
        headers={
            "Authorization": SecretReference(
                kind=SecretReferenceKind.ENVIRONMENT,
                name="REMOTE_MCP_TOKEN",
            )
        },
    )

    with pytest.raises(ValueError, match="does not match official pin"):
        normalize_external_mcp_candidate(
            official,
            selection,
            discovery_entry=_discovery_entry("io.example/other"),
        )


async def _official_entry(tmp_path, server):
    store = IntegrationCatalogStore(tmp_path, now=lambda: _NOW)

    async def fetch_page(**_kwargs):
        return {
            "servers": [{"server": server, "_meta": _official_metadata()}],
            "metadata": {"count": 1},
        }

    result = await sync_official_mcp_registry(store, fetch_page=fetch_page)
    assert result.success is True
    return next(item for item in store.list() if item.mcp_response is not None)


def _package_server(*, file_sha256=None):
    package = {
        "registryType": "npm",
        "identifier": "@acme/tools-mcp",
        "version": "1.2.3",
        "transport": {"type": "stdio"},
        "environmentVariables": [
            {
                "name": "SERVICE_TOKEN",
                "isRequired": True,
                "isSecret": True,
            }
        ],
    }
    if file_sha256 is not None:
        package["fileSha256"] = file_sha256
    return {
        "$schema": (
            "https://static.modelcontextprotocol.io/schemas/"
            "2025-12-11/server.schema.json"
        ),
        "name": "io.example/tools",
        "title": "Tools",
        "description": "Fixture MCP server.",
        "version": "1.2.3",
        "repository": {
            "url": "https://github.com/acme/tools",
            "source": "github",
        },
        "packages": [package],
    }


def _remote_server(*, http=False):
    return {
        "$schema": (
            "https://static.modelcontextprotocol.io/schemas/"
            "2025-12-11/server.schema.json"
        ),
        "name": "io.example/remote-tools",
        "title": "Remote Tools",
        "description": "Remote fixture MCP server.",
        "version": "2.0.0",
        "remotes": [
            {
                "type": "streamable-http",
                "url": (
                    "http://mcp.example.com/v1"
                    if http
                    else "https://mcp.example.com/v1"
                ),
                "headers": [
                    {
                        "name": "Authorization",
                        "isRequired": True,
                        "isSecret": True,
                    }
                ],
            }
        ],
    }


def _git_server():
    server = _package_server()
    server.pop("packages")
    return server


def _official_metadata():
    return {
        "io.modelcontextprotocol.registry/official": {
            "status": "active",
            "isLatest": True,
            "publishedAt": "2026-07-20T09:00:00Z",
            "updatedAt": "2026-07-20T09:00:00Z",
        }
    }


def _discovery_entry(package_id):
    source_id = "neuraldeep"
    version = "discovery"
    catalog_id = _catalog_id(source_id, package_id, version)
    observed_at = "2026-07-20T10:00:00Z"
    metadata = FederatedCatalogMetadata(
        upstream_id="neural-card-1",
        canonical_package_id=package_id,
        name="Localized tools",
        component="mcp",
        canonical_origin="https://neuraldeep.ru",
        detail_url="https://neuraldeep.ru/skapi/skills/neural-card-1",
        artifact_url="https://github.com/acme/tools",
        curated=True,
        popularity=42,
        upstream_audit="reported_reviewed",
        artifact_resolved=False,
        source_present=True,
    )
    return CatalogEntry(
        catalog_id=catalog_id,
        source_id=source_id,
        source_type=CatalogSourceType.FEDERATED_CATALOG,
        package_id=package_id,
        version=version,
        immutable_ref=None,
        content_hash="c" * 64,
        status=CatalogEntryStatus.ACTIVE,
        pinned=False,
        source_present=True,
        install_authorized=False,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
        federated=metadata,
    )


def _catalog_id(source_id, package_id, version):
    digest = hashlib.sha256(
        json.dumps(
            [source_id, package_id, version],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    return f"catalog_{digest[:32]}"
