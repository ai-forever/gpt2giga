"""Template capability adapters for a new provider package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gpt2giga.providers.contracts import ProviderAdapterBundle


@dataclass(frozen=True, slots=True)
class TemplateChatAdapter:
    """Example chat adapter shape for a new provider."""

    def build_normalized_request(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ):
        raise NotImplementedError


template_provider_adapters = ProviderAdapterBundle(
    chat=TemplateChatAdapter(),
)
