"""Signed request-scoped model headers for native Harness clients."""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import quote

HARNESS_MODEL_HEADER = "X-GigaLoom-Model"
HARNESS_MODEL_SIGNATURE_HEADER = "X-GigaLoom-Model-Signature"
PASS_MODEL_HEADER = "X-GPT2GIGA-Pass-Model"


def signed_harness_model_headers(
    *,
    protocol: str,
    model: str,
    key: str | None,
) -> tuple[tuple[str, str], ...]:
    """Return model pin headers only when a dedicated signing key exists."""
    if not key:
        return ()
    material = f"gigaloom-model/v1\0{protocol}\0{model}".encode()
    digest = hmac.new(key.encode(), material, hashlib.sha256).hexdigest()
    return (
        (HARNESS_MODEL_HEADER, quote(model, safe="")),
        (PASS_MODEL_HEADER, "false"),
        (HARNESS_MODEL_SIGNATURE_HEADER, f"v1:{digest}"),
    )
