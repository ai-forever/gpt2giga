from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from gpt2giga_harness.codex_mcp_target import (
    CODEX_MCP_MARKER,
    CODEX_MCP_TARGET_ID,
    CodexCommandResult,
    CodexMCPActivationError,
    CodexMCPInvocationRequest,
    CodexMCPRequest,
    CodexMCPServerSpec,
    CodexMCPTargetDriver,
    CodexMCPTransport,
    codex_mcp_target_plugin,
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


_DIGEST = "sha256:" + "a" * 64


class FakeCodex:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path | None]] = []

    def __call__(self, argv, env, cwd, _timeout):
        self.calls.append((argv, cwd))
        if argv[-1] == "--version":
            return CodexCommandResult(0, "codex-cli 0.144.5\n")
        if argv[-2:] == ("mcp", "--help"):
            return CodexCommandResult(0, "Commands: list get add remove login logout\n")
        if argv[-2:] == ("exec", "--help"):
            return CodexCommandResult(0, "Options: --json --ephemeral\n")
        if "mcp" in argv and "get" in argv:
            server_name = argv[argv.index("get") + 1]
            root = Path(env["CODEX_HOME"])
            path = (cwd / ".codex" / "config.toml") if cwd else root / "config.toml"
            config = tomllib.loads(path.read_text(encoding="utf-8"))
            server = config["mcp_servers"].get(server_name)
            if server is None:
                return CodexCommandResult(1, "", "server missing")
            return CodexCommandResult(
                0,
                json.dumps(
                    {
                        "name": server_name,
                        "enabled": server.get("enabled", True),
                        "transport": "stdio" if "command" in server else "http",
                    }
                ),
            )
        if "exec" in argv:
            return CodexCommandResult(
                0,
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "mcp-1",
                            "type": "mcp_tool_call",
                            "server": "fixture",
                            "tool": "ping",
                            "status": "completed",
                            "output": "secret-output-not-retained",
                        },
                    }
                )
                + "\n",
            )
        raise AssertionError(f"unexpected Codex argv: {argv!r}")


def test_codex_mcp_lifecycle_is_transactional_native_loaded_and_reversible(tmp_path):
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "homes" / "proj_fixture"
    root.mkdir(parents=True)
    config = root / "config.toml"
    config.write_text('model = "fixture-model"\n', encoding="utf-8")
    fake = FakeCodex()
    driver = CodexMCPTargetDriver(
        data_dir,
        command_runner=fake,
        allow_native_invocation=True,
    )
    request = _request(root)
    plan = driver.preview_install(request)

    installed = driver.install(
        request,
        plan,
        InstallationApproval(plan.plan_id, "test-operator"),
    )

    text = config.read_text(encoding="utf-8")
    assert 'model = "fixture-model"' in text
    assert CODEX_MCP_MARKER in text
    assert "secret-value-canary" not in text
    assert tomllib.loads(text)["mcp_servers"]["fixture"] == {
        "command": "fixture-mcp",
        "args": ["--readonly"],
        "env_vars": ["FIXTURE_TOKEN"],
        "enabled": True,
        "required": False,
        "startup_timeout_sec": 10,
        "tool_timeout_sec": 60,
        "default_tools_approval_mode": "prompt",
        "enabled_tools": ["ping"],
    }
    health = driver.health(installed.transaction_id)
    assert health.status == "healthy"
    assert health.native_cli_loaded is True
    assert driver.discover_installed()[0].current is True

    disable_plan = driver.preview_disable(request)
    disabled = driver.disable(
        request,
        disable_plan,
        InstallationApproval(disable_plan.plan_id, "test-operator"),
    )
    assert driver.health(disabled.transaction_id).enabled is False

    enable_plan = driver.preview_enable(request)
    enabled = driver.enable(
        request,
        enable_plan,
        InstallationApproval(enable_plan.plan_id, "test-operator"),
    )
    assert driver.health(enabled.transaction_id).enabled is True

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
    assert "--v2" in config.read_text(encoding="utf-8")

    rolled_back = driver.rollback(updated.transaction_id)
    assert rolled_back.status == "rolled_back"
    assert driver.discover_installed()[0].package_version == "1.0.0"
    assert "--v2" not in config.read_text(encoding="utf-8")

    current = driver.discover_installed()[0]
    evidence = driver.prove_native_tool_invocation(
        CodexMCPInvocationRequest(
            transaction_id=current.transaction_id,
            workspace=tmp_path,
            server_name="fixture",
            tool_name="ping",
            prompt="Call the fixture ping tool exactly once.",
            allow_provider_traffic=True,
        )
    )
    assert evidence.status == "completed"
    assert evidence.event_count == 1
    assert "secret-output-not-retained" not in repr(evidence)

    uninstall_plan = driver.preview_uninstall(current.transaction_id)
    uninstalled = driver.uninstall(
        uninstall_plan,
        InstallationApproval(uninstall_plan.plan_id, "test-operator"),
    )

    assert uninstalled.status == "rolled_back"
    assert config.read_text(encoding="utf-8") == 'model = "fixture-model"\n'
    assert driver.discover_installed() == ()


def test_codex_mcp_probe_registry_and_native_invocation_opt_in(tmp_path):
    fake = FakeCodex()
    driver = CodexMCPTargetDriver(tmp_path / "data", command_runner=fake)

    probe = driver.probe_target()
    registry = ExtensionTargetRegistry()
    registry.register(codex_mcp_target_plugin(lambda: driver))

    assert probe.status == "supported"
    assert probe.version == "codex-cli 0.144.5"
    assert set(probe.capabilities) == {
        "mcp_add",
        "mcp_get",
        "mcp_list",
        "mcp_remove",
        "exec_json",
        "exec_ephemeral",
    }
    assert registry.create_driver(CODEX_MCP_TARGET_ID) is driver
    with pytest.raises(CodexMCPActivationError, match="explicit opt-in"):
        driver.prove_native_tool_invocation(
            CodexMCPInvocationRequest(
                transaction_id="txn_" + "a" * 32,
                workspace=tmp_path,
                server_name="fixture",
                tool_name="ping",
                prompt="Call ping.",
            )
        )


def test_project_and_user_home_scopes_are_explicit_and_distinct(tmp_path):
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    user_home = tmp_path / "fake-user" / ".codex"
    project.mkdir()
    fake = FakeCodex()
    driver = CodexMCPTargetDriver(
        data_dir,
        project_roots=(project,),
        user_home_root=user_home,
        allow_user_home=True,
        command_runner=fake,
    )
    project_request = _request(project, scope=InstallationScope.PROJECT)
    project_plan = driver.preview_install(project_request)
    driver.install(
        project_request,
        project_plan,
        InstallationApproval(project_plan.plan_id, "test-operator"),
    )

    assert (project / ".codex" / "config.toml").is_file()
    assert any("projects." in value for argv, _cwd in fake.calls for value in argv)

    user_request = _request(user_home, scope=InstallationScope.USER_HOME)
    user_plan = driver.preview_install(user_request)
    with pytest.raises(InstallationScopeError, match="approval"):
        driver.install(
            user_request,
            user_plan,
            InstallationApproval(user_plan.plan_id, "test-operator"),
        )
    driver.install(
        user_request,
        user_plan,
        InstallationApproval(
            user_plan.plan_id,
            "test-operator",
            allow_user_home=True,
        ),
    )
    assert (user_home / "config.toml").is_file()


def test_codex_mcp_rejects_secrets_invalid_http_and_foreign_server_collision(tmp_path):
    with pytest.raises(ValueError, match="secret material"):
        CodexMCPServerSpec(
            name="fixture",
            transport=CodexMCPTransport.STDIO,
            command="fixture-mcp",
            args=("api_key=secret-value-canary",),
        )
    with pytest.raises(ValueError, match="HTTPS"):
        CodexMCPServerSpec(
            name="fixture",
            transport=CodexMCPTransport.STREAMABLE_HTTP,
            url="http://registry.example/mcp",
        )

    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "home"
    root.mkdir(parents=True)
    (root / "config.toml").write_text(
        '[mcp_servers.fixture]\ncommand = "foreign"\n', encoding="utf-8"
    )
    driver = CodexMCPTargetDriver(data_dir, command_runner=FakeCodex())

    with pytest.raises(InstallationConflictError, match="already owned"):
        driver.preview_install(_request(root))


def _request(
    root: Path,
    *,
    scope: InstallationScope = InstallationScope.MANAGED_HOME,
) -> CodexMCPRequest:
    return CodexMCPRequest(
        package=_package(scope),
        scope=scope,
        root=root,
        server=CodexMCPServerSpec(
            name="fixture",
            transport=CodexMCPTransport.STDIO,
            command="fixture-mcp",
            args=("--readonly",),
            env_vars=("FIXTURE_TOKEN",),
            enabled_tools=("ping",),
        ),
    )


def _package(scope: InstallationScope) -> IntegrationPackage:
    return IntegrationPackage(
        id="example.codex-mcp",
        version="1.0.0",
        publisher="example-publisher",
        license="Apache-2.0",
        source_type=IntegrationSourceType.GIT,
        source="https://git.example/integration",
        immutable_ref="commit-deadbeef",
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
        compatibility=(IntegrationCompatibility(target_id=CODEX_MCP_TARGET_ID),),
        scopes=(scope,),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("codex-mcp-get", "codex-exec-jsonl"),
        rollback_steps=("restore-config-snapshot",),
    )
