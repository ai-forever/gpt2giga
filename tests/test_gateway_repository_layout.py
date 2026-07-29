"""Repository layout contracts owned by ai-forever/gpt2giga."""

from pathlib import Path

from workspace_split_contract_support import (
    test_gateway_owned_modules_do_not_import_harness as _check_no_harness_imports,
)


FUTURE_REPOSITORY_OWNER = "ai-forever/gpt2giga"


def test_gateway_owned_modules_do_not_import_gigaloom():
    _check_no_harness_imports()


def test_source_repository_contains_only_the_gateway_workspace_member():
    root = Path(__file__).resolve().parents[1]
    workspace = (root / "pyproject.toml").read_text(encoding="utf-8")

    assert 'members = ["packages/gpt2giga"]' in workspace
    assert not (root / "packages/gpt2giga-harness").exists()
    assert not (root / "tests/harness").exists()
    assert not (root / "examples/harness").exists()
    assert not (root / "benchmarks/harness_p0").exists()
    assert not (root / "benchmarks/harness_p2_5").exists()
