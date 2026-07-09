from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.native.models import HarnessInvocationMode
from gpt2giga.harness.registry import HarnessRegistry
from gpt2giga.harness.routing import (
    recommend_harness_route,
    route_recommendation_to_dict,
)
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


def test_router_recommends_direct_chat_for_image_explanation():
    registry = HarnessRegistry()
    registry.register(
        _StaticHarness(
            HarnessSpec(
                id="direct-chat",
                title="Direct Chat",
                kind="built-in",
                description="chat",
                capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
                supports_attachments=True,
                accepted_attachment_kinds=("image", "text"),
            )
        )
    )
    registry.register(_agent("codex-cli"))

    recommendation = recommend_harness_route(
        registry,
        prompt="Explain this screenshot",
        mode="read",
        attachments=({"kind": "image", "filename": "screen.png"},),
    )

    assert recommendation.harness_id == "direct-chat"
    assert recommendation.mode == "read"
    assert recommendation.invocation_mode == HarnessInvocationMode.HEADLESS
    assert any("images" in reason for reason in recommendation.reasons)


def test_router_recommends_codex_for_explicit_edit_workspace():
    registry = HarnessRegistry()
    registry.register(_agent("codex-cli"))
    registry.register(_direct_chat())

    recommendation = recommend_harness_route(
        registry,
        prompt="Refactor this module and update tests",
        mode="edit",
        workspace="/repo",
        selected_files=("src/app.py",),
    )

    assert recommendation.harness_id == "codex-cli"
    assert recommendation.mode == "edit"
    assert any(
        "Edit mode was explicitly selected" in reason
        for reason in recommendation.reasons
    )
    assert not any("keeping mode" in warning for warning in recommendation.warnings)


def test_router_keeps_edit_intent_non_edit_until_explicit():
    registry = HarnessRegistry()
    registry.register(_agent("codex-cli"))
    registry.register(_direct_chat())

    recommendation = recommend_harness_route(
        registry,
        prompt="Fix this bug in src/app.py",
        mode="plan",
        workspace="/repo",
    )

    assert recommendation.harness_id == "codex-cli"
    assert recommendation.mode == "plan"
    assert any(
        "until edit is selected explicitly" in warning
        for warning in recommendation.warnings
    )


def test_router_falls_back_to_available_harness_when_agent_missing():
    registry = HarnessRegistry()
    registry.register(_agent("codex-cli", available=False))
    registry.register(_direct_chat())

    recommendation = recommend_harness_route(
        registry,
        prompt="Fix this module",
        mode="edit",
        workspace="/repo",
    )

    assert recommendation.harness_id == "direct-chat"
    assert any(
        "No available workspace-capable agent harness" in warning
        for warning in recommendation.warnings
    )
    assert recommendation.confidence < 0.8


def test_route_recommendation_serializes_for_api():
    registry = HarnessRegistry()
    registry.register(_direct_chat())

    payload = route_recommendation_to_dict(
        recommend_harness_route(registry, prompt="hello")
    )

    assert payload["harness_id"] == "direct-chat"
    assert payload["invocation_mode"] == "headless"
    assert isinstance(payload["reasons"], list)


def _direct_chat() -> BaseHarness:
    return _StaticHarness(
        HarnessSpec(
            id="direct-chat",
            title="Direct Chat",
            kind="built-in",
            description="chat",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supports_attachments=True,
            accepted_attachment_kinds=("image", "text", "workspace_file"),
        )
    )


def _agent(harness_id: str, *, available: bool = True) -> BaseHarness:
    return _StaticHarness(
        HarnessSpec(
            id=harness_id,
            title=harness_id,
            kind="agent-cli",
            description="agent",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_workspace=True,
            supports_attachments=True,
            accepted_attachment_kinds=("image", "text", "workspace_file", "document"),
            supports_native_sessions=True,
        ),
        available=available,
    )


class _StaticHarness(BaseHarness):
    def __init__(self, spec: HarnessSpec, *, available: bool = True) -> None:
        self._spec = spec
        self._available = available

    def spec(self) -> HarnessSpec:
        return self._spec

    def availability(self) -> Availability:
        if self._available:
            return Availability.available("test")
        return Availability.missing("missing test harness")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return HarnessResult(ok=True, text=request.prompt)
