"""Helpers for request-scoped and application-scoped state."""

import json

from fastapi import Request

from gpt2giga.storage.resources import ResourceStore, ResourceStoreError

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.catalog import ModelCatalogSnapshot
from gpt2giga.providers.gigachat.model_catalog import (
    DEFAULT_PROVIDER_PROFILE_ID,
    GigaChatModelCatalog,
)


def get_gigachat_client(request: Request):
    """Return the request-scoped GigaChat client when present."""
    app_state = request.app.state
    request_state = getattr(request, "state", None)
    return getattr(request_state, "gigachat_client", app_state.gigachat_client)


def get_request_transformer(request: Request):
    """Return preparation bound to the selected profile's configuration."""
    return getattr(
        request.state, "request_transformer", request.app.state.request_transformer
    )


def get_gigachat_model_catalog(request: Request) -> GigaChatModelCatalog:
    """Return the application-scoped dynamic GigaChat model catalog."""
    app_state = request.app.state
    if not hasattr(app_state, "gigachat_model_catalog"):
        app_state.gigachat_model_catalog = GigaChatModelCatalog()
    return app_state.gigachat_model_catalog


def get_gigachat_model_catalog_profile_id(request: Request) -> str:
    """Return the stable GigaChat profile identity shared by catalog surfaces."""
    app_state = request.app.state
    configured = getattr(app_state, "model_catalog_profile_id", None)
    if isinstance(configured, str) and configured:
        return configured
    registry = getattr(app_state, "provider_registry", None)
    profiles = tuple(getattr(getattr(registry, "config", None), "profiles", ()))
    gigachat_profiles = tuple(
        profile
        for profile in profiles
        if getattr(getattr(profile, "provider_kind", None), "value", None) == "gigachat"
    )
    if len(gigachat_profiles) == 1:
        return str(gigachat_profiles[0].profile_id)
    return DEFAULT_PROVIDER_PROFILE_ID


def record_gigachat_model_catalog_snapshot(
    request: Request,
    snapshot: ModelCatalogSnapshot,
) -> None:
    """Expose one content-free catalog revision to readiness and admission."""
    request.app.state.model_catalog_readiness = {
        "state": "stale" if snapshot.stale else "fresh",
        "provider_profile_id": snapshot.provider_profile_id,
        "inventory_revision": snapshot.inventory_revision,
    }


def get_model_concurrency_limiter(request: Request) -> ModelConcurrencyLimiter:
    """Return the application-scoped per-model concurrency limiter."""
    app_state = request.app.state
    if not hasattr(app_state, "model_concurrency_limiter"):
        app_state.model_concurrency_limiter = ModelConcurrencyLimiter({})
    return app_state.model_concurrency_limiter


def get_resource_store(request: Request) -> ResourceStore:
    """Return the lifespan-owned store; never create a volatile fallback."""
    store = getattr(request.app.state, "resource_store", None)
    if not isinstance(store, ResourceStore):
        raise ResourceStoreError("Resource storage is unavailable")
    return store


def get_resource_owner(
    request: Request, *, provider: str = "gigachat", profile: str | None = None
) -> str:
    """Derive a persistent owner from trusted configuration and request auth."""
    config = request.app.state.config
    settings = config.proxy_settings
    identity = settings.resource_trusted_identity
    if not identity:
        identity = (
            settings.api_key
            if settings.enable_api_key_auth or settings.mode == "PROD"
            else "anonymous"
        ) or "anonymous"
    runtime = getattr(request.app.state, "bridge_provider_runtime", None)
    profile = profile or getattr(request.state, "provider_profile_id", None)
    upstream = (
        runtime._giga_settings.get(profile, config.gigachat_settings)
        if runtime is not None
        else config.gigachat_settings
    )
    credential_context = {}
    for key in ("base_url", "scope", "credentials", "access_token", "user", "password"):
        value = getattr(upstream, key, None)
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        if value is not None:
            credential_context[key] = str(value)
    if settings.pass_token:
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            # Middleware validates the pass-through format; never decode JWT claims.
            credential_context = {
                "base_url": credential_context.get("base_url", ""),
                "pass_token": authorization.removeprefix("Bearer "),
            }
    return get_resource_store(request).owner_namespace(
        str(identity),
        provider=provider,
        profile=profile or get_gigachat_model_catalog_profile_id(request),
        credential_context=json.dumps(credential_context, sort_keys=True),
    )
