import pytest
from fastapi.testclient import TestClient

from gpt2giga_harness import proxy
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)
from gpt2giga_harness.ui.app import create_app, validate_ui_bind


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
    harnesses = response.json()["harnesses"]
    ids = {item["spec"]["id"] for item in harnesses}
    assert "direct-chat" in ids
    assert "echo" in ids
    codex = next(item for item in harnesses if item["spec"]["id"] == "codex-cli")
    assert codex["compatibility"]["event_schema"] == "codex-exec-jsonl-v1"
    assert codex["compatibility"]["history_schema"] == "codex-session-jsonl-v1"
    assert codex["compatibility"]["native_event_schema"] == "raw-terminal-v1"
    assert codex["compatibility"]["native_structured_events"] is False


def test_ui_harnesses_endpoint_includes_discovery_errors():
    registry = HarnessRegistry.with_builtins()
    registry.discovery_errors.append("broken-plugin: import failed")
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.get("/api/harnesses")

    assert response.status_code == 200
    assert response.json()["discovery_errors"] == ["broken-plugin: import failed"]


def test_ui_harnesses_endpoint_includes_plugin_metadata():
    registry = HarnessRegistry()
    registry.register(_SchemaPluginHarness())
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.get("/api/harnesses")

    assert response.status_code == 200
    item = response.json()["harnesses"][0]
    assert item["spec"]["id"] == "schema-plugin"
    assert item["spec"]["plugin_metadata"]["icon"] == "plug"
    assert (
        item["spec"]["plugin_metadata"]["config_schema"]["properties"]["endpoint"][
            "type"
        ]
        == "string"
    )
    assert item["validation"]["ok"] is True


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
    assert body["health"] == "unknown"
    assert body["last_checked_at"]
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
    assert body["api_mode"] == "v2"
    assert body["health"] == "unknown"
    assert body["route_path"] == "/v2/models"
    assert body["last_checked_at"]
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
    assert body["api_mode"] == "v1"
    assert body["health"] == "ready"
    assert body["route_path"] == "/v1/models"
    assert body["last_checked_at"]
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


def test_ui_can_run_echo_harness(tmp_path):
    app = create_app(
        HarnessConfig(data_dir=str(tmp_path)),
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


def test_ui_run_maps_v2_builtin_tools_into_direct_chat_payload():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "harness_id": "direct-chat",
            "prompt": "search and calculate",
            "api_mode": "v2",
            "builtin_tools": ["web_search", "code_interpreter"],
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["raw"]["payload"]["tools"] == [
        {"type": "web_search"},
        {"type": "code_interpreter"},
    ]


def test_ui_run_rejects_builtin_tools_outside_supported_v2_harness():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    v1_response = client.post(
        "/api/run",
        json={
            "harness_id": "direct-chat",
            "prompt": "search",
            "api_mode": "v1",
            "builtin_tools": ["web_search"],
        },
    )
    unsupported_response = client.post(
        "/api/run",
        json={
            "harness_id": "echo",
            "prompt": "search",
            "api_mode": "v2",
            "builtin_tools": ["web_search"],
        },
    )

    assert v1_response.status_code == 400
    assert "/v2/chat/completions" in v1_response.json()["detail"]
    assert unsupported_response.status_code == 400
    assert "does not support built-in tools" in unsupported_response.json()["detail"]


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


def test_ui_run_blocks_private_key_prompt_without_echoing_secret():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)
    prompt = "-----BEGIN PRIVATE KEY-----\nnot-real-secret\n-----END PRIVATE KEY-----"

    response = client.post(
        "/api/run",
        json={"harness_id": "echo", "prompt": prompt},
    )

    assert response.status_code == 400
    assert "Preflight blocked" in response.json()["detail"]
    assert "not-real-secret" not in response.text


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


def test_ui_rejects_remote_bind_without_allow_remote():
    with pytest.raises(ValueError, match="Pass --allow-remote"):
        validate_ui_bind(
            HarnessConfig(ui_host="0.0.0.0"),
            allow_remote=False,
        )


def test_ui_remote_flag_does_not_bypass_identity_boundary():
    with pytest.raises(ValueError, match="issuer, client ID, client secret"):
        validate_ui_bind(
            HarnessConfig(ui_host="0.0.0.0"),
            allow_remote=True,
        )


def test_ui_rejects_non_loopback_hostname_without_explicit_flag():
    with pytest.raises(ValueError, match="harness.example.*Pass --allow-remote"):
        validate_ui_bind(
            HarnessConfig(ui_host="harness.example"),
            allow_remote=False,
        )


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


class _SchemaPluginHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="schema-plugin",
            title="Schema Plugin",
            kind="custom",
            description="Schema-backed plugin harness",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            icon="plug",
            config_schema={
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "title": "Endpoint",
                    }
                },
            },
            metadata={"package": "schema-plugin"},
        )

    def availability(self) -> Availability:
        return Availability.available("schema plugin")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        return HarnessResult(ok=True, text=request.prompt)


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
