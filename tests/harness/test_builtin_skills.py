from __future__ import annotations

from dataclasses import replace

import pytest

from gpt2giga_harness.builtin_skills import (
    BUILTIN_SKILL_SOURCE_ID,
    build_builtin_skill_installation_request,
    builtin_skill_bundles,
    get_builtin_skill_bundle,
    import_builtin_skills,
)
from gpt2giga_harness.integration_catalog import CatalogSourceType
from gpt2giga_harness.integration_installer import (
    InstallationApproval,
    TransactionalIntegrationInstaller,
)
from gpt2giga_harness.integration_packages import InstallationScope
from gpt2giga_harness.integration_packages import IntegrationTrustDecision
from gpt2giga_harness.portable_skills import (
    CLAUDE_SKILL_TARGET_ID,
    CODEX_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
    SkillActivationMode,
    SkillCapabilitySnapshot,
    SkillDiscoveryStatus,
    SkillTargetStatus,
    discover_generated_skill,
    generated_skill_verifier,
)


_TARGETS = (
    CODEX_SKILL_TARGET_ID,
    CLAUDE_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
)


def test_builtin_starter_pack_is_deterministic_and_safe_by_construction():
    bundles = builtin_skill_bundles()

    assert tuple(item.skill.name for item in bundles) == (
        "find-skills",
        "skill-creator",
        "skill-installer",
    )
    assert bundles == builtin_skill_bundles()
    assert all(item.package.publisher == "gpt2giga" for item in bundles)
    assert all(item.package.requirements == () for item in bundles)
    assert all(
        set(item.package.scopes)
        == {InstallationScope.MANAGED_HOME, InstallationScope.PROJECT}
        for item in bundles
    )
    assert all(
        compatibility.required_capabilities == ("skill.discovery",)
        for item in bundles
        for compatibility in item.package.compatibility
    )

    find_skills = get_builtin_skill_bundle("gpt2giga.builtin.find-skills").skill
    assert "local cached integration catalog" in find_skills.instructions
    assert "candidate is not installation authority" in find_skills.instructions
    assert "npx skills add" not in find_skills.instructions
    assert "git clone" not in find_skills.instructions

    creator = get_builtin_skill_bundle("gpt2giga.builtin.skill-creator").skill
    assert "Do not install or publish" in creator.instructions
    assert any(
        item.relative_path == "references/portable-skill-contract.md"
        for item in creator.files
    )

    installer = get_builtin_skill_bundle("gpt2giga.builtin.skill-installer").skill
    assert "None of them grants installation authority" in installer.instructions
    assert (
        "Only the workbench installer may mutate" in installer.files[0].content.decode()
    )
    assert "npx skills add" not in installer.instructions
    assert "git clone" not in installer.instructions


def test_builtins_import_into_offline_catalog_without_install_authority(tmp_path):
    from gpt2giga_harness.integration_catalog import IntegrationCatalogStore

    store = IntegrationCatalogStore(tmp_path)
    entries = import_builtin_skills(store)

    assert tuple(item.package_id for item in entries) == (
        "gpt2giga.builtin.find-skills",
        "gpt2giga.builtin.skill-creator",
        "gpt2giga.builtin.skill-installer",
    )
    assert all(item.source_id == BUILTIN_SKILL_SOURCE_ID for item in entries)
    assert all(item.source_type is CatalogSourceType.LOCAL_PRIVATE for item in entries)
    assert all(item.install_authorized is False for item in entries)
    assert all(
        item.trust_decision is IntegrationTrustDecision.REVIEW_REQUIRED
        for item in entries
    )
    assert entries == import_builtin_skills(store)
    assert entries == store.list()


@pytest.mark.parametrize("target_id", _TARGETS)
def test_catalog_entry_hands_off_to_transactional_installer_only(
    tmp_path,
    target_id,
):
    from gpt2giga_harness.integration_catalog import IntegrationCatalogStore

    store = IntegrationCatalogStore(tmp_path / "catalog")
    entry = import_builtin_skills(store)[0]
    root = tmp_path / target_id
    root.mkdir()
    request, generated = build_builtin_skill_installation_request(
        entry,
        _capability(target_id),
        scope=InstallationScope.PROJECT,
        root=root,
    )
    installer = TransactionalIntegrationInstaller(
        tmp_path / "state",
        project_roots=(root,),
    )

    plan = installer.preview(request)
    result = installer.apply(
        request,
        plan,
        InstallationApproval(plan_id=plan.plan_id, authority="test-operator"),
        verifier=generated_skill_verifier(generated),
    )

    assert result.status == "committed"
    assert (
        discover_generated_skill(generated, root).status
        is SkillDiscoveryStatus.DISCOVERED
    )


def test_install_handoff_rejects_unknown_catalog_entries_and_degraded_targets(
    tmp_path,
):
    from gpt2giga_harness.integration_catalog import IntegrationCatalogStore

    store = IntegrationCatalogStore(tmp_path)
    entry = import_builtin_skills(store)[0]
    degraded = replace(
        _capability(CODEX_SKILL_TARGET_ID),
        status=SkillTargetStatus.DEGRADED,
        supports_discovery=False,
        supports_activation=False,
        reason_code="skill_surface_not_advertised",
    )

    with pytest.raises(ValueError, match="not supported"):
        build_builtin_skill_installation_request(
            entry,
            degraded,
            scope=InstallationScope.PROJECT,
            root=tmp_path / "project",
        )

    foreign = store.import_package(
        entry.package,
        source_id="foreign-source",
        source_type=CatalogSourceType.LOCAL_PRIVATE,
    )
    with pytest.raises(ValueError, match="first-party source"):
        build_builtin_skill_installation_request(
            foreign,
            _capability(CODEX_SKILL_TARGET_ID),
            scope=InstallationScope.PROJECT,
            root=tmp_path / "project",
        )


def _capability(target_id: str) -> SkillCapabilitySnapshot:
    return SkillCapabilitySnapshot(
        target_id=target_id,
        status=SkillTargetStatus.SUPPORTED,
        version="test",
        command=(target_id.removesuffix("-skill"),),
        supports_discovery=True,
        supports_activation=True,
        discovery_method=(
            "native_cli_list"
            if target_id == GEMINI_SKILL_TARGET_ID
            else "documented_filesystem"
        ),
        activation_mode=(
            SkillActivationMode.PROVIDER_CONSENT
            if target_id == GEMINI_SKILL_TARGET_ID
            else SkillActivationMode.IMPLICIT_OR_EXPLICIT
        ),
    )
