"""Shared types and normalization helpers for proxy settings."""

import json
from typing import Any, Literal

ProviderName = Literal["openai", "anthropic", "gemini"]
GigaChatAPIMode = Literal["v1", "v2"]
GovernanceLimitScope = Literal["api_key", "provider"]
ALL_ENABLED_PROVIDERS: tuple[ProviderName, ...] = ("openai", "anthropic", "gemini")


def normalize_provider_allowlist(value: Any) -> Any:
    """Normalize provider allowlists from ENV/CLI friendly forms."""
    if value is None or value == "":
        return None

    def _normalize_parts(parts: list[str]) -> list[str] | None:
        normalized = [part.strip().lower() for part in parts if part.strip()]
        if not normalized or "all" in normalized:
            return None
        return list(dict.fromkeys(normalized))

    if isinstance(value, str):
        return _normalize_parts(value.split(","))

    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.extend(item.split(","))
            else:
                return value
        return _normalize_parts(parts)

    return value


def normalize_optional_string_list(value: Any) -> Any:
    """Normalize endpoint/model allowlists from ENV/CLI friendly forms."""
    if value is None or value == "":
        return None

    def _normalize_parts(parts: list[str]) -> list[str] | None:
        normalized = [part.strip() for part in parts if isinstance(part, str)]
        normalized = [part for part in normalized if part]
        if not normalized:
            return None
        return list(dict.fromkeys(normalized))

    if isinstance(value, str):
        return _normalize_parts(value.split(","))

    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.extend(item.split(","))
            else:
                return value
        return _normalize_parts(parts)

    return value


def normalize_string_map(value: Any) -> Any:
    """Normalize string maps from ENV/CLI friendly forms."""
    if value is None or value == "":
        return {}

    if isinstance(value, dict):
        return {
            str(key).strip(): str(item).strip()
            for key, item in value.items()
            if str(key).strip() and item is not None and str(item).strip()
        }

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return {}
        try:
            decoded = json.loads(normalized)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            return normalize_string_map(decoded)
        result: dict[str, str] = {}
        for item in normalized.split(","):
            part = item.strip()
            if not part or "=" not in part:
                continue
            key, raw_value = part.split("=", 1)
            key = key.strip()
            raw_value = raw_value.strip()
            if key and raw_value:
                result[key] = raw_value
        return result

    return value


def normalize_enabled_providers(value: Any) -> Any:
    """Normalize enabled providers from ENV/CLI friendly forms."""
    if value is None or value == "":
        return list(ALL_ENABLED_PROVIDERS)

    def _normalize_parts(parts: list[str]) -> list[str]:
        normalized = [part.strip().lower() for part in parts if part.strip()]
        if "all" in normalized:
            return list(ALL_ENABLED_PROVIDERS)
        return list(dict.fromkeys(normalized))

    if isinstance(value, str):
        return _normalize_parts(value.split(","))

    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.extend(item.split(","))
            else:
                return value
        return _normalize_parts(parts)

    return value


def normalize_api_mode(value: Any) -> Any:
    """Normalize backend mode names from ENV/CLI friendly forms."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized or None
    return value


def normalize_lowercase_string(value: Any) -> Any:
    """Normalize string values by trimming and lowercasing them."""
    if isinstance(value, str):
        return value.strip().lower()
    return value


def normalize_optional_string(value: Any) -> Any:
    """Normalize blank string settings to ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return value


def normalize_required_string(value: Any) -> Any:
    """Normalize required string settings by trimming whitespace."""
    if isinstance(value, str):
        return value.strip()
    return value


def normalize_uppercase_string(value: Any) -> Any:
    """Normalize string values by trimming and uppercasing them."""
    if isinstance(value, str):
        return value.strip().upper()
    return value


def normalize_observability_sinks(value: Any) -> Any:
    """Normalize observability sink selection from ENV/CLI friendly forms."""
    if value is None:
        return ["prometheus"]

    def _normalize_parts(parts: list[str]) -> list[str]:
        normalized = [part.strip().lower() for part in parts if part.strip()]
        if not normalized:
            return []
        if any(part in {"off", "none", "disabled"} for part in normalized):
            return []
        return list(dict.fromkeys(normalized))

    if isinstance(value, str):
        return _normalize_parts(value.split(","))

    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.extend(item.split(","))
            else:
                return value
        return _normalize_parts(parts)

    return value


def normalize_json_array_setting(
    value: Any,
    *,
    error_message: str,
) -> Any:
    """Normalize JSON-array settings from ENV/CLI friendly forms."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return []
        try:
            decoded = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ValueError(error_message) from exc
        if decoded is None:
            return []
        return decoded
    return value
