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
from gpt2giga.providers.contracts import ProviderAdapterBundle
from gpt2giga.providers.descriptors import ProviderDescriptor, ProviderMountSpec


@dataclass(frozen=True, slots=True)
class OpenAIChatAdapter:
    """OpenAI chat request adapter."""

    def build_normalized_request(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ):
        return build_normalized_chat_request(payload, logger=logger)


@dataclass(frozen=True, slots=True)
class OpenAIResponsesAdapter:
    """OpenAI Responses request adapter."""

    def build_normalized_request(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ):
        return build_normalized_responses_request(payload, logger=logger)


@dataclass(frozen=True, slots=True)
class OpenAIEmbeddingsAdapter:
    """OpenAI embeddings request adapter."""

    def build_normalized_request(self, payload: dict[str, Any]):
        return build_normalized_embeddings_request(payload)


@dataclass(frozen=True, slots=True)
class OpenAIModelsAdapter:
    """OpenAI model presenter."""

    def serialize_model(self, model: ModelDescriptor) -> OpenAIModel:
        return OpenAIModel(
            id=model["id"],
            object=model["object"],
            owned_by=model["owned_by"],
            created=int(time.time()),
        )


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
class OpenAIBatchesAdapter:
    """OpenAI batches adapter."""

    def build_create_payload(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> dict[str, Any]:
        return dict(payload)


openai_provider_adapters = ProviderAdapterBundle(
    chat=OpenAIChatAdapter(),
    responses=OpenAIResponsesAdapter(),
    embeddings=OpenAIEmbeddingsAdapter(),
    models=OpenAIModelsAdapter(),
    files=OpenAIFilesAdapter(),
    batches=OpenAIBatchesAdapter(),
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
            tags=("V1",),
        ),
        ProviderMountSpec(
            router_factory=_load_litellm_router,
            prefix="/v1",
            tags=("V1 LiteLLM",),
        ),
        ProviderMountSpec(router_factory=_load_litellm_router),
    ),
    adapters=openai_provider_adapters,
)
