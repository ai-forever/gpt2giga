"""GigaChat embeddings request mapping entry point."""

from __future__ import annotations

import functools
from typing import Any

import anyio
import tiktoken


class GigaChatEmbeddingsMapper:
    """Wrap embeddings-specific request mapping for the GigaChat provider."""

    async def prepare_request(
        self,
        data: dict[str, Any],
        *,
        embeddings_model: str,
    ) -> dict[str, Any]:
        """Prepare a GigaChat embeddings request."""
        inputs = data.get("input", [])
        openai_model = data.get("model")
        normalized_inputs = await _normalize_embedding_inputs(inputs, openai_model)
        return {
            "input": normalized_inputs,
            "model": embeddings_model,
        }


async def transform_embedding_body(
    data: dict[str, Any],
    embeddings_model: str,
) -> dict[str, Any]:
    """Transform an OpenAI embeddings request into a GigaChat embeddings payload."""
    return await GigaChatEmbeddingsMapper().prepare_request(
        data,
        embeddings_model=embeddings_model,
    )


async def _normalize_embedding_inputs(inputs: Any, model: Any) -> list[str]:
    if isinstance(inputs, list):
        new_inputs: list[str] = []
        if inputs and isinstance(inputs[0], int):
            encoder = await anyio.to_thread.run_sync(
                functools.partial(tiktoken.encoding_for_model, model)
            )
            new_inputs = [encoder.decode(inputs)]
        else:
            encoder = None
            for row in inputs:
                if isinstance(row, list):
                    if encoder is None:
                        encoder = await anyio.to_thread.run_sync(
                            functools.partial(tiktoken.encoding_for_model, model)
                        )
                    new_inputs.append(encoder.decode(row))
                else:
                    new_inputs.append(row)
        return new_inputs
    return [inputs]
