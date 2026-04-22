"""Anthropic-compatible provider capability adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gpt2giga.api.anthropic.request_adapter import (
    build_normalized_chat_request,
    build_token_count_texts,
)
from gpt2giga.core.contracts import to_backend_payload
from gpt2giga.providers.contracts import ProviderAdapterBundle
from gpt2giga.providers.descriptors import ProviderDescriptor, ProviderMountSpec


class AnthropicBatchValidationError(ValueError):
    """Raised when an Anthropic batch payload is invalid."""


@dataclass(frozen=True, slots=True)
class AnthropicBatchCreatePayload:
    """Normalized Anthropic batch-create payload."""

    completion_window: str
    rows: list[dict[str, Any]]
    stored_requests: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class AnthropicChatAdapter:
    """Anthropic messages request adapter."""

    def build_normalized_request(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ):
        return build_normalized_chat_request(payload, logger=logger)

    def build_token_count_texts(self, payload: dict[str, Any]) -> list[str]:
        return build_token_count_texts(payload)


@dataclass(frozen=True, slots=True)
class AnthropicBatchesAdapter:
    """Anthropic message batches adapter."""

    def build_create_payload(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> AnthropicBatchCreatePayload:
        completion_window = payload.get("completion_window", "24h")
        if completion_window is None:
            completion_window = "24h"
        if completion_window != "24h":
            raise AnthropicBatchValidationError(
                'Only `completion_window="24h"` is supported.'
            )

        requests_data = payload.get("requests")
        if not isinstance(requests_data, list) or not requests_data:
            raise AnthropicBatchValidationError("`requests` must be a non-empty array.")

        seen_custom_ids: set[str] = set()
        rows: list[dict[str, Any]] = []
        stored_requests: list[dict[str, Any]] = []
        for index, batch_request in enumerate(requests_data):
            if not isinstance(batch_request, dict):
                raise AnthropicBatchValidationError(
                    f"`requests[{index}]` must be an object."
                )

            custom_id = batch_request.get("custom_id")
            params = batch_request.get("params")
            if not isinstance(custom_id, str) or not custom_id:
                raise AnthropicBatchValidationError(
                    f"`requests[{index}].custom_id` must be a non-empty string."
                )
            if custom_id in seen_custom_ids:
                raise AnthropicBatchValidationError(
                    f"Duplicate `custom_id` detected: `{custom_id}`."
                )
            if not isinstance(params, dict):
                raise AnthropicBatchValidationError(
                    f"`requests[{index}].params` must be an object."
                )
            if params.get("stream"):
                raise AnthropicBatchValidationError(
                    "Streaming requests are not supported inside message batches."
                )

            seen_custom_ids.add(custom_id)
            rows.append(
                {
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": to_backend_payload(
                        build_normalized_chat_request(params, logger=logger)
                    ),
                }
            )
            stored_requests.append({"custom_id": custom_id, "params": params})

        return AnthropicBatchCreatePayload(
            completion_window=str(completion_window),
            rows=rows,
            stored_requests=stored_requests,
        )


@dataclass(frozen=True, slots=True)
class AnthropicProviderAdapterBundle(ProviderAdapterBundle):
    """Anthropic adapter bundle with required capabilities."""

    chat: AnthropicChatAdapter = field(default_factory=AnthropicChatAdapter)
    responses: None = None
    embeddings: None = None
    models: None = None
    files: None = None
    batches: AnthropicBatchesAdapter = field(default_factory=AnthropicBatchesAdapter)


anthropic_provider_adapters = AnthropicProviderAdapterBundle(
    chat=AnthropicChatAdapter(),
    batches=AnthropicBatchesAdapter(),
)


def _load_anthropic_router():
    from gpt2giga.api.anthropic import router as anthropic_router

    return anthropic_router


ANTHROPIC_PROVIDER_DESCRIPTOR = ProviderDescriptor(
    name="anthropic",
    display_name="Anthropic",
    capabilities=("messages", "count_tokens", "message_batches"),
    routes=(
        "/messages",
        "/messages/count_tokens",
        "/messages/batches",
        "/v1/messages",
        "/v1/messages/count_tokens",
        "/v1/messages/batches",
    ),
    mounts=(
        ProviderMountSpec(
            router_factory=_load_anthropic_router,
            prefix="/v1",
        ),
        ProviderMountSpec(router_factory=_load_anthropic_router),
    ),
    adapters=anthropic_provider_adapters,
)
