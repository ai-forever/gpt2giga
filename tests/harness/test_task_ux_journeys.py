from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.integration_flows import IntegrationFlowService
from gpt2giga_harness.native_cli_contracts import (
    CapabilityLevel,
    NativeCommandClass,
    RouteReason,
    classify_native_route,
)
from gpt2giga_harness.project import init_project_config
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.runtime.policy import (
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
    permission_profile,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)
from gpt2giga_harness.ui.app import create_app


FIXTURE = Path(__file__).parent / "fixtures" / "task_ux_journeys.json"
EXPECTED_JOURNEYS = {
    "ask-question",
    "review-repository",
    "make-isolated-change",
    "connect-or-disable-mcp",
    "run-or-author-automation",
    "provider-login-guidance",
    "request-network-or-github-grant",
    "recover-disconnect",
}


def _journey_fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_task_journey_manifest_binds_public_routes_outcomes_and_authority():
    fixture = _journey_fixture()
    journeys = fixture["journeys"]
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    public_routes = {
        f"{method.upper()} {path}"
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }

    assert fixture["schema_version"] == 1
    assert {journey["id"] for journey in journeys} == EXPECTED_JOURNEYS
    for journey in journeys:
        assert journey["outcomes"]
        assert journey["authority"]["ceiling"]
        assert journey["authority"]["mutation"]
        assert set(journey["api_routes"]) <= public_routes
    serialized = json.dumps(fixture, sort_keys=True)
    assert not {
        "selector",
        "data-testid",
        "widget",
        "checkbox",
        "drawer",
        "headless",
        "transport",
    } & set(serialized.lower().replace('"', " ").split())


def test_ask_and_review_journeys_keep_read_only_authority_and_visible_results(
    tmp_path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
        )
    )

    ask = client.post(
        "/api/sessions/run",
        json={
            "authority": "read_only",
            "harness_id": "echo",
            "prompt": "What does this repository do?",
            "task_intent": "ask",
            "workbench_kind": "direct_chat",
            "workspace": str(workspace),
        },
    )
    review = client.post(
        "/api/sessions/run",
        json={
            "authority": "read_only",
            "harness_id": "echo",
            "prompt": "Review the repository without editing it.",
            "task_intent": "review",
            "workbench_kind": "direct_chat",
            "workspace": str(workspace),
        },
    )

    assert ask.status_code == 200
    assert review.status_code == 200
    assert ask.json()["result"]["text"] == "What does this repository do?"
    assert review.json()["result"]["text"] == (
        "Review the repository without editing it."
    )
    for response, intent, mode in (
        (ask, "ask", "plan"),
        (review, "review", "read"),
    ):
        admission = response.json()["run"]["metadata"]["workbench_admission"]
        assert admission["intent"] == intent
        assert admission["authority"] == "read_only"
        assert admission["mode"] == mode
    assert source.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_change_journey_isolates_review_and_requires_exact_apply_approval(tmp_path):
    repository = _git_repository(tmp_path / "repository")
    registry = HarnessRegistry()
    registry.register(_FileEditHarness())
    config = HarnessConfig(data_dir=str(tmp_path / "data"))
    runtime = RuntimeCoordinationStore(config.data_dir)
    client = TestClient(create_app(config, registry=registry, runtime_store=runtime))

    started = client.post(
        "/api/sessions/run",
        json={
            "authority": "workspace_write",
            "harness_id": "edit-file",
            "prompt": "Make the isolated change.",
            "task_intent": "change",
            "workbench_kind": "coding_agent",
            "workspace": str(repository),
        },
    )

    assert started.status_code == 200
    run = started.json()["run"]
    admission = run["metadata"]["workbench_admission"]
    assert admission["intent"] == "change"
    assert admission["authority"] == "workspace_write"
    assert admission["mode"] == "edit"
    assert (repository / "app.txt").read_text(encoding="utf-8") == "base\n"

    diff = client.get(f"/api/runs/{run['id']}/diff").json()["diff"]
    assert diff["workspace_execution"]["policy"] == "worktree"
    assert diff["can_apply"] is True
    assert diff["changed_files"] == ["app.txt"]
    assert "diff --git a/app.txt b/app.txt" in diff["patch"]

    requested = client.post(f"/api/runs/{run['id']}/apply", json={})
    assert requested.status_code == 202
    approval = requested.json()["approval"]
    assert approval["action"] == "git.apply"
    assert (repository / "app.txt").read_text(encoding="utf-8") == "base\n"
    decided = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "allow_once"},
    )
    assert decided.status_code == 200
    applied = client.post(f"/api/runs/{run['id']}/apply", json={})
    assert applied.status_code == 200
    assert applied.json()["applied"] is True
    assert (repository / "app.txt").read_text(encoding="utf-8") == "changed\n"


def test_mcp_journey_connects_then_disables_only_after_reviewed_operations(tmp_path):
    driver = _FakeMCPDriver("codex-mcp")
    service = IntegrationFlowService(
        tmp_path / "data",
        mcp_driver_provider=lambda target_id: (
            driver if target_id == "codex-mcp" else None
        ),
    )
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
            integration_flow_service=service,
        )
    )

    preview = client.post(
        "/api/integrations/preview",
        json={
            "source": "raw_descriptor",
            "package_id": "fixture-mcp",
            "target_id": "codex-mcp",
            "scope": "managed_home",
            "configuration": {
                "transport": "stdio",
                "command": "fixture-mcp",
                "args": ["--stdio"],
            },
        },
    ).json()
    without_consent = client.post(
        f"/api/integrations/flows/{preview['flow']['id']}/apply",
        json={
            "plan_id": preview["plan"]["plan_id"],
            "authority": "journey-operator",
        },
    )
    assert without_consent.status_code == 409

    connected = client.post(
        f"/api/integrations/flows/{preview['flow']['id']}/apply",
        json={
            "plan_id": preview["plan"]["plan_id"],
            "authority": "journey-operator",
            "native_consent_acknowledged": True,
        },
    )
    assert connected.status_code == 200
    assert connected.json()["flow"]["status"] == "verified"

    lifecycle = client.post(
        f"/api/integrations/flows/{preview['flow']['id']}/lifecycle/preview",
        json={"action": "disable"},
    ).json()
    disabled = client.post(
        f"/api/integrations/lifecycle/{lifecycle['operation']['id']}/apply",
        json={
            "authority": "journey-operator",
            "expected_revisions": lifecycle["plan"]["expected_revisions"],
            "plan_id": lifecycle["plan"]["plan_id"],
        },
    )
    assert disabled.status_code == 200
    assert disabled.json()["receipt"]["action"] == "disable"
    assert disabled.json()["receipt"]["outcome"] == "succeeded"
    assert client.get("/api/integrations").json()["installations"][0]["state"] == (
        "disabled"
    )


def test_automation_journey_authors_and_runs_one_revision_bound_workflow(tmp_path):
    client, worker = _workflow_client(tmp_path)
    _author_workflow(client, tmp_path / "workspace")

    worker["online"] = True
    started = client.post(
        "/api/workflows/journey-flow/run",
        json={
            "idempotency_key": "journey-run-1",
            "prompt": "Run the retained workflow.",
            "workspace": str(tmp_path / "workspace"),
        },
    )

    assert started.status_code == 200
    run = started.json()["run"]
    assert run["workflow_id"] == "journey-flow"
    assert run["definition_hash"]
    assert run["status"] == "succeeded"
    assert run["steps"][0]["status"] == "succeeded"


def test_provider_login_journey_stays_native_owned_and_non_authoritative():
    for namespace, suffix, version in (
        ("codex", ("login",), "0.144.3"),
        ("claude", ("auth",), "2.1.197"),
    ):
        decision = classify_native_route(namespace, suffix, version=version)
        assert decision.level is CapabilityLevel.NATIVE_PASSTHROUGH
        assert decision.reason is RouteReason.NATIVE_OWNED
        assert decision.command_class is NativeCommandClass.ADMINISTRATION
        assert decision.execution_authorized is False
        assert decision.intent_pattern_id is None


def test_network_and_github_grants_stay_pending_until_explicit_decision(tmp_path):
    runtime = RuntimeCoordinationStore(tmp_path / "data")
    engine = PolicyEngine(runtime)
    profile = permission_profile("review-every-action")
    requests = []
    for action, reason, preview in (
        (
            PermissionAction.NETWORK_CONNECT,
            "Connect to the reviewed API host.",
            {"host": "api.example.invalid", "port": 443, "method": "GET"},
        ),
        (
            PermissionAction.GITHUB_PULL_REQUEST_CREATE,
            "Create a pull request in the reviewed repository.",
            {"repository": "example/project", "base": "main"},
        ),
    ):
        context = PolicyContext(
            project_id="project-journey",
            run_id="run-journey",
            reason=reason,
            preview=preview,
        )
        resolution = engine.resolve(action, profile=profile, context=context)
        assert resolution.decision is PolicyDecision.ASK
        requests.append(runtime.create_approval_request(resolution, context))

    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            runtime_store=runtime,
        )
    )
    inbox = client.get("/api/approvals", params={"status": "pending"}).json()
    assert inbox["pending_count"] == 2
    assert {item["action"] for item in inbox["approvals"]} == {
        "network.connect",
        "github.pull_request.create",
    }
    assert not runtime.consume_matching_approval_grant(
        action=PermissionAction.NETWORK_CONNECT,
        project_id="project-journey",
        run_id="run-journey",
        job_id=None,
    )
    assert not runtime.consume_matching_approval_grant(
        action=PermissionAction.GITHUB_PULL_REQUEST_CREATE,
        project_id="project-journey",
        run_id="run-journey",
        job_id=None,
    )

    decided = client.post(
        f"/api/approvals/{requests[0].id}/decision",
        json={"decision": "allow_once"},
    )
    assert decided.status_code == 200
    assert runtime.consume_matching_approval_grant(
        action=PermissionAction.NETWORK_CONNECT,
        project_id="project-journey",
        run_id="run-journey",
        job_id=None,
    )
    assert not runtime.consume_matching_approval_grant(
        action=PermissionAction.GITHUB_PULL_REQUEST_CREATE,
        project_id="project-journey",
        run_id="run-journey",
        job_id=None,
    )


def test_disconnect_recovery_replays_identity_and_rejects_conflicting_intent(tmp_path):
    client, worker = _workflow_client(tmp_path)
    workspace = tmp_path / "workspace"
    _author_workflow(client, workspace)
    request = {
        "idempotency_key": "disconnect-recovery-1",
        "prompt": "Run once.",
        "workspace": str(workspace),
    }
    worker["online"] = True
    started = client.post("/api/workflows/journey-flow/run", json=request)
    worker["online"] = False

    replayed = client.post("/api/workflows/journey-flow/run", json=request)
    conflicting = client.post(
        "/api/workflows/journey-flow/run",
        json={**request, "prompt": "Different intent."},
    )

    assert started.status_code == 200
    assert replayed.status_code == 200
    assert replayed.json()["run"]["id"] == started.json()["run"]["id"]
    assert replayed.json()["run"]["session_id"] == started.json()["run"]["session_id"]
    assert conflicting.status_code == 409
    assert "different workflow submission" in conflicting.json()["detail"]


class _FileEditHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="edit-file",
            title="Edit File",
            kind="agent-cli",
            description="Hermetic journey edit harness",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_workspace=True,
        )

    def availability(self) -> Availability:
        return Availability.available("hermetic")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        workspace = Path(request.workspace or "")
        (workspace / "app.txt").write_text("changed\n", encoding="utf-8")
        return HarnessResult(ok=True, text="Isolated change ready for review.")


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


def _git_repository(path: Path) -> Path:
    path.mkdir()
    subprocess.run(("git", "init", "-b", "main"), cwd=path, check=True)
    subprocess.run(
        ("git", "config", "user.email", "journey@example.invalid"),
        cwd=path,
        check=True,
    )
    subprocess.run(
        ("git", "config", "user.name", "Journey Fixture"),
        cwd=path,
        check=True,
    )
    (path / "app.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(("git", "add", "app.txt"), cwd=path, check=True)
    subprocess.run(
        ("git", "commit", "-m", "seed journey"),
        cwd=path,
        check=True,
    )
    return path


def _workflow_client(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_project_config(workspace)
    config = HarnessConfig(
        data_dir=str(tmp_path / "data"),
        proxy_url="http://127.0.0.1:9",
        auto_start_proxy=False,
    )
    app = create_app(config)
    worker = {"online": False}
    app.state.harness_schedule_service.worker_health = lambda: {
        "online": worker["online"],
        "count": int(worker["online"]),
    }
    return TestClient(app), worker


def _author_workflow(client: TestClient, workspace: Path) -> None:
    content = "\n".join(
        [
            "id: journey-flow",
            "title: Journey flow",
            "version: '1.0.0'",
            "steps:",
            "  - id: retain",
            "    kind: transform",
            "    transform: identity",
            "",
        ]
    )
    preview = client.post(
        "/api/workflows/journey-flow/draft",
        json={"workspace": str(workspace), "content": content},
    )
    assert preview.status_code == 200
    applied = client.post(
        "/api/workflows/journey-flow/apply",
        json={
            "workspace": str(workspace),
            "content": content,
            "expected_hash": preview.json()["source_hash"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["workflow"]["source_hash"]
