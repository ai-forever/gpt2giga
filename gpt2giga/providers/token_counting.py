"""Shared token-count helpers for provider compatibility routes."""

from __future__ import annotations

from typing import Any

from gpt2giga.providers.contracts import TokenCountProviderAdapter


async def count_input_tokens(
    adapter: TokenCountProviderAdapter,
    payload: dict[str, Any],
    *,
    giga_client: Any,
    model: str,
) -> int:
    """Count input tokens for a provider payload via the upstream client."""
    texts = adapter.build_token_count_texts(payload)
    if not texts:
        return 0

    token_counts = await giga_client.atokens_count(texts, model=model)
    return sum(token_count.tokens for token_count in token_counts)
