from dataclasses import replace
import json

import pytest

from gpt2giga_harness.execution import (
    EMPTY_EXTENSION_SNAPSHOT_HASH,
    ExecutionBudgets,
    ExecutionClassification,
    ExecutionClassificationStatus,
    ExecutionSnapshot,
    ExecutionTransport,
    InteractionMode,
    ProviderRef,
    RouteRef,
    RuntimeOwnership,
    SnapshotEvidenceRef,
    create_execution_snapshot,
    execution_snapshot_from_dict,
    execution_snapshot_to_dict,
    legacy_execution_placeholder,
)


def test_execution_snapshot_round_trips_with_stable_semantic_hash():
    first = _snapshot(
        compatibility_evidence=(
            SnapshotEvidenceRef("cli-window", "2", "supported", "probe"),
            SnapshotEvidenceRef("protocol", "1", "supported", "fixture"),
        ),
        capability_evidence=(
            SnapshotEvidenceRef("structured-events", "4", "supported", "probe"),
        ),
    )
    reordered = _snapshot(
        compatibility_evidence=tuple(reversed(first.compatibility_evidence)),
        capability_evidence=first.capability_evidence,
    )

    payload = execution_snapshot_to_dict(first)

    assert first.snapshot_hash == reordered.snapshot_hash
    assert execution_snapshot_from_dict(payload) == first
    assert payload["snapshot_hash"] == first.snapshot_hash
    assert payload["provider"] == {"id": "provider-main", "revision": "7"}
    assert payload["route"]["provider"] == payload["provider"]
    assert first.is_executable is True
    assert ExecutionSnapshot.__module__ == "gpt2giga_harness.execution"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: replace(
            item,
            provider=ProviderRef("provider-main", "8"),
            route=RouteRef("coding", "11", ProviderRef("provider-main", "8")),
        ),
        lambda item: replace(item, route=replace(item.route, revision="12")),
        lambda item: replace(item, harness_id="claude-code"),
        lambda item: replace(item, harness_version="2.1.212"),
        lambda item: replace(item, transport=ExecutionTransport.NATIVE_TERMINAL),
        lambda item: replace(item, interaction_mode=InteractionMode.BATCH),
        lambda item: replace(item, runtime_ownership=RuntimeOwnership.REQUEST_BOUND),
        lambda item: replace(item, workspace_id="workspace-other"),
        lambda item: replace(item, worktree_id="worktree-other"),
        lambda item: replace(item, permission_profile="read-only"),
        lambda item: replace(item, extension_snapshot_hash="a" * 64),
        lambda item: replace(item, budgets=replace(item.budgets, timeout_seconds=121)),
        lambda item: replace(item, budgets=replace(item.budgets, retry_limit=3)),
        lambda item: replace(
            item, budgets=replace(item.budgets, cost_limit_microunits=2_000_001)
        ),
        lambda item: replace(item, budgets=replace(item.budgets, token_limit=200_000)),
        lambda item: replace(item, budgets=replace(item.budgets, runtime_seconds=601)),
        lambda item: replace(
            item,
            capability_evidence=(
                SnapshotEvidenceRef("structured-events", "5", "supported", "probe"),
            ),
        ),
    ],
)
def test_execution_snapshot_hash_changes_for_continuation_sensitive_fields(mutation):
    snapshot = _snapshot()

    changed = mutation(snapshot)

    assert changed.snapshot_hash != snapshot.snapshot_hash


def test_execution_snapshot_rejects_route_provider_mismatch_and_duplicate_evidence():
    with pytest.raises(ValueError, match="route provider"):
        _snapshot(route=RouteRef("coding", "11", ProviderRef("provider-other", "1")))

    evidence = SnapshotEvidenceRef("protocol", "1", "supported", "fixture")
    with pytest.raises(ValueError, match="duplicate compatibility evidence"):
        _snapshot(compatibility_evidence=(evidence, replace(evidence, revision="2")))


def test_execution_snapshot_rejects_invalid_axis_and_budget_combinations():
    with pytest.raises(ValueError, match="one_shot execution must be batch"):
        _snapshot(transport=ExecutionTransport.ONE_SHOT)

    with pytest.raises(ValueError, match="token_limit"):
        ExecutionBudgets(token_limit=-1)

    with pytest.raises(ValueError, match="retry_limit"):
        ExecutionBudgets(retry_limit=True)


def test_execution_snapshot_parser_is_strict_and_forward_only():
    payload = execution_snapshot_to_dict(_snapshot())

    future = dict(payload)
    future["schema_version"] = 2
    with pytest.raises(ValueError, match="schema_version"):
        execution_snapshot_from_dict(future)

    unknown = dict(payload)
    unknown["api_key"] = "must-not-be-accepted"
    with pytest.raises(ValueError, match="unknown execution snapshot fields"):
        execution_snapshot_from_dict(unknown)

    value_bearing_provider = json.loads(json.dumps(payload))
    value_bearing_provider["provider"]["value"] = "must-not-be-accepted"
    with pytest.raises(ValueError, match="unknown provider ref fields"):
        execution_snapshot_from_dict(value_bearing_provider)

    changed = json.loads(json.dumps(payload))
    changed["workspace"]["id"] = "workspace-other"
    with pytest.raises(ValueError, match="hash mismatch"):
        execution_snapshot_from_dict(changed)


def test_legacy_snapshot_maps_to_content_free_non_executable_placeholder():
    canary = "secret-canary-value"
    legacy = {
        "id": "nexec_old",
        "harness_id": "codex-cli",
        "api_mode": "v1",
        "model": "legacy-model",
        "workspace": "/private/customer/repository",
        "effective_workspace": "/private/customer/worktree",
        "project_id": "proj_repo",
        "permission_mode": "edit",
        "tool_config_hash": "legacy-tool-config",
        "api_key": canary,
    }

    placeholder = legacy_execution_placeholder(legacy, invocation_mode="native")
    serialized = json.dumps(execution_snapshot_to_dict(placeholder), sort_keys=True)

    assert placeholder.is_executable is False
    assert placeholder.transport is None
    assert placeholder.interaction_mode is None
    assert placeholder.runtime_ownership is None
    assert placeholder.classification.status is ExecutionClassificationStatus.AMBIGUOUS
    assert placeholder.classification.reason_code == "insufficient_execution_evidence"
    assert placeholder.provider.id == "legacy-unknown-provider"
    assert placeholder.workspace_id == "proj_repo"
    assert canary not in serialized
    assert "/private/customer" not in serialized
    assert "legacy-model" not in serialized
    assert (
        execution_snapshot_from_dict(execution_snapshot_to_dict(placeholder))
        == placeholder
    )


def test_non_executable_classification_cannot_retain_canonical_axes():
    with pytest.raises(ValueError, match="non-executable classification"):
        _snapshot(
            classification=ExecutionClassification(
                status=ExecutionClassificationStatus.AMBIGUOUS,
                source="legacy_record",
                reason_code="insufficient_execution_evidence",
            )
        )


def _snapshot(**overrides):
    provider = overrides.pop("provider", ProviderRef("provider-main", "7"))
    values = {
        "provider": provider,
        "route": RouteRef("coding", "11", provider),
        "harness_id": "codex-cli",
        "harness_version": "0.144.5",
        "transport": ExecutionTransport.NATIVE_STRUCTURED,
        "interaction_mode": InteractionMode.INTERACTIVE,
        "runtime_ownership": RuntimeOwnership.DURABLE,
        "workspace_id": "workspace-repo",
        "worktree_id": "worktree-run-1",
        "permission_profile": "workspace-write",
        "extension_snapshot_hash": EMPTY_EXTENSION_SNAPSHOT_HASH,
        "budgets": ExecutionBudgets(
            timeout_seconds=120,
            retry_limit=2,
            cost_limit_microunits=2_000_000,
            token_limit=100_000,
            runtime_seconds=600,
        ),
        "compatibility_evidence": (
            SnapshotEvidenceRef("protocol", "1", "supported", "fixture"),
        ),
        "capability_evidence": (
            SnapshotEvidenceRef("structured-events", "4", "supported", "probe"),
        ),
    }
    values.update(overrides)
    return create_execution_snapshot(**values)
