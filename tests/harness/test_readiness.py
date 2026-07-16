import json

from gpt2giga_harness import proxy, readiness
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.native.models import HarnessInvocationMode
from gpt2giga_harness.preflight import (
    build_preflight_report,
    format_preflight_block_message,
)
from gpt2giga_harness.readiness import build_execution_readiness
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.types import (
    Availability,
    GigaChatApiMode,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)
from gpt2giga_harness.worktrees import WorkspacePolicy


def test_echo_readiness_ignores_proxy_and_worker_for_synchronous_run(
    monkeypatch,
    tmp_path,
):
    registry = HarnessRegistry()
    registry.register(_EchoHarness())
    monkeypatch.setattr(
        readiness.proxy,
        "health_check",
        lambda _config: (_ for _ in ()).throw(
            AssertionError("Echo readiness must not probe the proxy")
        ),
    )

    report = build_execution_readiness(
        HarnessConfig(data_dir=str(tmp_path / "state")),
        registry,
        harness_id="echo",
        invocation_mode=HarnessInvocationMode.HEADLESS,
        api_mode=GigaChatApiMode.V2,
        model=None,
        mode="read",
        workspace=str(tmp_path),
        workspace_policy=WorkspacePolicy.AUTO,
        durable=False,
    )

    assert report["ok"] is True
    assert report["schema_version"] == 2
    assert report["status"] == "ready"
    assert report["evidence_status"] == "observed"
    assert report["summary"] == {
        "ready": 3,
        "not_checked": 0,
        "unknown": 0,
        "degraded": 0,
        "blocked": 0,
    }
    assert {finding["id"] for finding in report["findings"]} == {
        "harness-echo",
        "invocation-mode",
        "delivery",
    }


def test_selected_agent_readiness_blocks_only_required_missing_capabilities(
    monkeypatch,
    tmp_path,
):
    secret = "readiness-secret-value"
    registry = HarnessRegistry()
    registry.register(_AgentHarness(available=False))
    monkeypatch.setattr(
        readiness.proxy,
        "health_check",
        lambda config: proxy.ProxyHealth(
            ok=False,
            url=config.proxy_url,
            error=f"password={secret}",
        ),
    )
    monkeypatch.setattr(
        readiness.proxy,
        "sidecar_preflight",
        lambda _context: proxy.SidecarPreflight(
            ok=False,
            reason=f"credentials={secret}",
        ),
    )

    report = build_execution_readiness(
        HarnessConfig(data_dir=str(tmp_path / "state")),
        registry,
        harness_id="codex-cli",
        invocation_mode=HarnessInvocationMode.HEADLESS,
        api_mode=GigaChatApiMode.V2,
        model="GigaChat-2-Max",
        mode="read",
        workspace=str(tmp_path),
        workspace_policy=WorkspacePolicy.CURRENT,
        durable=False,
    )

    by_id = {finding["id"]: finding for finding in report["findings"]}
    assert report["blocked"] is True
    assert by_id["harness-codex-cli"]["status"] == "blocked"
    assert by_id["proxy-health"]["status"] == "blocked"
    assert by_id["route-v2"]["status"] == "blocked"
    assert by_id["model-discovery"]["status"] == "ready"
    assert "route-v1" not in by_id
    assert secret not in json.dumps(report)
    assert str(tmp_path) not in json.dumps(report)
    assert by_id["harness-codex-cli"]["remediation"][0]["command"] == (
        "giga harness inspect codex-cli --json"
    )


def test_worktree_git_readiness_blocks_edit_but_not_current_read(
    monkeypatch,
    tmp_path,
):
    registry = HarnessRegistry()
    registry.register(_AgentHarness(available=True))
    _ready_proxy(monkeypatch)

    common = {
        "config": HarnessConfig(data_dir=str(tmp_path / "state")),
        "registry": registry,
        "harness_id": "codex-cli",
        "invocation_mode": HarnessInvocationMode.HEADLESS,
        "api_mode": GigaChatApiMode.V2,
        "model": "GigaChat-2-Max",
        "workspace": str(tmp_path),
        "durable": False,
    }
    read_report = build_execution_readiness(
        **common,
        mode="read",
        workspace_policy=WorkspacePolicy.CURRENT,
    )
    edit_report = build_execution_readiness(
        **common,
        mode="edit",
        workspace_policy=WorkspacePolicy.AUTO,
    )

    assert read_report["blocked"] is False
    assert "git-readiness" not in {finding["id"] for finding in read_report["findings"]}
    edit_by_id = {finding["id"]: finding for finding in edit_report["findings"]}
    assert edit_report["blocked"] is True
    assert edit_by_id["git-readiness"]["status"] == "blocked"
    assert edit_by_id["git-readiness"]["remediation"][0]["command"] == "git init"


def test_selected_model_discovery_failure_becomes_redacted_block(monkeypatch, tmp_path):
    registry = HarnessRegistry()
    registry.register(_AgentHarness(available=True))
    _ready_proxy(monkeypatch)
    monkeypatch.setattr(
        readiness.proxy,
        "discover_models",
        lambda *_args, **_kwargs: proxy.ModelDiscovery(
            ok=False,
            models=(),
            source="/v2/models",
            error="password=readiness-secret-value",
        ),
    )

    report = build_execution_readiness(
        HarnessConfig(data_dir=str(tmp_path / "state")),
        registry,
        harness_id="codex-cli",
        invocation_mode=HarnessInvocationMode.HEADLESS,
        api_mode=GigaChatApiMode.V2,
        model="GigaChat-2-Max",
        mode="read",
        workspace=str(tmp_path),
        workspace_policy=WorkspacePolicy.CURRENT,
        durable=False,
    )

    route = next(
        finding for finding in report["findings"] if finding["id"] == "route-v2"
    )
    assert route["status"] == "blocked"
    assert "readiness-secret-value" not in json.dumps(report)
    assert route["remediation"][0]["command"] == "giga doctor --json"


def test_dry_run_route_is_ready_with_explicit_not_checked_evidence(tmp_path):
    registry = HarnessRegistry()
    registry.register(_AgentHarness(available=True))

    report = build_execution_readiness(
        HarnessConfig(data_dir=str(tmp_path / "state")),
        registry,
        harness_id="codex-cli",
        invocation_mode=HarnessInvocationMode.HEADLESS,
        api_mode=GigaChatApiMode.V2,
        model="GigaChat-2-Max",
        mode="read",
        workspace=str(tmp_path),
        workspace_policy=WorkspacePolicy.CURRENT,
        durable=False,
        dry_run=True,
    )

    route = next(
        finding for finding in report["findings"] if finding["id"] == "route-v2"
    )
    assert report["status"] == "ready"
    assert report["evidence_status"] == "not_checked"
    assert report["blocked"] is False
    assert report["summary"]["degraded"] == 0
    assert report["summary"]["not_checked"] == 1
    assert route["status"] == "not_checked"
    assert route["required"] is False
    assert route["remediation"][0]["command"] == "giga doctor --json"


def test_preflight_combines_readiness_block_with_content_safety_report():
    readiness_report = {
        "blocked": True,
        "summary": {"ready": 1, "degraded": 0, "blocked": 1},
        "findings": [
            {
                "id": "harness-codex-cli",
                "status": "blocked",
                "summary": "Selected adapter is missing.",
                "remediation": [],
            }
        ],
    }

    report = build_preflight_report(
        prompt="safe prompt",
        workspace=None,
        readiness=readiness_report,
    )

    assert report.hard_block is True
    assert report.findings == ()
    assert "harness-codex-cli" in format_preflight_block_message(report)


def _ready_proxy(monkeypatch):
    monkeypatch.setattr(
        readiness.proxy,
        "probe_json_route",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("execution readiness must not call Chat Completions")
        ),
    )
    monkeypatch.setattr(
        readiness.proxy,
        "health_check",
        lambda config: proxy.ProxyHealth(
            ok=True,
            url=config.proxy_url,
            path="/health",
            status_code=200,
        ),
    )
    monkeypatch.setattr(
        readiness.proxy,
        "sidecar_preflight",
        lambda _context: proxy.SidecarPreflight(ok=True, reason="ready"),
    )
    monkeypatch.setattr(
        readiness.proxy,
        "discover_models",
        lambda _config, _api_mode, **_kwargs: proxy.ModelDiscovery(
            ok=True,
            models=("GigaChat-2-Max",),
            source="/v2/models",
        ),
    )


class _EchoHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="echo",
            title="Echo",
            kind="test",
            description="Local test harness",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("local")

    def run(self, request: HarnessRequest, context: HarnessContext) -> HarnessResult:
        return HarnessResult(ok=True, text=request.prompt)


class _AgentHarness(BaseHarness):
    def __init__(self, *, available: bool) -> None:
        self.available = available

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="codex-cli",
            title="Codex",
            kind="agent-cli",
            description="Selected agent CLI",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_workspace=True,
            tags=("agent",),
        )

    def availability(self) -> Availability:
        if self.available:
            return Availability.available("test executable")
        return Availability.missing("test executable is missing")

    def run(self, request: HarnessRequest, context: HarnessContext) -> HarnessResult:
        return HarnessResult(ok=True, text=request.prompt)
