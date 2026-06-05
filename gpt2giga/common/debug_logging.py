"""Helpers for payload-level debug logging."""

import json
from typing import Any


def serialize_for_debug_log(value: Any, *, exclude_none: bool = False) -> Any:
    """Return a JSON-compatible snapshot suitable for structured debug logs."""
    dumped = _model_dump(value, exclude_none=exclude_none)
    try:
        return json.loads(json.dumps(dumped, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return str(dumped)


def log_debug_payload(
    logger: Any,
    config_or_mode: Any,
    *,
    event: str,
    message: str,
    payload_key: str,
    payload: Any,
    exclude_none: bool = False,
    **extra: Any,
) -> None:
    """Log full payloads in non-PROD DEBUG logs while omitting them in PROD."""
    if logger is None:
        return

    if _is_prod_mode(config_or_mode):
        logger.bind(event=event).debug(f"{message} (payload omitted in PROD)")
        return

    logger.bind(
        event=event,
        **extra,
        **{payload_key: serialize_for_debug_log(payload, exclude_none=exclude_none)},
    ).debug(message)


def _model_dump(value: Any, *, exclude_none: bool) -> Any:
    if not hasattr(value, "model_dump"):
        return value

    for kwargs in (
        {"exclude_none": exclude_none, "mode": "json", "by_alias": True},
        {"exclude_none": exclude_none, "mode": "json"},
        {"exclude_none": exclude_none},
        {},
    ):
        try:
            return value.model_dump(**kwargs)
        except TypeError:
            continue
    return value


def _is_prod_mode(config_or_mode: Any) -> bool:
    if isinstance(config_or_mode, str):
        return config_or_mode.upper() == "PROD"

    settings = getattr(config_or_mode, "proxy_settings", config_or_mode)
    mode = getattr(settings, "mode", "DEV")
    return isinstance(mode, str) and mode.upper() == "PROD"
