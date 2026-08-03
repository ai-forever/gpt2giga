"""Helpers for request-scoped and application-scoped state."""

from fastapi import Request

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


def get_batch_store(request: Request) -> dict:
    """Return the in-memory batch metadata store."""
    app_state = request.app.state
    if not hasattr(app_state, "batch_metadata_store"):
        app_state.batch_metadata_store = {}
    return app_state.batch_metadata_store


def get_file_store(request: Request) -> dict:
    """Return the in-memory file metadata store."""
    app_state = request.app.state
    if not hasattr(app_state, "file_metadata_store"):
        app_state.file_metadata_store = {}
    return app_state.file_metadata_store
