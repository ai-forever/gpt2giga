"""Gateway-owned repository separation assertions."""

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_MEMBER = REPO_ROOT / "packages/gpt2giga"


def _forbidden_harness_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        for module in modules:
            if module == "gpt2giga_harness" or module.startswith("gpt2giga_harness."):
                forbidden.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
            if module == "gpt2giga.harness" or module.startswith("gpt2giga.harness."):
                forbidden.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return forbidden


def test_gateway_owned_modules_do_not_import_harness() -> None:
    """Keep gateway runtime code independent from extracted GigaLoom code."""

    source_root = GATEWAY_MEMBER / "src/gpt2giga"
    violations = [
        violation
        for path in source_root.rglob("*.py")
        for violation in _forbidden_harness_imports(path)
    ]
    assert violations == []


def test_code_workflows_skip_documentation_only_changes() -> None:
    codeql = (REPO_ROOT / ".github/workflows/codeql.yaml").read_text(encoding="utf-8")
    dependency_review = (
        REPO_ROOT / ".github/workflows/dependency-review.yaml"
    ).read_text(encoding="utf-8")
    docker_workflows = tuple(
        (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in (
            ".github/workflows/docker-smoke.yaml",
            ".github/workflows/docker_image.yaml",
            ".github/workflows/publish-ghcr.yml",
        )
    )

    assert "- 'packages/gpt2giga/**/*.py'" in codeql
    assert "- 'packages/gpt2giga/pyproject.toml'" in codeql
    assert "- 'packages/**/*.py'" not in codeql
    assert "- 'packages/gpt2giga/pyproject.toml'" in dependency_review
    assert "- 'docs-site/package-lock.json'" in dependency_review
    assert all(
        "- '!packages/gpt2giga/**/*.md'" in workflow for workflow in docker_workflows
    )


def test_production_docker_build_remains_gateway_only() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    docker_workflows = "\n".join(
        (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in (
            ".github/workflows/docker-smoke.yaml",
            ".github/workflows/docker_image.yaml",
            ".github/workflows/publish-ghcr.yml",
        )
    )

    assert "uv build --package gpt2giga --wheel" in dockerfile
    assert "COPY packages/gpt2giga/README.md packages/gpt2giga/README.md" in dockerfile
    assert "packages/gpt2giga-harness" not in dockerfile
    assert "gpt2giga_harness" not in dockerfile
    assert "packages/gpt2giga-harness" not in docker_workflows
    assert "- 'uv.lock'" not in docker_workflows
