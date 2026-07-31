"""Authenticated request-scoped model overrides for legacy GigaLoom clients."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import unquote

from fastapi import Request

LEGACY_GIGALOOM_MODEL_HEADER = "x-gigaloom-model"
LEGACY_GIGALOOM_MODEL_SIGNATURE_HEADER = "x-gigaloom-model-signature"
LEGACY_GIGALOOM_HMAC_DOMAIN = "gigaloom-model/v1"
PASS_MODEL_HEADER = "x-gpt2giga-pass-model"
MAX_MODEL_LENGTH = 256


def apply_model_override(payload: Any, model: str | None) -> Any:
    """Apply a trusted request-scoped model after global pass-model handling."""
    if model is None:
        return payload
    if isinstance(payload, Mapping):
        return {**payload, "model": model}
    model_copy = getattr(payload, "model_copy", None)
    if callable(model_copy):
        return model_copy(update={"model": model})
    setattr(payload, "model", model)
    return payload


def resolve_signed_model_override(
    request: Request,
    *,
    protocol: str,
    user_agent_prefix: str,
    normalize: Callable[[str], str] | None = None,
) -> str | None:
    """Return an authenticated legacy model override or fail closed."""
    user_agent = request.headers.get("user-agent", "").strip().lower()
    if not user_agent.startswith(user_agent_prefix):
        return None
    if request.headers.get(PASS_MODEL_HEADER, "").strip().lower() != "false":
        return None
    encoded_model = request.headers.get(LEGACY_GIGALOOM_MODEL_HEADER)
    if not encoded_model:
        return None
    model = unquote(encoded_model).strip()
    if normalize is not None:
        model = normalize(model)
    if not _valid_model(model):
        return None
    key = getattr(request.app.state.config.proxy_settings, "harness_model_key", None)
    signature = request.headers.get(LEGACY_GIGALOOM_MODEL_SIGNATURE_HEADER, "")
    if not key or not signature:
        return None
    expected = _model_override_signature(key, protocol=protocol, model=model)
    if not hmac.compare_digest(signature, expected):
        return None
    return model


def _model_override_signature(key: str, *, protocol: str, model: str) -> str:
    """Sign one protocol/model pair with the legacy compatibility key."""
    material = f"{LEGACY_GIGALOOM_HMAC_DOMAIN}\0{protocol}\0{model}".encode()
    digest = hmac.new(key.encode(), material, hashlib.sha256).hexdigest()
    return f"v1:{digest}"


def _valid_model(model: str) -> bool:
    return bool(
        model
        and len(model) <= MAX_MODEL_LENGTH
        and not any(ord(character) < 32 or ord(character) == 127 for character in model)
    )
