from __future__ import annotations

import json
import hashlib
import stat
from types import SimpleNamespace

import pytest

from gpt2giga_harness.codex_plugin_target import CODEX_PLUGIN_TARGET_ID
from gpt2giga_harness.integration_catalog import CatalogSourceType
from gpt2giga_harness.integration_flows import (
    IntegrationFlowConflictError,
    IntegrationFlowError,
    IntegrationFlowService,
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


def test_raw_mcp_flow_shows_risk_installs_and_rolls_back(tmp_path):
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

    installed = service.apply(
        preview["flow"]["id"],
        plan_id=plan["plan_id"],
        authority="test-operator",
        native_consent_acknowledged=True,
    )
    assert installed["flow"]["status"] == "verified"
    assert installed["flow"]["verification_status"] == "native_verified"
    assert installed["flow"]["rollback_available"] is True
    assert service.rollback(installed["flow"]["id"])["flow"]["status"] == "rolled_back"


def test_raw_mcp_flow_installs_into_managed_harness_inventory(tmp_path):
    service = _service(tmp_path)
    preview = service.preview(
        {
            "source": "raw_descriptor",
            "package_id": "custom-mcp",
            "target_id": "harness-managed-mcp",
            "scope": "managed_home",
            "configuration": {
                "transport": "stdio",
                "command": "custom-mcp",
                "args": ["--stdio"],
            },
        }
    )

    assert preview["plan"]["target"]["execution_owner"] == (
        "harness_managed_mcp_inventory"
    )
    installed = service.apply(
        preview["flow"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
        native_consent_acknowledged=True,
    )

    assert installed["flow"]["status"] == "verified"
    assert installed["flow"]["verification_status"] == "inventory_verified"
    assert service.rollback(installed["flow"]["id"])["flow"]["status"] == (
        "rolled_back"
    )


@pytest.mark.parametrize(
    ("target_id", "transport"),
    [
        ("codex-mcp", "streamable_http"),
        ("claude-mcp", "streamable_http"),
        ("gemini-mcp", "sse"),
        ("harness-managed-mcp", "streamable_http"),
    ],
)
def test_typed_remote_mcp_preview_is_normalized_and_content_free(
    tmp_path,
    target_id,
    transport,
):
    service = _service(tmp_path)
    preview = service.preview(
        {
            "source": "raw_descriptor",
            "package_id": f"typed-{target_id}",
            "target_id": target_id,
            "scope": "managed_home",
            "configuration": {
                "schema_version": 1,
                "transport": transport,
                "remote": {
                    "url": "https://MCP.EXAMPLE/v1?tenant=fixture",
                    "headers": {
                        "X-Tenant": {
                            "kind": "environment",
                            "name": "TENANT_ID",
                        }
                    },
                },
            },
        }
    )

    configuration = preview["plan"]["configuration"]["preview"]
    assert configuration["transport"] == transport
    assert configuration["target"]["url"] == ("https://mcp.example/v1?tenant=fixture")
    assert configuration["secret_references"] == [
        {
            "field": "header",
            "name": "X-Tenant",
            "reference": {
                "schema_version": 1,
                "kind": "environment",
                "name": "TENANT_ID",
                "service": None,
                "account": None,
                "expires_at": None,
                "cache_ttl_seconds": 0,
            },
        }
    ]
    assert "fixture-secret-value" not in json.dumps(preview)


def test_typed_project_stdio_preview_resolves_cwd_inside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    service = _service(tmp_path / "data")

    preview = service.preview(
        {
            "source": "raw_descriptor",
            "package_id": "project-mcp",
            "target_id": "codex-mcp",
            "scope": "project",
            "workspace": str(workspace),
            "configuration": {
                "schema_version": 1,
                "transport": "stdio",
                "stdio": {
                    "executable": "fixture-mcp",
                    "argv": ["--stdio"],
                    "cwd": "tools/server",
                    "environment": {
                        "MCP_TOKEN": {
                            "kind": "environment",
                            "name": "MCP_TOKEN",
                        }
                    },
                },
            },
        }
    )

    target = preview["plan"]["configuration"]["preview"]["target"]
    assert target["command"] == "fixture-mcp"
    assert target["args"] == ["--stdio"]
    assert target["cwd"] == str(workspace / "tools" / "server")
    assert target["env_vars"] == ["MCP_TOKEN"]


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


def test_git_plugin_flow_previews_applies_verifies_and_rolls_back(tmp_path):
    plugin_driver = _FakePluginDriver()
    service = IntegrationFlowService(
        tmp_path,
        skill_capability_provider=_supported_skill,
        plugin_driver_provider=lambda _target, _root, _scope: plugin_driver,
    )
    package = _plugin_package()
    entry = service.catalog.import_package(
        package,
        source_id="git-test",
        source_type=CatalogSourceType.GIT,
    )

    preview = service.preview(
        {
            "source": "catalog",
            "catalog_id": entry.catalog_id,
            "target_id": CODEX_PLUGIN_TARGET_ID,
            "scope": "managed_home",
            "configuration": {"plugin_name": "review-tools"},
        }
    )

    assert preview["plan"]["target"]["executable"] is True
    assert preview["plan"]["target"]["execution_owner"] == (
        "provider_native_target_driver"
    )
    assert preview["plan"]["configuration"]["diff"] == [
        "native-command:codex-plugin-install"
    ]
    with pytest.raises(IntegrationFlowConflictError, match="native consent requires"):
        service.apply(
            preview["flow"]["id"],
            plan_id=preview["plan"]["plan_id"],
            authority="test-operator",
        )

    applied = service.apply(
        preview["flow"]["id"],
        plan_id=preview["plan"]["plan_id"],
        authority="test-operator",
        native_consent_acknowledged=True,
    )

    assert applied["flow"]["status"] == "verified"
    assert applied["flow"]["verification_status"] == "native_verified"
    assert plugin_driver.installed is True
    assert service.rollback(applied["flow"]["id"])["flow"]["status"] == ("rolled_back")
    assert plugin_driver.rolled_back is True


def _service(tmp_path) -> IntegrationFlowService:
    drivers = {
        target: _FakeMCPDriver(target)
        for target in ("codex-mcp", "claude-mcp", "gemini-mcp")
    }
    return IntegrationFlowService(
        tmp_path,
        skill_capability_provider=_supported_skill,
        mcp_driver_provider=drivers.__getitem__,
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


class _FakeMCPDriver:
    def __init__(self, target_id: str) -> None:
        self.target_id = target_id

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

    def rollback(self, _transaction_id):
        return None


class _FakePluginDriver:
    def __init__(self) -> None:
        self.installed = False
        self.rolled_back = False

    def preview_install(self, request):
        digest = hashlib.sha256(
            f"{request.package.id}:{request.root}:{request.plugin_name}".encode()
        ).hexdigest()
        return SimpleNamespace(
            plan_id=f"plan_{digest}",
            command_ids=("codex-plugin-install",),
            restart_required=True,
        )

    def install(self, _request, _plan, _approval):
        self.installed = True
        return SimpleNamespace()

    def verify(self, _request):
        return SimpleNamespace(status="healthy")

    def rollback(self, _request):
        self.rolled_back = True
        return SimpleNamespace()


def _plugin_package() -> IntegrationPackage:
    return IntegrationPackage(
        id="example.review-tools",
        version="1.0.0",
        publisher="example",
        license="MIT",
        source_type=IntegrationSourceType.GIT,
        source="https://github.com/example/review-tools.git",
        immutable_ref="b" * 40,
        checksum="sha256:" + "c" * 64,
        components=(
            IntegrationComponent(
                id="review-tools",
                type=IntegrationComponentType.PLUGIN,
                portable=False,
            ),
        ),
        requirements=(),
        overlays=(
            IntegrationTargetOverlay(
                target_id=CODEX_PLUGIN_TARGET_ID,
                component_ids=("review-tools",),
            ),
        ),
        compatibility=(IntegrationCompatibility(target_id=CODEX_PLUGIN_TARGET_ID),),
        scopes=(InstallationScope.MANAGED_HOME,),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("plugin-discovery",),
        rollback_steps=("plugin-remove",),
    )
