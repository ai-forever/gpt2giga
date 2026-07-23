from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from gpt2giga_harness.gemini_mcp_target import (
    GEMINI_MCP_TARGET_ID,
    GeminiCommandResult,
    GeminiMCPRequest,
    GeminiMCPServerSpec,
    GeminiMCPTargetDriver,
    GeminiMCPTargetError,
    GeminiMCPTransport,
    gemini_mcp_target_plugin,
)
from gpt2giga_harness.integration_installer import (
    InstallationApproval,
    InstallationConflictError,
    InstallationScopeError,
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


_DIGEST = "sha256:" + "c" * 64


class FakeGemini:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path | None, dict[str, str]]] = []

    def __call__(self, argv, env, cwd, _timeout):
        self.calls.append((argv, cwd, dict(env)))
        if argv[-1] == "--version":
            return GeminiCommandResult(0, "0.46.0\n")
        if argv[-1] == "--help" and "mcp" not in argv:
            return GeminiCommandResult(0, "Options: --acp --allowed-mcp-server-names\n")
        if argv[-2:] == ("mcp", "--help"):
            return GeminiCommandResult(
                0,
                "Commands: add remove list enable disable\n",
            )
        if argv[-3:] == ("mcp", "add", "--help"):
            return GeminiCommandResult(
                0,
                "Options: --scope user,project --transport stdio,sse,http\n",
            )
        if argv[-2:] == ("mcp", "list"):
            assert cwd is not None
            config = json.loads(
                (cwd / ".gemini" / "settings.json").read_text(encoding="utf-8")
            )
            servers = config.get("mcpServers", {})
            if not servers:
                return GeminiCommandResult(0, "No MCP servers configured.\n")
            lines = [
                "Warning: MCP servers are configured but disabled because this "
                "folder is untrusted.",
                "Configured MCP servers:",
            ]
            for name, server in sorted(servers.items()):
                transport = server.get("type", "stdio")
                location = server.get("url") or server.get("command")
                lines.append(f"○ {name}: {location} ({transport}) - Disabled")
            return GeminiCommandResult(0, "\n".join(lines) + "\n")
        raise AssertionError(f"unexpected Gemini argv: {argv!r}")


def test_gemini_mcp_lifecycle_is_exact_reversible_and_transport_truthful(tmp_path):
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "gemini" / "homes" / "fixture"
    config_path = root / ".gemini" / "settings.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "theme": "unchanged",
                "mcpServers": {
                    "foreign": {
                        "command": "foreign-mcp",
                        "args": [],
                        "trust": False,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    original = json.loads(config_path.read_text(encoding="utf-8"))
    codex_canary = root / ".codex" / "config.toml"
    claude_canary = root / ".mcp.json"
    codex_canary.parent.mkdir()
    codex_canary.write_text('model = "unchanged"\n', encoding="utf-8")
    claude_canary.write_text('{"unchanged":true}\n', encoding="utf-8")

    fake = FakeGemini()
    driver = GeminiMCPTargetDriver(data_dir, command_runner=fake)
    request = _request(root)
    plan = driver.preview_install(request)
    installed = driver.install(
        request,
        plan,
        InstallationApproval(plan.plan_id, "test-operator"),
    )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["theme"] == "unchanged"
    assert config["mcpServers"]["foreign"] == original["mcpServers"]["foreign"]
    assert config["mcpServers"][request.package.id] == {
        "command": "fixture-mcp",
        "args": ["--readonly"],
        "cwd": "tools/server",
        "env": {"FIXTURE_TOKEN": "${FIXTURE_TOKEN}"},
        "timeout": 10_000,
        "trust": False,
        "description": "Fixture MCP",
        "includeTools": ["ping"],
        "excludeTools": ["hidden"],
    }
    assert "secret-value-canary" not in config_path.read_text(encoding="utf-8")
    health = driver.health(installed.transaction_id)
    assert health.status == "awaiting_workspace_trust"
    assert health.native_cli_discovered is True
    assert health.native_workspace_trust_required is True
    assert health.native_terminal_status == "disabled_untrusted"
    assert health.acp_transport_supported is False
    assert health.acp_activation == "unsupported_stdio"
    assert driver.discover_installed()[0].current is True

    activation = driver.preview_activation(installed.transaction_id, workspace=tmp_path)
    assert activation.argv == ("gemini",)
    assert activation.cwd == tmp_path
    assert activation.native_terminal_env == (("GEMINI_CLI_HOME", str(root)),)
    assert activation.native_workspace_trust_required is True
    assert activation.acp_transport_supported is False
    assert activation.executes_provider is False
    with pytest.raises(GeminiMCPTargetError, match="does not advertise"):
        driver.acp_server(installed.transaction_id)

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
    assert driver.health(enabled.transaction_id).status == "awaiting_workspace_trust"

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
    assert claude_canary.read_text(encoding="utf-8") == '{"unchanged":true}\n'


def test_probe_registry_project_activation_and_explicit_user_scope(tmp_path):
    fake = FakeGemini()
    project = tmp_path / "project"
    project.mkdir()
    driver = GeminiMCPTargetDriver(
        tmp_path / "data",
        project_roots=(project,),
        command_runner=fake,
    )

    probe = driver.probe_target()
    registry = ExtensionTargetRegistry()
    registry.register(gemini_mcp_target_plugin(lambda: driver))

    assert probe.status == "supported"
    assert probe.version == "0.46.0"
    assert set(probe.capabilities) == {
        "mcp_add",
        "mcp_list",
        "mcp_remove",
        "mcp_enable",
        "mcp_disable",
        "mcp_project_scope",
        "mcp_user_scope",
        "stdio",
        "sse",
        "http",
        "acp",
    }
    assert registry.create_driver(GEMINI_MCP_TARGET_ID) is driver
    assert all("GEMINI_CLI_HOME" in call[2] for call in fake.calls)

    request = _request(project, scope=InstallationScope.PROJECT)
    plan = driver.preview_install(request)
    installed = driver.install(
        request,
        plan,
        InstallationApproval(plan.plan_id, "test-operator"),
    )
    assert (project / ".gemini" / "settings.json").stat().st_mode & 0o777 == 0o644
    activation = driver.preview_activation(installed.transaction_id)
    assert activation.argv == ("gemini",)
    assert activation.cwd == project.resolve()
    assert activation.native_terminal_env == ()
    with pytest.raises(ValueError, match="workspace must equal"):
        driver.preview_activation(installed.transaction_id, workspace=tmp_path)

    user_root = tmp_path / "fake-user-home"
    user_root.mkdir()
    user_request = _request(user_root, scope=InstallationScope.USER_HOME)
    with pytest.raises(InstallationScopeError, match="disabled"):
        driver.preview_install(user_request)

    user_driver = GeminiMCPTargetDriver(
        tmp_path / "user-data",
        user_home_root=user_root,
        allow_user_home=True,
        command_runner=FakeGemini(),
    )
    user_plan = user_driver.preview_install(user_request)
    with pytest.raises(InstallationScopeError, match="approval"):
        user_driver.install(
            user_request,
            user_plan,
            InstallationApproval(user_plan.plan_id, "test-operator"),
        )
    user_driver.install(
        user_request,
        user_plan,
        InstallationApproval(
            user_plan.plan_id,
            "test-operator",
            allow_user_home=True,
        ),
    )


def test_gemini_mcp_rejects_secrets_invalid_config_and_foreign_collision(tmp_path):
    with pytest.raises(ValueError, match="secret material"):
        GeminiMCPServerSpec(
            name="example.gemini-mcp",
            transport=GeminiMCPTransport.STDIO,
            command="fixture-mcp",
            args=("api_key=secret-value-canary",),
        )
    with pytest.raises(ValueError, match="HTTPS"):
        GeminiMCPServerSpec(
            name="example.gemini-mcp",
            transport=GeminiMCPTransport.HTTP,
            url="http://mcp.example/mcp",
        )

    data_dir = tmp_path / "data"
    root = data_dir / "native" / "gemini" / "homes" / "fixture"
    config_path = root / ".gemini" / "settings.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        '{"mcpServers":{"example.gemini-mcp":{"command":"foreign"}}}\n',
        encoding="utf-8",
    )
    driver = GeminiMCPTargetDriver(data_dir, command_runner=FakeGemini())
    with pytest.raises(InstallationConflictError, match="already owned"):
        driver.preview_install(_request(root))

    duplicate = data_dir / "native" / "gemini" / "homes" / "duplicate"
    duplicate_path = duplicate / ".gemini" / "settings.json"
    duplicate_path.parent.mkdir(parents=True)
    duplicate_path.write_text('{"mcpServers":{},"mcpServers":{}}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate keys"):
        driver.preview_install(_request(duplicate))

    secret = data_dir / "native" / "gemini" / "homes" / "secret"
    secret_path = secret / ".gemini" / "settings.json"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text(
        '{"mcpServers":{"foreign":{"type":"http",'
        '"url":"https://mcp.example/mcp",'
        '"headers":{"Authorization":"Bearer secret-value-canary"}}}}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="secret material"):
        driver.preview_install(_request(secret))


@pytest.mark.parametrize("transport", (GeminiMCPTransport.HTTP, GeminiMCPTransport.SSE))
def test_remote_specs_use_references_and_project_exact_acp_payload(tmp_path, transport):
    root = tmp_path / "project"
    root.mkdir()
    request = GeminiMCPRequest(
        package=_package(InstallationScope.PROJECT),
        scope=InstallationScope.PROJECT,
        root=root,
        server=GeminiMCPServerSpec(
            name="example.gemini-mcp",
            transport=transport,
            url="https://mcp.example/mcp?tenant=fixture",
            env_http_headers=(("Authorization", "MCP_AUTH_HEADER"),),
            timeout_ms=5_000,
        ),
    )
    driver = GeminiMCPTargetDriver(
        tmp_path / "data",
        project_roots=(root,),
        command_runner=FakeGemini(),
    )
    plan = driver.preview_install(request)
    installed = driver.install(
        request,
        plan,
        InstallationApproval(plan.plan_id, "test-operator"),
    )
    server = json.loads(
        (root / ".gemini" / "settings.json").read_text(encoding="utf-8")
    )["mcpServers"][request.package.id]
    assert server == {
        "type": transport.value,
        "url": "https://mcp.example/mcp?tenant=fixture",
        "headers": {"Authorization": "${MCP_AUTH_HEADER}"},
        "timeout": 5_000,
        "trust": False,
    }
    health = driver.health(installed.transaction_id)
    assert health.acp_transport_supported is True
    assert health.acp_activation == "session_injected"
    assert driver.acp_server(installed.transaction_id) == {
        "name": request.package.id,
        "type": transport.value,
        "url": "https://mcp.example/mcp?tenant=fixture",
        "headers": {"Authorization": "${MCP_AUTH_HEADER}"},
    }


def _request(
    root: Path,
    *,
    scope: InstallationScope = InstallationScope.MANAGED_HOME,
) -> GeminiMCPRequest:
    return GeminiMCPRequest(
        package=_package(scope),
        scope=scope,
        root=root,
        server=GeminiMCPServerSpec(
            name="example.gemini-mcp",
            transport=GeminiMCPTransport.STDIO,
            command="fixture-mcp",
            args=("--readonly",),
            cwd="tools/server",
            env_vars=("FIXTURE_TOKEN",),
            description="Fixture MCP",
            include_tools=("ping",),
            exclude_tools=("hidden",),
        ),
    )


def _package(scope: InstallationScope) -> IntegrationPackage:
    return IntegrationPackage(
        id="example.gemini-mcp",
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
        compatibility=(IntegrationCompatibility(target_id=GEMINI_MCP_TARGET_ID),),
        scopes=(scope,),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("gemini-mcp-list", "gemini-acp-projection"),
        rollback_steps=("restore-settings-snapshot",),
    )
