import json
from importlib.metadata import version
import signal
import sys

import pytest

from gpt2giga_harness import cli, proxy
from gpt2giga_harness import entrypoint
from gpt2giga_harness.codex_mcp_target import CodexMCPTargetDriver
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.harnesses.claude_code import ClaudeCodeHarness
from gpt2giga_harness.harnesses.codex_cli import CodexCliHarness
from gpt2giga_harness.harnesses.direct_chat import DirectChatHarness
from gpt2giga_harness.harnesses.gemini_cli import GeminiCliHarness
from gpt2giga_harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
)
from gpt2giga_harness.native.registry import NativeHistoryConnectorRegistry
from gpt2giga_harness.runtime.policy import (
    ApprovalDecision,
    PermissionAction,
    PolicyContext,
    PolicyEngine,
    REVIEWED_PROMOTION_APPLY_OWNER,
    permission_profile,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.types import (
    Availability,
    GigaChatApiMode,
    HarnessCapability,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


class _FakeWorkerProcess:
    def __init__(self, pid=4242):
        self.pid = pid
        self.return_code = None
        self.signals = []
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.return_code

    def send_signal(self, value):
        self.signals.append(value)
        self.return_code = 130

    def terminate(self):
        self.terminated = True
        self.return_code = 143

    def kill(self):
        self.killed = True
        self.return_code = 137

    def wait(self, timeout):
        return self.return_code


def _ready_execution_readiness(*_args, **_kwargs):
    return {
        "ok": True,
        "blocked": False,
        "summary": {"ready": 1, "degraded": 0, "blocked": 0},
        "findings": [],
    }


def test_cli_ui_allows_cold_worker_fingerprint_startup():
    assert cli.UI_WORKER_START_TIMEOUT_SECONDS == 10.0


def test_cli_version_reports_distribution_version(capsys):
    with pytest.raises(SystemExit) as raised:
        cli.main(["--version"])

    assert raised.value.code == 0
    assert (
        capsys.readouterr().out
        == f"GigaLoom {version('gpt2giga-harness')} (gpt2giga-harness)\n"
    )


@pytest.mark.parametrize("shell", ("bash", "zsh", "fish", "powershell"))
def test_cli_completion_is_static_and_leaves_provider_suffix_owned(shell, capsys):
    assert cli.main(["completion", shell]) == 0

    output = capsys.readouterr().out
    assert "codex" in output
    assert "claude" in output
    assert "gemini" in output
    assert "exec resume" not in output
    assert "--output-format" not in output


def test_console_entrypoint_reports_version_without_importing_full_cli(
    capsys, monkeypatch
):
    monkeypatch.delitem(sys.modules, "gpt2giga_harness.cli", raising=False)

    assert entrypoint.main(["--version"]) == 0

    assert "gpt2giga_harness.cli" not in sys.modules
    assert (
        capsys.readouterr().out
        == f"GigaLoom {version('gpt2giga-harness')} (gpt2giga-harness)\n"
    )


def test_cli_ui_starts_and_stops_worker_when_none_is_online(
    capsys,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path))
    process = _FakeWorkerProcess()
    popen_calls = []
    status_calls = 0

    def fake_worker_status(_store):
        nonlocal status_calls
        status_calls += 1
        workers = (
            [{"status": "online", "process_id": process.pid}]
            if status_calls > 1
            else []
        )
        return {"workers": workers, "online": len(workers)}

    monkeypatch.setattr(cli, "worker_status", fake_worker_status)
    monkeypatch.setattr(
        cli.subprocess,
        "Popen",
        lambda command, **kwargs: popen_calls.append((command, kwargs)) or process,
    )
    monkeypatch.setattr(cli, "create_app", lambda _config: "app")
    uvicorn_calls = []
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda *args, **kwargs: uvicorn_calls.append((args, kwargs)),
    )

    assert cli.main(["ui"]) == 0

    command, options = popen_calls[0]
    assert command[1:] == [
        "-m",
        "gpt2giga_harness.cli",
        "worker",
        "start",
    ]
    assert options["env"]["GPT2GIGA_HARNESS_DATA_DIR"] == str(tmp_path)
    assert options["env"]["GPT2GIGA_HARNESS_AUTO_START_PROXY"] == "false"
    assert uvicorn_calls == [
        (
            ("app",),
            {
                "host": "127.0.0.1",
                "port": 8091,
                "log_level": "info",
                "timeout_graceful_shutdown": 5,
            },
        )
    ]
    assert process.signals == [signal.SIGINT]
    assert process.terminated is False
    assert "Started durable Harness worker pid=4242." in capsys.readouterr().out


def test_cli_ui_reuses_online_worker_or_allows_autostart_opt_out(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        cli,
        "worker_status",
        lambda _store: {"workers": [{"status": "online"}], "online": 1},
    )
    monkeypatch.setattr(
        cli.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("must not start another worker"),
    )
    monkeypatch.setattr(cli, "create_app", lambda _config: "app")
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: None)

    assert cli.main(["ui"]) == 0

    monkeypatch.setattr(
        cli,
        "worker_status",
        lambda _store: pytest.fail("opt-out must skip worker discovery"),
    )
    assert cli.main(["ui", "--no-start-worker"]) == 0


def test_cli_ui_starts_missing_workers_to_reach_target_pool(
    capsys,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path))
    processes: list[_FakeWorkerProcess] = []

    def fake_worker_status(_store):
        workers = [{"status": "online", "process_id": 1000}]
        workers.extend(
            {"status": "online", "process_id": process.pid} for process in processes
        )
        return {"workers": workers, "online": len(workers)}

    def fake_popen(*_args, **_kwargs):
        process = _FakeWorkerProcess(pid=2000 + len(processes))
        processes.append(process)
        return process

    monkeypatch.setattr(cli, "worker_status", fake_worker_status)
    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli, "create_app", lambda _config: "app")
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: None)

    assert cli.main(["ui", "--worker-count", "4"]) == 0

    assert [process.pid for process in processes] == [2000, 2001, 2002]
    assert all(process.signals == [signal.SIGINT] for process in processes)
    output = capsys.readouterr().out
    assert (
        "Using 1 existing online durable Harness worker(s); starting 3 more." in output
    )


@pytest.mark.parametrize("worker_count", ["0", "33"])
def test_cli_ui_rejects_invalid_worker_count(capsys, worker_count):
    assert cli.main(["ui", "--worker-count", worker_count]) == 2
    assert "UI worker count must be between 1 and 32." in capsys.readouterr().err


def test_cli_harness_list_outputs_direct_chat(capsys):
    exit_code = cli.main(["harness", "list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "direct-chat" in output


def test_cli_harness_run_json_includes_selected_execution_readiness(capsys):
    exit_code = cli.main(["harness", "run", "echo", "--prompt", "hello", "--json"])

    payload = json.loads(capsys.readouterr().out)
    readiness = payload["raw"]["preflight"]["readiness"]
    simulation = payload["raw"]["preflight"]["permission_simulation"]
    assert exit_code == 0
    assert readiness["ok"] is True
    assert readiness["plan"] == {
        "harness_id": "echo",
        "invocation_mode": "headless",
        "execution_transport": "one_shot",
        "api_mode": "v2",
        "model": None,
        "mode": "plan",
        "workspace_configured": False,
        "workspace_policy": "auto",
        "delivery": "synchronous",
        "dry_run": False,
    }
    assert {finding["id"] for finding in readiness["findings"]} == {
        "harness-echo",
        "invocation-mode",
        "delivery",
    }
    assert simulation["route_snapshot"]["harness_id"] == "echo"
    assert simulation["route_snapshot"]["execution_transport"] == "one_shot"
    assert simulation["side_effect_free"] is True
    assert simulation["provider_safety_proven"] is False


def test_cli_session_application_flow_create_turn_events_and_approve(
    capsys,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))

    assert cli.main(["session", "create", "--harness", "echo", "--json"]) == 0
    session = json.loads(capsys.readouterr().out)["session"]

    assert (
        cli.main(
            [
                "session",
                "turn",
                session["id"],
                "--prompt",
                "shared CLI turn",
                "--harness",
                "echo",
                "--permission-profile",
                "review_every_action",
                "--transport",
                "one_shot",
                "--idempotency-key",
                "cli-application-turn",
                "--json",
            ]
        )
        == 0
    )
    submitted = json.loads(capsys.readouterr().out)
    assert submitted["job"]["status"] == "waiting_approval"
    assert submitted["run"]["metadata"]["execution_transport"] == "one_shot"

    assert cli.main(["session", "events", submitted["run"]["id"], "--json"]) == 0
    events = json.loads(capsys.readouterr().out)["events"]
    assert [event["type"] for event in events] == [
        "session.updated",
        "approval_requested",
    ]
    assert events[0]["payload"]["title"]["provenance"] == "fallback"
    approval_id = events[1]["payload"]["approval_id"]

    assert (
        cli.main(
            [
                "session",
                "approve",
                approval_id,
                "--decision",
                "allow_once",
                "--json",
            ]
        )
        == 0
    )
    approved = json.loads(capsys.readouterr().out)
    assert approved["approval"]["status"] == "approved"
    assert approved["job_status"] == "queued"


def test_cli_doctor_json_passes_explicit_workspace(capsys, monkeypatch, tmp_path):
    captured = {}

    def fake_report(config, *, workspace):
        captured["workspace"] = workspace
        return {
            "schema_version": 1,
            "ok": True,
            "summary": {"ready": 1, "degraded": 0, "blocked": 0},
            "checks": [],
        }

    monkeypatch.setattr(cli, "build_doctor_report", fake_report)

    assert cli.main(["doctor", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert captured["workspace"] == str(tmp_path)
    assert payload["schema_version"] == 1
    assert payload["ok"] is True


def test_cli_integration_flow_matches_api_preview_status_and_native_apply(
    capsys,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        CodexMCPTargetDriver,
        "_native_get",
        lambda _self, _root, _scope, _server_name: True,
    )

    assert cli.main(["integration", "list", "--json"]) == 0
    inventory = json.loads(capsys.readouterr().out)
    assert {item["id"] for item in inventory["sources"]} >= {
        "catalog",
        "raw_descriptor",
    }

    assert (
        cli.main(
            [
                "integration",
                "preview",
                "--source",
                "raw_descriptor",
                "--package-id",
                "cli-mcp",
                "--target",
                "codex-mcp",
                "--scope",
                "managed_home",
                "--configuration-json",
                '{"transport":"stdio","command":"cli-mcp"}',
                "--json",
            ]
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)
    flow_id = preview["flow"]["id"]
    plan_id = preview["plan"]["plan_id"]

    assert cli.main(["integration", "status", flow_id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["flow"]["status"] == (
        "awaiting_approval"
    )

    assert (
        cli.main(
            [
                "integration",
                "apply",
                flow_id,
                "--plan-id",
                plan_id,
                "--authority",
                "cli-operator",
                "--ack-native-consent",
                "--json",
            ]
        )
        == 0
    )
    applied = json.loads(capsys.readouterr().out)
    assert applied["flow"]["status"] == "verified"
    assert applied["flow"]["verification_status"] == "native_verified"
    assert applied["flow"]["rollback_available"] is True


def test_cli_extension_pack_preview_uses_shared_group_authority(
    capsys,
    monkeypatch,
    tmp_path,
):
    captured = {}

    class FakeGroups:
        def __init__(self, data_dir):
            captured["data_dir"] = str(data_dir)

        def preview(self, request):
            captured["request"] = request
            return {
                "group": {"id": "group_" + "a" * 32},
                "plan": {
                    "package": {"id": request["pack_id"]},
                    "plan_id": "plan_" + "b" * 64,
                    "compatibility": [
                        {
                            "target": "codex",
                            "status": "supported",
                            "included": True,
                        }
                    ],
                },
            }

    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "GroupedIntegrationService", FakeGroups)

    assert (
        cli.main(
            [
                "integration",
                "pack-preview",
                "--pack-id",
                "example.portable-pack",
                "--pack-version",
                "1.0.0",
                "--skill-catalog-id",
                "skill-pin",
                "--mcp-catalog-id",
                "mcp-pin",
                "--mcp-configuration-json",
                '{"selection":{"kind":"remote"}}',
                "--json",
            ]
        )
        == 0
    )

    assert json.loads(capsys.readouterr().out)["plan"]["package"]["id"] == (
        "example.portable-pack"
    )
    assert captured["request"] == {
        "component": "extension_pack",
        "pack_id": "example.portable-pack",
        "pack_version": "1.0.0",
        "skill_catalog_id": "skill-pin",
        "mcp_catalog_id": "mcp-pin",
        "scope": "managed_home",
        "workspace": None,
        "target_mode": "all_supported",
        "mcp_configuration": {"selection": {"kind": "remote"}},
    }


def test_cli_doctor_exports_support_report_and_fails_ci_threshold(
    capsys,
    monkeypatch,
    tmp_path,
):
    report = {
        "schema_version": 1,
        "kind": "gpt2giga_harness_doctor_report",
        "ok": True,
        "summary": {"ready": 2, "degraded": 1, "blocked": 0},
        "checks": [],
    }
    monkeypatch.setattr(cli, "build_doctor_report", lambda *args, **kwargs: report)
    output = tmp_path / "doctor.json"

    assert (
        cli.main(
            [
                "doctor",
                "--json",
                "--output",
                str(output),
                "--fail-on",
                "degraded",
            ]
        )
        == 1
    )

    assert json.loads(capsys.readouterr().out) == report
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_cli_doctor_ci_threshold_preserves_default_exit_code(capsys, monkeypatch):
    report = {
        "schema_version": 1,
        "kind": "gpt2giga_harness_doctor_report",
        "ok": False,
        "summary": {"ready": 1, "degraded": 0, "blocked": 1},
        "checks": [],
    }
    monkeypatch.setattr(cli, "build_doctor_report", lambda *args, **kwargs: report)

    assert cli.main(["doctor", "--json"]) == 0
    capsys.readouterr()
    assert cli.main(["doctor", "--json", "--fail-on", "blocked"]) == 1


def test_cli_harness_list_json_shows_native_metadata(capsys):
    exit_code = cli.main(["harness", "list", "--json"])

    rows = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    by_id = {row["id"]: row for row in rows}
    assert by_id["codex-cli"]["native"] is True
    assert by_id["codex-cli"]["default_invocation_mode"] == "headless"
    assert by_id["direct-chat"]["native"] is False


def test_cli_harness_capabilities_outputs_generated_matrix(capsys):
    assert cli.main(["harness", "capabilities", "--json"]) == 0

    matrix = json.loads(capsys.readouterr().out)
    assert matrix["generated_from"] == "HarnessSpec.adapter_capabilities"
    assert {item["id"] for item in matrix["adapters"]} == {
        "codex-cli",
        "claude-code",
        "gemini-cli",
    }
    assert cli.main(["harness", "capabilities"]) == 0
    assert "# Harness adapter capability matrix" in capsys.readouterr().out


def test_cli_harness_inspect_json_shows_native_support(capsys):
    exit_code = cli.main(["harness", "inspect", "claude-code", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["spec"]["supports_native_sessions"] is True
    assert payload["spec"]["supports_external_history"] is True
    assert payload["spec"]["default_invocation_mode"] == "native"
    assert payload["compatibility"]["event_schema"] == "claude-stream-json-v1"
    assert payload["validation"]["ok"] is True


def test_cli_harness_inspect_reports_executable_source(
    capsys,
    monkeypatch,
    tmp_path,
):
    executable = tmp_path / "bin" / "claude"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[executables]\n"claude-code" = "{executable}"\n',
        encoding="utf-8",
    )
    registry = cli.create_default_registry(
        include_entry_points=False,
        config_path=str(config_path),
    )
    monkeypatch.setattr(cli, "create_default_registry", lambda: registry)

    assert cli.main(["harness", "inspect", "claude-code", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["executable"] == str(executable)
    assert payload["executable_source"] == "user_config"


def test_cli_config_set_path_unset_round_trip(capsys, monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    executable = tmp_path / "bin" / "codex"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setattr(cli, "user_config_path", lambda: config_path)

    assert cli.main(["config", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(config_path)

    assert cli.main(["config", "set", "executables.codex-cli", str(executable)]) == 0
    assert '"codex-cli"' in config_path.read_text(encoding="utf-8")
    capsys.readouterr()

    assert cli.main(["config", "unset", "executables.codex-cli"]) == 0
    assert '"codex-cli"' not in config_path.read_text(encoding="utf-8")


def test_cli_config_rejects_non_executable_key(capsys):
    assert cli.main(["config", "set", "proxy.url", "/tmp/proxy"]) == 2
    assert "executables.<harness-id>" in capsys.readouterr().err


def test_cli_provider_commands_share_authoritative_reference_only_registry(
    monkeypatch,
    capsys,
    tmp_path,
):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    assert (
        cli.main(
            [
                "provider",
                "add",
                "team-openai",
                "--name",
                "Team OpenAI",
                "--protocol",
                "openai_compatible",
                "--dialect",
                "openai-responses-v1",
                "--base-url",
                "https://models.example.test",
                "--route-prefix",
                "/v1",
                "--secret-reference-name",
                "TEAM_OPENAI_KEY",
                "--coding-model",
                "coding-model",
                "--json",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)["provider"]
    assert created["authentication"]["reference_name"] == "TEAM_OPENAI_KEY"
    assert created["authentication"]["value_readable"] is False

    assert cli.main(["provider", "list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in listed["providers"]] == ["team-openai"]
    assert listed["secret_contract"]["values_accepted"] is False

    assert (
        cli.main(
            [
                "provider",
                "edit",
                "team-openai",
                "--expected-revision",
                str(created["registry_revision"]),
                "--title-model",
                "title-model",
                "--json",
            ]
        )
        == 0
    )
    updated = json.loads(capsys.readouterr().out)["provider"]
    assert updated["default_models"] == {
        "coding": "coding-model",
        "title": "title-model",
    }
    assert updated["effects"]["structured_sessions"] == ("fork_or_new_session_required")

    assert (
        cli.main(
            [
                "provider",
                "edit",
                "team-openai",
                "--expected-revision",
                str(created["registry_revision"]),
                "--name",
                "stale",
            ]
        )
        == 2
    )
    assert "Provider registry conflict" in capsys.readouterr().err


def test_cli_harness_validate_json_reports_invalid_plugin(
    capsys,
    monkeypatch,
):
    registry = cli.create_default_registry(include_entry_points=False)
    registry.register(_InvalidPluginHarness())
    monkeypatch.setattr(cli, "create_default_registry", lambda: registry)

    exit_code = cli.main(["harness", "validate", "invalid-plugin", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["validation"]["ok"] is False
    assert {issue["code"] for issue in payload["validation"]["issues"]} == {
        "no_known_capabilities",
        "unknown_capability",
    }


def test_cli_harness_scaffold_includes_plugin_metadata(capsys):
    exit_code = cli.main(["harness", "scaffold", "my-harness"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "config_schema" in output
    assert "HarnessCapability.CHAT_COMPLETIONS" in output
    assert "metadata={" in output


def test_cli_harness_scaffold_writes_full_package(capsys, tmp_path):
    output = tmp_path / "my-harness"

    exit_code = cli.main(["harness", "scaffold", "my-harness", "--output", str(output)])

    assert exit_code == 0
    assert (output / "pyproject.toml").is_file()
    assert (
        output / "src" / "agent_workbench_my_harness" / "adapter_manifest.json"
    ).is_file()
    assert "Created adapter scaffold" in capsys.readouterr().out


def test_cli_project_info_json_reports_workspace(capsys, tmp_path):
    exit_code = cli.main(["project", "info", "--workspace", str(tmp_path), "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["project"]["root"] == str(tmp_path)
    assert output["project"]["name"] == tmp_path.name
    assert output["config"]["exists"] is False
    assert output["defaults"]["harness"] == "codex-cli"


def test_cli_init_alias_writes_project_config(capsys, tmp_path):
    exit_code = cli.main(
        [
            "init",
            "--workspace",
            str(tmp_path),
            "--name",
            "cli-demo",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["project"]["name"] == "cli-demo"
    assert output["config"]["exists"] is True
    assert (tmp_path / ".giga" / "harness.toml").exists()
    assert (tmp_path / ".giga" / "agents" / "planner.yaml").exists()


def test_cli_agent_list_show_validate_and_run(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    assert cli.main(["init", "--workspace", str(tmp_path), "--json"]) == 0
    capsys.readouterr()

    assert cli.main(["agent", "list", "--workspace", str(tmp_path), "--json"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert {item["id"] for item in listing["agents"]} >= {"planner", "reviewer"}

    assert (
        cli.main(["agent", "show", "planner", "--workspace", str(tmp_path), "--json"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["title"] == "Planner"

    path = tmp_path / ".giga" / "agents" / "planner.yaml"
    assert cli.main(["agent", "validate", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True

    assert (
        cli.main(
            [
                "agent",
                "run",
                "planner",
                "--workspace",
                str(tmp_path),
                "--prompt",
                "Plan this",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    run = json.loads(capsys.readouterr().out)["run"]
    assert run["metadata"]["agent_id"] == "planner"
    assert run["metadata"]["agent_profile_snapshot"]["title"] == "Planner"


def test_cli_preset_list_and_run_dry_run_json(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    config_path = tmp_path / ".giga" / "harness.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        """
[project]
name = "cli-demo"

[presets.ask]
title = "Ask"
harness = "echo"
mode = "plan"
prompt = "Ask {{project_name}}: {{user_prompt}}"
""",
        encoding="utf-8",
    )

    list_code = cli.main(["preset", "list", "--workspace", str(tmp_path), "--json"])
    listed = json.loads(capsys.readouterr().out)

    assert list_code == 0
    assert listed[0]["name"] == "ask"
    assert listed[0]["harness"] == "echo"

    run_code = cli.main(
        [
            "preset",
            "run",
            "ask",
            "--workspace",
            str(tmp_path),
            "--prompt",
            "hello",
            "--dry-run",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert run_code == 0
    assert payload["prompt"] == "Ask cli-demo: hello"
    assert payload["result"]["ok"] is True
    assert payload["result"]["text"] == "Ask cli-demo: hello"


def test_cli_memory_add_list_disable_delete_json(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))

    add_code = cli.main(
        [
            "memory",
            "add",
            "Use Alembic migrations",
            "--workspace",
            str(tmp_path),
            "--tag",
            "decision",
            "--json",
        ]
    )
    added = json.loads(capsys.readouterr().out)

    assert add_code == 0
    memory_id = added["memory"]["id"]
    assert added["memory"]["tags"] == ["decision"]

    list_code = cli.main(["memory", "list", "--workspace", str(tmp_path), "--json"])
    listed = json.loads(capsys.readouterr().out)

    assert list_code == 0
    assert [item["id"] for item in listed["memories"]] == [memory_id]

    disable_code = cli.main(
        ["memory", "disable", memory_id, "--workspace", str(tmp_path), "--json"]
    )
    disabled = json.loads(capsys.readouterr().out)

    assert disable_code == 0
    assert disabled["memory"]["enabled"] is False

    delete_code = cli.main(
        ["memory", "delete", memory_id, "--workspace", str(tmp_path), "--json"]
    )
    deleted = json.loads(capsys.readouterr().out)

    assert delete_code == 0
    assert deleted["deleted"] is True


def test_cli_eval_list_and_run_json(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    eval_path = tmp_path / ".giga" / "evals" / "smoke.yaml"
    eval_path.parent.mkdir(parents=True)
    eval_path.write_text(
        """
name: smoke
harnesses: [echo]
cases:
  - id: echo_contains
    prompt: "FastAPI gateway"
    checks:
      - type: contains
        value: "FastAPI"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    list_code = cli.main(["eval", "list", "--workspace", str(tmp_path), "--json"])
    listed = json.loads(capsys.readouterr().out)

    assert list_code == 0
    assert listed["specs"][0]["name"] == "smoke"

    run_code = cli.main(
        [
            "eval",
            "run",
            "smoke",
            "--workspace",
            str(tmp_path),
            "--harness",
            "echo",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert run_code == 0
    assert payload["status"] == "passed"
    assert payload["summary"]["passed"] == 1


def test_cli_run_pr_summary_and_patch(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    store = FilesystemHarnessSessionStore(tmp_path / "data")
    session = store.create_session(title="PR demo")
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="change file",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="edit",
        workspace=str(tmp_path),
        status="succeeded",
        metadata={
            "workspace_execution": {
                "policy": "worktree",
                "patch": "diff --git a/app.txt b/app.txt\n",
                "changed_files": ["app.txt"],
                "untracked_files": [],
            }
        },
    )

    summary_code = cli.main(["run", "pr-summary", run.id, "--json"])
    summary = json.loads(capsys.readouterr().out)

    assert summary_code == 0
    assert summary["pr_artifact"]["title"] == "Update app.txt"
    assert summary["pr_artifact"]["changed_files"] == ["app.txt"]

    patch_code = cli.main(["run", "patch", run.id])
    patch_output = capsys.readouterr().out

    assert patch_code == 0
    assert "diff --git a/app.txt b/app.txt" in patch_output


def test_cli_open_file_session_and_run_diff_dry_run_json(
    capsys,
    tmp_path,
    monkeypatch,
):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('ok')\n", encoding="utf-8")
    config_path = workspace / ".giga" / "harness.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        '[editor]\ncommand = "code --reuse-window"\nterminal_command = "wezterm"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(data_dir))
    store = FilesystemHarnessSessionStore(data_dir)
    session = store.create_session(title="Editor demo", workspace=str(workspace))
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="change file",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="edit",
        workspace=str(workspace),
        status="succeeded",
        metadata={
            "workspace_execution": {
                "policy": "worktree",
                "source_workspace": str(workspace),
                "patch": "diff --git a/app.py b/app.py\n",
                "changed_files": ["app.py"],
            }
        },
    )

    file_code = cli.main(
        [
            "open",
            "file",
            "app.py",
            "--workspace",
            str(workspace),
            "--line",
            "4",
            "--dry-run",
            "--json",
        ]
    )
    file_payload = json.loads(capsys.readouterr().out)

    assert file_code == 0
    assert file_payload["editor"]["command"][:3] == [
        "code",
        "--reuse-window",
        "--goto",
    ]
    assert file_payload["editor"]["command"][3].endswith("app.py:4:1")

    session_code = cli.main(["open", "session", session.id, "--dry-run", "--json"])
    session_payload = json.loads(capsys.readouterr().out)

    assert session_code == 0
    assert session_payload["editor"]["kind"] == "workspace"
    assert session_payload["editor"]["target_path"] == str(workspace)

    run_code = cli.main(["open", "run", run.id, "--diff", "--dry-run", "--json"])
    run_payload = json.loads(capsys.readouterr().out)

    assert run_code == 0
    assert run_payload["editor"]["kind"] == "diff"
    assert run_payload["editor"]["target_path"].endswith(f"{run.id}.diff")

    terminal_code = cli.main(
        ["open", "run", run.id, "--terminal", "--dry-run", "--json"]
    )
    terminal_payload = json.loads(capsys.readouterr().out)

    assert terminal_code == 0
    assert terminal_payload["editor"]["kind"] == "terminal"
    assert terminal_payload["editor"]["command"] == [
        "wezterm",
        "start",
        "--cwd",
        str(workspace),
    ]


def test_cli_run_provenance_and_replay(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    store = FilesystemHarnessSessionStore(tmp_path / "data")
    session = store.create_session(title="Replay demo")
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="hello replay",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
        status="succeeded",
    )
    runtime = RuntimeCoordinationStore(tmp_path / "data")
    context = PolicyContext(
        run_id=run.id,
        reason="Apply reviewed patch.",
        preview={"source_sha": "a" * 40, "patch_sha256": "b" * 64},
        approval_binding="cli-reviewed-binding",
        enforcement_owner=REVIEWED_PROMOTION_APPLY_OWNER,
    )
    engine = PolicyEngine(runtime)
    resolution = engine.resolve(
        PermissionAction.GIT_APPLY,
        profile=permission_profile("interactive"),
        context=context,
    )
    approval = runtime.create_approval_request(resolution, context)
    runtime.decide_approval_request(approval.id, ApprovalDecision.ALLOW_ONCE)
    engine.resolve(
        PermissionAction.GIT_APPLY,
        profile=permission_profile("interactive"),
        context=context,
    )

    provenance_code = cli.main(["run", "provenance", run.id, "--json"])
    provenance = json.loads(capsys.readouterr().out)

    assert provenance_code == 0
    assert provenance["provenance"]["run_id"] == run.id
    assert provenance["provenance"]["replay_request"]["prompt"] == "hello replay"
    reviewed = provenance["provenance"]["reviewed_evidence"]
    assert reviewed["source_run_id"] == run.id
    assert reviewed["operations"][0]["operation_id"] == approval.id

    replay_code = cli.main(["run", "replay", run.id, "--json"])
    replay = json.loads(capsys.readouterr().out)

    assert replay_code == 0
    assert replay["source_run"]["id"] == run.id
    assert replay["result"]["text"] == "hello replay"
    assert (
        replay["replay_request"]["extra"]["source_reviewed_evidence"]["manifest_sha256"]
        == reviewed["manifest_sha256"]
    )
    assert replay["run"]["metadata"]["provenance"]["request"]["prompt"] == (
        "hello replay"
    )


def test_cli_chat_passes_api_mode_and_model(monkeypatch, capsys, tmp_path):
    captured = {}
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "build_execution_readiness", _ready_execution_readiness)

    def fake_run(self, request, context):
        captured["request"] = request
        captured["context"] = context
        return HarnessResult(ok=True, text="ok")

    monkeypatch.setattr(DirectChatHarness, "run", fake_run)
    monkeypatch.setattr(
        proxy,
        "health_check",
        lambda config: proxy.ProxyHealth(
            ok=True,
            url=config.proxy_url,
            path="/health",
            status_code=200,
        ),
    )
    monkeypatch.setattr(
        proxy,
        "sidecar_preflight",
        lambda _context: proxy.SidecarPreflight(ok=True, reason="ready"),
    )
    monkeypatch.setattr(
        proxy,
        "probe_json_route",
        lambda _config, path, **_kwargs: proxy.RouteProbe(
            ok=True,
            path=path,
            method="POST",
            status_code=422,
        ),
    )

    exit_code = cli.main(
        [
            "chat",
            "--api-mode",
            "v1",
            "--model",
            "GigaChat-2-Max",
            "hello",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "ok"
    assert captured["request"].api_mode.value == "v1"
    assert captured["request"].model == "GigaChat-2-Max"
    assert captured["request"].prompt == "hello"


def test_cli_no_start_proxy_override(monkeypatch, capsys):
    captured = {}

    def fake_run(self, request, context):
        captured["context"] = context
        return HarnessResult(ok=True, text="ok")

    monkeypatch.setattr(DirectChatHarness, "run", fake_run)
    monkeypatch.setattr(
        cli,
        "build_execution_readiness",
        _ready_execution_readiness,
    )

    exit_code = cli.main(["chat", "--no-start-proxy", "hello"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "ok"
    assert captured["context"].auto_start_proxy is False


def test_cli_agent_alias_passes_workspace(monkeypatch, capsys, tmp_path):
    captured = {}

    def fake_run(self, request, context):
        captured["request"] = request
        captured["context"] = context
        return HarnessResult(ok=True, text="ok")

    monkeypatch.setattr(CodexCliHarness, "run", fake_run)
    monkeypatch.setattr(cli, "build_execution_readiness", _ready_execution_readiness)

    exit_code = cli.main(
        [
            "run",
            "--agent",
            "codex",
            "--mode",
            "plan",
            "--workspace",
            str(tmp_path),
            "inspect",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "ok"
    assert captured["request"].workspace == str(tmp_path.resolve())
    assert captured["request"].capability.value == "agent_cli"


def test_cli_agent_aliases_include_claude_and_gemini(monkeypatch, capsys):
    captured = []

    def fake_run(self, request, context):
        captured.append((type(self).__name__, request.prompt))
        return HarnessResult(ok=True, text="ok")

    monkeypatch.setattr(ClaudeCodeHarness, "run", fake_run)
    monkeypatch.setattr(GeminiCliHarness, "run", fake_run)
    monkeypatch.setattr(cli, "build_execution_readiness", _ready_execution_readiness)

    assert cli.main(["run", "--agent", "claude", "inspect"]) == 0
    assert cli.main(["run", "--agent", "gemini", "inspect"]) == 0

    output = capsys.readouterr().out
    assert output.strip().splitlines() == ["ok", "ok"]
    assert captured == [
        ("ClaudeCodeHarness", "inspect"),
        ("GeminiCliHarness", "inspect"),
    ]


def test_cli_session_list_json_uses_configured_data_dir(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path))
    store = FilesystemHarnessSessionStore(tmp_path)
    session = store.create_session(title="CLI session", default_harness_id="echo")

    exit_code = cli.main(["session", "list", "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output[0]["id"] == session.id
    assert output[0]["title"] == "CLI session"


def test_cli_session_show_json(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path))
    store = FilesystemHarnessSessionStore(tmp_path)
    session = store.create_session(title="CLI session", default_harness_id="echo")

    exit_code = cli.main(["session", "show", session.id, "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["session"]["id"] == session.id
    assert output["messages"] == []


def test_cli_native_sync_list_and_import_json(monkeypatch, capsys, tmp_path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ref = NativeSessionRef(
        id="native_fake_1",
        harness_id="fake-cli",
        native_session_id="native-session-1",
        title="Fake native session",
        workspace=str(workspace),
        source="external",
        status=NativeSessionStatus.EXTERNAL_NATIVE,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:01:00Z",
        message_count=3,
        can_preview=True,
        can_import=True,
        can_resume=False,
        metadata={"model": "GigaChat-2-Max", "api_mode": "v2"},
    )
    registry = NativeHistoryConnectorRegistry()
    registry.register(
        FakeNativeConnector(
            ref,
            import_messages=(
                NativeTranscriptMessage(role="user", content="native user"),
                NativeTranscriptMessage(role="model", content="native answer"),
                NativeTranscriptMessage(role="mystery", content="skip me"),
            ),
        )
    )
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        cli,
        "create_default_native_registry",
        lambda *, data_dir: registry,
    )

    sync_code = cli.main(
        [
            "native",
            "sync",
            "--harness",
            "fake-cli",
            "--workspace",
            str(workspace),
            "--include-external",
            "--json",
        ]
    )
    sync_payload = json.loads(capsys.readouterr().out)

    assert sync_code == 0
    assert sync_payload["sessions"][0]["id"] == ref.id

    list_code = cli.main(
        [
            "native",
            "list",
            "--harness",
            "fake-cli",
            "--workspace",
            str(workspace),
            "--include-external",
            "--json",
        ]
    )
    list_payload = json.loads(capsys.readouterr().out)

    assert list_code == 0
    assert [item["id"] for item in list_payload] == [ref.id]

    import_code = cli.main(["native", "import", ref.id, "--json"])
    import_payload = json.loads(capsys.readouterr().out)

    assert import_code == 0
    assert import_payload["session"]["default_harness_id"] == "fake-cli"
    assert import_payload["session"]["title"] == "Fake native session"
    assert (
        import_payload["session"]["metadata"]["title_state"]["provenance"]
        == "provider_native"
    )
    assert import_payload["imported_message_count"] == 2
    assert import_payload["skipped_item_count"] == 1
    assert [message["role"] for message in import_payload["messages"]] == [
        "user",
        "assistant",
    ]
    store = FilesystemHarnessSessionStore(data_dir)
    bundle = store.get_session_bundle(import_payload["session"]["id"])
    assert bundle.native_links[0].native_ref_id == ref.id
    assert bundle.events[0].type == "native_import_warning"


@pytest.mark.parametrize(
    ("harness_id", "forbidden"),
    (
        ("codex-cli", ("exec", "--ephemeral")),
        ("claude-code", ("-p", "--no-session-persistence")),
        ("gemini-cli", ("-p", "--skip-trust")),
    ),
)
def test_cli_native_dry_run_prints_command_plan_without_headless_run(
    harness_id,
    forbidden,
    monkeypatch,
    capsys,
    tmp_path,
):
    secret = "sk-native-cli-key-123"

    def supported_gemini_prompt_probe(command, env, cwd):
        del env, cwd

        class Completed:
            returncode = 0
            stdout = "--prompt-interactive Execute prompt and continue interactively"
            stderr = ""

        assert command[-1] == "--help"
        return Completed()

    def fail_run(self, request, context):
        raise AssertionError("headless run should not be called for native dry-run")

    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GPT2GIGA_HARNESS_API_KEY", secret)
    monkeypatch.setattr(CodexCliHarness, "run", fail_run)
    monkeypatch.setattr(ClaudeCodeHarness, "run", fail_run)
    monkeypatch.setattr(GeminiCliHarness, "run", fail_run)
    monkeypatch.setattr(
        "gpt2giga_harness.native.gemini._run_capability_probe",
        supported_gemini_prompt_probe,
    )

    exit_code = cli.main(
        [
            "harness",
            "run",
            harness_id,
            "--native",
            "--dry-run",
            "--prompt",
            "Inspect",
            "--model",
            "GigaChat-2-Max",
            "--api-mode",
            "v2",
            "--json",
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    command = payload["raw"]["native_command_plan"]["command"]

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["text"] == "native dry run"
    assert payload["raw"]["native_command_plan"]["metadata"]["managed"] is True
    readiness = payload["raw"]["preflight"]["readiness"]
    assert readiness["schema_version"] == 2
    assert readiness["status"] in {"ready", "degraded"}
    assert readiness["evidence_status"] in {"not_checked", "unknown"}
    route = next(
        finding for finding in readiness["findings"] if finding["id"] == "route-v2"
    )
    assert route["status"] == "not_checked"
    assert route["remediation"][0]["command"] == "giga doctor --json"
    for item in forbidden:
        assert item not in command
    assert secret not in output
    assert payload["raw"]["native_command_plan"]["env"] != {}


class FakeNativeConnector:
    harness_id = "fake-cli"

    def __init__(
        self,
        ref: NativeSessionRef,
        *,
        import_messages: tuple[NativeTranscriptMessage, ...],
    ) -> None:
        self.ref = ref
        self.import_messages = import_messages

    def discover(self, *, workspace, include_external):
        assert include_external is True
        return (self.ref,)

    def preview(self, ref, *, max_messages=20):
        return self.import_messages[:max_messages]

    def import_ref(self, ref):
        assert ref.id == self.ref.id
        return self.import_messages


class _InvalidPluginHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="invalid-plugin",
            title="Invalid Plugin",
            kind="custom",
            description="Invalid plugin harness for CLI tests",
            capabilities=("future_capability",),
        )

    def availability(self) -> Availability:
        return Availability.available("invalid plugin")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        return HarnessResult(ok=True, text=request.prompt)
