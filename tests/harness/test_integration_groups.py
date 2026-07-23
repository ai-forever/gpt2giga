from __future__ import annotations

import hashlib
import json
import stat
from types import SimpleNamespace

import pytest

from gpt2giga_harness.integration_flows import IntegrationFlowService
from gpt2giga_harness.integration_catalog import sync_official_mcp_registry
from gpt2giga_harness.integration_groups import (
    GroupedIntegrationService,
    IntegrationGroupConflictError,
)
from gpt2giga_harness.portable_skills import (
    SkillActivationMode,
    SkillCapabilitySnapshot,
    SkillTargetStatus,
)


def test_all_supported_skill_group_applies_verifies_and_rolls_back(tmp_path):
    flows = _flows(tmp_path)
    groups = GroupedIntegrationService(tmp_path, flow_service=flows)
    entry = flows.inventory()["catalog"][0]

    preview = groups.preview(
        {
            "source": "catalog",
            "catalog_id": entry["catalog_id"],
            "scope": "managed_home",
            "target_mode": "all_supported",
        }
    )

    plan = preview["plan"]
    assert plan["target_ids"] == ["codex-skill", "claude-skill", "gemini-skill"]
    assert plan["atomicity"] == "recoverable_compensating_transaction"
    assert len(plan["children"]) == 3
    assert all(item["configuration_diff"] for item in plan["children"])

    applied = groups.apply(
        preview["group"]["id"],
        plan_id=plan["plan_id"],
        authority="test-operator",
    )["group"]

    assert applied["status"] == "verified"
    assert applied["approval_hash"]
    assert all(
        item["verification_status"] == "discovered" for item in applied["children"]
    )
    assert (
        groups.apply(
            applied["id"],
            plan_id=plan["plan_id"],
            authority="test-operator",
        )["group"]
        == applied
    )

    rolled_back = groups.rollback(applied["id"])["group"]
    assert rolled_back["status"] == "rolled_back"
    assert all(
        item["rollback_status"] == "rolled_back" for item in rolled_back["children"]
    )

    state_path = tmp_path / "integrations" / "groups.json"
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert "content_free" in json.loads(state_path.read_text())["groups"][0]


def test_group_rejects_stale_or_widened_approval(tmp_path):
    flows = _flows(tmp_path)
    groups = GroupedIntegrationService(tmp_path, flow_service=flows)
    entry = flows.inventory()["catalog"][0]
    preview = groups.preview(
        {
            "catalog_id": entry["catalog_id"],
            "scope": "managed_home",
        }
    )

    with pytest.raises(IntegrationGroupConflictError, match="does not match"):
        groups.apply(
            preview["group"]["id"],
            plan_id="plan_" + "0" * 64,
            authority="test-operator",
        )

    state = json.loads((tmp_path / "integrations" / "groups.json").read_text())
    state["groups"][0]["target_ids"].append("future-target")
    (tmp_path / "integrations" / "groups.json").write_text(json.dumps(state))
    widened = GroupedIntegrationService(tmp_path, flow_service=flows)
    with pytest.raises(IntegrationGroupConflictError, match="stale"):
        widened.apply(
            preview["group"]["id"],
            plan_id=preview["plan"]["plan_id"],
            authority="test-operator",
        )


def test_child_failure_compensates_and_recovery_repairs_exact_owned_child(tmp_path):
    flows = _flows(tmp_path)
    groups = GroupedIntegrationService(tmp_path, flow_service=flows)
    entry = flows.inventory()["catalog"][0]
    preview = groups.preview(
        {"catalog_id": entry["catalog_id"], "scope": "managed_home"}
    )
    original_apply = flows._apply_skill

    def fail_claude(request, resolved, **kwargs):
        if resolved.target.id == "claude-skill":
            raise RuntimeError("secret-value-canary")
        return original_apply(request, resolved, **kwargs)

    flows._apply_skill = fail_claude  # type: ignore[method-assign]
    result = groups.apply(
        preview["group"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
    )["group"]

    assert result["status"] == "compensated"
    assert result["error_code"] == "IntegrationFlowError"
    assert "secret-value-canary" not in json.dumps(result)
    assert result["children"][0]["rollback_status"] == "rolled_back"

    second_entry = flows.inventory()["catalog"][1]
    second = groups.preview(
        {"catalog_id": second_entry["catalog_id"], "scope": "managed_home"}
    )
    flows._apply_skill = original_apply  # type: ignore[method-assign]
    original_rollback = flows.rollback

    def fail_codex(flow_id):
        if flows.get(flow_id).target_id == "codex-skill":
            raise RuntimeError("drift detail")
        return original_rollback(flow_id)

    flows.rollback = fail_codex  # type: ignore[method-assign]
    applied = groups.apply(
        second["group"]["id"],
        plan_id=second["plan"]["plan_id"],
        authority="test-operator",
    )["group"]
    repair = groups.rollback(applied["id"])["group"]
    assert repair["status"] == "repair_required"
    assert repair["repair_actions"] == [
        f"retry-safe-rollback:codex-skill:{repair['children'][0]['flow_id']}"
    ]

    flows.rollback = original_rollback  # type: ignore[method-assign]
    restarted = GroupedIntegrationService(tmp_path, flow_service=flows)
    recovered = restarted.recover(applied["id"])["group"]
    assert recovered["status"] == "rolled_back"
    assert recovered["repair_actions"] == []


async def test_external_mcp_group_expands_native_homes_and_harness_inventory(tmp_path):
    drivers = {
        target: _FakeMCPDriver(target)
        for target in ("codex-mcp", "claude-mcp", "gemini-mcp")
    }
    flows = IntegrationFlowService(
        tmp_path,
        skill_capability_provider=lambda target_id: _supported(target_id),
        mcp_driver_provider=drivers.__getitem__,
    )

    async def fetch_page(**_kwargs):
        return {
            "servers": [{"server": _remote_server(), "_meta": _official_metadata()}],
            "metadata": {"count": 1},
        }

    synced = await sync_official_mcp_registry(flows.catalog, fetch_page=fetch_page)
    assert synced.success is True
    entry = next(item for item in flows.catalog.list() if item.mcp_response is not None)
    groups = GroupedIntegrationService(tmp_path, flow_service=flows)
    preview = groups.preview(
        {
            "catalog_id": entry.catalog_id,
            "scope": "managed_home",
            "configuration": {
                "selection": {
                    "kind": "remote",
                    "headers": {
                        "Authorization": {
                            "kind": "environment",
                            "name": "REMOTE_MCP_TOKEN",
                        }
                    },
                }
            },
        }
    )

    assert preview["plan"]["target_ids"] == [
        "codex-mcp",
        "claude-mcp",
        "gemini-mcp",
        "harness-managed-mcp",
    ]
    assert preview["plan"]["permissions"] == {
        "network": True,
        "native_consent": True,
        "user_home": False,
    }
    with pytest.raises(IntegrationGroupConflictError, match="network"):
        groups.apply(
            preview["group"]["id"],
            plan_id=preview["plan"]["plan_id"],
            authority="test-operator",
        )

    applied = groups.apply(
        preview["group"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
        allow_network=True,
        native_consent_acknowledged=True,
    )["group"]
    assert applied["status"] == "verified"
    inventory = json.loads(
        (tmp_path / "integrations" / "managed_mcp_inventory.json").read_text()
    )
    assert len(inventory["entries"]) == 1
    assert "REMOTE_MCP_TOKEN" in json.dumps(inventory)
    assert "secret-value-canary" not in json.dumps(inventory)

    rolled_back = groups.rollback(applied["id"])["group"]
    assert rolled_back["status"] == "rolled_back"
    inventory = json.loads(
        (tmp_path / "integrations" / "managed_mcp_inventory.json").read_text()
    )
    assert inventory["entries"] == {}
    assert all(driver.rolled_back for driver in drivers.values())


async def test_extension_pack_compiles_skill_and_mcp_for_every_supported_target(
    tmp_path,
):
    drivers = {
        target: _FakeMCPDriver(target)
        for target in ("codex-mcp", "claude-mcp", "gemini-mcp")
    }
    flows = IntegrationFlowService(
        tmp_path,
        skill_capability_provider=_supported,
        mcp_driver_provider=drivers.__getitem__,
    )
    flows.inventory()
    mcp_entry = await _sync_mcp_entry(flows)
    skill_entry = next(
        item for item in flows.catalog.list() if item.package is not None
    )
    groups = GroupedIntegrationService(tmp_path, flow_service=flows)

    preview = groups.preview(
        _pack_request(skill_entry.catalog_id, mcp_entry.catalog_id)
    )

    assert preview["group"]["component"] == "extension_pack"
    assert preview["group"]["catalog_ids"] == {
        "skill": skill_entry.catalog_id,
        "mcp": mcp_entry.catalog_id,
    }
    assert preview["plan"]["target_ids"] == [
        "codex-skill",
        "codex-mcp",
        "claude-skill",
        "claude-mcp",
        "gemini-skill",
        "gemini-mcp",
        "harness-managed-mcp",
    ]
    assert [item["status"] for item in preview["plan"]["compatibility"]] == [
        "supported",
        "supported",
        "supported",
        "supported",
    ]
    assert preview["plan"]["compatibility"][-1]["components"]["skill"] == {
        "status": "not_applicable",
        "target_id": None,
        "reason_code": "target_has_no_skill_surface",
        "content_free": True,
    }
    assert preview["plan"]["atomicity"] == "recoverable_compensating_transaction"
    assert preview["plan"]["permissions"] == {
        "network": True,
        "native_consent": True,
        "user_home": False,
    }

    applied = groups.apply(
        preview["group"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="pack-operator",
        allow_network=True,
        native_consent_acknowledged=True,
    )["group"]
    assert applied["status"] == "verified"
    assert len(applied["children"]) == 7
    assert groups.rollback(applied["id"])["group"]["status"] == "rolled_back"


async def test_extension_pack_matrix_excludes_incompatible_provider_without_leak(
    tmp_path,
):
    drivers = {
        target: _FakeMCPDriver(target)
        for target in ("codex-mcp", "claude-mcp", "gemini-mcp")
    }

    def capabilities(target_id: str) -> SkillCapabilitySnapshot:
        if target_id == "claude-skill":
            return SkillCapabilitySnapshot(
                target_id=target_id,
                status=SkillTargetStatus.BLOCKED,
                version=None,
                command=(),
                supports_discovery=False,
                supports_activation=False,
                discovery_method="documented_filesystem",
                activation_mode=SkillActivationMode.PROVIDER_CONSENT,
                reason_code="secret-value-canary",
            )
        return _supported(target_id)

    flows = IntegrationFlowService(
        tmp_path,
        skill_capability_provider=capabilities,
        mcp_driver_provider=drivers.__getitem__,
    )
    flows.inventory()
    mcp_entry = await _sync_mcp_entry(flows)
    skill_entry = next(
        item for item in flows.catalog.list() if item.package is not None
    )
    preview = GroupedIntegrationService(tmp_path, flow_service=flows).preview(
        _pack_request(skill_entry.catalog_id, mcp_entry.catalog_id)
    )

    claude = preview["plan"]["compatibility"][1]
    assert claude["status"] == "unsupported"
    assert claude["included"] is False
    assert claude["components"]["skill"]["reason_code"] == (
        "incompatible_or_unavailable"
    )
    assert "claude-skill" not in preview["plan"]["target_ids"]
    assert "claude-mcp" not in preview["plan"]["target_ids"]
    assert "secret-value-canary" not in json.dumps(preview)
    assert len(flows.list()) == len(preview["group"]["children"])


async def _sync_mcp_entry(flows: IntegrationFlowService):
    async def fetch_page(**_kwargs):
        return {
            "servers": [{"server": _remote_server(), "_meta": _official_metadata()}],
            "metadata": {"count": 1},
        }

    synced = await sync_official_mcp_registry(flows.catalog, fetch_page=fetch_page)
    assert synced.success is True
    return next(item for item in flows.catalog.list() if item.mcp_response is not None)


def _pack_request(skill_catalog_id: str, mcp_catalog_id: str) -> dict:
    return {
        "component": "extension_pack",
        "pack_id": "example.portable-pack",
        "pack_version": "1.0.0",
        "skill_catalog_id": skill_catalog_id,
        "mcp_catalog_id": mcp_catalog_id,
        "scope": "managed_home",
        "target_mode": "all_supported",
        "mcp_configuration": {
            "selection": {
                "kind": "remote",
                "headers": {
                    "Authorization": {
                        "kind": "environment",
                        "name": "REMOTE_MCP_TOKEN",
                    }
                },
            }
        },
    }


def _flows(tmp_path) -> IntegrationFlowService:
    return IntegrationFlowService(
        tmp_path,
        skill_capability_provider=lambda target_id: SkillCapabilitySnapshot(
            target_id=target_id,
            status=SkillTargetStatus.SUPPORTED,
            version="test",
            command=(target_id.removesuffix("-skill"),),
            supports_discovery=True,
            supports_activation=True,
            discovery_method="documented_filesystem",
            activation_mode=SkillActivationMode.IMPLICIT_OR_EXPLICIT,
        ),
    )


def _supported(target_id: str) -> SkillCapabilitySnapshot:
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


class _FakeMCPDriver:
    def __init__(self, target_id: str) -> None:
        self.target_id = target_id
        self.rolled_back: list[str] = []

    def preview_install(self, request):
        digest = hashlib.sha256(
            f"{self.target_id}:{request.package.id}:{request.root}".encode()
        ).hexdigest()
        return SimpleNamespace(
            plan_id=f"plan_{digest}",
            installation=SimpleNamespace(
                mutations=(
                    SimpleNamespace(
                        current_sha256=None,
                        relative_path=f"{self.target_id}.config",
                    ),
                )
            ),
        )

    def install(self, _request, plan, _approval):
        return SimpleNamespace(transaction_id=f"txn_{plan.plan_id[5:37]}")

    def verify(self, transaction_id):
        return SimpleNamespace(transaction_id=transaction_id, status="healthy")

    def rollback(self, transaction_id):
        self.rolled_back.append(transaction_id)


def _remote_server():
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "io.example/remote-tools",
        "title": "Remote Tools",
        "description": "Remote fixture MCP server.",
        "version": "2.0.0",
        "remotes": [
            {
                "type": "streamable-http",
                "url": "https://mcp.example.com/v1",
                "headers": [
                    {
                        "name": "Authorization",
                        "isRequired": True,
                        "isSecret": True,
                    }
                ],
            }
        ],
    }


def _official_metadata():
    return {
        "io.modelcontextprotocol.registry/official": {
            "status": "active",
            "isLatest": True,
            "publishedAt": "2026-07-20T09:00:00Z",
            "updatedAt": "2026-07-20T09:00:00Z",
        }
    }
