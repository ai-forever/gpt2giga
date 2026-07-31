"""Shared stable-SDK doubles for cross-protocol contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from gigachat.models import ChatCompletion, ChatCompletionChunk
from gigachat.models.chat_completions import (
    ChatCompletionChunk as ChatCompletionV2Chunk,
)
from gigachat.models.chat_completions import ChatCompletionResponse

from gpt2giga.core.context import RequestContext


def payload_dict(payload: Any) -> dict[str, Any]:
    """Return an alias-aware payload mapping for SDK models and dictionaries."""
    if isinstance(payload, dict):
        return payload
    return payload.model_dump(exclude_none=True, by_alias=True)


@dataclass
class RecordingLimiter:
    """Record the effective semaphore identity selected by the gateway."""

    calls: list[tuple[str, str]] = field(default_factory=list)

    @asynccontextmanager
    async def limit(self, model: str, *, provider: str) -> AsyncIterator[None]:
        self.calls.append((model, provider))
        yield


class StableChatResource:
    """Fake the SDK's async v1/v2 chat resource with real response models."""

    def __init__(self, owner: StableSDKClient) -> None:
        self.owner = owner

    async def __call__(self, payload: Any) -> ChatCompletion:
        effective_model = self.owner.record("v1.chat", payload)
        return ChatCompletion.model_validate(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "stable-v1"},
                        "index": 0,
                        "finish_reason": "stop",
                    }
                ],
                "created": 1_785_600_000,
                "model": effective_model or "assistant-model",
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },
                "object": "chat.completion",
            }
        )

    async def create(self, payload: Any) -> ChatCompletionResponse:
        effective_model = self.owner.record("v2.chat", payload)
        return ChatCompletionResponse.model_validate(
            {
                "model": effective_model,
                "created_at": 1_785_600_000,
                "messages": [{"role": "assistant", "content": [{"text": "stable-v2"}]}],
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 1,
                    "total_tokens": 3,
                },
            }
        )

    def stream(self, payload: Any) -> AsyncIterator[ChatCompletionV2Chunk]:
        effective_model = self.owner.record("v2.stream", payload)

        async def generate() -> AsyncIterator[ChatCompletionV2Chunk]:
            yield ChatCompletionV2Chunk.model_validate(
                {
                    "event": "response.message.done",
                    "model": effective_model,
                    "created_at": 1_785_600_000,
                    "messages": [
                        {"role": "assistant", "content": [{"text": "stable-v2"}]}
                    ],
                    "finish_reason": "stop",
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 1,
                        "total_tokens": 3,
                    },
                }
            )

        return generate()


class StableSDKClient:
    """Record SDK calls while returning stable GigaChat response models."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.configured_model: str | None = None
        self.effective_models: list[str | None] = []
        self.achat = StableChatResource(self)

    def record(self, operation: str, payload: Any) -> str | None:
        """Record the SDK input and emulate its whitespace-aware model choice."""
        self.calls.append((operation, payload))
        model = payload_dict(payload).get("model")
        effective = model if isinstance(model, str) and model.strip() else None
        if effective is None:
            configured = self.configured_model
            if isinstance(configured, str) and configured.strip():
                effective = configured
        self.effective_models.append(effective)
        return effective

    def astream(self, payload: Any) -> AsyncIterator[ChatCompletionChunk]:
        effective_model = self.record("v1.stream", payload)

        async def generate() -> AsyncIterator[ChatCompletionChunk]:
            yield ChatCompletionChunk.model_validate(
                {
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": "stable-v1"},
                            "index": 0,
                            "finish_reason": "stop",
                        }
                    ],
                    "created": 1_785_600_000,
                    "model": effective_model or "assistant-model",
                    "object": "chat.completion.chunk",
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                        "total_tokens": 3,
                    },
                }
            )

        return generate()


@pytest.fixture
def stable_sdk_client() -> StableSDKClient:
    """Provide a fresh stable-SDK fake for one contract test."""
    return StableSDKClient()


@pytest.fixture
def recording_limiter() -> RecordingLimiter:
    """Provide a fresh limiter recorder for one contract test."""
    return RecordingLimiter()


@pytest.fixture
def request_context() -> RequestContext:
    """Provide request telemetry state for model-source assertions."""
    return RequestContext(
        request_id="contract-request",
        trace_id="contract-trace",
        span_id=None,
        protocol="openai",
        route="/chat/completions",
        method="POST",
        started_at=datetime.now(timezone.utc),
    )
