"""GigaChat-backed dynamic model discovery."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from gpt2giga.models.catalog import (
    MODEL_CATALOG_SCHEMA_VERSION,
    CatalogSource,
    ModelCatalogSnapshot,
    ModelDescriptor,
    ModelDiscoveryContext,
)

_MAPPED_FIELDS = frozenset(
    {
        "id",
        "id_",
        "model",
        "owned_by",
        "type",
        "available",
        "deprecated",
    }
)
_SENSITIVE_METADATA_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "headers",
        "password",
        "refresh_token",
        "secret",
        "set_cookie",
        "token",
        "x_headers",
    }
)
_SENSITIVE_METADATA_SUFFIXES = (
    "_api_key",
    "_authorization",
    "_credential",
    "_credentials",
    "_password",
    "_secret",
    "_token",
)
_DROP = object()


class GigaChatModelDiscoveryError(RuntimeError):
    """Report an invalid provider inventory without echoing provider data."""


class GigaChatModelDiscovery:
    """Discover credential-visible models through the authenticated SDK client."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 30.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def discover(
        self,
        giga_client: Any,
        context: ModelDiscoveryContext,
    ) -> ModelCatalogSnapshot:
        """Call ``aget_models`` and normalize its safe inventory metadata."""
        response = await giga_client.aget_models()
        raw_models = getattr(response, "data", None)
        if raw_models is None:
            raise GigaChatModelDiscoveryError(
                "GigaChat models response does not expose a data collection"
            )

        discovered_at = self._clock()
        if discovered_at.tzinfo is None or discovered_at.utcoffset() is None:
            raise ValueError("discovery clock must return a timezone-aware datetime")

        normalized = [_normalize_model(item) for item in raw_models]
        _reject_duplicate_ids(normalized)
        revision = _inventory_revision(context.provider_profile_id, normalized)
        descriptors = tuple(
            ModelDescriptor(
                id=model["id"],
                provider_kind="gigachat",
                provider_profile_id=context.provider_profile_id,
                owned_by=model["owned_by"],
                model_type=model["model_type"],
                available=model["available"],
                deprecated=model["deprecated"],
                discovered_at=discovered_at,
                inventory_revision=revision,
                provider_metadata=model["provider_metadata"],
            )
            for model in normalized
        )
        return ModelCatalogSnapshot(
            provider_profile_id=context.provider_profile_id,
            credential_scope_digest=context.credential_scope_digest,
            models=descriptors,
            inventory_revision=revision,
            discovered_at=discovered_at,
            expires_at=discovered_at + self._ttl,
            source=CatalogSource.PROVIDER_API,
        )


def _normalize_model(model: Any) -> dict[str, Any]:
    payload = _dump_model(model)
    model_id = _non_blank_string(
        payload.get("id") or payload.get("id_") or payload.get("model")
    )
    if model_id is None:
        raise GigaChatModelDiscoveryError(
            "GigaChat model inventory contains an entry without an id"
        )

    metadata = {
        str(key): safe_value
        for key, value in payload.items()
        if key not in _MAPPED_FIELDS
        and (safe_value := _safe_json_value(key, value)) is not _DROP
    }
    return {
        "id": model_id,
        "owned_by": _non_blank_string(payload.get("owned_by")),
        "model_type": _non_blank_string(payload.get("type")),
        "available": _bool_or_default(payload.get("available"), default=True),
        "deprecated": _bool_or_default(payload.get("deprecated"), default=False),
        "provider_metadata": metadata,
    }


def _dump_model(model: Any) -> dict[str, Any]:
    if isinstance(model, Mapping):
        return dict(model)
    if hasattr(model, "model_dump"):
        try:
            dumped = model.model_dump(by_alias=True, mode="json")
        except TypeError:
            dumped = model.model_dump(by_alias=True)
        if isinstance(dumped, Mapping):
            return dict(dumped)
    try:
        return {
            key: value for key, value in vars(model).items() if not key.startswith("_")
        }
    except TypeError as exc:
        raise GigaChatModelDiscoveryError(
            "GigaChat model inventory contains an invalid entry"
        ) from exc


def _safe_json_value(key: Any, value: Any, *, depth: int = 0) -> Any:
    normalized_key = str(key).casefold().replace("-", "_")
    if _is_sensitive_metadata_key(normalized_key) or depth > 8:
        return _DROP
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _DROP
    if isinstance(value, Mapping):
        safe_mapping: dict[str, Any] = {}
        for nested_key, nested_value in value.items():
            safe_value = _safe_json_value(
                nested_key,
                nested_value,
                depth=depth + 1,
            )
            if safe_value is not _DROP:
                safe_mapping[str(nested_key)] = safe_value
        return safe_mapping
    if isinstance(value, (list, tuple)):
        safe_items = [
            safe_value
            for item in value
            if (safe_value := _safe_json_value("item", item, depth=depth + 1))
            is not _DROP
        ]
        return safe_items
    return _DROP


def _is_sensitive_metadata_key(key: str) -> bool:
    return key in _SENSITIVE_METADATA_KEYS or key.endswith(_SENSITIVE_METADATA_SUFFIXES)


def _inventory_revision(
    provider_profile_id: str,
    normalized: list[dict[str, Any]],
) -> str:
    revision_models = sorted(normalized, key=lambda model: model["id"])
    revision_input = {
        "schema_version": MODEL_CATALOG_SCHEMA_VERSION,
        "provider_profile_id": provider_profile_id,
        "models": revision_models,
    }
    serialized = json.dumps(
        revision_input,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def _reject_duplicate_ids(normalized: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for model in normalized:
        model_id = model["id"]
        if model_id in seen:
            raise GigaChatModelDiscoveryError(
                "GigaChat model inventory contains duplicate ids"
            )
        seen.add(model_id)


def _non_blank_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _bool_or_default(value: Any, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default
