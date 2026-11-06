"""Model selection for the small native operations surface."""

from typing import Any

from fastapi import Request

from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.core.context import update_request_context
from gpt2giga.providers.gigachat.model_resolution import resolve_upstream_model
from gpt2giga.providers.profiles.static_catalog import uses_static_registry_inventory


def require_native_gigachat(request: Request) -> None:
    """Reject native operations in deployments containing only other providers."""
    registry = getattr(request.app.state, "provider_registry", None)
    if registry is not None and uses_static_registry_inventory(registry):
        raise ClientCompatibilityError(
            "This operation requires a GigaChat provider.",
            code="unsupported_provider",
        )


def native_operation_model(
    request: Request, model: Any = None, *, image: bool = False
) -> str:
    """Resolve reviewed aliases and deployment defaults without forwarding image aliases."""
    require_native_gigachat(request)
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ClientCompatibilityError(
            "model must be a nonempty string.", param="model"
        )
    config = request.app.state.config
    registry = getattr(request.app.state, "provider_registry", None)
    forced = None
    if (
        isinstance(model, str)
        and registry is not None
        and model in registry.public_aliases()
    ):
        route = registry.resolve(model)
        if route.provider_kind.value != "gigachat":
            raise ClientCompatibilityError(
                "This operation requires a GigaChat model.",
                param="model",
                code="unsupported_provider",
            )
        forced = route.upstream_model
    elif image and model and not str(model).startswith("GigaChat"):
        if model not in {"gpt-image-1", "gpt-image-1-mini", "dall-e-2", "dall-e-3"}:
            raise ClientCompatibilityError("Unknown image model alias.", param="model")
        model = None
    elif not config.proxy_settings.pass_model:
        model = None
    selected = resolve_upstream_model({"model": model}, config, forced_model=forced)
    update_request_context(model_effective=selected.model)
    return selected.model
