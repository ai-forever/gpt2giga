import json
from pathlib import Path

import pytest

from gpt2giga_harness.harnesses import claude_code, codex_cli, gemini_cli
from gpt2giga_harness.harnesses.claude_code import ClaudeCodeHarness
from gpt2giga_harness.harnesses.codex_cli import CodexCliHarness
from gpt2giga_harness.harnesses.gemini_cli import GeminiCliHarness
from gpt2giga_harness.managed_mcp import (
    HeadlessManagedMCPSnapshotStore,
    clear_headless_mcp_materialization,
    materialize_headless_mcp_snapshot,
    write_startup_config,
)
from gpt2giga_harness.mcp import descriptor_from_profile
from gpt2giga_harness.project import ProjectToolProfile
from gpt2giga_harness.types import (
    Availability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
)


@pytest.mark.parametrize(
    ("harness_cls", "module", "harness_id"),
    (
        (CodexCliHarness, codex_cli, "codex-cli"),
        (ClaudeCodeHarness, claude_code, "claude-code"),
        (GeminiCliHarness, gemini_cli, "gemini-cli"),
    ),
)
def test_builtin_headless_adapter_reads_snapshot_from_its_active_temporary_home(
    tmp_path,
    monkeypatch,
    harness_cls,
    module,
    harness_id,
):
    data_dir = tmp_path / "data"
    descriptor = descriptor_from_profile(
        "issues",
        ProjectToolProfile(
            enabled=True,
            title="Issues",
            harnesses=(harness_id,),
            config={
                "transport": "stdio",
                "command": "issue-mcp",
                "trusted": True,
                "env": {
                    "TOKEN": {
                        "secret_ref": {
                            "kind": "environment",
                            "name": "HEADLESS_MCP_TEST_TOKEN",
                        }
                    }
                },
            },
        ),
    )
    snapshot = HeadlessManagedMCPSnapshotStore(data_dir).create(
        project_id="proj_abc123",
        harness_id=harness_id,
        descriptors=(descriptor,),
        server_ids=("issues",),
    )
    monkeypatch.setenv("HEADLESS_MCP_TEST_TOKEN", "runtime-only-secret")
    captured = {}

    def fake_run_command(**kwargs):
        env = kwargs["env"]
        home = Path(env.get("CODEX_HOME") or env["HOME"])
        path = {
            "codex-cli": home / "config.toml",
            "claude-code": home / ".claude.json",
            "gemini-cli": home / ".gemini" / "settings.json",
        }[harness_id]
        captured["home"] = home
        captured["config"] = path.read_text(encoding="utf-8")
        return HarnessResult(
            ok=True,
            text="ok",
            raw={"exit_code": 0},
            command=kwargs["command"],
        )

    monkeypatch.setattr(module, "run_command", fake_run_command)
    monkeypatch.setattr(
        module,
        "prepare_proxy_for_agent",
        lambda request, context, harness_id, command: (context, (), None),
    )
    harness = harness_cls()
    monkeypatch.setattr(harness, "availability", lambda: Availability.available())

    result = harness.run(
        HarnessRequest(
            prompt="inspect",
            workspace=str(tmp_path),
            extra={"managed_mcp_snapshot": snapshot.public_ref()},
        ),
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            api_key="proxy-key",
            data_dir=str(data_dir),
        ),
    )

    assert result.ok is True
    assert "issue-mcp" in captured["config"]
    assert "runtime-only-secret" in captured["config"]
    assert not captured["home"].exists()
    binding = result.raw["managed_mcp_snapshot"]
    assert binding["snapshot_id"] == snapshot.snapshot_id
    assert binding["materialized"] is True
    assert "runtime-only-secret" not in json.dumps(binding)


def test_app_server_can_scrub_resolved_mcp_values_after_process_initialization(
    tmp_path,
    monkeypatch,
):
    data_dir = tmp_path / "data"
    home = data_dir / "app_server" / "homes" / "scope"
    descriptor = descriptor_from_profile(
        "issues",
        ProjectToolProfile(
            enabled=True,
            title="Issues",
            harnesses=("codex-cli",),
            config={
                "transport": "stdio",
                "command": "issue-mcp",
                "trusted": True,
                "env": {
                    "TOKEN": {
                        "secret_ref": {
                            "kind": "environment",
                            "name": "HEADLESS_MCP_TEST_TOKEN",
                        }
                    }
                },
            },
        ),
    )
    snapshot = HeadlessManagedMCPSnapshotStore(data_dir).create(
        project_id="proj_abc123",
        harness_id="codex-cli",
        descriptors=(descriptor,),
        server_ids=("issues",),
    )
    monkeypatch.setenv("HEADLESS_MCP_TEST_TOKEN", "runtime-only-secret")
    write_startup_config("codex-cli", home, 'model = "GigaChat"\n')

    materialize_headless_mcp_snapshot(
        "codex-cli",
        home,
        snapshot.public_ref(),
        data_dir=data_dir,
    )
    loaded = (home / "config.toml").read_text(encoding="utf-8")
    clear_headless_mcp_materialization("codex-cli", home)
    scrubbed = (home / "config.toml").read_text(encoding="utf-8")

    assert "runtime-only-secret" in loaded
    assert "issue-mcp" in loaded
    assert "runtime-only-secret" not in scrubbed
    assert "issue-mcp" not in scrubbed
    assert 'model = "GigaChat"' in scrubbed
