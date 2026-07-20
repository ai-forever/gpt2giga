from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from gpt2giga_harness.claude_mcp_target import (
    CLAUDE_MCP_TARGET_ID,
    ClaudeCommandResult,
    ClaudeMCPRequest,
    ClaudeMCPServerSpec,
    ClaudeMCPTargetDriver,
    ClaudeMCPTransport,
    claude_mcp_target_plugin,
)
from gpt2giga_harness.integration_installer import (
    InstallationApproval,
    InstallationConflictError,
)
from gpt2giga_harness.integration_packages import (
    ExtensionTargetRegistry,
    InstallationScope,
    IntegrationCompatibility,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationSourceType,
    IntegrationUpdatePolicy,
)


_DIGEST = "sha256:" + "b" * 64


class FakeClaude:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path | None, dict[str, str]]] = []

    def __call__(self, argv, env, cwd, _timeout):
        self.calls.append((argv, cwd, dict(env)))
        if argv[-1] == "--version":
            return ClaudeCommandResult(0, "2.1.212 (Claude Code)\n")
        if argv[-1] == "--help" and "mcp" not in argv:
            return ClaudeCommandResult(
                0,
                "Options: --mcp-config --strict-mcp-config --remote-control\n",
            )
        if argv[-2:] == ("mcp", "--help"):
            return ClaudeCommandResult(0, "Commands: add get list remove login\n")
        if argv[-3:] == ("mcp", "add", "--help"):
            return ClaudeCommandResult(
                0,
                "Options: --scope local, user, or project --transport stdio,http\n",
            )
        if "mcp" in argv and "get" in argv:
            assert cwd is not None
            name = argv[-1]
            config = json.loads((cwd / ".mcp.json").read_text(encoding="utf-8"))
            server = config.get("mcpServers", {}).get(name)
            if server is None:
                return ClaudeCommandResult(
                    1,
                    f'No MCP server named "{name}". Run `claude mcp add` to add one.\n',
                )
            return ClaudeCommandResult(
                0,
                f"{name}:\n"
                "  Scope: Project config (shared via .mcp.json)\n"
                "  Status: Pending approval (run `claude` to approve)\n"
                f"  Type: {server['type']}\n",
            )
        raise AssertionError(f"unexpected Claude argv: {argv!r}")


def test_claude_mcp_lifecycle_is_exact_reversible_and_provider_owned(tmp_path):
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "claude" / "homes" / "fixture"
    root.mkdir(parents=True)
    config_path = root / ".mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "foreign": {
                        "type": "stdio",
                        "command": "foreign-mcp",
                        "args": [],
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    original = json.loads(config_path.read_text(encoding="utf-8"))
    codex_canary = root / ".codex" / "config.toml"
    gemini_canary = root / ".gemini" / "settings.json"
    codex_canary.parent.mkdir()
    gemini_canary.parent.mkdir()
    codex_canary.write_text('model = "unchanged"\n', encoding="utf-8")
    gemini_canary.write_text('{"unchanged":true}\n', encoding="utf-8")

    fake = FakeClaude()
    driver = ClaudeMCPTargetDriver(data_dir, command_runner=fake)
    request = _request(root)
    plan = driver.preview_install(request)
    installed = driver.install(
        request,
        plan,
        InstallationApproval(plan.plan_id, "test-operator"),
    )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["mcpServers"]["foreign"] == original["mcpServers"]["foreign"]
    assert config["mcpServers"][request.package.id] == {
        "type": "stdio",
        "command": "fixture-mcp",
        "args": ["--readonly"],
        "env": {"FIXTURE_TOKEN": "${FIXTURE_TOKEN}"},
    }
    assert "secret-value-canary" not in config_path.read_text(encoding="utf-8")
    health = driver.health(installed.transaction_id)
    assert health.status == "awaiting_native_consent"
    assert health.native_cli_discovered is True
    assert health.native_consent_required is True
    assert health.auth_ownership == "claude_code"
    assert health.consent_ownership == "claude_code"
    assert driver.discover_installed()[0].current is True

    handoff = driver.preview_handoff(installed.transaction_id, workspace=tmp_path)
    assert handoff.argv == (
        "claude",
        "--mcp-config",
        str(config_path),
        "--strict-mcp-config",
    )
    assert handoff.cwd == tmp_path
    assert handoff.provider_ui_handoff is True
    assert handoff.embedded_execution is False

    disable_plan = driver.preview_disable(request)
    disabled = driver.disable(
        request,
        disable_plan,
        InstallationApproval(disable_plan.plan_id, "test-operator"),
    )
    assert driver.health(disabled.transaction_id).status == "disabled"
    assert (
        request.package.id
        not in json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]
    )

    enable_plan = driver.preview_enable(request)
    enabled = driver.enable(
        request,
        enable_plan,
        InstallationApproval(enable_plan.plan_id, "test-operator"),
    )
    assert driver.health(enabled.transaction_id).status == "awaiting_native_consent"

    updated_request = replace(
        request,
        package=replace(request.package, version="2.0.0"),
        server=replace(request.server, args=("--readonly", "--v2")),
    )
    update_plan = driver.preview_update(updated_request)
    updated = driver.update(
        updated_request,
        update_plan,
        InstallationApproval(update_plan.plan_id, "test-operator"),
    )
    assert driver.discover_installed()[0].package_version == "2.0.0"
    assert "--v2" in config_path.read_text(encoding="utf-8")

    rolled_back = driver.rollback(updated.transaction_id)
    assert rolled_back.status == "rolled_back"
    assert driver.discover_installed()[0].package_version == "1.0.0"
    assert "--v2" not in config_path.read_text(encoding="utf-8")

    current = driver.discover_installed()[0]
    uninstall_plan = driver.preview_uninstall(current.transaction_id)
    uninstalled = driver.uninstall(
        uninstall_plan,
        InstallationApproval(uninstall_plan.plan_id, "test-operator"),
    )
    assert uninstalled.status == "rolled_back"
    assert json.loads(config_path.read_text(encoding="utf-8")) == original
    assert driver.discover_installed() == ()
    assert codex_canary.read_text(encoding="utf-8") == 'model = "unchanged"\n'
    assert gemini_canary.read_text(encoding="utf-8") == '{"unchanged":true}\n'


def test_probe_registry_project_handoff_and_user_scope_boundary(tmp_path):
    fake = FakeClaude()
    project = tmp_path / "project"
    project.mkdir()
    driver = ClaudeMCPTargetDriver(
        tmp_path / "data",
        project_roots=(project,),
        command_runner=fake,
    )

    probe = driver.probe_target()
    registry = ExtensionTargetRegistry()
    registry.register(claude_mcp_target_plugin(lambda: driver))

    assert probe.status == "supported"
    assert probe.version == "2.1.212 (Claude Code)"
    assert set(probe.capabilities) == {
        "mcp_add",
        "mcp_get",
        "mcp_list",
        "mcp_remove",
        "mcp_project_scope",
        "mcp_user_scope",
        "mcp_config",
        "strict_mcp_config",
    }
    assert registry.create_driver(CLAUDE_MCP_TARGET_ID) is driver
    assert all(
        "gigaloom-claude-mcp-probe-" in call[2]["CLAUDE_CONFIG_DIR"]
        for call in fake.calls
    )

    request = _request(project, scope=InstallationScope.PROJECT)
    plan = driver.preview_install(request)
    installed = driver.install(
        request,
        plan,
        InstallationApproval(plan.plan_id, "test-operator"),
    )
    assert (project / ".mcp.json").stat().st_mode & 0o777 == 0o644
    handoff = driver.preview_handoff(installed.transaction_id)
    assert handoff.argv == ("claude",)
    assert handoff.cwd == project.resolve()
    with pytest.raises(ValueError, match="workspace must equal"):
        driver.preview_handoff(installed.transaction_id, workspace=tmp_path)

    with pytest.raises(ValueError, match="native handoff"):
        _request(tmp_path / "fake-home", scope=InstallationScope.USER_HOME)


def test_claude_mcp_rejects_secrets_invalid_config_and_foreign_collision(tmp_path):
    with pytest.raises(ValueError, match="secret material"):
        ClaudeMCPServerSpec(
            name="example.claude-mcp",
            transport=ClaudeMCPTransport.STDIO,
            command="fixture-mcp",
            args=("api_key=secret-value-canary",),
        )
    with pytest.raises(ValueError, match="HTTPS"):
        ClaudeMCPServerSpec(
            name="example.claude-mcp",
            transport=ClaudeMCPTransport.HTTP,
            url="http://mcp.example/mcp",
        )

    data_dir = tmp_path / "data"
    root = data_dir / "native" / "claude" / "homes" / "fixture"
    root.mkdir(parents=True)
    (root / ".mcp.json").write_text(
        '{"mcpServers":{"example.claude-mcp":{"type":"stdio",'
        '"command":"foreign","args":[]}}}\n',
        encoding="utf-8",
    )
    driver = ClaudeMCPTargetDriver(data_dir, command_runner=FakeClaude())
    with pytest.raises(InstallationConflictError, match="already owned"):
        driver.preview_install(_request(root))

    duplicate = data_dir / "native" / "claude" / "homes" / "duplicate"
    duplicate.mkdir()
    (duplicate / ".mcp.json").write_text(
        '{"mcpServers":{},"mcpServers":{}}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate keys"):
        driver.preview_install(_request(duplicate))

    secret = data_dir / "native" / "claude" / "homes" / "secret"
    secret.mkdir()
    (secret / ".mcp.json").write_text(
        '{"mcpServers":{"foreign":{"type":"http",'
        '"url":"https://mcp.example/mcp",'
        '"headers":{"Authorization":"Bearer secret-value-canary"}}}}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="secret material"):
        driver.preview_install(_request(secret))


def test_claude_http_spec_uses_reference_only_headers(tmp_path):
    root = tmp_path / "data" / "native" / "claude" / "homes" / "http"
    root.mkdir(parents=True)
    request = ClaudeMCPRequest(
        package=_package(InstallationScope.MANAGED_HOME),
        scope=InstallationScope.MANAGED_HOME,
        root=root,
        server=ClaudeMCPServerSpec(
            name="example.claude-mcp",
            transport=ClaudeMCPTransport.HTTP,
            url="https://mcp.example/mcp?tenant=fixture",
            env_http_headers=(("Authorization", "MCP_AUTH_HEADER"),),
        ),
    )
    driver = ClaudeMCPTargetDriver(tmp_path / "data", command_runner=FakeClaude())
    plan = driver.preview_install(request)
    driver.install(
        request,
        plan,
        InstallationApproval(plan.plan_id, "test-operator"),
    )
    server = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][
        request.package.id
    ]
    assert server == {
        "type": "http",
        "url": "https://mcp.example/mcp?tenant=fixture",
        "headers": {"Authorization": "${MCP_AUTH_HEADER}"},
    }


def _request(
    root: Path,
    *,
    scope: InstallationScope = InstallationScope.MANAGED_HOME,
) -> ClaudeMCPRequest:
    return ClaudeMCPRequest(
        package=_package(scope),
        scope=scope,
        root=root,
        server=ClaudeMCPServerSpec(
            name="example.claude-mcp",
            transport=ClaudeMCPTransport.STDIO,
            command="fixture-mcp",
            args=("--readonly",),
            env_vars=("FIXTURE_TOKEN",),
        ),
    )


def _package(scope: InstallationScope) -> IntegrationPackage:
    return IntegrationPackage(
        id="example.claude-mcp",
        version="1.0.0",
        publisher="example-publisher",
        license="Apache-2.0",
        source_type=IntegrationSourceType.GIT,
        source="https://git.example/integration",
        immutable_ref="commit-cafebabe",
        checksum=_DIGEST,
        components=(
            IntegrationComponent(
                id="portable-mcp",
                type=IntegrationComponentType.MCP,
                portable=True,
            ),
        ),
        requirements=(),
        overlays=(),
        compatibility=(IntegrationCompatibility(target_id=CLAUDE_MCP_TARGET_ID),),
        scopes=(scope,),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("claude-mcp-get", "provider-owned-consent"),
        rollback_steps=("restore-config-snapshot",),
    )
