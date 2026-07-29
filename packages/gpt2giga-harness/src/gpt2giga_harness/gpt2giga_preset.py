"""Optional gpt2giga provider preset boundary."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module, util
from typing import Any, Callable

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.provider_profiles import (
    ModelPurpose,
    ProviderProfile,
    RouteProfile,
    migrate_legacy_provider_route,
)


GPT2GIGA_PRESET_EXTRA = "gpt2giga"
DEFAULT_GPT2GIGA_MODEL = "GigaChat"
_PRESET_MODULES = ("gpt2giga", "gigachat")


class Gpt2GigaPresetUnavailableError(RuntimeError):
    """Raised when an operation requires the optional gpt2giga preset."""


@dataclass(frozen=True)
class Gpt2GigaPresetRuntime:
    """Late-bound gateway runtime used only at the provider adapter boundary."""

    client_type: type[Any]
    load_config: Callable[[], Any]


def missing_gpt2giga_preset_modules() -> tuple[str, ...]:
    """Return missing optional runtime modules without importing them."""
    return tuple(name for name in _PRESET_MODULES if util.find_spec(name) is None)


def gpt2giga_preset_available() -> bool:
    """Return whether the optional preset runtime is installed."""
    return not missing_gpt2giga_preset_modules()


def require_gpt2giga_preset() -> Gpt2GigaPresetRuntime:
    """Load the optional runtime only for an operation that owns its use."""
    missing = missing_gpt2giga_preset_modules()
    if missing:
        raise Gpt2GigaPresetUnavailableError(
            "optional gpt2giga preset is unavailable; install "
            f"gigaloom[{GPT2GIGA_PRESET_EXTRA}]"
        )
    gigachat_module = import_module("gigachat")
    gateway_cli = import_module("gpt2giga.cli")
    return Gpt2GigaPresetRuntime(
        client_type=gigachat_module.GigaChat,
        load_config=gateway_cli.load_config,
    )


def migrate_legacy_gpt2giga_config(
    config: HarnessConfig,
    *,
    harness_id: str,
    model: str | None = None,
    purpose: ModelPurpose = ModelPurpose.CODING,
) -> tuple[ProviderProfile, RouteProfile]:
    """Project legacy environment/config values into reference-only profiles."""
    return migrate_legacy_provider_route(
        proxy_url=config.proxy_url,
        api_mode=config.default_api_mode.value,
        harness_id=harness_id,
        model=model or config.default_model or DEFAULT_GPT2GIGA_MODEL,
        purpose=purpose,
    )
