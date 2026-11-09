"""OpenAI image generation backed by the native GigaChat v2 image tool."""

import base64
import time

from fastapi import APIRouter, Request

from gpt2giga.app.providers import bind_model_request
from gpt2giga.app_state import get_request_transformer
from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.api_mode import resolve_gigachat_api_mode
from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.request_json import read_request_json
from gpt2giga.openapi_specs.openai import images_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_OPENAI_IMAGES
from gpt2giga.protocol.response.processor import ResponseProcessor
from gpt2giga.protocol.response.gigachat_chat_completion_adapter import (
    extract_chat_completion_message_metadata,
)
from gpt2giga.providers.gigachat.native import native_operation_model

router = APIRouter(tags=[OPENAPI_TAG_OPENAI_IMAGES])


@router.post("/images/generations", openapi_extra=images_openapi_extra())
@exceptions_handler
async def generate_image(request: Request):
    """Generate one image and return its real bytes as base64."""
    data = await read_request_json(request)
    options = extract_gigachat_request_options(request, data)
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ClientCompatibilityError(
            "prompt must be a nonempty string.", param="prompt"
        )
    if resolve_gigachat_api_mode(request) != "v2":
        raise ClientCompatibilityError(
            "Image generation requires the GigaChat v2 route.",
            code="unsupported_api_mode",
        )
    allowed = {"prompt", "model", "n", "response_format", "size", "user"}
    unsupported = next((key for key in data if key not in allowed), None)
    if unsupported:
        raise ClientCompatibilityError(
            "Unsupported image parameter.", param=unsupported
        )
    if "n" in data and type(data["n"]) is not int:
        raise ClientCompatibilityError("n must be the integer 1.", param="n")
    for key, supported in (("n", 1), ("response_format", "b64_json"), ("size", "auto")):
        if data.get(key, supported) != supported:
            raise ClientCompatibilityError(
                f"Only {key}={supported!r} is supported.", param=key
            )
    model = native_operation_model(request, data.get("model"), image=True)
    registry = getattr(request.app.state, "provider_registry", None)
    requested_alias = data.get("model")
    await bind_model_request(
        request,
        requested_alias
        if registry is not None and requested_alias in registry.public_aliases()
        else model,
        None,
    )
    client = get_gigachat_client(request)
    async with get_model_concurrency_limiter(request).limit(model, provider="openai"):
        async with gigachat_request_options(
            client, options, include_body=False
        ) as scoped:
            payload = await get_request_transformer(request).prepare_chat_completion(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": [{"type": "image_generation"}],
                    "tool_choice": "required",
                },
                scoped,
                forced_model=model,
            )
            result = await scoped.with_options(max_retries=0).achat.create(payload)
            metadata = extract_chat_completion_message_metadata(result)
            images = [
                file
                for file in ResponseProcessor._extract_files(metadata)
                if ResponseProcessor._is_image_file(file) and file.get("id")
            ]
            if not images:
                raise ClientCompatibilityError(
                    "The upstream response did not contain an image.",
                    status_code=502,
                    error_type="api_error",
                    code="invalid_upstream_response",
                )
            content = await scoped.aget_file_content(file_id=images[0]["id"])
            if not content:
                raise ClientCompatibilityError(
                    "The upstream image file was empty.",
                    status_code=502,
                    error_type="api_error",
                    code="invalid_upstream_response",
                )
    return {
        "created": int(time.time()),
        "data": [{"b64_json": base64.b64encode(content).decode("ascii")}],
    }
