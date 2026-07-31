"""Release and CI contracts owned by ai-forever/gpt2giga."""

from pathlib import Path

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


def test_gateway_ci_has_stable_bounded_required_check_names():
    workflow = (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8")

    assert "Gateway tests / Python ${{ matrix.python-version }}" in workflow
    assert "Gateway package / wheel and sdist" in workflow
    assert "Gateway artifact / Python ${{ matrix.python-version }}" in workflow
    assert "uv build --wheel --sdist --no-sources" in workflow


def test_gateway_ci_tests_minimum_stable_sdk_from_wheel():
    workflow = (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8")

    assert "Gateway minimum SDK / Python ${{ matrix.python-version }}" in workflow
    assert 'python-version: ["3.10", "3.14"]' in workflow
    assert "uv venv --python ${{ matrix.python-version }} .venv-min-sdk" in workflow
    assert '"gigachat==0.2.3"' in workflow
    assert "dist/min-sdk/gpt2giga-*.whl" in workflow
    assert "scripts/gateway_artifact_smoke.py" in workflow
    assert '--expected-gigachat-version "0.2.3"' in workflow
    assert ".venv-min-sdk/bin/gpt2giga --help" in workflow


def test_gateway_ci_resolves_stable_artifact_dependencies_without_prerelease_flags():
    workflow = (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8")

    assert "uv build --wheel --no-sources --out-dir dist/smoke" in workflow
    assert (
        "uv pip install --python .venv-artifact/bin/python dist/smoke/gpt2giga-*.whl"
    ) in workflow
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
    for path in ("'docs/**'", "'docs-site/**'", "'scripts/check_docs.py'"):
        assert path in workflows["docs-pages.yaml"]
