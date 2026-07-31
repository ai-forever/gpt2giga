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


def test_gateway_release_workflow_has_one_package_and_one_publish_contract():
    workflow = (_WORKFLOW_ROOT / "publish-pypi.yml").read_text(encoding="utf-8")

    assert "scripts/gateway_release_guard.py" in workflow
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
