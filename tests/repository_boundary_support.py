"""Standalone gateway repository boundary assertions."""

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_SOURCE_ROOT = REPO_ROOT / "src/gpt2giga"


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


def assert_gateway_runtime_has_no_extracted_namespace_imports() -> None:
    """Keep gateway runtime code independent from extracted GigaLoom code."""

    violations = [
        violation
        for path in GATEWAY_SOURCE_ROOT.rglob("*.py")
        for violation in _forbidden_harness_imports(path)
    ]
    assert violations == []


def assert_code_workflows_target_root_project() -> None:
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

    assert "- 'src/gpt2giga/**/*.py'" in codeql
    assert "- 'pyproject.toml'" in codeql
    assert "- 'pyproject.toml'" in dependency_review
    assert "- 'docs-site/package-lock.json'" in dependency_review
    assert all("- '!src/gpt2giga/**/*.md'" in workflow for workflow in docker_workflows)


def assert_production_dockerfile_installs_root_gateway() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "uv build --wheel" in dockerfile
    assert "COPY src/ src/" in dockerfile
    assert "COPY --from=builder /app/dist/*.whl /tmp/" in dockerfile
    assert 'pip install --no-cache-dir "${wheel_path}${INSTALL_EXTRAS}"' in dockerfile
    assert "gpt2giga_harness" not in dockerfile
