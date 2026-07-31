"""Release and CI contracts owned by ai-forever/gpt2giga."""

from pathlib import Path

from artifact_contract_support import assert_lock_is_current
from repository_boundary_support import (
    assert_code_workflows_skip_documentation_only_changes,
    assert_production_docker_build_remains_gateway_only,
)


_WORKFLOW_ROOT = Path(__file__).resolve().parents[1] / ".github/workflows"
_REMOVED_AUTOMATION_REFERENCES = (
    "packages/gpt2giga-harness",
    "gpt2giga-harness",
    "gpt2giga_harness",
    "giga benchmark",
    "cockpit-v2",
)


def test_gateway_code_workflows_ignore_documentation_only_changes():
    assert_code_workflows_skip_documentation_only_changes()


def test_gateway_production_docker_build_excludes_gigaloom():
    assert_production_docker_build_remains_gateway_only()


def test_source_lock_is_current():
    assert_lock_is_current()


def test_source_workflows_do_not_reference_removed_gigaloom_automation():
    violations = {
        path.name: [
            reference
            for reference in _REMOVED_AUTOMATION_REFERENCES
            if reference in path.read_text(encoding="utf-8").casefold()
        ]
        for path in sorted(_WORKFLOW_ROOT.glob("*.*"))
    }
    assert {path: refs for path, refs in violations.items() if refs} == {}


def test_gateway_ci_has_stable_bounded_required_check_names():
    workflow = (_WORKFLOW_ROOT / "ci.yaml").read_text(encoding="utf-8")

    assert 'python-version: ["3.10", "3.13", "3.14"]' in workflow
    assert "Gateway tests / Python ${{ matrix.python-version }}" in workflow
    assert "Gateway package / wheel and sdist" in workflow
    assert "Gateway artifact / Python ${{ matrix.python-version }}" in workflow
    assert "uv run ruff check ." in workflow
    assert "uv run ruff format --check ." in workflow
    assert "uv build --wheel --sdist --no-sources" in workflow


def test_gateway_release_workflow_has_one_package_and_one_publish_contract():
    workflow = (_WORKFLOW_ROOT / "publish-pypi.yml").read_text(encoding="utf-8")

    assert "scripts/gateway_release_guard.py" in workflow
    assert workflow.count("uv publish ") == 1
    assert workflow.count("secrets.PYPI_API_KEY") == 1
    assert "if: needs.metadata.outputs.mode == 'publish'" in workflow
    assert "Gateway release / protected PyPI upload" in workflow
    assert "needs: [metadata, build]" in workflow
    assert "name: pypi-gateway" in workflow
    assert "Download attested gateway artifacts" in workflow


def test_gateway_security_and_docs_filters_are_member_specific():
    codeql = (_WORKFLOW_ROOT / "codeql.yaml").read_text(encoding="utf-8")
    dependency_review = (_WORKFLOW_ROOT / "dependency-review.yaml").read_text(
        encoding="utf-8"
    )
    docs = (_WORKFLOW_ROOT / "docs-pages.yaml").read_text(encoding="utf-8")

    for workflow in (codeql, dependency_review, docs):
        assert "'packages/*/pyproject.toml'" not in workflow
        assert "'pyproject.toml'" in workflow
