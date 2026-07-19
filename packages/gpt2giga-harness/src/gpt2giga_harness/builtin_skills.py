"""First-party portable skills and their approval-gated installation handoff."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gpt2giga_harness.integration_catalog import (
    CatalogEntry,
    CatalogSourceType,
    IntegrationCatalogStore,
)
from gpt2giga_harness.integration_installer import InstallationRequest
from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationCompatibility,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationSourceType,
    IntegrationTargetOverlay,
    IntegrationTrustEvidence,
    IntegrationTrustKind,
    IntegrationTrustStatus,
    IntegrationUpdatePolicy,
)
from gpt2giga_harness.portable_skills import (
    CLAUDE_SKILL_TARGET_ID,
    CODEX_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
    GeneratedSkillPackage,
    PortableSkill,
    PortableSkillFile,
    SkillCapabilitySnapshot,
    SkillMetadataField,
    SkillTargetOverlay,
    build_skill_installation_request,
    generate_skill_package,
    portable_skill_semantic_hash,
)


BUILTIN_SKILL_SOURCE_ID = "gpt2giga-first-party"
BUILTIN_SKILL_VERSION = "1.0.0"
_TARGET_IDS = (
    CODEX_SKILL_TARGET_ID,
    CLAUDE_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
)


@dataclass(frozen=True)
class BuiltinSkillBundle:
    """One immutable first-party skill and its catalog manifest."""

    skill: PortableSkill
    package: IntegrationPackage

    def __post_init__(self) -> None:
        component = next(
            (
                item
                for item in self.package.components
                if item.id == self.skill.component_id
            ),
            None,
        )
        if (
            component is None
            or component.type is not IntegrationComponentType.SKILL
            or not component.portable
        ):
            raise ValueError("builtin package does not contain its portable skill")
        expected_checksum = f"sha256:{portable_skill_semantic_hash(self.skill)}"
        if self.package.checksum != expected_checksum:
            raise ValueError("builtin package checksum does not match its skill")


def builtin_skill_bundles() -> tuple[BuiltinSkillBundle, ...]:
    """Return the deterministic first-party starter pack."""
    return _BUILTIN_SKILLS


def get_builtin_skill_bundle(package_id: str) -> BuiltinSkillBundle:
    """Return one first-party bundle by immutable package identity."""
    try:
        return next(item for item in _BUILTIN_SKILLS if item.package.id == package_id)
    except StopIteration as exc:
        raise ValueError("unknown builtin skill package") from exc


def import_builtin_skills(
    store: IntegrationCatalogStore,
) -> tuple[CatalogEntry, ...]:
    """Seed the offline catalog without granting installation authority."""
    if not isinstance(store, IntegrationCatalogStore):
        raise TypeError("builtin skill import requires an IntegrationCatalogStore")
    existing = {
        (item.source_id, item.package_id, item.version): item for item in store.list()
    }
    imported: list[CatalogEntry] = []
    for bundle in _BUILTIN_SKILLS:
        key = (BUILTIN_SKILL_SOURCE_ID, bundle.package.id, bundle.package.version)
        current = existing.get(key)
        if current is not None and current.package == bundle.package:
            imported.append(current)
            continue
        imported.append(
            store.import_package(
                bundle.package,
                source_id=BUILTIN_SKILL_SOURCE_ID,
                source_type=CatalogSourceType.LOCAL_PRIVATE,
            )
        )
    return tuple(imported)


def build_builtin_skill_installation_request(
    entry: CatalogEntry,
    capability: SkillCapabilitySnapshot,
    *,
    scope: InstallationScope,
    root: str | Path,
) -> tuple[InstallationRequest, GeneratedSkillPackage]:
    """Create an N4-02 handoff bound to one exact first-party catalog entry."""
    if (
        not isinstance(entry, CatalogEntry)
        or entry.source_id != BUILTIN_SKILL_SOURCE_ID
        or entry.source_type is not CatalogSourceType.LOCAL_PRIVATE
        or entry.package is None
    ):
        raise ValueError("builtin install handoff requires the first-party source")
    bundle = get_builtin_skill_bundle(entry.package_id)
    if entry.package != bundle.package:
        raise ValueError("builtin catalog entry does not match the shipped package")
    generated = generate_skill_package(bundle.skill, capability)
    request = build_skill_installation_request(
        bundle.package,
        bundle.skill,
        generated,
        scope=scope,
        root=root,
    )
    return request, generated


def _bundle(skill: PortableSkill) -> BuiltinSkillBundle:
    package_id = f"gpt2giga.builtin.{skill.name}"
    package = IntegrationPackage(
        id=package_id,
        version=BUILTIN_SKILL_VERSION,
        publisher="gpt2giga",
        license="MIT",
        source_type=IntegrationSourceType.CURATED_CATALOG,
        source=f"builtin://gpt2giga-harness/skills/{skill.name}",
        immutable_ref=f"builtin:{skill.name}:{BUILTIN_SKILL_VERSION}",
        checksum=f"sha256:{portable_skill_semantic_hash(skill)}",
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
            for target_id in _TARGET_IDS
        ),
        compatibility=tuple(
            IntegrationCompatibility(
                target_id=target_id,
                required_capabilities=("skill.discovery",),
            )
            for target_id in _TARGET_IDS
        ),
        scopes=(InstallationScope.MANAGED_HOME, InstallationScope.PROJECT),
        update_policy=IntegrationUpdatePolicy.MANUAL_REVIEW,
        verification_steps=("skill-discovery",),
        rollback_steps=("restore-snapshot",),
        trust_evidence=tuple(
            IntegrationTrustEvidence(
                id=f"builtin-{skill.name}-{kind.value}",
                kind=kind,
                status=IntegrationTrustStatus.VERIFIED,
                authority="gpt2giga",
                revision=f"builtin-{BUILTIN_SKILL_VERSION}",
            )
            for kind in (
                IntegrationTrustKind.SOURCE,
                IntegrationTrustKind.PUBLISHER,
                IntegrationTrustKind.LICENSE,
            )
        ),
    )
    return BuiltinSkillBundle(skill=skill, package=package)


def _overlays(display_name: str) -> tuple[SkillTargetOverlay, ...]:
    return (
        SkillTargetOverlay(
            target_id=CODEX_SKILL_TARGET_ID,
            fields=(
                SkillMetadataField(
                    "interface",
                    {"display_name": display_name},
                ),
            ),
        ),
        SkillTargetOverlay(
            target_id=CLAUDE_SKILL_TARGET_ID,
            fields=(SkillMetadataField("user-invocable", True),),
        ),
    )


_FIND_SKILLS = PortableSkill(
    component_id="find-skills-skill",
    name="find-skills",
    description=(
        "Discover reviewed agent skills and prepare an approval-gated install "
        "candidate when the user wants to extend the workbench."
    ),
    instructions="""Help the user discover a suitable agent skill.

1. Clarify the capability, workflow, and target agent they need.
2. Search the local cached integration catalog first. Prefer exact capability matches and explain why each result is relevant.
3. Treat publisher reputation, usage, stars, scans, and signatures as trust signals only. A candidate is not installation authority.
4. If no cached result fits, propose a reviewed external catalog or immutable source lookup. Do not run a native package manager, clone a repository, or write an agent home.
5. Present the selected package identity, immutable reference, checksum, target, scope, declared effects, compatibility, and trust diagnostics.
6. Ask the workbench to create its normal transactional preview. Installation requires the application's explicit approval flow.

If no credible result exists, say so and suggest creating a portable skill instead.""",
    files=(
        PortableSkillFile(
            relative_path="references/catalog-safety.md",
            content=b"""# Catalog safety

- Catalog presence and popularity never authorize installation.
- Require an immutable package reference and checksum.
- Keep target, scope, permissions, commands, hooks, files, and network effects visible.
- Hand mutation to the workbench transactional preview and approval boundary.
""",
        ),
    ),
    overlays=_overlays("Find skills"),
)


_SKILL_CREATOR = PortableSkill(
    component_id="skill-creator-skill",
    name="skill-creator",
    description=(
        "Create or revise concise provider-neutral agent skills with explicit "
        "resources, target overlays, validation, and handoff boundaries."
    ),
    instructions="""Create or update one portable agent skill.

1. Establish concrete trigger examples and the smallest reusable workflow.
2. Keep the portable core in `SKILL.md`: a lowercase hyphenated name, a precise third-person description, and imperative instructions.
3. Add only resources that improve repeatability: deterministic scripts, focused references, or reusable assets. Keep reference depth shallow and remove placeholders.
4. Keep Codex, Claude, and Gemini metadata in explicit target overlays. Never hide an unsupported field or claim unsupported activation.
5. Validate schema, paths, size bounds, duplicate files, metadata shapes, secrets, and target compatibility. Exercise representative examples when practical.
6. Return the immutable candidate content and validation results. Do not install or publish it; hand any requested installation to the workbench preview and approval flow.

Read `references/portable-skill-contract.md` before final validation.""",
    files=(
        PortableSkillFile(
            relative_path="references/portable-skill-contract.md",
            content=b"""# Portable skill contract

## Required core

- `SKILL.md` frontmatter contains only `name` and `description`.
- The name is lowercase, hyphenated, and at most 64 characters.
- The description states both capability and triggering context.
- Instructions are imperative, concise, and self-contained.

## Optional resources

- `scripts/` contains deterministic executable helpers.
- `references/` contains material loaded only when needed.
- `assets/` contains output resources, not hidden instructions.

## Delivery boundary

Provider metadata stays in target overlays. A valid candidate still requires an immutable package, compatibility probe, transactional preview, explicit approval, verification, and reversible installation.
""",
        ),
    ),
    overlays=_overlays("Create a skill"),
)


_SKILL_INSTALLER = PortableSkill(
    component_id="skill-installer-skill",
    name="skill-installer",
    description=(
        "Prepare and supervise an approval-gated agent skill installation from "
        "an exact reviewed catalog entry."
    ),
    instructions="""Prepare one agent skill installation through the workbench-owned transaction boundary.

1. Require an exact cached catalog entry with package identity, immutable reference, checksum, and source provenance.
2. Confirm the selected target currently advertises skill discovery and that the requested managed-home or project scope is supported and explicitly admitted.
3. Show the generated file set, declared effects, compatibility, trust diagnostics, activation ownership, verification, and rollback behavior.
4. Treat catalog presence, first-party origin, and trust evidence as review inputs only. None of them grants installation authority.
5. Ask the workbench to create an exact transactional preview, then obtain approval through the application-owned approval flow.
6. After the application applies the plan, report exact discovery and verification state. If verification fails, use the recorded transactional rollback.

Never download or clone sources, invoke a package manager, bypass native consent, or write a provider home directly. Read `references/installation-boundary.md` when explaining why a request is blocked.""",
    files=(
        PortableSkillFile(
            relative_path="references/installation-boundary.md",
            content=b"""# Installation boundary

The skill may prepare a candidate and explain a preview. Only the workbench installer may mutate an admitted root after exact-plan approval.

The installer owns atomic writes, stale-preview rejection, symlink and traversal defense, discovery, verification, journals, and rollback. Catalog entries and trust assessments always retain `install_authorized=false`.
""",
        ),
    ),
    overlays=_overlays("Install a skill"),
)


_BUILTIN_SKILLS = tuple(
    sorted(
        (
            _bundle(_FIND_SKILLS),
            _bundle(_SKILL_CREATOR),
            _bundle(_SKILL_INSTALLER),
        ),
        key=lambda item: item.skill.name,
    )
)
