"""Execution-mode selection tests for the OpenAI Responses route."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from gpt2giga.app.responses_mode import (
    ResponsesExecutionMode,
    select_responses_execution,
)
from gpt2giga.core.context import RequestContext, request_context_var
from gpt2giga.providers.profiles import ProviderAliasError, ProviderKind


@dataclass(frozen=True)
class _Route:
    provider_kind: ProviderKind
    profile_id: str = "profile-1"
    public_alias: str = "model-1"

    def execution_context(self) -> dict[str, str]:
        return {
            "profile_id": self.profile_id,
            "provider_kind": self.provider_kind.value,
            "public_alias": self.public_alias,
        }


class _Registry:
    def __init__(self, route: _Route | None, *, synthesized: bool = False) -> None:
        self.route = route
        self.resolve_calls: list[object] = []
        self.config = SimpleNamespace(
            profiles=(
                SimpleNamespace(
                    profile_id=("legacy-gigachat" if synthesized else "profile-1"),
                    provider_kind=(
                        ProviderKind.GIGACHAT
                        if synthesized
                        else ProviderKind.OPENAI_COMPATIBLE
                    ),
                ),
            )
        )

    def resolve(self, model: object) -> _Route:
        self.resolve_calls.append(model)
        if self.route is None:
            raise ProviderAliasError("alias_unknown")
        return self.route


@pytest.mark.parametrize(
    ("provider_kind", "expected_mode"),
    [
        (ProviderKind.GIGACHAT, ResponsesExecutionMode.NATIVE_GIGACHAT),
        (
            ProviderKind.OPENAI_COMPATIBLE,
            ResponsesExecutionMode.NORMALIZED_BRIDGE,
        ),
        (ProviderKind.ANTHROPIC, ResponsesExecutionMode.NORMALIZED_BRIDGE),
        (ProviderKind.GEMINI, ResponsesExecutionMode.NORMALIZED_BRIDGE),
    ],
)
def test_exact_provider_route_selects_one_owner(
    provider_kind: ProviderKind,
    expected_mode: ResponsesExecutionMode,
) -> None:
    registry = _Registry(_Route(provider_kind))

    selection = select_responses_execution(
        SimpleNamespace(provider_registry=registry),
        requested_model="model-1",
    )

    assert selection.mode is expected_mode
    assert registry.resolve_calls == ["model-1"]


def test_config_free_gigachat_accepts_provider_visible_model() -> None:
    registry = _Registry(None, synthesized=True)

    selection = select_responses_execution(
        SimpleNamespace(provider_registry=registry),
        requested_model="GigaChat-2-Pro",
    )

    assert selection.mode is ResponsesExecutionMode.NATIVE_GIGACHAT
    assert selection.reason == "config_free_gigachat_model"
    assert registry.resolve_calls == ["GigaChat-2-Pro"]


def test_explicit_profile_rejects_unknown_alias() -> None:
    registry = _Registry(None)

    with pytest.raises(ProviderAliasError) as error:
        select_responses_execution(
            SimpleNamespace(provider_registry=registry),
            requested_model="missing/alias",
        )

    assert error.value.code == "unknown_model_alias"
    assert registry.resolve_calls == ["missing/alias"]


def test_selection_is_recorded_in_request_context_before_dispatch() -> None:
    context = RequestContext(
        request_id="request-1",
        trace_id="trace-1",
        span_id=None,
        protocol="openai",
        route="/responses",
        method="POST",
        started_at=datetime.now(timezone.utc),
    )
    route = _Route(ProviderKind.GIGACHAT)
    token = request_context_var.set(context)
    try:
        selection = select_responses_execution(
            SimpleNamespace(provider_registry=_Registry(route)),
            requested_model="model-1",
        )
    finally:
        request_context_var.reset(token)

    assert selection.mode is ResponsesExecutionMode.NATIVE_GIGACHAT
    assert context.model_requested == "model-1"
    assert context.provider_kind == "gigachat"
    assert context.metadata == {
        "responses_execution_mode": "native_gigachat",
        "responses_execution_reason": "gigachat_provider_route",
    }
