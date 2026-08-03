"""Unit contracts for versioned provider-profile configuration."""

from __future__ import annotations

import json

from pydantic import ValidationError
import pytest

from gpt2giga.providers.profiles import (
    PROVIDER_KINDS,
    PROVIDER_PROFILE_SCHEMA_V1,
    PROVIDER_PROFILE_SCHEMA_V2,
    PROVIDER_PROFILE_SCHEMA_VERSION,
    ProviderModelInventory,
    ProviderModelAlias,
    ProviderProfile,
    ProviderProfileConfig,
)


def _config(**overrides: object) -> ProviderProfileConfig:
    payload: dict[str, object] = {
        "schema_version": PROVIDER_PROFILE_SCHEMA_VERSION,
        "profiles": [
            {
                "profile_id": "anthropic-main",
                "provider_kind": "anthropic",
                "base_url": "https://API.Anthropic.com:443/v1/",
                "credential_env": "ANTHROPIC_API_KEY",
                "network_policy_ref": "public-anthropic",
                "tls_policy_ref": "system-default",
                "models": [
                    {
                        "public_alias": "anthropic/opus",
                        "upstream_model": "claude-opus-exact",
                        "capability_profile": "anthropic-opus-v1",
                        "support_status": "technical_preview",
                    }
                ],
            }
        ],
    }
    payload.update(overrides)
    return ProviderProfileConfig.model_validate(payload)


def test_profile_config_is_strict_immutable_and_secret_free() -> None:
    config = _config()

    assert PROVIDER_KINDS == {
        "anthropic",
        "gemini",
        "gigachat",
        "openai_compatible",
    }
    assert config.profiles[0].base_url == "https://api.anthropic.com/v1"
    assert config.profiles[0].models[0].public_alias == "anthropic/opus"
    assert config.revision.startswith("sha256:")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _config(api_key="plaintext-secret")
    with pytest.raises(ValidationError, match="Instance is frozen"):
        config.profiles[0].profile_id = "changed"  # type: ignore[misc]


def test_only_gigachat_profile_may_defer_models_to_dynamic_inventory() -> None:
    dynamic = _config().profiles[0].model_dump(mode="json")
    dynamic.update(
        {
            "provider_kind": "gigachat",
            "model_inventory": "dynamic",
            "models": [],
        }
    )

    profile = ProviderProfile.model_validate(dynamic)
    assert profile.model_inventory is ProviderModelInventory.DYNAMIC
    assert profile.models == ()

    with pytest.raises(ValidationError, match="dynamic model inventory"):
        ProviderProfile.model_validate({**dynamic, "provider_kind": "anthropic"})


def test_v1_stays_static_while_v2_admits_explicit_dynamic_inventory() -> None:
    v1_payload = _config().model_dump(mode="json", exclude_none=True)
    v1_payload["schema_version"] = PROVIDER_PROFILE_SCHEMA_V1
    v1 = ProviderProfileConfig.model_validate(v1_payload)

    assert v1.schema_version == PROVIDER_PROFILE_SCHEMA_V1
    assert "model_inventory" not in json.loads(v1.canonical_json())["profiles"][0]

    v1_payload["profiles"][0].update(
        {
            "provider_kind": "gigachat",
            "model_inventory": "dynamic",
            "models": [],
        }
    )
    with pytest.raises(ValidationError, match="provider-profiles.v2"):
        ProviderProfileConfig.model_validate(v1_payload)

    v2_payload = {
        **v1_payload,
        "schema_version": PROVIDER_PROFILE_SCHEMA_V2,
    }
    v2 = ProviderProfileConfig.model_validate(v2_payload)
    assert v2.schema_version == PROVIDER_PROFILE_SCHEMA_V2
    assert v2.profiles[0].model_inventory is ProviderModelInventory.DYNAMIC
    assert v2.profiles[0].models == ()


def test_only_one_dynamic_gigachat_inventory_is_unambiguous() -> None:
    dynamic = ProviderProfile(
        profile_id="gigachat-one",
        provider_kind="gigachat",
        base_url="https://example.com/v1",
        credential_env="GIGACHAT_CREDENTIALS",
        network_policy_ref="public-gigachat",
        tls_policy_ref="system-default",
        model_inventory="dynamic",
    )
    second = dynamic.model_copy(update={"profile_id": "gigachat-two"})

    with pytest.raises(ValidationError, match="multiple dynamic model inventories"):
        ProviderProfileConfig(profiles=(dynamic, second))


def test_canonical_digest_is_key_order_independent_and_array_order_sensitive() -> None:
    first = _config()
    reordered_input = {
        "profiles": [
            {
                "models": [
                    {
                        "support_status": "technical_preview",
                        "capability_profile": "anthropic-opus-v1",
                        "upstream_model": "claude-opus-exact",
                        "public_alias": "anthropic/opus",
                    }
                ],
                "tls_policy_ref": "system-default",
                "network_policy_ref": "public-anthropic",
                "credential_env": "ANTHROPIC_API_KEY",
                "base_url": "https://api.anthropic.com/v1",
                "provider_kind": "anthropic",
                "profile_id": "anthropic-main",
            }
        ],
        "schema_version": PROVIDER_PROFILE_SCHEMA_VERSION,
    }
    second = ProviderProfileConfig.model_validate(reordered_input)

    assert first.canonical_json() == second.canonical_json()
    assert first.revision == second.revision
    assert json.loads(first.canonical_json())["schema_version"] == (
        PROVIDER_PROFILE_SCHEMA_VERSION
    )

    extra_model = (
        first.profiles[0]
        .models[0]
        .model_copy(update={"public_alias": "anthropic/sonnet"})
    )
    reversed_models = first.profiles[0].model_copy(
        update={"models": (extra_model, first.profiles[0].models[0])}
    )
    changed = first.model_copy(update={"profiles": (reversed_models,)})
    assert first.revision != changed.revision


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "future"),
        ("credential_env", "secret-value"),
        ("base_url", "https://user:secret@example.com/v1"),
        ("base_url", "file:///tmp/provider"),
        ("base_url", "https://example.com/v1?api_key=secret"),
    ],
)
def test_invalid_schema_authority_and_credential_shapes_are_rejected(
    field: str,
    value: str,
) -> None:
    payload = _config().model_dump(mode="json")
    if field == "schema_version":
        payload[field] = value
    else:
        payload["profiles"][0][field] = value

    with pytest.raises(ValidationError):
        ProviderProfileConfig.model_validate(payload)


def test_aliases_are_normalized_before_global_uniqueness_validation() -> None:
    model = ProviderModelAlias(
        public_alias="provider/caf\N{LATIN SMALL LETTER E WITH ACUTE}",
        upstream_model="exact-a",
        capability_profile="cap-a",
        support_status="stable",
    )
    equivalent = ProviderModelAlias.model_validate(
        {
            **model.model_dump(mode="json"),
            "public_alias": "provider/cafe\N{COMBINING ACUTE ACCENT}",
        }
    )
    first = ProviderProfile(
        profile_id="first",
        provider_kind="gigachat",
        base_url="https://example.com",
        credential_env="GIGACHAT_CREDENTIALS",
        network_policy_ref="public-gigachat",
        tls_policy_ref="system-default",
        models=(model,),
    )
    second = first.model_copy(update={"profile_id": "second", "models": (equivalent,)})

    with pytest.raises(ValidationError, match="duplicate model aliases"):
        ProviderProfileConfig(profiles=(first, second))
