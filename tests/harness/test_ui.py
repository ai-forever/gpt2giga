import pytest
from fastapi.testclient import TestClient

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
