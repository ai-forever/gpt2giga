from __future__ import annotations

from dataclasses import replace

import pytest

import gpt2giga_harness.integration_packages as integration_module
from gpt2giga_harness.integration_packages import (
    EXTENSION_TARGET_ENTRY_POINTS,
    INTEGRATION_PACKAGE_SCHEMA_VERSION,
    NEUTRAL_EXTENSION_TARGET_ENTRY_POINT_GROUP,
    ExtensionTargetDescriptor,
    ExtensionTargetPlugin,
    ExtensionTargetRegistry,
    InstallationScope,
    IntegrationCompatibility,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationPolicyClass,
    IntegrationRequirement,
    IntegrationRequirementType,
    IntegrationSourceType,
    IntegrationTargetOverlay,
    IntegrationTrustDecision,
    IntegrationTrustEvidence,
    IntegrationTrustKind,
    IntegrationTrustStatus,
    IntegrationUpdatePolicy,
    assess_integration_package,
    integration_package_from_dict,
    integration_package_semantic_hash,
    integration_package_to_dict,
    integration_trust_assessment_to_dict,
)
from gpt2giga_harness.registries import RegistryCollisionError


_DIGEST = "sha256:" + "a" * 64
_ARTIFACT_DIGEST = "sha256:" + "b" * 64


def test_integration_package_round_trip_is_strict_deterministic_and_content_free():
    package = _package()

    payload = integration_package_to_dict(package)
    restored = integration_package_from_dict(payload)

    assert restored == package
    assert payload["schema_version"] == INTEGRATION_PACKAGE_SCHEMA_VERSION
    assert [item["id"] for item in payload["components"]] == [
        "portable-mcp",
        "target-plugin",
    ]
    assert payload["requirements"][0]["argv"] == ["runner", "--mode", "safe"]
    assert payload["requirements"][2]["secret_owner"] == "secret-backend"
    assert "secret-value-canary" not in repr(payload)
    assert integration_package_semantic_hash(restored) == (
        integration_package_semantic_hash(package)
    )


@pytest.mark.parametrize(
    ("patch", "match"),
    [
        ({"schema_version": 2}, "unsupported integration package"),
        ({"unknown": True}, "unknown fields"),
    ],
)
def test_integration_package_rejects_future_and_unknown_contracts(patch, match):
    payload = integration_package_to_dict(_package())
    payload.update(patch)

    with pytest.raises(ValueError, match=match):
        integration_package_from_dict(payload)


def test_integration_package_normalizes_order_without_changing_semantics():
    package = _package()
    reversed_package = replace(
        package,
        components=tuple(reversed(package.components)),
        requirements=tuple(reversed(package.requirements)),
        trust_evidence=tuple(reversed(package.trust_evidence)),
    )

    assert reversed_package == package
    assert integration_package_to_dict(reversed_package) == (
        integration_package_to_dict(package)
    )


@pytest.mark.parametrize(
    "requirement",
    [
        IntegrationRequirement(
            id="invalid-permission",
            type=IntegrationRequirementType.PERMISSION,
            classification=IntegrationPolicyClass.REVIEW_REQUIRED,
            reason="Invalid extra fields.",
        ),
        IntegrationRequirement(
            id="invalid-command",
            type=IntegrationRequirementType.COMMAND,
            classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
            reason="Invalid command shape.",
            argv=("runner",),
        ),
    ],
)
def test_requirement_valid_fixtures_cover_explicit_shapes(requirement):
    assert requirement.id.startswith("invalid-")


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "type": IntegrationRequirementType.SECRET,
            "secret_owner": None,
        },
        {
            "type": IntegrationRequirementType.COMMAND,
            "argv": (),
        },
        {
            "type": IntegrationRequirementType.BINARY,
            "locator": "pkg/bin/tool",
            "checksum": None,
        },
        {
            "type": IntegrationRequirementType.NETWORK,
            "locator": "http://metadata.internal",
        },
        {
            "type": IntegrationRequirementType.PERMISSION,
            "locator": "unexpected",
        },
    ],
)
def test_requirement_shapes_fail_closed(kwargs):
    defaults = {
        "id": "invalid",
        "type": IntegrationRequirementType.PERMISSION,
        "classification": IntegrationPolicyClass.EXPLICIT_APPROVAL,
        "reason": "Rejected fixture.",
    }
    defaults.update(kwargs)

    with pytest.raises(ValueError):
        IntegrationRequirement(**defaults)


def test_package_rejects_missing_overlay_references_and_unpinned_artifacts():
    package = _package()

    with pytest.raises(ValueError, match="unknown component"):
        replace(
            package,
            overlays=(
                IntegrationTargetOverlay(
                    target_id="codex",
                    component_ids=("missing",),
                ),
            ),
        )
    with pytest.raises(ValueError, match="sha256"):
        replace(package, checksum="mutable-tag")


def test_manifest_free_text_rejects_embedded_secret_material():
    package = _package()

    with pytest.raises(ValueError, match="secret material"):
        replace(package, source="https://user:password@catalog.example/package")
    with pytest.raises(ValueError, match="secret material"):
        IntegrationRequirement(
            id="leaking-command",
            type=IntegrationRequirementType.COMMAND,
            classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
            reason="Rejected secret-bearing argv.",
            argv=("runner", "api_key=secret-value-canary"),
        )


def test_target_specific_components_require_an_explicit_compatible_overlay():
    package = _package()

    with pytest.raises(ValueError, match="target-specific"):
        replace(package, overlays=())
    with pytest.raises(ValueError, match="compatibility"):
        replace(package, compatibility=())


def test_trust_assessment_is_content_free_and_never_authorizes_installation():
    package = _package(
        trust_evidence=(
            _trust(IntegrationTrustKind.SOURCE, IntegrationTrustStatus.VERIFIED),
            _trust(IntegrationTrustKind.PUBLISHER, IntegrationTrustStatus.DELEGATED),
            _trust(IntegrationTrustKind.LICENSE, IntegrationTrustStatus.VERIFIED),
            _trust(IntegrationTrustKind.SIGNATURE, IntegrationTrustStatus.UNVERIFIED),
            _trust(IntegrationTrustKind.SCAN, IntegrationTrustStatus.VERIFIED),
        )
    )

    assessment = assess_integration_package(package)
    payload = integration_trust_assessment_to_dict(assessment)

    assert assessment.decision is IntegrationTrustDecision.EXPLICIT_APPROVAL
    assert assessment.install_authorized is False
    assert payload["manifest_hash"] == integration_package_semantic_hash(package)
    assert "secret-value-canary" not in repr(payload)
    assert "https://network.example" not in repr(payload)
    assert "--mode" not in repr(payload)
    assert "Run the reviewed integration entry point" not in repr(payload)
    assert {item["code"] for item in payload["diagnostics"]} >= {
        "scope.user_home.explicit_approval",
        "trust.publisher.delegated",
        "trust.signature.unverified",
    }


def test_forbidden_requirement_or_blocked_evidence_blocks_without_side_effects():
    package = _package(
        requirements=(
            IntegrationRequirement(
                id="unsafe-hook",
                type=IntegrationRequirementType.HOOK,
                classification=IntegrationPolicyClass.FORBIDDEN,
                reason="Unreviewed lifecycle hook.",
                argv=("hook-runner",),
            ),
        ),
        overlays=(
            IntegrationTargetOverlay(
                target_id="codex",
                component_ids=("portable-mcp", "target-plugin"),
                requirement_ids=("unsafe-hook",),
            ),
        ),
        trust_evidence=(
            _trust(IntegrationTrustKind.SIGNATURE, IntegrationTrustStatus.BLOCKED),
        ),
    )

    assessment = assess_integration_package(package)

    assert assessment.decision is IntegrationTrustDecision.BLOCKED
    assert assessment.install_authorized is False
    assert {item.code for item in assessment.diagnostics} >= {
        "requirement.hook.blocked",
        "trust.signature.blocked",
    }


def test_any_blocked_evidence_wins_over_an_independent_verified_claim():
    package = _package(
        trust_evidence=(
            _trust(IntegrationTrustKind.SIGNATURE, IntegrationTrustStatus.VERIFIED),
            replace(
                _trust(IntegrationTrustKind.SIGNATURE, IntegrationTrustStatus.BLOCKED),
                id="second-signature",
            ),
        )
    )

    assessment = assess_integration_package(package)

    assert assessment.decision is IntegrationTrustDecision.BLOCKED
    assert any(
        item.code == "trust.signature.blocked" for item in assessment.diagnostics
    )


def test_missing_trust_evidence_remains_review_required_not_trusted():
    package = _package(requirements=(), trust_evidence=())

    assessment = assess_integration_package(package)

    assert assessment.decision is IntegrationTrustDecision.EXPLICIT_APPROVAL
    assert sum(item.code.endswith(".missing") for item in assessment.diagnostics) == 5


def test_extension_target_entry_points_use_neutral_family_and_registry_kernel(
    monkeypatch,
):
    plugin = _plugin()

    class FakeEntryPoint:
        name = "codex"
        value = f"{__name__}:_plugin"

        def load(self):
            return lambda: plugin

    class FakeEntryPoints:
        def select(self, *, group):
            assert group == NEUTRAL_EXTENSION_TARGET_ENTRY_POINT_GROUP
            return (FakeEntryPoint(),)

    monkeypatch.setattr(
        integration_module,
        "entry_points",
        lambda: FakeEntryPoints(),
    )
    registry = ExtensionTargetRegistry()

    registry.load_entry_points()

    assert EXTENSION_TARGET_ENTRY_POINTS.registry_id == "extension_target"
    assert EXTENSION_TARGET_ENTRY_POINTS.groups == (
        NEUTRAL_EXTENSION_TARGET_ENTRY_POINT_GROUP,
    )
    assert registry.list() == (plugin.descriptor,)
    assert registry.discovery_errors == []
    assert registry.create_driver("codex").descriptor == plugin.descriptor


def test_extension_target_registry_rejects_collisions_and_invalid_drivers():
    registry = ExtensionTargetRegistry()
    plugin = _plugin()
    registry.register(plugin)

    with pytest.raises(RegistryCollisionError):
        registry.register(
            replace(
                plugin,
                descriptor=replace(plugin.descriptor, revision="2"),
            )
        )
    with pytest.raises(TypeError, match="invalid driver"):
        ExtensionTargetRegistryWithInvalidDriver().create_driver("codex")


def test_extension_target_discovery_errors_are_bounded_and_redacted(monkeypatch):
    class BrokenEntryPoint:
        value = "target_plugin:factory"

        def __init__(self, index):
            self.name = f"broken-{index}"

        def load(self):
            raise ValueError("api_key=secret-value-canary")

    class FakeEntryPoints:
        def select(self, *, group):
            assert group == NEUTRAL_EXTENSION_TARGET_ENTRY_POINT_GROUP
            return tuple(BrokenEntryPoint(index) for index in range(25))

    monkeypatch.setattr(
        integration_module,
        "entry_points",
        lambda: FakeEntryPoints(),
    )
    registry = ExtensionTargetRegistry()

    registry.load_entry_points()

    assert (
        len(registry.discovery_errors) == integration_module.MAX_TARGET_DISCOVERY_ERRORS
    )
    assert all("secret-value-canary" not in item for item in registry.discovery_errors)
    assert all("details omitted" in item for item in registry.discovery_errors)


def _package(
    *,
    requirements: tuple[IntegrationRequirement, ...] | None = None,
    overlays: tuple[IntegrationTargetOverlay, ...] | None = None,
    trust_evidence: tuple[IntegrationTrustEvidence, ...] | None = None,
) -> IntegrationPackage:
    if requirements is None:
        requirements = (
            IntegrationRequirement(
                id="command-runner",
                type=IntegrationRequirementType.COMMAND,
                classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                reason="Run the reviewed integration entry point.",
                argv=("runner", "--mode", "safe"),
                environment=("PATH",),
            ),
            IntegrationRequirement(
                id="network-api",
                type=IntegrationRequirementType.NETWORK,
                classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                reason="Connect to the reviewed service origin.",
                locator="https://network.example/",
                environment=("HTTPS_PROXY",),
            ),
            IntegrationRequirement(
                id="secret-token",
                type=IntegrationRequirementType.SECRET,
                classification=IntegrationPolicyClass.EXPLICIT_APPROVAL,
                reason="Resolve a token only at the backend owner.",
                secret_owner="secret-backend",
            ),
            IntegrationRequirement(
                id="verified-binary",
                type=IntegrationRequirementType.BINARY,
                classification=IntegrationPolicyClass.REVIEW_REQUIRED,
                reason="Install the pinned executable artifact.",
                locator="artifacts/tool",
                checksum=_ARTIFACT_DIGEST,
            ),
        )
    if overlays is None:
        overlays = (
            IntegrationTargetOverlay(
                target_id="codex",
                component_ids=("target-plugin", "portable-mcp"),
                requirement_ids=tuple(item.id for item in requirements),
            ),
        )
    if trust_evidence is None:
        trust_evidence = tuple(
            _trust(kind, IntegrationTrustStatus.VERIFIED)
            for kind in IntegrationTrustKind
        )
    return IntegrationPackage(
        id="example.integration",
        version="1.2.3",
        publisher="example-publisher",
        license="Apache-2.0",
        source_type=IntegrationSourceType.GIT,
        source="https://git.example/integration",
        immutable_ref="commit-deadbeef",
        checksum=_DIGEST,
        components=(
            IntegrationComponent(
                id="target-plugin",
                type=IntegrationComponentType.PLUGIN,
                portable=False,
            ),
            IntegrationComponent(
                id="portable-mcp",
                type=IntegrationComponentType.MCP,
                portable=True,
            ),
        ),
        requirements=requirements,
        overlays=overlays,
        compatibility=(
            IntegrationCompatibility(
                target_id="codex",
                minimum_version="0.1.0",
                maximum_version_exclusive="1.0.0",
                required_capabilities=("mcp", "plugin"),
            ),
        ),
        scopes=(InstallationScope.USER_HOME, InstallationScope.MANAGED_HOME),
        update_policy=IntegrationUpdatePolicy.MANUAL_REVIEW,
        verification_steps=("manifest-check", "runtime-activation"),
        rollback_steps=("restore-snapshot", "verify-discovery"),
        trust_evidence=trust_evidence,
    )


def _trust(
    kind: IntegrationTrustKind,
    status: IntegrationTrustStatus,
) -> IntegrationTrustEvidence:
    return IntegrationTrustEvidence(
        id=f"{kind.value}-evidence",
        kind=kind,
        status=status,
        authority="fixture-authority",
        revision="1",
    )


class _Driver:
    def __init__(self, descriptor: ExtensionTargetDescriptor):
        self.descriptor = descriptor

    def probe_target(self):
        return None

    def discover_installed(self):
        return None

    def preview_install(self):
        return None

    def install(self):
        return None

    def verify(self):
        return None

    def enable(self):
        return None

    def disable(self):
        return None

    def preview_update(self):
        return None

    def update(self):
        return None

    def preview_uninstall(self):
        return None

    def uninstall(self):
        return None

    def rollback(self):
        return None


def _plugin() -> ExtensionTargetPlugin:
    descriptor = ExtensionTargetDescriptor(
        id="codex",
        revision="1",
        component_types=(IntegrationComponentType.PLUGIN, IntegrationComponentType.MCP),
        scopes=(InstallationScope.MANAGED_HOME,),
        capabilities=("discover", "preview", "rollback"),
        trust_evidence=(
            _trust(IntegrationTrustKind.SOURCE, IntegrationTrustStatus.VERIFIED),
        ),
    )
    return ExtensionTargetPlugin(
        descriptor=descriptor,
        factory=lambda: _Driver(descriptor),
    )


class ExtensionTargetRegistryWithInvalidDriver(ExtensionTargetRegistry):
    def __init__(self):
        super().__init__()
        plugin = _plugin()
        self.register(replace(plugin, factory=lambda: object()))
