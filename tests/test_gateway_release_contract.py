"""Release and CI contracts owned by ai-forever/gpt2giga."""

from pathlib import Path

from package_isolation_support import test_workspace_lock_is_current as _check_lock
from workspace_split_contract_support import (
    test_code_workflows_skip_documentation_only_changes as _check_code_workflows,
    test_production_docker_build_remains_gateway_only as _check_gateway_docker,
)


FUTURE_REPOSITORY_OWNER = "ai-forever/gpt2giga"
_OWNED_SUITE_FILES = (
    "test_gateway_artifact_isolation.py",
    "test_gateway_repository_layout.py",
    "test_gateway_release_contract.py",
)


def test_gateway_code_workflows_ignore_documentation_only_changes():
    _check_code_workflows()


def test_gateway_production_docker_build_excludes_gigaloom():
    _check_gateway_docker()


def test_source_workspace_lock_is_current_before_repository_cutover():
    _check_lock()


def test_split_contract_suites_declare_one_future_repository_owner():
    tests_root = Path(__file__).resolve().parent
    for filename in _OWNED_SUITE_FILES:
        source = (tests_root / filename).read_text(encoding="utf-8")
        declarations = [
            line
            for line in source.splitlines()
            if line.startswith("FUTURE_REPOSITORY_OWNER = ")
        ]
        assert len(declarations) == 1, filename
        assert "ai-forever/gpt2giga" in declarations[0], filename
