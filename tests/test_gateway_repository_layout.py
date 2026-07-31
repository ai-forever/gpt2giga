"""Repository layout contracts owned by ai-forever/gpt2giga."""

from pathlib import Path
import subprocess

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from repository_boundary_support import (
    assert_gateway_runtime_has_no_extracted_namespace_imports,
)


def test_gateway_runtime_has_no_extracted_namespace_imports():
    assert_gateway_runtime_has_no_extracted_namespace_imports()


def test_repository_is_a_standalone_gateway_project():
    root = Path(__file__).resolve().parents[1]

    with (root / "pyproject.toml").open("rb") as file:
        metadata = tomllib.load(file)

    tracked_metadata = subprocess.run(
        ["git", "ls-files", "*pyproject.toml"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    project = metadata["project"]
    build_targets = metadata["tool"]["hatch"]["build"]["targets"]

    assert tracked_metadata == ["pyproject.toml"]
    assert project["name"] == "gpt2giga"
    assert project["description"]
    assert project["readme"] == "README.md"
    assert project["scripts"] == {"gpt2giga": "gpt2giga:run"}
    assert build_targets["wheel"]["packages"] == ["src/gpt2giga"]
    assert build_targets["sdist"]["only-include"] == [
        "src",
        "CHANGELOG.md",
        "CHANGELOG_en.md",
    ]
    assert (root / "src/gpt2giga/__init__.py").is_file()
    assert not (root / "packages").exists()
