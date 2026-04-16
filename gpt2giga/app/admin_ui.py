"""Optional admin UI package detection and path helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from pathlib import Path

_UI_PACKAGE_NAME = "gpt2giga_ui"


@dataclass(frozen=True, slots=True)
class AdminUIResources:
    """Filesystem-backed resources exposed by the optional UI package."""

    package_root: Path
    static_dir: Path
    console_html_path: Path


def _build_resources(package_root: Path) -> AdminUIResources | None:
    static_dir = package_root / "static"
    console_html_path = package_root / "templates" / "console.html"
    if not static_dir.is_dir() or not console_html_path.is_file():
        return None
    return AdminUIResources(
        package_root=package_root,
        static_dir=static_dir,
        console_html_path=console_html_path,
    )


def _get_repo_local_admin_ui_resources() -> AdminUIResources | None:
    repo_root = Path(__file__).resolve().parents[2]
    package_root = repo_root / "packages" / "gpt2giga-ui" / "src" / _UI_PACKAGE_NAME
    return _build_resources(package_root)


@lru_cache(maxsize=1)
def get_admin_ui_resources() -> AdminUIResources | None:
    """Return UI resources from the repo checkout or installed optional package."""
    repo_local_resources = _get_repo_local_admin_ui_resources()
    if repo_local_resources is not None:
        return repo_local_resources

    try:
        package = import_module(_UI_PACKAGE_NAME)
    except ModuleNotFoundError:
        return None

    package_file = getattr(package, "__file__", None)
    if not isinstance(package_file, str):
        return None

    package_root = Path(package_file).resolve().parent
    return _build_resources(package_root)


def is_admin_ui_enabled(config: object) -> bool:
    """Return whether the optional admin UI should be exposed."""
    proxy_settings = getattr(config, "proxy_settings", config)
    return not bool(getattr(proxy_settings, "disable_ui", False)) and (
        get_admin_ui_resources() is not None
    )


def get_admin_setup_path(config: object) -> str:
    """Return the operator setup path appropriate for the current UI mode."""
    return "/admin/setup" if is_admin_ui_enabled(config) else "/admin/api/setup"
