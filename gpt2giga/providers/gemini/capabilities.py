"""Gemini-compatible provider capability adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gpt2giga.api.gemini.request import normalize_model_name
from gpt2giga.api.gemini.request_adapter import (
    build_batch_embeddings_request,
    build_count_tokens_texts,
    build_normalized_chat_request,
    build_single_embeddings_request,
)
from gpt2giga.api.gemini.response import build_gemini_model
from gpt2giga.features.models.contracts import ModelDescriptor
from gpt2giga.providers.contracts import ProviderAdapterBundle
from gpt2giga.providers.descriptors import ProviderDescriptor, ProviderMountSpec


@dataclass(frozen=True, slots=True)
class GeminiChatAdapter:
    """Gemini content-generation request adapter."""

    def build_normalized_request(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ):
        return build_normalized_chat_request(payload, logger=logger)

    def build_count_tokens_texts(self, payload: dict[str, Any]) -> list[str]:
        return build_count_tokens_texts(payload)


@dataclass(frozen=True, slots=True)
class GeminiEmbeddingsAdapter:
    """Gemini embeddings request adapter."""

    def build_normalized_request(self, payload: dict[str, Any]):
        return build_single_embeddings_request(payload, "")

    def build_batch_request(
        self,
        requests_payload: list[dict[str, Any]],
        model: str,
    ):
        return build_batch_embeddings_request(requests_payload, model)

    def build_single_request(self, payload: dict[str, Any], model: str):
        return build_single_embeddings_request(payload, model)


@dataclass(frozen=True, slots=True)
class GeminiModelsAdapter:
    """Gemini model presenter."""

    def serialize_model(self, model: ModelDescriptor) -> dict[str, object]:
        model_id = normalize_model_name(model["id"])
        if model["kind"] == "embeddings":
            return build_gemini_model(
                model_id,
                supported_generation_methods=["embedContent"],
                input_token_limit=8192,
                output_token_limit=1,
                description=(
                    "Proxy-configured embeddings model exposed through Gemini "
                    "compatibility."
                ),
                thinking=False,
            )
        return build_gemini_model(
            model_id,
            supported_generation_methods=["generateContent", "countTokens"],
            input_token_limit=32768,
            output_token_limit=8192,
            description="GigaChat model exposed through gpt2giga Gemini compatibility.",
            thinking=True,
        )


@dataclass(frozen=True, slots=True)
class GeminiProviderAdapterBundle(ProviderAdapterBundle):
    """Gemini adapter bundle with required capabilities."""

    chat: GeminiChatAdapter = field(default_factory=GeminiChatAdapter)
    responses: None = None
    embeddings: GeminiEmbeddingsAdapter = field(default_factory=GeminiEmbeddingsAdapter)
    models: GeminiModelsAdapter = field(default_factory=GeminiModelsAdapter)
    files: None = None
    batches: None = None


gemini_provider_adapters = GeminiProviderAdapterBundle(
    chat=GeminiChatAdapter(),
    embeddings=GeminiEmbeddingsAdapter(),
    models=GeminiModelsAdapter(),
)


def _load_gemini_router():
    from gpt2giga.api.gemini import router as gemini_router

    return gemini_router


def _load_gemini_upload_router():
    from gpt2giga.api.gemini.files import upload_router as gemini_upload_router

    return gemini_upload_router


GEMINI_PROVIDER_DESCRIPTOR = ProviderDescriptor(
    name="gemini",
    display_name="Gemini",
    capabilities=(
        "generate_content",
        "stream_generate_content",
        "count_tokens",
        "batch_embed_contents",
        "files",
        "batches",
        "models",
    ),
    routes=(
        "/upload/v1beta/files",
        "/v1beta/files",
        "/v1beta/files/{file}",
        "/v1beta/files/{file}:download",
        "/v1beta/batches",
        "/v1beta/batches/{batch}",
        "/v1beta/batches/{batch}:cancel",
        "/v1beta/models/{model}:batchGenerateContent",
        "/v1beta/models",
        "/v1beta/models/{model}",
        "/v1beta/models/{model}:generateContent",
        "/v1beta/models/{model}:streamGenerateContent",
        "/v1beta/models/{model}:countTokens",
        "/v1beta/models/{model}:batchEmbedContents",
    ),
    mounts=(
        ProviderMountSpec(
            router_factory=_load_gemini_router,
            prefix="/v1beta",
            auth_policy="gemini",
        ),
        ProviderMountSpec(
            router_factory=_load_gemini_upload_router,
            prefix="/upload/v1beta",
            auth_policy="gemini",
        ),
    ),
    adapters=gemini_provider_adapters,
)
