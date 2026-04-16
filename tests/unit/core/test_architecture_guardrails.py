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


def _find_transport_streaming_imports(source_file: Path) -> list[str]:
    module = ast.parse(source_file.read_text(encoding="utf-8"))
    violations: list[str] = []

    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == TRANSPORT_STREAMING_MODULE:
                    violations.append(
                        f"{source_file}:{node.lineno} imports {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module == TRANSPORT_STREAMING_MODULE:
                violations.append(
                    f"{source_file}:{node.lineno} imports from {TRANSPORT_STREAMING_MODULE}"
                )
            elif node.module == "gpt2giga.api.openai" and any(
                alias.name == "streaming" for alias in node.names
            ):
                violations.append(
                    f"{source_file}:{node.lineno} imports streaming from gpt2giga.api.openai"
                )

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
