import json

import pytest
from fastapi import HTTPException

from gpt2giga.common.client_params import (
    CLIENT_PARAM_STATUSES,
    GIGACHAT_CONTEXT_HEADER_NAMES,
    SAFE_GIGACHAT_QUERY_PARAM_NAMES,
    ClientCompatibilityError,
    ClientParamStatus,
    anthropic_compatibility_response,
    extract_gigachat_response_metadata,
    filter_safe_diagnostic_headers,
    filter_safe_extra_headers,
    filter_safe_query_items,
    is_blocked_client_header,
    is_safe_extra_header,
    is_safe_diagnostic_header,
    merge_openai_response_metadata,
    openai_compatibility_error,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.logger import rquid_context


def test_client_param_status_values_are_stable():
    assert CLIENT_PARAM_STATUSES == {
        "supported",
        "accepted_ignored",
        "rejected",
        "not_applicable",
    }
    assert ClientParamStatus.SUPPORTED.value == "supported"


def test_gigachat_context_header_names_are_stable():
    assert GIGACHAT_CONTEXT_HEADER_NAMES == {
        "authorization",
        "x-agent-id",
        "x-client-id",
        "x-operation-id",
        "x-request-id",
        "x-service-id",
        "x-session-id",
        "x-trace-id",
    }


def test_header_policy_blocks_secrets_transport_and_sdk_headers():
    assert is_blocked_client_header("Authorization") is True
    assert is_blocked_client_header("Cookie") is True
    assert is_blocked_client_header("X-Stainless-Lang") is True
    assert is_blocked_client_header("Anthropic-Beta") is True
    assert is_blocked_client_header("OpenAI-Organization") is True
    assert is_blocked_client_header("X-Request-ID") is False


def test_filter_safe_diagnostic_headers_allows_only_allowlisted_scalars():
    assert filter_safe_diagnostic_headers(
        {
            "X-Request-ID": "rq-1",
            "X-Correlation-ID": 123,
            "TraceParent": "00-trace",
            "Authorization": "Bearer secret",
            "X-Foo": "bar",
            "X-Trace-ID": None,
        }
    ) == {
        "x-request-id": "rq-1",
        "x-correlation-id": "123",
        "traceparent": "00-trace",
    }


def test_filter_safe_extra_headers_allows_gigachat_context_and_custom_headers():
    assert filter_safe_extra_headers(
        {
            "X-Request-ID": "rq-1",
            "X-Session-ID": 123,
            "X-Service-ID": "svc",
            "X-Custom-Flag": True,
            "TraceParent": "00-trace",
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
            "X-Stainless-Lang": "python",
            "OpenAI-Organization": "org_test",
            "X-None": None,
        }
    ) == {
        "x-request-id": "rq-1",
        "x-session-id": "123",
        "x-service-id": "svc",
        "x-custom-flag": "True",
        "traceparent": "00-trace",
    }


def test_extract_gigachat_response_metadata_allows_only_trace_ids():
    assert extract_gigachat_response_metadata(
        {
            "X-Request-ID": "rq-1",
            "x-session-id": 123,
            "Authorization": "Bearer secret",
            "X-Trace-ID": "trace-1",
            "X-Response-Debug": {"not": "scalar"},
        }
    ) == {
        "gigachat_x_request_id": "rq-1",
        "gigachat_x_session_id": "123",
    }


def test_merge_openai_response_metadata_preserves_user_metadata():
    assert merge_openai_response_metadata(
        {"user_id": "user-1"},
        {"gigachat_x_request_id": "rq-1"},
    ) == {
        "user_id": "user-1",
        "gigachat_x_request_id": "rq-1",
    }


def test_safe_query_policy_defaults_to_empty_allowlist():
    assert SAFE_GIGACHAT_QUERY_PARAM_NAMES == frozenset()
    assert filter_safe_query_items([("feature", "on"), ("debug", True)]) == ()
    assert filter_safe_query_items(
        [("feature", "on"), ("enabled", True), ("skip", None)],
        allowlist=frozenset({"enabled"}),
    ) == (("enabled", "true"),)


def test_safe_diagnostic_header_rejects_blocked_names():
    assert is_safe_diagnostic_header("X-Request-ID") is True
    assert is_safe_diagnostic_header("Authorization") is False
    assert is_safe_diagnostic_header("OpenAI-Request-ID") is False


def test_safe_extra_header_rejects_only_blocked_names():
    assert is_safe_extra_header("X-Session-ID") is True
    assert is_safe_extra_header("X-Custom-Flag") is True
    assert is_safe_extra_header("Authorization") is False
    assert is_safe_extra_header("OpenAI-Request-ID") is False


def test_openai_compatibility_error_shape():
    exc = openai_compatibility_error(
        "Unsupported parameter: n.",
        param="n",
        code="unsupported_parameter",
    )

    assert isinstance(exc, HTTPException)
    assert exc.status_code == 400
    assert exc.detail == {
        "error": {
            "message": "Unsupported parameter: n.",
            "type": "invalid_request_error",
            "param": "n",
            "code": "unsupported_parameter",
        }
    }


def test_anthropic_compatibility_response_shape():
    token = rquid_context.set("rq-test")
    try:
        response = anthropic_compatibility_response(
            "Unsupported parameter: container.",
            error_type="invalid_request_error",
        )
    finally:
        rquid_context.reset(token)

    assert response.status_code == 400
    assert json.loads(response.body) == {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "Unsupported parameter: container.",
        },
        "request_id": "rq-test",
    }


def test_client_compatibility_error_rejects_unknown_provider():
    with pytest.raises(ValueError, match="provider"):
        raise ClientCompatibilityError("bad provider", provider="gemini")


async def test_exceptions_handler_renders_openai_client_compatibility_error():
    @exceptions_handler
    async def boom():
        raise ClientCompatibilityError("Unsupported parameter: n.", param="n")

    with pytest.raises(HTTPException) as exc_info:
        await boom()

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["param"] == "n"


async def test_exceptions_handler_renders_anthropic_client_compatibility_error():
    token = rquid_context.set("rq-anthropic")

    @exceptions_handler
    async def boom():
        raise ClientCompatibilityError(
            "Unsupported parameter: container.",
            provider="anthropic",
        )

    try:
        response = await boom()
    finally:
        rquid_context.reset(token)

    assert response.status_code == 400
    assert json.loads(response.body) == {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "Unsupported parameter: container.",
        },
        "request_id": "rq-anthropic",
    }
