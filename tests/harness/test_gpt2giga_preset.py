from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.gpt2giga_preset import (
    Gpt2GigaPresetUnavailableError,
    gpt2giga_preset_available,
    migrate_legacy_gpt2giga_config,
    missing_gpt2giga_preset_modules,
    require_gpt2giga_preset,
)
from gpt2giga_harness.provider_profiles import (
    ProviderOwnership,
    provider_profile_to_dict,
    route_profile_to_dict,
)


def test_optional_preset_probe_does_not_import_provider_modules(monkeypatch):
    seen: list[str] = []

    def fake_find_spec(name: str):
        seen.append(name)
        return None if name == "gpt2giga" else SimpleNamespace()

    monkeypatch.setattr(
        "gpt2giga_harness.gpt2giga_preset.util.find_spec", fake_find_spec
    )

    assert missing_gpt2giga_preset_modules() == ("gpt2giga",)
    assert gpt2giga_preset_available() is False
    assert seen == ["gpt2giga", "gigachat", "gpt2giga", "gigachat"]


def test_optional_preset_loader_fails_with_bounded_install_guidance(monkeypatch):
    monkeypatch.setattr(
        "gpt2giga_harness.gpt2giga_preset.missing_gpt2giga_preset_modules",
        lambda: ("gpt2giga", "gigachat"),
    )

    with pytest.raises(Gpt2GigaPresetUnavailableError) as caught:
        require_gpt2giga_preset()

    assert str(caught.value) == (
        "optional gpt2giga preset is unavailable; install gpt2giga-harness[gpt2giga]"
    )


def test_legacy_environment_migrates_to_reference_only_preset(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_HARNESS_PROXY_URL", "https://proxy.example/root/")
    monkeypatch.setenv("GPT2GIGA_GIGACHAT_API_MODE", "v1")
    monkeypatch.setenv("GIGACHAT_MODEL", "GigaChat-2-Max")
    monkeypatch.setenv("GPT2GIGA_API_KEY", "secret-value-canary")

    provider, route = migrate_legacy_gpt2giga_config(
        HarnessConfig.from_env(),
        harness_id="direct-chat",
    )
    serialized = json.dumps(
        {
            "provider": provider_profile_to_dict(provider),
            "route": route_profile_to_dict(route),
        },
        sort_keys=True,
    )

    assert provider.ownership is ProviderOwnership.MIGRATED_LEGACY
    assert provider.base_url == "https://proxy.example/root"
    assert provider.route_prefix == "/v1"
    assert route.effective_base_url == "https://proxy.example/root/v1"
    assert route.model == "GigaChat-2-Max"
    assert "GPT2GIGA_HARNESS_API_KEY" in serialized
    assert "secret-value-canary" not in serialized
