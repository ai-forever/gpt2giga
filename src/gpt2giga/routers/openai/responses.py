"""OpenAI Responses endpoint orchestration."""

from fastapi import APIRouter, Request

from gpt2giga.app.responses_execution import (
    NativeGigaChatResponsesExecutor,
    NormalizedBridgeResponsesExecutor,
)
from gpt2giga.common.client_params import (
    ClientCompatibilityError,
    client_compatibility_response,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.openapi_specs.openai import responses_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_OPENAI_RESPONSES
from gpt2giga.protocols.normalized import BridgeMatrixAdmissionError
from gpt2giga.providers.profiles import ProviderAliasError

router = APIRouter(tags=[OPENAPI_TAG_OPENAI_RESPONSES])


@router.post("/responses", openapi_extra=responses_openapi_extra())
@exceptions_handler
async def responses(request: Request):
    """Select and invoke exactly one explicit Responses execution owner."""
    data = await read_request_json(request)
    state = request.app.state
    legacy_responses_enabled = getattr(state, "legacy_responses_enabled", False) is True
    if legacy_responses_enabled:
        return await NativeGigaChatResponsesExecutor().execute(request, data)

    try:
        return await NormalizedBridgeResponsesExecutor().execute(request, data)
    except (BridgeMatrixAdmissionError, ProviderAliasError) as exc:
        if isinstance(exc, BridgeMatrixAdmissionError):
            error = exc.as_public_error()
            compatibility_error = ClientCompatibilityError(
                error["message"],
                param=error["param"],
                code=error["code"],
                error_type=error["type"],
            )
        else:
            compatibility_error = ClientCompatibilityError(
                exc.message,
                param="model",
                code=exc.code,
            )
        return client_compatibility_response(compatibility_error)
    except ClientCompatibilityError as exc:
        return client_compatibility_response(exc)
