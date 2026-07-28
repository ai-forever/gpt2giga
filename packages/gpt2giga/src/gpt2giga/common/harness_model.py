"""Authenticated request-scoped model selection for native Harness clients."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from urllib.parse import unquote

from fastapi import Request

HARNESS_MODEL_HEADER = "x-gigaloom-model"
HARNESS_MODEL_SIGNATURE_HEADER = "x-gigaloom-model-signature"
PASS_MODEL_HEADER = "x-gpt2giga-pass-model"
MAX_MODEL_LENGTH = 256


def trusted_harness_model(
    request: Request,
    *,
    protocol: str,
    user_agent_prefix: str,
    normalize: Callable[[str], str] | None = None,
) -> str | None:
    """Return a signed Harness model override or fail closed."""
    user_agent = request.headers.get("user-agent", "").strip().lower()
    if not user_agent.startswith(user_agent_prefix):
        return None
    if request.headers.get(PASS_MODEL_HEADER, "").strip().lower() != "false":
        return None
    encoded_model = request.headers.get(HARNESS_MODEL_HEADER)
    if not encoded_model:
        return None
    model = unquote(encoded_model).strip()
    if normalize is not None:
        model = normalize(model)
    if not _valid_model(model):
        return None
    key = getattr(request.app.state.config.proxy_settings, "harness_model_key", None)
    signature = request.headers.get(HARNESS_MODEL_SIGNATURE_HEADER, "")
    if not key or not signature:
        return None
    expected = harness_model_signature(key, protocol=protocol, model=model)
    if not hmac.compare_digest(signature, expected):
        return None
    return model


def harness_model_signature(key: str, *, protocol: str, model: str) -> str:
    """Sign one protocol/model pair with the deployment-owned Harness key."""
    material = f"gigaloom-model/v1\0{protocol}\0{model}".encode()
    digest = hmac.new(key.encode(), material, hashlib.sha256).hexdigest()
    return f"v1:{digest}"


def _valid_model(model: str) -> bool:
    return bool(
        model
        and len(model) <= MAX_MODEL_LENGTH
        and not any(ord(character) < 32 or ord(character) == 127 for character in model)
    )
