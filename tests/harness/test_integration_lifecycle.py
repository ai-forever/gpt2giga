from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gpt2giga_harness.integration_catalog import CatalogSourceType
from gpt2giga_harness.integration_flows import (
    IntegrationFlowEvent,
    IntegrationFlowRecord,
    IntegrationFlowService,
    IntegrationFlowSource,
    IntegrationFlowStatus,
    _target,
)
from gpt2giga_harness.integration_groups import GroupedIntegrationService
from gpt2giga_harness.integration_lifecycle import (
    IntegrationLifecycleConflictError,
    IntegrationLifecycleService,
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
from gpt2giga_harness.integration_runtime import (
    IntegrationRuntimeProbeResult,
    IntegrationRuntimeStore,
)
from gpt2giga_harness.portable_skills import (
    SkillActivationMode,
    SkillCapabilitySnapshot,
    SkillTargetStatus,
)


def test_flow_lifecycle_is_revisioned_idempotent_and_keeps_verbs_distinct(tmp_path):
    flows, groups, lifecycle = _services(tmp_path)
    flow = _install_skill(flows)

    inventory = lifecycle.inventory()
    installation = next(
        item for item in inventory["installations"] if item["flow_id"] == flow.id
    )
    assert installation["state"] == "enabled"
    assert installation["revision"] == 1
    matrix = next(
        item
        for item in inventory["capability_matrix"]
        if item["target_id"] == "codex-skill"
    )
    assert {item["action"] for item in matrix["actions"]} == {
        "enable",
        "disable",
        "uninstall",
        "delete_definition",
        "rollback",
    }

    preview = lifecycle.preview_flow(flow.id, "disable")
    assert preview["plan"]["effects"][0]["mutation"] == "admission_state_only"
    result = lifecycle.apply(
        preview["operation"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
        expected_revisions=preview["plan"]["expected_revisions"],
    )
    assert result["operation"]["status"] == "succeeded"
    assert result["receipt"]["action"] == "disable"
    assert flow.id not in {item.id for item in lifecycle.admitted_flows()}
    assert (
        lifecycle.apply(
            preview["operation"]["id"],
            plan_id=preview["plan"]["plan_id"],
            authority="test-operator",
            expected_revisions=preview["plan"]["expected_revisions"],
        )
        == result
    )
    with pytest.raises(
        IntegrationLifecycleConflictError,
        match="unavailable while integration is disabled",
    ):
        lifecycle.preview_flow(flow.id, "disable")

    enable = lifecycle.preview_flow(flow.id, "enable")
    enabled = lifecycle.apply(
        enable["operation"]["id"],
        plan_id=enable["plan"]["plan_id"],
        authority="test-operator",
        expected_revisions=enable["plan"]["expected_revisions"],
    )
    assert enabled["receipt"]["action"] == "enable"
    assert {item.id for item in lifecycle.admitted_flows()} == {flow.id}


def test_disable_retains_active_session_but_uninstall_is_guarded(tmp_path):
    flows, groups, lifecycle = _services(tmp_path)
    flow = _install_skill(flows)
    target = _target(flow.target_id)
    root = flows._target_root(flow.request, target, create=False)
    installer = flows._skill_installer(flow.request, root)
    runtime = lifecycle.runtime
    snapshot = runtime.capture(installer, str(flow.receipt_id))
    runtime.activate_session(
        session_id="session-active",
        harness_id="codex-cli",
        snapshot_reference=snapshot.public_ref(),
        probe=lambda _home, _snapshot: IntegrationRuntimeProbeResult(
            discovered=True,
            behavior_verified=True,
            surface="test-probe",
        ),
    )

    preview = lifecycle.preview_flow(flow.id, "disable")
    assert preview["plan"]["active_session_count"] == 1
    assert preview["plan"]["active_sessions_retain_revision"] is True
    lifecycle.apply(
        preview["operation"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
        expected_revisions=preview["plan"]["expected_revisions"],
    )

    with pytest.raises(
        IntegrationLifecycleConflictError,
        match="active sessions retain this revision",
    ):
        lifecycle.preview_flow(flow.id, "uninstall")
    assert runtime.binding("session-active").snapshot_id == snapshot.id


def test_uninstall_removes_only_owned_material_and_is_safely_repeatable(tmp_path):
    flows, groups, lifecycle = _services(tmp_path)
    flow = _install_skill(flows)
    target = _target(flow.target_id)
    root = flows._target_root(flow.request, target, create=False)
    installer = flows._skill_installer(flow.request, root)
    assert installer.discover()

    preview = lifecycle.preview_flow(flow.id, "uninstall")
    result = lifecycle.apply(
        preview["operation"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
        expected_revisions=preview["plan"]["expected_revisions"],
        confirm_id=flow.package_id,
    )

    assert result["operation"]["status"] == "succeeded"
    assert result["receipt"]["recovery_actions"] == []
    assert installer.discover() == ()
    assert (
        lifecycle.apply(
            preview["operation"]["id"],
            plan_id=preview["plan"]["plan_id"],
            authority="test-operator",
            expected_revisions=preview["plan"]["expected_revisions"],
            confirm_id=flow.package_id,
        )
        == result
    )
    state = next(
        item
        for item in lifecycle.inventory()["installations"]
        if item["flow_id"] == flow.id
    )
    assert state["state"] == "uninstalled"
    assert state["installed"] is False


def test_group_disable_compensates_completed_children_after_failure(tmp_path):
    flows, groups, _lifecycle = _services(tmp_path)
    entry = flows.inventory()["catalog"][0]
    preview = groups.preview(
        {
            "source": "catalog",
            "catalog_id": entry["catalog_id"],
            "scope": "managed_home",
            "target_mode": "all_supported",
            "configuration": {},
        }
    )
    group = groups.apply(
        preview["group"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
    )["group"]

    def fail_second(_action: str, flow_id: str) -> None:
        if flows.get(flow_id).target_id == "claude-skill":
            raise RuntimeError("secret-value-canary")

    lifecycle = IntegrationLifecycleService(
        tmp_path,
        flow_service=flows,
        group_service=groups,
        fault_injector=fail_second,
    )
    operation = lifecycle.preview_group(group["id"], "disable")
    result = lifecycle.apply(
        operation["operation"]["id"],
        plan_id=operation["plan"]["plan_id"],
        authority="test-operator",
        expected_revisions=operation["plan"]["expected_revisions"],
    )

    assert result["operation"]["status"] == "compensated"
    assert result["receipt"]["recovery_actions"] == []
    assert "secret-value-canary" not in str(result)
    states = {
        item["flow_id"]: item["state"]
        for item in lifecycle.inventory()["installations"]
    }
    assert {states[item["flow_id"]] for item in group["children"]} == {"enabled"}


def test_user_definition_delete_requires_exact_catalog_revision_and_confirmation(
    tmp_path,
):
    flows, groups, lifecycle = _services(tmp_path)
    package = _user_plugin_package()
    entry = flows.catalog.import_package(
        package,
        source_id="user-git",
        source_type=CatalogSourceType.GIT,
    )
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    flow = IntegrationFlowRecord(
        id="flow_" + "d" * 32,
        plan_id="plan_" + "e" * 64,
        status=IntegrationFlowStatus.ROLLED_BACK,
        source=IntegrationFlowSource.CATALOG,
        package_id=package.id,
        package_version=package.version,
        manifest_sha256=entry.content_hash,
        target_id="codex-plugin",
        scope=InstallationScope.MANAGED_HOME,
        workspace=None,
        request={
            "source": "catalog",
            "catalog_id": entry.catalog_id,
            "target_id": "codex-plugin",
            "scope": "managed_home",
            "configuration": {},
        },
        receipt_id=None,
        verification_status="rolled_back",
        rollback_available=False,
        error_code=None,
        created_at=timestamp,
        updated_at=timestamp,
        events=(
            IntegrationFlowEvent(
                stage="rollback",
                status="rolled_back",
                occurred_at=timestamp,
            ),
        ),
    )
    flows._put(flow)

    preview = lifecycle.preview_flow(flow.id, "delete_definition")
    with pytest.raises(
        IntegrationLifecycleConflictError,
        match="exact lifecycle confirmation",
    ):
        lifecycle.apply(
            preview["operation"]["id"],
            plan_id=preview["plan"]["plan_id"],
            authority="test-operator",
            expected_revisions=preview["plan"]["expected_revisions"],
        )
    result = lifecycle.apply(
        preview["operation"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
        expected_revisions=preview["plan"]["expected_revisions"],
        confirm_id=package.id,
    )
    assert result["receipt"]["action"] == "delete_definition"
    assert flows.catalog.get(entry.catalog_id) is None


def _services(tmp_path):
    flows = IntegrationFlowService(
        tmp_path,
        skill_capability_provider=_supported_skill,
    )
    groups = GroupedIntegrationService(tmp_path, flow_service=flows)
    lifecycle = IntegrationLifecycleService(
        tmp_path,
        flow_service=flows,
        group_service=groups,
        runtime_store=IntegrationRuntimeStore(tmp_path),
    )
    return flows, groups, lifecycle


def _install_skill(flows: IntegrationFlowService) -> IntegrationFlowRecord:
    entry = flows.inventory()["catalog"][0]
    preview = flows.preview(
        {
            "source": "catalog",
            "catalog_id": entry["catalog_id"],
            "target_id": "codex-skill",
            "scope": "managed_home",
            "configuration": {},
        }
    )
    flows.apply(
        preview["flow"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
    )
    return flows.get(preview["flow"]["id"])


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


def _user_plugin_package() -> IntegrationPackage:
    return IntegrationPackage(
        id="example.user-plugin",
        version="1.0.0",
        publisher="example",
        license="MIT",
        source_type=IntegrationSourceType.GIT,
        source="https://github.com/example/user-plugin.git",
        immutable_ref="a" * 40,
        checksum="sha256:" + "b" * 64,
        components=(
            IntegrationComponent(
                id="user-plugin",
                type=IntegrationComponentType.PLUGIN,
                portable=False,
            ),
        ),
        requirements=(),
        overlays=(
            IntegrationTargetOverlay(
                target_id="codex-plugin",
                component_ids=("user-plugin",),
            ),
        ),
        compatibility=(IntegrationCompatibility(target_id="codex-plugin"),),
        scopes=(InstallationScope.MANAGED_HOME,),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("plugin-discovery",),
        rollback_steps=("plugin-remove",),
    )
