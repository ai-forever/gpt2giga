"""Small shared telemetry utilities."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any


def _label_value(value: Any, *, default: str = "unknown") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_package_version() -> str:
    try:
        return version("gpt2giga")
    except PackageNotFoundError:
        return "dev"


def _log_warning(logger: Any | None, message: str, *args: Any) -> None:
    if logger is None:
        return
    if args:
        try:
            message = message % args
        except (TypeError, ValueError):
            message = " ".join([message, *(str(item) for item in args)])
    warning = getattr(logger, "warning", None)
    if callable(warning):
        warning(message)
