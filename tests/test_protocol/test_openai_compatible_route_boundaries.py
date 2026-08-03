from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
import httpx
import pytest

from gpt2giga.protocols.normalized import (
    BridgeFeature,
    DownstreamProtocol,
    NormalizedChatRequest,
    NormalizedMessage,
    NormalizedTokenLimits,
)
from gpt2giga.providers.openai_compatible import (
    OpenAICompatibleProviderAdapter,
    OpenAICompatibleUpstreamError,
    openai_compatible_profile,
)


class _PeerStream:
    def __init__(self, address: str) -> None:
        self.address = address

    def get_extra_info(self, key: str) -> tuple[str, int] | None:
        return (self.address, 443) if key == "server_addr" else None


class _Authorization:
    def __init__(
        self,
        intent,
        *,
        expected_peer: str | None = None,
    ) -> None:
        self.max_response_bytes = intent.max_response_bytes
        self.peer_validation_required = expected_peer is not None
        self.expected_peer = expected_peer

    def validate_request_body(self, *, body_bytes, body_sha256) -> None:
        assert body_bytes > 0
        assert body_sha256 is not None

    def validate_connected_peer(self, address: str) -> None:
        if address != self.expected_peer:
            raise ValueError("fixture peer mismatch")

    def validate_response_body(self, *, body_bytes) -> None:
        assert body_bytes <= self.max_response_bytes


class _NetworkAuthorizer:
    def __init__(self, *, expected_peer: str | None = None) -> None:
        self.expected_peer = expected_peer
        self.intents = []

    def __call__(self, intent):
        self.intents.append(intent)
        return _Authorization(intent, expected_peer=self.expected_peer)


def _profile(
    *,
    base_url: str = "https://upstream.invalid/v1",
    credential: bool = False,
):
    return openai_compatible_profile(
        profile_id="boundary-openai",
        revision="boundary-r1",
        config_revision=f"sha256:{'5' * 64}",
        public_alias="openai/boundary",
        base_url=base_url,
        model="fixture-model",
        capability_profile="openai-boundary-v1",
        loss_matrix_revision=f"sha256:{'6' * 64}",
        features=frozenset(BridgeFeature),
        limits=NormalizedTokenLimits(
            context_window=8192,
            max_input_tokens=6144,
            max_output_tokens=2048,
        ),
        credential_reference_id="a" * 64 if credential else None,
        network_policy_ref="egress:boundary",
        timeout_seconds=2.0,
    )


def _request() -> NormalizedChatRequest:
    return NormalizedChatRequest(
        model="fixture-model",
        messages=[NormalizedMessage(role="user", content="hello")],
    )


async def _complete(
    adapter: OpenAICompatibleProviderAdapter,
):
    return await adapter.complete(
        _request(),
        downstream=DownstreamProtocol.OPENAI,
        downstream_capabilities=frozenset(BridgeFeature),
        input_token_count=1,
    )


def _chat_response(*, usage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "chatcmpl-boundary",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "fixture-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is not None:
        payload["usage"] = dict(usage)
    return payload


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (None, None),
        (
            {"prompt_tokens": 2},
            {"input_tokens": 2, "output_tokens": None, "total_tokens": None},
        ),
    ],
)
async def test_alternate_base_path_preserves_absent_or_partial_usage(
    usage,
    expected,
):
    app = FastAPI()
    app.state.paths = []

    @app.post("/tenant/acme/openai/v1/chat/completions")
    async def chat(request: Request):
        app.state.paths.append(request.url.path)
        return _chat_response(usage=usage)

    profile = _profile(base_url="https://upstream.invalid/tenant/acme/openai/v1")
    network = _NetworkAuthorizer()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    adapter = OpenAICompatibleProviderAdapter(
        profile,
        credential=None,
        authorize_network=network,
        http_client=client,
    )

    response = await _complete(adapter)
    await client.aclose()

    assert app.state.paths == ["/tenant/acme/openai/v1/chat/completions"]
    assert network.intents[0].url == (
        "https://upstream.invalid/tenant/acme/openai/v1/chat/completions"
    )
    assert (
        response.usage.model_dump(exclude={"raw_extensions", "provider_metadata"})
        if response.usage is not None
        else None
    ) == expected


def test_missing_reviewed_credential_fails_before_network_authorization():
    network = _NetworkAuthorizer()

    with pytest.raises(ValueError, match="credential is unresolved"):
        OpenAICompatibleProviderAdapter(
            _profile(credential=True),
            credential=None,
            authorize_network=network,
        )

    assert network.intents == []


@pytest.mark.parametrize(
    ("status", "code", "error_class"),
    [
        (401, "expired_api_key", "authentication"),
        (404, "model_not_found", "not_found"),
    ],
)
async def test_auth_and_unknown_model_errors_preserve_bounded_provider_facts(
    status,
    code,
    error_class,
):
    async def handler(_request):
        return httpx.Response(
            status,
            json={
                "error": {
                    "message": "bounded fixture failure",
                    "type": "invalid_request_error",
                    "code": code,
                    "param": "model" if status == 404 else None,
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(credential=status == 401),
        credential="expired-canary" if status == 401 else None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    with pytest.raises(OpenAICompatibleUpstreamError) as exc_info:
        await _complete(adapter)
    await client.aclose()

    assert exc_info.value.status_code == status
    assert exc_info.value.error.code == code
    assert exc_info.value.error.error_class == error_class
    assert exc_info.value.error.retryable is False
    assert "expired-canary" not in repr(exc_info.value.error)


async def test_redirect_is_not_followed_to_an_alternate_host():
    calls = []

    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://alternate.invalid/v1/chat/completions"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(),
        credential=None,
        authorize_network=_NetworkAuthorizer(),
        http_client=client,
    )

    with pytest.raises(OpenAICompatibleUpstreamError) as exc_info:
        await _complete(adapter)
    await client.aclose()

    assert calls == ["https://upstream.invalid/v1/chat/completions"]
    assert exc_info.value.error.code == "destination_mismatch"


async def test_connected_peer_mismatch_is_normalized_without_peer_disclosure():
    async def handler(_request):
        return httpx.Response(
            200,
            json=_chat_response(),
            extensions={"network_stream": _PeerStream("203.0.113.20")},
        )

    network = _NetworkAuthorizer(expected_peer="203.0.113.10")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleProviderAdapter(
        _profile(),
        credential=None,
        authorize_network=network,
        http_client=client,
    )

    with pytest.raises(OpenAICompatibleUpstreamError) as exc_info:
        await _complete(adapter)
    await client.aclose()

    error = exc_info.value.error
    assert error.code == "destination_mismatch"
    assert error.retryable is False
    assert "203.0.113" not in error.message
