"""OpenAI-compatible provider capability adapters."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from openai.types import Model as OpenAIModel

from gpt2giga.api.openai.request_adapter import (
    build_normalized_chat_request,
    build_normalized_embeddings_request,
    build_normalized_responses_request,
)
from gpt2giga.features.models.contracts import ModelDescriptor
from gpt2giga.providers._shared_adapters import (
    DelegatingBatchesAdapter,
    DelegatingChatAdapter,
    DelegatingEmbeddingsAdapter,
    DelegatingModelsAdapter,
    DelegatingResponsesAdapter,
)
from gpt2giga.providers.contracts import ProviderAdapterBundle
from gpt2giga.providers.descriptors import ProviderDescriptor, ProviderMountSpec


def _serialize_openai_model(model: ModelDescriptor) -> OpenAIModel:
    """Build an OpenAI-compatible model payload."""
    return OpenAIModel(
        id=model["id"],
        object="model",
        owned_by=model["owned_by"],
        created=int(time.time()),
    )


def _clone_batch_payload(
    payload: dict[str, Any],
    *,
    logger: Any = None,
) -> dict[str, Any]:
    """Return a shallow copy of an OpenAI batch payload."""
    del logger
    return dict(payload)


@dataclass(frozen=True, slots=True)
class OpenAIFilesAdapter:
    """OpenAI file upload adapter."""

    def extract_create_file_args(self, multipart: dict[str, Any]) -> tuple[str, Any]:
        form = multipart.get("form") or {}
        files = multipart.get("files") or {}
        purpose = form.get("purpose")
        upload = files.get("file")
        if not purpose or upload is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": (
                            "Multipart upload requires both `file` and `purpose`."
                        ),
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "invalid_multipart",
                    }
                },
            )
        return str(purpose), upload


@dataclass(frozen=True, slots=True)
class OpenAIProviderAdapterBundle(ProviderAdapterBundle):
    """OpenAI adapter bundle with non-optional capability types."""

    chat: DelegatingChatAdapter
    responses: DelegatingResponsesAdapter
    embeddings: DelegatingEmbeddingsAdapter
    models: DelegatingModelsAdapter
    files: OpenAIFilesAdapter
    batches: DelegatingBatchesAdapter


openai_provider_adapters = OpenAIProviderAdapterBundle(
    chat=DelegatingChatAdapter(build_normalized_chat_request),
    responses=DelegatingResponsesAdapter(build_normalized_responses_request),
    embeddings=DelegatingEmbeddingsAdapter(build_normalized_embeddings_request),
    models=DelegatingModelsAdapter(_serialize_openai_model),
    files=OpenAIFilesAdapter(),
    batches=DelegatingBatchesAdapter(_clone_batch_payload),
)


def _load_openai_router():
    from gpt2giga.api.openai import router as openai_router

    return openai_router


def _load_litellm_router():
    from gpt2giga.api.litellm import router as litellm_router

    return litellm_router


OPENAI_PROVIDER_DESCRIPTOR = ProviderDescriptor(
    name="openai",
    display_name="OpenAI",
    capabilities=(
        "models",
        "chat_completions",
        "responses",
        "embeddings",
        "files",
        "batches",
        "litellm_model_info",
    ),
    routes=(
        "/models",
        "/chat/completions",
        "/responses",
        "/embeddings",
        "/files",
        "/batches",
        "/model/info",
        "/v1/models",
        "/v1/chat/completions",
        "/v1/responses",
        "/v1/embeddings",
        "/v1/files",
        "/v1/batches",
        "/v1/model/info",
    ),
    mounts=(
        ProviderMountSpec(router_factory=_load_openai_router),
        ProviderMountSpec(
            router_factory=_load_openai_router,
            prefix="/v1",
        ),
        ProviderMountSpec(
            router_factory=_load_litellm_router,
            prefix="/v1",
        ),
        ProviderMountSpec(router_factory=_load_litellm_router),
    ),
    adapters=openai_provider_adapters,
)
