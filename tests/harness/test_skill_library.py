from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.federated_catalog import (
    FederatedCatalogCandidate,
    FederatedCatalogComponent,
    FederatedProvenance,
    FederatedSourceDescriptor,
    FederatedSourceKind,
    FederatedTrustProjection,
)
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.skill_library import GitCommandResult, SkillLibraryService
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
                ),
                trust=FederatedTrustProjection(
                    source_present=True,
                    curated=False,
                    popularity=42,
                    upstream_audit=None,
                ),
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

    assert inventory.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["markdown"] == _SKILL
    assert search.status_code == 200
    assert search.json()["sources"] == [
        {"id": "skills-sh", "status": "ready", "error_type": None}
    ]
    assert search.json()["items"][0]["artifact_url"] == (
        "https://github.com/acme/skills"
    )
    assert search.json()["items"][0]["install_authorized"] is False
