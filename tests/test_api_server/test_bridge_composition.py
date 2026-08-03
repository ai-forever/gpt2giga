"""Application-owned composition for the 0.3 provider bridge."""

from __future__ import annotations

import json

import pytest

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.providers.profiles import ProviderProfileError


def test_app_owns_one_immutable_synthesized_registry() -> None:
    app = create_app(ProxyConfig())

    registry = app.state.provider_registry
    assert registry.schema_version == "gpt2giga.provider-profiles.v1"
    assert registry.immutable is True
    assert registry.public_aliases() == ("GigaChat",)
    assert app.state.provider_machine_contracts.models_manifest()["models"] == [
        {
            "public_alias": "GigaChat",
            "provider_kind": "gigachat",
            "capability_profile": "legacy-gigachat-v1",
            "support_status": "stable",
            "deprecated": False,
            "profile_revision": registry.resolve("GigaChat").profile_revision,
        }
    ]


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
