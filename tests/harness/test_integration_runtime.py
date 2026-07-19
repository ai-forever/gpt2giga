from __future__ import annotations

import json
from pathlib import Path
import stat

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from gpt2giga_harness.codex_mcp_target import (
    CODEX_MCP_TARGET_ID,
    CodexCommandResult,
    CodexMCPRequest,
    CodexMCPServerSpec,
    CodexMCPTargetDriver,
    CodexMCPTransport,
)
from gpt2giga_harness.integration_installer import InstallationApproval
from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationCompatibility,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationSourceType,
    IntegrationUpdatePolicy,
)
from gpt2giga_harness.integration_runtime import (
    IntegrationRuntimeActivationError,
    IntegrationRuntimeConflictError,
    IntegrationRuntimeProbeResult,
    IntegrationRuntimeStateError,
    IntegrationRuntimeStore,
)


_DIGEST = "sha256:" + "a" * 64


class RuntimeCodex:
    """Content-free Codex surface with behavior selected by exact config bytes."""

    def __call__(self, argv, env, cwd, _timeout):
        if "mcp" in argv and "get" in argv:
            server_name = argv[argv.index("get") + 1]
            server = self._server(Path(env["CODEX_HOME"]), server_name)
            if server is None:
                return CodexCommandResult(1, "", "server missing")
            return CodexCommandResult(
                0,
                json.dumps(
                    {
                        "name": server_name,
                        "enabled": server.get("enabled", True),
                        "transport": "stdio",
                    }
                ),
            )
        if "exec" in argv:
            server = self._server(Path(env["CODEX_HOME"]), "fixture")
            version = "v2" if server and "--v2" in server.get("args", ()) else "v1"
            return CodexCommandResult(
                0,
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "mcp_tool_call",
                            "server": "fixture",
                            "tool": "ping",
                            "status": "completed",
                            "version": version,
                            "output": "secret-output-not-retained",
                        },
                    }
                ),
            )
        raise AssertionError(f"unexpected Codex argv: {argv!r}")

    @staticmethod
    def _server(home: Path, name: str):
        path = home / "config.toml"
        if not path.is_file():
            return None
        return tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"].get(name)

    def probe(self, expected_version: str):
        def run(home, _snapshot):
            env = {"CODEX_HOME": str(home)}
            discovered = self(
                ("codex", "mcp", "get", "fixture", "--json"), env, None, 10
            )
            invoked = self(("codex", "exec", "--json"), env, None, 10)
            payload = json.loads(invoked.stdout)
            return IntegrationRuntimeProbeResult(
                discovered=(
                    discovered.returncode == 0
                    and json.loads(discovered.stdout)["name"] == "fixture"
                ),
                behavior_verified=(
                    invoked.returncode == 0
                    and payload["item"]["status"] == "completed"
                    and payload["item"]["version"] == expected_version
                ),
                surface="codex-mcp-jsonl-v1",
            )

        return run


def test_runtime_snapshot_activation_update_fork_and_rollback(tmp_path):
    data_dir = tmp_path / "data"
    target_root = data_dir / "native" / "codex" / "homes" / "fixture"
    target_root.mkdir(parents=True)
    (target_root / "config.toml").write_text(
        'model = "fixture-model"\n', encoding="utf-8"
    )
    codex = RuntimeCodex()
    driver = CodexMCPTargetDriver(data_dir, command_runner=codex)
    runtime = IntegrationRuntimeStore(data_dir)

    request_v1 = _request(target_root, version="1.0.0", args=("--v1",))
    plan_v1 = driver.preview_install(request_v1)
    installed_v1 = driver.install(
        request_v1,
        plan_v1,
        InstallationApproval(plan_v1.plan_id, "test-operator"),
    )
    snapshot_v1 = runtime.capture(driver.installer, installed_v1.transaction_id)
    session_v1 = runtime.activate_session(
        session_id="native-session-v1",
        harness_id="codex-cli",
        snapshot_reference=snapshot_v1.public_ref(),
        probe=codex.probe("v1"),
    )

    request_v2 = _request(target_root, version="2.0.0", args=("--v2",))
    plan_v2 = driver.preview_update(request_v2)
    installed_v2 = driver.update(
        request_v2,
        plan_v2,
        InstallationApproval(plan_v2.plan_id, "test-operator"),
    )
    snapshot_v2 = runtime.capture(driver.installer, installed_v2.transaction_id)

    assert snapshot_v2.id != snapshot_v1.id
    assert snapshot_v2.previous_snapshot_id == snapshot_v1.id
    assert runtime.active_for(snapshot_v1.public_ref()) == snapshot_v2
    assert "--v1" in Path(session_v1.home).joinpath("config.toml").read_text(
        encoding="utf-8"
    )
    with pytest.raises(IntegrationRuntimeConflictError, match="already declares"):
        runtime.activate_session(
            session_id="native-session-v1",
            harness_id="codex-cli",
            snapshot_reference=snapshot_v2.public_ref(),
            probe=codex.probe("v2"),
        )

    fork_v2 = runtime.fork_session(
        source_session_id="native-session-v1",
        session_id="native-session-v2",
        snapshot_reference=snapshot_v2.public_ref(),
        probe=codex.probe("v2"),
    )
    assert fork_v2.forked_from_session_id == "native-session-v1"
    assert runtime.binding("native-session-v1").snapshot_id == snapshot_v1.id
    assert runtime.binding("native-session-v2").snapshot_id == snapshot_v2.id

    restored = runtime.rollback(driver.installer, snapshot_v2.public_ref())
    assert restored == snapshot_v1
    assert driver.discover_installed()[0].package_version == "1.0.0"
    assert runtime.active_for(snapshot_v2.public_ref()) == snapshot_v1
    session_after_rollback = runtime.activate_session(
        session_id="native-session-after-rollback",
        harness_id="codex-cli",
        snapshot_reference=restored.public_ref(),
        probe=codex.probe("v1"),
    )
    assert session_after_rollback.behavior_status == "verified"
    assert "secret-output-not-retained" not in repr(
        (
            snapshot_v1.public_ref(),
            snapshot_v2.public_ref(),
            session_v1.public_projection(),
            fork_v2.public_projection(),
            session_after_rollback.public_projection(),
        )
    )

    assert stat.S_IMODE(runtime.active_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(runtime.bindings_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(session_v1.home).stat().st_mode) == 0o700
    snapshot_record = json.loads(
        runtime._snapshot_path(snapshot_v1.id).read_text(encoding="utf-8")
    )
    assert "content_base64" in snapshot_record["files"][0]
    assert "content_base64" not in snapshot_v1.public_ref()

    Path(session_v1.home).joinpath("config.toml").write_text(
        "drifted\n", encoding="utf-8"
    )
    with pytest.raises(IntegrationRuntimeStateError, match="file changed"):
        runtime.binding("native-session-v1")


def test_runtime_activation_fails_closed_for_probe_target_and_state(tmp_path):
    data_dir = tmp_path / "data"
    target_root = data_dir / "native" / "codex" / "homes" / "fixture"
    target_root.mkdir(parents=True)
    driver = CodexMCPTargetDriver(data_dir, command_runner=RuntimeCodex())
    request = _request(target_root, version="1.0.0", args=("--v1",))
    plan = driver.preview_install(request)
    installed = driver.install(
        request,
        plan,
        InstallationApproval(plan.plan_id, "test-operator"),
    )
    runtime = IntegrationRuntimeStore(data_dir)
    snapshot = runtime.capture(driver.installer, installed.transaction_id)

    with pytest.raises(IntegrationRuntimeStateError, match="hash does not match"):
        runtime.load({**snapshot.public_ref(), "snapshot_hash": "0" * 64})
    with pytest.raises(IntegrationRuntimeConflictError, match="selected harness"):
        runtime.activate_session(
            session_id="wrong-target-session",
            harness_id="claude-code",
            snapshot_reference=snapshot.public_ref(),
            probe=RuntimeCodex().probe("v1"),
        )

    def leaking_probe(_home, _snapshot):
        raise RuntimeError("secret-output-not-retained")

    with pytest.raises(
        IntegrationRuntimeActivationError, match="details were omitted"
    ) as exc:
        runtime.activate_session(
            session_id="failed-probe-session",
            harness_id="codex-cli",
            snapshot_reference=snapshot.public_ref(),
            probe=leaking_probe,
        )
    assert "secret-output-not-retained" not in str(exc.value)
    with pytest.raises(IntegrationRuntimeStateError, match="not found"):
        runtime.binding("failed-probe-session")

    path = runtime._snapshot_path(snapshot.id)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["files"][0]["relative_path"] = "../escape"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(IntegrationRuntimeStateError, match="relative path"):
        runtime.load(snapshot.public_ref())


def _request(
    root: Path,
    *,
    version: str,
    args: tuple[str, ...],
) -> CodexMCPRequest:
    return CodexMCPRequest(
        package=_package(version),
        scope=InstallationScope.MANAGED_HOME,
        root=root,
        server=CodexMCPServerSpec(
            name="fixture",
            transport=CodexMCPTransport.STDIO,
            command="fixture-mcp",
            args=args,
            enabled_tools=("ping",),
        ),
    )


def _package(version: str) -> IntegrationPackage:
    return IntegrationPackage(
        id="example.runtime-codex-mcp",
        version=version,
        publisher="example-publisher",
        license="Apache-2.0",
        source_type=IntegrationSourceType.GIT,
        source="https://git.example/integration",
        immutable_ref=f"commit-{version.replace('.', '')}",
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
        scopes=(InstallationScope.MANAGED_HOME,),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("codex-mcp-get", "codex-exec-jsonl"),
        rollback_steps=("restore-config-snapshot",),
    )
