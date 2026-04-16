"""Secret encryption helpers for control-plane payloads."""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .paths import ensure_control_plane_dir, get_control_plane_key_file


def normalize_secret_value(value: Any) -> Any:
    """Convert Pydantic secret wrappers into JSON-serializable values."""
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    if isinstance(value, dict):
        return {key: normalize_secret_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_secret_value(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_secret_value(item) for item in value]
    return value


def load_fernet(*, create: bool) -> Fernet | None:
    """Load or lazily create the local encryption key."""
    key_file = get_control_plane_key_file()
    if key_file.exists():
        return Fernet(key_file.read_bytes())
    if not create:
        return None

    ensure_control_plane_dir()
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    try:
        import os

        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return Fernet(key)


def encrypt_secret_payload(fernet: Fernet, value: Any) -> str:
    """Encrypt a JSON-serializable secret payload."""
    encoded = json.dumps(
        normalize_secret_value(value),
        ensure_ascii=False,
    ).encode("utf-8")
    return fernet.encrypt(encoded).decode("utf-8")


def decrypt_secret_payload(fernet: Fernet, token: str) -> Any:
    """Decrypt a control-plane secret value."""
    decrypted = fernet.decrypt(token.encode("utf-8"))
    return json.loads(decrypted.decode("utf-8"))


def decrypt_secret_map(
    encrypted: dict[str, Any] | None,
    *,
    secret_fields: set[str],
) -> dict[str, Any]:
    """Decrypt a subset of persisted secret fields."""
    if not encrypted:
        return {}

    fernet = load_fernet(create=False)
    if fernet is None:
        raise RuntimeError(
            "Persisted secrets exist but the control-plane key is missing"
        )

    values: dict[str, Any] = {}
    for field in secret_fields:
        token = encrypted.get(field)
        if not token:
            continue
        if not isinstance(token, str):
            raise ValueError(
                f"Encrypted control-plane field `{field}` must be a string"
            )
        try:
            values[field] = decrypt_secret_payload(fernet, token)
        except InvalidToken as exc:
            raise RuntimeError(
                f"Failed to decrypt persisted control-plane field `{field}`"
            ) from exc
    return values
