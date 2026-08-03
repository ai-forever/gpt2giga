"""Application-owned composition for the 0.3 provider bridge."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.providers.profiles import ProviderProfileError
from gpt2giga.providers.network import ProviderNetworkAuthorizer


class _Response:
    def model_dump(self):
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "composed"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }


class _GigaChat:
    def __init__(self) -> None:
        self.calls = []
        self.closed = False

    async def achat(self, payload):
        self.calls.append(payload)
        return _Response()

    async def aclose(self) -> None:
        self.closed = True


class _ModelCatalog:
    def __init__(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        self.contexts = []

    async def list_models(self, context):
        self.contexts.append(context)
        return self.snapshot


def test_app_owns_one_immutable_synthesized_registry() -> None:
    app = create_app(ProxyConfig())

    registry = app.state.provider_registry
    assert registry.schema_version == "gpt2giga.provider-profiles.v1"
    assert registry.immutable is True
    assert registry.public_aliases() == ("GigaChat",)
    assert registry.resolve("GigaChat").provider_kind.value == "gigachat"


def test_app_loads_explicit_profiles_before_serving(tmp_path, monkeypatch) -> None:
    path = tmp_path / "providers.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "gpt2giga.provider-profiles.v1",
                "profiles": [
                    {
                        "profile_id": "anthropic-main",
                        "provider_kind": "anthropic",
                        "base_url": "https://api.anthropic.com",
                        "credential_env": "ANTHROPIC_API_KEY",
                        "network_policy_ref": "public-anthropic",
                        "tls_policy_ref": "system-default",
                        "models": [
                            {
                                "public_alias": "anthropic/opus",
                                "upstream_model": "claude-reviewed",
                                "capability_profile": "anthropic-opus-v1",
                                "support_status": "technical_preview",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "startup-secret")

    app = create_app(ProxyConfig(config=str(path)))

    assert app.state.provider_registry.public_aliases() == ("anthropic/opus",)
    rendered = repr(app.state.provider_registry.config)
    assert "startup-secret" not in rendered


def test_invalid_explicit_profile_fails_before_app_is_returned(tmp_path) -> None:
    path = tmp_path / "providers.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ProviderProfileError) as raised:
        create_app(ProxyConfig(config=str(path)))

    assert raised.value.code == "invalid_profile_schema"


def test_legacy_responses_cannot_mix_with_explicit_profiles(tmp_path) -> None:
    path = tmp_path / "providers.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Legacy Responses"):
        create_app(
            ProxyConfig(
                config=str(path),
                proxy=ProxySettings(legacy_responses=True),
            )
        )


def test_lifespan_composes_normalized_responses_adapter_once(monkeypatch) -> None:
    giga_client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda _settings: giga_client,
    )
    app = create_app(ProxyConfig())

    with TestClient(app) as client:
        runtime = app.state.bridge_provider_runtime
        first = runtime.adapter_for(
            app.state.openai_protocol_adapter.responses_to_normalized(
                {"input": "hello", "model": "GigaChat"}
            ),
            api_mode="v1",
        )
        second = runtime.adapter_for(
            app.state.openai_protocol_adapter.responses_to_normalized(
                {"input": "again", "model": "GigaChat"}
            ),
            api_mode="v1",
        )
        response = client.post(
            "/responses",
            json={"input": "hello", "model": "GigaChat"},
        )

    assert runtime.adapters_ready is True
    assert first is second
    assert response.status_code == 200
    assert response.json()["output"][0]["content"][0]["text"] == "composed"
    assert len(giga_client.calls) == 1
    assert giga_client.closed is True


def test_runtime_owns_one_network_authorizer_per_loaded_profile(monkeypatch) -> None:
    giga_client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda _settings: giga_client,
    )
    app = create_app(ProxyConfig())

    with TestClient(app):
        runtime = app.state.bridge_provider_runtime
        authorizers = runtime._network_authorizers

    assert tuple(authorizers) == ("legacy-gigachat",)
    assert isinstance(authorizers["legacy-gigachat"], ProviderNetworkAuthorizer)


def test_runtime_rejects_unknown_alias_before_provider_io(monkeypatch) -> None:
    giga_client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda _settings: giga_client,
    )
    app = create_app(ProxyConfig())

    with TestClient(app) as client:
        response = client.post(
            "/responses",
            json={"input": "hello", "model": "missing/alias"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_model_alias"
    assert giga_client.calls == []


def test_machine_endpoints_are_deterministic_and_do_not_call_provider(
    monkeypatch,
) -> None:
    giga_client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda _settings: giga_client,
    )
    app = create_app(ProxyConfig())
    inventory_revision = f"sha256:{'d' * 64}"
    app.state.model_discovery_context = object()
    app.state.model_catalog = _ModelCatalog(
        {
            "schema_version": "gpt2giga.model-catalog.v1",
            "provider_profile_id": "legacy-gigachat",
            "credential_scope_digest": f"sha256:{'e' * 64}",
            "inventory_revision": inventory_revision,
            "discovered_at": "2026-08-03T08:00:00Z",
            "expires_at": "2026-08-03T08:01:00Z",
            "stale": False,
            "source": "provider",
            "models": [
                {
                    "id": "GigaChat-3-Pro",
                    "provider_kind": "gigachat",
                    "provider_profile_id": "legacy-gigachat",
                    "owned_by": "gigachat",
                    "model_type": "chat",
                    "available": True,
                    "deprecated": False,
                    "stale": False,
                    "inventory_revision": inventory_revision,
                }
            ],
        }
    )

    with TestClient(app) as client:
        readiness = client.get("/ready")
        models = client.get("/bridge/models")
        capabilities = client.get("/bridge/capabilities")

    assert readiness.status_code == 200
    assert readiness.json()["ready"] is True
    assert readiness.json()["config_revision"] == models.json()["config_revision"]
    assert models.json()["models"][0]["id"] == "GigaChat-3-Pro"
    assert models.json()["source"] == "shared_model_catalog"
    assert len(capabilities.json()["cells"]) == 16
    assert capabilities.json()["matrix_revision"] == models.json()["matrix_revision"]
    serialized = json.dumps(
        {
            "readiness": readiness.json(),
            "models": models.json(),
            "capabilities": capabilities.json(),
        }
    ).lower()
    assert "credential" not in serialized
    assert "prompt" not in serialized
    assert giga_client.calls == []


def test_bridge_models_does_not_fall_back_to_static_profile_aliases() -> None:
    app = create_app(ProxyConfig())

    response = TestClient(app).get("/bridge/models")

    assert response.status_code == 503
    assert response.json()["detail"] == {"reason_id": "model_catalog_unavailable"}


def test_readiness_is_unavailable_before_lifespan_start() -> None:
    app = create_app(ProxyConfig())

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["ready"] is False
    assert response.json()["reasons"] == [{"reason_id": "provider_clients_not_ready"}]
