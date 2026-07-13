"""OpenAI Embeddings observability helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.normalized import NormalizedEmbeddingRequest
from gpt2giga.sinks.observability.factory import emit_observability_event
from gpt2giga.sinks.observability.llm import (
    EMBEDDINGS_SPAN_NAME,
    build_llm_embeddings_attributes,
)


async def emit_openai_embeddings_observability(
    state: Any,
    request_payload: Mapping[str, Any],
    transformed_payload: Mapping[str, Any],
    response_payload: Mapping[str, Any],
    *,
    context: RequestContext | None,
) -> None:
    """Emit one OpenInference-style span for an OpenAI Embeddings exchange."""
    sink = getattr(state, "observability_sink", None)
    if sink is None or sink.__class__.__name__ == "NoopObservabilitySink":
        return

    logger = getattr(state, "logger", None)
    try:
        settings = getattr(getattr(state, "config", None), "proxy_settings", None)
        normalized_request = embeddings_request_to_normalized(
            request_payload,
            transformed_payload,
            context=context,
        )
        attributes = build_llm_embeddings_attributes(
            normalized_request,
            response_payload,
            settings=settings,
        )
        emitted = await emit_observability_event(
            sink,
            EMBEDDINGS_SPAN_NAME,
            attributes,
            context=context,
            logger=logger,
        )
        if emitted and context is not None:
            context.llm_observability_emitted = True
    except Exception as exc:
        if logger is not None:
            logger.warning("OpenAI embeddings observability emission failed: {}", exc)


def embeddings_request_to_normalized(
    payload: Mapping[str, Any],
    transformed_payload: Mapping[str, Any],
    *,
    context: RequestContext | None = None,
) -> NormalizedEmbeddingRequest:
    """Convert an OpenAI Embeddings request to a normalized request."""
    raw_extensions = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "dimensions",
            "encoding_format",
            "extra_body",
            "extra_headers",
            "extra_query",
            "input",
            "model",
            "user",
        }
        and value is not None
    }
    return NormalizedEmbeddingRequest(
        id=context.request_id if context is not None else None,
        protocol="openai",
        operation="embeddings",
        model=_string_or_none(transformed_payload.get("model"))
        or _string_or_none(payload.get("model")),
        input=transformed_payload.get("input", payload.get("input")),
        dimensions=_int_or_none(payload.get("dimensions")),
        encoding_format=_string_or_none(payload.get("encoding_format")),
        user=_string_or_none(payload.get("user")),
        raw_extensions=raw_extensions,
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
