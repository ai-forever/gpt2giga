"""Exact alias-resolution contracts for provider profiles."""

from __future__ import annotations

import json

import pytest

from gpt2giga.providers.profiles import (
    BRIDGE_MODELS_SCHEMA_VERSION,
    EXECUTION_CONTEXT_SCHEMA_VERSION,
    LoadedProviderProfileSet,
    ProviderAliasError,
    ProviderProfileConfig,
    ProviderProfileError,
    ProviderRegistry,
)


MATRIX_REVISION = f"sha256:{'a' * 64}"
SECRET = "registry-secret-never-render"


def _registry() -> ProviderRegistry:
    config = ProviderProfileConfig.model_validate(
        {
            "profiles": [
                {
                    "profile_id": "gemini-main",
                    "provider_kind": "gemini",
                    "base_url": "https://generativelanguage.googleapis.com/v1beta",
                    "credential_env": "GEMINI_API_KEY",
                    "network_policy_ref": "public-gemini",
                    "tls_policy_ref": "system-default",
                    "models": [
                        {
                            "public_alias": "zeta/current",
                            "upstream_model": "models/gemini-current",
                            "capability_profile": "gemini-current-v1",
                            "support_status": "technical_preview",
                        },
                        {
                            "public_alias": "alpha/deprecated",
                            "upstream_model": "models/gemini-old",
                            "capability_profile": "gemini-old-v1",
                            "support_status": "blocked",
                            "deprecated": True,
                        },
                        {
                            "public_alias": "hidden/disabled",
                            "upstream_model": "models/gemini-disabled",
                            "capability_profile": "gemini-disabled-v1",
                            "support_status": "blocked",
                            "enabled": False,
                        },
                    ],
                }
            ]
        }
    )
    return ProviderRegistry(
        LoadedProviderProfileSet(
            config=config,
            _credentials={"gemini-main": SECRET},
        ),
        loss_matrix_revision=MATRIX_REVISION,
    )


def test_alias_resolves_to_exact_provider_model_and_revisions() -> None:
    registry = _registry()
    route = registry.resolve("zeta/current")

    assert route.profile_id == "gemini-main"
    assert route.provider_kind.value == "gemini"
    assert route.upstream_model == "models/gemini-current"
    assert route.capability_profile == "gemini-current-v1"
    assert route.loss_matrix_revision == MATRIX_REVISION
    assert route.config_revision == registry.config_revision
    assert route.profile_revision.startswith("sha256:")
    assert registry.credential_for(route) == SECRET
    assert route.execution_context() == {
        "schema_version": EXECUTION_CONTEXT_SCHEMA_VERSION,
        "config_revision": registry.config_revision,
        "profile_revision": route.profile_revision,
        "profile_id": "gemini-main",
        "public_alias": "zeta/current",
        "provider_kind": "gemini",
        "upstream_model": "models/gemini-current",
        "capability_profile": "gemini-current-v1",
        "loss_matrix_revision": MATRIX_REVISION,
    }
    assert registry.resolve("zeta/current") is route


@pytest.mark.parametrize(
    ("alias", "reason_id"),
    [
        ("missing/alias", "alias_unknown"),
        ("ZETA/CURRENT", "alias_unknown"),
        ("zeta/current ", "alias_unknown"),
        ("hidden/disabled", "alias_disabled"),
    ],
)
def test_unknown_case_changed_whitespace_and_disabled_aliases_never_fallback(
    alias: str,
    reason_id: str,
) -> None:
    registry = _registry()
    with pytest.raises(ProviderAliasError) as raised:
        registry.resolve(alias)
    assert raised.value.code == "unknown_model_alias"
    assert raised.value.reason_id == reason_id
    assert alias not in str(raised.value)


def test_deprecated_alias_resolves_only_to_its_own_exact_model() -> None:
    route = _registry().resolve("alpha/deprecated")
    assert route.deprecated is True
    assert route.upstream_model == "models/gemini-old"
    assert route.public_alias == "alpha/deprecated"


def test_model_manifest_is_lexical_deterministic_and_content_free() -> None:
    registry = _registry()
    first = registry.models_manifest()
    second = registry.models_manifest()

    assert first == second
    assert first["schema_version"] == BRIDGE_MODELS_SCHEMA_VERSION
    assert first["config_revision"] == registry.config_revision
    assert first["matrix_revision"] == MATRIX_REVISION
    assert [model["public_alias"] for model in first["models"]] == [
        "alpha/deprecated",
        "zeta/current",
    ]
    serialized = json.dumps(first).lower()
    assert SECRET.lower() not in serialized
    assert "credential" not in serialized
    assert "base_url" not in serialized
    assert "upstream_model" not in serialized
    assert "hidden/disabled" not in serialized

    first["models"][0]["public_alias"] = "tampered"
    assert registry.models_manifest() == second


def test_registry_rejects_noncanonical_matrix_revision() -> None:
    registry = _registry()
    with pytest.raises(ProviderProfileError) as raised:
        ProviderRegistry(registry._loaded, loss_matrix_revision="matrix-latest")
    assert raised.value.code == "invalid_profile_schema"
