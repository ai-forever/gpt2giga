"""Langfuse-specific OTLP adapters."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

from .otlp import OtlpHttpTraceSink, _build_otlp_headers
from .utils import _label_value, _safe_int
from .encoding import _is_error_event


class LangfuseTraceSink(OtlpHttpTraceSink):
    """Export normalized request events to Langfuse via its OTLP/HTTP endpoint."""

    name = "langfuse"


def _build_langfuse_attributes(event: Mapping[str, Any]) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "langfuse.observation.level": "ERROR" if _is_error_event(event) else "DEFAULT",
        "langfuse.observation.metadata.provider_surface": _label_value(
            event.get("provider")
        ),
        "langfuse.observation.metadata.endpoint": _label_value(event.get("endpoint")),
        "langfuse.observation.metadata.status_code": str(
            _safe_int(event.get("status_code"), default=0)
        ),
    }
    method = _label_value(event.get("method"), default="")
    if method:
        attributes["langfuse.observation.metadata.method"] = method.upper()
    request_id = _label_value(event.get("request_id"), default="")
    if request_id:
        attributes["langfuse.observation.metadata.request_id"] = request_id
    api_key_name = _label_value(event.get("api_key_name"), default="")
    if api_key_name:
        attributes["langfuse.observation.metadata.api_key_name"] = api_key_name
    error_type = _label_value(event.get("error_type"), default="")
    if error_type:
        attributes["langfuse.observation.status_message"] = error_type
        attributes["langfuse.observation.metadata.error_type"] = error_type

    model = _label_value(event.get("model"), default="")
    if model:
        attributes["langfuse.observation.type"] = "generation"
        attributes["langfuse.observation.model.name"] = model
    else:
        attributes["langfuse.observation.type"] = "span"

    usage = event.get("token_usage")
    if isinstance(usage, Mapping):
        attributes["langfuse.observation.usage_details"] = json.dumps(
            {
                "input": _safe_int(usage.get("prompt_tokens"), default=0),
                "output": _safe_int(usage.get("completion_tokens"), default=0),
                "total": _safe_int(usage.get("total_tokens"), default=0),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    return attributes


def _build_langfuse_endpoint(config: Any | None) -> str:
    proxy_settings = getattr(config, "proxy_settings", None)
    observability = getattr(proxy_settings, "observability", None)
    langfuse = getattr(observability, "langfuse", None)
    base_url = getattr(
        langfuse,
        "base_url",
        getattr(proxy_settings, "langfuse_base_url", None),
    )
    normalized = str(base_url).strip().rstrip("/") if base_url is not None else ""
    if not normalized:
        raise RuntimeError(
            "Langfuse sink requires GPT2GIGA_LANGFUSE_BASE_URL to be configured."
        )
    return f"{normalized}/api/public/otel/v1/traces"


def _build_langfuse_headers(config: Any | None) -> dict[str, str]:
    proxy_settings = getattr(config, "proxy_settings", None)
    observability = getattr(proxy_settings, "observability", None)
    langfuse = getattr(observability, "langfuse", None)
    public_key = str(
        getattr(
            langfuse,
            "public_key",
            getattr(proxy_settings, "langfuse_public_key", ""),
        )
        or ""
    ).strip()
    secret_key = str(
        getattr(
            langfuse,
            "secret_key",
            getattr(proxy_settings, "langfuse_secret_key", ""),
        )
        or ""
    ).strip()
    if not public_key or not secret_key:
        raise RuntimeError(
            "Langfuse sink requires GPT2GIGA_LANGFUSE_PUBLIC_KEY and "
            "GPT2GIGA_LANGFUSE_SECRET_KEY."
        )
    auth_value = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode(
        "ascii"
    )
    headers = {
        "Authorization": f"Basic {auth_value}",
        "x-langfuse-ingestion-version": "4",
    }
    headers.update(_build_otlp_headers(config))
    return headers
