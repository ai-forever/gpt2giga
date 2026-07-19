from __future__ import annotations

import json
import stat

import pytest

from gpt2giga_harness.integration_flows import (
    IntegrationFlowConflictError,
    IntegrationFlowError,
    IntegrationFlowService,
)
from gpt2giga_harness.portable_skills import (
    CODEX_SKILL_TARGET_ID,
    SkillActivationMode,
    SkillCapabilitySnapshot,
    SkillTargetStatus,
)


def test_inventory_exposes_all_add_sources_targets_and_content_free_catalog(tmp_path):
    service = _service(tmp_path)

    inventory = service.inventory()

    assert {item["id"] for item in inventory["sources"]} == {
        "catalog",
        "marketplace",
        "git",
        "local",
        "package",
        "raw_descriptor",
    }
    target_ids = {item["id"] for item in inventory["targets"]}
    assert {
        "codex-mcp",
        "claude-mcp",
        "gemini-mcp",
        "codex-skill",
        "claude-skill",
        "gemini-skill",
        "codex-plugin",
        "claude-plugin",
        "gemini-extension",
        "harness-adapter-package",
    } <= target_ids
    assert [item["package_id"] for item in inventory["catalog"]] == [
        "gpt2giga.builtin.find-skills",
        "gpt2giga.builtin.skill-creator",
        "gpt2giga.builtin.skill-installer",
    ]
    assert all(item["install_authorized"] is False for item in inventory["catalog"])
    assert inventory["content_free"] is True


def test_catalog_skill_flow_previews_applies_verifies_and_rolls_back(tmp_path):
    service = _service(tmp_path)
    entry = service.inventory()["catalog"][0]

    preview = service.preview(
        {
            "source": "catalog",
            "catalog_id": entry["catalog_id"],
            "target_id": CODEX_SKILL_TARGET_ID,
            "scope": "managed_home",
            "configuration": {},
        }
    )

    plan = preview["plan"]
    assert plan["target"] == {
        "id": "codex-skill",
        "revision": "1",
        "scope": "managed_home",
        "execution_owner": "workbench_transactional_installer",
        "executable": True,
    }
    assert plan["risk"]["install_authorized"] is False
    assert plan["configuration"]["diff"]
    assert plan["verification_steps"] == ["skill-discovery"]
    assert preview["flow"]["status"] == "awaiting_approval"

    applied = service.apply(
        preview["flow"]["id"],
        plan_id=plan["plan_id"],
        authority="test-operator",
    )["flow"]

    assert applied["status"] == "verified"
    assert applied["verification_status"] == "discovered"
    assert applied["rollback_available"] is True
    assert [item["stage"] for item in applied["events"]] == [
        "preview",
        "apply",
        "verify",
    ]
    assert (
        service.apply(
            applied["id"],
            plan_id=plan["plan_id"],
            authority="test-operator",
        )["flow"]
        == applied
    )

    rolled_back = service.rollback(applied["id"])["flow"]
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["verification_status"] == "rolled_back"
    assert rolled_back["rollback_available"] is False
    assert service.get(applied["id"]).status.value == "rolled_back"

    state_path = tmp_path / "integrations" / "flows.json"
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["schema_version"] == 1
    assert "content_free" in state["flows"][0]


def test_raw_mcp_flow_shows_risk_and_returns_explicit_native_handoff(tmp_path):
    service = _service(tmp_path)
    preview = service.preview(
        {
            "source": "raw_descriptor",
            "package_id": "issue-mcp",
            "target_id": "claude-mcp",
            "scope": "managed_home",
            "configuration": {
                "transport": "stdio",
                "command": "issue-mcp",
                "args": ["--stdio"],
                "env_vars": ["ISSUE_TOKEN"],
            },
        }
    )

    plan = preview["plan"]
    assert plan["package"]["source_type"] == "raw_mcp"
    assert plan["permissions"]["native_consent"] is True
    assert {item["type"] for item in plan["permissions"]["requirements"]} == {
        "command",
        "secret",
    }
    assert plan["target"]["execution_owner"] == "provider_native_target_driver"
    with pytest.raises(IntegrationFlowConflictError, match="native consent requires"):
        service.apply(
            preview["flow"]["id"],
            plan_id=plan["plan_id"],
            authority="test-operator",
        )

    handoff = service.apply(
        preview["flow"]["id"],
        plan_id=plan["plan_id"],
        authority="test-operator",
        native_consent_acknowledged=True,
    )
    assert handoff["flow"]["status"] == "handoff_required"
    assert handoff["flow"]["verification_status"] == "provider_owned"
    assert handoff["handoff"]["mutation_performed"] is False


def test_flow_rejects_secret_values_stale_approval_and_records_failure(tmp_path):
    service = _service(tmp_path)
    entry = service.inventory()["catalog"][0]
    with pytest.raises(ValueError, match="references, not secrets"):
        service.preview(
            {
                "source": "catalog",
                "catalog_id": entry["catalog_id"],
                "target_id": "codex-skill",
                "scope": "managed_home",
                "configuration": {"api_token": "do-not-store"},
            }
        )

    preview = service.preview(
        {
            "source": "catalog",
            "catalog_id": entry["catalog_id"],
            "target_id": "codex-skill",
            "scope": "managed_home",
        }
    )
    with pytest.raises(IntegrationFlowConflictError, match="does not match"):
        service.apply(
            preview["flow"]["id"],
            plan_id="plan_" + "0" * 64,
            authority="test-operator",
        )

    def fail_apply(*args, **kwargs):
        raise RuntimeError("secret-bearing native output")

    service._apply_skill = fail_apply  # type: ignore[method-assign]
    with pytest.raises(IntegrationFlowError, match="details were omitted") as exc:
        service.apply(
            preview["flow"]["id"],
            plan_id=preview["plan"]["plan_id"],
            authority="test-operator",
        )
    assert "secret-bearing" not in str(exc.value)
    failed = service.get(preview["flow"]["id"])
    assert failed.status.value == "failed"
    assert failed.error_code == "RuntimeError"
    assert failed.events[-1].stage == "failure"


def _service(tmp_path) -> IntegrationFlowService:
    return IntegrationFlowService(
        tmp_path,
        skill_capability_provider=_supported_skill,
    )


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
