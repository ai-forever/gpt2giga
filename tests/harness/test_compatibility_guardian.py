import json

from fastapi.testclient import TestClient

from gpt2giga_harness import cli
from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.compatibility_guardian import (
    compatibility_readiness_check,
    run_compatibility_guardian,
)
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.sessions import InMemoryHarnessSessionStore
from gpt2giga_harness.structured_sessions import AdapterCapabilitySnapshot
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)
from gpt2giga_harness.ui.app import create_app


def test_guardian_runs_deterministic_cli_sdk_schema_and_marketplace_fixtures():
    registry = _guardian_registry()

    first = run_compatibility_guardian(registry)
    second = run_compatibility_guardian(registry)

    assert first == second
    assert first["schema_version"] == 1
    assert first["fixture_version"] == "n7-05-v1"
    assert first["ok"] is True
    assert first["block_execution"] is False
    assert first["summary"]["blocked"] == 0
    assert set(first["failure_taxonomy"]) == {
        "adapter",
        "provider",
        "extension",
        "environment",
        "model",
    }
    assert {item["id"] for item in first["fixtures"]} == {
        "extension.sdk-schema",
        "extension.marketplace",
        "registry.discovery",
        "adapter.codex-cli",
        "provider.codex-cli",
        "adapter.claude-code",
        "provider.claude-code",
        "adapter.gemini-cli",
        "provider.gemini-cli",
    }
    assert all(len(item["evidence_hash"]) == 64 for item in first["fixtures"])
    assert len(first["snapshot_hash"]) == 64


def test_guardian_blocks_unreviewed_cli_version_without_leaking_probe_detail():
    secret = "guardian-secret-value"
    registry = HarnessRegistry()
    registry.register(
        _GuardianHarness(
            "codex-cli",
            _snapshot(
                "codex-cli",
                version="0.145.0",
                status="degraded",
                version_window_status="above_window",
                warning=f"token={secret}",
            ),
        )
    )

    report = run_compatibility_guardian(registry)
    readiness = compatibility_readiness_check(registry.get("codex-cli"))

    assert report["ok"] is False
    assert report["block_execution"] is True
    assert report["summary"]["categories"]["adapter"]["blocked"] == 1
    assert report["summary"]["categories"]["provider"]["blocked"] == 1
    adapter = next(
        item for item in report["fixtures"] if item["id"] == "adapter.codex-cli"
    )
    assert adapter["code"] == "native_cli_contract_drift"
    assert readiness is not None
    assert readiness["status"] == "blocked"
    assert readiness["required"] is True
    assert readiness["evidence"]["reason_codes"] == [
        "adapter_contract_unavailable",
        "native_cli_contract_drift",
    ]
    assert secret not in json.dumps(report)
    assert secret not in json.dumps(readiness)


def test_guardian_classifies_missing_cli_as_environment_failure():
    registry = HarnessRegistry()
    registry.register(
        _GuardianHarness(
            "claude-code",
            _snapshot(
                "claude-code",
                version=None,
                status="missing",
                version_window_status="not_probed",
            ),
        )
    )

    report = run_compatibility_guardian(registry)

    missing = next(
        item for item in report["fixtures"] if item["id"] == "adapter.claude-code"
    )
    assert missing["category"] == "environment"
    assert missing["code"] == "cli_missing"
    assert report["summary"]["categories"]["environment"]["blocked"] == 1


def test_cli_compatibility_check_is_headless_and_returns_failure_exit(
    capsys,
    monkeypatch,
):
    registry = _guardian_registry()
    monkeypatch.setattr(cli, "create_default_registry", lambda: registry)

    assert cli.main(["compatibility", "check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready"

    registry.get("gemini-cli").snapshot = _snapshot(
        "gemini-cli",
        version="0.47.0",
        status="degraded",
        version_window_status="above_window",
    )
    assert (
        cli.main(
            [
                "compatibility",
                "check",
                "--harness",
                "gemini-cli",
                "--json",
            ]
        )
        == 1
    )
    failed = json.loads(capsys.readouterr().out)
    assert failed["status"] == "blocked"
    assert {item["id"] for item in failed["fixtures"]} >= {
        "adapter.gemini-cli",
        "provider.gemini-cli",
    }


def test_compatibility_guardian_api_runs_same_bounded_selected_fixture(tmp_path):
    registry = HarnessRegistry()
    registry.register(
        _GuardianHarness("claude-code", _snapshot("claude-code", "2.1.9"))
    )
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "state")),
            registry=registry,
            store=InMemoryHarnessSessionStore(),
        )
    )

    response = client.get(
        "/api/compatibility/guardian",
        params={"harness": "claude-code"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert {item["id"] for item in payload["fixtures"]} == {
        "extension.sdk-schema",
        "extension.marketplace",
        "registry.discovery",
        "adapter.claude-code",
        "provider.claude-code",
    }


class _GuardianHarness(BaseHarness):
    def __init__(self, harness_id: str, snapshot: CliCapabilitySnapshot) -> None:
        self.harness_id = harness_id
        self.snapshot = snapshot

    def spec(self) -> HarnessSpec:
        return HarnessSpec(
            id=self.harness_id,
            title=self.harness_id,
            kind="agent-cli",
            description="Hermetic compatibility guardian harness",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_workspace=True,
            supports_streaming=True,
            supports_structured_events=True,
        )

    def availability(self) -> Availability:
        return Availability.available("hermetic")

    def capability_probe(self) -> CliCapabilitySnapshot:
        return self.snapshot

    def durable_structured_capabilities(self) -> AdapterCapabilitySnapshot:
        protocol = {
            "codex-cli": "codex-app-server-json-rpc-v2",
            "gemini-cli": "agent-client-protocol",
        }.get(self.harness_id, "not-applicable")
        version = "2" if self.harness_id == "codex-cli" else "1"
        return AdapterCapabilitySnapshot(
            adapter_id=self.harness_id,
            adapter_version="0.4.0",
            protocol=protocol,
            protocol_version=version,
            structured_events=True,
            partial_output=True,
            interactive_input=False,
            live_approvals=True,
            durable_approval=True,
            interrupt=True,
            steer=True,
            resume=True,
            fork=False,
            session_list=False,
            session_close=False,
            native_auth=False,
            provider_ui_handoff=False,
            dynamic_model=False,
            dynamic_mcp=False,
            recovery_after_process_loss=True,
        )

    def run_durable_structured(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return self.run(request, context)

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return HarnessResult(ok=True, text=request.prompt)


def _guardian_registry() -> HarnessRegistry:
    registry = HarnessRegistry()
    for harness_id, version in (
        ("codex-cli", "0.144.5"),
        ("claude-code", "2.1.9"),
        ("gemini-cli", "0.46.2"),
    ):
        registry.register(_GuardianHarness(harness_id, _snapshot(harness_id, version)))
    return registry


def _snapshot(
    harness_id: str,
    version: str | None,
    *,
    status: str = "supported",
    version_window_status: str = "in_window",
    warning: str | None = None,
) -> CliCapabilitySnapshot:
    contracts = {
        "codex-cli": {
            "minimum": "0.144.0",
            "maximum": "0.145.0",
            "event": "codex-exec-jsonl-v1",
            "history": "codex-session-jsonl-v1",
            "capabilities": ("--json", "--sandbox", "--ephemeral", "app-server"),
        },
        "claude-code": {
            "minimum": "2.1.0",
            "maximum": "2.2.0",
            "event": "claude-stream-json-v1",
            "history": "claude-project-jsonl-v1",
            "capabilities": (
                "--output-format",
                "stream-json",
                "--permission-mode",
                "--no-session-persistence",
            ),
        },
        "gemini-cli": {
            "minimum": "0.46.0",
            "maximum": "0.47.0",
            "event": "gemini-stream-json-v1",
            "history": "gemini-checkpoint-jsonl-v1",
            "capabilities": (
                "--output-format",
                "stream-json",
                "--approval-mode",
                "--skip-trust",
                "--acp",
                "--experimental-acp",
            ),
        },
    }
    contract = contracts[harness_id]
    return CliCapabilitySnapshot(
        harness_id=harness_id,
        status=status,
        version=version,
        parsed_version=version,
        command=(harness_id,),
        capabilities={item: True for item in contract["capabilities"]},
        event_schema=contract["event"],
        history_schema=contract["history"],
        native_event_schema="raw-terminal-v1",
        warning=warning,
        version_window_status=version_window_status,
        minimum_version=contract["minimum"],
        maximum_version_exclusive=contract["maximum"],
    )
