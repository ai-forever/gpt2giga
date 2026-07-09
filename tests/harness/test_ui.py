import pytest
from fastapi.testclient import TestClient

from gpt2giga.harness import proxy
from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.registry import HarnessRegistry, create_default_registry
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)
from gpt2giga.harness.ui.app import create_app, validate_ui_bind


def test_ui_defaults_endpoint_does_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_API_KEY", "super-secret-api-key")
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "super-secret-gigachat")
    app = create_app(
        HarnessConfig.from_env(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/api/defaults")

    assert response.status_code == 200
    body = response.json()
    assert body["proxy_url"] == "http://127.0.0.1:8090"
    assert body["default_api_mode"] == "v2"
    assert "super-secret-api-key" not in str(body)
    assert "super-secret-gigachat" not in str(body)


def test_ui_harnesses_endpoint_returns_specs():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/api/harnesses")

    assert response.status_code == 200
    ids = {item["spec"]["id"] for item in response.json()["harnesses"]}
    assert "direct-chat" in ids
    assert "echo" in ids


def test_ui_harnesses_endpoint_includes_discovery_errors():
    registry = HarnessRegistry.with_builtins()
    registry.discovery_errors.append("broken-plugin: import failed")
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.get("/api/harnesses")

    assert response.status_code == 200
    assert response.json()["discovery_errors"] == ["broken-plugin: import failed"]


def test_ui_models_rejects_invalid_api_mode_non_fatally():
    app = create_app(
        HarnessConfig(default_model="ConfiguredModel"),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/api/models?api_mode=v3")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["source"] == "fallback"
    assert body["models"][0] == "ConfiguredModel"
    assert "api_mode" in body["error"]


def test_ui_models_handles_discovery_exception_safely(monkeypatch):
    def fail_discovery(config, mode, **kwargs):
        raise RuntimeError("super-secret discovery failure")

    monkeypatch.setattr(proxy, "discover_models", fail_discovery)
    app = create_app(
        HarnessConfig(default_model="ConfiguredModel"),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/api/models?api_mode=v2")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["source"] == "/v2/models"
    assert body["models"] == []
    assert body["error"] == "model discovery failed"
    assert "super-secret" not in str(body)


def test_ui_models_uses_selected_versioned_endpoint_only(monkeypatch):
    captured = {}

    def fake_discovery(config, mode, **kwargs):
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        return proxy.ModelDiscovery(
            ok=True,
            models=("v1-only-model",),
            source=f"/{mode.value}/models",
        )

    monkeypatch.setattr(proxy, "discover_models", fake_discovery)
    app = create_app(
        HarnessConfig(default_model="ConfiguredModel"),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/api/models?api_mode=v1")

    assert response.status_code == 200
    body = response.json()
    assert body["models"] == ["v1-only-model"]
    assert body["source"] == "/v1/models"
    assert captured["mode"].value == "v1"
    assert captured["kwargs"] == {
        "include_compat_paths": False,
        "include_fallback": False,
    }


def test_ui_route_recommendation_endpoint_returns_safe_response():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/route/recommendation",
        json={
            "prompt": "Explain this screenshot",
            "mode": "read",
            "attachments": [
                {
                    "kind": "image",
                    "filename": "secret-token-screen.png",
                    "mime_type": "image/png",
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()["recommendation"]
    assert body["harness_id"] == "direct-chat"
    assert body["mode"] == "read"
    assert body["invocation_mode"] == "headless"
    assert "secret-token-screen.png" not in response.text


def test_ui_can_run_echo_harness():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={"harness_id": "echo", "prompt": "hello", "api_mode": "v2"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["text"] == "hello"


def test_ui_run_passes_stream_and_dry_run_extra():
    harness = _CaptureRequestHarness()
    registry = HarnessRegistry()
    registry.register(harness)
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "harness_id": "capture-run",
            "prompt": "hello",
            "model": "GigaChat-2-Max",
            "api_mode": "v1",
            "capability": "chat_completions",
            "mode": "read",
            "stream": True,
            "dry_run": True,
            "extra": {"custom": "value"},
        },
    )

    assert response.status_code == 200
    assert harness.last_request is not None
    assert harness.last_request.prompt == "hello"
    assert harness.last_request.model == "GigaChat-2-Max"
    assert harness.last_request.api_mode.value == "v1"
    assert harness.last_request.capability.value == "chat_completions"
    assert harness.last_request.mode == "read"
    assert harness.last_request.stream is True
    assert harness.last_request.extra == {"custom": "value", "dry_run": True}


def test_ui_run_passes_explicit_extra_mapping():
    harness = _CaptureRequestHarness()
    registry = HarnessRegistry()
    registry.register(harness)
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "harness_id": "capture-run",
            "prompt": "hello",
            "extra": {"temperature": 0, "dry_run": False},
        },
    )

    assert response.status_code == 200
    assert harness.last_request is not None
    assert harness.last_request.extra == {"temperature": 0, "dry_run": False}


def test_ui_run_rejects_invalid_api_mode_with_400():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={"harness_id": "echo", "prompt": "hello", "api_mode": "v3"},
    )

    assert response.status_code == 400
    assert "api_mode" in response.json()["detail"]


def test_ui_run_rejects_invalid_capability_with_400():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "harness_id": "echo",
            "prompt": "hello",
            "capability": "bad_capability",
        },
    )

    assert response.status_code == 400
    assert "capability" in response.json()["detail"].lower()


def test_ui_run_unknown_harness_returns_404():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={"harness_id": "missing-harness", "prompt": "hello"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown harness"


def test_ui_run_unexpected_error_uses_safe_body():
    registry = HarnessRegistry()
    registry.register(_ExplodingHarness())
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/run",
        json={"harness_id": "explode", "prompt": "hello"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Harness run failed"
    assert "secret" not in response.text


def test_ui_run_resolves_workspace(tmp_path):
    registry = HarnessRegistry()
    registry.register(_WorkspaceCaptureHarness())
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "harness_id": "capture-workspace",
            "prompt": "hello",
            "workspace": str(tmp_path),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["raw"]["workspace"] == str(tmp_path.resolve())


def test_ui_index_contains_control_panel_elements():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    for element_id in (
        "new-chat-button",
        "session-list",
        "session-search",
        "session-workspace-filter",
        "session-harness-filter",
        "include-archived-checkbox",
        "project-status",
        "project-name",
        "project-meta",
        "init-project-button",
        "current-model-badge",
        "current-route-badge",
        "harness-list",
        "harness-select",
        "arena-harness-select",
        "invocation-select",
        "model-input",
        "model-menu-button",
        "model-list",
        "api-mode-v2",
        "api-mode-v1",
        "capability-select",
        "mode-select",
        "workspace-policy-select",
        "workspace-input",
        "dry-run-checkbox",
        "stream-checkbox",
        "composer",
        "prompt-input",
        "attachment-file-input",
        "attach-file-button",
        "attachment-status",
        "attachment-list",
        "workspace-file-menu",
        "sync-native-button",
        "open-native-history-button",
        "native-all-workspaces-checkbox",
        "native-count",
        "native-status",
        "native-history-modal",
        "native-modal-status",
        "native-page-status",
        "native-session-list",
        "load-more-native-button",
        "close-native-history-button",
        "native-terminal-status",
        "native-process-summary",
        "native-terminal-output",
        "native-terminal-input",
        "send-native-input-button",
        "poll-native-output-button",
        "stop-native-process-button",
        "clear-native-terminal-button",
        "run-button",
        "compare-button",
        "cancel-run-button",
        "copy-cli-button",
        "copy-curl-button",
        "reset-button",
        "proxy-status",
        "model-status",
        "harness-details",
        "route-recommendation",
        "route-recommendation-badge",
        "route-recommendation-reasons",
        "apply-route-recommendation-button",
        "preset-status",
        "preset-list",
        "output-panel",
        "run-panel",
        "arena-panel",
        "events-panel",
        "raw-request-panel",
        "raw-response-panel",
        "command-panel",
        "diff-panel",
        "diff-text",
        "apply-branch-input",
        "apply-run-diff-button",
        "discard-run-worktree-button",
        "open-run-worktree-button",
        "attachments-panel",
        "native-panel",
        "storage-panel",
    ):
        assert element_id in html
    for text in (
        "+ New chat",
        "/api/project",
        "/api/project/state",
        "project_id",
        "Project Cockpit",
        "GPT2Giga chats",
        "Native sessions",
        "Sync native history",
        "Browse history",
        "Show all workspaces",
        "Native history unavailable",
        "Load 5 more",
        "Showing 0 of 0",
        "Preview",
        "Import",
        "Link to current chat",
        "Resume native",
        "Terminal output will appear here",
        "Native stdin",
        "Send input",
        "Stop process",
        "Arena",
        "Compare",
        "Recommended",
        "Apply recommendation",
        "/api/route/recommendation",
        "Presets",
        "/api/project/presets",
        "applyPreset",
        "Attachments",
        "Storage",
        "Attach",
        "Cancel",
        "EventSource",
        "/api/arena/runs",
        "/events/stream",
        "/cancel",
        "/diff",
        "/apply",
        "/discard",
        "/open-worktree",
        "Workspace policy",
        "workspace_policy",
        "Apply",
        "Discard",
        "Open worktree",
        'id="apply-run-diff-button" type="button" disabled',
        'id="discard-run-worktree-button" class="danger" type="button" disabled',
        'id="open-run-worktree-button" class="secondary" type="button" disabled',
        "attachment_ids",
        "data_base64",
        "/api/workspace/tree",
        "/attachments/workspace",
        "/attachments",
        "dragover",
        "clipboardData",
        "persistProjectState",
    ):
        assert text in html


def test_ui_rejects_remote_bind_without_allow_remote():
    with pytest.raises(ValueError):
        validate_ui_bind("0.0.0.0", allow_remote=False)


def test_ui_allows_remote_bind_with_explicit_flag():
    validate_ui_bind("0.0.0.0", allow_remote=True)


class _WorkspaceCaptureHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="capture-workspace",
            title="Capture Workspace",
            kind="test",
            description="Capture workspace for UI tests",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_workspace=True,
        )

    def availability(self) -> Availability:
        return Availability.available("test harness")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        return HarnessResult(
            ok=True,
            text="ok",
            raw={"workspace": request.workspace},
        )


class _CaptureRequestHarness(BaseHarness):
    def __init__(self) -> None:
        self.last_request: HarnessRequest | None = None

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="capture-run",
            title="Capture Run",
            kind="test",
            description="Capture request for UI tests",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("test harness")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        self.last_request = request
        return HarnessResult(ok=True, text="ok")


class _ExplodingHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="explode",
            title="Explode",
            kind="test",
            description="Raise for UI tests",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("test harness")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        raise RuntimeError("secret traceback")
