"""Architecture guardrails for module dependency direction."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
TRANSPORT_STREAMING_MODULE = "gpt2giga.api.openai.streaming"
RESTRICTED_ROOTS = (
    REPO_ROOT / "gpt2giga" / "features",
    REPO_ROOT / "gpt2giga" / "providers",
)
ADMIN_ROUTE_FILES = (
    REPO_ROOT / "gpt2giga" / "api" / "admin" / "runtime.py",
    REPO_ROOT / "gpt2giga" / "api" / "admin" / "settings.py",
)
ADMIN_ROUTE_BANNED_IMPORTS = (
    "gpt2giga.app._admin_runtime",
    "gpt2giga.app._admin_settings",
    "gpt2giga.app.runtime_backends",
    "gpt2giga.app.wiring",
    "gpt2giga.core.config.control_plane",
    "gpt2giga.core.config._control_plane",
)
FRONTEND_ROUTE_STATE_DIRS = (
    REPO_ROOT / "gpt2giga" / "frontend" / "admin" / "pages" / "files-batches",
    REPO_ROOT / "gpt2giga" / "frontend" / "admin" / "pages" / "logs",
    REPO_ROOT / "gpt2giga" / "frontend" / "admin" / "pages" / "traffic",
    REPO_ROOT / "gpt2giga" / "frontend" / "admin" / "pages" / "settings",
    REPO_ROOT / "gpt2giga" / "frontend" / "admin" / "pages" / "setup",
)
FRONTEND_ROUTE_STATE_ALLOWED_FILES = {"serializers.ts", "state.ts"}
FRONTEND_ROUTE_STATE_TOKENS = (
    "new URLSearchParams",
    "window.location.search",
    "location.search",
)


def _matches_module_name(imported_module: str, expected_module: str) -> bool:
    return imported_module == expected_module or imported_module.startswith(
        f"{expected_module}."
    )


def _find_banned_imports(
    source_file: Path,
    *,
    banned_modules: tuple[str, ...],
) -> list[str]:
    module = ast.parse(source_file.read_text(encoding="utf-8"))
    violations: list[str] = []

    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(
                    _matches_module_name(alias.name, banned_module)
                    for banned_module in banned_modules
                ):
                    violations.append(
                        f"{source_file}:{node.lineno} imports {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if any(
                _matches_module_name(node.module, banned_module)
                for banned_module in banned_modules
            ):
                violations.append(
                    f"{source_file}:{node.lineno} imports from {node.module}"
                )

    return violations


def _find_transport_streaming_imports(source_file: Path) -> list[str]:
    violations = _find_banned_imports(
        source_file,
        banned_modules=(TRANSPORT_STREAMING_MODULE,),
    )
    module = ast.parse(source_file.read_text(encoding="utf-8"))
    for node in ast.walk(module):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "gpt2giga.api.openai"
            and any(alias.name == "streaming" for alias in node.names)
        ):
            violations.append(
                f"{source_file}:{node.lineno} imports streaming from gpt2giga.api.openai"
            )
    return violations


def _find_frontend_route_state_violations(source_file: Path) -> list[str]:
    if source_file.name in FRONTEND_ROUTE_STATE_ALLOWED_FILES:
        return []

    violations: list[str] = []
    for lineno, line in enumerate(
        source_file.read_text(encoding="utf-8").splitlines(), 1
    ):
        for token in FRONTEND_ROUTE_STATE_TOKENS:
            if token in line:
                violations.append(f"{source_file}:{lineno} uses {token}")
    return violations


def test_feature_and_provider_layers_do_not_depend_on_openai_transport_streaming():
    violations: list[str] = []

    for root in RESTRICTED_ROOTS:
        for source_file in root.rglob("*.py"):
            violations.extend(_find_transport_streaming_imports(source_file))

    assert not violations, (
        "Transport-layer SSE helpers leaked into feature/provider layers:\n"
        + "\n".join(violations)
    )


def test_admin_runtime_and_settings_routes_do_not_import_internal_control_plane_details():
    violations: list[str] = []

    for source_file in ADMIN_ROUTE_FILES:
        violations.extend(
            _find_banned_imports(
                source_file,
                banned_modules=ADMIN_ROUTE_BANNED_IMPORTS,
            )
        )

    assert not violations, (
        "Admin route modules must delegate through app-level service facades:\n"
        + "\n".join(violations)
    )


def test_structured_admin_page_folders_keep_query_state_logic_in_state_or_serializers():
    violations: list[str] = []

    for root in FRONTEND_ROUTE_STATE_DIRS:
        for source_file in root.rglob("*.ts"):
            violations.extend(_find_frontend_route_state_violations(source_file))

    assert not violations, (
        "Structured admin page folders should keep query-string parsing in state/"
        "serializers helpers:\n" + "\n".join(violations)
    )
