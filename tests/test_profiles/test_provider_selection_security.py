"""Security regressions for immutable provider and alias selection."""

from __future__ import annotations

from dataclasses import replace

from pydantic import ValidationError
import pytest

from gpt2giga.providers.profiles import (
    LoadedProviderProfileSet,
    ProviderAliasError,
    ProviderProfile,
    ProviderProfileConfig,
    ProviderProfileError,
    ProviderRegistry,
)


MATRIX_REVISION = f"sha256:{'c' * 64}"
SECRET = "selection-secret-never-render"


def _profile(
    *,
    profile_id: str = "provider-main",
    public_alias: str = "provider/current",
    upstream_model: str = "exact-model-v1",
) -> ProviderProfile:
    return ProviderProfile.model_validate(
        {
            "profile_id": profile_id,
            "provider_kind": "openai_compatible",
            "base_url": "https://provider.example.com/v1",
            "credential_env": "PROVIDER_API_KEY",
            "network_policy_ref": "public-provider",
            "tls_policy_ref": "system-default",
            "models": [
                {
                    "public_alias": public_alias,
                    "upstream_model": upstream_model,
                    "capability_profile": "provider-v1",
                    "support_status": "technical_preview",
                }
            ],
        }
    )


def _registry(
    *,
    profile: ProviderProfile | None = None,
    secret: str = SECRET,
) -> ProviderRegistry:
    selected = profile or _profile()
    loaded = LoadedProviderProfileSet(
        config=ProviderProfileConfig(profiles=(selected,)),
        _credentials={selected.profile_id: secret},
    )
    return ProviderRegistry(loaded, loss_matrix_revision=MATRIX_REVISION)


@pytest.mark.parametrize(
    ("field", "replacement", "reason_id"),
    [
        ("config_revision", f"sha256:{'d' * 64}", "route_revision_mismatch"),
        ("profile_revision", f"sha256:{'e' * 64}", "route_revision_mismatch"),
        ("profile_id", "provider-other", "route_revision_mismatch"),
        ("public_alias", "provider/other", "alias_unknown"),
        ("provider_kind", "anthropic", "route_revision_mismatch"),
        ("upstream_model", "exact-model-v2", "route_revision_mismatch"),
        ("capability_profile", "provider-v2", "route_revision_mismatch"),
        ("loss_matrix_revision", f"sha256:{'f' * 64}", "route_revision_mismatch"),
    ],
)
def test_stale_or_changed_route_never_reveals_a_credential(
    field: str,
    replacement: object,
    reason_id: str,
) -> None:
    registry = _registry()
    route = registry.resolve("provider/current")
    changed = replace(route, **{field: replacement})

    with pytest.raises(ProviderAliasError) as raised:
        registry.credential_for(changed)

    assert raised.value.code == "unknown_model_alias"
    assert raised.value.reason_id == reason_id
    assert SECRET not in str(raised.value)
    assert str(replacement) not in str(raised.value)


def test_loaded_credentials_and_registry_are_process_lifetime_snapshots() -> None:
    source = {"provider-main": SECRET}
    config = ProviderProfileConfig(profiles=(_profile(),))
    loaded = LoadedProviderProfileSet(config=config, _credentials=source)
    registry = ProviderRegistry(loaded, loss_matrix_revision=MATRIX_REVISION)
    original_route = registry.resolve("provider/current")

    source["provider-main"] = "mutated-secret"
    with pytest.raises(ValidationError, match="Instance is frozen"):
        config.profiles[0].base_url = "https://changed.invalid"  # type: ignore[misc]

    replacement_registry = _registry(
        profile=_profile(upstream_model="exact-model-v2"),
        secret="replacement-secret",
    )
    replacement_route = replacement_registry.resolve("provider/current")

    assert registry.credential_for(original_route) == SECRET
    assert original_route.upstream_model == "exact-model-v1"
    assert replacement_route.upstream_model == "exact-model-v2"
    assert registry.config_revision != replacement_registry.config_revision
    with pytest.raises(ProviderAliasError):
        registry.credential_for(replacement_route)


def test_missing_credential_fails_closed_without_alias_or_reference_disclosure() -> (
    None
):
    profile = _profile()
    loaded = LoadedProviderProfileSet(
        config=ProviderProfileConfig(profiles=(profile,)),
        _credentials={},
    )
    registry = ProviderRegistry(loaded, loss_matrix_revision=MATRIX_REVISION)
    route = registry.resolve("provider/current")

    with pytest.raises(ProviderProfileError) as raised:
        registry.credential_for(route)

    assert raised.value.code == "credential_unavailable"
    rendered = f"{raised.value!s} {raised.value!r}"
    assert "PROVIDER_API_KEY" not in rendered
    assert "provider/current" not in rendered


def test_registry_defensively_rejects_collisions_even_for_unvalidated_config() -> None:
    first = _profile(profile_id="provider-first")
    second = _profile(profile_id="provider-second")
    unvalidated = ProviderProfileConfig.model_construct(profiles=(first, second))
    loaded = LoadedProviderProfileSet(
        config=unvalidated,
        _credentials={
            "provider-first": "first-secret",
            "provider-second": "second-secret",
        },
    )

    with pytest.raises(ProviderProfileError) as raised:
        ProviderRegistry(loaded, loss_matrix_revision=MATRIX_REVISION)

    assert raised.value.code == "duplicate_model_alias"
    assert "first-secret" not in str(raised.value)
    assert "second-secret" not in str(raised.value)


@pytest.mark.parametrize(
    "alias",
    [
        "provider/missing",
        "Provider/current",
        "provider/current ",
        "exact-model-v1",
        "openai_compatible",
    ],
)
def test_unknown_provider_model_or_nearby_alias_never_selects_the_only_route(
    alias: str,
) -> None:
    registry = _registry()

    with pytest.raises(ProviderAliasError) as raised:
        registry.resolve(alias)

    assert raised.value.code == "unknown_model_alias"
    assert registry.public_aliases() == ("provider/current",)
    assert alias not in str(raised.value)


def test_unknown_provider_kind_is_rejected_before_registry_construction() -> None:
    payload = _profile().model_dump(mode="json")
    payload["provider_kind"] = "automatic"

    with pytest.raises(ValidationError):
        ProviderProfile.model_validate(payload)
