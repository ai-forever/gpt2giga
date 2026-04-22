"""Standalone batch validation endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from gpt2giga.api.batch_validation import validate_batch_input_request
from gpt2giga.api.tags import TAG_BATCHES
from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.features.batches import BatchValidationReport

router = APIRouter(tags=[TAG_BATCHES])


class BatchValidateRequest(BaseModel):
    """Multi-provider batch validation request payload."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "api_format": "openai",
                    "input_file_id": "file-batch-123",
                },
                {
                    "api_format": "anthropic",
                    "requests": [
                        {
                            "custom_id": "req-1",
                            "params": {
                                "model": "claude-test",
                                "max_tokens": 64,
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": "Hello from validation.",
                                    }
                                ],
                            },
                        }
                    ],
                },
                {
                    "api_format": "gemini",
                    "model": "models/gemini-2.5-flash",
                    "requests": [
                        {
                            "key": "req-1",
                            "request": {
                                "contents": [
                                    {
                                        "role": "user",
                                        "parts": [{"text": "Hello from validation."}],
                                    }
                                ]
                            },
                            "metadata": {"label": "row-1"},
                        }
                    ],
                },
            ]
        },
    )

    api_format: NormalizedArtifactFormat = NormalizedArtifactFormat.OPENAI
    input_file_id: str | None = None
    model: str | None = None
    requests: list[dict[str, Any]] | None = None


@router.post("/batches/validate", response_model=BatchValidationReport)
@exceptions_handler
async def validate_batch_input(
    payload: BatchValidateRequest,
    request: Request,
):
    """Validate provider-specific batch input without creating a batch job.

    Accepts OpenAI, Anthropic, or Gemini batch payloads via `api_format` and
    inspects either a staged file (`input_file_id`) or inline `requests`.
    Returns normalized diagnostics with detected format, row counts, and
    blocking issues or warnings. The endpoint does not enqueue or persist a
    batch run.
    """
    return await validate_batch_input_request(
        request=request,
        api_format=payload.api_format,
        input_file_id=payload.input_file_id,
        input_bytes=None,
        fallback_model=payload.model,
        requests=payload.requests,
    )
