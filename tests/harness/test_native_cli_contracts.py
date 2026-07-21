from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path

import pytest

from gpt2giga_harness.cli_capabilities import CLI_PROBE_CONTRACTS
from gpt2giga_harness.native_cli_capture import CAPTURE_OUTPUT_BYTES
from gpt2giga_harness.native_cli_capture import build_native_cli_capture_plan
from gpt2giga_harness.native_cli_capture import digest_native_cli_capture
from gpt2giga_harness.native_cli_contracts import CapabilityContext
from gpt2giga_harness.native_cli_contracts import CapabilityLevel
from gpt2giga_harness.native_cli_contracts import CapabilityState
from gpt2giga_harness.native_cli_contracts import NATIVE_NAMESPACE_SPECS
from gpt2giga_harness.native_cli_contracts import NativeCommandClass
from gpt2giga_harness.native_cli_contracts import VersionEvidenceStatus
from gpt2giga_harness.native_cli_contracts import WORKBENCH_INTEGRATION_SPECS
from gpt2giga_harness.native_cli_contracts import classify_native_route
from gpt2giga_harness.native_cli_contracts import evaluate_contextual_capability
from gpt2giga_harness.native_cli_contracts import native_namespace_spec_to_dict
from gpt2giga_harness.native_cli_contracts import route_decision_to_dict
from gpt2giga_harness.native_cli_contracts import workbench_integration_spec_to_dict

FIXTURES = Path(__file__).parents[1] / "fixtures" / "native_cli_contracts"
HARNESS_FIXTURES = Path(__file__).parents[1] / "fixtures" / "harness_cli"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_contracts_reserve_exactly_three_split_immutable_namespaces():
    assert set(NATIVE_NAMESPACE_SPECS) == {"codex", "claude", "gemini"}
    assert set(WORKBENCH_INTEGRATION_SPECS) == set(NATIVE_NAMESPACE_SPECS)

    namespace = NATIVE_NAMESPACE_SPECS["codex"]
    integration = WORKBENCH_INTEGRATION_SPECS["codex"]
    namespace_payload = native_namespace_spec_to_dict(namespace)
    integration_payload = workbench_integration_spec_to_dict(integration)

    assert "version_window" not in namespace_payload
    assert "intent_patterns" not in namespace_payload
    assert "process_strategies" not in integration_payload
    assert namespace.discovery_authorizes_execution is False
    assert namespace.discovery_authorizes_mutation is False
    with pytest.raises(FrozenInstanceError):
        namespace.namespace = "other"
    with pytest.raises(TypeError):
        NATIVE_NAMESPACE_SPECS["other"] = namespace


def test_content_free_inventory_matches_split_contracts_and_capture_digests():
    fixture = _fixture("command_inventory.json")

    assert fixture["content_free"] is True
    assert not any(fixture["authority"].values())
    assert set(fixture["providers"]) == set(NATIVE_NAMESPACE_SPECS)
    assert fixture["capture"]["source"] == "hermetic_fixture"
    assert fixture["capture"]["raw_output_retained"] is False

    for namespace, provider in fixture["providers"].items():
        native = NATIVE_NAMESPACE_SPECS[namespace]
        integration = WORKBENCH_INTEGRATION_SPECS[namespace]
        frozen_native = provider["native_namespace"]
        frozen_integration = provider["integration"]

        assert frozen_native["executable"] == native.executable
        assert frozen_native["posix_strategy"] == native.posix_strategy
        assert frozen_integration["harness_id"] == integration.harness_id
        assert frozen_integration["version_window"] == [
            integration.version_window.minimum,
            integration.version_window.maximum_exclusive,
        ]
        assert frozen_integration["release_tag"] == integration.evidence.release_tag
        assert frozen_integration["repository"] == integration.evidence.repository
        assert frozen_integration["release_url"] == integration.evidence.release_url
        assert frozen_integration["commit"] == integration.evidence.commit
        assert frozen_integration["intent_patterns"] == [
            pattern.pattern_id for pattern in integration.intent_patterns
        ]
        assert frozen_integration["capability_status"] == {
            capability.capability_id: capability.state.value
            for capability in integration.capabilities
        }
        for digest in frozen_integration["help_byte_digests"].values():
            assert digest["bytes"] > 0
            assert len(digest["sha256"]) == 64
            int(digest["sha256"], 16)


ROUTE_INPUTS = {
    "codex-root-admitted": ("codex", (), "0.144.5", True, True),
    "codex-resume-drift": ("codex", ("resume", "--last"), "0.145.0", True, True),
    "codex-unknown-absent": ("codex", ("--future-mode",), None, True, True),
    "codex-headless-unparsed": (
        "codex",
        ("exec", "--future-mode"),
        "development",
        False,
        True,
    ),
    "claude-root-reviewed": ("claude", (), "2.1.212", True, True),
    "claude-headless-precedence": (
        "claude",
        ("-c", "-p", "fixture-input"),
        "2.1.212",
        True,
        True,
    ),
    "claude-unknown-newer": ("claude", ("--future-mode",), "2.2.0", True, True),
    "gemini-root-admitted": ("gemini", (), "0.46.0", True, True),
    "gemini-non-tty": ("gemini", ("fixture-input",), "0.46.0", False, False),
    "gemini-resume-below": ("gemini", ("-r", "latest"), "0.45.9", True, True),
    "gemini-unknown-unparsed": (
        "gemini",
        ("--future-mode",),
        "nightly",
        True,
        True,
    ),
}


def test_frozen_route_evidence_is_deterministic_and_content_free():
    cases = _fixture("classification_cases.json")["cases"]

    assert {case["case_id"] for case in cases} == set(ROUTE_INPUTS)
    for case in cases:
        namespace, suffix, version, stdin_tty, stdout_tty = ROUTE_INPUTS[
            case["case_id"]
        ]
        decision = classify_native_route(
            namespace,
            suffix,
            version=version,
            stdin_is_tty=stdin_tty,
            stdout_is_tty=stdout_tty,
        )
        payload = route_decision_to_dict(decision)

        assert payload["namespace"] == case["provider"]
        assert payload["command_class"] == case["command_class"]
        assert payload["version_evidence"] == case["version_evidence"]
        assert payload["level"] == case["level"]
        assert payload["reason"] == case["reason"]
        assert payload["l0_eligible"] is True
        assert payload["execution_authorized"] is False
        assert not set(payload) & {"argv", "suffix", "input", "output"}


@pytest.mark.parametrize(
    ("namespace", "suffix", "pattern_id", "level"),
    [
        ("codex", (), "codex.root", CapabilityLevel.STRUCTURED_WORKBENCH),
        (
            "codex",
            ("resume", "--last"),
            "codex.resume",
            CapabilityLevel.STRUCTURED_WORKBENCH,
        ),
        (
            "codex",
            ("fork", "fixture-session"),
            "codex.fork",
            CapabilityLevel.STRUCTURED_WORKBENCH,
        ),
        ("claude", (), "claude.root", CapabilityLevel.MANAGED_HANDOFF),
        (
            "claude",
            ("fixture-input",),
            "claude.prompt",
            CapabilityLevel.MANAGED_HANDOFF,
        ),
        (
            "claude",
            ("-c",),
            "claude.continue",
            CapabilityLevel.MANAGED_HANDOFF,
        ),
        (
            "claude",
            ("-r", "fixture-session"),
            "claude.resume",
            CapabilityLevel.MANAGED_HANDOFF,
        ),
        (
            "claude",
            ("--permission-mode", "plan"),
            "claude.control",
            CapabilityLevel.MANAGED_HANDOFF,
        ),
        ("gemini", (), "gemini.root", CapabilityLevel.STRUCTURED_WORKBENCH),
        (
            "gemini",
            ("fixture-input",),
            "gemini.prompt",
            CapabilityLevel.STRUCTURED_WORKBENCH,
        ),
        (
            "gemini",
            ("-i", "fixture-input"),
            "gemini.interactive",
            CapabilityLevel.STRUCTURED_WORKBENCH,
        ),
        (
            "gemini",
            ("-r", "latest"),
            "gemini.resume",
            CapabilityLevel.STRUCTURED_WORKBENCH,
        ),
    ],
)
def test_every_managed_pattern_is_affirmative_and_deterministic(
    namespace, suffix, pattern_id, level
):
    versions = {"codex": "0.144.5", "claude": "2.1.212", "gemini": "0.46.0"}

    first = classify_native_route(namespace, suffix, version=versions[namespace])
    second = classify_native_route(namespace, suffix, version=versions[namespace])

    assert first == second
    assert first.intent_pattern_id == pattern_id
    assert first.level is level


@pytest.mark.parametrize("version", [None, "nightly", "0.143.9", "0.145.0"])
def test_l0_machine_and_unknown_routes_do_not_require_version_admission(version):
    headless = classify_native_route(
        "codex", ("exec", "--json", "fixture-input"), version=version
    )
    unknown = classify_native_route("codex", ("--future-mode",), version=version)

    assert headless.level is CapabilityLevel.NATIVE_PASSTHROUGH
    assert headless.command_class is NativeCommandClass.HEADLESS
    assert unknown.level is CapabilityLevel.NATIVE_PASSTHROUGH
    assert unknown.command_class is NativeCommandClass.UNKNOWN_NATIVE
    assert headless.l0_eligible and unknown.l0_eligible


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (None, VersionEvidenceStatus.ABSENT),
        ("nightly", VersionEvidenceStatus.UNPARSED),
        ("0.143.9", VersionEvidenceStatus.BELOW_WINDOW),
        ("0.144.5", VersionEvidenceStatus.IN_WINDOW),
        ("0.145.0", VersionEvidenceStatus.ABOVE_WINDOW),
    ],
)
def test_version_window_gates_only_structured_workbench(version, expected):
    decision = classify_native_route("codex", (), version=version)

    assert decision.version_evidence is expected
    assert decision.level is (
        CapabilityLevel.STRUCTURED_WORKBENCH
        if expected is VersionEvidenceStatus.IN_WINDOW
        else CapabilityLevel.MANAGED_HANDOFF
    )
    assert decision.l0_eligible is True


def test_unknown_namespace_nul_and_lossy_human_shapes_fail_safe_to_l0():
    with pytest.raises(KeyError, match="unknown native CLI namespace"):
        classify_native_route("other", ())
    with pytest.raises(ValueError, match="NUL-free"):
        classify_native_route("codex", ("bad\x00token",))

    lossy = classify_native_route(
        "codex", ("resume", "--last", "--future-mode"), version="0.144.5"
    )
    assert lossy.level is CapabilityLevel.NATIVE_PASSTHROUGH
    assert lossy.command_class is NativeCommandClass.UNKNOWN_NATIVE


def test_existing_adapter_windows_are_reused_without_coupling_l0():
    fixture_versions = {"codex": "0.144", "claude": "2.1", "gemini": "0.46"}

    for namespace, integration in WORKBENCH_INTEGRATION_SPECS.items():
        legacy = CLI_PROBE_CONTRACTS[integration.harness_id]
        assert legacy.minimum_version == integration.version_window.minimum
        assert (
            legacy.maximum_version_exclusive
            == integration.version_window.maximum_exclusive
        )
        assert (HARNESS_FIXTURES / namespace / fixture_versions[namespace]).is_dir()


@pytest.mark.parametrize("namespace", ["codex", "claude", "gemini"])
def test_capture_plans_are_isolated_bounded_and_non_authoritative(namespace, tmp_path):
    real_home = tmp_path / "real-home"
    isolated_home = tmp_path / "isolated"
    plan = build_native_cli_capture_plan(
        namespace,
        (f"/fixture/{namespace}",),
        isolated_home,
        inherited_environment={"PATH": "/fixture/bin", "HOME": str(real_home)},
    )

    assert plan.environment["HOME"] == str(isolated_home)
    assert str(real_home) not in plan.environment.values()
    assert plan.environment["DO_NOT_TRACK"] == "1"
    assert plan.execution_authorized is False
    assert plan.network_authorized is False
    assert plan.mutation_authorized is False
    assert plan.invocations[0].argv[-1] == "--version"
    assert all(
        invocation.argv[-1] in {"--version", "--help"}
        for invocation in plan.invocations
    )
    with pytest.raises(TypeError):
        plan.environment["NEW"] = "value"


def test_capture_digest_discards_raw_bytes_and_enforces_limits(tmp_path):
    plan = build_native_cli_capture_plan("codex", ("/fixture/codex",), tmp_path)
    invocation = plan.invocations[1]
    raw_stdout = b"hermetic fixture output"

    digest = digest_native_cli_capture(
        invocation,
        returncode=0,
        stdout=raw_stdout,
        stderr=b"",
    )

    assert digest.stdout_bytes == len(raw_stdout)
    assert digest.stdout_sha256 == hashlib.sha256(raw_stdout).hexdigest()
    assert raw_stdout.decode() not in repr(digest)
    with pytest.raises(ValueError, match="bounded evidence limit"):
        digest_native_cli_capture(
            invocation,
            returncode=0,
            stdout=b"x" * (CAPTURE_OUTPUT_BYTES + 1),
            stderr=b"",
        )


def test_contextual_capabilities_require_all_context_axes():
    integration = WORKBENCH_INTEGRATION_SPECS["codex"]
    capability = integration.capabilities[0]
    admitted = CapabilityContext(
        version="0.144.5",
        transport="app-server",
        process_owner="harness",
        session_generation=1,
        policy_allows=True,
    )

    assert evaluate_contextual_capability(integration, capability, admitted).state is (
        CapabilityState.READY
    )
    drifted = CapabilityContext(
        version="0.145.0",
        transport="app-server",
        process_owner="harness",
        session_generation=1,
        policy_allows=True,
    )
    denied = CapabilityContext(
        version="0.144.5",
        transport="app-server",
        process_owner="harness",
        session_generation=1,
        policy_allows=False,
    )
    assert evaluate_contextual_capability(integration, capability, drifted).state is (
        CapabilityState.DEGRADED
    )
    assert evaluate_contextual_capability(integration, capability, denied).state is (
        CapabilityState.BLOCKED
    )


def test_fixtures_retain_no_native_content_or_private_state():
    fixture_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(FIXTURES.glob("*.json"))
    )
    lowered = fixture_text.lower()

    assert '"suffix"' not in lowered
    assert '"argv"' not in lowered
    assert '"transcript"' not in lowered
    assert '"credential"' not in lowered
    assert '"provider_response"' not in lowered
    assert "fixture-input" not in lowered
    assert "fixture-session" not in lowered
    assert "secret" not in lowered
