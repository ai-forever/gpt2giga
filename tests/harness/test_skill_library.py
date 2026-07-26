from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.federated_catalog import (
    FederatedAuditProjection,
    FederatedCatalogCandidate,
    FederatedCatalogComponent,
    FederatedProvenance,
    FederatedSourceDescriptor,
    FederatedSourceKind,
    FederatedTrustProjection,
)
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.skill_library import GitCommandResult, SkillLibraryService
from gpt2giga_harness.integration_flows import IntegrationFlowService
from gpt2giga_harness.portable_skills import (
    SkillActivationMode,
    SkillCapabilitySnapshot,
    SkillTargetStatus,
)
from gpt2giga_harness.ui.app import create_app


_COMMIT = "a" * 40
_SKILL = """---
name: review-pull-request
description: Review one pull request safely.
---

# Review pull request

Inspect the diff before making changes.
"""
_GIT_SKILL = _SKILL.replace(
    "description: Review one pull request safely.\n",
    "description: Review one pull request safely.\nallowed-tools: Read, Grep\n",
)


def _supported_skill(target_id: str) -> SkillCapabilitySnapshot:
    return SkillCapabilitySnapshot(
        target_id=target_id,
        status=SkillTargetStatus.SUPPORTED,
        version="test",
        command=(target_id.removesuffix("-skill"),),
        supports_discovery=True,
        supports_activation=True,
        discovery_method="documented_filesystem",
        activation_mode=SkillActivationMode.IMPLICIT_OR_EXPLICIT,
    )


class _CatalogSource:
    descriptor = FederatedSourceDescriptor(
        source_id="skills-sh",
        kind=FederatedSourceKind.HOSTED_METADATA,
        canonical_origin="https://skills.sh",
        components=(FederatedCatalogComponent.SKILL,),
        hosted_auth_required=True,
        immutable_reference_capable=True,
    )

    async def search(self, query: str, *, limit: int = 50):
        assert query == "review"
        assert limit == 10
        return (
            FederatedCatalogCandidate(
                source_id="skills-sh",
                upstream_id="acme/skills/review",
                name="Review pull request",
                component=FederatedCatalogComponent.SKILL,
                source_present=True,
                immutable_ref="sha256:" + "b" * 64,
                provenance=FederatedProvenance(
                    source_id="skills-sh",
                    upstream_id="acme/skills/review",
                    canonical_origin="https://skills.sh",
                    observed_at="2026-07-20T09:30:00+00:00",
                    detail_url="https://skills.sh/acme/skills/review",
                    artifact_url="https://github.com/acme/skills",
                    artifact_origin="https://github.com",
                    relative_path="review/SKILL.md",
                    file_paths=("review/SKILL.md",),
                ),
                trust=FederatedTrustProjection(
                    source_present=True,
                    curated=False,
                    popularity=42,
                    upstream_audit=None,
                ),
            ),
        )

    async def detail(self, upstream_id: str):
        assert upstream_id == "acme/skills/review"
        return (await self.search("review", limit=10))[0]

    async def audits(self, upstream_id: str):
        assert upstream_id == "acme/skills/review"
        return (
            FederatedAuditProjection(
                provider="Socket",
                status="pass",
                audited_at="2026-07-20T09:35:00Z",
                risk_level="LOW",
            ),
        )


def test_root_skill_inventory_and_preview_merge_harness_targets(tmp_path: Path):
    shared = tmp_path / "shared"
    codex = tmp_path / "codex"
    (shared / "review").mkdir(parents=True)
    (codex / "review").mkdir(parents=True)
    (shared / "review" / "SKILL.md").write_text(_SKILL, encoding="utf-8")
    (codex / "review" / "SKILL.md").write_text(_SKILL, encoding="utf-8")
    service = SkillLibraryService(
        tmp_path / "data",
        root_skill_roots=(
            (shared, ("codex-skill", "claude-skill", "gemini-skill"), "root"),
            (codex, ("codex-skill",), "codex-root"),
        ),
        federated_sources=(),
    )

    inventory = service.root_skills()
    preview = service.preview(inventory[0]["preview_id"])

    assert len(inventory) == 1
    assert inventory[0]["scope"] == "root"
    assert inventory[0]["connected"] is True
    assert inventory[0]["target_ids"] == [
        "claude-skill",
        "codex-skill",
        "gemini-skill",
    ]
    assert preview["markdown"] == _SKILL
    assert preview["target_ids"] == inventory[0]["target_ids"]


def test_root_inventory_skips_invalid_yaml_without_hiding_valid_skills(tmp_path: Path):
    root = tmp_path / "root"
    (root / "broken").mkdir(parents=True)
    (root / "valid").mkdir(parents=True)
    (root / "broken" / "SKILL.md").write_text(
        "---\nname: broken\ndescription: bad: yaml\n---\n", encoding="utf-8"
    )
    (root / "valid" / "SKILL.md").write_text(_SKILL, encoding="utf-8")
    service = SkillLibraryService(
        tmp_path / "data",
        root_skill_roots=((root, ("codex-skill",), "root"),),
        federated_sources=(),
    )

    assert [item["name"] for item in service.root_skills()] == ["review-pull-request"]


def test_root_plugin_inventory_projects_openai_bundles_and_invocation(tmp_path: Path):
    root = tmp_path / "openai-primary-runtime"
    plugin = root / "pdf" / "1.0.0"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / "skills" / "pdf").mkdir(parents=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "pdf",
                "version": "1.0.0",
                "description": "PDF workflows.",
                "repository": "https://github.com/openai/openai",
                "skills": "./skills/",
                "interface": {
                    "displayName": "PDF",
                    "shortDescription": "Read, create, and verify PDF files",
                    "defaultPrompt": [
                        "Review this PDF",
                        "Create a PDF",
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (plugin / "skills" / "pdf" / "SKILL.md").write_text(
        "---\nname: pdf\ndescription: Work with PDF files.\n---\n\nUse PDF tools.\n",
        encoding="utf-8",
    )
    service = SkillLibraryService(
        tmp_path / "data",
        root_skill_roots=(),
        root_plugin_roots=((root, "openai-primary-runtime"),),
        federated_sources=(),
    )

    assert service.root_plugins() == [
        {
            "id": service.root_plugins()[0]["id"],
            "name": "pdf",
            "title": "PDF",
            "description": "Read, create, and verify PDF files",
            "version": "1.0.0",
            "target_ids": ["codex-plugin"],
            "origin": "openai-primary-runtime",
            "source_label": "OpenAI",
            "scope": "system",
            "connected": True,
            "invocation": "@pdf",
            "bundled_skills": ["pdf"],
            "default_prompts": ["Review this PDF", "Create a PDF"],
            "repository_url": "https://github.com/openai/openai",
        }
    ]


async def test_git_inspection_pins_commit_then_imports_reviewed_skill(tmp_path: Path):
    calls: list[tuple[str, ...]] = []

    def git_runner(
        argv: tuple[str, ...], cwd: Path | None, timeout: float
    ) -> GitCommandResult:
        calls.append(argv)
        assert timeout == 90.0
        if argv[:2] == ("git", "clone"):
            repo = Path(argv[-1])
            (repo / "skills" / "review").mkdir(parents=True)
            (repo / "skills" / "review" / "SKILL.md").write_text(
                _GIT_SKILL, encoding="utf-8"
            )
            (repo / "LICENSE").write_text("MIT", encoding="utf-8")
            return GitCommandResult(0, "")
        assert cwd is not None
        return GitCommandResult(0, _COMMIT + "\n")

    service = SkillLibraryService(
        tmp_path / "data",
        root_skill_roots=(),
        federated_sources=(),
        git_runner=git_runner,
    )

    inspection = await service.inspect_git("https://github.com/acme/skills/tree/main")
    candidate = inspection["candidates"][0]
    preview = service.preview(candidate["preview_id"])
    entry = service.import_git_skill(candidate["id"])
    catalog_preview = service.preview(f"catalog:{entry.catalog_id}")

    assert inspection["repository_url"] == "https://github.com/acme/skills.git"
    assert inspection["requested_ref"] == "main"
    assert inspection["commit"] == _COMMIT
    assert candidate["relative_dir"] == "skills/review"
    assert candidate["license"] == "LICENSE"
    assert preview["markdown"] == _GIT_SKILL
    assert entry.package is not None
    assert entry.package.immutable_ref == _COMMIT
    assert entry.package.checksum.startswith("sha256:")
    assert catalog_preview["name"] == "review-pull-request"
    assert "Inspect the diff before making changes." in catalog_preview["markdown"]
    assert "allowed-tools" not in catalog_preview["markdown"]
    assert "--branch" in calls[0] and "main" in calls[0]
    assert calls[0][0:2] == ("git", "clone")
    assert calls[1] == ("git", "rev-parse", "HEAD")


async def test_remote_provenance_survives_git_import_preview_and_receipt(
    tmp_path: Path,
):
    raw_hash = hashlib.sha256(b"SKILL.md\0" + _GIT_SKILL.encode("utf-8")).hexdigest()

    class _BoundSource(_CatalogSource):
        async def detail(self, upstream_id: str):
            candidate = (await self.search("review", limit=10))[0]
            return replace(
                candidate,
                immutable_ref=f"sha256:{raw_hash}",
                provenance=replace(
                    candidate.provenance,
                    relative_path="SKILL.md",
                    file_paths=("SKILL.md",),
                ),
            )

    def git_runner(
        argv: tuple[str, ...], cwd: Path | None, _timeout: float
    ) -> GitCommandResult:
        if argv[:2] == ("git", "clone"):
            repo = Path(argv[-1])
            (repo / "review").mkdir(parents=True)
            (repo / "review" / "SKILL.md").write_text(_GIT_SKILL, encoding="utf-8")
            (repo / "LICENSE").write_text("MIT", encoding="utf-8")
            return GitCommandResult(0, "")
        assert cwd is not None
        return GitCommandResult(0, _COMMIT + "\n")

    data_dir = tmp_path / "data"
    library = SkillLibraryService(
        data_dir,
        root_skill_roots=(),
        federated_sources=(_BoundSource(),),
        git_runner=git_runner,
    )

    inspection = await library.inspect_git(
        "https://github.com/acme/skills",
        source_id="skills-sh",
        upstream_id="acme/skills/review",
    )
    entry = library.import_git_skill(inspection["candidates"][0]["id"])
    service = IntegrationFlowService(
        data_dir,
        skill_capability_provider=_supported_skill,
    )
    preview = service.preview(
        {
            "source": "catalog",
            "catalog_id": entry.catalog_id,
            "target_id": "codex-skill",
            "scope": "managed_home",
        }
    )
    applied = service.apply(
        preview["flow"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
    )

    assert entry.federated is not None
    assert entry.federated.discovery_location == ("skills-sh/acme/skills/review")
    assert preview["plan"]["package"]["source_provenance"]["immutable_ref"] == (
        f"sha256:{raw_hash}"
    )
    assert preview["flow"]["source_provenance"]["canonical_origin"] == (
        "https://skills.sh"
    )
    assert (
        applied["flow"]["source_provenance"] == (preview["flow"]["source_provenance"])
    )


def test_integration_library_api_exposes_root_preview_and_remote_search(tmp_path: Path):
    root = tmp_path / "root"
    (root / "review").mkdir(parents=True)
    (root / "review" / "SKILL.md").write_text(_SKILL, encoding="utf-8")
    library = SkillLibraryService(
        tmp_path / "data",
        root_skill_roots=((root, ("codex-skill",), "root"),),
        federated_sources=(_CatalogSource(),),
    )
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
            skill_library_service=library,
        )
    )

    inventory = client.get("/api/integrations")
    root_skill = inventory.json()["root_skills"][0]
    preview = client.get(
        "/api/integrations/skills/preview",
        params={"preview_id": root_skill["preview_id"]},
    )
    search = client.get(
        "/api/integrations/search",
        params={"q": "review", "component": "skill", "limit": 10},
    )
    detail = client.get(
        "/api/integrations/source-detail",
        params={
            "source_id": "skills-sh",
            "upstream_id": "acme/skills/review",
            "include_audit": True,
        },
    )

    assert inventory.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["markdown"] == _SKILL
    assert search.status_code == 200
    assert search.json()["sources"] == [
        {
            "id": "skills-sh",
            "status": "ready",
            "reason_code": None,
            "cache_status": "live",
            "cache_age_seconds": None,
            "last_good": False,
        }
    ]
    assert search.json()["items"][0]["artifact_url"] == (
        "https://github.com/acme/skills"
    )
    assert search.json()["items"][0]["install_authorized"] is False
    assert detail.status_code == 200
    assert detail.json()["provenance"]["discovery_location"] == (
        "skills-sh/acme/skills/review"
    )
    assert detail.json()["provenance"]["relative_path"] == "review/SKILL.md"
    assert detail.json()["audits"][0]["provider"] == "Socket"
