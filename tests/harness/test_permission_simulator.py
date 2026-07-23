from dataclasses import replace

import pytest

from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.mcp import MCPTransport, ToolServerDescriptor
from gpt2giga_harness.permission_simulator import (
    PermissionPrediction,
    build_permission_simulation,
    extension_permission_contract,
)
from gpt2giga_harness.runtime.policy import PermissionAction
from gpt2giga_harness.secrets import SecretReference, SecretReferenceKind
from gpt2giga_harness.types import HarnessCapability, HarnessSpec


def _spec() -> HarnessSpec:
    return HarnessSpec(
        id="codex-cli",
        title="Codex CLI",
        kind="agent-cli",
        description="test",
        capabilities=(
            HarnessCapability.AGENT_CLI,
            HarnessCapability.FILE_EDIT,
            HarnessCapability.SHELL,
        ),
        supports_workspace=True,
        supports_native_sessions=True,
    )


def _simulate(**overrides):
    values = {
        "spec": _spec(),
        "execution_transport": ExecutionTransport.NATIVE_STRUCTURED,
        "invocation_mode": "headless",
        "permission_profile_id": "interactive",
        "mode": "edit",
        "workspace": "/tmp/workspace-a",
        "api_mode": "v2",
        "model": "model-a",
    }
    values.update(overrides)
    return build_permission_simulation(**values)


def test_simulation_is_deterministic_content_free_and_side_effect_free():
    first = _simulate()
    second = _simulate()

    assert first == second
    payload = first.to_dict()
    assert payload["simulation_hash"] == second.simulation_hash
    assert payload["route_snapshot"]["snapshot_hash"] == (
        second.route_snapshot.snapshot_hash
    )
    assert payload["content_free"] is True
    assert payload["side_effect_free"] is True
    assert payload["provider_safety_proven"] is False
    assert "/tmp/workspace-a" not in str(payload)
    assert "model-a" not in str(payload)
    assert payload["summary"]["unknown"] == 2
    assert {
        item["domain"]
        for item in payload["outcomes"]
        if item["prediction"] == "unknown"
    } == {"provider", "secret"}


def test_review_profile_projects_likely_approvals_without_consuming_grants():
    simulation = _simulate(permission_profile_id="review-every-action")
    payload = simulation.to_dict()

    assert simulation.block_run is False
    assert PermissionAction.PROCESS_SPAWN in simulation.approval_points
    assert PermissionAction.WORKSPACE_WRITE in simulation.approval_points
    assert payload["summary"]["approval_required"] >= 4
    process = next(
        item
        for item in simulation.outcomes
        if item.action is PermissionAction.PROCESS_SPAWN
    )
    assert process.prediction is PermissionPrediction.APPROVAL_REQUIRED
    assert process.enforcement.value == "delegated_to_cli_sandbox"


def test_local_harness_does_not_invent_provider_or_network_permissions():
    local_spec = replace(
        _spec(),
        id="local-test",
        kind="test",
        capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        tags=("local", "test"),
    )

    payload = _simulate(
        spec=local_spec,
        execution_transport=ExecutionTransport.ONE_SHOT,
        mode="plan",
        workspace=None,
    ).to_dict()

    assert payload["summary"]["unknown"] == 0
    assert all(item["domain"] != "provider" for item in payload["outcomes"])
    assert all(item["action"] != "network.connect" for item in payload["outcomes"])


def test_explicit_required_action_is_blocked_by_effective_unattended_policy():
    simulation = _simulate(
        permission_profile_id="unattended",
        required_actions=(PermissionAction.GIT_PUSH,),
    )

    assert simulation.block_run is True
    assert simulation.blocked_actions == (PermissionAction.GIT_PUSH,)
    blocked = next(
        item for item in simulation.outcomes if item.action is PermissionAction.GIT_PUSH
    )
    assert blocked.prediction is PermissionPrediction.DENIED
    assert blocked.occurrence.value == "required_before_start"


def test_extension_contract_hashes_values_and_exposes_only_capabilities():
    first = ToolServerDescriptor(
        id="issues",
        title="Issues",
        transport=MCPTransport.STDIO,
        command="issue-mcp",
        environment={
            "TOKEN": SecretReference(
                kind=SecretReferenceKind.ENVIRONMENT,
                name="ISSUE_TOKEN",
            )
        },
        enabled=True,
        trusted=True,
    )
    second = replace(first, command="issue-mcp-v2")

    first_contract = extension_permission_contract(first)
    second_contract = extension_permission_contract(second)
    assert first_contract.identity_sha256 != second_contract.identity_sha256
    assert first_contract.secret_reference_count == 1
    assert first_contract.capabilities == (
        "mcp.server.start",
        "mcp.tool.call",
        "process.spawn",
        "provider_owned_approval",
        "secret.reference",
    )
    payload = _simulate(extensions=(first_contract,)).to_dict()
    assert payload["route_snapshot"]["extension_count"] == 1
    assert payload["summary"]["unknown"] == 4
    assert "ISSUE_TOKEN" not in str(payload)
    assert "issue-mcp" not in str(payload)


def test_invalid_or_duplicate_extension_contracts_fail_closed():
    descriptor = ToolServerDescriptor(
        id="remote",
        title="Remote",
        transport=MCPTransport.STREAMABLE_HTTP,
        url="https://example.invalid/mcp",
        enabled=True,
        trusted=True,
    )
    contract = extension_permission_contract(descriptor)

    with pytest.raises(ValueError, match="duplicates"):
        _simulate(extensions=(contract, contract))
