"""Release and CI contracts owned by ai-forever/gpt2giga."""

from pathlib import Path

from packaging.specifiers import SpecifierSet
import yaml

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from artifact_contract_support import assert_lock_is_current
from repository_boundary_support import (
    assert_code_workflows_target_root_project,
    assert_production_dockerfile_installs_root_gateway,
)


_WORKFLOW_ROOT = Path(__file__).resolve().parents[1] / ".github/workflows"


def test_gateway_code_workflows_target_root_project():
    assert_code_workflows_target_root_project()


def test_production_dockerfile_installs_root_gateway():
    assert_production_dockerfile_installs_root_gateway()


def test_source_lock_is_current():
    assert_lock_is_current()


def test_gateway_resolves_sdk_from_pypi():
    root = _WORKFLOW_ROOT.parents[1]
    with (root / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)
    with (root / "uv.lock").open("rb") as file:
        lock = tomllib.load(file)

    assert "gigachat" not in pyproject["tool"].get("uv", {}).get("sources", {})
    sdk = next(package for package in lock["package"] if package["name"] == "gigachat")
    assert sdk["version"] == "0.2.4a1"
    assert sdk["source"] == {"registry": "https://pypi.org/simple"}
    assert all(
        wheel["url"].startswith("https://files.pythonhosted.org/")
        for wheel in sdk["wheels"]
    )


def test_gateway_ci_has_stable_bounded_required_check_names():
    workflow = (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8")

    assert "Gateway tests / Python ${{ matrix.python-version }}" in workflow
    assert "Gateway package / wheel and sdist" in workflow
    assert "Gateway artifact / Python ${{ matrix.python-version }}" in workflow
    assert "uv build --wheel --sdist --no-sources" in workflow


def test_gateway_ci_selects_the_python_version_it_advertises():
    workflow = yaml.safe_load((_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    for job_name in ("test", "minimum-sdk", "artifact-smoke"):
        job = jobs[job_name]
        assert job["env"]["UV_PYTHON"] == "${{ matrix.python-version }}"
        assert not job.get("continue-on-error", False)
    assert jobs["build"]["env"]["UV_PYTHON"] == "3.13"


def test_gateway_ci_checks_release_branches_without_updating_their_badges():
    workflow = yaml.load(
        (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    for event in ("push", "pull_request"):
        assert workflow["on"][event]["branches"] == ["main", "release/**"]
    badge_commit = next(
        step
        for step in workflow["jobs"]["coverage-badge"]["steps"]
        if step["name"] == "Commit coverage badge on main"
    )
    assert badge_commit["if"] == (
        "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )


def test_gateway_python315_is_installable_and_tested_as_experimental():
    root = _WORKFLOW_ROOT.parents[1]
    with (root / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]
    supported = SpecifierSet(project["requires-python"])
    assert "3.10" in supported
    assert "3.15" in supported
    assert "3.16" not in supported

    workflow = yaml.safe_load((_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["python315-alpha"]
    assert job["env"]["UV_PYTHON"] == "3.15"
    assert job["continue-on-error"] is True
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "uv sync --locked --all-extras --dev" in commands
    assert "uv run --locked pytest tests/" in commands
    assert "uv build --wheel --sdist --no-sources" in commands
    assert "uv venv --python 3.15 .venv-artifact" in commands
    assert "uv pip install --python .venv-artifact/bin/python" in commands
    assert ".venv-artifact/bin/python -I scripts/gateway_artifact_smoke.py" in commands
    assert ".venv-artifact/bin/gpt2giga --help" in commands


def test_gateway_ci_tests_minimum_sdk_from_pypi():
    workflow = (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8")

    assert "Gateway minimum SDK / Python ${{ matrix.python-version }}" in workflow
    assert 'python-version: ["3.10", "3.14"]' in workflow
    assert "uv venv --python ${{ matrix.python-version }} .venv-min-sdk" in workflow
    assert '"gigachat==0.2.4a1" dist/min-sdk/gpt2giga-*.whl' in workflow
    assert "dist/min-sdk/gpt2giga-*.whl" in workflow
    assert "scripts/gateway_artifact_smoke.py" in workflow
    assert '--expected-gigachat-version "0.2.4a1"' in workflow
    assert ".venv-min-sdk/bin/gpt2giga --help" in workflow


def test_gateway_ci_installs_artifact_dependencies_without_global_prerelease_flags():
    workflow = (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8")

    assert "uv build --wheel --no-sources --out-dir dist/smoke" in workflow
    assert (
        "uv pip install --python .venv-artifact/bin/python dist/smoke/gpt2giga-*.whl"
    ) in workflow
    assert "gigachat-0.2.4a1-py3-none-any.whl" not in workflow
    assert "test ! -e gpt2giga" in workflow
    assert ".venv-artifact/bin/python -I scripts/gateway_artifact_smoke.py" in workflow
    assert ".venv-artifact/bin/gpt2giga --help" in workflow
    assert " --pre " not in workflow


def test_gateway_release_workflow_has_one_package_and_one_publish_contract():
    workflow = (_WORKFLOW_ROOT / "publish-pypi.yml").read_text(encoding="utf-8")

    assert "scripts/gateway_release_guard.py" in workflow
    assert "RELEASE_PRERELEASE: ${{ github.event.release.prerelease }}" in workflow
    assert '--release-prerelease "${RELEASE_PRERELEASE}"' in workflow
    assert "--metadata" not in workflow
    assert workflow.count("uv publish ") == 1
    assert workflow.count("secrets.PYPI_API_KEY") == 1
    assert "if: needs.metadata.outputs.mode == 'publish'" in workflow
    assert "name: pypi-gateway" in workflow


def test_gateway_security_and_docs_filters_target_root_metadata():
    codeql = (_WORKFLOW_ROOT / "codeql.yaml").read_text(encoding="utf-8")
    dependency_review = (_WORKFLOW_ROOT / "dependency-review.yaml").read_text(
        encoding="utf-8"
    )
    docs = (_WORKFLOW_ROOT / "docs-pages.yaml").read_text(encoding="utf-8")

    for workflow in (codeql, dependency_review, docs):
        assert "'packages/*/pyproject.toml'" not in workflow
        assert "'pyproject.toml'" in workflow


def test_all_workflow_filters_use_standalone_gateway_paths():
    workflows = {
        path.name: path.read_text(encoding="utf-8")
        for path in _WORKFLOW_ROOT.iterdir()
        if path.suffix in {".yml", ".yaml"}
    }

    assert all("packages/gpt2giga" not in workflow for workflow in workflows.values())
    for path in (
        "'src/gpt2giga/**'",
        "'pyproject.toml'",
        "'uv.lock'",
        "'tests/**'",
        "'scripts/**'",
    ):
        assert path in workflows["ci.yaml"]
    for path in ("'src/gpt2giga/**'", "'Dockerfile'", "'deploy/**'"):
        assert path in workflows["docker-smoke.yaml"]
    for workflow_name in ("docker-smoke.yaml", "docker_image.yaml", "publish-ghcr.yml"):
        assert "'pyproject.toml'" in workflows[workflow_name]
        assert "'gigachat-0.2.4a1-py3-none-any.whl'" not in workflows[workflow_name]
    for path in ("'docs/**'", "'docs-site/**'", "'scripts/check_docs.py'"):
        assert path in workflows["docs-pages.yaml"]
