from __future__ import annotations

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.integration_flows import IntegrationFlowService
from gpt2giga_harness.portable_skills import (
    SkillActivationMode,
    SkillCapabilitySnapshot,
    SkillTargetStatus,
)
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app


def test_integration_api_keeps_preview_apply_progress_and_rollback_equivalent(
    tmp_path,
):
    service = IntegrationFlowService(
        tmp_path / "data",
        skill_capability_provider=_supported_skill,
    )
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
            integration_flow_service=service,
        )
    )
    inventory = client.get("/api/integrations")
    entry = inventory.json()["catalog"][0]

    preview = client.post(
        "/api/integrations/preview",
        json={
            "source": "catalog",
            "catalog_id": entry["catalog_id"],
            "target_id": "codex-skill",
            "scope": "managed_home",
        },
    )

    assert inventory.status_code == 200
    assert preview.status_code == 200
    flow = preview.json()["flow"]
    plan = preview.json()["plan"]
    read_back = client.get(f"/api/integrations/flows/{flow['id']}")
    assert read_back.json()["flow"] == flow

    stale = client.post(
        f"/api/integrations/flows/{flow['id']}/apply",
        json={"plan_id": "plan_" + "0" * 64, "authority": "api-operator"},
    )
    assert stale.status_code == 409

    applied = client.post(
        f"/api/integrations/flows/{flow['id']}/apply",
        json={"plan_id": plan["plan_id"], "authority": "api-operator"},
    )
    assert applied.status_code == 200
    assert applied.json()["flow"]["status"] == "verified"
    assert applied.json()["flow"]["content_free"] is True

    rolled_back = client.post(
        f"/api/integrations/flows/{flow['id']}/rollback",
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["flow"]["status"] == "rolled_back"


def test_integration_api_validates_fields_and_never_returns_secret_payloads(tmp_path):
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
        )
    )

    invalid = client.post(
        "/api/integrations/preview",
        json={
            "source": "raw_descriptor",
            "package_id": "unsafe-mcp",
            "target_id": "codex-mcp",
            "scope": "managed_home",
            "configuration": {
                "transport": "stdio",
                "command": "unsafe-mcp",
                "access_token": "secret-canary",
            },
        },
    )

    assert invalid.status_code == 422
    assert "secret-canary" not in invalid.text
    assert client.get("/api/integrations/flows/flow_" + "0" * 32).status_code == 404


def test_group_api_keeps_all_target_preview_apply_recovery_and_rollback_equivalent(
    tmp_path,
):
    service = IntegrationFlowService(
        tmp_path / "data",
        skill_capability_provider=_supported_skill,
    )
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
            integration_flow_service=service,
        )
    )
    entry = client.get("/api/integrations").json()["catalog"][0]
    preview = client.post(
        "/api/integrations/groups/preview",
        json={
            "source": "catalog",
            "catalog_id": entry["catalog_id"],
            "scope": "managed_home",
            "target_mode": "all_supported",
        },
    )
    assert preview.status_code == 200
    group = preview.json()["group"]
    plan = preview.json()["plan"]
    assert plan["target_ids"] == ["codex-skill", "claude-skill", "gemini-skill"]
    assert (
        client.get(f"/api/integrations/groups/{group['id']}").json()["group"] == group
    )

    stale = client.post(
        f"/api/integrations/groups/{group['id']}/apply",
        json={"plan_id": "plan_" + "0" * 64, "authority": "api-operator"},
    )
    assert stale.status_code == 409
    applied = client.post(
        f"/api/integrations/groups/{group['id']}/apply",
        json={"plan_id": plan["plan_id"], "authority": "api-operator"},
    )
    assert applied.status_code == 200
    assert applied.json()["group"]["status"] == "verified"
    rolled_back = client.post(
        f"/api/integrations/groups/{group['id']}/rollback",
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["group"]["status"] == "rolled_back"


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
