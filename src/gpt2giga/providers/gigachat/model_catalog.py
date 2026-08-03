"""Bounded credential-scoped cache for GigaChat model discovery."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from gpt2giga.models.catalog import (
    CatalogSource,
    ModelCatalogSnapshot,
    ModelDescriptor,
    ModelDiscoveryContext,
    ModelNotFoundError,
)
from gpt2giga.providers.gigachat.model_discovery import GigaChatModelDiscovery

DEFAULT_PROVIDER_PROFILE_ID = "native-gigachat"


class ModelCatalogBoundsError(RuntimeError):
    """Report a provider inventory that exceeds configured safety bounds."""


class SupportsGigaChatModelDiscovery(Protocol):
    """Represent the provider discovery operation used by the cache."""

    async def discover(
        self,
        giga_client: Any,
        context: ModelDiscoveryContext,
    ) -> ModelCatalogSnapshot:
        """Return a fresh provider inventory snapshot."""


class CredentialScopeDigester:
    """Create process-local HMAC identities without retaining auth values."""

    def __init__(self, *, salt: bytes | None = None) -> None:
        self._salt = salt or os.urandom(32)
        if len(self._salt) < 32:
            raise ValueError("credential scope digest salt must be at least 32 bytes")

    def digest(self, giga_client: Any, *, provider_profile_id: str) -> str:
        """Hash one SDK client's credential/account/scope identity."""
        identity = _credential_identity(giga_client)
        serialized = json.dumps(
            {
                "provider_profile_id": provider_profile_id,
                "identity": identity,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{hmac.new(self._salt, serialized, hashlib.sha256).hexdigest()}"


class GigaChatModelCatalog:
    """Share bounded provider inventory snapshots across matching auth scopes."""

    def __init__(
        self,
        *,
        discovery: SupportsGigaChatModelDiscovery | None = None,
        scope_digester: CredentialScopeDigester | None = None,
        max_models: int = 256,
        max_payload_bytes: int = 2 * 1024 * 1024,
        max_scopes: int = 64,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_models <= 0:
            raise ValueError("max_models must be positive")
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        if max_scopes <= 0:
            raise ValueError("max_scopes must be positive")
        self._discovery = discovery or GigaChatModelDiscovery()
        self._scope_digester = scope_digester or CredentialScopeDigester()
        self._max_models = max_models
        self._max_payload_bytes = max_payload_bytes
        self._max_scopes = max_scopes
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._cache: OrderedDict[tuple[str, str], ModelCatalogSnapshot] = OrderedDict()
        self._inflight: dict[tuple[str, str], asyncio.Task[ModelCatalogSnapshot]] = {}
        self._lock = asyncio.Lock()

    async def list_models(
        self,
        giga_client: Any,
        *,
        provider_profile_id: str = DEFAULT_PROVIDER_PROFILE_ID,
        refresh: bool = False,
    ) -> ModelCatalogSnapshot:
        """Return a fresh cache hit or one shared provider refresh."""
        context = self.discovery_context(
            giga_client,
            provider_profile_id=provider_profile_id,
        )
        key = (context.provider_profile_id, context.credential_scope_digest)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("catalog clock must return a timezone-aware datetime")

        async with self._lock:
            cached = self._cache.get(key)
            if cached is not None and not refresh and _is_fresh(cached, now=now):
                self._cache.move_to_end(key)
                return cached

            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(
                    self._refresh(
                        key=key,
                        giga_client=giga_client,
                        context=context,
                        stale_candidate=cached,
                    )
                )
                self._inflight[key] = task

        return await asyncio.shield(task)

    async def refresh(
        self,
        giga_client: Any,
        *,
        provider_profile_id: str = DEFAULT_PROVIDER_PROFILE_ID,
    ) -> ModelCatalogSnapshot:
        """Explicitly refresh one credential-scoped provider inventory."""
        return await self.list_models(
            giga_client,
            provider_profile_id=provider_profile_id,
            refresh=True,
        )

    async def get_model(
        self,
        model_id: str,
        giga_client: Any,
        *,
        provider_profile_id: str = DEFAULT_PROVIDER_PROFILE_ID,
        refresh: bool = False,
    ) -> ModelDescriptor:
        """Resolve one model from the same snapshot used by list_models."""
        snapshot = await self.list_models(
            giga_client,
            provider_profile_id=provider_profile_id,
            refresh=refresh,
        )
        for model in snapshot.models:
            if model.id == model_id:
                return model
        raise ModelNotFoundError(model_id)

    def discovery_context(
        self,
        giga_client: Any,
        *,
        provider_profile_id: str = DEFAULT_PROVIDER_PROFILE_ID,
    ) -> ModelDiscoveryContext:
        """Build a secret-free context for one SDK client."""
        return ModelDiscoveryContext(
            provider_profile_id=provider_profile_id,
            credential_scope_digest=self._scope_digester.digest(
                giga_client,
                provider_profile_id=provider_profile_id,
            ),
        )

    async def _refresh(
        self,
        *,
        key: tuple[str, str],
        giga_client: Any,
        context: ModelDiscoveryContext,
        stale_candidate: ModelCatalogSnapshot | None,
    ) -> ModelCatalogSnapshot:
        current_task = asyncio.current_task()
        try:
            try:
                snapshot = await self._discovery.discover(giga_client, context)
                self._validate_bounds(snapshot)
            except Exception:
                if stale_candidate is None:
                    raise
                snapshot = _as_stale(stale_candidate)

            async with self._lock:
                self._cache[key] = snapshot
                self._cache.move_to_end(key)
                while len(self._cache) > self._max_scopes:
                    self._cache.popitem(last=False)
            return snapshot
        finally:
            async with self._lock:
                if self._inflight.get(key) is current_task:
                    self._inflight.pop(key, None)

    def _validate_bounds(self, snapshot: ModelCatalogSnapshot) -> None:
        if len(snapshot.models) > self._max_models:
            raise ModelCatalogBoundsError("model inventory exceeds the model limit")
        payload_size = len(snapshot.model_dump_json().encode("utf-8"))
        if payload_size > self._max_payload_bytes:
            raise ModelCatalogBoundsError("model inventory exceeds the payload limit")


def _credential_identity(giga_client: Any) -> tuple[tuple[str, str], ...]:
    settings = getattr(giga_client, "_settings", None)
    if settings is None:
        settings = getattr(giga_client, "settings", None)

    credentials = _non_blank(getattr(settings, "credentials", None))
    if credentials is not None:
        return (
            ("auth_mode", "credentials"),
            ("credentials", credentials),
            ("scope", _non_blank(getattr(settings, "scope", None)) or ""),
        )

    user = _non_blank(getattr(settings, "user", None))
    password = _non_blank(getattr(settings, "password", None))
    if user is not None or password is not None:
        return (
            ("auth_mode", "user_password"),
            ("base_url", str(getattr(settings, "base_url", ""))),
            ("password", password or ""),
            ("user", user or ""),
        )

    access_token = _non_blank(getattr(settings, "access_token", None))
    if access_token is None:
        access_token = _non_blank(getattr(giga_client, "_access_token", None))
    if access_token is not None:
        return (("auth_mode", "access_token"), ("access_token", access_token))

    return (("auth_mode", "client_instance"), ("identity", str(id(giga_client))))


def _non_blank(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _is_fresh(snapshot: ModelCatalogSnapshot, *, now: datetime) -> bool:
    return not snapshot.stale and now < snapshot.expires_at


def _as_stale(snapshot: ModelCatalogSnapshot) -> ModelCatalogSnapshot:
    models = tuple(
        model.model_copy(update={"stale": True}) for model in snapshot.models
    )
    return snapshot.model_copy(
        update={
            "models": models,
            "stale": True,
            "source": CatalogSource.STALE_CACHE,
        }
    )
