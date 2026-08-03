"""Failing-first ownership and admission boundaries for the 0.3 bridge."""

from __future__ import annotations

from dataclasses import fields
import inspect
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
import pytest

from gpt2giga.app.factory import create_app
from gpt2giga.core.context import RequestContext
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.protocols.normalized import (
    BRIDGE_LOSS_MATRIX_V1,
    NormalizedProtocolCapabilities,
)
from gpt2giga.providers.openai_compatible import (
    OpenAICompatibleProviderAdapter,
    OpenAICompatibleUpstreamProfile,
)
from gpt2giga.providers.profiles import (
    LoadedProviderProfileSet,
    ProviderModelAlias,
    ProviderProfile,
    ProviderProfileConfig,
    ProviderRegistry,
    ProviderSupportStatus,
)
from gpt2giga.routers.openai.responses import responses, router as responses_router


ROOT = Path(__file__).parents[2]
CONTRACT_PATH = Path(__file__).with_name("bridge_0_3_ownership.json")
FUTURE = pytest.mark.xfail(strict=True, reason="GPT-P0-04 implementation boundary")


def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _responses_app(stable_sdk_client) -> FastAPI:
    app = FastAPI()
    app.include_router(responses_router)
    config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode="v2"),
        gigachat={"model": "configured-model"},
    )
    stable_sdk_client.configured_model = "configured-model"
    app.state.config = config
    app.state.provider_registry = _explicit_openai_registry()
    app.state.gigachat_client = stable_sdk_client
    app.state.request_transformer = RequestTransformer(config, logger=logger)
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.logger = logger
    return app


def _explicit_openai_registry() -> ProviderRegistry:
    profile = ProviderProfile(
        profile_id="boundary-openai",
        provider_kind="openai_compatible",
        base_url="https://upstream.invalid/v1",
        credential_env="BOUNDARY_OPENAI_KEY",
        network_policy_ref="public-openai",
        tls_policy_ref="system-default",
        models=(
            ProviderModelAlias(
                public_alias="bridge/codex-test",
                upstream_model="fixture-model",
                capability_profile="boundary-openai-v1",
                support_status=ProviderSupportStatus.TECHNICAL_PREVIEW,
            ),
        ),
    )
    loaded = LoadedProviderProfileSet(
        config=ProviderProfileConfig(profiles=(profile,)),
        _credentials={"boundary-openai": "fixture-secret"},
    )
    return ProviderRegistry(
        loaded,
        loss_matrix_revision=BRIDGE_LOSS_MATRIX_V1.revision,
    )


def _openai_compatible_profile(base_url: str) -> OpenAICompatibleUpstreamProfile:
    return OpenAICompatibleUpstreamProfile(
        id="boundary-fixture",
        revision="r1",
        base_url=base_url,
        model="fixture-model",
        capabilities=NormalizedProtocolCapabilities(
            profile="boundary-fixture@r1",
            features=frozenset(),
        ),
        network_policy_ref="public-only",
    )


def test_path_ownership_and_import_boundaries_are_frozen() -> None:
    contract = _contract()
    assert contract["schema_version"] == "gpt2giga.bridge-ownership.v1"
    assert contract["lanes"]["responses-normalized"][-1] == (
        "src/gpt2giga/routers/openai/responses.py"
    )
    assert contract["lanes"]["openai-upstream"] == [
        "src/gpt2giga/providers/openai_compatible/"
    ]

    owned = [path for paths in contract["lanes"].values() for path in paths]
    assert len(owned) == len(set(owned))
    assert not set(owned) & set(contract["integration_exclusive"])

    shipped = ROOT.joinpath("src/gpt2giga").rglob("*.py")
    forbidden = [
        path.relative_to(ROOT).as_posix()
        for path in shipped
        if "gpt2giga_harness" in path.read_text(encoding="utf-8")
    ]
    assert forbidden == []


def test_responses_orchestrates_explicit_execution_owners() -> None:
    source = inspect.getsource(responses)
    assert "NativeGigaChatResponsesExecutor" in source
    assert "NormalizedBridgeResponsesExecutor" in source
    for execution_detail in (
        "prepare_response_chat",
        "prepare_response_chat_completion",
        "stream_responses_generator",
        "stream_responses_chat_completion_generator",
        "giga_client.achat",
    ):
        assert execution_detail not in source


def test_profile_registry_is_the_only_route_resolution_authority() -> None:
    app = create_app(ProxyConfig())
    registry = app.state.provider_registry
    assert registry.schema_version == "gpt2giga.provider-profiles.v1"
    assert registry.immutable is True


def test_unknown_alias_is_rejected_before_provider_io(stable_sdk_client) -> None:
    app = _responses_app(stable_sdk_client)
    response = TestClient(app).post(
        "/responses",
        json={"input": "hello", "model": "missing/alias"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_model_alias"
    assert stable_sdk_client.calls == []


def test_request_cannot_override_profile_transport_or_provider(
    stable_sdk_client,
) -> None:
    app = _responses_app(stable_sdk_client)
    response = TestClient(app).post(
        "/responses",
        json={
            "api_key": "fixture-request-key",
            "base_url": "https://untrusted.invalid/v1",
            "input": "hello",
            "model": "bridge/codex-test",
            "provider": "untrusted",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_semantic"
    assert stable_sdk_client.calls == []


@FUTURE
def test_private_destination_is_rejected_by_profile_admission() -> None:
    with pytest.raises(ValueError, match="private|loopback"):
        _openai_compatible_profile("https://127.0.0.1/v1")


async def test_openai_compatible_adapter_disables_redirects() -> None:
    adapter = OpenAICompatibleProviderAdapter(
        _openai_compatible_profile("https://upstream.invalid/v1"),
        credential=None,
        authorize_network=lambda _intent: None,
    )
    try:
        assert adapter._client.follow_redirects is False
    finally:
        await adapter.aclose()


def test_execution_context_carries_exact_bridge_revisions() -> None:
    names = {field.name for field in fields(RequestContext)}
    assert {
        "capability_profile",
        "config_revision",
        "loss_matrix_revision",
        "profile_id",
        "provider_kind",
        "public_alias",
        "upstream_model",
    } <= names


def test_responses_dispatch_has_no_fallback() -> None:
    source = inspect.getsource(responses)
    assert "except" not in source or "fallback" not in source
    assert _contract()["machine_contract"]["fallback_policy"] == "none"


def test_unsupported_semantic_has_stable_error_before_io(stable_sdk_client) -> None:
    app = _responses_app(stable_sdk_client)
    response = TestClient(app).post(
        "/responses",
        json={
            "input": "hello",
            "model": "bridge/codex-test",
            "web_search_options": {},
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "unsupported_semantic",
        "message": "The selected bridge route cannot preserve this semantic.",
        "param": "web_search_options",
        "type": "invalid_request_error",
    }
    assert stable_sdk_client.calls == []


def test_machine_capability_contract_is_complete_and_content_free() -> None:
    app = create_app(ProxyConfig())
    response = TestClient(app).get("/bridge/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "gpt2giga.route-support-matrix.v1"
    assert body["contract_kind"] == "route_support_matrix"
    assert body["not_model_inventory"] is True
    assert body["not_effective_model_capabilities"] is True
    assert len(body["cells"]) == 16
    assert {cell["status"] for cell in body["cells"]} <= {
        "blocked",
        "stable",
        "technical_preview",
    }
    serialized = json.dumps(body).lower()
    assert "credential" not in serialized
    assert "prompt" not in serialized
