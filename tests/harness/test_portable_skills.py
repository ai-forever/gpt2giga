from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from gpt2giga_harness.integration_installer import (
    InstallationApproval,
    TransactionalIntegrationInstaller,
)
from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationCompatibility,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationSourceType,
    IntegrationTargetOverlay,
    IntegrationUpdatePolicy,
)
from gpt2giga_harness.portable_skills import (
    CLAUDE_SKILL_TARGET_ID,
    CODEX_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
    GeneratedSkillPackage,
    PortableSkill,
    PortableSkillFile,
    SkillActivationMode,
    SkillCapabilitySnapshot,
    SkillCommandResult,
    SkillDiscoveryStatus,
    SkillMetadataDisposition,
    SkillMetadataField,
    SkillTargetOverlay,
    SkillTargetStatus,
    build_skill_installation_request,
    discover_generated_skill,
    generate_skill_package,
    generated_skill_verifier,
    portable_skill_semantic_hash,
    probe_skill_target,
)


_TARGETS = (
    CODEX_SKILL_TARGET_ID,
    CLAUDE_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
)


def test_capability_probe_advertises_current_documented_skill_surfaces():
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def runner(argv, env, _cwd, _timeout):
        calls.append((argv, dict(env)))
        target = Path(argv[0]).name
        if argv[-1] == "--version":
            versions = {
                "codex": "codex-cli 0.144.5",
                "claude": "2.1.212 (Claude Code)",
                "gemini": "0.46.0",
            }
            return SkillCommandResult(0, versions[target])
        help_text = {
            "codex": "Codex CLI",
            "claude": "Skills still resolve via /skill-name\n--disable-slash-commands",
            "gemini": "gemini skills <command> Manage agent skills",
        }
        return SkillCommandResult(0, help_text[target])

    snapshots = tuple(
        probe_skill_target(target_id, runner=runner) for target_id in _TARGETS
    )

    assert all(item.status is SkillTargetStatus.SUPPORTED for item in snapshots)
    assert all(item.supports_discovery for item in snapshots)
    assert snapshots[-1].discovery_method == "native_cli_list"
    assert snapshots[-1].activation_mode is SkillActivationMode.PROVIDER_CONSENT
    assert len(calls) == 6
    assert all(
        Path(env["HOME"]).name.startswith("gpt2giga-skill-probe-") for _, env in calls
    )


def test_projection_keeps_portable_core_and_reports_unsupported_metadata():
    skill = _skill()
    projections = {
        target_id: generate_skill_package(skill, _capability(target_id))
        for target_id in _TARGETS
    }

    codex = projections[CODEX_SKILL_TARGET_ID]
    claude = projections[CLAUDE_SKILL_TARGET_ID]
    gemini = projections[GEMINI_SKILL_TARGET_ID]
    codex_paths = {item.relative_path for item in codex.files}
    assert ".agents/skills/review-release/SKILL.md" in codex_paths
    assert ".agents/skills/review-release/agents/openai.yaml" in codex_paths
    assert ".agents/skills/review-release/references/checklist.md" in codex_paths
    assert any(
        item.field_name == "allowed-tools"
        and item.disposition is SkillMetadataDisposition.UNSUPPORTED
        for item in codex.metadata
    )
    claude_skill = _file(claude, "SKILL.md").decode()
    assert "allowed-tools:" in claude_skill
    assert "disable-model-invocation: true" in claude_skill
    assert "Review one release candidate." in claude_skill
    assert all(
        item.disposition is SkillMetadataDisposition.APPLIED for item in claude.metadata
    )
    assert _file(gemini, "SKILL.md").decode().startswith("---\ndescription:")
    assert any(
        item.field_name == "activation-policy"
        and item.disposition is SkillMetadataDisposition.UNSUPPORTED
        for item in gemini.metadata
    )
    assert skill.overlays[0].fields


def test_one_portable_skill_installs_and_is_discovered_by_every_supported_target(
    tmp_path,
):
    skill = _skill()
    package = _package(skill)
    roots = tuple(tmp_path / target_id for target_id in _TARGETS)
    installer = TransactionalIntegrationInstaller(
        tmp_path / "state",
        project_roots=roots,
    )

    for target_id, root in zip(_TARGETS, roots, strict=True):
        root.mkdir()
        generated = generate_skill_package(skill, _capability(target_id))
        request = build_skill_installation_request(
            package,
            skill,
            generated,
            scope=InstallationScope.PROJECT,
            root=root,
        )
        plan = installer.preview(request)
        result = installer.apply(
            request,
            plan,
            InstallationApproval(plan_id=plan.plan_id, authority="test-operator"),
            verifier=generated_skill_verifier(generated),
        )

        assert result.status == "committed"
        discovered = discover_generated_skill(generated, root)
        assert discovered.status is SkillDiscoveryStatus.DISCOVERED
        assert discovered.relative_paths == tuple(
            item.relative_path for item in generated.files
        )

    assert len(installer.discover()) == 3
    assert all(item.current for item in installer.discover())


def test_degraded_or_blocked_targets_cannot_be_installed_and_drift_is_visible(
    tmp_path,
):
    skill = _skill()
    package = _package(skill)
    degraded = replace(
        _capability(CODEX_SKILL_TARGET_ID),
        status=SkillTargetStatus.DEGRADED,
        supports_discovery=False,
        supports_activation=False,
        reason_code="skill_surface_not_advertised",
    )
    generated = generate_skill_package(skill, degraded)

    with pytest.raises(ValueError, match="not supported"):
        build_skill_installation_request(
            package,
            skill,
            generated,
            scope=InstallationScope.PROJECT,
            root=tmp_path,
        )
    assert (
        discover_generated_skill(generated, tmp_path).status
        is SkillDiscoveryStatus.BLOCKED
    )

    supported = generate_skill_package(skill, _capability(CODEX_SKILL_TARGET_ID))
    for item in supported.files:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(item.content)
    (tmp_path / supported.files[0].relative_path).write_text("drift", encoding="utf-8")

    result = discover_generated_skill(supported, tmp_path)
    assert result.status is SkillDiscoveryStatus.DRIFTED
    assert result.reason_code == "skill_file_drifted"


def test_portable_skill_validation_and_hash_fail_closed():
    skill = _skill()
    package = _package(skill)

    assert portable_skill_semantic_hash(skill) == portable_skill_semantic_hash(
        replace(skill, files=tuple(reversed(skill.files)))
    )
    with pytest.raises(ValueError, match="relative"):
        PortableSkillFile(relative_path="../escape", content=b"no")
    with pytest.raises(ValueError, match="reserved"):
        PortableSkillFile(relative_path="SKILL.md", content=b"no")
    with pytest.raises(ValueError, match="name"):
        replace(skill, name="Bad Skill")
    with pytest.raises(ValueError, match="unique"):
        replace(skill, overlays=(skill.overlays[0], skill.overlays[0]))
    with pytest.raises(ValueError, match="collide"):
        replace(
            skill,
            files=(
                PortableSkillFile(relative_path="scripts", content=b"file"),
                PortableSkillFile(relative_path="scripts/run.sh", content=b"script"),
            ),
        )
    with pytest.raises(ValueError, match="Codex.*mapping"):
        SkillTargetOverlay(
            target_id=CODEX_SKILL_TARGET_ID,
            fields=(SkillMetadataField("interface", "invalid"),),
        )
    with pytest.raises(ValueError, match="Claude.*boolean"):
        SkillTargetOverlay(
            target_id=CLAUDE_SKILL_TARGET_ID,
            fields=(SkillMetadataField("disable-model-invocation", "true"),),
        )

    generated = generate_skill_package(skill, _capability(CODEX_SKILL_TARGET_ID))
    forged = replace(
        generated,
        files=(replace(generated.files[0], content=b"forged"), *generated.files[1:]),
    )
    with pytest.raises(ValueError, match="does not match"):
        build_skill_installation_request(
            package,
            skill,
            forged,
            scope=InstallationScope.PROJECT,
            root=Path("/tmp/forged-skill-root"),
        )


def _skill() -> PortableSkill:
    return PortableSkill(
        component_id="release-review-skill",
        name="review-release",
        description="Review release candidates using one bounded checklist.",
        instructions="Review one release candidate.\n\nRead references/checklist.md first.",
        files=(
            PortableSkillFile(
                relative_path="references/checklist.md",
                content=b"# Checklist\n\n- Verify tests.\n",
            ),
        ),
        overlays=(
            SkillTargetOverlay(
                target_id=CODEX_SKILL_TARGET_ID,
                fields=(
                    SkillMetadataField(
                        "interface",
                        {"display_name": "Release reviewer"},
                    ),
                    SkillMetadataField("allowed-tools", ["Read", "Grep"]),
                ),
            ),
            SkillTargetOverlay(
                target_id=CLAUDE_SKILL_TARGET_ID,
                fields=(
                    SkillMetadataField("allowed-tools", ["Read", "Grep"]),
                    SkillMetadataField("disable-model-invocation", True),
                ),
            ),
            SkillTargetOverlay(
                target_id=GEMINI_SKILL_TARGET_ID,
                fields=(SkillMetadataField("activation-policy", "reviewed"),),
            ),
        ),
    )


def _capability(target_id: str) -> SkillCapabilitySnapshot:
    return SkillCapabilitySnapshot(
        target_id=target_id,
        status=SkillTargetStatus.SUPPORTED,
        version={
            CODEX_SKILL_TARGET_ID: "0.144.5",
            CLAUDE_SKILL_TARGET_ID: "2.1.212",
            GEMINI_SKILL_TARGET_ID: "0.46.0",
        }[target_id],
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


def _package(skill: PortableSkill) -> IntegrationPackage:
    return IntegrationPackage(
        id="example.release-review",
        version="1.0.0",
        publisher="example",
        license="Apache-2.0",
        source_type=IntegrationSourceType.GIT,
        source="https://example.invalid/release-review",
        immutable_ref="commit-deadbeef",
        checksum="sha256:" + "a" * 64,
        components=(
            IntegrationComponent(
                id=skill.component_id,
                type=IntegrationComponentType.SKILL,
                portable=True,
            ),
        ),
        requirements=(),
        overlays=tuple(
            IntegrationTargetOverlay(
                target_id=target_id,
                component_ids=(skill.component_id,),
            )
            for target_id in _TARGETS
        ),
        compatibility=tuple(
            IntegrationCompatibility(
                target_id=target_id,
                required_capabilities=("skill.discovery",),
            )
            for target_id in _TARGETS
        ),
        scopes=(InstallationScope.PROJECT,),
        update_policy=IntegrationUpdatePolicy.MANUAL_REVIEW,
        verification_steps=("skill-discovery",),
        rollback_steps=("restore-snapshot",),
    )


def _file(package: GeneratedSkillPackage, suffix: str) -> bytes:
    return next(
        item.content for item in package.files if item.relative_path.endswith(suffix)
    )
