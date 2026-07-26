"""Compatibility accessors for the packaged no-build Harness UI assets."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources


ASSET_PACKAGE = "gpt2giga_harness.ui.assets"
ASSET_NAMES = frozenset(
    {
        "app.css",
        "app.js",
        "brand/gigaloom-mark.svg",
        "brand/gigaloom-mark-dark.svg",
        "brand/gigaloom-mask.svg",
        "brand/gigaloom.webmanifest",
        "index.html",
    }
)


class UIAssetNotFoundError(FileNotFoundError):
    """Report a missing or unknown packaged UI asset."""


@lru_cache(maxsize=len(ASSET_NAMES))
def load_asset(name: str) -> bytes:
    """Load one allowlisted UI asset from package resources."""
    if name not in ASSET_NAMES:
        raise UIAssetNotFoundError(name)
    try:
        return resources.files(ASSET_PACKAGE).joinpath(name).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise UIAssetNotFoundError(name) from exc


def load_text_asset(name: str) -> str:
    """Load one UTF-8 UI asset as text."""
    return load_asset(name).decode("utf-8")


# Keep the historical import working while callers migrate to packaged assets.
INDEX_HTML = load_text_asset("index.html")
